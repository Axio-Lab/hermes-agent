---
name: firecrawl-deep-research
description: "Deep web research: collect sources, extract facts, turn messy information into clear insights."
platforms: [linux, macos, windows]
---

# Firecrawl Deep Research

## When to use

Load for deep web research that needs sources, fact extraction, and synthesized insights. Trigger on: research this topic, deep dive, gather sources, or turn web research into a report.

Use this only for report-scale research: a rigorous, cited synthesis the user
explicitly wants delivered as a formal written report. If the request is a
product pick, a top-N list, a quick lookup, or anything answerable with a short
search, stop; do not use this skill, let the request be handled the standard
way.

## Onboarding Interview

Infer the topic and output format from context. Before starting, unless already specified, always ask one short question to define the scope:

> "How long do you want this research task to run?"

Map the answer to a depth tier in the Collection Plan below:
- A few minutes → Quick
- ~10-15 minutes → Thorough
- Longer / no limit → Exhaustive

If the topic itself is unclear, you may ask at most 1-2 additional concise
questions (topic, or a critical angle/source constraint). Otherwise proceed once
the runtime is set.

## Firecrawl Collection Plan

Use Firecrawl search and scrape through the CLI or equivalent tool surface. Match
depth to the runtime the user chose during onboarding.

- Quick (~a few minutes): search 3-5 queries and scrape 5-10 high-quality sources.
- Thorough (~10-15 minutes): search 5-10 queries from different angles and scrape 15-25 sources.
- Exhaustive (longer): search 10+ queries and scrape 25+ sources, including primary sources, research papers, expert views, and contrarian sources.

Avoid re-scraping URLs already returned with full content from a search-with-scrape result.

## Parallel Work

If appropriate, use sub-agents or equivalent parallel task runners by research angle:

- overview and definitions
- technical or implementation details
- market and industry context
- contrarian views, risks, and limitations
- primary sources and official docs

Each researcher should return claims, source URLs, source quality notes, and uncertainty.

## Final Deliverable

Default structure:

```markdown
# Deep Research: [Topic]

## Executive Summary
[2-3 paragraphs]

## Key Findings
[Numbered findings with source links]

## Detailed Analysis
[Themes, evidence, and synthesis]

## Contrarian Views And Risks
[Counterarguments, limitations, failure modes]

## Open Questions
[What remains uncertain]

## Sources
[Every URL used with a one-line note]

## Rerun Inputs
workflow: firecrawl-deep-research
topic: [topic]
depth: [quick/thorough/exhaustive]
output: [markdown/json/brief]
```

## Quality Bar

- Cite sources for factual claims.
- Prefer primary sources when available.
- Flag uncertainty and conflicting evidence.
- Synthesize instead of listing scrape summaries.
