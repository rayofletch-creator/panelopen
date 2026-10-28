"""Merge raw directory data per provider, score how trustworthy each
"accepting new patients" claim is, and render a static, SEO-first site.

Usage: python3 -I pipeline/build.py --site-url https://panelopen.com
Reads data/raw_*.json.gz, writes dist/.
"""
import argparse
import glob
import html
import json
import os
import re
import gzip
import shutil
from collections import defaultdict
from urllib.parse import urlparse
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
BRAND = "PanelOpen"
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

STATE_NAMES = {"CO": "Colorado"}


def e(s):
    return html.escape(str(s or ""), quote=True)


def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")


def digits(s):
    return re.sub(r"\D", "", s or "")[-10:]


def fmt_phone(p):
    d = digits(p)
    return f"({d[:3]}) {d[3:6]}-{d[6:]}" if len(d) == 10 else (p or "")


def fmt_date(s):
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%b %-d, %Y")
    except Exception:
        return s


# ---------------------------------------------------------------- merge ---

def merge(raw):
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
        score = sum(1 for ok, _ in checks if ok)
        if not accepting_payers:
            level = "none"
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
    ld_html = "".join(f'<script type="application/ld+json">{json.dumps(x)}</script>' for x in ld)
    doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(desc)}">
<link rel="canonical" href="{e(url)}">
{'<meta name="robots" content="noindex, follow">' if noindex else ''}
<meta property="og:type" content="website">
<meta property="og:site_name" content="{BRAND}">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}">
<meta name="twitter:card" content="summary">
<link rel="icon" href="/favicon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/assets/site.css">
{ld_html}
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <div class="wrap top-in">
    <a class="logo" href="/"><span class="logo-mark" aria-hidden="true"></span>{BRAND}</a>
    <nav class="top-nav" aria-label="Main">
      <a href="/co/denver/">Denver</a>
      <a href="/how-we-verify/">How we verify</a>
      <a href="/for-providers/" class="top-cta">For providers</a>
    </nav>
  </div>
</header>
<main id="main" class="wrap">
{crumb_html}
{body}
</main>
<footer class="foot">
  <div class="wrap foot-in">
    <div class="crisis"><strong>In crisis?</strong> Call or text <a href="tel:988">988</a> (Suicide &amp; Crisis Lifeline), or call 911 for an emergency.</div>
    <div class="foot-cols">
      <div><p class="foot-brand">{BRAND}</p><p class="muted">Find in-network providers who are actually taking new patients. Data from insurers' public directories and the federal NPI registry, cross-checked and scored.</p></div>
      <div><p class="foot-h">Find care</p>{''.join(f'<a href="/co/denver/{c}/">{CATS[c][0]} in Denver</a>' for c in CATS)}</div>
      <div><p class="foot-h">Insurance</p>{''.join(f'<a href="/insurance/{s}/">{e(ctx["payers"][k])}</a>' for k, s in PAYER_SLUG.items() if k in ctx["active_payers"])}</div>
      <div><p class="foot-h">{BRAND}</p><a href="/how-we-verify/">How we verify</a><a href="/for-providers/">Claim your profile</a><a href="/about/">About &amp; disclosures</a><a href="/privacy/">Privacy</a></div>
    </div>
    <p class="muted small">Listings are informational and not a guarantee of coverage or availability. Always confirm network status with your insurer and the provider before booking. Data last refreshed {fmt_date(ctx["generated"])}.</p>
  </div>
</footer>
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


LEVEL_LABEL = {"high": "High confidence", "medium": "Medium confidence", "low": "Low confidence", "none": "Not accepting"}


def payer_names(ctx, keys):
    return [ctx["payers"][k] for k in keys]


def card(ctx, p):
    accepting = payer_names(ctx, p["accepting_payers"])
    loc = p["locations"][0] if p["locations"] else None
    where = "Telehealth only" if loc and loc["virtual"] and len(p["locations"]) == 1 else (f'{e(loc["line"])}, {e(loc["city"])} {e(loc["zip"])}' if loc else "")
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
    <div class="card-head">
      <h3><a href="/provider/{p['slug']}/">{e(p['name'])}{', ' + e(p['credential']) if p['credential'] else ''}</a></h3>
      <span class="conf conf-{p['level']}" title="{p['score']} of {len(p['checks'])} checks passed">{LEVEL_LABEL[p['level']]}</span>
    </div>
    <p class="card-sub">{e(cats)}{' · Telehealth' if p['telehealth'] else ''}</p>
    <p class="card-ins"><span class="dot" aria-hidden="true"></span>Accepting new patients with <strong>{e(', '.join(accepting))}</strong></p>
    <p class="card-loc muted">{where}{' · +' + str(len(p['locations']) - 1) + ' more' if len(p['locations']) > 1 else ''}</p>
  </div>
  <div class="card-act">{phone}<a class="btn btn-ghost" href="/provider/{p['slug']}/">Details</a></div>
