"""Eval runner — loads golden.jsonl, runs the meal graph on each case, reports.

Run:
    podman compose -f docker-compose.dev.yml exec api python -m app.evals.run
    podman compose -f docker-compose.dev.yml exec api python -m app.evals.run --output /tmp/report.md

Metrics produced:
  • is_food classification accuracy
  • parse accuracy (name / brand / amount / unit match)
  • nutrition MAPE per macro (kcal / protein / fat / carbs)
  • pass-rate: cases where ALL macros within ±10% AND is_food matches
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.graph.graph import get_meal_graph
from app.mcp.client import start_nutrition_mcp, stop_nutrition_mcp

GOLDEN_PATH = Path(__file__).parent / "golden.jsonl"
PASS_TOLERANCE = 0.10  # ±10% per macro counts as pass


@dataclass
class CaseResult:
    case: dict
    parsed: list[dict] = field(default_factory=list)
    resolved: list[dict] = field(default_factory=list)
    is_food_predicted: bool | None = None
    error: str | None = None
    total: dict[str, float] = field(
        default_factory=lambda: {"kcal": 0.0, "p": 0.0, "f": 0.0, "c": 0.0}
    )


# ─── Per-macro delta helpers ──────────────────────────────────────────────────


def _pct(actual: float, expected: float) -> float | None:
    """Return signed % delta, or None when expected==0 and actual==0 (N/A)."""
    if expected == 0 and actual == 0:
        return None
    if expected == 0:
        return float("inf")  # over-counted a zero-expected macro
    return (actual - expected) / expected * 100.0


def _fmt_pct(delta: float | None) -> str:
    if delta is None:
        return "—"
    if delta == float("inf"):
        return "+∞"
    sign = "+" if delta >= 0 else ""
    return f"{sign}{delta:.0f}%"


def _is_pass(result: CaseResult) -> tuple[bool, str]:
    """A case passes if is_food matches AND all macros within ±tolerance."""
    expected_is_food = result.case.get("is_food", True)
    if result.is_food_predicted != expected_is_food:
        return (
            False,
            f"is_food mismatch (got={result.is_food_predicted}, want={expected_is_food})",
        )

    if not expected_is_food:
        return True, ""  # non-food correctly rejected

    exp = result.case["expected_nutrition"]
    for macro_key, exp_key in [
        ("kcal", "kcal"),
        ("p", "protein_g"),
        ("f", "fat_g"),
        ("c", "carbs_g"),
    ]:
        delta = _pct(result.total[macro_key], exp[exp_key])
        if delta is None:
            continue
        if delta == float("inf"):
            return False, f"{macro_key} expected 0, got {result.total[macro_key]:.1f}"
        if abs(delta) > PASS_TOLERANCE * 100:
            return (
                False,
                f"{macro_key} delta {delta:+.0f}% (>{PASS_TOLERANCE * 100:.0f}%)",
            )

    return True, ""


# ─── Runner ───────────────────────────────────────────────────────────────────


async def _run_one(graph, case: dict) -> CaseResult:
    result = CaseResult(case=case)
    state = {
        "raw_input_type": "text",
        "text_input": case["input"],
        "telegram_user_id": 999999,
    }
    try:
        out = await graph.ainvoke(state)
    except Exception as exc:
        result.error = f"{exc.__class__.__name__}: {exc}"
        return result

    result.is_food_predicted = out.get("is_food_related", True)
    for p in out.get("parsed_items") or []:
        result.parsed.append(
            {
                "name": p.name,
                "brand": p.brand,
                "amount": p.amount,
                "unit": p.unit.value,
            }
        )
    for r in out.get("resolved_items") or []:
        payload = r["payload"]
        result.resolved.append(
            {
                "food_name": payload.food_name,
                "amount": payload.amount,
                "unit": payload.unit.value,
                "kcal": payload.kcal,
                "p": payload.protein_g,
                "f": payload.fat_g,
                "c": payload.carbs_g,
                "source": r["source"].value
                if hasattr(r["source"], "value")
                else str(r["source"]),
            }
        )
        result.total["kcal"] += payload.kcal
        result.total["p"] += payload.protein_g
        result.total["f"] += payload.fat_g
        result.total["c"] += payload.carbs_g
    return result


def _load_golden() -> list[dict]:
    cases: list[dict] = []
    for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("//"):
            cases.append(json.loads(line))
    return cases


# ─── Report rendering ─────────────────────────────────────────────────────────


_MACRO_KEYS: list[tuple[str, str]] = [
    ("kcal", "kcal"),
    ("p", "protein_g"),
    ("f", "fat_g"),
    ("c", "carbs_g"),
]
_MACRO_LABELS: list[tuple[str, str]] = [
    ("kcal", "kcal"),
    ("p", "protein"),
    ("f", "fat"),
    ("c", "carbs"),
]


def _render_case_row(idx: int, r: CaseResult) -> tuple[str, bool]:
    """Render one Markdown table row; also report whether the case passed."""
    passed, reason = _is_pass(r)
    exp = r.case.get("expected_nutrition") or {}
    d_kcal = _pct(r.total["kcal"], exp.get("kcal", 0))
    d_p = _pct(r.total["p"], exp.get("protein_g", 0))
    d_f = _pct(r.total["f"], exp.get("fat_g", 0))
    d_c = _pct(r.total["c"], exp.get("carbs_g", 0))
    is_food_cell = f"{r.is_food_predicted}"
    if r.is_food_predicted != r.case.get("is_food", True):
        is_food_cell = f"❌ {is_food_cell}"
    input_short = r.case["input"].replace("\n", " ⏎ ")
    if len(input_short) > 60:
        input_short = input_short[:57] + "…"
    pass_cell = "✅" if passed else f"❌ {reason}" if reason else "❌"
    row = (
        f"| {idx} | `{input_short}` | {is_food_cell} | "
        f"{_fmt_pct(d_kcal)} | {_fmt_pct(d_p)} | {_fmt_pct(d_f)} | {_fmt_pct(d_c)} | "
        f"{pass_cell} | {r.case.get('source', '')} |"
    )
    return row, passed


def _render_per_case_table(results: list[CaseResult]) -> tuple[list[str], int]:
    lines = [
        "\n## Per-case results\n",
        "| # | Input | is_food | ΔKcal | ΔP | ΔF | ΔC | Pass | Source |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    pass_count = 0
    for i, r in enumerate(results, 1):
        row, passed = _render_case_row(i, r)
        lines.append(row)
        if passed:
            pass_count += 1
    return lines, pass_count


def _compute_macro_mapes(results: list[CaseResult]) -> dict[str, list[float]]:
    mapes: dict[str, list[float]] = {"kcal": [], "p": [], "f": [], "c": []}
    for r in results:
        if not r.case.get("is_food", True):
            continue
        exp = r.case.get("expected_nutrition") or {}
        for mkey, ekey in _MACRO_KEYS:
            ev = exp.get(ekey, 0)
            if ev == 0:
                continue
            mapes[mkey].append(abs((r.total[mkey] - ev) / ev) * 100.0)
    return mapes


def _render_mape_lines(mapes: dict[str, list[float]]) -> list[str]:
    out = ["- **MAPE (food cases only):**"]
    for mkey, label in _MACRO_LABELS:
        values = mapes[mkey]
        if not values:
            out.append(f"  - {label}: — (no data)")
            continue
        mean_mape = sum(values) / len(values)
        within_10 = sum(1 for v in values if v <= 10)
        within_20 = sum(1 for v in values if v <= 20)
        out.append(
            f"  - {label}: mean={mean_mape:.1f}% · "
            f"within ±10%: {within_10}/{len(values)} · "
            f"within ±20%: {within_20}/{len(values)}"
        )
    return out


def _render_source_breakdown(results: list[CaseResult]) -> list[str]:
    counts: dict[str, int] = {}
    total = 0
    for r in results:
        for item in r.resolved:
            counts[item["source"]] = counts.get(item["source"], 0) + 1
            total += 1
    if not total:
        return []
    out = [f"- **Resolved items by source** (total {total}):"]
    for src, n_items in sorted(counts.items(), key=lambda x: -x[1]):
        out.append(f"  - {src}: {n_items} ({n_items / total * 100:.0f}%)")
    return out


def _render_aggregate(results: list[CaseResult], pass_count: int) -> list[str]:
    n = len(results)
    lines = [
        "\n## Aggregate\n",
        f"- **Pass rate:** {pass_count}/{n} = **{pass_count / n * 100:.1f}%**",
    ]
    is_food_correct = sum(
        1 for r in results if r.is_food_predicted == r.case.get("is_food", True)
    )
    lines.append(
        f"- **is_food accuracy:** {is_food_correct}/{n} = {is_food_correct / n * 100:.1f}%"
    )
    lines.extend(_render_mape_lines(_compute_macro_mapes(results)))
    lines.extend(_render_source_breakdown(results))
    return lines


def _render_failures(results: list[CaseResult]) -> list[str]:
    fails = [r for r in results if not _is_pass(r)[0]]
    if not fails:
        return []
    out = [f"\n## Failures ({len(fails)})\n"]
    for r in fails:
        _, reason = _is_pass(r)
        out.append(f"\n### `{r.case['input'][:80]}`")
        out.append(f"- **Reason:** {reason}")
        out.append(f"- Parsed: {json.dumps(r.parsed, ensure_ascii=False)}")
        out.append(f"- Resolved: {json.dumps(r.resolved, ensure_ascii=False)}")
        out.append(f"- Got total: {r.total}")
        out.append(f"- Expected: {r.case.get('expected_nutrition')}")
        if r.error:
            out.append(f"- Error: `{r.error}`")
        if r.case.get("notes"):
            out.append(f"- Notes: {r.case['notes']}")
    return out


def _render_markdown(results: list[CaseResult]) -> str:
    lines = [
        "# NutriSnap Eval Report\n",
        f"**Cases:** {len(results)}  ·  **Tolerance:** ±{PASS_TOLERANCE * 100:.0f}% per macro\n",
    ]
    case_lines, pass_count = _render_per_case_table(results)
    lines.extend(case_lines)
    lines.extend(_render_aggregate(results, pass_count))
    lines.extend(_render_failures(results))
    return "\n".join(lines)


async def main() -> None:
    parser = argparse.ArgumentParser(description="NutriSnap eval runner")
    parser.add_argument(
        "--output", "-o", default=None, help="Path to write markdown report"
    )
    parser.add_argument(
        "--limit", type=int, default=None, help="Run only first N cases"
    )
    args = parser.parse_args()

    cases = _load_golden()
    if args.limit:
        cases = cases[: args.limit]
    graph = get_meal_graph()

    # The graph's nutrition node talks to the Nutrition MCP server, which only
    # the FastAPI lifespan normally starts — bring it up for the standalone run.
    await start_nutrition_mcp()
    try:
        results: list[CaseResult] = []
        for i, case in enumerate(cases, 1):
            print(f"[{i}/{len(cases)}] {case['input'][:60]!r}", file=sys.stderr)
            results.append(await _run_one(graph, case))
    finally:
        await stop_nutrition_mcp()

    report = _render_markdown(results)
    if args.output:
        Path(args.output).write_text(report, encoding="utf-8")
        print(f"✓ Report written to {args.output}", file=sys.stderr)
    print(report)


if __name__ == "__main__":
    asyncio.run(main())
