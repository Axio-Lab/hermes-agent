# Discovering industry leaders from the web

Use this when there is no bundled `industries/<slug>.json`, the user wants a refresh,
or they name an industry without a curated list.

## Goal

Build a list of **operators and original thinkers**, not commentators or engagement
farmers. Every person in the final JSON should have a clear `why` tied to building,
running, or researching in that industry.

## Search pass (run several queries)

Adapt `[industry]` to the user's niche (e.g. "B2B fintech", "climate SaaS", "D2C beauty").

```
[industry] founders CEOs operators 2026
[industry] best podcasts operators not influencers
[industry] subreddit operators discussion
site:linkedin.com/in [industry] founder CEO
[industry] conference speakers operators
[industry] newsletter written by founder
[industry] thought leaders who actually build
```

Also search for industry trade publications, Y Combinator / accelerator batches, and
"who to follow in [industry]" lists, then **verify** each name against the leader
bar below.

## Leader bar (include only if most are true)

- Holds or held an operating role (founder, exec, PM, engineer, researcher with
  shipped work) in this industry
- Publishes original analysis, lessons, or firsthand accounts (not only hot takes)
- Has a track record you can point to (company, product, research, years in role)
- Is not primarily a reaction/commentary or aggregator account

Exclude: pure finfluencers, motivational posters, repost accounts, anonymous meme
pages, and "growth hack" threads with no operating depth.

## Collect per platform

For each accepted leader, capture every channel they **actually use**:

| Field | What to find |
|---|---|
| `xAccounts` | Handle + `https://x.com/...` if active on X |
| `linkedInProfiles` | `https://www.linkedin.com/in/...` if they post or write there |
| `instagramAccounts` | Only if substantive operator content (often skip) |
| `tiktokAccounts` | Only if substantive operator content (often skip) |
| `facebookPages` | Company or community pages with real updates |

Also collect:

- `podcasts` they host or frequently appear on (YouTube channel IDs when findable)
- `subreddits` where operators in this niche discuss (not meme subs)
- `blogs` and `newsletters` they write

Use `web_fetch` on profile pages, podcast show notes, and conference agendas to
confirm roles. Prefer primary sources over listicles.

## YouTube channel IDs

Public RSS needs `youtubeChannelId`. If only `@handle` is known:

1. `web_fetch` the channel page or use Composio YouTube tools if connected
2. Resolve `UC...` before saving the industry file
3. Leave empty only if unresolved; note in setup that RSS fetch may skip that show

## Output

Save to `~/.follow-leaders/industries/<industry-slug>.json` using
`industries/default-template.json` as schema. Show the user the proposed list,
counts per platform, and ask for cuts/additions before saving.

## After discovery

Run the connections check (YouTube, LinkedIn, Twitter, Reddit, Instagram, TikTok,
Facebook on Composio) and the first digest using Composio-first sourcing from
`SKILL.md`.
