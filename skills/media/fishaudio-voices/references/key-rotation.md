# Fish Audio API key rotation

1. In the Fish console (https://fish.audio/app/api-keys), create a new API key.
2. In Verxio/Hermes Settings → Fish Audio (or the profile `.env`), set
   `FISH_AUDIO_API_KEY` to the new value and save.
3. Smoke-test: owned voice list loads; run a short TTS or whole-file
   transcription if credits allow.
4. In the Fish console, revoke the old key.
5. Gateway workers that read credentials via `get_env_value()` pick up the new
   key without restart. Restart the runtime if a process cached an empty key at
   boot.
6. Optional: inspect `~/.hermes/logs/fishaudio-audit.jsonl` for `http_status:401`
   spikes in the rotation window (lines never contain the secret).
