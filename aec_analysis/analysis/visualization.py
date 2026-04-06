"""Interactive HTML report and CSV export from cross-platform synthesis data."""

import csv
import json
from html import escape

from .config import DATA_DIR, SYNTHESIS_DIR


def build_feature_matrix_html(cross: dict) -> str:
    """Build self-contained HTML feature gap matrix report with interactive Chart.js charts."""
    import json as _json

    ranked = sorted(cross.values(), key=lambda x: x["avg_gap_score"], reverse=True)
    platforms = ["bluebeam", "autodesk", "procore"]
    platform_labels = {"bluebeam": "Bluebeam", "autodesk": "Autodesk", "procore": "Procore"}
    platform_colors = {
        "bluebeam": {"bg": "rgba(21,101,192,0.2)", "border": "rgba(21,101,192,1)"},
        "autodesk": {"bg": "rgba(198,40,40,0.2)", "border": "rgba(198,40,40,1)"},
        "procore": {"bg": "rgba(46,125,50,0.2)", "border": "rgba(46,125,50,1)"},
    }

    max_gap = max((item["avg_gap_score"] for item in ranked), default=1)
    max_count = max(
        (item["platforms"].get(p, {}).get("count", 0) for item in ranked for p in platforms),
        default=1,
    )

    def heat_color(value, max_val):
        if max_val == 0:
            return "background: #f8f9fa"
        intensity = min(value / max_val, 1.0)
        if intensity < 0.2: return "background: #f0f4ff"
        elif intensity < 0.4: return "background: #d0e0ff"
        elif intensity < 0.6: return "background: #a0c0ff"
        elif intensity < 0.8: return "background: #5090e0; color: #fff"
        else: return "background: #1a56c4; color: #fff"

    def neg_color(pct):
        if pct >= 50: return "color: #c62828; font-weight: 700"
        elif pct >= 30: return "color: #e65100"
        return ""

    # --- Prepare chart data ---
    top10 = ranked[:10]
    top10_labels = _json.dumps([item["label"] for item in top10])

    radar_datasets = []
    for p in platforms:
        values = [item["platforms"].get(p, {}).get("gap_score", 0) for item in top10]
        radar_datasets.append({
            "label": platform_labels[p],
            "data": values,
            "backgroundColor": platform_colors[p]["bg"],
            "borderColor": platform_colors[p]["border"],
            "borderWidth": 2,
            "pointRadius": 4,
        })

    bar_datasets = []
    for p in platforms:
        values = [item["platforms"].get(p, {}).get("gap_score", 0) for item in top10]
        bar_datasets.append({
            "label": platform_labels[p],
            "data": values,
            "backgroundColor": platform_colors[p]["border"],
        })

    bubble_datasets = []
    for p in platforms:
        bubbles = []
        for item in ranked:
            d = item["platforms"].get(p, {})
            if d and d.get("count", 0) > 0:
                bubbles.append({
                    "x": d["count"],
                    "y": d.get("avg_severity", 0),
                    "r": max(d.get("negative_pct", 0) / 5, 3),
                    "label": item["label"],
                })
        bubble_datasets.append({
            "label": platform_labels[p],
            "data": bubbles,
            "backgroundColor": platform_colors[p]["bg"],
            "borderColor": platform_colors[p]["border"],
            "borderWidth": 1,
        })

    sent_labels = _json.dumps([item["label"] for item in top10])
    sent_datasets = []
    for sent, color in [("negative", "#c62828"), ("neutral", "#9e9e9e"), ("positive", "#2e7d32"), ("mixed", "#f57c00")]:
        values = []
        for item in top10:
            total = 0
            for p in platforms:
                d = item["platforms"].get(p, {})
                total += d.get("sentiments", {}).get(sent, 0)
            values.append(total)
        sent_datasets.append({"label": sent.title(), "data": values, "backgroundColor": color})

    html = ["""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Feature Gap Matrix — AEC Product Opportunity Analysis</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       max-width: 1400px; margin: 0 auto; padding: 24px; background: #f5f7fa; color: #1a1a2e; }
h1 { font-size: 26px; margin-bottom: 6px; color: #003087; }
h2 { font-size: 20px; margin: 32px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #003087; color: #003087; }
h3 { font-size: 16px; margin: 16px 0 8px; color: #003087; }
.subtitle { color: #666; margin-bottom: 24px; font-size: 14px; }
table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 24px; }
th { background: #003087; color: #fff; text-align: left; padding: 10px 12px; font-size: 13px; }
td { padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 13px; }
tr:hover td { background: #f0f4ff; }
.heat-cell { text-align: center; font-weight: 600; font-size: 12px; border-radius: 4px; padding: 6px 8px; }
.opp-card { background: #fff; border-radius: 8px; padding: 20px; margin-bottom: 16px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid #003087; }
.opp-card h3 { margin-top: 0; }
.opp-rank { font-size: 28px; font-weight: 700; color: #003087; float: left; margin-right: 16px; line-height: 1; }
.opp-meta { font-size: 12px; color: #666; margin-bottom: 8px; }
.platform-pills { display: flex; gap: 8px; margin-top: 8px; flex-wrap: wrap; }
.pill { padding: 4px 10px; border-radius: 12px; font-size: 11px; font-weight: 600; }
.pill-bb { background: #e3f2fd; color: #1565c0; }
.pill-ad { background: #fce4ec; color: #c62828; }
.pill-pc { background: #e8f5e9; color: #2e7d32; }
.need-item { font-size: 12px; color: #444; margin: 4px 0; padding-left: 12px; border-left: 2px solid #ddd; }
.stats-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-bottom: 24px; }
.stat-card { background: #fff; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); text-align: center; }
.stat-num { font-size: 28px; font-weight: 700; color: #003087; }
.stat-label { font-size: 12px; color: #666; margin-top: 4px; }
details summary { cursor: pointer; font-size: 12px; color: #0066cc; margin-top: 6px; }
.chart-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; margin-bottom: 32px; }
.chart-card { background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
.chart-card h3 { margin-top: 0; margin-bottom: 12px; }
.chart-card canvas { max-height: 400px; }
.chart-wide { grid-column: 1 / -1; }
</style>
</head>
<body>
<h1>Feature Gap Matrix</h1>
<p class="subtitle">AEC Product Opportunity Analysis — Bluebeam, Autodesk, Procore Community Forums</p>
"""]

    # Stats row
    total_ext = sum(item["total_count"] for item in ranked)
    html.append('<div class="stats-row">')
    for num, label in [
        (f"{total_ext:,}", "Threads Analyzed"),
        (f"{len(ranked)}", "Feature Categories"),
        ("3", "Platforms Compared"),
        (f"{ranked[0]['label']}" if ranked else "—", "Top Opportunity"),
    ]:
        html.append(f'<div class="stat-card"><div class="stat-num">{num}</div><div class="stat-label">{label}</div></div>')
    html.append('</div>')

    # --- CHARTS ---
    html.append('<h2>Visual Analysis</h2>')
    html.append('<div class="chart-grid">')
    html.append('<div class="chart-card"><h3>Platform Pain Profile (Top 10 Categories)</h3><canvas id="radarChart"></canvas></div>')
    html.append('<div class="chart-card"><h3>Top 10 Opportunities — Gap Score by Platform</h3><canvas id="barChart"></canvas></div>')
    html.append('<div class="chart-card chart-wide"><h3>Severity vs Volume (bubble size = % negative sentiment)</h3><canvas id="bubbleChart"></canvas></div>')
    html.append('<div class="chart-card chart-wide"><h3>Sentiment Distribution — Top 10 Categories</h3><canvas id="sentChart"></canvas></div>')
    html.append('</div>')

    # Chart.js scripts
    html.append(f"""<script>
new Chart(document.getElementById('radarChart'), {{
    type: 'radar',
    data: {{ labels: {top10_labels}, datasets: {_json.dumps(radar_datasets)} }},
    options: {{
        responsive: true,
        scales: {{ r: {{ beginAtZero: true, ticks: {{ font: {{ size: 10 }} }}, pointLabels: {{ font: {{ size: 11 }} }} }} }},
        plugins: {{ legend: {{ position: 'bottom' }}, tooltip: {{ callbacks: {{ label: function(ctx) {{ return ctx.dataset.label + ': Gap ' + ctx.raw; }} }} }} }}
    }}
}});
new Chart(document.getElementById('barChart'), {{
    type: 'bar',
    data: {{ labels: {top10_labels}, datasets: {_json.dumps(bar_datasets)} }},
    options: {{
        indexAxis: 'y', responsive: true,
        scales: {{ x: {{ stacked: true, title: {{ display: true, text: 'Gap Score' }} }}, y: {{ stacked: true }} }},
        plugins: {{ legend: {{ position: 'bottom' }} }}
    }}
}});
new Chart(document.getElementById('bubbleChart'), {{
    type: 'bubble',
    data: {{ datasets: {_json.dumps(bubble_datasets)} }},
    options: {{
        responsive: true,
        scales: {{ x: {{ title: {{ display: true, text: 'Post Count' }}, beginAtZero: true }}, y: {{ title: {{ display: true, text: 'Avg Severity (1-5)' }}, min: 0, max: 5 }} }},
        plugins: {{ legend: {{ position: 'bottom' }}, tooltip: {{ callbacks: {{ label: function(ctx) {{ let d = ctx.raw; return ctx.dataset.label + ': ' + (d.label||'') + ' (' + d.x + ' posts, sev ' + d.y.toFixed(1) + ')'; }} }} }} }}
    }}
}});
new Chart(document.getElementById('sentChart'), {{
    type: 'bar',
    data: {{ labels: {sent_labels}, datasets: {_json.dumps(sent_datasets)} }},
    options: {{
        responsive: true,
        scales: {{ x: {{ stacked: true }}, y: {{ stacked: true, title: {{ display: true, text: 'Post Count' }} }} }},
        plugins: {{ legend: {{ position: 'bottom' }} }}
    }}
}});
</script>""")

    # --- HEATMAP TABLE ---
    html.append('<h2>Feature Gap Heatmap</h2>')
    html.append('<p style="font-size:13px;color:#666;margin-bottom:12px">Darker cells = higher demand x severity.</p>')
    html.append('<table><tr><th>Feature</th><th>Gap Score</th>')
    for p in platforms:
        html.append(f'<th>{platform_labels[p]}<br><span style="font-weight:normal;font-size:11px">count / sev / neg%</span></th>')
    html.append('<th>Total</th></tr>')

    for item in ranked:
        gap = item["avg_gap_score"]
        html.append(f'<tr><td><strong>{escape(item["label"])}</strong></td>')
        html.append(f'<td><span class="heat-cell" style="{heat_color(gap, max_gap)}">{gap}</span></td>')
        for p in platforms:
            d = item["platforms"].get(p, {})
            count = d.get("count", 0)
            sev = d.get("avg_severity", 0)
            neg = d.get("negative_pct", 0)
            style = heat_color(count, max_count)
            neg_style = neg_color(neg)
            html.append(f'<td><span class="heat-cell" style="{style}">{count}</span> / {sev:.1f} / <span style="{neg_style}">{neg:.0f}%</span></td>')
        html.append(f'<td>{item["total_count"]}</td></tr>')
    html.append('</table>')

    # --- TOP 10 OPPORTUNITIES ---
    html.append('<h2>Top 10 Product Opportunities</h2>')
    for i, item in enumerate(ranked[:10]):
        html.append(f'<div class="opp-card">')
        html.append(f'<div class="opp-rank">#{i+1}</div>')
        html.append(f'<h3>{escape(item["label"])}</h3>')
        html.append(f'<div class="opp-meta">Gap Score: {item["avg_gap_score"]} | Total Mentions: {item["total_count"]}</div>')
        html.append('<div class="platform-pills">')
        for p in platforms:
            d = item["platforms"].get(p, {})
            if d:
                pill_class = {"bluebeam": "pill-bb", "autodesk": "pill-ad", "procore": "pill-pc"}[p]
                html.append(f'<span class="pill {pill_class}">{platform_labels[p]}: {d["count"]} posts, sev {d["avg_severity"]:.1f}, {d["negative_pct"]:.0f}% negative</span>')
        html.append('</div>')

        all_needs = []
        for p in platforms:
            d = item["platforms"].get(p, {})
            for n in d.get("top_needs", [])[:2]:
                all_needs.append((n.get("severity", 0), n.get("need", ""), n.get("title", ""), p))
        all_needs.sort(key=lambda x: x[0], reverse=True)

        if all_needs:
            html.append('<details><summary>Top user needs</summary>')
            for sev, need, title, p in all_needs[:6]:
                html.append(f'<div class="need-item"><strong>[{platform_labels[p]}]</strong> sev={sev}: {escape(need)}</div>')
            html.append('</details>')
        html.append('</div>')

    # --- PER-PLATFORM BREAKDOWN ---
    for p in platforms:
        html.append(f'<h2>{platform_labels[p]} — Category Breakdown</h2>')
        platform_cats = []
        for item in ranked:
            d = item["platforms"].get(p, {})
            if d and d["count"] > 0:
                platform_cats.append((item["label"], d))
        platform_cats.sort(key=lambda x: x[1]["gap_score"], reverse=True)

        html.append('<table><tr><th>Category</th><th>Posts</th><th>Avg Severity</th><th>Negative %</th><th>Staff Response</th><th>Gap Score</th></tr>')
        for label, d in platform_cats:
            neg_style = neg_color(d["negative_pct"])
            html.append(f'<tr><td>{escape(label)}</td><td>{d["count"]}</td><td>{d["avg_severity"]:.1f}</td>'
                        f'<td><span style="{neg_style}">{d["negative_pct"]:.0f}%</span></td>'
                        f'<td>{d["staff_response_rate"]:.0f}%</td><td>{d["gap_score"]}</td></tr>')
        html.append('</table>')

    html.append('</body></html>')
    return "\n".join(html)


def run_visualization():
    """Generate feature gap matrix HTML report and CSV export."""
    cross_file = SYNTHESIS_DIR / "cross_platform.json"
    if not cross_file.exists():
        print("  No synthesis data found. Run --synthesize first.")
        return

    with open(cross_file, "r", encoding="utf-8") as f:
        cross = json.load(f)

    html = build_feature_matrix_html(cross)
    output = DATA_DIR / "feature_matrix.html"
    with open(output, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Wrote {output}")

    csv_file = DATA_DIR / "feature_matrix.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["category", "label", "platform", "count", "avg_severity", "gap_score",
                     "negative_pct", "staff_response_rate"])
        for cat, item in sorted(cross.items(), key=lambda x: x[1]["avg_gap_score"], reverse=True):
            for p in ["bluebeam", "autodesk", "procore"]:
                d = item["platforms"].get(p, {})
                if d:
                    w.writerow([cat, item["label"], p, d["count"], d["avg_severity"],
                                d["gap_score"], d["negative_pct"], d["staff_response_rate"]])
    print(f"  Wrote {csv_file}")
