"""Thread serialization and batch creation for LLM processing."""

import json
import random
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path

from .config import (
    AUTODESK_SAMPLE_SIZE,
    BATCHES_DIR,
    DATA_DIR,
    MAX_BODY_CHARS,
    MAX_COMMENT_CHARS,
    MAX_COMMENTS_PER_THREAD,
    TEST_BATCHES,
    THREADS_PER_BATCH,
)


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
    names = [r.get("name", "") for r in roles if r.get("name")]
    if any(r in ("Staff", "Moderator", "Admin") for r in names):
        return "Staff"
    return ""


# --- Thread Serialization ---

def serialize_bluebeam_thread(d: dict, index: int) -> dict:
    """Serialize a Bluebeam discussion + comments into LLM-readable format."""
    user = d.get("insertUser", {}) or {}
    cat = (d.get("category", {}) or {}).get("name", "")
    views = d.get("countViews", 0)
    comment_count = d.get("countComments", 0)
    date = d.get("dateInserted", "")[:10]
    author = user.get("name", "Unknown")
    role = get_roles(user)
    author_label = f"{author} ({role})" if role else author

    body = strip_html(d.get("body", ""))[:MAX_BODY_CHARS]

    lines = [
        f"THREAD {index + 1} [Bluebeam | {cat} | {comment_count} comments | {views} views]",
        f"Title: {d.get('name', '')}",
        f"Post by {author_label} ({date}):",
        f"  {body}",
    ]

    for c in (d.get("comments", []) or [])[:MAX_COMMENTS_PER_THREAD]:
        cu = c.get("insertUser", {}) or {}
        c_author = cu.get("name", "Unknown")
        c_role = get_roles(cu)
        c_label = f"{c_author} ({c_role})" if c_role else c_author
        c_body = strip_html(c.get("body", ""))[:MAX_COMMENT_CHARS]
        lines.append(f"  Reply by {c_label}: {c_body}")

    lines.append("---")
    text = "\n".join(lines)

    return {
        "thread_id": str(d.get("discussionID", "")),
        "title": d.get("name", ""),
        "serialized_text": text,
        "metadata": {
            "views": views,
            "comments": comment_count,
            "category": cat,
            "type": d.get("type", ""),
            "score": d.get("score") or 0,
        },
    }


def serialize_procore_thread(q: dict, index: int) -> dict:
    """Serialize a Procore question + comments."""
    body = (q.get("body", "") or "")[:MAX_BODY_CHARS]
    comments = q.get("comments", []) or []
    author = q.get("author", "Unknown") or "Unknown"
    date = q.get("date", "")

    lines = [
        f"THREAD {index + 1} [Procore | {q.get('topic_name', '')} | {len(comments)} comments]",
        f"Title: {q.get('title', '')}",
        f"Post by {author} ({date}):",
        f"  {body}",
    ]

    for c in comments[:MAX_COMMENTS_PER_THREAD]:
        c_author = c.get("author", "Unknown") or "Unknown"
        c_body = (c.get("body", "") or c.get("raw_text", ""))[:MAX_COMMENT_CHARS]
        lines.append(f"  Reply by {c_author}: {c_body}")

    lines.append("---")
    return {
        "thread_id": str(q.get("id", "")),
        "title": q.get("title", ""),
        "serialized_text": "\n".join(lines),
        "metadata": {
            "comments": len(comments),
            "topic": q.get("topic_name", ""),
        },
    }


def serialize_autodesk_thread(thread: dict, replies: list[dict], index: int) -> dict:
    """Serialize an Autodesk thread + replies."""
    author = (thread.get("author", {}) or {}).get("login", "Unknown")
    board = (thread.get("board", {}) or {}).get("id", "unknown")
    views = (thread.get("metrics", {}) or {}).get("views", 0)
    date = (thread.get("post_time", "") or "")[:10]
    body = strip_html(thread.get("body", ""))[:MAX_BODY_CHARS]

    lines = [
        f"THREAD {index + 1} [Autodesk | {board} | {len(replies)} replies | {views} views]",
        f"Title: {thread.get('subject', '')}",
        f"Post by {author} ({date}):",
        f"  {body}",
    ]

    for r in replies[:MAX_COMMENTS_PER_THREAD]:
        r_author = (r.get("author", {}) or {}).get("login", "Unknown")
        r_body = strip_html(r.get("body", ""))[:MAX_COMMENT_CHARS]
        lines.append(f"  Reply by {r_author}: {r_body}")

    lines.append("---")
    return {
        "thread_id": str(thread.get("id", "")),
        "title": thread.get("subject", ""),
        "serialized_text": "\n".join(lines),
        "metadata": {
            "views": views,
            "replies": len(replies),
            "board": board,
        },
    }


# --- Batch Creation ---

