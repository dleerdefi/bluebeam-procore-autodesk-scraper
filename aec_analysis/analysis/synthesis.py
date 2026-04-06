"""Aggregate extraction results into per-category and cross-platform summaries."""

import json
from collections import defaultdict

from .config import RESULTS_DIR, SYNTHESIS_DIR
from .prompts import CATEGORY_LABELS


def load_all_extractions(platform: str) -> list[dict]:
    """Load all extraction results for a platform."""
    results_dir = RESULTS_DIR / platform
    all_ext = []
    if not results_dir.exists():
        return all_ext
    for f in sorted(results_dir.glob("batch_*.json")):
        with open(f, "r", encoding="utf-8") as fh:
            r = json.load(fh)
        if r.get("json_valid"):
            for i, ext in enumerate(r.get("extractions", [])):
                ext["_title"] = r["thread_titles"][i] if i < len(r.get("thread_titles", [])) else ""
                ext["_platform"] = platform
            all_ext.extend(r.get("extractions", []))
    return all_ext


def synthesize_platform(platform: str, extractions: list[dict]) -> dict:
    """Aggregate extractions into per-category summary."""
    cats = defaultdict(lambda: {
        "count": 0, "severities": [], "sentiments": defaultdict(int),
        "staff_responded": 0, "total_agreement": 0,
        "top_needs": [], "sample_titles": [],
    })

    for ext in extractions:
        cat = ext.get("category", "ux_usability")
        c = cats[cat]
        c["count"] += 1
        sev = ext.get("severity", 0)
        if isinstance(sev, (int, float)):
            c["severities"].append(sev)
        c["sentiments"][ext.get("sentiment", "neutral")] += 1
        if ext.get("staff_response"):
            c["staff_responded"] += 1
        c["total_agreement"] += ext.get("user_agreement", 0) or 0
        c["top_needs"].append({
            "need": ext.get("need", ""),
            "severity": sev,
            "title": ext.get("_title", ""),
        })
        if len(c["sample_titles"]) < 5:
            c["sample_titles"].append(ext.get("_title", ""))

    summary = {}
    for cat, c in cats.items():
        c["top_needs"].sort(key=lambda x: x.get("severity", 0), reverse=True)
        avg_sev = sum(c["severities"]) / len(c["severities"]) if c["severities"] else 0
        summary[cat] = {
            "count": c["count"],
            "avg_severity": round(avg_sev, 2),
            "gap_score": round(c["count"] * avg_sev, 1),
            "sentiments": dict(c["sentiments"]),
            "negative_pct": round(c["sentiments"].get("negative", 0) / max(c["count"], 1) * 100, 1),
            "staff_response_rate": round(c["staff_responded"] / max(c["count"], 1) * 100, 1),
            "top_needs": c["top_needs"][:5],
            "sample_titles": c["sample_titles"][:5],
        }

    return summary


def run_synthesis():
    """Synthesize all platform results into per-platform and cross-platform summaries."""
    SYNTHESIS_DIR.mkdir(parents=True, exist_ok=True)
    all_summaries = {}

    for platform in ["bluebeam", "autodesk", "procore"]:
        print(f"  Synthesizing {platform}...")
        extractions = load_all_extractions(platform)
        if not extractions:
            print(f"    No extractions found — skipping")
            continue
        summary = synthesize_platform(platform, extractions)
        all_summaries[platform] = summary

        with open(SYNTHESIS_DIR / f"{platform}_summary.json", "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"    {len(extractions)} extractions -> {len(summary)} categories")

    # Cross-platform matrix
    cross = {}
    all_cats = set()
    for s in all_summaries.values():
        all_cats.update(s.keys())

    for cat in sorted(all_cats):
        cross[cat] = {
            "label": CATEGORY_LABELS.get(cat, cat),
            "platforms": {},
            "total_count": 0,
            "avg_gap_score": 0,
        }
        scores = []
        for platform, summary in all_summaries.items():
            if cat in summary:
                cross[cat]["platforms"][platform] = summary[cat]
                cross[cat]["total_count"] += summary[cat]["count"]
                scores.append(summary[cat]["gap_score"])
        cross[cat]["avg_gap_score"] = round(sum(scores) / len(scores), 1) if scores else 0

    with open(SYNTHESIS_DIR / "cross_platform.json", "w", encoding="utf-8") as f:
        json.dump(cross, f, ensure_ascii=False, indent=2)

    ranked = sorted(cross.values(), key=lambda x: x["avg_gap_score"], reverse=True)
    print(f"\n  Top 10 Cross-Platform Opportunities:")
    for i, item in enumerate(ranked[:10]):
        print(f"    {i+1}. {item['label']} (gap={item['avg_gap_score']}, mentions={item['total_count']})")
        for p, d in item["platforms"].items():
            print(f"       {p}: {d['count']} posts, sev={d['avg_severity']}, {d['negative_pct']}% negative")

    return all_summaries, cross
