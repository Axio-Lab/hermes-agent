"""Verxio artifact materialization for ``video_generate`` results."""

from __future__ import annotations

import json
from io import BytesIO

from agent import video_gen_registry
from agent.video_gen_provider import VideoGenProvider


class _LocalFileProvider(VideoGenProvider):
    def __init__(self, path: str):
        self._path = path

    @property
    def name(self) -> str:
        return "local-file"

    def generate(self, prompt, **kwargs):
        return {
            "success": True,
            "video": self._path,
            "model": "m",
            "prompt": prompt,
            "modality": "text",
            "aspect_ratio": "",
            "duration": 5,
            "provider": self.name,
        }


def test_postprocess_materializes_cache_video_into_artifacts(monkeypatch, tmp_path):
    from tools import video_generation_tool

    cache_dir = tmp_path / "cache" / "videos"
    cache_dir.mkdir(parents=True)
    cache_video = cache_dir / "dashscope_clip.mp4"
    cache_video.write_bytes(b"fake-mp4-bytes")

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    monkeypatch.setenv("VERXIO_ARTIFACTS_DIR", str(artifact_dir))

    raw = json.dumps({
        "success": True,
        "video": str(cache_video),
        "prompt": "Onion flexes in the kitchen",
    })
    result = json.loads(video_generation_tool._postprocess_video_generate_result(raw))

    assert result["success"] is True
    assert result["original_video"] == str(cache_video)
    assert result["video"].startswith(str(artifact_dir))
    assert result["host_video"] == result["video"]
    assert result["video"].endswith(".mp4")
    assert (artifact_dir / result["video"].split("/")[-1]).read_bytes() == b"fake-mp4-bytes"


def test_postprocess_materializes_remote_video_url(monkeypatch, tmp_path):
    from tools import video_generation_tool

    artifact_dir = tmp_path / "artifacts"
    video_bytes = b"\x00\x00\x00\x18ftypmp42"

    class FakeResponse(BytesIO):
        headers = {"Content-Type": "video/mp4"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setenv("VERXIO_ARTIFACTS_DIR", str(artifact_dir))
    monkeypatch.setattr(
        video_generation_tool.urllib.request,
        "urlopen",
        lambda *args, **kwargs: FakeResponse(video_bytes),
    )

    raw = json.dumps({
        "success": True,
        "video": "https://example.com/clip.mp4",
        "prompt": "A happy dog runs",
    })
    result = json.loads(video_generation_tool._postprocess_video_generate_result(raw))

    assert result["original_video"] == "https://example.com/clip.mp4"
    assert result["video"].startswith(str(artifact_dir))
    assert (artifact_dir / result["video"].split("/")[-1]).read_bytes() == video_bytes


def test_postprocess_marks_success_without_video_as_failure():
    from tools import video_generation_tool

    raw = json.dumps({"success": True, "video": "", "prompt": "x"})
    result = json.loads(video_generation_tool._postprocess_video_generate_result(raw))

    assert result["success"] is False
    assert result["error_type"] == "empty_video_result"


def test_handle_video_generate_materializes_provider_path(monkeypatch, tmp_path):
    from tools import video_generation_tool
    import hermes_cli.plugins as plugins_module

    video_gen_registry._reset_for_tests()

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    cache_video = cache_dir / "provider.mp4"
    cache_video.write_bytes(b"mp4data")

    artifact_dir = tmp_path / "artifacts"
    artifact_dir.mkdir()

    video_gen_registry.register_provider(_LocalFileProvider(str(cache_video)))
    monkeypatch.setenv("VERXIO_ARTIFACTS_DIR", str(artifact_dir))

    saved = video_generation_tool._read_configured_video_provider
    saved_discover = plugins_module._ensure_plugins_discovered
    video_generation_tool._read_configured_video_provider = lambda: None  # type: ignore
    plugins_module._ensure_plugins_discovered = lambda *_a, **_k: None  # type: ignore
    try:
        result = json.loads(
            video_generation_tool._handle_video_generate({"prompt": "animate onion"})
        )
    finally:
        video_generation_tool._read_configured_video_provider = saved  # type: ignore
        plugins_module._ensure_plugins_discovered = saved_discover  # type: ignore
        video_gen_registry._reset_for_tests()

    assert result["success"] is True
    assert result["video"].startswith(str(artifact_dir))
    assert result["original_video"] == str(cache_video)