def preprocess_bluebeam(test_mode: bool = False) -> list[list[dict]]:
    """Load and batch Bluebeam threads."""
    print("Preprocessing Bluebeam...")
    with open(DATA_DIR / "combined.json", "r", encoding="utf-8") as f:
        discussions = json.load(f)

    if test_mode:
        by_comments = sorted(discussions, key=lambda d: d.get("countComments", 0), reverse=True)
        ideas = [d for d in discussions if d.get("type") == "idea" and d.get("score", 0)]
        ideas.sort(key=lambda d: d.get("score", 0), reverse=True)

        test_set = by_comments[:10] + ideas[:10]
        for d in discussions:
            body = strip_html(d.get("body", "")).lower()
            if any(w in body for w in ["bug", "crash", "broken", "not working"]):
                test_set.append(d)
                if len(test_set) >= 30:
                    break
        discussions = test_set[:30]

    threads = [serialize_bluebeam_thread(d, i) for i, d in enumerate(discussions)]
    batches = [threads[i:i + THREADS_PER_BATCH] for i in range(0, len(threads), THREADS_PER_BATCH)]

    if test_mode:
        batches = batches[:TEST_BATCHES]

    out_dir = BATCHES_DIR / "bluebeam"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, batch in enumerate(batches):
        with open(out_dir / f"batch_{i}.json", "w", encoding="utf-8") as f:
            json.dump({"platform": "bluebeam", "batch_id": i, "threads": batch}, f, ensure_ascii=False)

    print(f"  {len(discussions)} threads -> {len(batches)} batches")
    return batches


def preprocess_procore(test_mode: bool = False) -> list[list[dict]]:
    """Load and batch Procore threads."""
    print("Preprocessing Procore...")
    combined = DATA_DIR / "procore" / "combined.json"
    if not combined.exists():
        print("  Procore combined.json not found — skipping (scrape may still be running)")
        return []

    with open(combined, "r", encoding="utf-8") as f:
        questions = json.load(f)

    if test_mode:
        questions = questions[:30]

    threads = [serialize_procore_thread(q, i) for i, q in enumerate(questions)]
    batches = [threads[i:i + THREADS_PER_BATCH] for i in range(0, len(threads), THREADS_PER_BATCH)]

    if test_mode:
        batches = batches[:TEST_BATCHES]

    out_dir = BATCHES_DIR / "procore"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, batch in enumerate(batches):
        with open(out_dir / f"batch_{i}.json", "w", encoding="utf-8") as f:
            json.dump({"platform": "procore", "batch_id": i, "threads": batch}, f, ensure_ascii=False)

    print(f"  {len(questions)} threads -> {len(batches)} batches")
    return batches


def preprocess_autodesk(test_mode: bool = False) -> list[list[dict]]:
    """Load, sample, and batch Autodesk threads with replies."""
    print("Preprocessing Autodesk...")
    threads_dir = DATA_DIR / "autodesk" / "threads"
    replies_dir = DATA_DIR / "autodesk" / "replies"

    if not threads_dir.exists():
        print("  Autodesk threads not found — skipping")
        return []

    print("  Loading threads...")
    all_threads = []
    for f in sorted(threads_dir.glob("batch_*.jsonl")):
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    all_threads.append(json.loads(line))

    all_threads.sort(key=lambda t: (t.get("metrics", {}) or {}).get("views", 0), reverse=True)
    sample_size = 30 if test_mode else AUTODESK_SAMPLE_SIZE
    sampled = all_threads[:sample_size]

    sampled_ids = {str(t.get("id", "")) for t in sampled}
    print(f"  Loading replies for {len(sampled_ids)} threads...")
    reply_map: dict[str, list[dict]] = defaultdict(list)

    if replies_dir.exists():
        for f in sorted(replies_dir.glob("batch_*.jsonl")):
            with open(f, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        r = json.loads(line)
                        pid = str((r.get("parent", {}) or {}).get("id", ""))
                        if pid in sampled_ids:
                            reply_map[pid].append(r)

    threads = []
    for i, t in enumerate(sampled):
        tid = str(t.get("id", ""))
        replies = reply_map.get(tid, [])
        threads.append(serialize_autodesk_thread(t, replies, i))

    batches = [threads[i:i + THREADS_PER_BATCH] for i in range(0, len(threads), THREADS_PER_BATCH)]

    if test_mode:
        batches = batches[:TEST_BATCHES]

    out_dir = BATCHES_DIR / "autodesk"
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, batch in enumerate(batches):
        with open(out_dir / f"batch_{i}.json", "w", encoding="utf-8") as f:
            json.dump({"platform": "autodesk", "batch_id": i, "threads": batch}, f, ensure_ascii=False)

    print(f"  {len(sampled)} threads (sampled) -> {len(batches)} batches")
    return batches