</li>"""


def filters(ctx, providers, fixed_cat=None, fixed_ins=None):
    ins_opts = "".join(f'<option value="{PAYER_SLUG[k]}">{e(ctx["payers"][k])}</option>' for k in PAYER_SLUG if k in ctx["active_payers"])
    cat_opts = "".join(f'<option value="{c}">{e(CATS[c][0])}</option>' for c in CATS)
    return f"""<form class="filters" data-filters aria-label="Filter results">
  {'' if fixed_ins else f'<label>Insurance<select name="ins"><option value="">Any insurance</option>{ins_opts}</select></label>'}
  {'' if fixed_cat else f'<label>Type of care<select name="cat"><option value="">Any</option>{cat_opts}</select></label>'}
  <label>ZIP<input name="zip" inputmode="numeric" maxlength="5" placeholder="e.g. 80206"></label>
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
<ol class="cards" data-list start="{i * PAGE_SIZE + 1}">{items}</ol>
<p class="noresults" data-noresults hidden>No matches on this page. Clear a filter or try the next page.</p>
{pager}
{monetization_slot(ctx, next((k for k, s in PAYER_SLUG.items() if s == fixed_ins), None), fixed_cat) if i == 0 else ''}
{extra_links if i == 0 else ''}
{faq_html}"""
        page(ctx, path, title if i == 0 else f"{title} — Page {i + 1}", desc, body, crumbs, [item_ld] + ([faq_ld] if faq_ld else []), noindex=noindex)
    return len(acc)


def link_grid(title, links):
    if not links:
        return ""
    return f'<section class="links"><h2>{e(title)}</h2><ul>' + "".join(f'<li><a href="{h}">{e(n)}</a> <span class="muted">{c}</span></li>' for n, h, c in links) + "</ul></section>"


def provider_page(ctx, p, city_path, city):
    cats = ", ".join(CATS[c][1] for c in p["cats"])
    rows = ""
    for k, pl in sorted(p["plans"].items(), key=lambda x: x[1]["accepting"] != "yes"):
        status = {"yes": ("Accepting new patients", "ok"), "no": ("Not accepting new patients", "no"), "unknown": ("Not stated", "unk")}[pl["accepting"]]
        nets = ", ".join(pl["networks"][:6]) + (f" +{len(pl['networks']) - 6} more" if len(pl["networks"]) > 6 else "")
        rows += f'<tr><th scope="row"><a href="/insurance/{PAYER_SLUG[k]}/">{e(ctx["payers"][k])}</a></th><td data-label="New patients"><span class="pill pill-{status[1]}">{status[0]}</span></td><td class="muted" data-label="Networks / plans">{e(nets.title()) or "—"}</td><td class="muted" data-label="Insurer updated">{fmt_date(pl["updated"])}</td></tr>'
    checks = "".join(f'<li class="{"ok" if ok else "no"}"><span aria-hidden="true">{"✓" if ok else "–"}</span> {e(label)}</li>' for ok, label in p["checks"])
    locs = "".join(f'<li>{"Telehealth / virtual visits" if l["virtual"] else e(l["line"]) + ", " + e(l["city"]) + ", " + e(l["state"]) + " " + e(l["zip"])}</li>' for l in p["locations"][:8])
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
  <div>
    <h1>{e(full)}</h1>
    <p class="lede">{e(cats.capitalize())} in {e(city)}{' · Offers telehealth' if p['telehealth'] else ''}{' · ' + e(p['gender']) if p['gender'] else ''}</p>
    <p><span class="conf conf-{p['level']} conf-lg">{LEVEL_LABEL[p['level']]} · {p['score']}/{len(p['checks'])} checks</span></p>
  </div>
  <div class="prov-cta">{call}<a class="btn btn-ghost" href="/report/?npi={p['npi']}">I called — report what happened</a></div>
</header>
<section class="panel"><h2>Insurance & new-patient status</h2>
<div class="table-wrap"><table><thead><tr><th>Insurer</th><th>New patients</th><th>Networks / plans</th><th>Insurer updated</th></tr></thead><tbody>{rows}</tbody></table></div>
<p class="muted small">Status comes from each insurer's public provider directory, which federal rules require them to publish. Plans within one insurer can differ — confirm your specific plan.</p></section>
<div class="two">
<section class="panel"><h2>How confident are we?</h2><ul class="checks">{checks}</ul><p class="small"><a href="/how-we-verify/">How the confidence score works</a></p></section>
<section class="panel"><h2>Where they practice</h2><ul class="plain">{locs}</ul>
<h3>Before you call</h3><p class="script" data-copy>{e(script)}</p><button class="btn btn-ghost btn-sm" type="button" data-copy-btn>Copy script</button></section>
</div>
<section class="panel"><h2>Specialties on record</h2><p>{e(', '.join(p['specialties']))}</p><p class="muted small">NPI {p['npi']} · <a href="https://npiregistry.cms.hhs.gov/provider-view/{p['npi']}" rel="nofollow noopener" target="_blank">View federal NPI record</a></p></section>
<aside class="claim"><div><h2>Are you {e(p['name'])}?</h2><p>Confirm your availability in 30 seconds so patients stop calling when you're full — and get a booking link on this page.</p></div><a class="btn" href="/for-providers/?npi={p['npi']}">Claim this profile</a></aside>
</article>"""
    desc = f"{full} — {cats} in {city}. " + (f"Listed as accepting new patients with {accepting}. " if accepting else "") + f"Confidence: {LEVEL_LABEL[p['level']].lower()}."
    title = f"{full} — {cats.split(',')[0].title()} in {city}" + (f" | Takes {accepting}" if accepting and len(accepting) < 40 else "")
    crumbs = [("Home", "/"), (city, city_path), (CATS[p["cats"][0]][0], f"{city_path}{p['cats'][0]}/"), (p["name"], f"/provider/{p['slug']}/")]
    page(ctx, f"/provider/{p['slug']}/", title, desc, body, crumbs, [ld], noindex=p["level"] == "none")


