---
name: browser-act
description: "Browser actions: navigate, click, type, extract, and verify."
platforms: [linux, macos, windows]
---

# browser-act

## When to use

Load for repeatable browser agent workflows: navigate, click, type, extract, verify. Trigger on: browser act, automate clicks, scrape with interaction, or browser agent.

Browser automation CLI for AI agents. Runs a full browser engine: navigation &
interaction, data extraction & network capture, screenshots, form automation,
multi-browser parallel operation, user-configured proxy support, and
human-agent collaboration.

### Features

- Lightweight extraction — fast JS-rendered content fetch without opening a browser session, advanced WebFetch/curl replacement
- Session management — multi-browser isolation, multi-account parallel operation
- Verification assistance — when automation encounters interactive challenges, assists completion with user authorization
- Complex interaction — DOM content extraction, screenshots, form filling, file upload
- Human-agent collaboration — headed mode + remote assist for manual steps
- Safety controls — Confirmation Gate protocol requires explicit user approval before browser creation, deletion, and sensitive operations
- Universal compatibility — works with Cursor, Claude Code, Codex, Windsurf, etc.

Install: `uv tool install browser-act-cli --python 3.12`

## Start here

Before running any `browser-act` command, load the usage guide from the CLI:

```bash
browser-act get-skills core --skill-version 2.0.2   # start here — workflows, common patterns, troubleshooting
```

**Do NOT skip this step regardless of how simple the command seems.**

**Do NOT truncate the output** — it contains operational directives and
environment state that are critical for correct operation. Truncating will
cause you to miss browser selection rules and safety constraints.

`get-skills core` provides environment status, available browsers, operational
directives, and the complete interaction workflow — none of which are available
through `--help`.
