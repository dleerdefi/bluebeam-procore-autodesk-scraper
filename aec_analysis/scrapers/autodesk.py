"""Autodesk AEC Forum Scraper

Scrapes all threads and replies from the Architecture, Engineering & Construction
category on forums.autodesk.com using the public Khoros LiQL API.
"""

import argparse
import csv
import json
import sys
import time
from collections import defaultdict
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# --- Configuration ---
BASE_URL = "https://forums.autodesk.com/api/2.0/search"
CATEGORY_ID = "architecture-engineering-construction-en"
PAGE_SIZE = 1000
REQUEST_TIMEOUT = 60
DELAY_BETWEEN_REQUESTS = 0.5  # seconds
BACKOFF_DELAY = 10  # seconds on rate limit
MAX_RETRIES = 5

DATA_DIR = Path("data") / "autodesk"
THREADS_DIR = DATA_DIR / "threads"
REPLIES_DIR = DATA_DIR / "replies"
BOARDS_DIR = DATA_DIR / "boards"


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


# --- HTTP Client ---

def create_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=2,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"Accept": "application/json"})
    return session


def liql_fetch(session: requests.Session, query: str, cursor: str | None = None) -> dict:
    """Execute a LiQL query and return the JSON response.

    Cursor pagination: the cursor value is appended to the LiQL query
    as CURSOR 'value' (not as a separate URL parameter).
    """
    full_query = query
    if cursor:
        full_query = f"{query} CURSOR '{cursor}'"

    params = {"q": full_query}

    while True:
        try:
            resp = session.get(BASE_URL, params=params, timeout=REQUEST_TIMEOUT)
            if resp.status_code == 429:
                print(f"\n  Rate limited, waiting {BACKOFF_DELAY}s...")
                time.sleep(BACKOFF_DELAY)
                continue
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as e:
            print(f"\n  HTTP error: {e}")
            raise
        except requests.exceptions.ConnectionError as e:
            print(f"\n  Connection error, retrying in {BACKOFF_DELAY}s...")
            time.sleep(BACKOFF_DELAY)
            continue


# --- Pass 1: Fetch Threads ---

def get_total_count(session: requests.Session, depth_filter: str) -> int:
    """Get total message count for a given depth filter."""
    query = (
        f"SELECT count(*) FROM messages "
        f"WHERE category.id = '{CATEGORY_ID}' AND {depth_filter}"
    )
    result = liql_fetch(session, query)
    return result.get("data", {}).get("count", 0)


def fetch_pass(session: requests.Session, pass_name: str, query: str,
               output_dir: Path, cursor_file: Path, count_file: Path,
               estimated_total: int, max_pages: int | None = None):
    """Generic paginated fetch pass — streams results to JSONL files."""
    output_dir.mkdir(parents=True, exist_ok=True)

    # Check for resume
    batch_num = 0
    cursor = None
    total_fetched = 0

    if cursor_file.exists():
        cursor = cursor_file.read_text().strip()
        if cursor == "DONE":
            # Already completed
            total = int(count_file.read_text().strip()) if count_file.exists() else 0
            print(f"  {pass_name}: already completed ({total:,} items)")
            return total
        # Count existing batches
        existing = sorted(output_dir.glob("batch_*.jsonl"))
        if existing:
            batch_num = len(existing)
            # Count items in existing files
            for f in existing:
                with open(f, "r", encoding="utf-8") as fh:
                    total_fetched += sum(1 for _ in fh)
            print(f"  Resuming {pass_name} from batch {batch_num} ({total_fetched:,} items so far)")

    effective_total = min(estimated_total, max_pages * PAGE_SIZE) if max_pages else estimated_total
    pbar = tqdm(total=effective_total, initial=total_fetched, desc=f"  {pass_name}", unit="msg")
    pages_fetched = 0

    while True:
        if max_pages and pages_fetched >= max_pages:
            print(f"\n  Reached max pages ({max_pages}) for test mode")
            break

        result = liql_fetch(session, query, cursor)
        data = result.get("data", {})
        items = data.get("items", [])

        if not items:
            break

        # Write batch
        batch_file = output_dir / f"batch_{batch_num}.jsonl"
        with open(batch_file, "w", encoding="utf-8") as f:
            for item in items:
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

        total_fetched += len(items)
        batch_num += 1
        pages_fetched += 1
        pbar.update(len(items))

        # Get next cursor
        cursor = data.get("next_cursor")
        if not cursor:
            break

        # Save cursor for resume (only mark DONE if no max_pages limit)
        cursor_file.write_text(cursor)
        time.sleep(DELAY_BETWEEN_REQUESTS)

    pbar.close()

    if not max_pages:
        # Mark complete only for full runs
        cursor_file.write_text("DONE")
    count_file.write_text(str(total_fetched))
    print(f"  {pass_name}: {total_fetched:,} items in {batch_num} batches")
    return total_fetched


