"""Pull in-network provider listings for one city from insurers' public
CMS-mandated FHIR provider directories (Da Vinci PDex Plan-Net), then
enrich each provider from the federal NPPES NPI registry.

Usage: python3 -I pipeline/fetch.py --city Denver --state CO
Writes data/raw_<city>.json.gz (cached HTTP responses live in .cache/).
"""
import argparse
import gzip
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE = os.path.join(ROOT, ".cache")
HEADERS = {"Accept": "application/fhir+json", "User-Agent": "NowAccepting/0.1 (+https://nowacceptingpatients.com)"}

PAYERS = {
    "cigna": {"name": "Cigna", "base": "https://fhir.cigna.com/ProviderDirectory/v1"},
    "uhc": {"name": "UnitedHealthcare", "base": "https://flex.optum.com/fhirpublic/R4"},
    # Humana's CDN blocks bursts, so it gets few workers and a pause per request.
    "humana": {"name": "Humana", "base": "https://fhir.humana.com/api", "threads": 2, "pause": 0.5},
    "kaiser": {"name": "Kaiser Permanente", "base": "https://kpx-service-bus.kp.org/service/hp/mhpo/healthplanproviderv1rc"},
}

# NUCC taxonomy prefixes we list, mapped to a consumer-facing category.
CATEGORIES = [
    ("2084P0800X", "psychiatrist"),
    ("2084P0804X", "psychiatrist"),
    ("2084", "psychiatrist"),
    ("363LP0808X", "psychiatric-np"),
    ("103T", "psychologist"),
    ("1041C0700X", "therapist"),
    ("1041", "therapist"),
    ("101Y", "therapist"),
    ("106H", "therapist"),
    ("207Q", "primary-care"),
    ("207R00000X", "primary-care"),
    ("208D", "primary-care"),
    ("363LF0000X", "primary-care"),
    ("363LA2200X", "primary-care"),
    ("208000000X", "pediatrician"),
    ("363LP0200X", "pediatrician"),
]


def category_for(code):
    for prefix, cat in CATEGORIES:
        if code and code.startswith(prefix):
            return cat
    return None


class Blocked(Exception):
    """The insurer refused us (403/429). Stop that insurer for this run instead of retrying."""


PAUSE = 0.0  # seconds to wait after each live request (set per insurer)
MIN_KEEP_SHARE = 0.5


def get(url, retries=3):
    key = hashlib.sha1(url.encode()).hexdigest()
    path = os.path.join(CACHE, key + ".json")
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.load(r)
            tmp = f"{path}.{os.getpid()}.tmp"  # atomic: parallel city fetches share the cache
            with open(tmp, "w") as f:
                json.dump(data, f)
            os.replace(tmp, path)
            if PAUSE:
                time.sleep(PAUSE)
            return data
        except urllib.error.HTTPError as e:
            if e.code in (403, 429):
                raise Blocked(f"{e.code} from {url.split('?')[0]}")
            if e.code in (400, 404):
                return {}
            time.sleep(2 * (attempt + 1))
        except Exception:
            time.sleep(2 * (attempt + 1))
    return {}


def paged(url, limit_pages=200):
    out = []
    for _ in range(limit_pages):
        d = get(url)
        out += [e["resource"] for e in d.get("entry", [])]
        nxt = [l["url"] for l in d.get("link", []) if l.get("relation") == "next"]
        if not nxt:
            break
        url = nxt[0]
    return out


def ext(resource, suffix):
    return [e for e in resource.get("extension", []) if e.get("url", "").endswith(suffix)]


def accepting_status(role):
    for e in ext(role, "newpatients"):
        for sub in e.get("extension", []):
            if sub.get("url") == "acceptingPatients":
                code = sub.get("valueCodeableConcept", {}).get("coding", [{}])[0].get("code")
                return {"newpt": "yes", "existptonly": "no", "nopt": "no", "existptfam": "no"}.get(code, "unknown")
    return "unknown"


def npi_of(resource):
    for i in resource.get("identifier", []):
        if "npi" in i.get("system", "").lower() or i.get("type", {}).get("coding", [{}])[0].get("code") == "NPI":
            v = str(i.get("value", "")).strip()
            if len(v) == 10 and v.isdigit():
                return v
    return None


