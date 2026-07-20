"""Google Gemini Nano Banana image generation backend.

Native Gemini API (Interactions):
``POST https://generativelanguage.googleapis.com/v1beta/interactions``

Catalog (friendly IDs → API model ids):

    nano-banana       Gemini 3.1 Flash Image (Nano Banana 2)
    nano-banana-pro   Gemini 3 Pro Image (Nano Banana Pro)

Auth: ``GOOGLE_API_KEY`` or ``GEMINI_API_KEY`` (same keys Hermes already
uses for Gemini chat / TTS).

Docs: https://ai.google.dev/gemini-api/docs/image-generation
"""

from __future__ import annotations

import base64
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from agent.image_gen_provider import (
    DEFAULT_ASPECT_RATIO,
    ImageGenProvider,
    error_response,
    normalize_reference_images,
    resolve_aspect_ratio,
    save_b64_image,
    success_response,
)

logger = logging.getLogger(__name__)

INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"

_MODELS: Dict[str, Dict[str, Any]] = {
    "nano-banana": {
        "display": "Nano Banana",
        "speed": "~5-15s",
        "strengths": "Gemini 3.1 Flash Image — fast generalist, text rendering, multi-ref edits",
        "price": "paid",
        "api_model": "gemini-3.1-flash-image",
    },
    "nano-banana-pro": {
        "display": "Nano Banana Pro",
        "speed": "~10-30s",
        "strengths": "Gemini 3 Pro Image — highest fidelity, brand consistency, complex scenes",
        "price": "premium",
        "api_model": "gemini-3-pro-image",
    },
}

# Also accept raw Gemini API model ids in config / env.
_API_ALIASES = {
    "gemini-3.1-flash-image": "nano-banana",
    "gemini-3-pro-image": "nano-banana-pro",
    "gemini-2.5-flash-image": "nano-banana",
}

DEFAULT_MODEL = "nano-banana"

_ASPECT_MAP = {
    "landscape": "16:9",
    "square": "1:1",
    "portrait": "9:16",
}


def _api_key() -> str:
    return (
        os.environ.get("GOOGLE_API_KEY")
        or os.environ.get("GEMINI_API_KEY")
        or os.environ.get("GOOGLE_GENAI_API_KEY")
        or ""
    ).strip()


def _load_image_gen_section() -> Dict[str, Any]:
    try:
        from hermes_cli.config import load_config

        cfg = load_config()
        section = cfg.get("image_gen") if isinstance(cfg, dict) else None
        return section if isinstance(section, dict) else {}
    except Exception as exc:
        logger.debug("Could not load image_gen config: %s", exc)
        return {}


