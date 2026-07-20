"""Tests for the bundled DashScope image_gen plugin."""

from __future__ import annotations

from unittest.mock import patch

import pytest
import yaml

import plugins.image_gen.dashscope as dashscope_plugin


@pytest.fixture(autouse=True)
def _tmp_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    return dashscope_plugin.DashScopeImageGenProvider()


class TestMetadata:
    def test_name(self, provider):
        assert provider.name == "dashscope"

    def test_default_model(self, provider):
        assert provider.default_model() == "qwen-image-2.0-pro"

    def test_list_models_includes_mode_labels(self, provider):
        models = provider.list_models()
        ids = [m["id"] for m in models]
        assert "qwen-image-2.0-pro" in ids
        assert "qwen-image-edit-plus" in ids
        assert "wan2.7-image-pro" in ids
        by_id = {m["id"]: m for m in models}
        assert "Text-to-image" in by_id["qwen-image-2.0-pro"]["strengths"]
        assert "Image-to-image" in by_id["qwen-image-edit-plus"]["strengths"]

    def test_setup_schema_mentions_modes(self, provider):
        schema = provider.get_setup_schema()
        assert "text-to-image" in schema["tag"].lower()


class TestAvailability:
    def test_no_api_key_unavailable(self, monkeypatch):
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        assert dashscope_plugin.DashScopeImageGenProvider().is_available() is False

    def test_api_key_set_available(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_API_KEY", "test")
        assert dashscope_plugin.DashScopeImageGenProvider().is_available() is True


class TestModelResolution:
    def test_default_t2i(self):
        model_id, meta = dashscope_plugin._resolve_model(prefer_edit=False)
        assert model_id == "qwen-image-2.0-pro"
        assert meta["mode"] == "t2i"

    def test_default_edit(self):
        model_id, meta = dashscope_plugin._resolve_model(prefer_edit=True)
        assert model_id == "qwen-image-edit-plus"
        assert meta["mode"] == "edit"

    def test_env_override(self, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_IMAGE_MODEL", "qwen-image-2.0")
        model_id, _ = dashscope_plugin._resolve_model()
        assert model_id == "qwen-image-2.0"

    def test_config_model(self, tmp_path):
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump({"image_gen": {"model": "wan2.7-image"}})
        )
        model_id, _ = dashscope_plugin._resolve_model()
        assert model_id == "wan2.7-image"


class TestGenerate:
    def test_missing_prompt(self, provider):
        result = provider.generate("")
        assert result["success"] is False
        assert result["error_type"] == "invalid_argument"

    def test_missing_key(self, monkeypatch):
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        result = dashscope_plugin.DashScopeImageGenProvider().generate("a cat")
        assert result["success"] is False
        assert result["error_type"] == "auth_required"

    def test_t2i_success(self, provider, tmp_path):
        image_url = "https://example.com/out.png"
        payload = {
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [{"image": image_url}],
                            "role": "assistant",
                        }
                    }
                ]
            }
        }
        saved = tmp_path / "saved.png"
        saved.write_bytes(b"png")

        with patch.object(
            dashscope_plugin, "request_json", return_value=(200, payload)
        ) as mock_req, patch.object(
            dashscope_plugin, "save_url_image", return_value=saved
        ):
            result = provider.generate("a red apple", aspect_ratio="square")

        assert result["success"] is True
        assert result["modality"] == "text"
        assert result["model"] == "qwen-image-2.0-pro"
        assert result["image"] == str(saved)
        assert "Text-to-image" in result.get("mode_label", "")
        body = mock_req.call_args.kwargs["body"]
        assert body["model"] == "qwen-image-2.0-pro"
        assert body["input"]["messages"][0]["content"] == [{"text": "a red apple"}]

    def test_edit_auto_fallback_from_t2i_model(self, provider, tmp_path, monkeypatch):
        monkeypatch.setenv("DASHSCOPE_IMAGE_MODEL", "qwen-image-2.0-pro")
        image_url = "https://example.com/edited.png"
        payload = {
            "output": {
                "choices": [
                    {
                        "message": {
                            "content": [{"image": image_url}],
                            "role": "assistant",
                        }
                    }
                ]
            }
        }
        saved = tmp_path / "edited.png"
        saved.write_bytes(b"png")

        with patch.object(
            dashscope_plugin, "request_json", return_value=(200, payload)
        ) as mock_req, patch.object(
            dashscope_plugin, "save_url_image", return_value=saved
        ):
            result = provider.generate(
                "make it blue",
                image_url="https://cdn.example.com/source.png",
            )

        assert result["success"] is True
        assert result["modality"] == "image"
        assert result["model"] == "qwen-image-edit-plus"
        body = mock_req.call_args.kwargs["body"]
        assert body["model"] == "qwen-image-edit-plus"
        content = body["input"]["messages"][0]["content"]
        assert content[0] == {"image": "https://cdn.example.com/source.png"}
        assert content[1] == {"text": "make it blue"}

    def test_register(self):
        from unittest.mock import MagicMock

        ctx = MagicMock()
        dashscope_plugin.register(ctx)
        ctx.register_image_gen_provider.assert_called_once()
        registered = ctx.register_image_gen_provider.call_args[0][0]
        assert registered.name == "dashscope"
