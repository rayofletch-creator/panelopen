"""Merge raw directory data per provider, score how trustworthy each
"accepting new patients" claim is, and render a static, SEO-first site.

Usage: python3 -I pipeline/build.py --site-url https://nowacceptingpatients.com
Reads data/cities.json and data/raw_<city>.json.gz, writes dist/.
"""
import argparse
import html
import json
import os
import re
import gzip
import importlib.util
import shutil
from collections import defaultdict
from urllib.parse import urlparse
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
BRAND = "Now Accepting"
PAGE_SIZE = 25
MIN_INDEXABLE = 3  # combos with fewer providers are built but noindexed

CATS = {
    "therapist": ("Therapists", "therapist", "Licensed counselors, clinical social workers and marriage & family therapists"),
    "psychologist": ("Psychologists", "psychologist", "Licensed psychologists for therapy, testing and assessment"),
    "psychiatrist": ("Psychiatrists", "psychiatrist", "Medical doctors who diagnose and prescribe for mental health"),
    "psychiatric-np": ("Psychiatric Nurse Practitioners", "psychiatric nurse practitioner", "Nurse practitioners who can prescribe mental health medication"),
    "primary-care": ("Primary Care Doctors", "primary care doctor", "Family medicine, internal medicine and adult primary care"),
    "pediatrician": ("Pediatricians", "pediatrician", "Doctors and nurse practitioners for children and teens"),
}
PAYER_SLUG = {"cigna": "cigna", "uhc": "unitedhealthcare", "humana": "humana", "kaiser": "kaiser-permanente"}

STATE_NAMES = {"CO": "Colorado", "TX": "Texas"}


def e(s):
    return html.escape(str(s or ""), quote=True)


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def digits(s):
    return re.sub(r"\D", "", s or "")[-10:]


def fmt_phone(p):
    d = digits(p)
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else (p or "")


def clip(s, n):
    """Trim to n characters at a word boundary (titles/descriptions Google truncates)."""
    return s if len(s) <= n else s[:n - 1].rsplit(" ", 1)[0].rstrip(",;:—-") + "…"


def fmt_date(s):
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%b %-d, %Y")
    except Exception:
        return s


# ---------------------------------------------------------------- merge ---

def merge(raw, reports):
    by_npi = defaultdict(list)
    for l in raw["listings"]:
        by_npi[l["npi"]].append(l)
    today = datetime.strptime(raw["generated"], "%Y-%m-%d").date()
    # An insurer that marks (nearly) everyone as accepting isn't telling us anything.
    tally = defaultdict(lambda: [0, 0])
    for l in raw["listings"]:
        if l["accepting"] in ("yes", "no"):
            tally[l["payer"]][l["accepting"] == "yes"] += 1
    reliable = {k for k, (no, yes) in tally.items() if no + yes and no / (no + yes) >= 0.02}
    providers = []
    for npi, ls in by_npi.items():
        reg = raw["registry"].get(npi) or {}
        if reg.get("status") and reg["status"] != "A":
            continue  # deactivated NPI: never list
        name = " ".join(x for x in [reg.get("first"), reg.get("last")] if x) or (ls[0].get("dir_name") or "").title()
        if not name:
            continue
        plans = {}
        for l in ls:
            p = plans.setdefault(l["payer"], {"accepting": "unknown", "networks": set(), "updated": "", "phones": set()})
            if l["accepting"] == "yes" or p["accepting"] == "unknown":
                p["accepting"] = l["accepting"] if p["accepting"] != "yes" else "yes"
            p["networks"].update(l["networks"])
            p["updated"] = max(p["updated"], l["updated"] or "")
            if l["phone"]:
                p["phones"].add(digits(l["phone"]))
        locs, seen = [], set()
        for l in ls:
            for loc in l["locations"]:
                k = (loc["line"].upper(), loc["zip"])
                if k not in seen:
                    seen.add(k)
                    locs.append(loc)
        phones = sorted({digits(l["phone"]) for l in ls if l["phone"]} - {""})
        cats = sorted({c for l in ls for c in l["categories"]})
        specs = sorted({s for l in ls for s in l["specialties"]})
        src = sorted({l["src"] for l in ls})

        # ---- verification checks: each is (passed, label) ----
        accepting_payers = [k for k, p in plans.items() if p["accepting"] == "yes"]
        reliable_yes = [k for k in accepting_payers if k in reliable]
        unreliable_yes = [k for k in accepting_payers if k not in reliable]
        if reliable_yes:
            accept_label = "Insurer directory lists them as accepting new patients"
        else:
            names = ", ".join(raw["payers"][k] for k in unreliable_yes)
            accept_label = f"Accepting status unconfirmed — {names} marks almost every provider as accepting"
        refusing_payers = [k for k, p in plans.items() if p["accepting"] == "no"]
        freshest = max((p["updated"] for p in plans.values()), default="")
        try:
            age = (today - datetime.strptime(freshest, "%Y-%m-%d").date()).days
        except Exception:
            age = 9999
        nppes_zip = (reg.get("nppes_address") or "")[-5:]
        checks = [
            (bool(reliable_yes), accept_label),
            (age <= 90, f"Insurer record refreshed in the last 90 days ({fmt_date(freshest)})" if freshest else "Insurer record date unknown"),
            (reg.get("status") == "A", "Active license ID in the federal NPI registry"),
            (bool(nppes_zip) and any(loc["zip"] == nppes_zip for loc in locs), "Office ZIP matches the federal NPI registry"),
            (bool(reg.get("nppes_phone")) and digits(reg.get("nppes_phone")) in phones, "Phone number matches the federal NPI registry"),
            (len(plans) > 1, "Listed by more than one insurer"),
            (not refusing_payers or not accepting_payers, "No conflicting reports between insurers"),
        ]
        # Patient call reports (last 90 days). One person can submit many times, so a
        # positive needs two reports to count, while negatives can only lower the level.
        rep = reports.get(npi) or {}
        good = rep.get("yes", 0) + rep.get("waitlist", 0)
        bad = rep.get("no", 0) + rep.get("oon", 0) + rep.get("wrong", 0)
        if good or bad:
            checks.append((good >= 2 and good > bad, f"Patients reported {good} with openings, {bad} without (last 90 days)"))
        else:
            checks.append((False, "No patient call reports yet"))
        score = sum(1 for ok, _ in checks if ok)
        if not accepting_payers:
            level = "none"
        elif bad >= 2 and bad > good:
            level = "low"
        elif not reliable_yes:
            level = "low" if score < 4 else "medium"
        elif score >= 5:
            level = "high"
        elif score >= 4:
            level = "medium"
        else:
            level = "low"
        providers.append({
            "npi": npi,
            "name": name,
            "credential": reg.get("credential") or "",
            "gender": {"F": "Female", "M": "Male"}.get(reg.get("gender") or "", ""),
            "slug": f"{slugify(name)}-{npi}",
            "cats": cats,
            "specialties": specs,
            "plans": {k: {**v, "networks": sorted(v["networks"]), "phones": sorted(v["phones"])} for k, v in plans.items()},
            "accepting_payers": accepting_payers,
            "locations": locs,
            "telehealth": any(loc["virtual"] for loc in locs),
            "phones": phones,
            "phone": (reg.get("nppes_phone") and digits(reg["nppes_phone"]) in phones and digits(reg["nppes_phone"])) or (phones[0] if phones else ""),
            "checks": checks,
            "score": score,
            "level": level,
            "freshest": freshest,
            "reports": rep,
            "src": src,
        })
    level_rank = {"high": 0, "medium": 1, "low": 2, "none": 3}
    providers.sort(key=lambda p: (level_rank[p["level"]], -p["score"], p["name"]))
    return providers


# ------------------------------------------------------------- template ---

def page(ctx, path, title, desc, body, crumbs=None, jsonld=None, noindex=False):
    url = ctx["site"] + path
    ld = list(jsonld or [])
    if crumbs:
        ld.append({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": i + 1, "name": n, "item": ctx["site"] + h} for i, (n, h) in enumerate(crumbs)]})
    crumb_html = ""
    if crumbs:
        parts = [f'<a href="{h}">{e(n)}</a>' for n, h in crumbs[:-1]] + [f'<span aria-current="page">{e(crumbs[-1][0])}</span>']
        crumb_html = '<nav class="crumbs" aria-label="Breadcrumb">' + '<span aria-hidden="true">/</span>'.join(parts) + "</nav>"
    if '<article class="prose' in body and 'class="side"' not in body:
        body = re.sub(r'(<article class="prose[^"]*">)', lambda m: m.group(1) + '<aside class="side"><h2>Find who’s accepting</h2><p>Search in-network providers by care type, insurance and city.</p><a class="btn btn-lamp" href="/#board">Start a search</a></aside>', body, count=1)
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x)}</script>' for x in ld)
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(clip(desc, 155))}">
<link rel="canonical" href="{e(url)}">
{'<meta name="robots" content="noindex, follow">' if noindex else ''}
<meta property="og:type" content="website">
<meta property="og:site_name" content="{BRAND}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
<meta property="og:image" content="{ctx['site']}/og.png">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:image" content="{ctx['site']}/og.png">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="preload" href="/assets/fonts/archivo.woff2" as="font" type="font/woff2" crossorigin>
<script>document.documentElement.className = "js";</script>
<link rel="stylesheet" href="/assets/site.css">
{f'<meta name="forms-endpoint" content="{e(ctx["forms"])}">' if ctx["forms"] else ''}
{ld_html}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <div class="wrap top-in">
    <a class="logo" href="/"><span class="logo-mark" aria-hidden="true"></span>{BRAND}</a>
    <nav class="top-nav" aria-label="Main">
      <a href="/#cities">Cities</a><a href="/guides/">Guides</a><a href="/how-we-verify/">How we verify</a>
      <a href="/for-providers/" class="top-cta">For providers</a>
    </nav>
  </div>
</header>
<main id="main" class="wrap">
{crumb_html}
{body}
</main>
<footer class="foot"><div class="wrap">
  <div class="crisis"><strong>In crisis?</strong> Call or text <a href="tel:988">988</a> (Suicide &amp; Crisis Lifeline), or call 911 for an emergency.</div>
  <div class="foot-cols">
    <div><p class="foot-lead">In-network providers, with every listing checked against public records.</p></div>
    <div><p class="foot-h">Cities</p>{''.join(f'<a href="{path}">{e(name)}</a>' for name, path in ctx["cities"])}</div>
    <div><p class="foot-h">Insurance</p>{''.join(f'<a href="/insurance/{s}/">{e(ctx["payers"][k])}</a>' for k, s in PAYER_SLUG.items() if k in ctx["active_payers"])}</div>
    <div><p class="foot-h">{BRAND}</p><a href="/guides/">Guides</a><a href="/how-we-verify/">How we verify</a><a href="/reports/">Directory accuracy reports</a><a href="/for-providers/">Claim your profile</a><a href="/about/">About &amp; disclosures</a><a href="/privacy/">Privacy</a></div>
  </div>
  <p class="foot-note">Listings are informational and not a guarantee of coverage or availability. Always confirm network status with your insurer and the provider before booking. Data last refreshed {fmt_date(ctx["generated"])}.</p>
