---
name: youtube-to-ebook
description: "Turn YouTube channel uploads into polished long-read articles packaged as an EPUB ebook."
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [youtube, ebook, epub, newsletter, transcripts]
    category: media
    related_skills: [youtube-content, follow-leaders]
---

# YouTube to Ebook

## When to use

Load when the user wants to turn YouTube channels into a readable ebook, digest, or newsletter from video transcripts. Trigger on: YouTube to ebook, YouTube digest, turn channels into articles, EPUB from YouTube, video newsletter, or `/youtube-to-ebook`.

`SKILL_DIR` = directory containing this SKILL.md.

Transform latest uploads from favorite YouTube channels into magazine-style articles, then package them into an EPUB readable on any device.

## What you get

1. Fetch recent videos from configured channels (Shorts filtered out)
2. Extract transcripts for each video
3. Rewrite transcripts into polished long-read articles
4. Package articles into a single EPUB ebook

## Verxio orchestration (preferred)

On Verxio, **you** write the articles — do not require a separate Anthropic API key unless the user explicitly wants the standalone script pipeline.

### 1. Project workspace

Create a working folder, e.g. `~/youtube-to-ebook/`:

```text
~/youtube-to-ebook/
├── channels.txt      # one @handle per line
├── .env              # optional API keys (see config/env.example)
├── articles/         # generated markdown articles
└── output/           # EPUB files
```

Seed `channels.txt` from `SKILL_DIR/templates/channels.txt` if the user has no list yet.

### 2. Dependencies

Install into the Hermes-managed environment:

```bash
uv pip install google-api-python-client python-dotenv youtube-transcript-api markdown ebooklib requests
```

For the all-in-one upstream script path that calls Anthropic directly, also install `anthropic` and set `ANTHROPIC_API_KEY` in `.env`.

### 3. YouTube data sourcing

| Need | Verxio path | Script fallback |
|------|-------------|-----------------|
| Channel uploads | **YouTube** via **Skills → Connections** (Composio) when connected | `YOUTUBE_API_KEY` + `SKILL_DIR/scripts/get_videos.py` |
| Transcripts | `youtube-content` skill helper for single videos; batch via `get_transcripts.py` | `uv run python3 SKILL_DIR/scripts/get_transcripts.py` pattern from `main.py` |

Check **Verxio Connected Apps** before fetching. If YouTube is connected in Composio, prefer it for channel metadata and uploads lists.

### 4. Recommended agent workflow

1. **Setup** — Ask which channels to track; write `channels.txt`. Confirm ebook tone (magazine default).
2. **Fetch videos** — Run or adapt `SKILL_DIR/scripts/get_videos.py` from the project folder with `channels.txt` and `YOUTUBE_API_KEY` in `.env`, **or** fetch via Composio YouTube tools.
3. **Filter new videos** — Use `SKILL_DIR/scripts/video_tracker.py` logic to skip already-processed IDs; persist state under the project folder.
4. **Transcripts** — Fetch with `get_transcripts.py` helpers. Read `references/known-pitfalls.md` before batch runs.
5. **Write articles** — For each video, follow `prompts/write-article.md`. Include title + description for spelling fixes. Save markdown under `articles/`.
6. **Create EPUB** — Use `SKILL_DIR/scripts/send_email.py` `create_epub()` via a small driver script in the project folder, or import its EPUB builder after articles are ready.
7. **Deliver** — Give the user the EPUB path. Offer optional Gmail delivery if credentials exist in `.env`.

### 5. Standalone script pipeline (optional)

If the user wants the original automation with their own API keys:

```bash
cd ~/youtube-to-ebook
cp SKILL_DIR/config/env.example .env
# edit .env and channels.txt
uv run python3 SKILL_DIR/scripts/main.py
```

This path uses `write_articles.py` (Anthropic API) and optional Gmail delivery. On Verxio hosted inference, prefer the agent workflow above instead.

## Setup conversation

Ask together:

1. **Channels** — Which YouTube handles? (e.g. `@mkbhd`, `@veritasium`)
2. **Scope** — How many recent videos per channel? (default: latest 1 per channel per run)
3. **Style** — Magazine long-read (default), academic, casual blog, or technical
4. **Delivery** — EPUB file only, or also email?
5. **Schedule** — One-time now, or recurring local automation?

## Key files

| Path | Purpose |
|------|---------|
| `SKILL_DIR/scripts/get_videos.py` | Fetch latest uploads per channel |
| `SKILL_DIR/scripts/get_transcripts.py` | Batch transcript extraction |
| `SKILL_DIR/scripts/video_tracker.py` | Dedupe already-processed videos |
| `SKILL_DIR/scripts/send_email.py` | EPUB builder + optional Gmail send |
| `SKILL_DIR/scripts/main.py` | Full upstream pipeline |
| `SKILL_DIR/scripts/write_articles.py` | Anthropic-only article generation |
| `SKILL_DIR/prompts/write-article.md` | Agent article prompt (Verxio default) |
| `SKILL_DIR/references/known-pitfalls.md` | YouTube API quirks and fixes |
| `SKILL_DIR/config/env.example` | API key template |
| `SKILL_DIR/templates/channels.txt` | Starter channel list |

## Pitfalls

Read `references/known-pitfalls.md` before the first batch run. Highlights:

- Shorts: check `/shorts/` URL, not duration alone
- Chronological order: use uploads playlist, not Search API
- Transcript rate limits: sleep ~2s between fetches
- Cloud CI: transcript fetching often fails off-machine — schedule locally

## Credits

Adapted from [zarazhangrui/youtube-to-ebook](https://github.com/zarazhangrui/youtube-to-ebook) (MIT).
