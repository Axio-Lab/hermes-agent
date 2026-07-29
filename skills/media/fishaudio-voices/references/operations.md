# Fish Audio operations

## Setup

1. Create an API key at https://fish.audio/app/api-keys
2. Save it as `FISH_AUDIO_API_KEY` in the active Hermes/Verxio profile `.env`
   (Settings → Fish Audio, or `hermes setup`)
3. Set `tts.provider: fishaudio` and/or `stt.provider: fishaudio` as needed
4. Smoke-test: voice list loads; optional short TTS or whole-file transcription

## Privacy

- Voice create/delete/persist require explicit confirmation (typed phrase or UI)
- Clone and design accept only opaque `fishatt_` / `fishpreview_` handles —
  never raw filesystem paths or remote URLs from the model
- Voices are forced `private`; mismatched visibility is deleted, not cataloged
- Audit logs never store transcripts, audio bytes, paths, handles, or API keys

## Cost

Fish bills against your Fish Audio account credits. Hermes enforces **local**
daily/session caps (`fishaudio.quotas` in `config.yaml`) to limit accidental
spend, but plan limits and credit top-ups are managed in the Fish console.

## ASR vs STT paths

| Path | Behavior |
|------|----------|
| Mic / notepad STT | Uses configured `stt.provider` (Fish whole-file when `fishaudio`) |
| `fishaudio_transcribe` tool | Whole-file ASR on a scoped attachment handle only |
| Live / streaming Fish ASR | **Not supported** |

Fallback for mic STT: set `stt.provider: local` (or another configured provider).

## TTS streaming

Interactive voice conversation may use live WSS (`tts.stream.*`) when
`tts.fishaudio.streaming` is true and the browser supports MediaSource MPEG.
Messaging gateways and `/api/audio/speak` stay on buffered HTTP TTS.

## Confirmation

Destructive or billing-sensitive voice ops emit a confirmation challenge.
Desktop clients answer via `fishaudio.confirmation.respond`; CLI users type the
exact phrase returned by the tool.

## Quotas and audit

- Usage counters: `~/.hermes/fishaudio/usage.v1.json`
- Audit JSONL: `~/.hermes/logs/fishaudio-audit.jsonl` (rotated by size)
- Concurrent Fish HTTP calls are limited; repeated failures open a short circuit
