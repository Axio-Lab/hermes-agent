---
name: fishaudio-voices
description: "Manage private Fish voices with explicit consent."
version: 1.0.0
author: Axio Lab
license: MIT
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [Audio, Voice, TTS, Fish Audio, Privacy]
    category: media
---

# Fish Audio Voices Skill

Create and manage private Fish Audio voices from audio the user attached to
the current session. The backend enforces ownership, attachment scope,
privacy, and confirmation; these instructions explain the safe interaction.

## When to Use

- The user explicitly asks to create a Fish voice from attached audio.
- The user asks to list, inspect, select, or delete one of their Fish voices.
- Do not infer consent from an attachment alone.

## Prerequisites

- Fish Audio must be configured with `FISH_AUDIO_API_KEY`.
- The Fish Audio plugin and its `fishaudio` toolset must be enabled.
- Creation requires an opaque `fishatt_` attachment handle issued by Hermes.

## How to Run

1. Ask the user for a short alias and an explicit consent attestation.
2. Call `fishaudio_voice_create` with the attachment handle, alias, and receipt.
3. Relay the exact confirmation phrase returned by the tool.
4. Wait for the user to type that phrase in a new message.
5. Call the same tool again with unchanged inputs and that confirmation.
6. Offer `fishaudio_voice_set_default` after successful creation.

Deletion follows the same two-turn confirmation flow with
`fishaudio_voice_delete`.

## Quick Reference

- `fishaudio_voice_create`: private creation from a scoped audio handle.
- `fishaudio_voice_list`: caller-owned profile catalog.
- `fishaudio_voice_get`: one owned voice by alias or catalog ID.
- `fishaudio_voice_set_default`: choose the profile TTS default.
- `fishaudio_voice_delete`: delete an owned voice with confirmation.

## Procedure

Treat a returned `confirmation_required` result as a hard stop. Never call the
tool again until the user personally types the exact phrase. Keep the alias,
attachment handle, consent receipt, and requested action unchanged.

After creation, mention that the provider confirmed `private` visibility.
Refresh a voice picker when the result contains `refresh_voices: true`.

## Pitfalls

- Never pass a filesystem path, URL, model ID supplied outside the owned
  catalog, transcript, or raw audio bytes to these tools.
- Never fabricate, paraphrase, or automatically echo a confirmation as user
  consent.
- Group/channel messages, webhook/cron calls, anonymous actors, stale handles,
  and cross-session handles are intentionally denied.
- Prompt text is not a security boundary; backend checks remain authoritative.

## Verification

- Creation reports `visibility: private` and a voice ID.
- Listing shows the new alias only to its owner.
- Setting default reports `is_default: true`.
- Deletion reports `deleted: true` and removes the voice from the live catalog.
