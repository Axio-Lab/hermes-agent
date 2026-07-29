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

Design, create, and manage private Fish Audio voices. The backend enforces
ownership, session scope, privacy, expiry, and confirmation; these
instructions explain the safe interaction.

## When to Use

- The user explicitly asks to create a Fish voice from attached audio.
- The user asks to explore a voice from a written description and preview
  script before saving it.
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

For prompt-driven design:

1. Ask for the desired voice description and a short preview script.
2. Call `fishaudio_voice_design_preview`; relay each returned `MEDIA:` value
   unchanged so the client or gateway delivers it as an audio attachment.
   Do not invent, alter, or describe its storage path in prose.
3. Let the user listen to the returned scoped preview candidates. If they
   reject them, call `fishaudio_voice_design_discard`.
4. After the user selects one, call `fishaudio_voice_design_persist` with its
   unchanged `fishpreview_` handle and a private alias.
5. Stop for the server confirmation prompt or typed fallback, then repeat the
   persist call with unchanged inputs and the returned confirmation.

## Quick Reference

- `fishaudio_voice_create`: private creation from a scoped audio handle.
- `fishaudio_voice_design_preview`: generate expiring scoped candidates.
- `fishaudio_voice_design_persist`: privately save a selected candidate.
- `fishaudio_voice_design_discard`: remove rejected current-session previews.
- `fishaudio_voice_list`: caller-owned profile catalog.
- `fishaudio_voice_get`: one owned voice by alias or catalog ID.
- `fishaudio_voice_set_default`: choose the profile TTS default.
- `fishaudio_voice_delete`: delete an owned voice with confirmation.

## Procedure

Treat a returned `confirmation_required` result as a hard stop. When the
client presents a server-side confirmation dialog, wait for its result. On
clients without that dialog, never call the tool again until the user
personally types the exact phrase. Keep the alias, source handle, and requested
action unchanged.

After creation, mention that the provider confirmed `private` visibility.
Refresh a voice picker when the result contains `refresh_voices: true`.

## Pitfalls

- Never pass a filesystem path, URL, model ID supplied outside the owned
  catalog, transcript, or raw audio bytes to these tools.
- `fishpreview_` handles are short-lived and bound to the originating actor,
  session, and profile. Generate a new preview after expiry.
- Never fabricate, paraphrase, or automatically echo a confirmation as user
  consent.
- Group/channel messages, webhook/cron calls, anonymous actors, stale handles,
  and cross-session handles are intentionally denied.
- Prompt text is not a security boundary; backend checks remain authoritative.

## Verification

- Creation reports `visibility: private` and a voice ID.
- Voice design returns opaque handles, bounded metadata, and short-lived
  generated audio attachments.
- Persisting a selected preview reports `visibility: private`.
- Listing shows the new alias only to its owner.
- Setting default reports `is_default: true`.
- Deletion reports `deleted: true` and removes the voice from the live catalog.