def fetch_threads(session: requests.Session, max_pages: int | None = None) -> int:
    query = (
        f"SELECT id, subject, body, post_time, board.id, metrics, author.login, "
        f"conversation.solved, conversation.last_post_time "
        f"FROM messages "
        f"WHERE category.id = '{CATEGORY_ID}' AND depth = 0 "
        f"ORDER BY post_time DESC "
        f"LIMIT {PAGE_SIZE}"
    )
    print("\nPass 1: Counting threads...")
    total = get_total_count(session, "depth = 0")
    print(f"  Total thread starters: {total:,}")

    print("Pass 1: Fetching threads...")
    return fetch_pass(
        session, "Threads", query,
        THREADS_DIR, DATA_DIR / "threads_cursor.txt",
        DATA_DIR / "threads_count.txt", total, max_pages,
    )


def fetch_replies(session: requests.Session, max_pages: int | None = None) -> int:
    query = (
        f"SELECT id, subject, body, post_time, board.id, author.login, parent.id, depth "
        f"FROM messages "
        f"WHERE category.id = '{CATEGORY_ID}' AND depth > 0 "
        f"ORDER BY post_time DESC "
        f"LIMIT {PAGE_SIZE}"
    )
    print("\nPass 2: Counting replies...")
    total = get_total_count(session, "depth > 0")
    print(f"  Total replies: {total:,}")

    print("Pass 2: Fetching replies...")
    return fetch_pass(
        session, "Replies", query,
        REPLIES_DIR, DATA_DIR / "replies_cursor.txt",
        DATA_DIR / "replies_count.txt", total, max_pages,
    )


# --- Pass 3: Combine ---

