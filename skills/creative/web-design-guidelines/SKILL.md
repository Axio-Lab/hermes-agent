---
name: web-design-guidelines
description: "Web design rules: visual structure, readability, UI patterns, and common mistakes."
platforms: [linux, macos, windows]
---

# Web Interface Guidelines

## When to use

Load when reviewing or building landing pages, SaaS UI, dashboards, or product sites against design and UX best practices. Trigger on: review my UI, check accessibility, audit design, web design rules, or landing page feedback.

Review files for compliance with Web Interface Guidelines.

## How It Works

1. Fetch the latest guidelines from the source URL below
2. Read the specified files (or prompt user for files/pattern)
3. Check against all rules in the fetched guidelines
4. Output findings in the terse `file:line` format

## Guidelines Source

Fetch fresh guidelines before each review:

```
https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md
```

Use WebFetch to retrieve the latest rules. The fetched content contains all the rules and output format instructions.

## Usage

When a user provides a file or pattern argument:
1. Fetch guidelines from the source URL above
2. Read the specified files
3. Apply all rules from the fetched guidelines
4. Output findings using the format specified in the guidelines

If no files specified, ask the user which files to review.
