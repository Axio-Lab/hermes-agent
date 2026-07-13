---
name: finding-your-first-customer
description: "Use when a user wants to find first customers, early adopters, design partners, beta users, startup validation prospects, urgent product opportunities, public pain or workaround signals, concierge offers, or an evidence-backed first-customer report from a product idea, URL, market, repository, or landing page."
version: 1.2.0
author: Verxio
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [research, customer-discovery, startup-validation, sales, prospects]
    related_skills: [customer-research, prospecting]
---

# Finding Your First Customer

## Overview

Turn a product idea, URL, landing page, repository, or market into a short, evidence-backed list of plausible first customers. Combine positive deviance discovery with public-signal prospecting: look for people already solving the problem manually, paying for inferior substitutes, complaining about the workflow, or showing a fresh adoption trigger.

Treat every candidate as a research hypothesis. Say "potential customer based on public signals," not "buyer," "lead," or "interested prospect" unless the user provides explicit first-party confirmation.

Read [references/research-framework.md](references/research-framework.md) before researching or scoring prospects. Read [references/report-artifact.md](references/report-artifact.md) before creating a final HTML report.

## When to Use

- Find a startup's first customers, early adopters, design partners, beta users, or first ten users.
- Validate whether a product idea is urgent enough to build.
- Identify public pain, workaround, switching, or "looking for a tool" signals.
- Turn a landing page, repo, or product description into an ideal customer profile and outreach shortlist.
- Create a source-based first-customer report with ranked prospects and manual outreach openers.

Do not use this skill for TAM estimates, broad competitive landscape work, high-volume lead scraping, automated messaging, private contact enrichment, or CRM imports.

## Core Principle

Zero-to-one products win by replicating deviant behavior: users already solving an urgent problem themselves, badly. The workaround is the thesis.

Fastest path:

```text
observe workaround -> identify deviant -> offer concierge outcome -> charge manually -> build
```

Prefer these signals, in order:

- `paid_workaround_exists` over `workaround_exists`
- `time_spent_on_workaround` over stated willingness to pay
- `urgency_this_week` over potential future need
- `one_charged_card` over ten enthusiastic signups
- `independent_parallel_invention` over one power-user workaround

## Workflow

### 1. Understand the Product

Inspect the supplied URL, repository, landing-page copy, or product description. Identify:

- product and promised outcome
- user, buyer, price point, and buying motion
- urgent job to be done
- current alternative or workaround
- likely adoption trigger
- geography, language, or segment constraints
- disqualifiers that should remove weak matches

Ask one concise question only when ambiguity would materially change the search. Otherwise infer safely and label the inference.

Completion criterion: the ICP is specific enough to reject a weak prospect without debate.

### 2. Run the Positive Deviance Tests

Only use behavioral evidence. Reject stated preferences unless paired with action.

Required tests:

1. **Workaround exists:** stop if there is no observable manual behavior.
2. **Paid workaround tier:** classify the workaround:
   - Tier 3: paid workaround, such as a consultant, VA, internal hire, or worse paid product.
   - Tier 2: embarrassment-cost workaround, such as awkward manual sharing, public correction, or client-visible cleanup.
   - Tier 1: free high-friction workaround, such as spreadsheets, copy-paste, manual tagging, scripts, or repeated DMs.
3. **Independent parallel invention:** prefer at least three independent examples of the same workaround.
4. **Urgency gate:** include only problems being solved now, not someday.
5. **Switching friction:** favor pure subtraction over behavior change.
6. **Build-vs-workaround delta:** proceed only when the product can be meaningfully better than the workaround.

If a paid workaround and a reachable deviant exist, move to a manual concierge offer before recommending more product buildout.

Completion criterion: every candidate has a cited behavior, workaround, pain, or trigger.

### 3. Build a Public-Signal Search Plan

Use [references/research-framework.md](references/research-framework.md). Search several buckets:

- explicit demand: "looking for," "recommend a tool," "alternative to," "does anything exist"
- pain: "takes hours," "manual," "frustrating," "hate," "difficult," "keeps breaking"
- workaround: spreadsheet, copy-paste, assistant, script, template, manual process
- switching: cancellation, migration, missing feature, pricing complaint, competitor frustration
- timing: hiring, launch, expansion, regulation, integration, new workflow, recent announcement

Prefer original public pages over snippets. Record URL, source type, visible date, observed evidence, and inference separately.

Completion criterion: the search covers at least three distinct query/source angles unless the user requested a quick pass.

### 4. Research Safely

- Use only public, intentionally shared professional or business information.
- Do not bypass login walls, paywalls, access controls, rate limits, or robots restrictions.
- Do not use data brokers, leaked datasets, private groups, personal email discovery, phone enrichment, or sensitive personal information.
- Do not infer protected traits or target people using health, financial hardship, political belief, sexuality, religion, or other sensitive attributes.
- Prefer companies, public professional profiles, public requests, product reviews, public community posts, GitHub issues, job posts, changelogs, and company announcements.
- Quote minimally and paraphrase by default. Link every material pain or timing signal.

Completion criterion: every material claim about a prospect can be traced to a public source or is clearly labeled as an inference.