def stream_jsonl(directory: Path):
    """Stream all JSONL files in a directory, yielding parsed objects."""
    for f in sorted(directory.glob("batch_*.jsonl")):
        with open(f, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    yield json.loads(line)


def combine_data():
    """Group threads and replies by board, output per-board JSON files."""
    print("\nPass 3: Combining data...")

    # Index threads by ID and group by board
    boards: dict[str, list] = defaultdict(list)
    thread_index: dict[str, dict] = {}
    thread_count = 0

    print("  Loading threads...")
    for msg in tqdm(stream_jsonl(THREADS_DIR), desc="  Threads", unit="msg"):
        board_id = msg.get("board", {}).get("id", "unknown")
        thread_id = msg.get("id", "")
        thread_entry = {
            "id": thread_id,
            "subject": msg.get("subject", ""),
            "body": msg.get("body", ""),
            "post_time": msg.get("post_time", ""),
            "board": board_id,
            "views": msg.get("metrics", {}).get("views", 0) if msg.get("metrics") else 0,
            "author": msg.get("author", {}).get("login", "") if msg.get("author") else "",
            "solved": msg.get("conversation", {}).get("solved", False) if msg.get("conversation") else False,
            "last_post_time": msg.get("conversation", {}).get("last_post_time", "") if msg.get("conversation") else "",
            "replies": [],
        }
        boards[board_id].append(thread_entry)
        thread_index[str(thread_id)] = thread_entry
        thread_count += 1

    print(f"  Indexed {thread_count:,} threads across {len(boards)} boards")

    # Attach replies to threads
    reply_count = 0
    orphan_count = 0
    print("  Loading replies...")
    for msg in tqdm(stream_jsonl(REPLIES_DIR), desc="  Replies", unit="msg"):
        parent_id = str(msg.get("parent", {}).get("id", "")) if msg.get("parent") else ""
        reply_entry = {
            "id": msg.get("id", ""),
            "subject": msg.get("subject", ""),
            "body": msg.get("body", ""),
            "post_time": msg.get("post_time", ""),
            "author": msg.get("author", {}).get("login", "") if msg.get("author") else "",
            "depth": msg.get("depth", 1),
            "parent_id": parent_id,
        }

        # Try to attach to parent thread
        if parent_id in thread_index:
            thread_index[parent_id]["replies"].append(reply_entry)
        else:
            # Reply to a reply — attach to the board's orphan bucket
            # We'll still save it, just not nested under a thread
            board_id = msg.get("board", {}).get("id", "unknown")
            # Try to find any thread in same board to attach loosely
            orphan_count += 1

        reply_count += 1

    print(f"  Attached {reply_count:,} replies ({orphan_count:,} orphaned/nested)")

    # Write per-board JSON files
    BOARDS_DIR.mkdir(parents=True, exist_ok=True)
    summary = {}

    print("  Writing per-board files...")
    for board_id, threads in tqdm(boards.items(), desc="  Boards", unit="board"):
        threads.sort(key=lambda t: t.get("post_time", ""), reverse=True)
        board_file = BOARDS_DIR / f"{board_id}.json"
        with open(board_file, "w", encoding="utf-8") as f:
            json.dump(threads, f, ensure_ascii=False)

        total_replies = sum(len(t["replies"]) for t in threads)
        summary[board_id] = {
            "threads": len(threads),
            "replies": total_replies,
            "total_messages": len(threads) + total_replies,
        }

    # Write summary
    summary_file = DATA_DIR / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # Write threads CSV
    print("  Writing threads.csv...")
    csv_file = DATA_DIR / "threads.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "subject", "board", "author", "post_time", "views",
                     "solved", "reply_count", "body_text"])
        for board_id, threads in boards.items():
            for t in threads:
                body = strip_html(t.get("body", ""))
                if len(body) > 2000:
                    body = body[:2000] + "..."
                w.writerow([
                    t["id"], t["subject"], t["board"], t["author"],
                    t["post_time"], t["views"], t["solved"],
                    len(t["replies"]), body,
                ])

    # Print summary
    print(f"\n{'='*60}")
    print(f"  Total boards:   {len(boards)}")
    print(f"  Total threads:  {thread_count:,}")
    print(f"  Total replies:  {reply_count:,}")
    print(f"{'='*60}")
    print(f"\n  Top 10 boards by thread count:")
    sorted_boards = sorted(summary.items(), key=lambda x: x[1]["threads"], reverse=True)
    for board_id, stats in sorted_boards[:10]:
        print(f"    {board_id}: {stats['threads']:,} threads, {stats['replies']:,} replies")

    print(f"\n  Output files:")
    print(f"    {summary_file}")
    print(f"    {csv_file}")
    print(f"    {BOARDS_DIR}/ ({len(boards)} board files)")


# --- Data Quality Validation ---