def _resolve_model(explicit: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    candidates: List[Optional[str]] = [
        explicit,
        os.environ.get("GOOGLE_IMAGE_MODEL"),
        os.environ.get("GEMINI_IMAGE_MODEL"),
    ]
    cfg = _load_image_gen_section()
    nested = cfg.get("google") if isinstance(cfg.get("google"), dict) else {}
    if isinstance(nested, dict):
        candidates.append(nested.get("model") if isinstance(nested.get("model"), str) else None)
    top = cfg.get("model")
    if isinstance(top, str):
        candidates.append(top)

    for raw in candidates:
        if not isinstance(raw, str) or not raw.strip():
            continue
        key = raw.strip()
        if key in _MODELS:
            return key, _MODELS[key]
        alias = _API_ALIASES.get(key)
        if alias and alias in _MODELS:
            return alias, _MODELS[alias]
    return DEFAULT_MODEL, _MODELS[DEFAULT_MODEL]


def _load_image_bytes(ref: str) -> Tuple[bytes, str]:
    """Load image bytes + mime type from URL, data URI, or local path."""
    ref = ref.strip()
    lower = ref.lower()
    if lower.startswith(("http://", "https://")):
        resp = requests.get(ref, timeout=60)
        resp.raise_for_status()
        ctype = (resp.headers.get("Content-Type") or "image/png").split(";", 1)[0].strip()
        if not ctype.startswith("image/"):
            ctype = "image/png"
        return resp.content, ctype
    if lower.startswith("data:"):
        header, _, b64 = ref.partition(",")
        mime = "image/png"
        if "image/" in header:
            mime = "image/" + header.split("image/", 1)[1].split(";", 1)[0]
        return base64.b64decode(b64), mime

    path = Path(ref).expanduser()
    if not path.is_file():
        workspace_alias = Path("/workspace/artifacts")
        if str(path).startswith(str(workspace_alias)):
            alt = Path("/opt/data/artifacts") / path.name
            if alt.is_file():
                path = alt
        if not path.is_file():
            raise FileNotFoundError(f"Image not found: {ref}")
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    if not mime.startswith("image/"):
        mime = "image/png"
    return path.read_bytes(), mime


def _extract_image_b64(payload: Dict[str, Any]) -> Optional[Tuple[str, str]]:
    """Return ``(b64, extension)`` from an Interactions (or similar) payload."""
    if not isinstance(payload, dict):
        return None

    # Convenience field used by the GenAI SDK / Interactions docs.
    out_img = payload.get("output_image")
    if isinstance(out_img, dict):
        data = out_img.get("data")
        mime = str(out_img.get("mime_type") or out_img.get("mimeType") or "image/png")
        if isinstance(data, str) and data.strip():
            ext = "png"
            if "jpeg" in mime or "jpg" in mime:
                ext = "jpg"
            elif "webp" in mime:
                ext = "webp"
            return data.strip(), ext

    # Walk common nested shapes: outputs / steps / candidates / parts.
    stack: List[Any] = [payload]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            ident = id(node)
            if ident in seen:
                continue
            seen.add(ident)

            inline = node.get("inlineData") or node.get("inline_data")
            if isinstance(inline, dict):
                data = inline.get("data")
                mime = str(inline.get("mimeType") or inline.get("mime_type") or "image/png")
                if isinstance(data, str) and data.strip():
                    ext = "jpg" if ("jpeg" in mime or "jpg" in mime) else "png"
                    return data.strip(), ext

            if node.get("type") in {"image", "IMAGE"} and isinstance(node.get("data"), str):
                mime = str(node.get("mime_type") or node.get("mimeType") or "image/png")
                ext = "jpg" if ("jpeg" in mime or "jpg" in mime) else "png"
                return node["data"].strip(), ext

            for key in (
                "outputs",
                "output",
                "steps",
                "candidates",
                "content",
                "parts",
                "result",
                "response",
            ):
                child = node.get(key)
                if child is not None:
                    stack.append(child)
        elif isinstance(node, list):
            stack.extend(node)
    return None


class GoogleImageGenProvider(ImageGenProvider):
    """Google Gemini Nano Banana / Nano Banana Pro via the Gemini API."""

    @property
    def name(self) -> str:
        return "google"

    @property
    def display_name(self) -> str:
        return "Google (Nano Banana)"

    def is_available(self) -> bool:
        return bool(_api_key())

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
            "name": "Google (Nano Banana)",
            "badge": "paid",
            "tag": "Nano Banana & Nano Banana Pro — Gemini native image generation",
            "env_vars": [
                {
                    "key": "GOOGLE_API_KEY",
                    "prompt": "Google AI Studio / Gemini API key (GEMINI_API_KEY also works)",
                    "url": "https://aistudio.google.com/app/apikey",
                },
            ],
        }

    def capabilities(self) -> Dict[str, Any]:
        return {"modalities": ["text", "image"], "max_reference_images": 14}

    def generate(
        self,
        prompt: str,
        aspect_ratio: str = DEFAULT_ASPECT_RATIO,
        *,
        model: Optional[str] = None,
        image_url: Optional[str] = None,
        reference_image_urls: Optional[List[str]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        del kwargs
        prompt = (prompt or "").strip()
        aspect = resolve_aspect_ratio(aspect_ratio)
        ratio = _ASPECT_MAP.get(aspect, "16:9")

        if not prompt:
            return error_response(
                error="Prompt is required and must be a non-empty string",
                error_type="invalid_argument",
                provider="google",
                aspect_ratio=aspect,
            )

        key = _api_key()
        if not key:
            return error_response(
                error=(
                    "GOOGLE_API_KEY (or GEMINI_API_KEY) not set. Run "
                    "`hermes tools` → Image Generation → Google (Nano Banana), "
                    "or add the key in Verxio Skills → Toolsets → Image Generation."
                ),
                error_type="auth_required",
                provider="google",
                aspect_ratio=aspect,
            )

        model_id, meta = _resolve_model(model)
        api_model = str(meta["api_model"])

        sources: List[str] = []
        if isinstance(image_url, str) and image_url.strip():
            sources.append(image_url.strip())
        for ref in normalize_reference_images(reference_image_urls) or []:
            sources.append(ref)
        sources = sources[:14]
        modality = "image" if sources else "text"

        input_parts: List[Dict[str, Any]] = [{"type": "text", "text": prompt}]
        try:
            for ref in sources:
                data, mime = _load_image_bytes(ref)
                input_parts.append(
                    {
                        "type": "image",
                        "data": base64.b64encode(data).decode("ascii"),
                        "mime_type": mime,
                    }
                )
        except Exception as exc:
            return error_response(
                error=f"Could not load source image for editing: {exc}",
                error_type="io_error",
                provider="google",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        body: Dict[str, Any] = {
            "model": api_model,
            "input": input_parts,
            "response_format": {
                "type": "image",
                "mime_type": "image/png",
                "aspect_ratio": ratio,
            },
        }

        try:
            resp = requests.post(
                INTERACTIONS_URL,
                headers={
                    "x-goog-api-key": key,
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=180,
            )
        except Exception as exc:
            return error_response(
                error=f"Google image request failed: {exc}",
                error_type="api_error",
                provider="google",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        try:
            payload = resp.json() if resp.content else {}
        except Exception:
            payload = {"raw": (resp.text or "")[:500]}

        if resp.status_code >= 400 or not isinstance(payload, dict):
            detail = ""
            if isinstance(payload, dict):
                err = payload.get("error")
                if isinstance(err, dict):
                    detail = str(err.get("message") or err)
                else:
                    detail = str(payload.get("message") or payload)[:400]
            if not detail:
                detail = (resp.text or f"HTTP {resp.status_code}")[:400]
            return error_response(
                error=f"Google image generation failed (HTTP {resp.status_code}): {detail}",
                error_type="api_error",
                provider="google",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        extracted = _extract_image_b64(payload)
        if not extracted:
            return error_response(
                error="Google returned no image data",
                error_type="empty_response",
                provider="google",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        b64, ext = extracted
        try:
            saved = save_b64_image(b64, prefix=f"google_{model_id}", extension=ext)
        except Exception as exc:
            return error_response(
                error=f"Could not save image to cache: {exc}",
                error_type="io_error",
                provider="google",
                model=model_id,
                prompt=prompt,
                aspect_ratio=aspect,
            )

        return success_response(
            image=str(saved),
            model=model_id,
            prompt=prompt,
            aspect_ratio=aspect,
            modality=modality,
            provider="google",
            extra={
                "api_model": api_model,
                "mode_label": meta.get("strengths", ""),
                "aspect_ratio_api": ratio,
            },
        )


def register(ctx) -> None:
    ctx.register_image_gen_provider(GoogleImageGenProvider())
