#!/usr/bin/env python3
"""Generate a standalone Finding Your First Customer HTML report from JSON."""

from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


DIMENSIONS = {
    "pain_strength": "Pain strength",
    "product_fit": "Product fit",
    "timing": "Timing",
    "reachability": "Reachability",
    "evidence_quality": "Evidence quality",
}


def esc(value: Any) -> str:
    return html.escape(str(value if value is not None else ""), quote=True)


def as_items(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def clamp(value: Any, maximum: int = 100) -> int:
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        number = 0
    return max(0, min(maximum, number))


def safe_url(value: Any) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return esc(raw)
    return "#"


def stage_class(stage: Any) -> str:
    value = str(stage or "").lower()
    if "high" in value:
        return "hot"
    if "problem" in value or "trigger" in value:
        return "warm"
    return "cool"


def render_dimensions(data: Any) -> str:
    dimensions = data if isinstance(data, dict) else {}
    rows = []
    for key, label in DIMENSIONS.items():
        score = clamp(dimensions.get(key, 0), 5)
        rows.append(
            "<div class=\"metric\">"
            f"<span>{esc(label)}</span>"
            "<div class=\"track\">"
            f"<i style=\"width:{score * 20}%\"></i>"
            "</div>"
            f"<b>{score}/5</b>"
            "</div>"
        )
    return "".join(rows)


def render_prospect(prospect: dict[str, Any], index: int) -> str:
    score = clamp(prospect.get("score"))
    source = safe_url(prospect.get("source_url"))
    return f"""
    <article class="prospect">
      <header class="prospect-head">
        <div class="rank">{index:02d}</div>
        <div>
          <span class="eyebrow">{esc(prospect.get("type", "Public prospect"))}</span>
          <h3>{esc(prospect.get("name", f"Prospect {index}"))}</h3>
          <span class="stage {stage_class(prospect.get("stage"))}">{esc(prospect.get("stage", "Potential fit"))}</span>
        </div>
        <div class="score" style="--score:{score}" aria-label="Fit score {score} out of 100">
          <strong>{score}</strong><small>/100</small>
        </div>
      </header>
      <section class="signal">
        <span>Public signal</span>
        <p>{esc(prospect.get("pain_signal", ""))}</p>
      </section>
      <div class="grid">
        <div><span>Why it fits</span><p>{esc(prospect.get("why_fit", ""))}</p></div>
        <div><span>Why now</span><p>{esc(prospect.get("why_now", ""))}</p></div>
        <div><span>Suggested channel</span><p>{esc(prospect.get("suggested_channel", ""))}</p></div>
        <div><span>Caution</span><p>{esc(prospect.get("caution", "Confirm current relevance before outreach."))}</p></div>
      </div>
      <blockquote><span>Suggested opener</span>{esc(prospect.get("opener", ""))}</blockquote>
      <details>
        <summary>Evidence and score breakdown</summary>
        <div class="evidence">
          <div><span>Evidence</span><p>{esc(prospect.get("evidence", ""))}</p></div>
          <div>
            <span>Source</span>
            <p>{esc(prospect.get("source_type", "Public source"))} | {esc(prospect.get("signal_date", "Date unavailable"))}</p>
            <a href="{source}" target="_blank" rel="noreferrer">{esc(prospect.get("source_title", "Open original source"))}</a>
          </div>
        </div>
        <div class="metrics">{render_dimensions(prospect.get("dimensions"))}</div>
      </details>
    </article>"""


def render_pattern(pattern: dict[str, Any], index: int) -> str:
    return f"""
    <article class="pattern">
      <span>{index:02d}</span>
      <div><h3>{esc(pattern.get("title", "Repeated signal"))}</h3><p>{esc(pattern.get("insight", ""))}</p></div>
      <strong>{clamp(pattern.get("count"), 999)}x</strong>
    </article>"""


def build_html(data: dict[str, Any]) -> str:
    prospects = [item for item in as_items(data.get("prospects")) if isinstance(item, dict)]
    patterns = [item for item in as_items(data.get("patterns")) if isinstance(item, dict)]
    scores = [clamp(item.get("score")) for item in prospects]
    average_score = round(sum(scores) / len(scores)) if scores else 0
    high_intent = sum(1 for item in prospects if "high" in str(item.get("stage", "")).lower())
    top = max(prospects, key=lambda item: clamp(item.get("score")), default={})
    plan = data.get("outreach_plan") if isinstance(data.get("outreach_plan"), dict) else {}
    limits = "".join(f"<li>{esc(item)}</li>" for item in as_items(data.get("limits")))
    prospect_html = "".join(render_prospect(item, index) for index, item in enumerate(prospects, 1))
    pattern_html = "".join(render_pattern(item, index) for index, item in enumerate(patterns, 1))
    product_url = safe_url(data.get("product_url"))

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>{esc(data.get("title", "Finding Your First Customer"))}</title>
  <style>
    :root {{
      --bg: #0b0c10;
      --panel: #141820;
      --panel-2: #1d232d;
      --ink: #f7f4ea;
      --muted: #aab2c0;
      --line: #303844;
      --accent: #d9ff63;
      --blue: #76bdff;
      --orange: #ff9566;
      --green: #66e3c4;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      line-height: 1.55;
    }}
    a {{ color: inherit; }}
    .shell {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; }}
    .top {{
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: center;
      padding: 22px 0;
      border-bottom: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
      font-weight: 700;
    }}
    .hero {{
      display: grid;
      grid-template-columns: 1.35fr .65fr;
      gap: 28px;
      align-items: end;
      padding: 64px 0 32px;
    }}
    .eyebrow, .grid span, .signal span, blockquote span, .evidence span, .stat span {{
      display: block;
      color: var(--accent);
      font: 750 11px ui-monospace, SFMono-Regular, Menlo, monospace;
      letter-spacing: .08em;
      text-transform: uppercase;
      margin-bottom: 7px;
    }}
    h1 {{
      margin: 10px 0 20px;
      font-size: clamp(44px, 7vw, 86px);
      line-height: .94;
      letter-spacing: 0;
    }}
    .verdict {{ max-width: 760px; color: #dbe1ea; font-size: clamp(18px, 2.1vw, 24px); margin: 0; }}
    .summary-card {{
      background: var(--accent);
      color: #11140d;
      padding: 24px;
      border-radius: 8px;
      box-shadow: 0 22px 70px rgba(0,0,0,.32);
    }}
    .summary-card strong {{ display: block; font-size: 58px; line-height: 1; }}
    .summary-card span {{ font-weight: 850; text-transform: uppercase; font-size: 12px; }}
    .stats {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      border: 1px solid var(--line);
      border-radius: 8px;
      overflow: hidden;
      margin: 8px 0 28px;
    }}
    .stat {{ padding: 18px; background: var(--panel); min-width: 0; }}
    .stat + .stat {{ border-left: 1px solid var(--line); }}
    .stat strong {{ display: block; overflow-wrap: anywhere; }}
    .best {{
      display: grid;
      grid-template-columns: 170px 1fr auto;
      gap: 20px;
      align-items: center;
      background: var(--orange);
      color: #1b0f08;
      border-radius: 8px;
      padding: 24px;
      margin: 0 0 58px;
    }}
    .best h2 {{ margin: 0 0 6px; font-size: clamp(26px, 4vw, 42px); line-height: 1; letter-spacing: 0; }}
    .best p {{ margin: 0; }}
    .best strong {{ font-size: 42px; }}
    .section-head {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: end;
      border-bottom: 1px solid var(--line);
      padding-bottom: 18px;
      margin-bottom: 18px;
    }}
    .section-head h2 {{ margin: 0; font-size: clamp(34px, 5vw, 58px); line-height: 1; letter-spacing: 0; }}
    .section-head p {{ max-width: 470px; margin: 0; color: var(--muted); }}
    .prospects {{ display: grid; gap: 16px; margin-bottom: 60px; }}
    .prospect {{
      background: linear-gradient(135deg, var(--panel), #10141b);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 24px;
      box-shadow: 0 12px 36px rgba(0,0,0,.18);
    }}
    .prospect-head {{ display: grid; grid-template-columns: 52px 1fr 92px; gap: 16px; align-items: start; }}
    .rank {{ color: var(--accent); font: 850 24px ui-monospace, SFMono-Regular, Menlo, monospace; padding-top: 8px; }}
    .prospect h3 {{ margin: 5px 0 10px; font-size: 28px; line-height: 1.1; letter-spacing: 0; }}
    .stage {{ display: inline-block; border: 1px solid var(--line); border-radius: 999px; padding: 6px 9px; color: var(--muted); font-size: 12px; font-weight: 750; }}
    .stage.hot {{ color: var(--orange); border-color: rgba(255,149,102,.55); }}
    .stage.warm {{ color: var(--green); border-color: rgba(102,227,196,.45); }}
    .score {{
      --score: 0;
      width: 88px;
      height: 88px;
      border-radius: 50%;
      display: grid;
      place-content: center;
      text-align: center;
      background: radial-gradient(circle, var(--panel) 58%, transparent 60%), conic-gradient(var(--accent) calc(var(--score) * 1%), var(--line) 0);
    }}
    .score strong {{ font-size: 26px; line-height: 1; }}
    .score small {{ color: var(--muted); }}
    .signal {{ margin: 20px 0 12px; padding: 16px; background: var(--panel-2); border-left: 4px solid var(--accent); }}
    .signal p, .grid p, .evidence p {{ margin: 0; }}
    .grid, .evidence {{ display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }}
    .grid > div, .evidence > div {{ border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: rgba(255,255,255,.02); }}
    blockquote {{ margin: 12px 0 0; padding: 16px; border: 1px dashed rgba(217,255,99,.55); border-radius: 8px; color: #eef9ca; }}
    details {{ margin-top: 10px; }}
    summary {{ cursor: pointer; color: var(--accent); font-weight: 800; padding: 10px 0; }}
    .evidence a {{ display: inline-block; margin-top: 8px; color: var(--blue); overflow-wrap: anywhere; }}
    .metrics {{ display: grid; gap: 8px; margin-top: 14px; }}
    .metric {{ display: grid; grid-template-columns: 145px 1fr 42px; gap: 12px; align-items: center; font-size: 13px; }}
    .track {{ height: 8px; border-radius: 8px; background: var(--line); overflow: hidden; }}
    .track i {{ display: block; height: 100%; background: linear-gradient(90deg, var(--blue), var(--accent)); }}
    .patterns {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; margin-bottom: 60px; }}
    .pattern {{ display: grid; grid-template-columns: 42px 1fr auto; gap: 14px; align-items: start; padding: 18px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); }}
    .pattern span {{ color: var(--accent); font: 800 13px ui-monospace, SFMono-Regular, Menlo, monospace; }}
    .pattern h3 {{ margin: 0 0 5px; }}
    .pattern p {{ margin: 0; color: var(--muted); }}
    .pattern strong {{ font-size: 28px; color: var(--accent); }}
    .plan {{ display: grid; grid-template-columns: .8fr 1.2fr; gap: 24px; background: var(--accent); color: #11140d; padding: 26px; border-radius: 8px; margin-bottom: 24px; }}
    .plan h2 {{ margin: 8px 0 0; font-size: 36px; line-height: 1.05; letter-spacing: 0; }}
    .plan .eyebrow {{ color: #11140d; }}
    .plan-grid {{ display: grid; grid-template-columns: 1fr 1fr; gap: 9px; }}
    .plan-grid div {{ border: 1px solid rgba(0,0,0,.25); border-radius: 8px; padding: 13px; }}
    .plan-grid span {{ display: block; font: 750 10px ui-monospace, SFMono-Regular, Menlo, monospace; text-transform: uppercase; margin-bottom: 5px; }}
    .plan-grid p {{ margin: 0; }}
    .limits {{ border: 1px solid var(--line); border-radius: 8px; padding: 22px; color: var(--muted); margin-bottom: 54px; }}
    .limits h2 {{ color: var(--ink); margin-top: 0; }}
    footer {{ display: flex; justify-content: space-between; gap: 20px; border-top: 1px solid var(--line); padding: 22px 0 40px; color: var(--muted); font-size: 12px; }}
    @media (max-width: 820px) {{
      .hero, .best, .plan {{ grid-template-columns: 1fr; }}
      .stats, .patterns, .grid, .evidence, .plan-grid {{ grid-template-columns: 1fr; }}
      .stat + .stat {{ border-left: 0; border-top: 1px solid var(--line); }}
      .prospect-head {{ grid-template-columns: 38px 1fr; }}
      .score {{ grid-column: 1 / -1; }}
      .section-head {{ display: block; }}
      .section-head p {{ margin-top: 10px; }}
    }}
    @media print {{
      body {{ background: #fff; color: #111; }}
      .prospect, .pattern, .limits {{ break-inside: avoid; background: #fff; color: #111; }}
      .top {{ color: #333; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <header class="top">
      <span>Finding Your First Customer</span>
      <span>Public signals only | Outreach not sent automatically</span>
    </header>
    <main>
      <section class="hero">
        <div>
          <span class="eyebrow">Early-customer report | {esc(data.get("generated_at", ""))}</span>
          <h1>{esc(data.get("title", "Finding Your First Customer"))}</h1>
          <p class="verdict">{esc(data.get("verdict", "No verdict supplied."))}</p>
        </div>
        <aside class="summary-card">
          <span>Qualified prospects</span>
          <strong>{len(prospects)}</strong>
          <p>Potential customers based on public signals.</p>
        </aside>
      </section>
      <section class="stats">
        <div class="stat"><span>Product</span><strong><a href="{product_url}" target="_blank" rel="noreferrer">{esc(data.get("product", "Not specified"))}</a></strong></div>
        <div class="stat"><span>Target customer</span><strong>{esc(data.get("target_customer", "Not specified"))}</strong></div>
        <div class="stat"><span>High intent</span><strong>{high_intent}</strong></div>
        <div class="stat"><span>Average score</span><strong>{average_score}/100</strong></div>
      </section>
      <section class="best">
        <div><strong>Top prospect</strong></div>
        <div><h2>{esc(top.get("name", "No qualified prospect"))}</h2><p>{esc(top.get("why_now", top.get("pain_signal", "")))}</p></div>
        <strong>{clamp(top.get("score"))}</strong>
      </section>
      <section>
        <header class="section-head">
          <h2>People with a reason to care now.</h2>
          <p>Every primary prospect is tied to public pain, demand, workaround, or timing evidence.</p>
        </header>
        <div class="prospects">{prospect_html or "<p>No qualified prospects supplied.</p>"}</div>
      </section>
      <section>
        <header class="section-head">
          <h2>Signals that repeat.</h2>
          <p>Patterns across prospects reveal the strongest positioning, workflow, and concierge offer angles.</p>
        </header>
        <div class="patterns">{pattern_html or "<p>No repeated patterns supplied.</p>"}</div>
      </section>
      <section class="plan">
        <div>
          <span class="eyebrow">Seven-day manual plan</span>
          <h2>{esc(plan.get("angle", "Validate the pain before pitching the product."))}</h2>
        </div>
        <div class="plan-grid">
          <div><span>First step</span><p>{esc(plan.get("first_step", ""))}</p></div>
          <div><span>Follow-up</span><p>{esc(plan.get("follow_up", ""))}</p></div>
          <div><span>Success signal</span><p>{esc(plan.get("success", ""))}</p></div>
          <div><span>Research scope</span><p>{esc(data.get("search_scope", "Not specified"))}</p></div>
        </div>
      </section>
      <section class="limits">
        <h2>Use this shortlist responsibly</h2>
        <ul>{limits or "<li>These are potential customers inferred from public signals, not confirmed buyers.</li>"}</ul>
      </section>
    </main>
    <footer>
      <span>Generated by $finding-your-first-customer</span>
      <span>Manual validation before automation.</span>
    </footer>
  </div>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Path to report JSON")
    parser.add_argument("output", type=Path, help="Path to output HTML")
    args = parser.parse_args()

    with args.input.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise SystemExit("Input JSON must contain an object at the top level.")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(build_html(data), encoding="utf-8")
    print(f"Created report: {args.output.resolve()}")


if __name__ == "__main__":
    main()
