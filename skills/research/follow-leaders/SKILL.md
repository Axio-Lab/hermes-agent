---
name: follow-leaders
description: "Industry digest tracking real operators across YouTube, LinkedIn, X, Reddit, and other social platforms."
platforms: [linux, macos, windows]
---

# Follow Leaders, Not Influencers

## When to use

Load when the user wants to follow operators instead of influencers, set up an industry digest, discover who the real leaders are in a field, or monitor what top people are saying on social and podcast channels. Trigger on: follow leaders, industry digest, follow leaders in [industry], LinkedIn leaders, who should I follow in [industry], find industry leaders, weekly roundup, thought leaders, or social media monitoring for an industry.

An AI-powered digest that tracks real operators, founders, and original thinkers in **any industry**, then remixes what they publish into a short, skimmable digest.

**Philosophy:** Follow people who do the work and have original opinions earned from practice, not people optimizing for engagement.

## What You Get

A digest (in chat, or scheduled when configured) with:

- New podcast / YouTube appearances from tracked shows
- LinkedIn posts and articles from curated operator profiles
- Key takes from X/Twitter, Instagram, TikTok, and Facebook (when tracked)
- High-signal Reddit threads
- Blogs and newsletters when listed
- Links to every source

Bundled starter lists live under `industries/` (fintech, healthtech, e-commerce, climate-tech, creator-economy, real-estate, marketing, logistics-supply-chain). **Any industry:** discover leaders from the web first (see below).

## Discover industry leaders from the web

When there is no matching bundled file, the user names a new niche, or they ask who to follow:

1. Read and follow `references/discover-leaders-from-web.md` end to end.
2. Run multiple `web_search` and `web_fetch` passes (LinkedIn profiles, podcast guests, conference speakers, operator newsletters).
3. Propose a curated list with counts per platform; confirm with the user.
4. Save to `~/.follow-leaders/industries/<industry-slug>.json` (schema: `industries/default-template.json`).

Do not guess leaders from memory alone when building a new industry file. Ground the list in live web research.

## Verxio data sourcing (Composio first, public fallback)

On Verxio, prefer **Skills → Connections** (Composio). Check **Verxio Connected Apps** in system context before fetching.

| Source | Composio app (if connected) | Public fallback |
|---|---|---|
| YouTube | `youtube` — channel uploads, metadata, captions via `mcp_composio_*` tools | Channel RSS (`fetch-content.js`); **`youtube-content`** for transcripts |
| LinkedIn | `linkedin` — profile posts, articles, company updates | `web_search` / `web_fetch` on public post URLs (limited; suggest connecting LinkedIn) |
| X / Twitter | `twitter` | `web_search` / `web_fetch` on public profiles (thinner coverage; say so if asked) |
| Reddit | `reddit` | Public `.json` listings via `fetch-content.js` |
| Instagram | `instagram` | `web_fetch` on public profile/post URLs when Composio not connected |
| TikTok | `tiktok` | `web_search` / `web_fetch` on public profile URLs |
| Facebook | `facebook` | `web_fetch` on public page posts when Composio not connected |
| Blogs / newsletters | — (no standard Composio app) | `web_fetch` / RSS when available |

**Rules:**

1. If a Composio app is connected for a source, use it. Do not silently fall back when the connected app can fetch the data.
2. If not connected and richer access is needed, tell the user to connect the app under **Skills → Connections**, then use public fallback for this run if possible.
3. Discover tool slugs with `mcp_composio_COMPOSIO_SEARCH_TOOLS`; execute with `mcp_composio_COMPOSIO_MULTI_EXECUTE_TOOL`.
4. Scripts under `scripts/` only implement **YouTube RSS + Reddit JSON**. All other platforms are agent-orchestrated (Composio or web tools).

## Quick Start

1. "Set up follow leaders" or "follow leaders in [industry]" or "find fintech leaders on LinkedIn"
2. Discover or load industry list (web research if needed)
3. Check Connections; run first digest immediately

## Setup Conversation

### 1. Industry and leader list

`SKILL_DIR` = directory containing this SKILL.md.

- Check `SKILL_DIR/industries/` and `~/.follow-leaders/industries/`.
- **Bundled match:** report counts (podcasts, LinkedIn, X, Reddit, social); ask use as-is or edit.
- **No match:** run `references/discover-leaders-from-web.md`; save user-approved JSON under `~/.follow-leaders/industries/`.
- Screen out commentary/reaction accounts; respect user overrides.

### 2. Connections check (Verxio)

Before the first fetch, note connected apps among: **YouTube**, **LinkedIn**, **Twitter**, **Reddit**, **Instagram**, **TikTok**, **Facebook**. Suggest **Skills → Connections** for any gap the user cares about.

### 3. Frequency, delivery, language

Default Verxio: **in-chat** digest on demand. Optional Hermes cron if user wants schedule. Default language: English.

### 4. Save config

Write `~/.follow-leaders/config.json` (schema: `config/default-config.json`).

Public script path (YouTube + Reddit only):

```bash
node SKILL_DIR/scripts/fetch-content.js <industry-slug>
node SKILL_DIR/scripts/prepare-digest.js <industry-slug>
```

Merge Composio/web results for LinkedIn and other social into the same remix step.

### 5. First digest now

Fetch all sources (Composio where connected), remix with `prompts/`, show sample before finishing setup.

## Customizing summaries

| Prompt | Use for |
|---|---|
| `summarize-podcast.md` | YouTube / podcast episodes |
| `summarize-linkedin.md` | LinkedIn posts and articles |
| `summarize-tweets.md` | X / Twitter |
| `summarize-social.md` | Instagram, TikTok, Facebook |
| `summarize-reddit.md` | Reddit |
| `digest-intro.md` | Overall structure and tone |
| `translate.md` | Non-English output |

User overrides: `~/.follow-leaders/prompts/`.

## Privacy

Composio uses the user's connected accounts via Verxio's bridge. Public fallback uses public endpoints only. State under `~/.follow-leaders/`.

See `examples/sample-digest.md` for output shape.
