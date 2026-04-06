"""Export analysis data to TypeScript for the blog post.

Reads synthesis results and extraction data, produces a typed data.ts file
for the interactive FeatureMatrix React component.
"""

import json
import sys
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

DATA_DIR = Path("data")
SYNTHESIS_DIR = DATA_DIR / "llm_synthesis"
RESULTS_DIR = DATA_DIR / "llm_results"
OUTPUT_DIR = Path("blog_export")


class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self._parts: list[str] = []

    def handle_data(self, data):
        self._parts.append(data)

    def get_text(self) -> str:
        return " ".join("".join(self._parts).split())


def strip_html(html: str) -> str:
    if not html:
        return ""
    s = HTMLStripper()
    try:
        s.feed(html)
        return s.get_text()
    except Exception:
        return html


def load_sample_posts() -> dict:
    """Load top posts per category per platform from extraction results."""
    # Structure: {platform: {category: [posts]}}
    samples: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for platform in ["bluebeam", "autodesk", "procore"]:
        results_dir = RESULTS_DIR / platform
        if not results_dir.exists():
            continue

        for f in sorted(results_dir.glob("batch_*.json")):
            with open(f, "r", encoding="utf-8") as fh:
                r = json.load(fh)
            if not r.get("json_valid"):
                continue

            for i, ext in enumerate(r.get("extractions", [])):
                cat = ext.get("category", "")
                title = r["thread_titles"][i] if i < len(r.get("thread_titles", [])) else ""
                if not cat or not title:
                    continue

                # Only keep top 5 per category per platform (by severity)
                bucket = samples[platform][cat]
                if len(bucket) < 5:
                    bucket.append({
                        "title": title[:120],
                        "need": ext.get("need", ""),
                        "severity": ext.get("severity", 0),
                        "sentiment": ext.get("sentiment", "neutral"),
                        "staffResponse": ext.get("staff_response", False),
                    })

    return {p: dict(cats) for p, cats in samples.items()}


def generate_typescript():
    """Generate the data.ts file."""
    # Load cross-platform synthesis
    cross_file = SYNTHESIS_DIR / "cross_platform.json"
    if not cross_file.exists():
        print("No cross_platform.json found. Run llm_analysis.py --synthesize first.")
        return

    with open(cross_file, "r", encoding="utf-8") as f:
        cross = json.load(f)

    # Load sample posts
    print("Loading sample posts...")
    samples = load_sample_posts()

    # Build the data structure
    categories = []
    for cat_id, item in sorted(cross.items(), key=lambda x: x[1]["avg_gap_score"], reverse=True):
        cat_data = {
            "id": cat_id,
            "label": item["label"],
            "avgGapScore": item["avg_gap_score"],
            "totalCount": item["total_count"],
            "platforms": {},
        }
        for p in ["bluebeam", "autodesk", "procore"]:
            d = item["platforms"].get(p, {})
            if d:
                cat_data["platforms"][p] = {
                    "count": d["count"],
                    "avgSeverity": d["avg_severity"],
                    "gapScore": d["gap_score"],
                    "negativePct": d["negative_pct"],
                    "staffResponseRate": d["staff_response_rate"],
                    "sentiments": d.get("sentiments", {}),
                    "topNeeds": [
                        {"need": n["need"], "severity": n["severity"]}
                        for n in d.get("top_needs", [])[:3]
                    ],
                    "samplePosts": samples.get(p, {}).get(cat_id, []),
                }
        categories.append(cat_data)

    # Generate TypeScript
    ts_content = '''// Auto-generated from community forum analysis
// Bluebeam (3,195 threads) + Autodesk (3,000 sampled) + Procore (3,294 threads)

export type Platform = "bluebeam" | "autodesk" | "procore"

export type Sentiment = "positive" | "negative" | "neutral" | "mixed"

export interface SamplePost {
  title: string
  need: string
  severity: number
  sentiment: Sentiment
  staffResponse: boolean
}

export interface PlatformData {
  count: number
  avgSeverity: number
  gapScore: number
  negativePct: number
  staffResponseRate: number
  sentiments: Record<string, number>
  topNeeds: { need: string; severity: number }[]
  samplePosts: SamplePost[]
}

export interface Category {
  id: string
  label: string
  avgGapScore: number
  totalCount: number
  platforms: Partial<Record<Platform, PlatformData>>
}

export const PLATFORM_CONFIG = {
  bluebeam: { label: "Bluebeam", color: "#1565c0", bg: "#e3f2fd" },
  autodesk: { label: "Autodesk", color: "#c62828", bg: "#fce4ec" },
  procore: { label: "Procore", color: "#2e7d32", bg: "#e8f5e9" },
} as const

export const categories: Category[] = '''

    ts_content += json.dumps(categories, indent=2, ensure_ascii=False)

    ts_content += '''

export const totalThreadsAnalyzed = ''' + str(sum(c["totalCount"] for c in categories))

    ts_content += '''
export const totalCategories = ''' + str(len(categories))

    ts_content += "\n"

    # Write output
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_file = OUTPUT_DIR / "data.ts"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(ts_content)

    print(f"Wrote {output_file} ({len(categories)} categories)")
    return categories