def fetch_payer(key, city, state, max_locations):
    base = PAYERS[key]["base"]
    workers = PAYERS[key].get("threads", 16)
    pause = PAYERS[key].get("pause", 0.0)
    global PAUSE
    PAUSE = pause  # one city per process and insurers run in turn, so a module setting is safe
    q = urllib.parse.urlencode({"address-city": city, "address-state": state, "_count": 100})
    locations = {l["id"]: l for l in paged(f"{base}/Location?{q}", limit_pages=max(1, max_locations // 100))}
    print(f"[{key}] {len(locations)} locations in {city}", file=sys.stderr)

    def roles_at(loc_id):
        found = paged(f"{base}/PractitionerRole?location={loc_id}&_count=100", limit_pages=20)
        if not found:
            found = paged(f"{base}/PractitionerRole?location={urllib.parse.quote(base + '/Location/' + loc_id, safe='')}&_count=100", limit_pages=20)
        return found

    with ThreadPoolExecutor(workers) as pool:
        role_lists = list(pool.map(roles_at, list(locations)))

    roles = []
    for rl in role_lists:
        for r in rl:
            cats = {category_for(c.get("code")) for s in r.get("specialty", []) for c in s.get("coding", [])}
            cats.discard(None)
            if cats:
                roles.append((r, sorted(cats)))
    print(f"[{key}] {len(roles)} relevant practitioner roles", file=sys.stderr)

    # Resolve practitioners (for NPI + name) and network names.
    prac_ids = sorted({r["practitioner"]["reference"].split("/")[-1] for r, _ in roles if r.get("practitioner")})
    with ThreadPoolExecutor(workers) as pool:
        pracs = dict(zip(prac_ids, pool.map(lambda i: get(f"{base}/Practitioner/{i}"), prac_ids)))
    net_ids = sorted({e["valueReference"]["reference"].split("/")[-1]
                      for r, _ in roles for e in ext(r, "network-reference") if e.get("valueReference")})
    with ThreadPoolExecutor(workers) as pool:
        nets = dict(zip(net_ids, pool.map(lambda i: get(f"{base}/Organization/{i}"), net_ids)))

    listings = []
    for r, cats in roles:
        pid = r.get("practitioner", {}).get("reference", "").split("/")[-1]
        prac = pracs.get(pid) or {}
        npi = npi_of(r) or npi_of(prac)
        if not npi:
            continue
        locs = []
        for ref in r.get("location", []):
            loc = locations.get(ref.get("reference", "").split("/")[-1])
            if loc:
                a = loc.get("address", {})
                locs.append({
                    "line": ", ".join(a.get("line", [])),
                    "city": (a.get("city") or "").title(),
                    "state": a.get("state"),
                    "zip": (a.get("postalCode") or "")[:5],
                    "virtual": "VIRTUAL" in " ".join(a.get("line", [])).upper(),
                })
        phones = [t["value"] for t in r.get("telecom", []) if t.get("system") == "phone"]
        networks = sorted({(nets.get(e["valueReference"]["reference"].split("/")[-1]) or {}).get("name", "")
                           for e in ext(r, "network-reference") if e.get("valueReference")} - {""})
        listings.append({
            "payer": key,
            "npi": npi,
            "categories": cats,
            "specialties": sorted({c.get("display") for s in r.get("specialty", []) for c in s.get("coding", []) if c.get("display")}),
            "accepting": accepting_status(r),
            "phone": phones[0] if phones else None,
            "locations": locs,
            "networks": networks,
            "updated": r.get("meta", {}).get("lastUpdated", "")[:10],
            "dir_name": (prac.get("name") or [{}])[0].get("text") if prac else None,
        })
    return listings


def nppes(npi):
    try:
        d = get(f"https://npiregistry.cms.hhs.gov/api/?version=2.1&number={npi}")
    except Blocked:
        return None
    res = (d.get("results") or [None])[0]
    if not res:
        return None
    b = res.get("basic", {})
    loc = next((a for a in res.get("addresses", []) if a.get("address_purpose") == "LOCATION"), {})
    return {
        "first": (b.get("first_name") or "").title(),
        "last": (b.get("last_name") or "").title(),
        "credential": (b.get("credential") or "").replace(".", "").strip(),
        "gender": b.get("sex") or b.get("gender"),
        "status": b.get("status"),
        "nppes_updated": b.get("last_updated"),
        "taxonomies": [t.get("desc") for t in res.get("taxonomies", [])],
        "nppes_phone": loc.get("telephone_number"),
        "nppes_address": loc and f"{loc.get('address_1','')}, {loc.get('city','').title()}, {loc.get('state','')} {loc.get('postal_code','')[:5]}",
    }


def keep_previous(new_count, prior_count):
    """A run that finds under half of last run's listings is a partial pull (an API
    failure or a lower location limit), not providers leaving, so it can't replace them."""
    return new_count == 0 or new_count < prior_count * MIN_KEEP_SHARE


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", default="Denver")
    ap.add_argument("--state", default="CO")
    ap.add_argument("--payers", default=",".join(PAYERS))
    ap.add_argument("--max-locations", type=int, default=1500, help="per insurer; raise for full coverage")
    args = ap.parse_args()
    os.makedirs(CACHE, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "data"), exist_ok=True)

    path = os.path.join(ROOT, "data", f"raw_{args.city.lower().replace(' ', '-')}.json.gz")
    previous = {"listings": [], "registry": {}}
    if os.path.exists(path):
        with gzip.open(path, "rt") as f:
            previous = json.load(f)

    # Merge into the existing file: insurers not in --payers are kept, and an
    # insurer whose API fails or returns nothing keeps last run's listings
    # rather than vanishing from the site.
    listings, fetched = [], set()
    for key in args.payers.split(","):
        try:
            got = fetch_payer(key, args.city, args.state, args.max_locations)
        except Exception as e:
            print(f"[{key}] failed: {e}", file=sys.stderr)
            got = []
        prior = sum(1 for l in previous["listings"] if l["payer"] == key)
        if keep_previous(len(got), prior):
            print(f"[{key}] only {len(got)} listings against {prior} last run; keeping previous listings", file=sys.stderr)
        else:
            listings += got
            fetched.add(key)
    listings += [l for l in previous["listings"] if l["payer"] not in fetched]
    global PAUSE
    PAUSE = 0.0

    npis = sorted({l["npi"] for l in listings})
    todo = [n for n in npis if fetched & {l["payer"] for l in listings if l["npi"] == n} or n not in previous["registry"]]
    print(f"enriching {len(todo)} NPIs from NPPES", file=sys.stderr)
    with ThreadPoolExecutor(8) as pool:
        registry = {n: previous["registry"].get(n) for n in npis}
        registry.update(zip(todo, pool.map(nppes, todo)))

    out = {
        "city": args.city, "state": args.state,
        "generated": time.strftime("%Y-%m-%d"),
        "payers": {k: PAYERS[k]["name"] for k in PAYERS},
        "listings": listings, "registry": registry,
    }
    with gzip.open(path, "wt") as f:
        json.dump(out, f)
    print(f"wrote {path}: {len(listings)} listings, {len(npis)} providers", file=sys.stderr)


if __name__ == "__main__":
    main()