### 5. Score, Deduplicate, and Stage Prospects

Score each prospect using the bundled framework:

- pain strength
- product fit
- timing
- public reachability
- evidence quality

Stages:

- **High intent:** publicly requesting a solution, actively switching, or paying for an inferior workaround.
- **Problem aware:** clearly describing the pain or expensive workaround.
- **Trigger present:** a current business event makes the product relevant.
- **Potential fit:** ICP match with incomplete evidence. Keep outside the primary shortlist.

Remove duplicates and weak matches. A prospect without a cited pain, need, workaround, or timing signal must not appear in the primary shortlist.

Completion criterion: the shortlist favors fewer high-confidence prospects over a generic lead list.

### 6. Draft Outreach, Never Send It

Write one short opener grounded only in cited public context:

```text
Saw your public note about [specific workflow/pain]. I am testing a way to [outcome] without [workaround]. I can do it manually for [price or next step] by [date]. Worth a quick look?
```

Rules:

- Keep the opener under 90 words by default.
- Do not pretend familiarity or mention unrelated personal details.
- Recommend the natural public or professional channel already associated with the source.
- Do not send messages, submit forms, connect, follow, comment, or create CRM records unless the user separately authorizes that action.

Completion criterion: the opener would still be truthful if the prospect read the report source-by-source.

### 7. Produce the Report

Lead with the most actionable evidence. Use this order:

1. **Verdict:** whether reachable early-customer signals exist.
2. **ICP:** buyer, user, trigger, workaround, and disqualifiers.
3. **Top prospect:** strongest evidence-backed candidate and why now.
4. **Prospect shortlist:** source, pain signal, score, stage, why now, channel, and opener.
5. **Repeated patterns:** pains and triggers appearing across prospects.
6. **Seven-day validation plan:** manual, low-volume outreach and concierge testing.
7. **Limits:** missing evidence and what real conversations must confirm.

Create a standalone HTML report unless the user explicitly requests chat-only output:

1. Structure the analysis JSON using [references/report-artifact.md](references/report-artifact.md).
2. Run `python3 scripts/generate_report.py <analysis.json> outputs/first-customer-report.html` from this skill directory, or pass absolute paths.
3. Verify the report includes prospect cards, source links, scores, repeated patterns, outreach plan, and limitations.
4. Return a clickable absolute file link.

## Modes

- **quick:** qualify up to five strong prospects.
- **standard:** qualify up to ten prospects across several source types. Use this by default.
- **deep:** qualify up to twenty prospects and map repeated pain patterns.
- **design-partners:** prioritize people willing to test and give feedback over immediate buyers.
- **b2b:** prioritize companies, public business triggers, and relevant decision roles.
- **community:** prioritize public discussion and explicit request signals.

## Required Outputs

### Deviance Table

| # | Observed behavior | Platform/context | Workaround method | Tier | Cost of workaround |
|---|---|---|---|---|---|
| 1 | | | | 1/2/3 | time + money + embarrassment |

Quantify where possible. "2 hrs/week x $50/hr = $100/week" beats "annoying."

### First-Customer Profile

```text
Who they are:        [specific description, not "SMBs" or "developers"]
Where to find them:  [exact source, community, job board, hashtag, or public page]
Why they care now:   [what changed recently or what they are already doing]
Evidence:            [source URL and observed signal]
Concierge offer:     ["I will do X manually for $Y by Friday"]
Outreach opener:     [exact message draft, not sent automatically]
```

### Verdict

| Verdict | Condition | Action |
|---|---|---|
| **Charge now manually** | Paid workaround exists, deviant identified, concierge feasible | Send a manual, authorized outreach and charge before building |
| **Interview and charge** | Workaround exists, deviants found, no paid signal yet | Talk to three deviants this week and attempt a paid concierge close |
| **Watch and wait** | Parallel invention pattern is emerging but evidence is thin | Monitor for 30 days and define a recheck trigger |
| **Discard** | No observable workaround or only low-friction free behavior | Kill or reframe the idea |

## Quality Bar

- Link every primary prospect to at least one meaningful public signal.
- Prefer ten strong matches over a long generic list.
- Make uncertainty and stale evidence visible.
- Separate observed evidence from inference.
- Keep outreach manual, respectful, and reversible.
- End with what must be validated through real conversations.

## Common Pitfalls

1. **Turning ICP fit into evidence.** Industry match is not enough; require public pain, workaround, demand, or timing.
2. **Treating a prospect as consented.** Public signals justify research, not claims of interest.
3. **Skipping the paid manual test.** If the product can be done manually, test willingness to pay before building.
4. **Over-personalizing outreach.** Use only the cited business context.
5. **Letting stale signals look fresh.** Show dates and lower timing scores when evidence is old.

## Verification Checklist

- [ ] ICP and disqualifiers are explicit.
- [ ] Positive deviance tests were applied.
- [ ] Each primary prospect has a public source URL.
- [ ] Scores use the five-dimension framework.
- [ ] Outreach drafts are clearly drafts and were not sent.
- [ ] Report labels prospects as potential customers based on public signals.
- [ ] HTML report, when requested or expected, was generated and opened or inspected.