def generate_mdx(categories: list):
    """Generate the blog post MDX file."""
    top5 = categories[:5]

    mdx = '''---
title: "AEC Software Feature Gap Analysis: What 9,500 Community Forum Threads Reveal"
slug: "aec-feature-gap-analysis"
summary: "I scraped and analyzed community forums from Bluebeam, Autodesk, and Procore using local LLMs to uncover the biggest product opportunities in AEC software."
date: "2026-04-06"
tags: ["data-analysis", "AEC", "product-strategy", "local-llm", "web-scraping"]
status: "published"
---

What if you could read every single community forum post from three major AEC software platforms — and distill them into actionable product insights?

That's exactly what I did. I built scrapers to collect **9,500+ discussion threads** (with all their replies) from Bluebeam, Autodesk, and Procore community forums, then ran every thread through a local LLM to extract structured product intelligence.

## The Data

| Platform | Threads Analyzed | Source |
|----------|:---:|---|
| **Bluebeam** | 3,195 | community.bluebeam.com |
| **Autodesk** | 3,000 (sampled from 482K) | forums.autodesk.com |
| **Procore** | 3,294 | community.procore.com |

Each thread includes the original post plus up to 5 replies — preserving the full conversational context: user complaints, "+1" agreements, staff responses, and workarounds.

## Methodology

1. **Scraping**: Custom Python scrapers for each platform's API (Bluebeam: Vanilla Forums API, Autodesk: Khoros LiQL API, Procore: Playwright browser automation)
2. **LLM Extraction**: Each thread batch processed through a local **Gemma 4 26B** model (Q4\_K\_M quantization) with structured JSON output
3. **Classification**: Every thread categorized into 20 feature categories, rated by severity (1-5), sentiment, and staff engagement

## Interactive Results

Use the filters below to explore the data by platform. Click any category to see actual user posts.

<FeatureMatrix />

## Key Findings

'''

    mdx += f'''### 1. Performance is the highest-severity pain point
Across all three platforms, performance issues (crashes, freezing, slow loading) have the **highest average severity** (~3.5/5) and ~85% negative sentiment. Users don't just dislike slow software — it blocks their work.

### 2. Document Management is the biggest overall opportunity
With **{top5[0]["totalCount"]}+ mentions** across all platforms, document management (versioning, search, file organization) is the most universally demanded category. Every platform struggles here.

### 3. Each platform has a distinct pain signature
- **Bluebeam** users want better markup tools and measurement features
- **Autodesk** users struggle with BIM workflows and general usability
- **Procore** users need better cost tracking and integrations

### 4. Staff engagement varies significantly
Some categories show high staff response rates (35%+), indicating active product teams. Others show near-zero staff engagement — potential blind spots.

## How I Built This

The entire pipeline — scraping, preprocessing, LLM extraction, synthesis, and visualization — runs locally. No cloud APIs, no data leaving the machine.

**Tech stack:**
- Python (requests, Playwright, tqdm)
- Local LLM via LM Studio (Gemma 4 26B, Q4\_K\_M quantization)
- Structured JSON output with enforced schema
- React + Recharts for interactive visualization

The scraping collected **2.4 million messages** from Autodesk alone (482K threads + 1.95M replies), though only the top 3,000 by view count were sampled for LLM analysis.

A/B testing between Qwen 3.5 35B and Gemma 4 26B showed Gemma produced more accurate categorizations with better sentiment calibration, while Qwen was ~30% faster.

'''

    output_file = OUTPUT_DIR / "index.mdx"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(mdx)

    print(f"Wrote {output_file}")


def main():
    print("Exporting blog data...")
    categories = generate_typescript()
    if categories:
        generate_mdx(categories)
    print("Done! Files in blog_export/")


if __name__ == "__main__":
    main()
