# PanelOpen

Find in-network therapists and doctors who are actually accepting new patients.
Static, SEO-first site generated from public data. Pilot city: Denver, CO.

## How it works

1. `pipeline/fetch.py` pulls the public provider directories that federal rules
   (CMS Interoperability rule, Da Vinci PDex Plan-Net FHIR) require insurers to
   publish: in-network status, the "accepting new patients" flag, plan networks,
   office location and phone. Live sources: Cigna and UnitedHealthcare (Optum). Humana's API can't be
   searched by location, and Kaiser's records carry no specialty codes, so both
   are wired in but contribute nothing yet. Each provider is then looked up by NPI in the federal NPPES
   registry.
2. `pipeline/build.py` merges listings per NPI, runs 7 cross-checks (accepting
   flag, record freshness, active NPI, ZIP match, phone match, multi-insurer,
   no contradictions) and renders static HTML to `dist/`.

```bash
python3 -I pipeline/fetch.py --city Denver --state CO
python3 -I pipeline/build.py --site-url https://your-domain.com
python3 -m http.server -d dist 8080
```

HTTP responses are cached in `.cache/`; delete it to force a fresh pull.

## Deployment (GitHub Pages)

`.github/workflows/deploy.yml` builds and deploys on every push to `main`. Every
Monday it also re-pulls insurer data, commits the refreshed `data/raw_*.json.gz`
and redeploys. To trigger a refresh by hand, use Actions → "Build and deploy" →
Run workflow.

Repo variables (Settings → Secrets and variables → Actions → Variables):
- `SITE_URL`: set this when you add a custom domain (e.g. `https://panelopen.com`).
  It's used for canonical URLs and the sitemap.
- `MAX_LOCATIONS`: insurer locations pulled per insurer (default 1500). Raise it
  for fuller coverage; the run gets slower.

## SEO structure

- `/co/denver/` city hub → `/co/denver/<care-type>/` → `/co/denver/<care-type>/<insurer>/`
  (the "therapist that takes cigna denver" long tail), `/insurance/<insurer>/`,
  `/provider/<name>-<npi>/`.
- Every page is pre-rendered HTML with a unique title and meta description, a
  canonical URL, breadcrumbs, and JSON-LD (BreadcrumbList, ItemList, FAQPage,
  Physician/MedicalBusiness with `isAcceptingNewPatients`).
- Pages with fewer than 3 accepting providers and providers who are not accepting
  are `noindex` to avoid thin content. `sitemap.xml` and `robots.txt` are generated.
- No client-side rendering, so there's nothing for crawlers to wait on.
  `app.js` only adds filters.

## Monetization (built in)

| Stream | Where it lives | Notes |
| --- | --- | --- |
| Provider subscriptions ($0 / $39 / $149 mo) | `/for-providers/`, "Claim this profile" on every provider page | Also improves accuracy: providers confirm their own availability |
| Labelled partner referrals | `data/partners.json` → shows on listing pages | Telehealth services that take insurance; marked `rel="sponsored"`. Nothing shows until you add real partners (copy `partners.example.json`) |
| Data / accuracy reports (B2B) | `/about/` disclosure | Aggregated directory-accuracy data for employers, brokers, regulators |
| Featured placement (Group tier) | Not rendered yet | Must be labelled and must never change confidence scores |

Deliberately excluded: third-party ad pixels and retargeting. Health-search
tracking has drawn FTC enforcement (BetterHelp, GoodRx), and it would undercut
the trust the site depends on.

## Before launch

- Connect the report and claim forms to a backend (they currently show a demo message).
- Add more insurers. Aetna, Anthem/Elevance and the BCBS plans publish directories
  too, but they need registration or use different endpoints.
- Add a provider-verification flow for claimed profiles (contact via the NPPES phone or email).
- Get a legal review of the disclaimers.