def static_pages(ctx, city_path, city):
    page(ctx, "/how-we-verify/", f"How We Verify Provider Listings | {BRAND}",
         "Where our in-network and accepting-new-patients data comes from, and how each listing's confidence score is calculated.",
         f"""<article class="prose"><h1>How we verify listings</h1>
<p class="lede">Insurer directories are notoriously wrong. In a U.S. Senate secret-shopper study of Medicare Advantage plans, 80% of the mental health listings checked were inaccurate or unreachable. We can't fix that alone, but we can show you which listings are most likely to be real.</p>
<h2>Where the data comes from</h2>
<ul><li><strong>Insurer provider directories.</strong> Federal interoperability rules require insurers to publish their directories as open data. We pull each insurer's in-network status and its "accepting new patients" flag directly.</li>
<li><strong>The federal NPI registry (NPPES).</strong> Every U.S. provider has a National Provider Identifier. We use it to confirm the provider is active and to cross-check their address and phone.</li>
<li><strong>Patient reports</strong> (coming soon). When you call a provider, tell us what happened. Reports feed straight into the score.</li>
<li><strong>Provider confirmations.</strong> Providers who claim their profile can confirm availability directly.</li></ul>
<h2>The confidence score</h2><p>Each listing gets one point for each check it passes:</p>
<ol><li>An insurer lists them as accepting new patients</li><li>The insurer's record was refreshed in the last 90 days</li><li>Their NPI is active in the federal registry</li><li>Their office ZIP matches the federal registry</li><li>Their phone number matches the federal registry</li><li>More than one insurer lists them</li><li>Insurers don't contradict each other</li></ol>
<p><strong>High confidence</strong> = 5+ checks. <strong>Medium</strong> = 4. <strong>Low</strong> = 3 or fewer. Listings that no insurer marks as accepting are never shown in "accepting" results.</p>
<p>Some insurers mark nearly every provider as accepting new patients. When an insurer's directory does that, its "accepting" flag doesn't earn a point, and those listings can't reach high confidence unless other checks back them up.</p>
<h2>What we don't do</h2><p>We don't sell rankings. Sponsored and partner placements are always labelled, and never change a provider's confidence score or order within results.</p></article>""",
         [("Home", "/"), ("How we verify", "/how-we-verify/")])
    page(ctx, "/for-providers/", f"For Providers: Claim Your Profile | {BRAND}",
         "Stop fielding calls when your panel is full. Claim your free profile, confirm availability and add a booking link.",
         """<article class="prose"><h1>Your panel status, kept accurate</h1>
<p class="lede">Insurer directories say you're accepting new patients when you're not — or hide you when you are. Claim your profile and control what patients see.</p></article>
<div class="tiers">
<div class="tier"><h2>Free</h2><p class="price">$0</p><ul><li>Claim and correct your listing</li><li>Toggle "accepting new patients"</li><li>Shown as provider-confirmed</li></ul><a class="btn btn-ghost" href="#claim">Claim free</a></div>
<div class="tier tier-main"><p class="tag">Most popular</p><h2>Practice Pro</h2><p class="price">$39<span>/mo</span></p><ul><li>Everything in Free</li><li>Online booking or intake link</li><li>Weekly opening counts & waitlist</li><li>Patient call analytics</li><li>Directory-error alerts across insurers</li></ul><a class="btn" href="#claim">Start 30-day trial</a></div>
<div class="tier"><h2>Group</h2><p class="price">$149<span>/mo</span></p><ul><li>Up to 15 clinicians</li><li>Group page & intake routing</li><li>Bulk availability updates</li><li>Labelled featured placement</li></ul><a class="btn btn-ghost" href="#claim">Talk to us</a></div>
</div>
<section class="panel" id="claim"><h2>Claim your profile</h2><form class="stack" data-demo-form><label>NPI number<input name="npi" inputmode="numeric" maxlength="10" required></label><label>Work email<input type="email" name="email" required></label><button class="btn" type="submit">Send verification</button><p class="muted small" data-form-msg>We verify ownership by contacting the phone or email on your NPI record.</p></form></section>""",
         [("Home", "/"), ("For providers", "/for-providers/")])
    page(ctx, "/report/", f"Report a Call Outcome | {BRAND}",
         "Tell us whether a provider was really accepting new patients. Your report improves listings for everyone.",
         """<article class="prose"><h1>What happened when you called?</h1><p class="lede">Takes 20 seconds. No account, and we never ask about your health.</p></article>
<section class="panel"><form class="stack" data-demo-form><input type="hidden" name="npi" data-npi>
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
<h2>Not medical advice</h2><p>Listings are informational. Always confirm coverage with your insurer.</p></article>""",
         [("Home", "/"), ("About", "/about/")])
    page(ctx, "/privacy/", f"Privacy | {BRAND}", f"{BRAND} doesn't use ad trackers or sell personal data.",
         """<article class="prose"><h1>Privacy</h1><p class="lede">Searching for mental health care is sensitive. We built this site so nothing about your search leaves it.</p>
<ul><li>No advertising pixels, retargeting, or third-party trackers.</li><li>No account needed to search.</li><li>Call reports store only the provider, the outcome and the date — never your name or health information.</li><li>We use privacy-friendly, cookie-free page counts only.</li></ul></article>""",
         [("Home", "/"), ("Privacy", "/privacy/")])


