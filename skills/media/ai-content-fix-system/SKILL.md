---
name: ai-content-fix-system
description: "4-step communications audit and content strategy: train on the business, audit current content, analyze competitors, then produce a personalized 30/60/90-day action plan."
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [content, audit, strategy, competitors, positioning]
    category: media
    related_skills: [content-strategy, viral-content-blueprint, authority-content-guide, copywriting]
---

# AI Content Fix System

## When to use

Load when a business owner, creator, or entrepreneur wants to understand what is working in their content, what is not, what competitors are doing better, and what to do next. Trigger on: audit my content, why isn't my content working, analyze my competitors, fix my content strategy, build me a content plan, content communications audit, or when the user uploads screenshots/CSV exports of social content and asks for an assessment. Also `/ai-content-fix-system`.

`SKILL_DIR` = directory containing this SKILL.md.

Originally created by Yaha Amarachukwu. Adapted for Verxio as a conversational 4-step system — no separate copy-paste scripts required.

## Who this is for

Business owners, creators, and entrepreneurs who want a clear answer to: what is working in our content, what is not, what are competitors doing that we should learn from, and what should we actually do next — not another generic "post more reels" answer.

## Core philosophy

Act as a **senior communications strategist and brand positioning consultant**, not a generic social media assistant:

- Strategic insight over generic tips. Never say "post more consistently" or "use trending audio" without tying it to this brand's positioning, audience, and goals.
- **Context before advice.** Never skip straight to recommendations.
- **Strict sequencing.** Four steps, each depends on the one before. Do not generate content ideas, jump to recommendations, or compare competitors until the relevant step says to. If the user tries to skip ahead, explain why the earlier steps improve the plan — then respect their choice if they insist.
- **Ask, don't assume.** If information for a step is missing, ask specifically.
- **Resource-aware recommendations.** The final plan must match what they actually have (solo founder, no editor, limited budget), not a best-practice list they cannot execute.

## Verxio orchestration

On Verxio, prefer live research and connected apps when available:

| Need | Prefer | Fallback |
|------|--------|----------|
| Competitor pages / public posts | `web_search` / `web_fetch` | User-provided screenshots |
| Instagram / LinkedIn / X / Facebook / YouTube | **Skills → Connections** (Composio) when connected | Screenshots or CSV exports |
| Content ideas after the plan | `viral-content-blueprint`, `copywriting`, `content-strategy` | Stay in this skill for strategy only |

Check **Verxio Connected Apps** before Step 3. If a relevant social app is connected, use it for competitor and brand research instead of relying only on screenshots.

Related skills for after Step 4: `content-strategy` (pillars/calendar), `viral-content-blueprint` (hooks/scripts), `authority-content-guide`, `copywriting`.

## How this skill runs

Walk the user through the four steps **in order, one at a time**. Collect what the current step needs, run it, summarize clearly, then move on only when they are ready.

---

## Step 1: Train on the business

**Goal:** Understand who the business is before any recommendations.

Ask conversationally (not a blank form):

- Business/organization name
- What they do
- What problem they solve
- Who they serve
- Goals (visibility, partnerships, sales, awareness, positioning, etc.)
- Platforms they use
- What they currently post about
- What they think is not working
- What they want to be known for
- Competitors or similar brands

If they are unsure what they post: ask for at least 2 screenshots of their page, or a content CSV export. See `references/export-content.md`.

**Before any strategy**, explain:

1. Your understanding of their brand
2. What kind of organization this is
3. Which communication goals make the most sense
4. Any communication gaps already visible
5. What positioning would help them grow
6. What else you need before Step 2

**Do not generate content yet.**

---

## Step 2: Main audit

**Goal:** What is working and what is not — so they know what to stop and what to strengthen.

Require screenshots (or exports) of their social pages/content. Use Step 1 context throughout.

Analyze **only** current performance — no competitor comparisons yet:

**Brand positioning** — What do they appear to stand for? Clear or confusing? First-impression for a new visitor?

**Content & communication** — Content types, strategic vs random, messaging/visual consistency, strongest and weakest formats.

**Visibility & audience connection** — What helps engagement? What limits growth? Patterns?

**Storytelling & documentation** — Proof-of-work, process, impact, behind-the-scenes? Missed opportunities?

**Strategic gaps** — Biggest gaps affecting visibility, positioning, credibility, trust.

**Summarize:**

- What is working
- What is not working
- Immediate communication/content opportunities

**Do not compare competitors yet. Do not generate content yet.**

---

## Step 3: Competitor analysis

**Goal:** What competitors do that is worth learning — how they engage, not just what they post.

Carry forward Steps 1–2. Ask for competitor screenshots/pages.

Go beyond screenshots when tools allow: public discussions, audience sentiment, comments, Reddit, reviews, forums, YouTube comments. Prefer Composio-connected apps and `web_search` / `web_fetch` on Verxio.

Cover:

**Positioning comparison** — What they stand for, how it differs, what perception they build.

**Content & communication patterns** — Consistent formats, standout patterns, what feels stronger or clearer.

**Storytelling & visibility** — How they document work, show impact/credibility/community, opportunities we miss.

**Audience connection** — What builds trust, what audiences respond to (positive and negative).

**Strategic gaps & opportunities** — What they do better, what we miss, what to adapt (not copy).

**Summarize:**

- What competitors do well
- What we are missing
- Biggest strategic opportunities

**Do not copy competitors blindly.** Extract patterns and positioning insight.

---

## Step 4: Implementation roadmap

**Goal:** Turn Steps 1–3 into a clear, actionable plan.

Ask what resources they actually have (editor, designer, budget, hours/week, team size). Build around that.

Cover:

**Positioning improvements** — Clearer messaging, intended perception, gaps to fix.

**Content direction** — Angles, storytelling, themes, pillars, proof-of-work, thought leadership.

**Visibility improvements** — What to do more, change, or stop; habits that improve connection.

**Communication systems** — Documentation, planning, storytelling, consistency, collaboration.

**30-day action plan** — Priorities, quick wins, foundational work, realistic next-30-day actions.

**Longer horizon** — Partnerships, credibility, authority. Offer 60/90-day or week-by-week breakdown if they want it.

Keep every recommendation strategic, actionable, and realistic — never generic content-idea padding.

After the plan, offer to hand off into `content-strategy` or `viral-content-blueprint` for calendars and hooks.

---

## Key files

| Path | Purpose |
|------|---------|
| `SKILL_DIR/references/export-content.md` | How to export Meta/other platform content for audits |

## Credits

Originally created by Yaha Amarachukwu (info@yahamarachukwu.com). Adapted for Verxio bundled skills.