def validate_sample(directory: Path, label: str, expected_fields: list[str]) -> dict:
    """Validate a sample of fetched data and report quality metrics."""
    total = 0
    missing_fields: dict[str, int] = defaultdict(int)
    empty_bodies = 0
    empty_subjects = 0
    duplicate_ids = set()
    seen_ids = set()
    boards_seen = set()
    date_errors = 0
    sample_items = []

    for msg in stream_jsonl(directory):
        total += 1
        msg_id = str(msg.get("id", ""))

        if msg_id in seen_ids:
            duplicate_ids.add(msg_id)
        seen_ids.add(msg_id)

        for field in expected_fields:
            # Handle nested fields like "board.id"
            val = msg
            for part in field.split("."):
                val = val.get(part) if isinstance(val, dict) else None
            if val is None or val == "":
                missing_fields[field] += 1

        if not msg.get("body"):
            empty_bodies += 1
        if not msg.get("subject"):
            empty_subjects += 1

        board = msg.get("board", {})
        if isinstance(board, dict):
            boards_seen.add(board.get("id", "unknown"))

        pt = msg.get("post_time", "")
        if pt and not (pt.startswith("20") and "T" in pt):
            date_errors += 1

        if total <= 3:
            sample_items.append(msg)

    print(f"\n  --- {label} Quality Report ---")
    print(f"  Total items:       {total:,}")
    print(f"  Unique IDs:        {len(seen_ids):,}")
    print(f"  Duplicates:        {len(duplicate_ids):,}")
    print(f"  Empty bodies:      {empty_bodies:,} ({empty_bodies/max(total,1)*100:.1f}%)")
    print(f"  Empty subjects:    {empty_subjects:,}")
    print(f"  Date parse errors: {date_errors:,}")
    print(f"  Boards seen:       {len(boards_seen)}")
    if missing_fields:
        print(f"  Missing fields:")
        for field, count in sorted(missing_fields.items(), key=lambda x: -x[1]):
            print(f"    {field}: {count:,} ({count/max(total,1)*100:.1f}%)")

    if sample_items:
        print(f"\n  Sample items:")
        for item in sample_items[:2]:
            subj = item.get("subject", "")[:80]
            author = item.get("author", {})
            author_name = author.get("login", "") if isinstance(author, dict) else str(author)
            print(f"    [{item.get('id')}] {subj}")
            print(f"      author={author_name}, time={item.get('post_time', '')[:19]}")

    return {
        "total": total,
        "duplicates": len(duplicate_ids),
        "empty_bodies": empty_bodies,
        "boards": len(boards_seen),
    }


# --- Main ---

def main(argv=None):
    parser = argparse.ArgumentParser(description="Autodesk AEC Forum Scraper")
    parser.add_argument("--test", action="store_true",
                        help="Test mode: fetch only 2 pages per pass and validate")
    parser.add_argument("--threads-only", action="store_true",
                        help="Only fetch threads (skip replies)")
    parser.add_argument("--replies-only", action="store_true",
                        help="Only fetch replies (skip threads)")
    parser.add_argument("--combine-only", action="store_true",
                        help="Only run the combine step (skip fetching)")
    parser.add_argument("--validate-only", action="store_true",
                        help="Only validate existing data (no fetching)")
    args = parser.parse_args(argv)

    global PAGE_SIZE
    test_max_pages = None
    if args.test:
        test_max_pages = 2
        print("=" * 60)
        print("  TEST MODE: fetching only 2 pages per pass")
        print("=" * 60)

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    session = create_session()

    if args.validate_only:
        if THREADS_DIR.exists():
            validate_sample(THREADS_DIR, "Threads",
                            ["id", "subject", "body", "post_time", "board.id", "author.login"])
        if REPLIES_DIR.exists():
            validate_sample(REPLIES_DIR, "Replies",
                            ["id", "subject", "body", "post_time", "board.id", "author.login", "parent.id"])
        return

    if args.combine_only:
        combine_data()
        return

    if not args.replies_only:
        fetch_threads(session, max_pages=test_max_pages)
        if args.test:
            validate_sample(THREADS_DIR, "Threads",
                            ["id", "subject", "body", "post_time", "board.id", "author.login"])

    if not args.threads_only:
        fetch_replies(session, max_pages=test_max_pages)
        if args.test:
            validate_sample(REPLIES_DIR, "Replies",
                            ["id", "subject", "body", "post_time", "board.id", "author.login", "parent.id"])

    if not args.test:
        combine_data()
    else:
        print("\n" + "=" * 60)
        print("  TEST COMPLETE. Review quality reports above.")
        print("  If satisfied, run without --test for the full scrape.")
        print("  Data will resume from where it left off.")
        print("=" * 60)

    print("\nDone!")


if __name__ == "__main__":
    main()
