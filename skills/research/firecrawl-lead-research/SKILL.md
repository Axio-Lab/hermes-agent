---
name: firecrawl-lead-research
description: "Lead research: companies, websites, signals, context, and outreach angles."
platforms: [linux, macos, windows]
---

# Firecrawl Lead Research

## When to use

Load for B2B lead research: companies, signals, context, outreach angles. Trigger on: research leads, company research, sales research, or find prospects.

Use this to create a concise, actionable pre-meeting brief.

## Onboarding Interview

Infer the company, person, meeting context, and desired brief depth from context. If the company is clear, proceed immediately.

Ask at most 1-3 concise questions only if blocked, such as the company/person to research or the meeting context.

## Firecrawl Collection Plan

Use Firecrawl search and scrape to gather:

- company website, about, product, pricing, careers, team, and customer pages
- recent news, funding, launches, hiring, partnerships, and press
- public person profiles, talks, posts, interviews, and role/background
- relevant industry context and likely business challenges

## Parallel Work

If appropriate, use sub-agents or equivalent parallel task runners:

- Company Profile researcher
- Recent News and Activity researcher
- Person researcher
- Industry/Pain Point researcher

Each researcher should return source URLs and only evidence-backed claims.

## Final Deliverable

```markdown
# Lead Brief: [Company]

## Company Overview
[What they do, stage/size signals, products, customers]

## Recent Activity
[News, launches, funding, hiring, partnerships]

## Key People
[Relevant people and public background]

## Talking Points
[5-7 specific conversation starters]

## Likely Pain Points
[Evidence-backed hypotheses]

## Outreach Angle
[Suggested positioning or next step]

## Sources
[URLs used]

## Rerun Inputs
workflow: firecrawl-lead-research
company: [name/url]
person: [optional]
context: [meeting context]
```

## Quality Bar

- Keep it concise and useful before a meeting.
- Do not fabricate personal details.
- Clearly separate facts from inferred pain points.
