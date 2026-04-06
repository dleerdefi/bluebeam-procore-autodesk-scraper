"""Bluebeam Community Data Analyzer

Reads combined.json and produces:
- data/discussions.csv  (flat, readable)
- data/comments.csv     (flat, readable)
- data/report.html      (self-contained insights report)
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime
from html import escape
from html.parser import HTMLParser
from pathlib import Path

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


DATA_DIR = Path("data")
COMBINED_FILE = DATA_DIR / "combined.json"
MAX_BODY_LEN = 2000


# --- HTML stripping ---

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


def get_roles(user: dict) -> str:
    roles = user.get("roles", [])
    if not roles:
        return ""
    return ", ".join(r.get("name", "") for r in roles if r.get("name"))


def parse_date(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso)
    except Exception:
        return None


def month_key(iso: str | None) -> str:
    dt = parse_date(iso)
    return dt.strftime("%Y-%m") if dt else "Unknown"


# --- CSV Export ---

def export_discussions_csv(discussions: list[dict]):
    path = DATA_DIR / "discussions.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "discussion_id", "title", "author", "author_roles", "category",
            "type", "status", "date_posted", "date_last_comment",
            "comment_count", "view_count", "score", "body_text", "url",
        ])
        for d in discussions:
            user = d.get("insertUser", {}) or {}
            cat = d.get("category", {}) or {}
            status = d.get("status", {}) or {}
            body = strip_html(d.get("body", ""))
            if len(body) > MAX_BODY_LEN:
                body = body[:MAX_BODY_LEN] + "..."
            w.writerow([
                d.get("discussionID"),
                d.get("name", ""),
                user.get("name", ""),
                get_roles(user),
                cat.get("name", ""),
                d.get("type", ""),
                status.get("name", ""),
                d.get("dateInserted", ""),
                d.get("dateLastComment", ""),
                d.get("countComments", 0),
                d.get("countViews", 0),
                d.get("score", 0),
                body,
                d.get("url", ""),
            ])
    print(f"  Wrote {path} ({len(discussions)} rows)")


def export_comments_csv(discussions: list[dict]):
    path = DATA_DIR / "comments.csv"
    total = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "comment_id", "discussion_id", "discussion_title", "author",
            "author_roles", "date_posted", "score", "body_text", "url",
        ])
        for d in discussions:
            for c in d.get("comments", []):
                user = c.get("insertUser", {}) or {}
                body = strip_html(c.get("body", ""))
                if len(body) > MAX_BODY_LEN:
                    body = body[:MAX_BODY_LEN] + "..."
                w.writerow([
                    c.get("commentID"),
                    d.get("discussionID"),
                    d.get("name", ""),
                    user.get("name", ""),
                    get_roles(user),
                    c.get("dateInserted", ""),
                    c.get("score", 0),
                    body,
                    c.get("url", ""),
                ])
                total += 1
    print(f"  Wrote {path} ({total} rows)")


# --- Insight Extraction ---

def compute_insights(discussions: list[dict]) -> dict:
    total_comments = sum(len(d.get("comments", [])) for d in discussions)

    # Unique users
    users: dict[int, dict] = {}
    user_post_count: Counter = Counter()
    user_comment_count: Counter = Counter()

    for d in discussions:
        u = d.get("insertUser", {}) or {}
        uid = u.get("userID")
        if uid:
            users[uid] = u
            user_post_count[uid] += 1
        for c in d.get("comments", []):
            cu = c.get("insertUser", {}) or {}
            cuid = cu.get("userID")
            if cuid:
                users[cuid] = cu
                user_comment_count[cuid] += 1

    # Date range
    dates = [parse_date(d.get("dateInserted")) for d in discussions]
    dates = [dt for dt in dates if dt]
    date_min = min(dates) if dates else None
    date_max = max(dates) if dates else None

    # Top discussed
    by_comments = sorted(discussions, key=lambda d: d.get("countComments", 0), reverse=True)

    # Top viewed
    by_views = sorted(discussions, key=lambda d: d.get("countViews", 0), reverse=True)

    # Category breakdown
    cat_stats: dict[str, dict] = defaultdict(lambda: {"discussions": 0, "comments": 0, "views": 0})
    for d in discussions:
        cat = (d.get("category", {}) or {}).get("name", "Unknown")
        cat_stats[cat]["discussions"] += 1
        cat_stats[cat]["comments"] += d.get("countComments", 0)
        cat_stats[cat]["views"] += d.get("countViews", 0)

    # Type breakdown
    type_counts = Counter(d.get("type", "unknown") for d in discussions)

    # Idea status breakdown
    idea_status = Counter()
    for d in discussions:
        if d.get("type") == "idea":
            status = (d.get("status", {}) or {}).get("name", "No Status")
            idea_status[status] += 1

    # Monthly activity
    monthly_discussions: Counter = Counter()
    monthly_comments: Counter = Counter()
    for d in discussions:
        mk = month_key(d.get("dateInserted"))
        monthly_discussions[mk] += 1
        for c in d.get("comments", []):
            cmk = month_key(c.get("dateInserted"))
            monthly_comments[cmk] += 1

    # Top feature requests (ideas by score)
    ideas = [d for d in discussions if d.get("type") == "idea"]
    top_ideas = sorted(ideas, key=lambda d: d.get("score") or 0, reverse=True)

    # Unanswered questions
    questions = [d for d in discussions if d.get("type") == "question"]
    unanswered = [d for d in questions if d.get("countComments", 0) == 0]

    # Top active users
    all_uids = set(user_post_count.keys()) | set(user_comment_count.keys())
    user_activity = []
    for uid in all_uids:
        total = user_post_count[uid] + user_comment_count[uid]
        user_activity.append({
            "user": users.get(uid, {}),
            "posts": user_post_count[uid],
            "comments": user_comment_count[uid],
            "total": total,
        })
    user_activity.sort(key=lambda x: x["total"], reverse=True)

    return {
        "total_discussions": len(discussions),
        "total_comments": total_comments,
        "unique_users": len(users),
        "date_min": date_min,
        "date_max": date_max,
        "by_comments": by_comments[:20],
        "by_views": by_views[:20],
        "cat_stats": dict(cat_stats),
        "type_counts": type_counts,
        "idea_status": idea_status,
        "monthly_discussions": monthly_discussions,
        "monthly_comments": monthly_comments,
        "top_ideas": top_ideas[:20],
        "unanswered": unanswered[:20],
        "total_unanswered": len(unanswered),
        "user_activity": user_activity[:20],
    }


# --- Product Insights ---

THEMES = [
    # (category, theme_name, keywords)
    ("pain", "Bugs & Crashes", [
        "bug", "crash", "freeze", "not working", "broken", "glitch", "error message",
        "unresponsive", "stops responding", "fatal", "corrupted", "won't open",
        "doesn't work", "does not work", "stopped working",
    ]),
    ("pain", "Performance Issues", [
        "slow", "lag", "laggy", "performance", "takes forever", "hang", "hanging",
        "loading", "sluggish", "crawl", "unusable", "memory", "cpu",
    ]),
    ("pain", "Missing Features & Gaps", [
        "wish we could", "wish there was", "no way to", "can't even",
        "cannot even", "why isn't", "why can't", "should be able",
        "need the ability", "missing feature", "no option", "not possible",
        "would be nice if", "desperately need",
    ]),
    ("pain", "UX & Workflow Friction", [
        "confusing", "unintuitive", "clunky", "tedious", "workaround",
        "cumbersome", "frustrating", "annoying", "extra steps", "too many clicks",
        "time consuming", "inefficient", "counterintuitive", "hard to find",
    ]),
    ("pain", "iPad & Mobile Gaps", [
        "ipad", "mobile", "tablet", "ios", "touch", "retire", "retirement",
        "android", "phone", "portable",
    ]),
    ("pain", "Collaboration & Sessions", [
        "session crash", "session issue", "sync issue", "sync problem",
        "lost markups", "conflict", "multi-user", "permission",
        "simultaneous", "locked out", "can't access", "studio session",
    ]),
    ("love", "Core Product Praise", [
        "love bluebeam", "love revu", "love this", "love the",
        "great software", "great tool", "great product", "amazing tool",
        "awesome", "fantastic", "excellent", "best software", "best tool",
        "game changer", "indispensable", "couldn't live without",
        "highly recommend", "love using",
    ]),
    ("love", "Markup & Annotation Tools", [
        "love the markup", "markup tools are", "great markup",
        "annotation", "stamp", "cloud markup", "callout",
        "highlight", "text box", "polyline",
    ]),
    ("love", "Measurement & Takeoff", [
        "measure", "takeoff", "take-off", "quantity", "count",
        "area calculation", "perimeter", "estimation",
    ]),
    ("love", "Overlay & Comparison", [
        "overlay", "compare", "comparison", "revision",
        "change detection", "diff", "side by side",
    ]),
    ("love", "Batch & Automation", [
        "batch", "action set", "batch link", "auto", "bulk",
        "multiple files", "batch process",
    ]),
    ("want", "AI & Smart Features", [
        r"\bai\b", "artificial intelligence", "machine learning",
        "auto-detect", "autodetect", "smart", "chatgpt", "claude",
        "copilot", "intelligent", "ocr", "recognition",
    ]),
    ("want", "Integrations", [
        "integrat", "excel", "revit", "procore", "autocad", "bluebeam cloud",
        r"\bapi\b", "plugin", "add-in", "sharepoint", "onedrive",
        "plangrid", "autodesk", "bentley",
    ]),
    ("want", "Cloud & Web Access", [
        "cloud", "web version", "web app", "browser", "saas",
        "online", "bluebeam max", "subscription", "anywhere",
        "remote access", "chromebook",
    ]),
    ("want", "Better PDF Editing", [
        "edit pdf", "edit text", "text editing", "font", "redact",
        "redaction", "form", "fillable", "digital signature",
        "e-sign", "esign", "flatten",
    ]),
    ("want", "Improved Organization", [
        "folder", "organize", "sort", "filter", "search",
        "tag", "label", "category", "bookmark", "rename",
        "file management", "project management",
    ]),
]


def compute_product_insights(discussions: list[dict]) -> list[dict]:
    """Scan all discussions + comments for thematic patterns."""
    # Pre-compile regex patterns for each theme
    compiled_themes = []
    for category, name, keywords in THEMES:
        patterns = []
        for kw in keywords:
            if kw.startswith(r"\b"):
                patterns.append(re.compile(kw, re.IGNORECASE))
            else:
                patterns.append(re.compile(r"\b" + re.escape(kw), re.IGNORECASE))
        compiled_themes.append((category, name, patterns))

    # Build full text for each discussion (title + body + all comments)
    discussion_texts: list[tuple[dict, str]] = []
    for d in discussions:
        parts = [d.get("name", ""), strip_html(d.get("body", ""))]
        for c in d.get("comments", []):
            parts.append(strip_html(c.get("body", "")))
        full_text = " ".join(parts)
        discussion_texts.append((d, full_text))

    # Match each discussion against each theme
    results = []
    for category, name, patterns in compiled_themes:
        matched = []
        for d, text in discussion_texts:
            for pat in patterns:
                if pat.search(text):
                    matched.append(d)
                    break

        if not matched:
            continue

        total_engagement = sum(d.get("countComments", 0) for d in matched)
        total_views = sum(d.get("countViews", 0) for d in matched)

        # Top posts by engagement
        top_posts = sorted(matched, key=lambda x: x.get("countComments", 0), reverse=True)[:5]

        # Sample quotes — pick discussions with non-empty bodies, take excerpts
        sample_quotes = []
        for d in matched:
            excerpt = strip_html(d.get("body", ""))
            if len(excerpt) > 30:
                sample_quotes.append({
                    "title": d.get("name", ""),
                    "text": excerpt[:200] + ("..." if len(excerpt) > 200 else ""),
                })
            if len(sample_quotes) >= 3:
                break

        results.append({
            "category": category,
            "name": name,
            "count": len(matched),
            "engagement": total_engagement,
            "views": total_views,
            "top_posts": top_posts,
            "sample_quotes": sample_quotes,
        })

    results.sort(key=lambda x: x["count"], reverse=True)
    return results


# --- HTML Report ---

def build_html_report(insights: dict) -> str:
    parts = []
    parts.append("""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Bluebeam Community Insights</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         max-width: 1100px; margin: 0 auto; padding: 24px; background: #f5f7fa; color: #1a1a2e; }
  h1 { font-size: 28px; margin-bottom: 8px; color: #003087; }
  h2 { font-size: 20px; margin: 32px 0 12px; padding-bottom: 6px; border-bottom: 2px solid #003087; color: #003087; }
  .subtitle { color: #666; margin-bottom: 24px; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 16px; margin-bottom: 24px; }
  .stat-card { background: #fff; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  .stat-card .num { font-size: 32px; font-weight: 700; color: #003087; }
  .stat-card .label { font-size: 13px; color: #666; margin-top: 4px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden;
          box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 16px; }
  th { background: #003087; color: #fff; text-align: left; padding: 10px 12px; font-size: 13px; }
  td { padding: 8px 12px; border-bottom: 1px solid #eee; font-size: 13px; }
  tr:hover td { background: #f0f4ff; }
  a { color: #0066cc; text-decoration: none; }
  a:hover { text-decoration: underline; }
  .bar-container { display: flex; align-items: center; gap: 8px; }
  .bar { height: 18px; background: #003087; border-radius: 3px; min-width: 2px; }
  .bar-label { font-size: 12px; white-space: nowrap; }
  .section { margin-bottom: 32px; }
  .tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
  .tag-idea { background: #e8f0fe; color: #1a73e8; }
  .tag-question { background: #fef3e0; color: #e65100; }
  .tag-discussion { background: #e8f5e9; color: #2e7d32; }
  .exec-summary { background: #fff; border-radius: 8px; padding: 24px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 24px; }
  .exec-summary h3 { font-size: 16px; margin: 16px 0 8px; }
  .exec-summary h3:first-child { margin-top: 0; }
  .exec-summary ul { margin-left: 20px; margin-bottom: 8px; }
  .exec-summary li { margin-bottom: 4px; font-size: 14px; line-height: 1.5; }
  .pain-color { color: #c62828; }
  .love-color { color: #2e7d32; }
  .want-color { color: #1565c0; }
  .insight-card { background: #fff; border-radius: 8px; padding: 16px 20px; margin-bottom: 12px;
                  box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 4px solid #ccc; }
  .insight-card.pain { border-left-color: #c62828; }
  .insight-card.love { border-left-color: #2e7d32; }
  .insight-card.want { border-left-color: #1565c0; }
  .insight-header { display: flex; align-items: center; gap: 12px; cursor: pointer; }
  .insight-header h3 { font-size: 15px; margin: 0; flex: 1; }
  .badge { display: inline-block; padding: 2px 10px; border-radius: 12px; font-size: 12px; font-weight: 600; color: #fff; }
  .badge.pain { background: #c62828; }
  .badge.love { background: #2e7d32; }
  .badge.want { background: #1565c0; }
  .insight-meta { font-size: 12px; color: #666; }
  details summary { list-style: none; }
  details summary::-webkit-details-marker { display: none; }
  details[open] .insight-header::after { content: ""; }
  .quote-block { background: #f8f9fa; border-left: 3px solid #ddd; padding: 8px 12px; margin: 8px 0;
                 font-size: 13px; color: #444; line-height: 1.5; }
  .quote-title { font-weight: 600; font-size: 12px; color: #666; margin-bottom: 2px; }
</style>
</head>
<body>
<h1>Bluebeam Community Insights</h1>
""")

    dm = insights["date_min"]
    dx = insights["date_max"]
    date_range = f"{dm.strftime('%b %d, %Y') if dm else '?'} &mdash; {dx.strftime('%b %d, %Y') if dx else '?'}"
    parts.append(f'<p class="subtitle">Data from {date_range} &middot; Generated {datetime.now().strftime("%b %d, %Y")}</p>')

    # 1. Overview stats
    parts.append('<div class="stats-grid">')
    for num, label in [
        (f'{insights["total_discussions"]:,}', "Discussions"),
        (f'{insights["total_comments"]:,}', "Comments"),
        (f'{insights["unique_users"]:,}', "Unique Users"),
        (f'{insights["total_unanswered"]:,}', "Unanswered Questions"),
    ]:
        parts.append(f'<div class="stat-card"><div class="num">{num}</div><div class="label">{label}</div></div>')
    parts.append('</div>')

    # Executive Summary + Product Insights
    if "product_insights" in insights:
        pi = insights["product_insights"]
        pain_themes = [t for t in pi if t["category"] == "pain"]
        love_themes = [t for t in pi if t["category"] == "love"]
        want_themes = [t for t in pi if t["category"] == "want"]

        parts.append('<h2>Executive Summary</h2>')
        parts.append('<div class="exec-summary">')

        parts.append('<h3 class="pain-color">Where Bluebeam Is Failing</h3><ul>')
        for t in pain_themes[:4]:
            parts.append(f'<li><strong>{escape(t["name"])}</strong> &mdash; {t["count"]} discussions, '
                         f'{t["engagement"]:,} comments, {t["views"]:,} views</li>')
        parts.append('</ul>')

        parts.append('<h3 class="love-color">What Users Love</h3><ul>')
        for t in love_themes[:4]:
            parts.append(f'<li><strong>{escape(t["name"])}</strong> &mdash; {t["count"]} discussions, '
                         f'{t["engagement"]:,} comments</li>')
        parts.append('</ul>')

        parts.append('<h3 class="want-color">What Users Want</h3><ul>')
        for t in want_themes[:4]:
            parts.append(f'<li><strong>{escape(t["name"])}</strong> &mdash; {t["count"]} discussions, '
                         f'{t["engagement"]:,} comments</li>')
        parts.append('</ul>')

        # Biggest opportunities: high want+pain, sorted by combined count
        parts.append('<h3>Biggest Opportunities</h3><ul>')
        all_themes_by_opp = sorted(pain_themes + want_themes,
                                    key=lambda t: t["engagement"], reverse=True)
        for t in all_themes_by_opp[:5]:
            label = "pain" if t["category"] == "pain" else "want"
            parts.append(f'<li><span class="badge {label}">{label}</span> '
                         f'<strong>{escape(t["name"])}</strong> &mdash; '
                         f'{t["count"]} discussions, {t["engagement"]:,} comments engaged</li>')
        parts.append('</ul>')
        parts.append('</div>')

        # Detailed theme cards
        for section_title, themes, cat in [
            ("Pain Points", pain_themes, "pain"),
            ("What Users Love", love_themes, "love"),
            ("What Users Want", want_themes, "want"),
        ]:
            if not themes:
                continue
            parts.append(f'<h2>{section_title}</h2>')
            for t in themes:
                parts.append(f'<div class="insight-card {cat}">')
                parts.append('<details><summary><div class="insight-header">')
                parts.append(f'<h3>{escape(t["name"])}</h3>')
                parts.append(f'<span class="badge {cat}">{t["count"]} posts</span>')
                parts.append(f'<span class="insight-meta">{t["engagement"]:,} comments &middot; {t["views"]:,} views</span>')
                parts.append('</div></summary>')

                # Top posts table
                if t["top_posts"]:
                    parts.append(_table(t["top_posts"], [
                        ("Title", lambda i, d: f'<a href="{escape(d.get("url", ""))}">{escape(d.get("name", ""))}</a>'),
                        ("Date", lambda i, d: escape(d.get("dateInserted", "")[:10])),
                        ("Comments", lambda i, d: str(d.get("countComments", 0))),
                        ("Views", lambda i, d: f'{d.get("countViews", 0):,}'),
                    ]))

                # Sample quotes
                if t["sample_quotes"]:
                    for q in t["sample_quotes"]:
                        parts.append(f'<div class="quote-block">'
                                     f'<div class="quote-title">{escape(q["title"])}</div>'
                                     f'{escape(q["text"])}</div>')

                parts.append('</details></div>')

    # 2. Top discussed
    parts.append('<h2>Top 20 Most-Discussed Posts</h2>')
    parts.append(_table(insights["by_comments"], [
        ("#", lambda i, d: str(i + 1)),
        ("Title", lambda i, d: f'<a href="{escape(d.get("url", ""))}">{escape(d.get("name", ""))}</a>'),
        ("Author", lambda i, d: escape((d.get("insertUser") or {}).get("name", ""))),
        ("Date", lambda i, d: escape(d.get("dateInserted", "")[:10])),
        ("Comments", lambda i, d: str(d.get("countComments", 0))),
        ("Views", lambda i, d: f'{d.get("countViews", 0):,}'),
    ]))

    # 3. Top viewed
    parts.append('<h2>Top 20 Most-Viewed Posts</h2>')
    parts.append(_table(insights["by_views"], [
        ("#", lambda i, d: str(i + 1)),
        ("Title", lambda i, d: f'<a href="{escape(d.get("url", ""))}">{escape(d.get("name", ""))}</a>'),
        ("Author", lambda i, d: escape((d.get("insertUser") or {}).get("name", ""))),
        ("Date", lambda i, d: escape(d.get("dateInserted", "")[:10])),
        ("Views", lambda i, d: f'{d.get("countViews", 0):,}'),
        ("Comments", lambda i, d: str(d.get("countComments", 0))),
    ]))

    # 4. Top active users
    parts.append('<h2>Top 20 Most Active Users</h2>')
    parts.append(_table(insights["user_activity"], [
        ("#", lambda i, d: str(i + 1)),
        ("User", lambda i, d: escape(d["user"].get("name", "Unknown"))),
        ("Roles", lambda i, d: escape(get_roles(d["user"]))),
        ("Posts", lambda i, d: str(d["posts"])),
        ("Comments", lambda i, d: str(d["comments"])),
        ("Total", lambda i, d: f'<strong>{d["total"]}</strong>'),
    ]))

    # 5. Category breakdown
    parts.append('<h2>Category Breakdown</h2>')
    cats_sorted = sorted(insights["cat_stats"].items(), key=lambda x: x[1]["discussions"], reverse=True)
    max_disc = max((v["discussions"] for _, v in cats_sorted), default=1)
    parts.append('<table><tr><th>Category</th><th>Discussions</th><th>Comments</th><th>Avg Views</th><th></th></tr>')
    for cat, stats in cats_sorted:
        avg_views = stats["views"] // max(stats["discussions"], 1)
        bar_w = int(stats["discussions"] / max_disc * 200)
        parts.append(f'<tr><td>{escape(cat)}</td><td>{stats["discussions"]}</td>'
                     f'<td>{stats["comments"]}</td><td>{avg_views:,}</td>'
                     f'<td><div class="bar" style="width:{bar_w}px"></div></td></tr>')
    parts.append('</table>')

    # 6. Type breakdown
    parts.append('<h2>Discussion Types</h2>')
    parts.append('<div class="stats-grid">')
    for dtype, count in insights["type_counts"].most_common():
        parts.append(f'<div class="stat-card"><div class="num">{count:,}</div><div class="label">{escape(dtype.title())}</div></div>')
    parts.append('</div>')

    # 7. Idea status
    if insights["idea_status"]:
        parts.append('<h2>Idea/Feature Request Status</h2>')
        parts.append('<table><tr><th>Status</th><th>Count</th><th></th></tr>')
        max_s = max(insights["idea_status"].values(), default=1)
        for status, count in insights["idea_status"].most_common():
            bar_w = int(count / max_s * 200)
            parts.append(f'<tr><td>{escape(status)}</td><td>{count}</td>'
                         f'<td><div class="bar" style="width:{bar_w}px"></div></td></tr>')
        parts.append('</table>')

    # 8. Monthly activity
    parts.append('<h2>Monthly Activity Trend</h2>')
    all_months = sorted(set(insights["monthly_discussions"].keys()) | set(insights["monthly_comments"].keys()))
    if all_months:
        max_m = max(max(insights["monthly_discussions"].values(), default=1),
                    max(insights["monthly_comments"].values(), default=1))
        parts.append('<table><tr><th>Month</th><th>Discussions</th><th>Comments</th><th>Activity</th></tr>')
        for m in all_months:
            dc = insights["monthly_discussions"].get(m, 0)
            cc = insights["monthly_comments"].get(m, 0)
            bar_w = int((dc + cc) / (max_m * 2) * 300)
            parts.append(f'<tr><td>{escape(m)}</td><td>{dc}</td><td>{cc}</td>'
                         f'<td><div class="bar" style="width:{max(bar_w, 2)}px"></div></td></tr>')
        parts.append('</table>')

    # 9. Top feature requests
    if insights["top_ideas"]:
        parts.append('<h2>Top 20 Feature Requests (by Score)</h2>')
        parts.append(_table(insights["top_ideas"], [
            ("#", lambda i, d: str(i + 1)),
            ("Title", lambda i, d: f'<a href="{escape(d.get("url", ""))}">{escape(d.get("name", ""))}</a>'),
            ("Date", lambda i, d: escape(d.get("dateInserted", "")[:10])),
            ("Score", lambda i, d: str(d.get("score") or 0)),
            ("Status", lambda i, d: escape((d.get("status") or {}).get("name", "—"))),
            ("Comments", lambda i, d: str(d.get("countComments", 0))),
        ]))

    # 10. Unanswered questions
    if insights["unanswered"]:
        parts.append(f'<h2>Unanswered Questions ({insights["total_unanswered"]} total, showing 20)</h2>')
        parts.append(_table(insights["unanswered"], [
            ("#", lambda i, d: str(i + 1)),
            ("Title", lambda i, d: f'<a href="{escape(d.get("url", ""))}">{escape(d.get("name", ""))}</a>'),
            ("Author", lambda i, d: escape((d.get("insertUser") or {}).get("name", ""))),
            ("Date", lambda i, d: escape(d.get("dateInserted", "")[:10])),
            ("Views", lambda i, d: f'{d.get("countViews", 0):,}'),
        ]))

    parts.append('</body></html>')
    return "\n".join(parts)


def _table(items: list, columns: list[tuple]) -> str:
    rows = ['<table><tr>']
    for col_name, _ in columns:
        rows.append(f'<th>{col_name}</th>')
    rows.append('</tr>')
    for i, item in enumerate(items):
        rows.append('<tr>')
        for _, fn in columns:
            rows.append(f'<td>{fn(i, item)}</td>')
        rows.append('</tr>')
    rows.append('</table>')
    return "".join(rows)


# --- Main ---

def main():
    print("Loading data...")
    with open(COMBINED_FILE, "r", encoding="utf-8") as f:
        discussions = json.load(f)
    print(f"  Loaded {len(discussions)} discussions")

    print("\nExporting CSVs...")
    export_discussions_csv(discussions)
    export_comments_csv(discussions)

    print("\nComputing insights...")
    insights = compute_insights(discussions)

    print("Computing product insights...")
    insights["product_insights"] = compute_product_insights(discussions)

    # Print summary to terminal
    print(f"\n{'='*50}")
    print(f"  Discussions:          {insights['total_discussions']:,}")
    print(f"  Comments:             {insights['total_comments']:,}")
    print(f"  Unique Users:         {insights['unique_users']:,}")
    print(f"  Unanswered Questions: {insights['total_unanswered']:,}")
    dm = insights["date_min"]
    dx = insights["date_max"]
    print(f"  Date Range:           {dm.strftime('%Y-%m-%d') if dm else '?'} to {dx.strftime('%Y-%m-%d') if dx else '?'}")
    print(f"{'='*50}")
    print(f"\n  Top 5 Categories:")
    cats_sorted = sorted(insights["cat_stats"].items(), key=lambda x: x[1]["discussions"], reverse=True)
    for cat, stats in cats_sorted[:5]:
        print(f"    {cat}: {stats['discussions']} discussions, {stats['comments']} comments")
    print(f"\n  Top 5 Most-Discussed:")
    for d in insights["by_comments"][:5]:
        print(f"    [{d['countComments']} comments] {d['name']}")
    print()

    # Print product insights summary
    pi = insights.get("product_insights", [])
    if pi:
        pain = [t for t in pi if t["category"] == "pain"]
        love = [t for t in pi if t["category"] == "love"]
        want = [t for t in pi if t["category"] == "want"]
        print(f"\n  Pain Points:")
        for t in pain[:4]:
            print(f"    [{t['count']} posts] {t['name']}")
        print(f"\n  What Users Love:")
        for t in love[:4]:
            print(f"    [{t['count']} posts] {t['name']}")
        print(f"\n  What Users Want:")
        for t in want[:4]:
            print(f"    [{t['count']} posts] {t['name']}")
        print()

    print("Generating HTML report...")
    html = build_html_report(insights)
    report_path = DATA_DIR / "report.html"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Wrote {report_path}")

    print("\nDone! Open data/report.html in your browser to view the full report.")


if __name__ == "__main__":
    main()
