"""DashScope / Qwen Cloud image generation backend.

Uses the native multimodal-generation API (intl):
``POST /api/v1/services/aigc/multimodal-generation/generation``.

Routing:
  - no source image → text-to-image models
  - ``image_url`` / references present → edit models (auto-fallback from T2I)
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    normalize_reference_images,
    resolve_aspect_ratio,
    save_url_image,
    success_response,
)
from plugins._dashscope_common import (
    api_key,
    error_message,
    request_json,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "qwen-image-2.0-pro"
DEFAULT_EDIT_MODEL = "qwen-image-edit-plus"

_ASPECT_SIZES = {
    "landscape": "1280*720",
    "square": "1024*1024",
    "portrait": "720*1280",
}

_MODELS: Dict[str, Dict[str, Any]] = {
    "qwen-image-2.0-pro": {
        "display": "Qwen Image 2.0 Pro",
        "speed": "~10-30s",
        "strengths": "Text-to-image (best quality)",
        "mode": "t2i",
        "price": "paid",
    },
    "qwen-image-2.0": {
        "display": "Qwen Image 2.0",
        "speed": "~8-20s",
        "strengths": "Text-to-image (faster)",
        "mode": "t2i",
        "price": "paid",
    },
    "qwen-image-max": {
        "display": "Qwen Image Max",
        "speed": "~15-40s",
        "strengths": "Text-to-image (max tier)",
        "mode": "t2i",
        "price": "paid",
    },
    "qwen-image-plus": {
        "display": "Qwen Image Plus",
        "speed": "~10-25s",
        "strengths": "Text-to-image (balanced)",
        "mode": "t2i",
        "price": "paid",
    },
    "qwen-image-edit-plus": {
        "display": "Qwen Image Edit Plus",
        "speed": "~10-30s",
        "strengths": "Image-to-image / edit (attach a source image)",
        "mode": "edit",
        "price": "paid",
    },
    "qwen-image-edit-max": {
        "display": "Qwen Image Edit Max",
        "speed": "~15-40s",
        "strengths": "Image-to-image / edit (stronger)",
        "mode": "edit",
        "price": "paid",
    },
    "qwen-image-edit": {
        "display": "Qwen Image Edit",
        "speed": "~8-20s",
        "strengths": "Image-to-image / edit (basic)",
        "mode": "edit",
        "price": "paid",
    },
    "wan2.7-image-pro": {
        "display": "Wan 2.7 Image Pro",
        "speed": "~15-45s",
        "strengths": "Text-to-image",
        "mode": "t2i",
        "price": "paid",
    },
    "wan2.7-image": {
        "display": "Wan 2.7 Image",
        "speed": "~10-30s",
        "strengths": "Text-to-image",
        "mode": "t2i",
        "price": "paid",
    },
    "z-image-turbo": {
        "display": "Z-Image Turbo",
        "speed": "~5-15s",
        "strengths": "Text-to-image (fast)",
        "mode": "t2i",
        "price": "paid",
    },
}


def _load_image_gen_section() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception as exc:
        logger.debug("Could not load image_gen config: %s", exc)
        return {}


def _resolve_model(prefer_edit: bool = False) -> Tuple[str, Dict[str, Any]]:
    candidates: List[Optional[str]] = [
        os.environ.get("DASHSCOPE_IMAGE_MODEL"),
    ]
    cfg = _load_image_gen_section()
    nested = cfg.get("dashscope") if isinstance(cfg.get("dashscope"), dict) else {}
    if isinstance(nested, dict):
        candidates.append(nested.get("model") if isinstance(nested.get("model"), str) else None)
    top = cfg.get("model")
    if isinstance(top, str):
        candidates.append(top)

    for raw in candidates:
        if isinstance(raw, str) and raw.strip() in _MODELS:
            model_id = raw.strip()
            meta = _MODELS[model_id]
            if prefer_edit and meta.get("mode") != "edit":
                continue
            if not prefer_edit and meta.get("mode") == "edit":
                # Allow explicit edit model even without image (will fail later
                # with a clear error if no source is provided).
                pass
            return model_id, meta

    if prefer_edit:
        return DEFAULT_EDIT_MODEL, _MODELS[DEFAULT_EDIT_MODEL]
    return DEFAULT_MODEL, _MODELS[DEFAULT_MODEL]


def _image_ref_to_api_value(ref: str) -> str:
    """Return a public URL or data-URI DashScope accepts as ``image``."""
    ref = ref.strip()
    lower = ref.lower()
    if lower.startswith(("http://", "https://", "data:")):
        return ref
    path = Path(ref).expanduser()
    if not path.is_file():
        raise FileNotFoundError(f"Source image not found: {ref}")
    data = path.read_bytes()
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    b64 = base64.b64encode(data).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _extract_image_url(payload: Dict[str, Any]) -> Optional[str]:
    output = payload.get("output")
    if not isinstance(output, dict):
        return None
    choices = output.get("choices")
    if isinstance(choices, list):
        for choice in choices:
            if not isinstance(choice, dict):
                continue
            message = choice.get("message")
            if not isinstance(message, dict):
                continue
            content = message.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and isinstance(part.get("image"), str):
                        return part["image"]
            elif isinstance(content, str) and content.startswith("http"):
                return content
    # Some Wan-style responses nest results differently
    results = output.get("results")
    if isinstance(results, list):
        for item in results:
            if isinstance(item, dict):
                for key in ("url", "image", "image_url"):
                    if isinstance(item.get(key), str):
                        return item[key]
    return None


class DashScopeImageGenProvider(ImageGenProvider):
    """DashScope native multimodal image generation / editing."""

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
                "id": model_id,
                "display": meta["display"],
                "speed": meta.get("speed", ""),
                "strengths": meta.get("strengths", ""),
                "price": meta.get("price", "paid"),
            }
            for model_id, meta in _MODELS.items()
        ]

    def default_model(self) -> Optional[str]:
        return DEFAULT_MODEL

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "DashScope (Qwen Cloud)",
            "badge": "paid",
            "tag": "Pick Qwen/Wan image models — text-to-image & image editing",
            "env_vars": [
                {
                    "key": "DASHSCOPE_API_KEY",
                    "prompt": "DashScope / Qwen Cloud API key",
                    "url": "https://modelstudio.console.alibabacloud.com/",
                },
            ],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {"modalities": ["text", "image"], "max_reference_images": 6}

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        prompt = (prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)

        if not prompt:
            return error_response(
                error="Prompt is required and must be a non-empty string",
                error_type="invalid_argument",
                provider="dashscope",
                aspect_ratio=aspect,
            )

        if not api_key():
            return error_response(
                error=(
                    "DASHSCOPE_API_KEY not set. Connect Qwen Cloud / DashScope "
                    "or run `hermes tools` → Image Generation → DashScope."
                ),
                error_type="auth_required",
                provider="dashscope",
                aspect_ratio=aspect,
            )

        sources: List[str] = []
        if isinstance(image_url, str) and image_url.strip():
            sources.append(image_url.strip())
        for ref in normalize_reference_images(reference_image_urls) or []:
            sources.append(ref)
        sources = sources[:6]
        is_edit = bool(sources)
        modality = "image" if is_edit else "text"

        model_id, meta = _resolve_model(prefer_edit=is_edit)
        if is_edit and meta.get("mode") != "edit":
            model_id, meta = DEFAULT_EDIT_MODEL, _MODELS[DEFAULT_EDIT_MODEL]
        if not is_edit and meta.get("mode") == "edit":
            return error_response(
                error=(
                    f"Model {model_id} is image-to-image / edit only. "
                    "Attach a source image, or pick a text-to-image model."
                ),
                error_type="invalid_argument",
                provider="dashscope",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        content: List[Dict[str, str]] = []
        try:
            for src in sources:
                content.append({"image": _image_ref_to_api_value(src)})
        except Exception as exc:
            return error_response(
                error=f"Could not load source image: {exc}",
                error_type="io_error",
                provider="dashscope",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )
        content.append({"text": prompt})

        size = _ASPECT_SIZES.get(aspect, _ASPECT_SIZES["square"])
        parameters: Dict[str, Any] = {
            "n": 1,
            "watermark": False,
            "prompt_extend": True,
        }
        # Basic qwen-image-edit does not support custom size / prompt_extend.
        if model_id != "qwen-image-edit":
            parameters["size"] = size
        else:
            parameters.pop("prompt_extend", None)

        body = {
            "model": model_id,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": parameters,
        }

        status, payload = request_json(
            "POST",
            "services/aigc/multimodal-generation/generation",
            body=body,
            timeout=180.0,
        )
        if status != 200:
            return error_response(
                error=error_message(payload, f"DashScope image API returned HTTP {status}"),
                error_type="api_error",
                provider="dashscope",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        image_result = _extract_image_url(payload)
        if not image_result:
            return error_response(
                error="DashScope returned no image URL",
                error_type="empty_response",
                provider="dashscope",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        local_path: Optional[str] = None
        try:
            saved = save_url_image(image_result, prefix="dashscope")
            local_path = str(saved)
            image_out = local_path
        except Exception as exc:
            logger.debug("Could not materialise DashScope image locally: %s", exc)
            image_out = image_result

        return success_response(
            image=image_out,
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            modality=modality,
            provider="dashscope",
            extra={
                "remote_url": image_result,
                "host_image": local_path,
                "mode_label": meta.get("strengths", ""),
            },
        )


def register(ctx) -> None:
    ctx.register_image_gen_provider(DashScopeImageGenProvider())
