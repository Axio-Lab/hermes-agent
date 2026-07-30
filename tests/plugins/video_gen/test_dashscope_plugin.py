"""Tests for the bundled DashScope video_gen plugin."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import yaml

import plugins.video_gen.dashscope as dashscope_video


@pytest.fixture(autouse=True)
def _tmp_hermes_home(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    yield tmp_path


@pytest.fixture
def provider(monkeypatch):
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-key")
    return dashscope_video.DashScopeVideoGenProvider()


class TestMetadata:
    def test_name(self, provider):
        assert provider.name == "dashscope"

    def test_families_and_labels(self, provider):
        models = provider.list_models()
        ids = [m["id"] for m in models]
        assert ids == ["happyhorse-1.1", "wan2.7"]
        by_id = {m["id"]: m for m in models}
        assert "Text-to-video" in by_id["happyhorse-1.1"]["strengths"]
        assert "image-to-video" in by_id["happyhorse-1.1"]["strengths"].lower()

    def test_setup_schema(self, provider):
        tag = provider.get_setup_schema()["tag"].lower()
        assert "text-to-video" in tag
        assert "image-to-video" in tag


class TestFamilyResolution:
    def test_default(self):
        fid, meta = dashscope_video._resolve_family(None)
        assert fid == "happyhorse-1.1"
        assert meta["t2v"] == "happyhorse-1.1-t2v"

    def test_api_model_maps_to_family(self):
        fid, meta = dashscope_video._resolve_family("wan2.7-i2v")
        assert fid == "wan2.7"
        assert meta["i2v"] == "wan2.7-i2v"

    def test_config_model(self, tmp_path):
        (tmp_path / "config.yaml").write_text(
            yaml.safe_dump({"video_gen": {"model": "wan2.7"}})
        )
        fid, _ = dashscope_video._resolve_family(None)
        assert fid == "wan2.7"


class TestGenerate:
    def test_auth_required(self, monkeypatch):
        monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
        monkeypatch.delenv("DASHSCOPE_KEY", raising=False)
        monkeypatch.delenv("DASHSCOPE", raising=False)
        result = dashscope_video.DashScopeVideoGenProvider().generate("a cat runs")
        assert result["success"] is False
        assert result["error_type"] == "auth_required"

    def test_t2v_success(self, provider, tmp_path):
        submit = {
            "output": {"task_id": "task-1", "task_status": "PENDING"},
        }
        done = {
            "output": {
                "task_id": "task-1",
                "task_status": "SUCCEEDED",
                "video_url": "https://example.com/out.mp4",
            },
            "usage": {"output_video_duration": 5},
        }
        local = tmp_path / "out.mp4"
        local.write_bytes(b"mp4")

        with patch.object(
            dashscope_video, "request_json", return_value=(200, submit)
        ) as mock_req, patch.object(
            dashscope_video,
            "poll_task",
            return_value={"ok": True, "status": "succeeded", "body": done},
        ), patch.object(
            dashscope_video, "_download_video", return_value=str(local)
        ):
            result = provider.generate(
                "A cat running",
                duration=5,
                aspect_ratio="16:9",
                resolution="720p",
            )

        assert result["success"] is True
        assert result["modality"] == "text"
        assert result["model"] == "happyhorse-1.1-t2v"
        assert result["video"] == str(local)
        assert result["family"] == "happyhorse-1.1"
        body = mock_req.call_args.kwargs["body"]
        assert body["model"] == "happyhorse-1.1-t2v"
        assert body["input"]["prompt"] == "A cat running"
        assert "media" not in body["input"]

    def test_i2v_routes_model(self, provider, tmp_path):
        submit = {"output": {"task_id": "task-2", "task_status": "PENDING"}}
        done = {
            "output": {
                "task_status": "SUCCEEDED",
                "video_url": "https://example.com/i2v.mp4",
            },
            "usage": {"output_video_duration": 5},
        }
        local = tmp_path / "i2v.mp4"
        local.write_bytes(b"mp4")

        with patch.object(
            dashscope_video, "request_json", return_value=(200, submit)
        ) as mock_req, patch.object(
            dashscope_video,
            "poll_task",
            return_value={"ok": True, "status": "succeeded", "body": done},
        ), patch.object(
            dashscope_video, "_download_video", return_value=str(local)
        ):
            result = provider.generate(
                "camera pans left",
                image_url="https://cdn.example.com/frame.png",
                model="happyhorse-1.1",
            )

        assert result["success"] is True
        assert result["modality"] == "image"
        assert result["model"] == "happyhorse-1.1-i2v"
        body = mock_req.call_args.kwargs["body"]
        assert body["model"] == "happyhorse-1.1-i2v"
        assert body["input"]["media"] == [
            {"type": "first_frame", "url": "https://cdn.example.com/frame.png"}
        ]

    def test_register(self):
        ctx = MagicMock()
        dashscope_video.register(ctx)
        ctx.register_video_gen_provider.assert_called_once()
