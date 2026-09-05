"""Gemini picker should show live Google models plus the curated catalog."""

from unittest.mock import patch

from hermes_cli import models as M


def test_gemini_merges_curated_live_and_models_dev(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    curated = list(M._PROVIDER_MODELS["gemini"])
    live = ["gemini-3.2-pro-preview"]

    with (
        patch.object(M, "_fetch_gemini_models", return_value=live),
        patch.object(M, "_merge_with_models_dev", return_value=["gemini-3.2-flash"]),
    ):
        result = M.provider_model_ids("gemini", force_refresh=True)

    assert result[: len(curated)] == curated
    assert "gemini-3.2-pro-preview" in result
    assert "gemini-3.2-flash" in result


def test_gemini_falls_back_to_curated_and_models_dev_when_live_unavailable():
    with (
        patch.object(M, "_fetch_gemini_models", return_value=None),
        patch.object(M, "_merge_with_models_dev", side_effect=lambda provider, curated: list(curated)),
    ):
        result = M.provider_model_ids("gemini", force_refresh=True)

    assert result == list(M._PROVIDER_MODELS["gemini"])


def test_fetch_gemini_models_keeps_generate_content_and_drops_embeddings(monkeypatch):
    payload = {
        "models": [
            {
                "name": "models/gemini-3.2-pro-preview",
                "supportedGenerationMethods": ["generateContent"],
            },
            {
                "name": "models/gemini-embedding-001",
                "supportedGenerationMethods": ["embedContent"],
            },
            {
                "name": "models/imagen-4.0-generate",
                "supportedGenerationMethods": ["predict"],
            },
        ]
    }

    class _Resp:
        def read(self):
            import json

            return json.dumps(payload).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    with patch.object(M.urllib.request, "urlopen", return_value=_Resp()):
        result = M._fetch_gemini_models()

    assert result == ["gemini-3.2-pro-preview"]
