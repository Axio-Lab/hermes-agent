#!/usr/bin/env python3
"""Import bundled third-party skills into hermes-agent/skills with Verxio frontmatter."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = Path("/tmp/skills-fetch/repos")
DEST_ROOT = REPO_ROOT / "skills"

SKILLS: list[tuple[str, str, Path, str]] = [
    (
        "frontend-design",
        "creative",
        Path("anthropics-skills/skills/frontend-design"),
        "Improve frontend layout, spacing, typography, visual hierarchy, and polish.",
    ),
    (
        "agent-browser",
        "browser",
        Path("vercel-labs-agent-browser/skills/agent-browser"),
        "Browser automation: open sites, run flows, collect context, and verify pages.",
    ),
    (
        "web-design-guidelines",
        "creative",
        Path("vercel-labs-agent-skills/skills/web-design-guidelines"),
        "Web design rules: visual structure, readability, UI patterns, and common mistakes.",
    ),
    (
        "design-taste-frontend",
        "creative",
        Path("leonxlnx-taste-skill/skills/taste-skill"),
        "Stronger frontend taste: composition, color, spacing, typography, and product presentation.",
    ),
    (
        "high-end-visual-design",
        "creative",
        Path("leonxlnx-taste-skill/skills/soft-skill"),
        "High-end visuals: premium composition, sharper details, less generic AI-looking design.",
    ),
    (
        "redesign-existing-projects",
        "creative",
        Path("leonxlnx-taste-skill/skills/redesign-skill"),
        "Redesign existing projects: find weak spots, modernize UI, and strengthen product feel.",
    ),
    (
        "firecrawl-deep-research",
        "research",
        Path("firecrawl-firecrawl-workflows/skills/firecrawl-deep-research"),
        "Deep web research: collect sources, extract facts, turn messy information into clear insights.",
    ),
    (
        "firecrawl-market-research",
        "research",
        Path("firecrawl-firecrawl-workflows/skills/firecrawl-market-research"),
        "Market research: players, categories, trends, positioning, and opportunities.",
    ),
    (
        "firecrawl-lead-research",
        "research",
        Path("firecrawl-firecrawl-workflows/skills/firecrawl-lead-research"),
        "Lead research: companies, websites, signals, context, and outreach angles.",
    ),
    (
        "firecrawl-research-papers",
        "research",
        Path("firecrawl-firecrawl-workflows/skills/firecrawl-research-papers"),
        "Research papers: find, analyze, extract main ideas, apply to content or product work.",
    ),
    (
        "use-my-browser",
        "browser",
        Path("xixu-me-skills/skills/use-my-browser"),
        "Work through the user's browser: pages, sessions, accounts, and real web actions.",
    ),
    (
        "browser-act",
        "browser",
        Path("browser-act-skills/browser-act"),
        "Browser actions: navigate, click, type, extract, and verify.",
    ),
    (
        "firecrawl-browser",
        "browser",
        Path("firecrawl-cli/skills/firecrawl-interact"),
        "Browser-based web extraction and interaction: pages, forms, login, pagination, data collection.",
    ),
    (
        "browser",
        "browser",
        Path("browserbase-skills/skills/browser"),
        "Browser automation through the Browserbase ecosystem.",
    ),
    (
        "figma-use",
        "creative",
        Path("figma-mcp-server-guide/skills/figma-use"),
        "Work with Figma: read designs, understand structure, use design files as source material.",
    ),
    (
        "implement-design",
        "creative",
        Path("openai-skills/skills/.curated/figma-implement-design"),
        "Turn Figma designs into code: components, layout, and visual matching.",
    ),
    (
        "figma-generate-design",
        "creative",
        Path("figma-mcp-server-guide/skills/figma-generate-design"),
        "Generate design work in Figma: screens, variations, and interface structures.",
    ),
    (
        "figma-generate-library",
        "creative",
        Path("figma-mcp-server-guide/skills/figma-generate-library"),
        "Generate a design library: components, styles, rules, and system structure.",
    ),
    (
        "figma",
        "creative",
        Path("openai-skills/skills/.curated/figma"),
        "Connect Figma work to agent workflows.",
    ),
    (
        "figma-implement-design",
        "creative",
        Path("openai-skills/skills/.curated/figma-implement-design"),
        "Turn Figma designs into implementation while keeping structure and visual details.",
    ),
    (
        "ai-research-explore",
        "research",
        Path("lllllllama-rigorpilot-skills/skills/ai-research-explore"),
        "AI research exploration: ideas, hypotheses, connections, and research directions.",
    ),
    (
        "last30days",
        "research",
        Path("mvanhorn-last30days-skill/skills/last30days"),
        "Find fresh topics and discussions from the last 30 days.",
    ),
    (
        "persona-sales-ops",
        "sales",
        Path("googleworkspace-cli/skills/persona-sales-ops"),
        "Sales ops persona: process, CRM logic, sales operations, and working documents.",
    ),
    (
        "sales-qualification",
        "sales",
        Path("refoundai-lenny-skills/skills/sales-qualification"),
        "Qualify leads: who fits, what questions to ask, and how strong the fit is.",
    ),
    (
        "salesforce-developer",
        "sales",
        Path("jeffallan-claude-skills/skills/salesforce-developer"),
        "Salesforce development: logic, integrations, workflows, code, and admin tasks.",
    ),
    (
        "copywriting",
        "media",
        Path("coreyhaines31-marketingskills/skills/copywriting"),
        "Copywriting: headlines, offers, structure, persuasion, and CTAs.",
    ),
    (
        "customer-research",
        "research",
        Path("coreyhaines31-marketingskills/skills/customer-research"),
        "Research an audience: pains, desires, objections, and customer language.",
    ),
    (
        "prospecting",
        "sales",
        Path("coreyhaines31-marketingskills/skills/prospecting"),
        "Find potential customers: segments, lead signals, and outreach angles.",
    ),
    (
        "cold-email",
        "sales",
        Path("coreyhaines31-marketingskills/skills/cold-email"),
        "Cold email: structure, personalization, follow-ups, and subject lines.",
    ),
    (
        "content-strategy",
        "media",
        Path("coreyhaines31-marketingskills/skills/content-strategy"),
        "Content strategy: topics, pillars, audience, positioning, and publishing rhythm.",
    ),
]

WHEN_TO_USE: dict[str, str] = {
    "frontend-design": "Load when building or reshaping UI and the user wants layout, spacing, typography, visual hierarchy, or final polish. Trigger on: make this look better, improve the design, landing page, dashboard UI, frontend polish, or any request to ship UI that should feel like a real product.",
    "agent-browser": "Load when the task needs real browser automation: open URLs, click through flows, extract page content, or verify UI behavior. Trigger on: open this site, automate the browser, check the page, browser flow, or web automation.",
    "web-design-guidelines": "Load when reviewing or building landing pages, SaaS UI, dashboards, or product sites against design and UX best practices. Trigger on: review my UI, check accessibility, audit design, web design rules, or landing page feedback.",
    "design-taste-frontend": "Load when frontend code works but visual quality needs stronger composition, color, spacing, or typography. Trigger on: improve taste, make it feel premium, better visual design, or less generic UI.",
    "high-end-visual-design": "Load for promo pages, portfolios, personal brand visuals, or product pages that need premium, non-generic presentation. Trigger on: high-end design, premium look, expensive feel, or polished marketing visuals.",
    "redesign-existing-projects": "Load when an existing site or app needs a visual upgrade without breaking functionality. Trigger on: redesign, modernize UI, audit my design, or make this product look stronger.",
    "firecrawl-deep-research": "Load for deep web research that needs sources, fact extraction, and synthesized insights. Trigger on: research this topic, deep dive, gather sources, or turn web research into a report.",
    "firecrawl-market-research": "Load when entering or analyzing a market: competitors, categories, trends, positioning. Trigger on: market research, competitive landscape, niche analysis, or TAM research.",
    "firecrawl-lead-research": "Load for B2B lead research: companies, signals, context, outreach angles. Trigger on: research leads, company research, sales research, or find prospects.",
    "firecrawl-research-papers": "Load when finding, reading, or applying academic papers and technical research. Trigger on: research paper, arxiv, paper summary, or apply research to product/content.",
    "use-my-browser": "Load when the agent should work through the user's existing browser session, accounts, or logged-in pages. Trigger on: use my browser, my session, logged-in site, or user's Chrome.",
    "browser-act": "Load for repeatable browser agent workflows: navigate, click, type, extract, verify. Trigger on: browser act, automate clicks, scrape with interaction, or browser agent.",
    "firecrawl-browser": "Load when pages need clicks, forms, login, pagination, or JS interaction before extraction. Trigger on: interact with page, fill form, log in, paginate, or scrape failed behind JS.",
    "browser": "Load for browser tasks on Browserbase infrastructure. Trigger on: browserbase, cloud browser, stable browser automation, or remote browser session.",
    "figma-use": "Load when working with Figma files: read structure, inspect designs, or use Figma as source material. Trigger on: Figma file, read design, Figma URL, or design context from Figma.",
    "implement-design": "Load when implementing UI from Figma with components, layout, and visual fidelity. Trigger on: implement design, Figma to code, build this screen, or match Figma specs.",
    "figma-generate-design": "Load when drafting UI concepts directly in Figma. Trigger on: generate design in Figma, create screens in Figma, or draft UI in Figma.",
    "figma-generate-library": "Load when building or extending a Figma design system library. Trigger on: design library, component library in Figma, or design system in Figma.",
    "figma": "Load when Figma should connect to broader agent workflows. Trigger on: Figma workflow, Figma integration, or design handoff with Figma.",
    "figma-implement-design": "Load when translating Figma designs to code with structure and visual detail preserved. Trigger on: figma implement, design to code, or pixel-perfect from Figma.",
    "ai-research-explore": "Load for AI research exploration beyond surface news: ideas, hypotheses, connections, directions. Trigger on: explore research, AI research ideas, research directions, or deep AI topic exploration.",
    "last30days": "Load when the user wants fresh topics, trends, or discussions from roughly the last 30 days. Trigger on: what's trending, last 30 days, recent discussions, or timely content ideas.",
    "persona-sales-ops": "Load for sales operations work: process, CRM logic, pipelines, and RevOps documents. Trigger on: sales ops, RevOps, CRM process, or sales operations.",
    "sales-qualification": "Load when qualifying B2B leads: fit, discovery questions, scoring. Trigger on: qualify lead, sales qualification, is this a good fit, or discovery questions.",
    "salesforce-developer": "Load for Salesforce development, integrations, workflows, Apex, or admin tasks. Trigger on: Salesforce, Apex, Flow, SOQL, or Salesforce integration.",
    "copywriting": "Load for marketing copy: headlines, offers, persuasion, CTAs. Trigger on: write copy, headline, landing page copy, or improve messaging.",
    "customer-research": "Load when researching audience pains, desires, objections, and language. Trigger on: customer research, audience research, ICP, or voice of customer.",
    "prospecting": "Load for systematic lead generation: segments, signals, outreach angles. Trigger on: prospecting, find customers, lead gen, or build a prospect list.",
    "cold-email": "Load for outbound email: structure, personalization, follow-ups, subject lines. Trigger on: cold email, outbound email, email sequence, or write outreach.",
    "content-strategy": "Load when building a content system: pillars, topics, audience, publishing rhythm. Trigger on: content strategy, content plan, editorial calendar, or content pillars.",
}


def split_frontmatter(text: str) -> tuple[str | None, str]:
    if not text.startswith("---"):
        return None, text
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not match:
        return None, text
    return match.group(1), text[match.end() :]


def build_frontmatter(name: str, description: str) -> str:
    desc = description.replace('"', '\\"')
    return f'---\nname: {name}\ndescription: "{desc}"\nplatforms: [linux, macos, windows]\n---\n\n'


def inject_when_to_use(body: str, name: str) -> str:
    if re.search(r"^## When to use\b", body, re.MULTILINE | re.IGNORECASE):
        return body
    if re.search(r"^## When To Use\b", body, re.MULTILINE):
        return body

    when = WHEN_TO_USE.get(name, "")
    if not when:
        return body

    title_match = re.match(r"^(#\s+[^\n]+\n)", body)
    if title_match:
        rest = body[title_match.end() :].lstrip("\n")
        return f"{title_match.group(1)}\n## When to use\n\n{when}\n\n{rest}"
    return f"## When to use\n\n{when}\n\n{body}"


def adapt_skill_md(skill_md: Path, name: str, description: str) -> None:
    text = skill_md.read_text(encoding="utf-8")
    _, body = split_frontmatter(text)
    body = inject_when_to_use(body.lstrip("\n"), name)
    skill_md.write_text(build_frontmatter(name, description) + body, encoding="utf-8")


def copy_skill(name: str, category: str, src: Path, description: str) -> None:
    if not src.is_dir():
        raise FileNotFoundError(f"Missing source: {src}")
    dest = DEST_ROOT / category / name
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(
        src,
        dest,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store"),
    )
    skill_md = dest / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"No SKILL.md in {src}")
    adapt_skill_md(skill_md, name, description)
    print(f"  + {category}/{name}")


def main() -> None:
    print(f"Importing {len(SKILLS)} skills into {DEST_ROOT}")
    for name, category, rel_src, description in SKILLS:
        src = SRC_ROOT / rel_src
        copy_skill(name, category, src, description)
    print("Done.")


if __name__ == "__main__":
    main()
