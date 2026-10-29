# Now Accepting — SEO plan

Goal: rank on page 1 for "[care type] that takes [insurer] in [city]" searches
first, then broader terms like "therapist accepting new patients denver".

## Realistic timeline

| When | What to expect |
| --- | --- |
| Week 1–2 | Google indexes the home page, report, city hubs and some listing pages |
| Month 1–2 | Long-tail pages (e.g. "psychiatrists in Boulder that take Cigna") start appearing on pages 1–3 |
| Month 3–6 | With 20–50 good backlinks, city + care-type pages compete on page 1 |
| 6–12 months | Broad terms ("therapist near me") stay dominated by Psychology Today, Zocdoc and insurers; compete there only with strong authority |

New domains rarely rank for competitive health terms in the first months.
Google holds health ("Your Money or Your Life") sites to a higher trust bar,
so links from credible sites matter more than anything else on this list.

## Done (technical)

- Pre-rendered pages, unique titles and descriptions, canonical URLs, sitemap, robots.txt
- Structured data: BreadcrumbList, ItemList, FAQPage, Physician/MedicalBusiness, Article, Organization
- "At a glance" facts unique to every listing page (no near-duplicate templates)
- Low-confidence provider profiles noindexed so crawl goes to strong pages
- Google Search Console verified; sitemap submitted
- IndexNow (Bing, Yandex, Seznam, Naver; Bing powers DuckDuckGo and ChatGPT search):
  all URLs submitted, and every weekly refresh re-submits automatically
- Linkable asset: /reports/colorado-insurance-directory-accuracy/
- Keyword-first titles (≤ ~65 chars) and descriptions (≤ 155 chars); no duplicates
- Paginated pages 2+ noindexed (still followed) to concentrate ranking signals
- Every profile links to up to six similar strong providers and its listing pages
- Four guides targeting informational searches, with Article + FAQ schema:
  /guides/find-a-therapist-that-takes-your-insurance/, /guides/ghost-networks/,
  /guides/no-in-network-therapist-available/, /guides/questions-to-ask-when-calling-a-provider/
- Sitemap index split into providers / listings / pages (separate Search Console reports)
- Social card (og:image), 404 page, IndexNow ping on every push
- Indexing requested in Search Console (Oct 29): home, report, find-a-therapist guide
- Audit (Oct 29): 5,407 pages, 0 broken internal links, 0 invalid JSON-LD, 0 duplicate titles

## Do this week (needs you)

1. **Bing Webmaster Tools**: sign in at bing.com/webmasters and choose "Import from
   Google Search Console". One click; gives Bing data and its own index report.
2. **Request indexing in Search Console** for up to ~10 URLs a day (Google's
   quota). Priority order:
   - /co/denver/  /co/colorado-springs/  /co/aurora/  /co/boulder/  /co/fort-collins/  /co/lakewood/
   - /guides/ghost-networks/  /guides/no-in-network-therapist-available/
   - /co/denver/therapist/cigna/  /co/denver/therapist/unitedhealthcare/
   - /co/denver/psychiatrist/  /co/colorado-springs/therapist/
3. **Google Business Profile**: skip. A directory without a public office
   doesn't qualify, and faking one risks suspension.

## Earn links (the part that moves rankings)

Lead with the data report. It's original, local and newsworthy.

**Local press (best links).** Pitch the report to health and consumer reporters at:
Denver Post, Colorado Sun, Denverite, CPR News, Axios Denver, 9News, Denver7,
Colorado Springs Gazette, Boulder Daily Camera, Coloradoan (Fort Collins).

> Subject: Data: only 22% of Colorado provider listings pass basic accuracy checks
>
> Hi [name], I run Now Accepting, which pulls the provider directories insurers
> are required to publish and cross-checks them against the federal NPI registry.
> In 4,207 Colorado listings, only 22% passed enough checks to be considered
> reliable, the listed phone number matched the federal record just 33% of the
> time, and UnitedHealthcare marks every provider as "accepting new patients."
> Full methodology: nowacceptingpatients.com/reports/colorado-insurance-directory-accuracy/
> Happy to pull numbers for a specific city, insurer or specialty.

**Advocacy and nonprofits** (they link to helpful tools): NAMI Colorado, Mental
Health Colorado, Colorado Consumer Health Initiative, Colorado Center on Law and
Policy, the Colorado Division of Insurance consumer pages, county public health
departments, university counseling centers (CU Boulder, DU, CSU, UCCS).

**Community (traffic + some links).** Answer real questions, disclose you built it:
r/Denver, r/ColoradoSprings, r/boulder, r/FortCollins, r/therapy,
r/mentalhealth, r/HealthInsurance. Search each for "in-network therapist" and
"accepting new patients".

**Providers.** Every claimed profile is a reason for a practice to link "Find us
on Now Accepting". Add a small badge for their website once claims start.

**Directories and tool lists.** Product Hunt launch; submit to health-tech
resource lists; Hacker News "Show HN" (the open-data angle does well there).

## Keep improving on-site

- Add cities in other states (each adds ~1,000 pages); Texas and Florida have
  large Cigna and UHC networks.
- Publish a monthly update of the report (fresh data earns repeat coverage).
- Put a real person's name and background on /about/. Google weighs who stands
  behind health information.
- Track in Search Console: Pages (indexing), Performance (queries), and
  Enhancements (structured data errors).
