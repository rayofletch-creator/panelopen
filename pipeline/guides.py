"""Evergreen guides that answer the questions people search before they look
for a provider. Each guide: slug, title (<60 chars), description, h1, intro,
sections [(h2, html)], faq [(q, a)]. Keep claims sourced and conservative."""

GUIDES = [
    {
        "slug": "find-a-therapist-that-takes-your-insurance",
        "title": "How to Find a Therapist That Takes Your Insurance",
        "desc": "A step-by-step way to find an in-network therapist who is actually accepting new patients: what to search, who to call first, and what to ask.",
        "h1": "How to find a therapist who takes your insurance — and has an opening",
        "intro": "Most people start with their insurer's directory and end up calling a dozen offices. Here is a faster order of operations.",
        "sections": [
            ("1. Know your exact plan", "<p>Network status is set per plan, not per insurer. Find the plan name on your insurance card or member portal (for example an HMO versus a PPO from the same company). Therapists can be in-network for one and not the other.</p>"),
            ("2. Decide what kind of care you need", "<p><strong>Therapists</strong> (licensed counselors, clinical social workers, marriage and family therapists) provide talk therapy. <strong>Psychologists</strong> also do testing and assessment. <strong>Psychiatrists</strong> and <strong>psychiatric nurse practitioners</strong> diagnose and prescribe medication. Many people see a therapist and, if needed, a prescriber separately.</p>"),
            ("3. Start with listings most likely to be real", "<p>Insurer directories are often out of date. On <a href=\"/\">Now Accepting</a> every listing is cross-checked against the federal NPI registry and ranked by confidence, so start with high-confidence listings and work down.</p>"),
            ("4. Call with a script", "<p>Ask three things: are you in-network for my specific plan, are you accepting new patients, and how soon is the first appointment? See <a href=\"/guides/questions-to-ask-when-calling-a-provider/\">questions to ask when you call</a>.</p>"),
            ("5. Keep a record", "<p>Note who you called, the date and what they said. If your insurer's directory was wrong, that record matters — see <a href=\"/guides/no-in-network-therapist-available/\">what to do if no in-network therapist is available</a>.</p>"),
            ("6. Consider telehealth", "<p>Many in-network therapists offer video sessions to anyone in the state where they're licensed, which widens your options well beyond your neighborhood.</p>"),
        ],
        "faq": [
            ("How do I know if a therapist is in-network?", "Ask the therapist's office whether they are in-network for your specific plan name, and confirm with your insurer by phone or member portal. Directory listings alone are not a guarantee."),
            ("Why do so many listed therapists say they are full?", "Insurer directories are often outdated. A 2023 U.S. Senate Finance Committee secret-shopper study found 80% of mental health listings checked in Medicare Advantage directories were inaccurate or unreachable."),
            ("Is telehealth therapy covered by insurance?", "Many plans cover telehealth therapy with in-network providers. Check your plan's benefits, and confirm the provider is licensed in your state."),
        ],
    },
    {
        "slug": "ghost-networks",
        "title": "What Is a Ghost Network? Why Directories Are Wrong",
        "desc": "Ghost networks are insurer directories full of providers who can't actually see you. What causes them, how common they are, and how to protect yourself.",
        "h1": "What is a ghost network?",
        "intro": "A \"ghost network\" is a health plan's provider directory that lists providers who are not actually available: they've left the network, moved, retired, stopped taking new patients, or never answer.",
        "sections": [
            ("How common are they?", "<p>A 2023 U.S. Senate Finance Committee secret-shopper study of Medicare Advantage plans found 80% of the mental health provider listings it checked were inaccurate or unreachable. Our own <a href=\"/reports/\">directory-accuracy reports</a> cross-check thousands of listings against the federal NPI registry.</p>"),
            ("Why do they happen?", "<p>Providers rarely notify every insurer when they change offices or close their panel, and directories are not always verified. Larger listed networks can also make a plan look better than it is.</p>"),
            ("What the law requires", "<p>Under the federal No Surprises Act, most private health plans must verify directory information at least every 90 days, update it within two business days of receiving changes, and respond to network-status questions within one business day. If you rely on a directory listing that wrongly showed a provider as in-network, your plan generally can't charge you more than in-network cost-sharing for that visit. Keep records of the listing and your calls.</p>"),
            ("How to protect yourself", "<ul class=\"plain\"><li>Confirm network status for your exact plan before the first visit.</li><li>Save a screenshot of the directory listing with the date.</li><li>Start with providers whose details match independent sources — that's what our confidence score measures.</li><li>Report wrong listings to your insurer, and to your state insurance regulator if it keeps happening.</li></ul>"),
        ],
        "faq": [
            ("What is a ghost network in health insurance?", "A provider directory that lists doctors or therapists who are not actually available to new patients in that network, because the listing is outdated, wrong, or the provider is not accepting patients."),
            ("Can I be charged out-of-network rates if the directory was wrong?", "Under the No Surprises Act, if you relied on a plan's directory listing that incorrectly showed a provider as in-network, most plans can't charge you more than your in-network cost-sharing. Keep a dated screenshot of the listing."),
        ],
    },
    {
        "slug": "no-in-network-therapist-available",
        "title": "No In-Network Therapist Available? What to Do",
        "desc": "If no in-network therapist has openings, you may have options: network adequacy complaints, single case agreements, out-of-network benefits and telehealth.",
        "h1": "Can't find an in-network therapist with openings? Your options",
        "intro": "If you've called through the list and nobody in-network can see you, you are not out of options. Here's what to try, roughly in order.",
        "sections": [
            ("Ask your insurer to find someone for you", "<p>Call the member services number on your card and ask them to locate an in-network provider who is accepting new patients. Ask for a reference number for the call.</p>"),
            ("Ask about a single case agreement", "<p>When a plan cannot provide timely in-network care, it may agree to cover an out-of-network provider at in-network cost-sharing for your case. This is called a single case agreement (or network gap exception). It is not guaranteed, but documenting the in-network providers you contacted strengthens the request.</p>"),
            ("Use out-of-network benefits", "<p>PPO and some other plans reimburse part of out-of-network care. Ask the provider for a superbill and submit it to your insurer.</p>"),
            ("File a complaint", "<p>Health plans regulated by your state must meet network adequacy standards. If you can't get timely care, you can file a complaint with your state insurance department (the Colorado Division of Insurance, or the Texas Department of Insurance). Mental health parity law also requires that mental health coverage not be more restrictive than medical coverage.</p>"),
            ("Widen the search", "<p>Try telehealth providers licensed in your state, nearby cities, and group practices, which often have more openings than solo clinicians. <a href=\"/\">Search Now Accepting</a> by city and insurer.</p>"),
        ],
        "faq": [
            ("What is a single case agreement?", "An arrangement where your health plan agrees to cover an out-of-network provider at in-network cost-sharing, usually because no suitable in-network provider is available in a reasonable time or distance."),
            ("Who do I complain to about no in-network providers?", "Start with your health plan's grievance process. For state-regulated plans, you can also contact your state insurance department; employer self-funded plans are overseen by the U.S. Department of Labor."),
        ],
    },
    {
        "slug": "does-insurance-cover-online-therapy",
        "title": "Does Insurance Cover Online Therapy? How to Check",
        "desc": "Many health plans cover online therapy with in-network providers. How to check your plan, what it should cost, and how to find someone who takes your insurance.",
        "h1": "Does insurance cover online therapy?",
        "intro": "Often, yes, as long as the therapist is in-network for your plan and licensed where you live. The details depend on your plan, so here's how to check before your first session.",
        "sections": [
            ("What usually decides coverage", "<ul class=\"plain\"><li><strong>Your plan.</strong> Coverage and cost-sharing are set per plan, not per insurer.</li><li><strong>The provider's network status.</strong> An online therapist still has to be in-network for your plan to get in-network prices.</li><li><strong>Licensing.</strong> A provider generally needs to be licensed in the state where you are during the session.</li></ul>"),
            ("How to check your plan", "<p>Call the member services number on your card, or check your member portal, and ask:</p><ul class=\"plain\"><li>Are telehealth mental health visits covered under my plan?</li><li>Is the cost the same as an office visit?</li><li>Is there a deductible to meet first?</li><li>Do I have to use a specific telehealth vendor?</li></ul>"),
            ("Therapy apps versus in-network therapists", "<p>Some subscription therapy apps don't bill insurance at all, or only work with certain plans. Before you sign up, ask whether the service bills your insurer directly and whether the therapist you'd see is in-network. A therapist who bills your plan directly often costs only your usual copay or coinsurance.</p>"),
            ("State rules", "<p>Many states, including Colorado and Texas, have laws on telehealth coverage for state-regulated health plans. Self-funded employer plans generally follow federal rules instead, so your HR team or plan documents are the best place to check.</p>"),
            ("Finding someone online who takes your insurance", "<p>Browse providers listing a telehealth location in <a href=\"/co/telehealth/\">Colorado</a> or <a href=\"/tx/telehealth/\">Texas</a>. Each listing is cross-checked against the federal NPI registry and scored for accuracy. Then use our <a href=\"/guides/questions-to-ask-when-calling-a-provider/\">call script</a> to confirm.</p>"),
        ],
        "faq": [
            ("Is online therapy covered by insurance?", "Many plans cover online therapy with in-network providers, often at the same cost as an office visit. Check your specific plan through member services or your member portal."),
            ("Can I see an online therapist in another state?", "Usually a therapist must be licensed in the state where you are during the session. Some professions have interstate agreements, so ask the therapist directly."),
        ],
    },
    {
        "slug": "questions-to-ask-when-calling-a-provider",
        "title": "What to Ask When Calling a New Therapist or Doctor",
        "desc": "A short call script for checking network status, new-patient openings, wait times and costs before you book — plus what to write down.",
        "h1": "What to ask when you call a new provider",
        "intro": "A two-minute call saves weeks. Read this script, then write down the answers.",
        "sections": [
            ("The script", "<p class=\"script\">\"Hi, I found [provider] listed as in-network with my [insurer + plan name] plan. Are they accepting new patients, and are they in-network for that specific plan? How long is the wait for a first appointment?\"</p>"),
            ("If they say yes", "<ul class=\"plain\"><li>Is there an intake call or paperwork first?</li><li>Do you offer telehealth?</li><li>What will my first visit cost with my plan?</li><li>Is a referral or prior authorization needed?</li></ul>"),
            ("If they say no", "<ul class=\"plain\"><li>Do you keep a waitlist, and how long is it?</li><li>Can you recommend a colleague who's taking new patients?</li><li>Is another clinician at the practice in-network and available?</li></ul>"),
            ("Write it down", "<p>Record the date, who you spoke to and what they said. If the listing was wrong, <a href=\"/report/\">tell us</a> — it improves the listing for the next person — and keep the record in case you need it with your insurer.</p>"),
        ],
        "faq": [
            ("What should I ask a therapist before booking?", "Confirm they are in-network for your exact plan, that they are accepting new patients, how long the wait is, whether they offer telehealth, and what your first visit will cost."),
        ],
    },
]