def build(raw, site, partners):
    city, st = raw["city"], raw["state"]
    city_path = f"/{st.lower()}/{slugify(city)}/"
    providers = merge(raw)
    active = sorted({k for p in providers for k in p["plans"]})
    ctx = {"site": site.rstrip("/"), "base": urlparse(site).path.rstrip("/"), "payers": raw["payers"], "active_payers": active, "generated": raw["generated"],
           "sitemap": [], "partners": partners}
    accepting = [p for p in providers if p["level"] != "none"]
    cityname = f"{city}, {st}"

    # Category × insurer combos (the long-tail money pages)
    cat_links, ins_links = [], []
    for c, (plural, singular, blurb) in CATS.items():
        ps = [p for p in providers if c in p["cats"]]
        sub_links = []
        for k in active:
            s = PAYER_SLUG[k]
            pk = [p for p in ps if k in p["accepting_payers"]]
            n = listing_pages(ctx, f"{city_path}{c}/{s}/",
                              [("Home", "/"), (city, city_path), (plural, f"{city_path}{c}/"), (raw["payers"][k], f"{city_path}{c}/{s}/")],
                              f"{plural} in {city} that take {raw['payers'][k]}",
                              f"{e(blurb)} who are in-network with <strong>{e(raw['payers'][k])}</strong> and listed as accepting new patients. Sorted by how confident we are the listing is accurate.",
                              f"{plural} in {city} Accepting {raw['payers'][k]} — New Patients ({datetime.now():%b %Y})",
                              f"{len(pk)} {plural.lower()} in {cityname} in-network with {raw['payers'][k]} and accepting new patients, each with an accuracy score from cross-checked public data.",
                              pk, fixed_cat=c, fixed_ins=s,
                              faq=[(f"How do I find a {singular} in {city} that takes {raw['payers'][k]}?", f"Every {singular} on this page is listed in {raw['payers'][k]}'s own provider directory as in-network and accepting new patients. We cross-check each listing against the federal NPI registry and score how likely it is to be accurate. Start with high-confidence listings and confirm your specific plan when you call."),
                                   ("Why do some listings say low confidence?", "Low confidence means the insurer's record is old, the address or phone doesn't match the federal registry, or insurers disagree. Those providers may still have openings, but call before relying on them.")])
            if pk:
                sub_links.append((f"{plural} that take {raw['payers'][k]}", f"{city_path}{c}/{s}/", f"{n} accepting"))
        n = listing_pages(ctx, f"{city_path}{c}/", [("Home", "/"), (city, city_path), (plural, f"{city_path}{c}/")],
                          f"{plural} accepting new patients in {city}",
                          f"{e(blurb)} in {e(cityname)} that at least one insurer lists as in-network and accepting new patients — ranked by how confident we are the listing is real.",
                          f"{plural} Accepting New Patients in {city}, {st} — In-Network ({datetime.now():%b %Y})",
                          f"Find {plural.lower()} in {cityname} who take your insurance and are accepting new patients. {len([p for p in ps if p['level'] != 'none'])} listings, each scored for accuracy.",
                          ps, fixed_cat=c, extra_links=link_grid(f"{plural} by insurance", sub_links),
                          faq=[(f"Are these {plural.lower()} really accepting new patients?", "Each one is marked as accepting new patients in at least one insurer's official directory. Because those directories are often wrong, we score each listing using cross-checks against the federal NPI registry, so you can call the most reliable ones first."),
                               ("What should I say when I call?", "Give your insurer and plan name, ask whether they're in-network for that specific plan, whether they're accepting new patients, and how long the wait is for a first appointment. Each profile has a copy-paste script.")])
        if n:
            cat_links.append((plural, f"{city_path}{c}/", f"{n} accepting"))

    for k in active:
        s = PAYER_SLUG[k]
        pk = [p for p in providers if k in p["accepting_payers"]]
        links = [(f"{CATS[c][0]} in {city}", f"{city_path}{c}/{s}/", f"{sum(1 for p in pk if c in p['cats'])} accepting") for c in CATS if any(c in p["cats"] for p in pk)]
        listing_pages(ctx, f"/insurance/{s}/", [("Home", "/"), (raw["payers"][k], f"/insurance/{s}/")],
                      f"In-network providers that take {raw['payers'][k]}",
                      f"Therapists, psychiatrists and doctors listed in <strong>{e(raw['payers'][k])}</strong>'s directory as accepting new patients, scored for accuracy.",
                      f"Find Doctors & Therapists That Take {raw['payers'][k]} — Accepting New Patients",
                      f"{len(pk)} providers in-network with {raw['payers'][k]} and accepting new patients in {cityname}, with accuracy scores.",
                      pk, fixed_ins=s, extra_links=link_grid(f"{raw['payers'][k]} by type of care", links))
        ins_links.append((raw["payers"][k], f"/insurance/{s}/", f"{len(pk)} accepting"))

    # City hub
    hi = sum(1 for p in accepting if p["level"] == "high")
    body = f"""<header class="hero-sm"><h1>In-network care accepting new patients in {e(city)}</h1>
<p class="lede">{len(accepting)} providers in {e(cityname)} are listed by their insurer as accepting new patients. {hi} pass enough cross-checks to earn high confidence.</p></header>
{link_grid("Choose the type of care", cat_links)}
{link_grid("Or start with your insurance", ins_links)}"""
    page(ctx, city_path, f"Doctors & Therapists Accepting New Patients in {city}, {st} | {BRAND}",
         f"Find in-network therapists, psychiatrists and doctors in {cityname} who are actually accepting new patients. Updated {fmt_date(raw['generated'])}.",
         body, [("Home", "/"), (city, city_path)])

    for p in providers:
        provider_page(ctx, p, city_path, city)

    # Home
    ins_opts = "".join(f'<option value="{PAYER_SLUG[k]}">{e(raw["payers"][k])}</option>' for k in active)
    cat_opts = "".join(f'<option value="{c}">{e(CATS[c][0])}</option>' for c in CATS)
    body = f"""<section class="hero">
<h1>Find a provider who takes your insurance <em>and</em> is actually taking new patients.</h1>
<p class="lede">In one U.S. Senate study, 80% of mental health listings in insurer directories were wrong or unreachable. We pull every insurer's public directory, cross-check it against the federal registry, and score each listing — so you call the right people first.</p>
<form class="search" action="{city_path}" data-search>
  <label><span>I need a</span><select name="cat">{cat_opts}</select></label>
  <label><span>My insurance</span><select name="ins"><option value="">Any insurance</option>{ins_opts}</select></label>
  <label><span>Near</span><select name="city"><option value="{city_path}">{e(cityname)}</option></select></label>
  <button class="btn btn-lg" type="submit">Find openings</button>
</form>
<p class="muted small">{len(accepting):,} listings accepting new patients · {hi:,} high confidence · refreshed {fmt_date(raw['generated'])}</p>
</section>
<section class="how"><div><span class="num">1</span><h2>We pull the official data</h2><p>Insurers must publish their directories as open data. We collect them all in one place.</p></div>
<div><span class="num">2</span><h2>We cross-check every listing</h2><p>Each provider is matched against the federal NPI registry: license status, address and phone.</p></div>
<div><span class="num">3</span><h2>You call the likely ones first</h2><p>Listings are ranked by confidence. Report what happened, and the next person gets better data.</p></div></section>
{link_grid(f"Popular in {city}", [(f"{CATS[c][0]} that take {raw['payers'][k]}", f"{city_path}{c}/{PAYER_SLUG[k]}/", "") for c in ("therapist", "psychiatrist", "primary-care") for k in active][:12])}"""
    page(ctx, "/", f"{BRAND} — In-Network Therapists & Doctors Accepting New Patients",
         "Find therapists, psychiatrists and doctors who take your insurance and are actually accepting new patients. Every listing cross-checked and scored for accuracy.",
         body, jsonld=[{"@context": "https://schema.org", "@type": "WebSite", "name": BRAND, "url": ctx["site"] + "/"}])
    static_pages(ctx, city_path, city)

    # SEO plumbing
    with open(os.path.join(DIST, "sitemap.xml"), "w") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
        for path in ctx["sitemap"]:
            f.write(f"<url><loc>{ctx['site']}{path}</loc><lastmod>{raw['generated']}</lastmod></url>\n")
        f.write("</urlset>\n")
    with open(os.path.join(DIST, "robots.txt"), "w") as f:
        f.write(f"User-agent: *\nAllow: /\nDisallow: {ctx['base']}/report/\nSitemap: {ctx['site']}/sitemap.xml\n")
    return providers, ctx


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--site-url", default="https://panelopen.com")
    args = ap.parse_args()
    if os.path.exists(DIST):
        shutil.rmtree(DIST)
    shutil.copytree(os.path.join(ROOT, "static"), DIST)
    partners_path = os.path.join(ROOT, "data", "partners.json")
    partners = json.load(open(partners_path)) if os.path.exists(partners_path) else []
    for path in sorted(glob.glob(os.path.join(ROOT, "data", "raw_*.json.gz"))):
        with gzip.open(path, "rt") as f:
            raw = json.load(f)
        providers, ctx = build(raw, args.site_url, partners)
        lv = defaultdict(int)
        for p in providers:
            lv[p["level"]] += 1
        print(f"{raw['city']}: {len(providers)} providers {dict(lv)}; {len(ctx['sitemap'])} indexable pages")


if __name__ == "__main__":
    main()
