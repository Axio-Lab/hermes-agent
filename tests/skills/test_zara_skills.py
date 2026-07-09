"""Smoke tests for bundled Verxio media/creative skills."""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

SKILLS_ROOT = Path(__file__).resolve().parents[2] / "skills"


def _load_frontmatter(skill_dir: Path) -> dict:
    src = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^---\n(.*?)\n---", src, re.DOTALL)
    assert match, f"{skill_dir.name} SKILL.md missing YAML frontmatter"
    return yaml.safe_load(match.group(1))


@pytest.mark.parametrize(
    ("category", "name", "required_paths"),
    [
        (
            "creative",
            "frontend-slides",
            [
                "STYLE_PRESETS.md",
                "viewport-base.css",
                "html-template.md",
                "animation-patterns.md",
                "bold-template-pack/selection-index.json",
                "scripts/extract-pptx.py",
                "scripts/deploy.sh",
                "scripts/export-pdf.sh",
            ],
        ),
        (
            "media",
            "youtube-to-ebook",
            [
                "prompts/write-article.md",
                "references/known-pitfalls.md",
                "config/env.example",
                "templates/channels.txt",
                "scripts/get_videos.py",
                "scripts/get_transcripts.py",
                "scripts/send_email.py",
                "scripts/main.py",
            ],
        ),
        (
            "media",
            "ai-content-fix-system",
            [
                "references/export-content.md",
            ],
        ),
    ],
)
def test_bundled_skill_layout(category: str, name: str, required_paths: list[str]) -> None:
    skill_dir = SKILLS_ROOT / category / name
    assert skill_dir.is_dir(), f"missing skill dir: {skill_dir}"
    frontmatter = _load_frontmatter(skill_dir)
    assert frontmatter["name"] == name
    assert frontmatter["description"]
    assert "platforms" in frontmatter
    for rel_path in required_paths:
        assert (skill_dir / rel_path).is_file(), f"missing {rel_path} in {name}"


def test_frontend_slides_uses_skill_dir_paths() -> None:
    src = (SKILLS_ROOT / "creative" / "frontend-slides" / "SKILL.md").read_text(encoding="utf-8")
    assert "SKILL_DIR/scripts/" in src
    assert "When to use" in src


def test_youtube_to_ebook_verxio_orchestration() -> None:
    src = (SKILLS_ROOT / "media" / "youtube-to-ebook" / "SKILL.md").read_text(encoding="utf-8")
    assert "Verxio orchestration" in src
    assert "prompts/write-article.md" in src
    assert "references/known-pitfalls.md" in src


def test_ai_content_fix_system_verxio_format() -> None:
    src = (SKILLS_ROOT / "media" / "ai-content-fix-system" / "SKILL.md").read_text(encoding="utf-8")
    assert "When to use" in src
    assert "Verxio orchestration" in src
    assert "Step 1:" in src
    assert "Step 4:" in src
    assert "references/export-content.md" in src
    frontmatter = _load_frontmatter(SKILLS_ROOT / "media" / "ai-content-fix-system")
    assert len(frontmatter["description"]) <= 1024


@pytest.mark.parametrize(
    "rel_path",
    [
        "creative/frontend-slides/scripts/extract-pptx.py",
        "media/youtube-to-ebook/scripts/get_videos.py",
        "media/youtube-to-ebook/scripts/get_transcripts.py",
        "media/youtube-to-ebook/scripts/send_email.py",
        "media/youtube-to-ebook/scripts/main.py",
    ],
)
def test_shipped_python_scripts_parse(rel_path: str) -> None:
    ast.parse((SKILLS_ROOT / rel_path).read_text(encoding="utf-8"))
