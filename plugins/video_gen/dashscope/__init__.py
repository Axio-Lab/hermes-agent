"""DashScope / Qwen Cloud video generation backend.

Native async API:
``POST /api/v1/services/aigc/video-generation/video-synthesis``
then poll ``GET /api/v1/tasks/{task_id}``.

Families expose both text-to-video and image-to-video; routing follows
``image_url`` presence (same pattern as the FAL video plugin).
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from agent.video_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    DEFAULT_RESOLUTION,
    VideoGenProvider,
    error_response,
    save_bytes_video,
    success_response,
)
from plugins._dashscope_common import (
    api_key,
    error_message,
    poll_task,
    request_json,
)

logger = logging.getLogger(__name__)


FAMILIES: Dict[str, Dict[str, Any]] = {
    "happyhorse-1.1": {
        "display": "HappyHorse 1.1",
        "speed": "~60-180s",
        "price": "premium",
        "strengths": "Text-to-video / image-to-video (best)",
        "t2v": "happyhorse-1.1-t2v",
        "i2v": "happyhorse-1.1-i2v",
        "min_duration": 3,
        "max_duration": 15,
        "default_duration": 5,
        "resolutions": ("720P", "1080P"),
        "ratios": ("16:9", "9:16", "1:1", "4:3", "3:4", "4:5", "5:4", "9:21", "21:9"),
    },
    "wan2.7": {
        "display": "Wan 2.7",
        "speed": "~60-180s",
        "price": "premium",
        "strengths": "Text-to-video / image-to-video",
        "t2v": "wan2.7-t2v",
        "i2v": "wan2.7-i2v",
        "min_duration": 2,
        "max_duration": 15,
        "default_duration": 5,
        "resolutions": ("720P", "1080P"),
        "ratios": ("16:9", "9:16", "1:1", "4:3", "3:4"),
    },
}

DEFAULT_FAMILY = "happyhorse-1.1"


def _load_video_gen_section() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("video_gen") if isinstance(cfg, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception as exc:
        logger.debug("Could not load video_gen config: %s", exc)
        return {}


def _resolve_family(explicit: Optional[str]) -> Tuple[str, Dict[str, Any]]:
    candidates: List[Optional[str]] = [
        explicit,
        os.environ.get("DASHSCOPE_VIDEO_MODEL"),
    ]
    cfg = _load_video_gen_section()
    nested = cfg.get("dashscope") if isinstance(cfg.get("dashscope"), dict) else {}
    if isinstance(nested, dict):
        candidates.append(nested.get("model") if isinstance(nested.get("model"), str) else None)
    top = cfg.get("model")
    if isinstance(top, str):
        candidates.append(top)

    for raw in candidates:
        if not isinstance(raw, str) or not raw.strip():
            continue
        key = raw.strip()
        # Accept bare API model ids and map to family.
        if key in FAMILIES:
            return key, FAMILIES[key]
        for fid, meta in FAMILIES.items():
            if key in (meta.get("t2v"), meta.get("i2v")):
                return fid, meta
    return DEFAULT_FAMILY, FAMILIES[DEFAULT_FAMILY]


def _normalize_resolution(value: Optional[str], family: Dict[str, Any]) -> str:
    raw = (value or DEFAULT_RESOLUTION or "720p").strip().upper()
    if not raw.endswith("P"):
        raw = f"{raw}P" if raw.isdigit() else raw
    allowed = family.get("resolutions") or ("720P", "1080P")
    if raw in allowed:
        return raw
    return "720P"


def _normalize_ratio(aspect_ratio: Optional[str], family: Dict[str, Any]) -> str:
    raw = (aspect_ratio or DEFAULT_ASPECT_RATIO).strip()
    allowed = family.get("ratios") or ("16:9",)
    if raw in allowed:
        return raw
    return "16:9"


def _clamp_duration(duration: Optional[int], family: Dict[str, Any]) -> int:
    lo = int(family.get("min_duration") or 3)
    hi = int(family.get("max_duration") or 15)
    default = int(family.get("default_duration") or lo)
    if duration is None:
        return default
    try:
        value = int(duration)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, value))


def _download_video(url: str) -> str:
    import requests

    resp = requests.get(url, timeout=120, stream=True)
    resp.raise_for_status()
    chunks: List[bytes] = []
    total = 0
    for chunk in resp.iter_content(chunk_size=64 * 1024):
        if not chunk:
            continue
        total += len(chunk)
        if total > 200 * 1024 * 1024:
            raise ValueError("Video exceeds 200MB download cap")
        chunks.append(chunk)
    path = save_bytes_video(b"".join(chunks), prefix="dashscope", extension="mp4")
    return str(path)


class DashScopeVideoGenProvider(VideoGenProvider):
    """DashScope HappyHorse / Wan video synthesis."""

    @property
    def name(self) -> str:
        return "dashscope"

    @property
    def display_name(self) -> str:
        return "DashScope (Qwen Cloud)"

    def is_available(self) -> bool:
        return bool(api_key())

    def list_models(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": family_id,
                "display": meta["display"],
                "speed": meta.get("speed", ""),
                "strengths": meta.get("strengths", ""),
                "price": meta.get("price", "paid"),
                "modalities": ["text", "image"],
            }
            for family_id, meta in FAMILIES.items()
        ]

    def default_model(self) -> Optional[str]:
        return DEFAULT_FAMILY

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "DashScope (Qwen Cloud)",
            "badge": "paid",
            "tag": "HappyHorse & Wan — text-to-video / image-to-video",
            "env_vars": [
                {
                    "key": "DASHSCOPE_API_KEY",
                    "prompt": "DashScope / Qwen Cloud API key",
                    "url": "https://modelstudio.console.alibabacloud.com/",
                },
            ],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {
            "modalities": ["text", "image"],
            "aspect_ratios": list(FAMILIES[DEFAULT_FAMILY]["ratios"]),
            "resolutions": ["720p", "1080p"],
            "max_duration": 15,
            "min_duration": 3,
            "supports_audio": True,
            "supports_negative_prompt": False,
            "max_reference_images": 0,
        }

    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        duration: Optional[int] = None,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        resolution: str = DEFAULT_RESOLUTION,
        negative_prompt: Optional[str] = None,
        audio: Optional[bool] = None,
        seed: Optional[int] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        del reference_image_urls, negative_prompt, audio  # not in v1 surface
        prompt = (prompt or "").strip()
        image_ref = image_url.strip() if isinstance(image_url, str) else ""
        modality = "image" if image_ref else "text"

        if not api_key():
            return error_response(
                error=(
                    "DASHSCOPE_API_KEY not set. Connect Qwen Cloud / DashScope "
                    "or run `hermes tools` → Video Generation → DashScope."
                ),
                error_type="auth_required",
                provider="dashscope",
                prompt=prompt,
            )

        if not prompt and not image_ref:
            return error_response(
                error="prompt is required for text-to-video (and recommended for image-to-video)",
                error_type="missing_prompt",
                provider="dashscope",
                prompt=prompt,
            )

        family_id, family = _resolve_family(model)
        api_model = family["i2v"] if modality == "image" else family["t2v"]
        ratio = _normalize_ratio(aspect_ratio, family)
        res = _normalize_resolution(resolution, family)
        seconds = _clamp_duration(duration, family)

        input_payload: Dict[str, Any] = {}
        if prompt:
            input_payload["prompt"] = prompt
        if image_ref:
            input_payload["media"] = [{"type": "first_frame", "url": image_ref}]

        parameters: Dict[str, Any] = {
            "resolution": res,
            "duration": seconds,
            "watermark": False,
        }
        if modality == "text":
            parameters["ratio"] = ratio
        if seed is not None:
            try:
                parameters["seed"] = int(seed)
            except (TypeError, ValueError):
                pass

        body = {"model": api_model, "input": input_payload, "parameters": parameters}
        status, payload = request_json(
            "POST",
            "services/aigc/video-generation/video-synthesis",
            body=body,
            headers={"X-DashScope-Async": "enable"},
            timeout=60.0,
        )
        if status != 200:
            return error_response(
                error=error_message(payload, f"DashScope video submit failed (HTTP {status})"),
                error_type="api_error",
                provider="dashscope",
                model=api_model,
                prompt=prompt,
                aspect_ratio=ratio,
            )

        output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
        task_id = output.get("task_id")
        if not isinstance(task_id, str) or not task_id:
            return error_response(
                error="DashScope video submit returned no task_id",
                error_type="empty_response",
                provider="dashscope",
                model=api_model,
                prompt=prompt,
                aspect_ratio=ratio,
            )

        polled = poll_task(task_id, timeout_seconds=360.0, poll_interval=5.0)
        body_out = polled.get("body") if isinstance(polled.get("body"), dict) else {}
        if not polled.get("ok"):
            out = body_out.get("output") if isinstance(body_out.get("output"), dict) else {}
            detail = out.get("message") or error_message(body_out, polled.get("status", "failed"))
            return error_response(
                error=f"DashScope video generation {polled.get('status')}: {detail}",
                error_type=str(polled.get("status") or "api_error"),
                provider="dashscope",
                model=api_model,
                prompt=prompt,
                aspect_ratio=ratio,
            )

        out = body_out.get("output") if isinstance(body_out.get("output"), dict) else {}
        video_url = out.get("video_url")
        if not isinstance(video_url, str) or not video_url:
            return error_response(
                error="DashScope video completed without video_url",
                error_type="empty_response",
                provider="dashscope",
                model=api_model,
                prompt=prompt,
                aspect_ratio=ratio,
            )

        local_path = video_url
        try:
            local_path = _download_video(video_url)
        except Exception as exc:
            logger.debug("Could not cache DashScope video locally: %s", exc)

        usage = body_out.get("usage") if isinstance(body_out.get("usage"), dict) else {}
        return success_response(
            video=local_path,
            model=api_model,
            prompt=prompt,
            modality=modality,
            aspect_ratio=ratio if modality == "text" else "",
            duration=int(usage.get("output_video_duration") or seconds),
            provider="dashscope",
            extra={
                "family": family_id,
                "remote_url": video_url,
                "task_id": task_id,
                "mode_label": family.get("strengths", ""),
                "resolution": res,
            },
        )


def register(ctx) -> None:
    ctx.register_video_gen_provider(DashScopeVideoGenProvider())