</div></footer>
<script src="/assets/app.js" defer></script>
</body>
</html>
"""
    base = ctx["base"]
    if base:  # site served from a sub-path, e.g. https://user.github.io/repo/
        for attr in ('href="/', 'src="/', 'action="/', 'value="/'):
            doc = doc.replace(attr, attr[:-1] + base + "/")
    out = os.path.join(DIST, path.strip("/"), "index.html") if path.endswith("/") else os.path.join(DIST, path.strip("/"))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        f.write(doc)
    if not noindex:
        ctx["sitemap"].append(path)


LEVEL_LABEL = {"high": "High confidence", "medium": "Medium confidence", "low": "Call to confirm", "none": "Not accepting"}


def payer_names(ctx, keys):
    return [ctx["payers"][k] for k in keys]


def tidy_address(line):
    """Insurer feeds often shout: 121 S MADISON ST # C -> 121 S Madison St # C."""
    if line != line.upper():
        return line
    keep = {"N", "S", "E", "W", "NE", "NW", "SE", "SW", "PO", "II", "III", "IV"}
    return " ".join(w if w in keep or not w[0].isalpha() and not w[-1].isalpha() else (w.capitalize() if w[0].isalpha() else w.lower()) for w in line.split())


def pips(score, total=8, cls=""):
    bars = "".join(f'<i class="{"on" if i < score else ""}"></i>' for i in range(total))
    return f'<span class="pips{cls}" role="img" aria-label="{score} of {total} checks passed">{bars}</span>'


def score_tag(p):
    return f'<span class="score score-{p["level"]}" title="{p["score"]} of {len(p["checks"])} checks passed">{pips(p["score"], len(p["checks"]))}{LEVEL_LABEL[p["level"]]}</span>'


def provider_sample():
    """An obviously generic preview of a claimed profile; no real provider implied."""
    return f"""<aside class="sample" data-ui aria-label="Example of a claimed profile">
<p class="sample-tag">Example profile</p>
<p class="sample-name">Your Name, LCSW</p>
<p class="muted">Therapist · Your city</p>
<p class="status"><span class="lamp" aria-hidden="true"></span>Accepting new patients</p>
<p>{pips(7)} <span class="score score-high">High confidence</span> <span class="confirmed">Confirmed by provider</span></p>
<span class="btn" aria-hidden="true">Book or call</span>
</aside>"""


def card(ctx, p):
    accepting = payer_names(ctx, p["accepting_payers"])
    loc = p["locations"][0] if p["locations"] else None
    where = "Telehealth only" if loc and loc["virtual"] and len(p["locations"]) == 1 else (f'{e(tidy_address(loc["line"]))}, {e(loc["city"])} {e(loc["zip"])}' if loc else "")
    data = {
        "ins": " ".join(PAYER_SLUG[k] for k in p["accepting_payers"]),
        "cat": " ".join(p["cats"]), "g": p["gender"][:1].lower(), "tele": "1" if p["telehealth"] else "0",
        "lvl": p["level"], "zip": " ".join(sorted({l["zip"] for l in p["locations"]})),
    }
    attrs = " ".join(f'data-{k}="{e(v)}"' for k, v in data.items())
    phone = f'<a class="btn btn-call" href="tel:+1{p["phone"]}">Call {fmt_phone(p["phone"])}</a>' if p["phone"] else ""
    cats = ", ".join(CATS[c][1].capitalize() for c in p["cats"])
    return f"""<li class="card" {attrs}>
  <div class="card-main">
    <h2><a href="/provider/{p['slug']}/">{e(p['name'])}{', ' + e(p['credential']) if p['credential'] else ''}</a></h2>
    <p class="card-sub">{e(cats)}{' · Telehealth' if p['telehealth'] else ''}</p>
    <p class="card-ins"><span class="lamp" aria-hidden="true"></span><span>Listed as accepting with <strong>{e(', '.join(accepting))}</strong></span></p>
    <div class="card-foot">{score_tag(p)}<p class="card-loc muted">{where}{' · +' + str(len(p['locations']) - 1) + ' more' if len(p['locations']) > 1 else ''}</p></div>
  </div>
  <div class="card-act">{phone}<a class="btn btn-ghost" href="/provider/{p['slug']}/">Details</a></div>
</li>"""


def example_zip(providers):
    zips = defaultdict(int)
    for p in providers:
        for l in p["locations"]:
            if l["zip"] and not l["virtual"]:
                zips[l["zip"]] += 1
    return max(zips, key=zips.get) if zips else "80206"


def filters(ctx, providers, fixed_cat=None, fixed_ins=None):
    ins_opts = "".join(f'<option value="{PAYER_SLUG[k]}">{e(ctx["payers"][k])}</option>' for k in PAYER_SLUG if k in ctx["active_payers"])
    cat_opts = "".join(f'<option value="{c}">{e(CATS[c][0])}</option>' for c in CATS)
    return f"""<form class="filters" data-filters aria-label="Filter results">
  {'' if fixed_ins else f'<label>Insurance<select name="ins"><option value="">Any insurance</option>{ins_opts}</select></label>'}
  {'' if fixed_cat else f'<label>Type of care<select name="cat"><option value="">Any</option>{cat_opts}</select></label>'}
  <label>ZIP<input name="zip" inputmode="numeric" maxlength="5" placeholder="e.g. {example_zip(providers)}"></label>
  <label>Gender<select name="g"><option value="">Any</option><option value="f">Female</option><option value="m">Male</option></select></label>
  <label class="check"><input type="checkbox" name="tele"> Telehealth</label>
  <label class="check"><input type="checkbox" name="hi"> High confidence only</label>
  <p class="filter-count" aria-live="polite" data-count></p>
</form>"""


