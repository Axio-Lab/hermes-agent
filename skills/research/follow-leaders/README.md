# Follow Leaders (Verxio bundled skill)

Industry digest bundled under `skills/research/follow-leaders/`. Tracks real operators on YouTube, **LinkedIn**, X, Reddit, Instagram, TikTok, Facebook, blogs, and newsletters for any industry.

## Verxio usage

1. Enable the skill on **Skills**.
2. Connect apps on **Skills → Connections** (YouTube, LinkedIn, Twitter, Reddit, Instagram, TikTok, Facebook via Composio when available).
3. Ask: "set up follow leaders", "find SaaS leaders on LinkedIn", or "follow leaders in fintech".

For a new industry, the agent **researches leaders from the web** (`references/discover-leaders-from-web.md`), then saves the list to `~/.follow-leaders/industries/`.

Composio is preferred for connected apps; public RSS/JSON/web fetch is the fallback.

## Layout

```
follow-leaders/
├── SKILL.md
├── references/discover-leaders-from-web.md
├── industries/
├── prompts/
├── scripts/          # YouTube RSS + Reddit JSON only
└── examples/
```

User config: `~/.follow-leaders/`

## License

MIT (remixed from [zarazhangrui/follow-builders](https://github.com/zarazhangrui/follow-builders)).
