"""Bluebeam Community Forum Scraper

Scrapes all discussion posts and comments from community.bluebeam.com
using the public Vanilla Forums API.
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock

import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry

# --- Configuration ---
BASE_URL = "https://community.bluebeam.com/api/v2"
DISCUSSIONS_PER_PAGE = 100
COMMENTS_PER_PAGE = 100
MAX_WORKERS = 5
DELAY_BETWEEN_PAGES = 0.5  # seconds
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 2

DATA_DIR = Path("data")
DISCUSSIONS_DIR = DATA_DIR / "discussions"
COMMENTS_DIR = DATA_DIR / "comments"

# Thread-safe print lock
print_lock = Lock()


def create_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.headers.update({"Accept": "application/json"})
    return session


def fetch_all_discussions() -> list[dict]:
    """Fetch all discussions, paginating through the API."""
    session = create_session()
    all_discussions = []
    page = 1

    print("Phase 1: Fetching discussions...")

    while True:
        cache_file = DISCUSSIONS_DIR / f"page_{page}.json"

        # Resume from cache
        if cache_file.exists():
            with open(cache_file, "r", encoding="utf-8") as f:
                discussions = json.load(f)
            if not discussions:
                break
            all_discussions.extend(discussions)
            print(f"  Page {page}: loaded {len(discussions)} from cache")
            page += 1
            continue

        # Fetch from API
        try:
            resp = session.get(
                f"{BASE_URL}/discussions",
                params={
                    "limit": DISCUSSIONS_PER_PAGE,
                    "page": page,
                    "sort": "-dateInserted",
                    "expand": "all",
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            discussions = resp.json()
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                break
            raise
        except Exception as e:
            print(f"  Error fetching page {page}: {e}")
            break

        if not discussions:
            break

        # Save checkpoint
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(discussions, f, ensure_ascii=False)

        all_discussions.extend(discussions)
        print(f"  Page {page}: fetched {len(discussions)} discussions")

        if len(discussions) < DISCUSSIONS_PER_PAGE:
            break

        page += 1
        time.sleep(DELAY_BETWEEN_PAGES)

    print(f"  Total: {len(all_discussions)} discussions")
    return all_discussions


def fetch_comments_for_discussion(discussion_id: int, expected_count: int) -> list[dict]:
    """Fetch all comments for a single discussion."""
    cache_file = COMMENTS_DIR / f"{discussion_id}.json"

    # Resume from cache
    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    if expected_count == 0:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump([], f)
        return []

    session = create_session()
    all_comments = []
    page = 1

    while True:
        try:
            resp = session.get(
                f"{BASE_URL}/comments",
                params={
                    "discussionID": discussion_id,
                    "limit": COMMENTS_PER_PAGE,
                    "page": page,
                    "expand": "all",
                },
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            comments = resp.json()
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                break
            with print_lock:
                print(f"  Warning: HTTP error for discussion {discussion_id}: {e}")
            break
        except Exception as e:
            with print_lock:
                print(f"  Warning: Error fetching comments for {discussion_id}: {e}")
            break

        if not comments:
            break

        all_comments.extend(comments)

        if len(comments) < COMMENTS_PER_PAGE:
            break

        page += 1
        time.sleep(0.1)

    # Save checkpoint
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(all_comments, f, ensure_ascii=False)

    return all_comments


def fetch_all_comments(discussions: list[dict]) -> dict[int, list[dict]]:
    """Fetch comments for all discussions using thread pool."""
    print(f"\nPhase 2: Fetching comments for {len(discussions)} discussions...")

    comments_map: dict[int, list[dict]] = {}
    failed_ids: list[int] = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = {}
        for d in discussions:
            did = d["discussionID"]
            count = d.get("countComments", 0)
            future = executor.submit(fetch_comments_for_discussion, did, count)
            futures[future] = did

        with tqdm(total=len(futures), desc="  Comments", unit="post") as pbar:
            for future in as_completed(futures):
                did = futures[future]
                try:
                    comments_map[did] = future.result()
                except Exception as e:
                    with print_lock:
                        print(f"  Failed: discussion {did}: {e}")
                    failed_ids.append(did)
                    comments_map[did] = []
                pbar.update(1)

    if failed_ids:
        print(f"  Warning: {len(failed_ids)} discussions had comment fetch errors")

    total_comments = sum(len(c) for c in comments_map.values())
    print(f"  Total: {total_comments} comments collected")
    return comments_map


def combine_data(discussions: list[dict], comments_map: dict[int, list[dict]]) -> None:
    """Merge discussions with their comments and write combined output."""
    print("\nPhase 3: Combining data...")

    combined = []
    for d in discussions:
        did = d["discussionID"]
        entry = dict(d)
        entry["comments"] = comments_map.get(did, [])
        combined.append(entry)

    # Sort by discussionID
    combined.sort(key=lambda x: x["discussionID"])

    output_file = DATA_DIR / "combined.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(combined, f, ensure_ascii=False, indent=2)

    print(f"  Wrote {len(combined)} discussions to {output_file}")

    # Summary stats
    total_comments = sum(len(d["comments"]) for d in combined)
    categories = {}
    for d in combined:
        cat = d.get("category", {}).get("name", "Unknown") if isinstance(d.get("category"), dict) else str(d.get("categoryID", "Unknown"))
        categories[cat] = categories.get(cat, 0) + 1

    print(f"\n  Summary:")
    print(f"    Discussions: {len(combined)}")
    print(f"    Comments:    {total_comments}")
    print(f"    Categories:  {len(categories)}")
    for cat, count in sorted(categories.items(), key=lambda x: -x[1])[:10]:
        print(f"      {cat}: {count}")


def main():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    DISCUSSIONS_DIR.mkdir(exist_ok=True)
    COMMENTS_DIR.mkdir(exist_ok=True)

    discussions = fetch_all_discussions()
    if not discussions:
        print("No discussions found. Exiting.")
        sys.exit(1)

    comments_map = fetch_all_comments(discussions)
    combine_data(discussions, comments_map)

    print("\nDone!")


if __name__ == "__main__":
    main()