def faq_block(items):
    ld = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
        {"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in items]}
    body = '<section class="faq"><h2>Common questions</h2>' + "".join(
        f"<details><summary>{e(q)}</summary><p>{e(a)}</p></details>" for q, a in items) + "</section>"
    return body, ld


def monetization_slot(ctx, ins_key=None, cat=None):
    """Clearly labelled referral block for when local openings are thin. Affiliate links
    are configured in data/partners.json; nothing renders until a partner is added."""
    partners = [p for p in ctx["partners"] if (not ins_key or ins_key in p["insurers"]) and (not cat or cat in p["cats"])]
    if not partners:
        return ""
    items = "".join(f'<li><a href="{e(p["url"])}" rel="sponsored noopener" target="_blank">{e(p["name"])}</a> <span class="muted">{e(p["blurb"])}</span></li>' for p in partners)
    return f'<aside class="partner"><p class="tag">Partner · we may earn a referral fee</p><h2>No luck locally? Telehealth options that take insurance</h2><ul>{items}</ul></aside>'


def insights(ctx, acc, fixed_cat=None, fixed_ins=None):
    """'At a glance' facts computed from this page's own listings, so every
    listing page carries content no other page has."""
    if len(acc) < MIN_INDEXABLE:
        return ""
    n = len(acc)
    pct = lambda k: f"{round(100 * k / n)}%"
    hi = sum(1 for p in acc if p["level"] == "high")
    tele = sum(1 for p in acc if p["telehealth"])
    fem = sum(1 for p in acc if p["gender"] == "Female")
    male = sum(1 for p in acc if p["gender"] == "Male")
    fresh = sum(1 for p in acc if p["checks"][1][0])
    multi = sum(1 for p in acc if len(p["accepting_payers"]) > 1)
    zips = defaultdict(int)
    for p in acc:
        for z in {l["zip"] for l in p["locations"] if not l["virtual"] and l["zip"]}:
            zips[z] += 1
    top = sorted(zips.items(), key=lambda x: -x[1])[:6]
    facts = [
        f"<li><strong>{hi} of {n}</strong> ({pct(hi)}) pass enough cross-checks for high confidence — call these first.</li>",
        f"<li><strong>{pct(fresh)}</strong> had their insurer record refreshed in the last 90 days.</li>",
    ]
    if tele:
        facts.append(f"<li><strong>{tele}</strong> list a telehealth or virtual-visit location.</li>")
    if fem or male:
        facts.append(f"<li><strong>{fem}</strong> are women and <strong>{male}</strong> are men, per the federal NPI registry.</li>")
    if not fixed_ins:
        split = ", ".join(f"{ctx['payers'][k]} {sum(1 for p in acc if k in p['accepting_payers'])}" for k in ctx["active_payers"])
        facts.append(f"<li>Accepting by insurer: {e(split)}. <strong>{multi}</strong> are listed as accepting by more than one insurer.</li>")
    if not fixed_cat:
        split = ", ".join(f"{CATS[c][0].lower()} {sum(1 for p in acc if c in p['cats'])}" for c in CATS if any(c in p["cats"] for p in acc))
        facts.append(f"<li>By type of care: {e(split)}.</li>")
    if top:
        facts.append("<li>Most listings by ZIP: " + ", ".join(f"{z} ({k})" for z, k in top) + ".</li>")
    return f'<section class="glance"><h2>At a glance</h2><ul>{"".join(facts)}</ul><p class="muted small">Computed from insurer directories and the NPI registry on {fmt_date(ctx["generated"])}.</p></section>'


def list_scope(ctx, base_path):
    """Attributes telling app.js which full list a paginated page belongs to."""
    parts = base_path.strip("/").split("/")
    if parts[0] == "insurance":
        return f'data-scope="{ctx["base"]}/data/all.json" data-fins="{e(parts[1])}"'
    st, rest = parts[0], parts[1:]
    attrs = [f'data-scope="{ctx["base"]}/data/{e(st)}.json"']
    if "telehealth" in rest:
        attrs.append('data-ftele="1"')
        rest = [x for x in rest if x != "telehealth"]
    if rest and rest[-1] in PAYER_SLUG.values():
        attrs.append(f'data-fins="{e(rest.pop())}"')
    if rest and rest[-1] in CATS:
        attrs.append(f'data-fcat="{e(rest.pop())}"')
    if rest:
        attrs.append(f'data-src="/{e(st)}/{e(rest[0])}/"')
    return " ".join(attrs)


def lamp_html(row):
    hi, med, low = row[:3]
    return "".join(f'<i class="{c}" style="--n:{min(i, 120)}"></i>' if c == "h" else f'<i class="{c}"></i>' for i, c in enumerate(["h"] * hi + ["m"] * med + ["l"] * low))


def first_calls_html(board, row):
    items = ""
    for i in row[3]:
        slug, name, phone, kind = board["people"][i]
        items += f'<li><a href="/provider/{e(slug)}/"><strong>{e(name)}</strong><span>{e(kind)} · {fmt_phone(phone) if phone else "No phone listed"}</span></a></li>'
    return items


def write_board_data(ctx, providers):
    """Counts and first three calls for every city x care type x insurer, for the home switchboard."""
    listed = [p for p in providers if p["level"] != "none"]
    people, index, keys = [], {}, {}
    for name, path in ctx["cities"]:
        in_city = [p for p in listed if path in p["src"]]
        for c in CATS:
            in_cat = [p for p in in_city if c in p["cats"]]
            for k in [""] + list(ctx["active_payers"]):
                ps = [p for p in in_cat if not k or k in p["accepting_payers"]]
                counts = [sum(1 for p in ps if p["level"] == lv) for lv in ("high", "medium", "low")]
                top = []
                for p in [q for q in ps if q["phone"] and q["level"] in ("high", "medium")][:3]:
                    if p["npi"] not in index:
                        index[p["npi"]] = len(people)
                        full = p["name"] + (", " + p["credential"] if p["credential"] else "")
                        people.append([p["slug"], full, p["phone"], CATS[p["cats"][0]][1].capitalize()])
                    top.append(index[p["npi"]])
                keys[f"{path}|{c}|{PAYER_SLUG[k] if k else ''}"] = counts + [top]
    board = {"people": people, "keys": keys, "plural": {c: v[0] for c, v in CATS.items()},
             "cities": {path: name.split(",")[0] for name, path in ctx["cities"]},
             "payers": {PAYER_SLUG[k]: ctx["payers"][k] for k in ctx["active_payers"]}}
    os.makedirs(os.path.join(DIST, "data"), exist_ok=True)
    with open(os.path.join(DIST, "data", "board.json"), "w") as f:
        json.dump(board, f, separators=(",", ":"))
    return board


def write_search_data(ctx, providers):
    """Compact listings per state, loaded only when someone filters a long list."""
    slug_of = PAYER_SLUG
    rows = []
    for p in providers:
        if p["level"] == "none":
            continue
        loc = p["locations"][0] if p["locations"] else None
        where = "Telehealth only" if loc and loc["virtual"] and len(p["locations"]) == 1 else (f'{tidy_address(loc["line"])}, {loc["city"]} {loc["zip"]}' if loc else "")
        if len(p["locations"]) > 1:
            where += f' · +{len(p["locations"]) - 1} more'
        rows.append({"s": p["slug"], "n": p["name"], "c": p["credential"], "d": int(p["npi"]) % 5, "t": p["cats"], "h": 1 if p["telehealth"] else 0,
                     "i": [slug_of[k] for k in p["accepting_payers"]], "l": p["level"], "k": p["score"], "p": p["phone"], "w": where,
                     "a": sorted({l["zip"] for l in p["locations"]}), "g": p["gender"][:1].lower(), "f": p["src"]})
    meta = {"cats": {c: v[1].capitalize() for c, v in CATS.items()}, "levels": LEVEL_LABEL,
            "payers": {PAYER_SLUG[k]: ctx["payers"][k] for k in ctx["active_payers"]}}
    os.makedirs(os.path.join(DIST, "data"), exist_ok=True)
    states = {path.split("/")[1] for r in rows for path in r["f"]}
    for st in states:
        with open(os.path.join(DIST, "data", f"{st}.json"), "w") as f:
            json.dump({**meta, "providers": [r for r in rows if any(path.startswith(f"/{st}/") for path in r["f"])]}, f, separators=(",", ":"))
    with open(os.path.join(DIST, "data", "all.json"), "w") as f:
        json.dump({**meta, "providers": rows}, f, separators=(",", ":"))


def listing_pages(ctx, base_path, crumbs, h1, intro, title, desc, providers, faq=None, fixed_cat=None, fixed_ins=None, extra_links=""):
    acc = [p for p in providers if p["level"] != "none"]
    pages = max(1, (len(acc) + PAGE_SIZE - 1) // PAGE_SIZE)
    noindex = len(acc) < MIN_INDEXABLE
    hi = sum(1 for p in acc if p["level"] == "high")
    for i in range(pages):
        chunk = acc[i * PAGE_SIZE:(i + 1) * PAGE_SIZE]
        path = base_path if i == 0 else f"{base_path}page/{i + 1}/"
        pager = ""
        if pages > 1:
            links = []
            if i > 0:
                links.append(f'<a href="{base_path if i == 1 else f"{base_path}page/{i}/"}" rel="prev">← Previous</a>')
            links.append(f"<span>Page {i + 1} of {pages}</span>")
            if i < pages - 1:
                links.append(f'<a href="{base_path}page/{i + 2}/" rel="next">Next →</a>')
            pager = '<nav class="pager" aria-label="Pages">' + "".join(links) + "</nav>"
        faq_html, faq_ld = faq_block(faq) if faq and i == 0 else ("", None)
        stats = f"""<div class="stats"><div><strong>{len(acc)}</strong><span>accepting new patients</span></div><div><strong>{hi}</strong><span>high confidence</span></div><div><strong>{fmt_date(ctx['generated'])}</strong><span>last refreshed</span></div></div>"""
        items = "".join(card(ctx, p) for p in chunk) or '<li class="empty">No providers in this view are currently listed as accepting new patients. Try a nearby category or insurer below.</li>'
        item_ld = {"@context": "https://schema.org", "@type": "ItemList", "itemListElement": [
            {"@type": "ListItem", "position": i * PAGE_SIZE + n + 1, "url": ctx["site"] + f"/provider/{p['slug']}/", "name": p["name"]} for n, p in enumerate(chunk)]}
        body = f"""<header class="hero-sm"><h1>{e(h1)}{'' if i == 0 else f' — page {i + 1}'}</h1><p class="lede">{intro}</p>{stats}</header>
{filters(ctx, acc, fixed_cat, fixed_ins)}
<ol class="cards" data-list start="{i * PAGE_SIZE + 1}"{(" " + list_scope(ctx, base_path)) if pages > 1 else ""}>{items}</ol>
<p class="noresults" data-noresults hidden>No matches on this page. Clear a filter or try the next page.</p>
{pager}
{insights(ctx, acc, fixed_cat, fixed_ins) if i == 0 else ''}
{monetization_slot(ctx, next((k for k, s in PAYER_SLUG.items() if s == fixed_ins), None), fixed_cat) if i == 0 else ''}
{extra_links if i == 0 else ''}
{link_grid("Before you call", [(t, p, "") for t, p in GUIDE_LINKS]) if i == 0 else ''}
{faq_html}"""
        page(ctx, path, title if i == 0 else f"{title} — Page {i + 1}", desc, body, crumbs, [item_ld] + ([faq_ld] if faq_ld else []), noindex=noindex or i > 0)
    return len(acc)


def state_crumb(city_path):
    st = city_path.split("/")[1].upper()
    return (STATE_NAMES.get(st, st), f"/{st.lower()}/")


def link_grid(title, links):
    if not links:
        return ""
    return f'<section class="links">{f"<h2>{e(title)}</h2>" if title else ""}<ul>' + "".join(f'<li><a href="{h}">{e(n)}</a> <span class="muted">{c}</span></li>' for n, h, c in links) + "</ul></section>"


def provider_page(ctx, p, city_path, city, peers=()):
    cats = ", ".join(CATS[c][1] for c in p["cats"])
    rows = ""
    for k, pl in sorted(p["plans"].items(), key=lambda x: x[1]["accepting"] != "yes"):
        status = {"yes": ("Accepting new patients", "ok"), "no": ("Not accepting new patients", "no"), "unknown": ("Not stated", "unk")}[pl["accepting"]]
        nets = ", ".join(pl["networks"][:6]) + (f" +{len(pl['networks']) - 6} more" if len(pl["networks"]) > 6 else "")
        rows += f'<tr><th scope="row"><a href="/insurance/{PAYER_SLUG[k]}/">{e(ctx["payers"][k])}</a></th><td data-label="New patients"><span class="pill pill-{status[1]}">{status[0]}</span></td><td class="muted" data-label="Networks / plans">{e(nets.title()) or "—"}</td><td class="muted" data-label="Insurer updated">{fmt_date(pl["updated"])}</td></tr>'
    checks = "".join(f'<li class="{"ok" if ok else "no"}"><i aria-hidden="true"></i><span class="vh">{"Passed: " if ok else "Not passed: "}</span> {e(label)}</li>' for ok, label in p["checks"])
    locs = "".join(f'<li>{"Telehealth / virtual visits" if l["virtual"] else e(tidy_address(l["line"])) + ", " + e(l["city"]) + ", " + e(l["state"]) + " " + e(l["zip"])}</li>' for l in p["locations"][:8])
    full = p["name"] + (", " + p["credential"] if p["credential"] else "")
    phys = any(c in ("psychiatrist", "primary-care", "pediatrician") for c in p["cats"]) and p["credential"] in ("MD", "DO")
    ld = {
        "@context": "https://schema.org", "@type": "Physician" if phys else "MedicalBusiness",
        "name": full, "url": ctx["site"] + f"/provider/{p['slug']}/",
        "identifier": {"@type": "PropertyValue", "propertyID": "NPI", "value": p["npi"]},
        "medicalSpecialty": p["specialties"][:5],
        "isAcceptingNewPatients": bool(p["accepting_payers"]),
        "paymentAccepted": ", ".join(payer_names(ctx, p["accepting_payers"])),
    }
    if p["phone"]:
        ld["telephone"] = "+1" + p["phone"]
    phys_loc = next((l for l in p["locations"] if not l["virtual"]), None)
    if phys_loc:
        ld["address"] = {"@type": "PostalAddress", "streetAddress": phys_loc["line"], "addressLocality": phys_loc["city"], "addressRegion": phys_loc["state"], "postalCode": phys_loc["zip"], "addressCountry": "US"}
    call = f'<a class="btn btn-call btn-lg" href="tel:+1{p["phone"]}">Call {fmt_phone(p["phone"])}</a>' if p["phone"] else ""
    accepting = ", ".join(payer_names(ctx, p["accepting_payers"]))
    script = f"Hi, I found {p['name']} listed as in-network with my {accepting or 'insurance'} plan. Are they accepting new patients, and what's the wait for a first appointment?"
    body = f"""<article class="prov">
<header class="prov-head">
  <div class="prov-id">
    <div>
    <h1>{e(full)}</h1>
    <p class="lede">{e(cats.capitalize())} in {e(city)}{' · Offers telehealth' if p['telehealth'] else ''}{' · ' + e(p['gender']) if p['gender'] else ''}</p>
    <p class="score-line" style="margin:0">{score_tag(p)}</p>
    </div>
  </div>
  <div class="prov-cta">{call}<a class="btn btn-ghost" href="/report/?npi={p['npi']}">I called — report what happened</a></div>
</header>
<section class="panel"><h2>Insurance & new-patient status</h2>
<div class="table-wrap"><table><thead><tr><th>Insurer</th><th>New patients</th><th>Networks / plans</th><th>Insurer updated</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted small">Status comes from each insurer's public provider directory, which federal rules require them to publish. Plans within one insurer can differ — confirm your specific plan.</p></section>
<div class="two">
<section class="panel"><h2>How complete is this listing's data?</h2><ul class="checks">{checks}</ul><p class="small"><a href="/how-we-verify/">How the confidence score works</a></p></section>
<section class="panel"><h2>Where they practice</h2><ul class="plain">{locs}</ul>
<h3>Before you call</h3><p class="script" data-copy>{e(script)}</p><button class="btn btn-ghost btn-sm" type="button" data-copy-btn>Copy script</button></section>
</div>
<section class="panel"><h2>Specialties on record</h2><p>{e(', '.join(p['specialties']))}</p><p class="muted small">NPI {p['npi']} · <a href="https://npiregistry.cms.hhs.gov/provider-view/{p['npi']}" rel="nofollow noopener" target="_blank">View federal NPI record</a></p></section>
{related(ctx, p, city_path, city, peers)}
<aside class="claim"><div><h2>Are you {e(p['name'])}?</h2><p>Confirm your availability in 30 seconds so patients stop calling when you're full — and get a booking link on this page. Or <a href="/for-providers/badge/?p={p['slug']}">add a badge to your website</a>.</p></div><a class="btn" href="/for-providers/?npi={p['npi']}">Claim this profile</a></aside>
</article>"""
    desc = f"{full} — {cats} in {city}. " + (f"Listed as accepting new patients with {accepting}. " if accepting else "") + f"Confidence: {LEVEL_LABEL[p['level']].lower()}."
    short = p["name"] + (", " + re.split(r"[ ,]", p["credential"])[0] if p["credential"] else "")
    title = f"{short} — {cats.split(',')[0].title()} in {city}"
    if accepting and len(title) + len(accepting) + 9 <= 62:
        title += f" | Takes {accepting}"
    crumbs = [("Home", "/"), state_crumb(city_path), (city, city_path), (CATS[p["cats"][0]][0], f"{city_path}{p['cats'][0]}/"), (p["name"], f"/provider/{p['slug']}/")]
    page(ctx, f"/provider/{p['slug']}/", title, desc, body, crumbs, [ld], noindex=p["level"] in ("none", "low"))


def related(ctx, p, city_path, city, peers):
    """Similar providers plus the listing pages this profile belongs to."""
    cat = p["cats"][0]
    payer = (p["accepting_payers"] or list(p["plans"]))[0]
    plural = CATS[cat][0]
    items = "".join(
        f'<li><a href="/provider/{q["slug"]}/">{e(q["name"])}{", " + e(q["credential"]) if q["credential"] else ""}</a> '
        f'<span class="muted">{LEVEL_LABEL[q["level"]]}</span></li>' for q in peers)
    hub = (f'<p><a href="{city_path}{cat}/{PAYER_SLUG[payer]}/">All {e(plural.lower())} in {e(city)} taking {e(ctx["payers"][payer])}</a>'
           f' · <a href="{city_path}{cat}/">All {e(plural.lower())} in {e(city)}</a> · <a href="{city_path}">Everything in {e(city)}</a></p>')
    if not items:
        return f'<section class="panel"><h2>Keep looking</h2>{hub}</section>'
    return (f'<section class="panel"><h2>Other {e(plural.lower())} in {e(city)} taking {e(ctx["payers"][payer])}</h2>'
            f'<ul class="plain">{items}</ul>{hub}</section>')


def pay_button(ctx, plan, label, cls):
    """Stripe Payment Link when configured (data/payments.json), else the free claim form."""
    link = ctx["payments"].get(plan)
    if link:
        return f'<a class="{cls}" href="{e(link)}" data-pay rel="noopener">{label}</a>'
    return f'<a class="{cls}" href="?plan={plan}#claim">{label}</a>'


def static_pages(ctx, city_path, city):
    page(ctx, "/how-we-verify/", f"How We Verify Provider Listings | {BRAND}",
         "Where our in-network and accepting-new-patients data comes from, and how each listing's confidence score is calculated.",
         f"""<article class="prose"><h1>How we verify listings</h1>
<p class="lede">Insurer directories are notoriously wrong. In a U.S. Senate secret-shopper study of Medicare Advantage plans, 80% of the mental health listings checked were inaccurate or unreachable. We can't fix that alone, but we can show you which listings are most likely to be real.</p>
<h2>Where the data comes from</h2>
<ul><li><strong>Insurer provider directories.</strong> Federal interoperability rules require insurers to publish their directories as open data. We pull each insurer's in-network status and its "accepting new patients" flag directly.</li>
<li><strong>The federal NPI registry (NPPES).</strong> Every U.S. provider has a National Provider Identifier. We use it to confirm the provider is active and to cross-check their address and phone.</li>
<li><strong>Patient reports.</strong> When you call a provider, tell us what happened. Two or more recent reports of openings add a point; repeated reports of no openings drop a listing to low confidence.</li>
<li><strong>Provider confirmations.</strong> Providers who claim their profile can confirm availability directly.</li></ul>
<h2>The confidence score</h2><p>Each listing gets one point for each check it passes:</p>
<ol><li>An insurer lists them as accepting new patients</li><li>The insurer's record was refreshed in the last 90 days</li><li>Their NPI is active in the federal registry</li><li>Their office ZIP matches the federal registry</li><li>Their phone number matches the federal registry</li><li>More than one insurer lists them</li><li>Insurers don't contradict each other</li><li>Recent patient call reports confirm openings</li></ol>
<p><strong>High confidence</strong> = 5+ checks. <strong>Medium</strong> = 4. <strong>Low</strong> (shown as "Call to confirm") = 3 or fewer. The score rates the listing's public data, not the provider's quality of care. Listings that no insurer marks as accepting are never shown in "accepting" results.</p>
<p>Some insurers mark nearly every provider as accepting new patients. When an insurer's directory does that, its "accepting" flag doesn't earn a point, and those listings can't reach high confidence unless other checks back them up.</p>
<h2>What we don't do</h2><p>We don't sell rankings. Sponsored and partner placements are always labelled, and never change a provider's confidence score or order within results.</p></article>""",
         [("Home", "/"), ("How we verify", "/how-we-verify/")])
    page(ctx, "/for-providers/", f"For Providers: Claim Your Profile | {BRAND}",
         "Stop fielding calls when your panel is full. Claim your free profile, confirm availability and add a booking link.",
         f"""<section class="bleed prov-hero"><div class="wrap prov-hero-in">
<div>
<h1>Your name is already in the directories.</h1>
<p class="lede">They can say you’re open when you’re full, or hide you when you have room. Claim your free profile and show patients your real availability.</p>
<div class="band-actions"><a class="btn btn-lamp btn-lg" href="?plan=free#claim">Claim your free profile</a><a class="btn btn-line btn-lg" href="#plans">See plans</a></div></div>
{provider_sample()}
</div></section>
<section class="chapter" style="padding-top:clamp(56px,7vw,96px)">
<div class="sec-head rise"><h2>A listing you’d be glad to share</h2><p>Built to respect your time and your name.</p></div>
<div class="values">
<div class="rise"><h3>Fewer calls you can’t take</h3><p>When you confirm you’re full, patients can see that before they pick up the phone. When you have openings, they can see that too.</p></div>
<div class="rise"><h3>Your status, in your hands</h3><p>Claim your listing, correct what’s out of date and mark it provider-confirmed, without an insurer portal or a form for each plan.</p></div>
<div class="rise"><h3>A score you can trust</h3><p>Our checks rate a listing’s public data, never your quality of care. Paying doesn’t change your score, and any sponsored placement is labelled.</p></div>
</div>
<p class="source-note">Keeping directories current is a real cost: in a <a href="https://www.prnewswire.com/news-releases/caqh-survey-maintaining-provider-directories-costs-us-physician-practices-2-76-billion-annually-300957624.html" rel="nofollow noopener" target="_blank">2019 CAQH survey</a>, practices reported spending about $1,000 a month on it. A Now Accepting profile doesn’t update your insurers’ directories, but it gives patients one accurate place to check.</p>
</section>
<section class="chapter" id="plans"><div class="sec-head rise"><h2>Plans</h2><p>Claiming and correcting your listing is free. Paid plans add booking links, insights and tools for groups.</p></div>
<div class="tiers">
<div class="tier"><h2>Free</h2><p class="price">$0</p><ul><li>Claim and correct your listing</li><li>Toggle "accepting new patients"</li><li>Shown as provider-confirmed</li></ul><a class="btn btn-ghost" href="?plan=free#claim">Claim free</a></div>
<div class="tier tier-main"><h2>Practice Pro</h2><p class="price">$39<span>/mo</span></p><p class="tag" style="margin:10px 0 0">Most popular</p><ul><li>Everything in Free</li><li>Online booking or intake link</li><li>Weekly opening counts & waitlist</li><li>Patient call analytics</li><li>Directory-error alerts across insurers</li></ul>""" + pay_button(ctx, "pro", "Start 30-day trial", "btn") + """</div>
<div class="tier"><h2>Group</h2><p class="price">$149<span>/mo</span></p><ul><li>Up to 15 clinicians</li><li>Group page & intake routing</li><li>Bulk availability updates</li><li>Labelled featured placement</li></ul>""" + pay_button(ctx, "group", "Subscribe", "btn btn-ghost") + """</div>
</div>
""" + (f'<p class="muted small">Already subscribed? <a href="{e(ctx["payments"]["portal"])}" rel="noopener">Manage your plan or cancel</a>.</p>' if ctx["payments"].get("portal") else "") + """</section>
<section class="panel claim-panel" id="claim"><div><h2>Claim your profile</h2><form class="stack" data-form><input type="hidden" name="kind" value="claim"><input type="hidden" name="plan" data-plan value="free"><div class="hp" aria-hidden="true"><label>Website<input name="website" tabindex="-1" autocomplete="off"></label></div><label>NPI number<input name="npi" inputmode="numeric" maxlength="10" required></label><label>Work email<input type="email" name="email" required></label><button class="btn" type="submit">Send verification</button><p class="muted small" data-form-msg>We verify ownership by contacting the phone or email on your NPI record.</p></form></div><div class="claim-next"><h3>What happens next</h3><ol><li>We contact the phone or email on your NPI record to confirm it’s you.</li><li>You confirm your availability and correct your details.</li><li>Your listing shows as confirmed by the provider.</li></ol></div></section>""",
         [("Home", "/"), ("For providers", "/for-providers/")])
    snippet = lambda v: e(f'<a href="{ctx["site"]}/"><img src="{ctx["site"]}/assets/badge-{v}.svg" alt="Find us on Now Accepting" width="200" height="56"></a>')
    page(ctx, "/for-providers/badge/", f"Add a Now Accepting Badge to Your Website | {BRAND}",
         "A free badge for your practice website that sends patients to your Now Accepting profile.",
         f"""<article class="prose"><h1>Add a badge to your website</h1>
<p class="lede">Show patients where to check your insurance and availability. The badge is free and optional, and it has no effect on your confidence score or your place in results.</p></article>
<p class="muted small" data-badge-note>These snippets link to our home page. Open this page from your profile, using the "add a badge" link, to link to your own listing.</p>
<div class="badge-opts">
<section class="panel"><h2>Light</h2><div class="badge-preview light"><img src="/assets/badge-light.svg" alt="Find us on Now Accepting" width="200" height="56"></div><textarea class="badge-code" readonly aria-label="Light badge HTML" data-badge-code>{snippet("light")}</textarea><button class="btn btn-ghost btn-sm" type="button" data-badge-copy>Copy code</button></section>
<section class="panel"><h2>Dark</h2><div class="badge-preview dark"><img src="/assets/badge-dark.svg" alt="Find us on Now Accepting" width="200" height="56"></div><textarea class="badge-code" readonly aria-label="Dark badge HTML" data-badge-code>{snippet("dark")}</textarea><button class="btn btn-ghost btn-sm" type="button" data-badge-copy>Copy code</button></section>
</div>
<article class="prose"><h2>How to add it</h2><ol><li>Copy the code for the version that suits your site.</li><li>Paste it into your website's HTML, using a custom HTML or embed block if you use a site builder.</li><li>Publish, then click the badge to check that it opens your profile.</li></ol>
<p>Your web person can also download the <a href="/assets/badge-light.svg">light</a> or <a href="/assets/badge-dark.svg">dark</a> image directly.</p></article>""",
         [("Home", "/"), ("For providers", "/for-providers/"), ("Badge", "/for-providers/badge/")], noindex=True)
    page(ctx, "/for-providers/welcome/", f"Welcome | {BRAND}",
         "Your subscription is active.",
         """<article class="prose"><h1>You're in — thank you</h1>
<p class="lede">Your subscription is active. Stripe has emailed your receipt.</p>
<h2>What happens next</h2><ol><li>We verify you own the listing by contacting the phone or email on your NPI record — usually within one business day.</li>
<li>Once verified, we'll set up your booking link and availability on your profile.</li>
<li>You can update your card or cancel any time from your billing portal.</li>
<li>If you like, <a href="/for-providers/badge/">add a free badge</a> to your practice website.</li></ol>
<p><a class="btn" href="/">Back to Now Accepting</a> """ + (f'<a class="btn btn-ghost" href="{e(ctx["payments"]["portal"])}" rel="noopener">Manage subscription</a>' if ctx["payments"].get("portal") else "") + """</p></article>""",
         [("Home", "/"), ("For providers", "/for-providers/"), ("Welcome", "/for-providers/welcome/")], noindex=True)
    page(ctx, "/report/", f"Report a Call Outcome | {BRAND}",
         "Tell us whether a provider was really accepting new patients. Your report improves listings for everyone.",
         """<article class="prose"><h1>What happened when you called?</h1><p class="lede">Takes 20 seconds. No account, and we never ask about your health.</p></article>
<section class="panel"><form class="stack" data-form><input type="hidden" name="kind" value="report"><input type="hidden" name="npi" data-npi><input type="hidden" name="page" data-page><div class="hp" aria-hidden="true"><label>Website<input name="website" tabindex="-1" autocomplete="off"></label></div>
<fieldset><legend>Were they accepting new patients with your insurance?</legend>
<label class="check"><input type="radio" name="o" value="yes" required> Yes — I booked or could book</label>
<label class="check"><input type="radio" name="o" value="waitlist"> Waitlist only</label>
<label class="check"><input type="radio" name="o" value="no"> No, not accepting</label>
<label class="check"><input type="radio" name="o" value="oon"> Not in-network with my plan</label>
<label class="check"><input type="radio" name="o" value="wrong"> Wrong number / couldn't reach</label></fieldset>
<label>Wait until first appointment (optional)<select name="wait"><option value="">—</option><option>Under 1 week</option><option>1–4 weeks</option><option>1–3 months</option><option>3+ months</option></select></label>
<button class="btn" type="submit">Submit report</button><p class="muted small" data-form-msg></p></form></section>""",
         [("Home", "/"), ("Report", "/report/")], noindex=True)
    page(ctx, "/about/", f"About & Disclosures | {BRAND}", f"Who runs {BRAND}, how we make money, and our editorial independence.",
         f"""<article class="prose"><h1>About {BRAND}</h1><p class="lede">{BRAND} exists because finding an in-network provider who is actually taking patients shouldn't take 20 phone calls.</p>
<h2>How we make money</h2><ul><li><strong>Provider subscriptions.</strong> Providers can pay for booking links, analytics and directory-error alerts. Paying never changes a confidence score.</li>
<li><strong>Labelled partner referrals.</strong> When local openings are thin, we may show telehealth services that accept insurance and earn a referral fee. These are always marked.</li>
<li><strong>Data partnerships.</strong> We sell aggregated directory-accuracy reports to employers, brokers and researchers. We never sell anything about you.</li></ul>
<h2>Where the data comes from</h2><p>Listings come from the provider directories insurers are required to publish, checked against the federal NPI registry. Every listing is scored using <a href="/how-we-verify/">published criteria</a>. We don't call every provider, so a high score means a listing's public records hold up, not that an appointment is guaranteed.</p>
<h2>Corrections</h2><p>Found something wrong? <a href="/report/">Tell us what happened when you called</a>. Providers can <a href="/for-providers/">claim and correct their listing</a> for free.</p>
<h2>Not medical advice</h2><p>Listings are informational. Always confirm coverage with your insurer. If you're in crisis, call or text 988, or call 911 in an emergency.</p>
</article>""",
         [("Home", "/"), ("About", "/about/")])
    page(ctx, "/privacy/", f"Privacy | {BRAND}", f"{BRAND} doesn't use ad trackers, retargeting pixels or sell personal data. Searching for care stays private: no account, no health information collected.",
         """<article class="prose"><h1>Privacy</h1><p class="lede">Searching for mental health care is sensitive. We built this site so nothing about your search leaves it.</p>
<ul><li>No advertising pixels, retargeting, or third-party trackers.</li><li>No account needed to search.</li><li>Call reports store only the provider, the outcome, the wait time and the date — never your name or health information.</li><li>Providers who claim a profile give us a work email, used only to verify and contact them about their listing.</li><li>We use privacy-friendly, cookie-free page counts only.</li></ul></article>""",
         [("Home", "/"), ("Privacy", "/privacy/")])


def build_city(ctx, raw, city, st, city_path, providers):
    """City hub, care-type and care-type x insurer pages for one city."""
    active = ctx["active_payers"]
    accepting = [p for p in providers if p["level"] != "none"]
    cityname = f"{city}, {st}"
    cat_links, ins_links = [], []
    for c, (plural, singular, blurb) in CATS.items():
        ps = [p for p in providers if c in p["cats"]]
        sub_links = []
        for k in active:
            s = PAYER_SLUG[k]
            pk = [p for p in ps if k in p["accepting_payers"]]
            n = listing_pages(ctx, f"{city_path}{c}/{s}/",
                              [("Home", "/"), state_crumb(city_path), (city, city_path), (plural, f"{city_path}{c}/"), (raw["payers"][k], f"{city_path}{c}/{s}/")],
                              f"{plural} in {city} that take {raw['payers'][k]}",
                              f"{e(blurb)} who are in-network with <strong>{e(raw['payers'][k])}</strong> and listed as accepting new patients. Sorted by how confident we are the listing is accurate.",
                              f"{city} {plural} Taking {raw['payers'][k]}" + (" — New Patients" if len(f"{city} {plural} Taking {raw['payers'][k]}") <= 50 else ""),
                              f"{len(pk)} {plural.lower()} in {cityname} in-network with {raw['payers'][k]} and accepting new patients, each with an accuracy score from cross-checked public data.",
                              pk, fixed_cat=c, fixed_ins=s,
                              faq=[(f"How do I find a {singular} in {city} that takes {raw['payers'][k]}?", f"Every {singular} on this page is listed in {raw['payers'][k]}'s own provider directory as in-network and accepting new patients. We cross-check each listing against the federal NPI registry and score how likely it is to be accurate. Start with high-confidence listings and confirm your specific plan when you call."),
                                   ("Why do some listings say call to confirm?", "It means fewer of our checks could be completed: the insurer's record is old, the address or phone doesn't match the federal registry, or insurers disagree. Those providers may still have openings, but call before relying on them.")])
            if pk:
                sub_links.append((f"{plural} that take {raw['payers'][k]}", f"{city_path}{c}/{s}/", f"{n} accepting"))
        n = listing_pages(ctx, f"{city_path}{c}/", [("Home", "/"), state_crumb(city_path), (city, city_path), (plural, f"{city_path}{c}/")],
                          f"{plural} accepting new patients in {city}",
                          f"{e(blurb)} in {e(cityname)} that at least one insurer lists as in-network and accepting new patients — ranked by how confident we are the listing is real.",
                          f"{city} {plural} Accepting New Patients" + (f" ({datetime.now():%b %Y})" if len(f"{city} {plural} Accepting New Patients") <= 54 else ""),
                          f"Find {plural.lower()} in {cityname} who take your insurance and are accepting new patients. {len([p for p in ps if p['level'] != 'none'])} listings, each scored for accuracy.",
                          ps, fixed_cat=c, extra_links=link_grid(f"{plural} by insurance", sub_links),
                          faq=[(f"Are these {plural.lower()} really accepting new patients?", "Each one is marked as accepting new patients in at least one insurer's official directory. Because those directories are often wrong, we score each listing using cross-checks against the federal NPI registry, so you can call the most reliable ones first."),
                               ("What should I say when I call?", "Give your insurer and plan name, ask whether they're in-network for that specific plan, whether they're accepting new patients, and how long the wait is for a first appointment. Each profile has a copy-paste script.")])
        if n:
            cat_links.append((plural, f"{city_path}{c}/", f"{n} accepting"))
    for k in active:
        n = sum(1 for p in providers if k in p["accepting_payers"])
        if n:
            ins_links.append((f"{raw['payers'][k]} in {city}", f"/insurance/{PAYER_SLUG[k]}/", f"{n} accepting"))
    others = [(name, path, "") for name, path in ctx["cities"] if path != city_path and path.startswith(f"/{st.lower()}/")]
    hi = sum(1 for p in accepting if p["level"] == "high")
    body = f"""<header class="hero-sm"><h1>In-network care accepting new patients in {e(city)}</h1>
<p class="lede">{len(accepting)} providers in {e(cityname)} are listed by their insurer as accepting new patients. {hi} pass enough cross-checks to earn high confidence.</p></header>
{link_grid("Choose the type of care", cat_links)}
{link_grid("Or start with your insurance", ins_links)}
{link_grid(f"Other {STATE_NAMES.get(st, st)} cities", others)}
{link_grid("Wider search", [(f"All of {STATE_NAMES.get(st, st)}", f"/{st.lower()}/", "")] + ([(f"Online care in {STATE_NAMES.get(st, st)}", f"/{st.lower()}/telehealth/", "")] if st in ctx["tele_states"] else []))}"""
    page(ctx, city_path, f"{city} Doctors & Therapists Accepting New Patients",
         f"Find in-network therapists, psychiatrists and doctors in {cityname} who are actually accepting new patients. Updated {fmt_date(raw['generated'])}.",
         body, [("Home", "/"), state_crumb(city_path), (city, city_path)])
    return len(accepting), hi


def build_state(ctx, st, paths, providers):
    """Statewide hub, care-type and care-type x insurer pages, plus online care.
    Telehealth gets its own pages because it isn't tied to one city."""
    name = STATE_NAMES.get(st, st)
    root = f"/{st.lower()}/"
    payers = ctx["payers"]
    in_state = [p for p in providers if paths & set(p["src"])]
    accepting = [p for p in in_state if p["level"] != "none"]
    home = [("Home", "/"), (name, root)]
    coverage = f"the {len(paths)} {name} cities we cover"
    cat_links, ins_links = [], []
    for c, (plural, singular, blurb) in CATS.items():
        ps = [p for p in in_state if c in p["cats"]]
        sub_links = []
        for k in ctx["active_payers"]:
            pk = [p for p in ps if k in p["accepting_payers"]]
            n = sum(1 for p in pk if p["level"] != "none")
            if not n:
                continue
            title = f"{name} {plural} Taking {payers[k]}"
            listing_pages(ctx, f"{root}{c}/{PAYER_SLUG[k]}/", home + [(plural, f"{root}{c}/"), (payers[k], f"{root}{c}/{PAYER_SLUG[k]}/")],
                          f"{plural} in {name} that take {payers[k]}",
                          f"{e(blurb)} in {e(coverage)}, in-network with <strong>{e(payers[k])}</strong> and listed as accepting new patients. Sorted by how confident we are the listing is accurate.",
                          title + (" — New Patients" if len(title) <= 50 else ""),
                          f"{n} {plural.lower()} in {name} in-network with {payers[k]} and accepting new patients, each with an accuracy score from cross-checked public data.",
                          pk, fixed_cat=c, fixed_ins=PAYER_SLUG[k])
            sub_links.append((f"{plural} that take {payers[k]}", f"{root}{c}/{PAYER_SLUG[k]}/", f"{n:,} accepting"))
        n = sum(1 for p in ps if p["level"] != "none")
        if not n:
            continue
        city_links = [(f"{plural} in {city.split(',')[0]}", f"{path}{c}/", f"{sum(1 for p in ps if p['level'] != 'none' and path in p['src']):,} accepting")
                      for city, path in ctx["cities"] if path in paths and any(path in p["src"] for p in ps)]
        listing_pages(ctx, f"{root}{c}/", home + [(plural, f"{root}{c}/")],
                      f"{plural} accepting new patients in {name}",
                      f"{e(blurb)} in {e(coverage)} that at least one insurer lists as in-network and accepting new patients, ranked by how confident we are the listing is real.",
                      f"{name} {plural} Accepting New Patients",
                      f"Find {plural.lower()} in {name} who take your insurance and are accepting new patients. {n:,} listings, each scored for accuracy.",
                      ps, fixed_cat=c, extra_links=link_grid(f"{plural} by insurance", sub_links) + link_grid(f"{plural} by city", city_links))
        cat_links.append((plural, f"{root}{c}/", f"{n:,} accepting"))
    for k in ctx["active_payers"]:
        n = sum(1 for p in accepting if k in p["accepting_payers"])
        if n:
            ins_links.append((f"{payers[k]} in {name}", f"/insurance/{PAYER_SLUG[k]}/", f"{n:,} accepting"))
    tele_links = build_telehealth(ctx, st, in_state)
    hi = sum(1 for p in accepting if p["level"] == "high")
    city_links = [(city, path, f"{sum(1 for p in accepting if path in p['src']):,} accepting") for city, path in ctx["cities"] if path in paths]
    body = f"""<header class="hero-sm"><h1>In-network care accepting new patients in {e(name)}</h1>
<p class="lede">{len(accepting):,} providers in {e(coverage)} are listed by their insurer as accepting new patients. {hi:,} pass enough cross-checks to earn high confidence.</p></header>
{link_grid("Choose a city", city_links)}
{link_grid("Choose the type of care", cat_links)}
{link_grid("Online care", tele_links)}
{link_grid("Or start with your insurance", ins_links)}
{link_grid("Directory accuracy", [(f"How accurate are {name} insurer directories?", f"/reports/{name.lower()}-insurance-directory-accuracy/", "")])}"""
    page(ctx, root, f"{name} Doctors & Therapists Accepting New Patients",
         f"Find in-network therapists, psychiatrists and doctors in {name} who are actually accepting new patients. {len(accepting):,} listings, each scored for accuracy.",
         body, home)
    return len(accepting), hi


def build_telehealth(ctx, st, in_state):
    """/xx/telehealth/ pages. Combos with too few listings are skipped, not built."""
    name = STATE_NAMES.get(st, st)
    root = f"/{st.lower()}/telehealth/"
    payers = ctx["payers"]
    online = [p for p in in_state if p["telehealth"] and p["level"] != "none"]
    if len(online) < MIN_INDEXABLE:
        return []
    home = [("Home", "/"), (name, f"/{st.lower()}/"), ("Online care", root)]
    note = f"These providers list a telehealth or virtual-visit location in an insurer's directory. Confirm they're licensed in {e(name)} and in-network for your plan when you call."
    links = []
    for c, (plural, singular, blurb) in CATS.items():
        ps = [p for p in online if c in p["cats"]]
        if len(ps) < MIN_INDEXABLE:
            continue
        sub_links = []
        for k in ctx["active_payers"]:
            pk = [p for p in ps if k in p["accepting_payers"]]
            if len(pk) < MIN_INDEXABLE:
                continue
            listing_pages(ctx, f"{root}{c}/{PAYER_SLUG[k]}/", home + [(plural, f"{root}{c}/"), (payers[k], f"{root}{c}/{PAYER_SLUG[k]}/")],
                          f"Online {plural.lower()} in {name} that take {payers[k]}",
                          f"In-network with <strong>{e(payers[k])}</strong> and listed as accepting new patients. {note}",
                          f"Online {plural} in {name} Taking {payers[k]}",
                          f"{len(pk)} online {plural.lower()} in {name} in-network with {payers[k]} and accepting new patients, each scored for accuracy.",
                          pk, fixed_cat=c, fixed_ins=PAYER_SLUG[k])
            sub_links.append((f"Online {plural.lower()} that take {payers[k]}", f"{root}{c}/{PAYER_SLUG[k]}/", f"{len(pk)} accepting"))
        listing_pages(ctx, f"{root}{c}/", home + [(plural, f"{root}{c}/")],
                      f"Online {plural.lower()} in {name} that take insurance",
                      f"Listed as in-network with an insurer and accepting new patients. {note}",
                      f"Online {plural} in {name} That Take Insurance",
                      f"{len(ps)} online {plural.lower()} in {name} who take insurance and are accepting new patients, each scored for accuracy.",
                      ps, fixed_cat=c, extra_links=link_grid("By insurance", sub_links),
                      faq=[("Does insurance cover online therapy and telehealth visits?", "Many plans cover telehealth with in-network providers, often at the same cost as an office visit. Check your plan's benefits and confirm with the provider before your first session."),
                           (f"Do online providers have to be licensed in {name}?", f"Generally, yes. A provider usually needs to be licensed where you are during the visit, so confirm they can see patients in {name}.")])
        links.append((f"Online {plural.lower()}", f"{root}{c}/", f"{len(ps)} accepting"))
    listing_pages(ctx, root, home,
                  f"Online care in {name} that takes insurance",
                  f"Therapists and doctors listed as in-network and accepting new patients who offer telehealth. {note}",
                  f"Online Therapists & Doctors in {name} That Take Insurance",
                  f"{len(online)} providers offering online visits in {name}, in-network with an insurer and accepting new patients. Each listing is scored for accuracy.",
                  online, extra_links=link_grid("By type of care", links))
    return [(f"All online care in {name}", root, f"{len(online)} accepting")] + links


def report_page(ctx, raws, providers):
    """Original, citable statistics on directory accuracy: the page most
    likely to earn links from press, bloggers and forums."""
    listings = [l for r in raws for l in r["listings"]]
    states = sorted({r["state"] for r in raws})
    region = ", ".join(STATE_NAMES.get(st, st) for st in states)
    n = len(providers)
    pct = lambda k, d: f"{round(100 * k / d)}%" if d else "—"
    rows = ""
    for k in ctx["active_payers"]:
        ls = [l for l in listings if l["payer"] == k]
        yes = sum(1 for l in ls if l["accepting"] == "yes")
        no = sum(1 for l in ls if l["accepting"] == "no")
        rows += f"<tr><th scope='row'>{e(ctx['payers'][k])}</th><td data-label='Listings checked'>{len(ls):,}</td><td data-label='Marked accepting'>{pct(yes, len(ls))}</td><td data-label='Marked not accepting'>{pct(no, len(ls))}</td></tr>"
    reg = [p for p in providers if p["level"] != "none"]
    zip_ok = sum(1 for p in reg if p["checks"][3][0])
    phone_ok = sum(1 for p in reg if p["checks"][4][0])
    fresh = sum(1 for p in reg if p["checks"][1][0])
    multi = [p for p in providers if len(p["plans"]) > 1]
    conflict = sum(1 for p in multi if any(pl["accepting"] == "yes" for pl in p["plans"].values()) and any(pl["accepting"] == "no" for pl in p["plans"].values()))
    lv = defaultdict(int)
    for p in providers:
        lv[p["level"]] += 1
    names = [r["city"] for r in raws]
    cities = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
    uhc_all = all(l["accepting"] == "yes" for l in listings if l["payer"] == "uhc") and any(l["payer"] == "uhc" for l in listings)
    headline = f"We checked {n:,} {region} provider listings against the federal registry"
    lede = (f"Insurers are legally required to publish who is in-network and accepting new patients. We pulled those public directories for {e(cities)} "
            f"and cross-checked every provider against the federal NPI registry. Only <strong>{pct(lv['high'], n)}</strong> of providers passed enough checks to earn high confidence.")
    body = f"""<article class="prose report"><h1>{e(headline)}</h1><p class="tag">Data report · {fmt_date(ctx['generated'])}</p>
<p class="lede">{lede}</p>
<h2>Key findings</h2><ul>
<li><strong>{pct(lv['high'], n)}</strong> of {n:,} providers earned high confidence; <strong>{pct(lv['low'] + lv['none'], n)}</strong> were low confidence or not accepting.</li>
<li>For providers listed as accepting, the office ZIP matched the federal registry <strong>{pct(zip_ok, len(reg))}</strong> of the time, and the phone number only <strong>{pct(phone_ok, len(reg))}</strong>. A mismatch isn't always an error — many providers practice at several offices — but it's a reason to call before you go.</li>
<li><strong>{pct(fresh, len(reg))}</strong> had an insurer record refreshed in the last 90 days.</li>
<li>Of {len(multi):,} providers listed by more than one insurer, <strong>{conflict}</strong> were marked accepting by one and not accepting by another.</li>
{"<li><strong>UnitedHealthcare marked every one of its listings as accepting new patients</strong> — so its flag can't distinguish open panels from full ones.</li>" if uhc_all else ""}
</ul>
<h2>Accepting-new-patients flags by insurer</h2>
<div class="table-wrap"><table><thead><tr><th>Insurer</th><th>Listings checked</th><th>Marked accepting</th><th>Marked not accepting</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Why it matters</h2><p>A 2023 U.S. Senate Finance Committee secret-shopper study found 80% of mental health listings in Medicare Advantage directories were inaccurate or unreachable. These "ghost networks" leave patients calling provider after provider. Our numbers measure consistency between public data sources rather than phone calls, so they show where to be cautious rather than a definitive error rate.</p>
<h2>Methodology</h2><p>Source data: insurer provider directories published under the CMS Interoperability and Patient Access rule (Da Vinci PDex Plan-Net FHIR APIs), and the CMS NPPES NPI registry, retrieved {fmt_date(ctx['generated'])}. Up to 1,500 directory locations per insurer per city were sampled. Providers were matched by NPI. A listing earns one point per check passed; see <a href="/how-we-verify/">how we verify</a>. Deactivated NPIs were excluded.</p>
<h2>Use this data</h2><p>Journalists and researchers may cite these figures with a link to this page.</p>
<p><a class="btn" href="/">Search providers accepting new patients</a></p></article>"""
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": headline, "datePublished": ctx["generated"], "dateModified": ctx["generated"],
          "author": {"@type": "Organization", "name": BRAND, "url": ctx["site"] + "/"}, "publisher": {"@type": "Organization", "name": BRAND},
          "about": "Accuracy of health insurer provider directories"}
    slug = f"/reports/{slugify(region)}-insurance-directory-accuracy/"
    page(ctx, slug, f"{region} Provider Directory Accuracy: {n:,} Listings Checked",
         f"Original data: only {pct(lv['high'], n)} of {n:,} {region} providers in insurer directories passed our accuracy cross-checks. Findings by insurer, methodology and sources.",
         body, [("Home", "/"), ("Reports", slug)], [ld])
    return slug


def load_guides():
    # build.py runs with -I (isolated), so its own folder isn't importable by name.
    spec = importlib.util.spec_from_file_location("guides", os.path.join(os.path.dirname(os.path.abspath(__file__)), "guides.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.GUIDES


GUIDE_LINKS = []  # (title, path), filled by guide_pages for footers and listing pages


def guide_pages(ctx):
    guides = load_guides()
    GUIDE_LINKS[:] = [(g["title"], f"/guides/{g['slug']}/") for g in guides]
    for g in guides:
        path = f"/guides/{g['slug']}/"
        faq_html, faq_ld = faq_block(g["faq"])
        others = "".join(f'<li><a href="{p}">{e(t)}</a></li>' for t, p in GUIDE_LINKS if p != path)
        body = f"""<article class="prose report"><h1>{e(g['h1'])}</h1><p class="tag">Guide · updated {fmt_date(ctx['generated'])}</p>
<p class="lede">{g['intro']}</p>
{''.join(f'<h2>{e(h)}</h2>{html_}' for h, html_ in g['sections'])}
</article>
{faq_html}
<aside class="claim"><div><h2>Find someone who's actually taking patients</h2><p>Search in-network providers by city and insurer, ranked by how likely the listing is accurate.</p></div><a class="btn" href="/">Search now</a></aside>
<section class="links"><h2>More guides</h2><ul>{others}</ul></section>"""
        ld = {"@context": "https://schema.org", "@type": "Article", "headline": g["h1"], "description": g["desc"],
              "datePublished": "2026-10-29", "dateModified": ctx["generated"],
              "author": {"@type": "Organization", "name": BRAND, "url": ctx["site"] + "/"}, "publisher": {"@type": "Organization", "name": BRAND}}
        page(ctx, path, g["title"], g["desc"], body, [("Home", "/"), ("Guides", "/guides/"), (g["title"], path)], [ld, faq_ld])
    items = "".join(f'<li><a href="/guides/{g["slug"]}/">{e(g["title"])}</a> <span class="muted">{e(g["desc"])}</span></li>' for g in guides)
    page(ctx, "/guides/", "Guides: Finding In-Network Care That's Accepting Patients",
         "Practical guides to finding an in-network therapist or doctor with openings: ghost networks, what to ask when you call, and your options if no one is available.",
         f'<header class="hero-sm"><h1>Guides</h1><p class="lede">Practical help for finding in-network care that is actually available.</p></header><section class="links"><ul>{items}</ul></section>',
         [("Home", "/"), ("Guides", "/guides/")])


def build(raws, site, partners, forms_url, reports, payments):
    # One combined pass so a provider listed in two cities gets one profile page.
    first = raws[0]
    combined = {"generated": max(r["generated"] for r in raws), "payers": first["payers"], "listings": [], "registry": {}}
    cities = []
    for r in raws:
        path = f"/{r['state'].lower()}/{slugify(r['city'])}/"
        cities.append((r["city"], r["state"], path, r))
        combined["listings"] += [{**l, "src": path} for l in r["listings"]]
        combined["registry"].update(r["registry"])
    providers = merge(combined, reports)
    active = sorted({k for p in providers for k in p["plans"]})
    ctx = {"site": site.rstrip("/"), "base": urlparse(site).path.rstrip("/"), "payers": first["payers"], "active_payers": active,
           "generated": combined["generated"], "sitemap": [], "partners": partners, "forms": forms_url, "payments": payments,
           "cities": [(f"{c}, {st}", path) for c, st, path, _ in cities]}
    guide_pages(ctx)
    state_paths = defaultdict(set)
    for city, st, path, _ in cities:
        state_paths[st].add(path)
    ctx["tele_states"] = {st for st, paths in state_paths.items()
                          if sum(1 for p in providers if p["telehealth"] and p["level"] != "none" and paths & set(p["src"])) >= MIN_INDEXABLE}
    city_stats = []
    for city, st, path, r in cities:
        n, hi = build_city(ctx, r, city, st, path, [p for p in providers if path in p["src"]])
        city_stats.append((city, st, path, n, hi))

    state_stats = {st: build_state(ctx, st, paths, providers) for st, paths in state_paths.items()}

    # Insurer hubs span every city
    for k in active:
        s = PAYER_SLUG[k]
        pk = [p for p in providers if k in p["accepting_payers"]]
        links = [(f"{CATS[c][0]} in {city}", f"{path}{c}/{s}/", f"{sum(1 for p in pk if c in p['cats'] and path in p['src'])} accepting")
                 for city, st, path, _ in cities for c in CATS if any(c in p["cats"] and path in p["src"] for p in pk)]
        listing_pages(ctx, f"/insurance/{s}/", [("Home", "/"), (first["payers"][k], f"/insurance/{s}/")],
                      f"In-network providers that take {first['payers'][k]}",
                      f"Therapists, psychiatrists and doctors listed in <strong>{e(first['payers'][k])}</strong>'s directory as accepting new patients, scored for accuracy.",
                      f"Doctors & Therapists Taking {first['payers'][k]} — New Patients",
                      f"{len(pk)} providers in-network with {first['payers'][k]} and accepting new patients across {len({c for p in pk for c in p['src']})} {'city' if len({c for p in pk for c in p['src']}) == 1 else 'cities'}, with accuracy scores.",
                      pk, fixed_ins=s, extra_links=link_grid(f"{first['payers'][k]} by city and type of care", links))

    city_by_path = {path: (city, path) for city, st, path, _ in cities}
    by_group = defaultdict(list)  # (city, care type, insurer) -> strong listings, best first
    for p in providers:
        if p["level"] in ("high", "medium"):
            for path in p["src"]:
                for k in p["accepting_payers"]:
                    by_group[(path, p["cats"][0], k)].append(p)
    for p in providers:
        city, path = city_by_path[p["src"][0]]
        payer = (p["accepting_payers"] or list(p["plans"]))[0]
        peers = [q for q in by_group[(path, p["cats"][0], payer)] if q["npi"] != p["npi"]][:6]
        provider_page(ctx, p, path, city, peers)

    reports_out = []
    for st in sorted({r["state"] for r in raws}):
        st_raws = [r for r in raws if r["state"] == st]
        st_paths = {f"/{st.lower()}/{slugify(r['city'])}/" for r in st_raws}
        st_providers = [p for p in providers if st_paths & set(p["src"])]
        reports_out.append((STATE_NAMES.get(st, st), report_page(ctx, st_raws, st_providers), len(st_providers)))
    page(ctx, "/reports/", "Insurer Directory Accuracy Reports by State",
         "Original data on how often health insurer provider directories agree with the federal NPI registry, state by state.",
         f'<header class="hero-sm"><h1>Directory accuracy reports</h1><p class="lede">We cross-check insurer provider directories against the federal NPI registry. Pick a state.</p></header>'
         + link_grid("Reports", [(f"{name}: {n:,} providers checked", url, "") for name, url, n in reports_out]),
         [("Home", "/"), ("Reports", "/reports/")])
    report_url = "/reports/"

    # Home
    listed = [p for p in providers if p["level"] != "none"]
    accepting = len(listed)
    hi_total = sum(1 for p in listed if p["level"] == "high")
    ins_opts = "".join(f'<option value="{PAYER_SLUG[k]}">{e(first["payers"][k])}</option>' for k in active)
    cat_opts = "".join(f'<option value="{c}">{e(CATS[c][0])}</option>' for c in CATS)
    city_opts = "".join(f'<option value="{path}">{e(city)}, {e(st)}</option>' for city, st, path, *_ in city_stats)
    city_grid = "".join(
        link_grid(STATE_NAMES.get(state, state), [(f"All of {STATE_NAMES.get(state, state)}", f"/{state.lower()}/", f"{state_stats[state][0]:,} accepting · {state_stats[state][1]:,} high confidence")] + [(f"{city}, {st}", path, f"{n:,} accepting · {hi:,} high confidence") for city, st, path, n, hi in city_stats if st == state])
        for state in dict.fromkeys(st for _, st, *_ in city_stats))
    state_count = len({st for _, st, *_ in city_stats})
    insurer_names = [first["payers"][k] for k in active]
    insurer_tiles = ""
    for k in active:
        flags = [p["plans"][k]["accepting"] == "yes" for p in providers if k in p["plans"]]
        if flags:
            insurer_tiles += f'<div class="tile rise"><strong>{round(100 * sum(flags) / len(flags))}%</strong><span>of {e(first["payers"][k])} listings we pulled are marked as accepting new patients</span></div>'
    source_rows = "".join(f'<tr><th scope="row">{e(first["payers"][k])}</th><td>{sum(1 for p in providers if k in p["plans"]):,}</td></tr>' for k in active)
    board = write_board_data(ctx, providers)
    start = board["keys"][f"{cities[0][2]}|therapist|"]
    start_n = sum(start[:3])
    columns = ""
    for state in dict.fromkeys(st for _, st, *_ in city_stats):
        rows = "".join(f'<li><a href="{path}">{e(city)}<span>{n:,} accepting</span></a></li>' for city, st, path, n, hi in city_stats if st == state)
        columns += f'<div class="rise"><h3>{e(STATE_NAMES.get(state, state))}</h3><ul><li class="state-all"><a href="/{state.lower()}/">All of {e(STATE_NAMES.get(state, state))}<span>{state_stats[state][0]:,} accepting</span></a></li>{rows}</ul></div>'
    columns += '<div class="rise"><h3>Guides</h3><ul>' + "".join(f'<li><a href="{p}">{e(t)}</a></li>' for t, p in GUIDE_LINKS) + "</ul></div>"
    checks_html = "".join(f'<li><span class="lamp" aria-hidden="true"></span><span>{n}<small>{d}</small></span></li>' for n, d in [
        ("Marked accepting", "An insurer lists them as taking new patients"), ("Recently updated", "Record changed in the last 90 days"),
        ("Active NPI", "Active in the federal registry"), ("Office matches", "ZIP code matches federal records"),
        ("Phone matches", "Number matches federal records"), ("More than one insurer", "A second insurer lists them too"),
        ("No conflicts", "Insurers don't contradict each other"), ("Patient reports", "Recent callers confirm openings")])
    example = next(p for p in listed if p["level"] == "high" and p["phone"])
    qa = [("Are these providers really accepting new patients?", "Each one is marked as accepting in at least one insurer's official directory. Directories can be wrong, so we score each listing and rank the likeliest first. Always confirm when you call."),
          ("What does the confidence score measure?", "It counts how many of eight checks a listing passes, using public records and patient reports. It rates the listing's data, never a provider's quality of care."),
          ("Does it cost anything to search?", "Searching is free and needs no account. We earn money from provider subscriptions and clearly labelled referrals, and paying never changes a score."),
          ("Which insurers and places do you cover?", f"We currently cover {e(', '.join(insurer_names))} in {len(cities)} cities across Colorado and Texas, refreshed from public directories every week."),
          ("What should I say when I call?", "Give your insurer and exact plan name, then ask whether they're in-network for that plan, whether they're taking new patients and how long the wait is.")]
    qa_html = "".join(f'<li><button type="button" data-q="{i}" aria-expanded="{"true" if i == 0 else "false"}">{e(q)}</button><p class="qa-a{" open" if i == 0 else ""}" id="qa-{i}">{e(a)}</p></li>' for i, (q, a) in enumerate(qa))
    body = f"""<section class="bleed hero"><div class="wrap">
<div class="hero-top">
<h1 class="home-title"><span class="line"><span>Find who’s taking</span></span><span class="line"><span>new patients.</span></span></h1>
<p class="hero-lede">In-network therapists and doctors, with every insurer listing checked against federal records.</p>
</div>
<div class="console" data-ui id="board" data-board="{ctx['base']}/data/board.json">
<form class="search" action="{cities[0][2]}" data-search>
  <label><span>I need a</span><select name="cat">{cat_opts}</select></label>
  <label><span>My insurance</span><select name="ins"><option value="">Any insurance</option>{ins_opts}</select></label>
  <label><span>Near</span><select name="city">{city_opts}</select></label>
  <button class="btn btn-lamp btn-lg" type="submit">Find openings</button>
</form>
<div class="console-body">
<div>
<h2 class="console-title" data-board-title>{start_n:,} therapists in {e(cities[0][0])} are listed as accepting</h2>
<p class="switch-note">Each dot is one provider. Brighter dots passed more of our checks.</p>
<div class="lamps on" data-lamps role="img" aria-label="{start[0]} high confidence, {start[1]} medium, {start[2]} call to confirm">{lamp_html(start)}</div>
<ul class="lamp-key"><li><i style="background:var(--signal)"></i><span data-key-h>{start[0]:,} high confidence</span></li><li><i style="background:var(--signal-dim)"></i><span data-key-m>{start[1]:,} medium</span></li><li><i style="background:var(--signal-off)"></i><span data-key-l>{start[2]:,} call to confirm</span></li></ul>
</div>
<div class="first-calls">
<h3>Call these first</h3>
<ol data-first>{first_calls_html(board, start)}</ol>
<a class="btn btn-lamp" data-board-link href="{cities[0][2]}therapist/">See all {start_n:,} listings</a>
</div>
</div>
</div>
</div></section>
<section class="chapter"><div class="tiles">
<div class="tile tile-head rise"><h2>The “accepting” flag</h2></div>
{insurer_tiles}
<div class="tile tile-navy rise"><strong>80%</strong><span>of the mental health listings checked in a 2023 U.S. Senate secret-shopper study of Medicare Advantage directories were inaccurate or unreachable.</span></div>
<div class="tile tile-note rise"><strong>{hi_total:,}</strong><span>of the {accepting:,} providers listed as accepting pass enough checks for high confidence. <a href="{report_url}">Read our accuracy reports</a>.</span></div>
</div></section>
<section class="chapter">
<div class="show rise"><div><h2>How a listing gets checked</h2><h3>Pulled from the source</h3><p>Federal rules make insurers publish their directories as open data. We collect them every week.</p></div>
<div class="frag" data-ui><table><thead><tr><th>Insurer directory</th><th>Providers pulled</th></tr></thead><tbody>{source_rows}</tbody></table></div></div>
<div class="show rise"><div><h3>Checked eight ways</h3><p>Every provider is matched by NPI against the federal registry and scored. A mismatch isn’t always an error, so the score tells you where to be careful. <a href="/how-we-verify/">How we verify</a>.</p></div>
<div class="frag" data-ui><ul class="frag-checks">{checks_html}</ul></div></div>
<div class="show rise"><div><h3>Ranked for your first call</h3><p>The most reliable listings come first, each with a number to call. Tell us what happened, and the next person gets better data.</p></div>
<div class="frag" data-ui><ul class="cards">{card(ctx, example)}</ul></div></div>
</section>
<section class="chapter" id="cities"><h2 class="rows-head rise">Browse by city</h2><div class="rows">{columns}</div></section>
<section class="chapter qa" data-qa><div><h2 class="rise">Common questions</h2><ul class="qa-list">{qa_html}</ul></div><p class="qa-pane" aria-live="polite" data-qa-pane>{e(qa[0][1])}</p></section>
<section class="bleed band-last" style="background:var(--surface);margin-top:var(--gap-section)"><div class="wrap blank">
<form class="blank-form" action="/for-providers/" method="get">I’m a provider and my NPI is <input name="npi" inputmode="numeric" maxlength="10" placeholder="10 digits" aria-label="Your 10-digit NPI number"> <button type="submit">claim</button></form>
<p class="blank-note">Claim your listing for free, confirm whether you’re taking patients and correct anything out of date. <a href="/for-providers/">See what’s included</a>.</p>
</div></section>"""
    page(ctx, "/", "Find In-Network Therapists & Doctors Accepting New Patients",
         "Find therapists, psychiatrists and doctors who take your insurance and are actually accepting new patients. Every listing cross-checked and scored for accuracy.",
         body, jsonld=[{"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in qa]},
                      {"@context": "https://schema.org", "@type": "WebSite", "name": BRAND, "url": ctx["site"] + "/"},
                      {"@context": "https://schema.org", "@type": "Organization", "name": BRAND, "url": ctx["site"] + "/", "logo": ctx["site"] + "/favicon.svg"}])
    static_pages(ctx, cities[0][2], cities[0][0])

    page(ctx, "/404.html", f"Page not found | {BRAND}", "This page doesn't exist. Search in-network providers accepting new patients by city and insurer.",
         f"""<header class="hero-sm"><h1>We couldn't find that page</h1><p class="lede">The listing may have moved or the provider may no longer be in-network. Try one of these instead.</p></header>
{link_grid("Search by city", [(name, path, "") for name, path in ctx["cities"]])}
{link_grid("Guides", [(t, p, "") for t, p in GUIDE_LINKS])}""", noindex=True)

    write_search_data(ctx, providers)

    # SEO plumbing: a sitemap index so Search Console reports each section separately
    groups = {"providers": [p for p in ctx["sitemap"] if p.startswith("/provider/")],
              "listings": [p for p in ctx["sitemap"] if p.count("/") >= 3 and not p.startswith(("/provider/", "/guides/", "/reports/"))],
              }
    groups["pages"] = [p for p in ctx["sitemap"] if p not in set(groups["providers"]) | set(groups["listings"])]
    for name, paths in groups.items():
        with open(os.path.join(DIST, f"sitemap-{name}.xml"), "w") as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
            for path in paths:
                f.write(f"<url><loc>{ctx['site']}{path}</loc><lastmod>{ctx['generated']}</lastmod></url>\n")
            f.write("</urlset>\n")
    with open(os.path.join(DIST, "sitemap.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for name in groups:
            f.write(f"<sitemap><loc>{ctx['site']}/sitemap-{name}.xml</loc><lastmod>{ctx['generated']}</lastmod></sitemap>\n")
        f.write("</sitemapindex>\n")
    with open(os.path.join(DIST, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nDisallow: {ctx['base']}/report/\nDisallow: {ctx['base']}/data/\nSitemap: {ctx['site']}/sitemap.xml\n")
    return providers, ctx, city_stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-url", default="https://nowacceptingpatients.com")
    ap.add_argument("--payments", help="Stripe links JSON (default data/payments.json; data/payments.test.json for test mode)")
    ap.add_argument("--forms-url", default=os.environ.get("FORMS_URL", ""), help="Apps Script web app URL (forms/Code.gs)")
    args = ap.parse_args()
    if os.path.exists(DIST):
        shutil.rmtree(DIST)
    shutil.copytree(os.path.join(ROOT, "static"), DIST)
    partners_path = os.path.join(ROOT, "data", "partners.json")
    partners = json.load(open(partners_path)) if os.path.exists(partners_path) else []
    reports_path = os.path.join(ROOT, "data", "reports.json")
    reports = json.load(open(reports_path)) if os.path.exists(reports_path) else {}
    payments_path = args.payments or os.path.join(ROOT, "data", "payments.json")
    payments = json.load(open(payments_path)) if os.path.exists(payments_path) else {}
    raws = []
    for c in json.load(open(os.path.join(ROOT, "data", "cities.json"))):
        path = os.path.join(ROOT, "data", f"raw_{c['city'].lower().replace(' ', '-')}.json.gz")
        if os.path.exists(path):  # cities not fetched yet are skipped
            with gzip.open(path, "rt") as f:
                raws.append(json.load(f))
    providers, ctx, city_stats = build(raws, args.site_url, partners, args.forms_url, reports, payments)
    lv = defaultdict(int)
    for p in providers:
        lv[p["level"]] += 1
    for city, st, path, n, hi in city_stats:
        print(f"{city}, {st}: {n} accepting, {hi} high confidence")
    print(f"total: {len(providers)} providers {dict(lv)}; {len(ctx['sitemap'])} indexable pages")


if __name__ == "__main__":
    main()
