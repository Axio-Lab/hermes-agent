from __future__ import annotations

import re
from pathlib import Path

import yaml


SKILL_DIR = Path(__file__).resolve().parents[2] / "skills" / "creative" / "anti-ai-slop"


def test_anti_ai_slop_frontmatter_covers_edit_and_detection() -> None:
    source = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^---\n(.*?)\n---", source, re.DOTALL)

    assert match
    frontmatter = yaml.safe_load(match.group(1))
    assert frontmatter["name"] == "anti-ai-slop"
    assert "detect" in frontmatter["description"]
    assert "humanize" in frontmatter["description"]


def test_anti_ai_slop_writing_workflow_is_complete() -> None:
    source = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    editor = (SKILL_DIR / "references" / "writing-editor.md").read_text(encoding="utf-8")
    evaluation = (SKILL_DIR / "references" / "writing-eval.md").read_text(encoding="utf-8")

    assert "references/writing-editor.md" in source
    assert "references/writing-eval.md" in source
    assert "**Edit (default).**" in source
    assert "**Detect.**" in source
    assert "minimum effective edit" in editor
    assert "Do not rewrite the draft" in editor
    assert "Does the writer still sound like themselves?" in evaluation


def test_anti_ai_slop_preserves_upstream_license_notice() -> None:
    license_text = (SKILL_DIR / "references" / "no-ai-slop-license.txt").read_text(
        encoding="utf-8"
    )

    assert "Copyright (c) 2026 Peter Yang" in license_text
    assert "MIT License" in license_text
