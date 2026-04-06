"""Procore Community Scraper

Scrapes all questions and answers from community.procore.com
using Playwright browser automation (Salesforce Experience Cloud).
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from tqdm import tqdm

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BASE_URL = "https://community.procore.com"
DATA_DIR = Path("data") / "procore"
TOPICS_FILE = DATA_DIR / "topics.json"
TOPIC_POSTS_DIR = DATA_DIR / "topic_posts"
QUESTIONS_DIR = DATA_DIR / "questions"

PAGE_LOAD_WAIT = 8  # seconds to wait for JS rendering
BETWEEN_PAGES = 2  # delay between page loads
MAX_RETRIES = 3


def wait_for_content(page, seconds=PAGE_LOAD_WAIT):
    """Wait for Salesforce Lightning content to render."""
    time.sleep(seconds)


def dismiss_cookie_banner(page):
    """Dismiss OneTrust cookie consent banner if present."""
    try:
        accept_btn = page.query_selector("#onetrust-accept-btn-handler")
        if accept_btn and accept_btn.is_visible():
            accept_btn.click()
            time.sleep(1)
            return
        # Try rejecting or closing
        for selector in ["#onetrust-reject-all-handler", ".onetrust-close-btn-handler", "#onetrust-close-btn-container button"]:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                btn.click()
                time.sleep(1)
                return
        # Force remove the overlay via JS
        page.evaluate("document.querySelector('#onetrust-consent-sdk')?.remove()")
    except Exception:
        try:
            page.evaluate("document.querySelector('#onetrust-consent-sdk')?.remove()")
        except Exception:
            pass


def safe_goto(page, url, retries=MAX_RETRIES):
    """Navigate to URL with retries."""
    for attempt in range(retries):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            wait_for_content(page)
            dismiss_cookie_banner(page)
            return True
        except PlaywrightTimeout:
            print(f"  Timeout loading {url}, retry {attempt + 1}/{retries}")
            time.sleep(5)
        except Exception as e:
            print(f"  Error loading {url}: {e}, retry {attempt + 1}/{retries}")
            time.sleep(5)
    return False


# --- Phase 1: Collect Topics ---

def collect_topics(page) -> list[dict]:
    """Scrape all topic URLs from the topic catalog."""
    if TOPICS_FILE.exists():
        with open(TOPICS_FILE, "r", encoding="utf-8") as f:
            topics = json.load(f)
        print(f"  Loaded {len(topics)} topics from cache")
        return topics

    print("Phase 1: Collecting topics from catalog...")
    if not safe_goto(page, f"{BASE_URL}/s/topiccatalog"):
        print("  Failed to load topic catalog")
        return []

    links = page.eval_on_selector_all('a[href*="/s/topic/"]', '''
        elements => elements.map(el => ({
            url: el.href,
            name: el.textContent.trim()
        }))
    ''')

    # Deduplicate by URL
    seen = set()
    topics = []
    for link in links:
        url = link["url"].split("?")[0]  # strip query params
        if url not in seen and link["name"]:
            seen.add(url)
            # Extract topic ID from URL
            match = re.search(r"/s/topic/(0TO[A-Za-z0-9]+)", url)
            topic_id = match.group(1) if match else url.split("/")[-1]
            topics.append({
                "id": topic_id,
                "name": link["name"],
                "url": url,
            })

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(TOPICS_FILE, "w", encoding="utf-8") as f:
        json.dump(topics, f, ensure_ascii=False, indent=2)

    print(f"  Found {len(topics)} unique topics")
    for t in topics:
        print(f"    {t['name']}")
    return topics


# --- Phase 2: Collect Question URLs per Topic ---

def _extract_question_links(page) -> list[dict]:
    """Extract all question links currently visible on the page."""
    return page.eval_on_selector_all('a[href*="/s/question/"]', '''
        elements => elements.map(el => ({
            url: el.href,
            title: el.textContent.trim()
        }))
    ''')


def collect_topic_posts(page, topic: dict) -> list[dict]:
    """Scrape all question URLs from a single topic page, clicking 'View More' to load all."""
    TOPIC_POSTS_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = TOPIC_POSTS_DIR / f"{topic['id']}.json"

    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    if not safe_goto(page, topic["url"]):
        return []

    consecutive_failures = 0
    max_view_more_clicks = 100

    for click_num in range(max_view_more_clicks):
        # Try clicking "View More"
        try:
            view_more = page.query_selector("button.cuf-showMore")
            if not view_more or not view_more.is_visible():
                break

            # Count links before click
            count_before = len(_extract_question_links(page))

            # Scroll to button and click
            view_more.scroll_into_view_if_needed()
            time.sleep(0.5)
            view_more.click()

            # Poll for new content (up to 12 seconds)
            loaded = False
            for _ in range(12):
                time.sleep(1)
                count_after = len(_extract_question_links(page))
                if count_after > count_before:
                    loaded = True
                    break

            if loaded:
                consecutive_failures = 0
            else:
                consecutive_failures += 1
                if consecutive_failures >= 2:
                    break

        except Exception:
            consecutive_failures += 1
            if consecutive_failures >= 2:
                break

    # Extract all question links after loading everything
    links = _extract_question_links(page)
    all_questions = []
    seen_urls = set()

    for link in links:
        url = link["url"].split("?")[0]
        if url not in seen_urls and link["title"]:
            match = re.search(r"/s/question/(0D5[A-Za-z0-9]+)", url)
            qid = match.group(1) if match else ""
            all_questions.append({
                "id": qid,
                "title": link["title"][:200],
                "url": url,
                "topic_id": topic["id"],
                "topic_name": topic["name"],
            })
            seen_urls.add(url)

    print(f"    {topic['name']}: {len(all_questions)} questions")

    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(all_questions, f, ensure_ascii=False, indent=2)

    return all_questions


def collect_all_posts(page, topics: list[dict]) -> list[dict]:
    """Collect question URLs from all topics."""
    print("\nPhase 2: Collecting question URLs from topics...")
    all_questions = []

    for topic in tqdm(topics, desc="  Topics", unit="topic"):
        questions = collect_topic_posts(page, topic)
        all_questions.extend(questions)
        time.sleep(BETWEEN_PAGES)

    # Deduplicate (questions can appear in multiple topics)
    seen = {}
    unique = []
    for q in all_questions:
        if q["url"] not in seen:
            seen[q["url"]] = True
            unique.append(q)

    print(f"  Total unique questions: {len(unique)}")
    return unique


# --- Phase 3: Scrape Individual Questions ---

_TIME_PATTERN = re.compile(
    r'(\d+\s+(?:second|minute|hour|day|week|month|year)s?\s+ago'
    r'|a\s+(?:second|minute|hour|day|week|month|year)\s+ago'
    r'|yesterday|just now)',
    re.IGNORECASE,
)


def _clean_body(text: str) -> str:
    """Strip trailing 'Expand Post' and other artifacts from body text."""
    text = re.sub(r'\s*Expand Post\s*$', '', text)
    text = re.sub(r'\s*Upvote\s*Upvoted\s*Remove Upvote\s*Reply\s*$', '', text)
    return text.strip()


def scrape_question(page, question: dict) -> dict | None:
    """Scrape a single question page for content and comments."""
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    cache_file = QUESTIONS_DIR / f"{question['id']}.json"

    if cache_file.exists():
        with open(cache_file, "r", encoding="utf-8") as f:
            return json.load(f)

    if not safe_goto(page, question["url"]):
        return None

    # Click all "Expand Post" links to uncollapse truncated content
    try:
        expand_links = page.query_selector_all("a.cuf-more")
        for link in expand_links:
            try:
                if link.is_visible():
                    link.click()
                    time.sleep(0.3)
            except Exception:
                pass
        if expand_links:
            time.sleep(1)
    except Exception:
        pass

    result = {
        "id": question["id"],
        "url": question["url"],
        "topic_id": question.get("topic_id", ""),
        "topic_name": question.get("topic_name", ""),
    }

    # Extract title
    try:
        result["title"] = (page.text_content(".cuf-questionTitle") or "").strip()
    except Exception:
        result["title"] = question.get("title", "")

    # Extract body — prefer .feedBodyInner for cleaner text
    try:
        body = (page.text_content(".cuf-questionBody .feedBodyInner")
                or page.text_content(".cuf-questionBody") or "")
        result["body"] = _clean_body(body)
    except Exception:
        result["body"] = ""

    # Extract body HTML
    try:
        result["body_html"] = page.inner_html(".cuf-questionBody") or ""
    except Exception:
        result["body_html"] = ""

    # Extract timestamp (first non-empty .cuf-timestamp on page)
    try:
        timestamps = page.eval_on_selector_all(
            ".cuf-timestamp",
            "els => els.map(e => e.textContent.trim()).filter(t => t.length > 0)"
        )
        result["date"] = timestamps[0] if timestamps else ""
    except Exception:
        result["date"] = ""

    # Extract author — first entityLink (not a @mention) is the question author
    try:
        authors = page.eval_on_selector_all(
            "a.cuf-entityLink:not(.cuf-mention)",
            "els => els.map(e => e.textContent.trim())"
        )
        result["author"] = authors[0] if authors else ""
    except Exception:
        result["author"] = ""

    # Extract comments/answers
    comments = []
    try:
        comment_elements = page.query_selector_all(".cuf-commentItem")
        for el in comment_elements:
            try:
                comment_data = {}

                # Author: first entityLink that's not a @mention
                author_el = el.query_selector("a.cuf-entityLink:not(.cuf-mention)")
                comment_data["author"] = (author_el.text_content() or "").strip() if author_el else ""

                # Body: use .feedBodyInner for clean text
                body_el = el.query_selector(".feedBodyInner")
                if not body_el:
                    body_el = el.query_selector(".cuf-feedBodyText")
                body = (body_el.text_content() or "").strip() if body_el else ""
                comment_data["body"] = _clean_body(body)

                # Timestamp: parse relative time from raw text
                raw = (el.text_content() or "").strip()
                time_match = _TIME_PATTERN.search(raw)
                comment_data["date"] = time_match.group(0) if time_match else ""

                # Keep raw text as backup
                comment_data["raw_text"] = raw[:2000]

                # Skip empty comments (no body and no author)
                if comment_data["body"] or comment_data["author"]:
                    comments.append(comment_data)
            except Exception:
                continue
    except Exception:
        pass

    result["comments"] = comments
    result["comment_count"] = len(comments)

    # Save
    with open(cache_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    return result


def scrape_all_questions(page, questions: list[dict]):
    """Scrape content for all questions."""
    print(f"\nPhase 3: Scraping {len(questions)} questions...")
    results = []
    errors = []

    for q in tqdm(questions, desc="  Questions", unit="q"):
        result = scrape_question(page, q)
        if result:
            results.append(result)
        else:
            errors.append(q["url"])
        time.sleep(BETWEEN_PAGES)

    if errors:
        print(f"  {len(errors)} questions failed to load")

    return results


# --- Combine ---

def combine_data():
    """Merge all question files into combined output."""
    print("\nCombining data...")
    questions = []
    for f in sorted(QUESTIONS_DIR.glob("*.json")):
        with open(f, "r", encoding="utf-8") as fh:
            questions.append(json.load(fh))

    # Write combined JSON
    combined_file = DATA_DIR / "combined.json"
    with open(combined_file, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)

    # Write CSV
    import csv
    csv_file = DATA_DIR / "questions.csv"
    with open(csv_file, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "title", "author", "date", "topic", "comment_count", "body", "url"])
        for q in questions:
            body = q.get("body", "")[:2000]
            w.writerow([
                q.get("id", ""),
                q.get("title", ""),
                q.get("author", ""),
                q.get("date", ""),
                q.get("topic_name", ""),
                q.get("comment_count", 0),
                body,
                q.get("url", ""),
            ])

    # Summary
    total_comments = sum(q.get("comment_count", 0) for q in questions)
    topics = set(q.get("topic_name", "") for q in questions)
    print(f"\n{'='*50}")
    print(f"  Questions:       {len(questions):,}")
    print(f"  Total comments:  {total_comments:,}")
    print(f"  Topics:          {len(topics)}")
    print(f"{'='*50}")
    print(f"  Output: {combined_file}")
    print(f"  CSV:    {csv_file}")


# --- Main ---

def main(argv=None):
    parser = argparse.ArgumentParser(description="Procore Community Scraper")
    parser.add_argument("--phase", type=int, choices=[1, 2, 3],
                        help="Run only a specific phase (1=topics, 2=post URLs, 3=content)")
    parser.add_argument("--combine-only", action="store_true",
                        help="Only run the combine step")
    args = parser.parse_args(argv)

    if args.combine_only:
        combine_data()
        return

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        if args.phase == 1 or args.phase is None:
            topics = collect_topics(page)
        else:
            # Load from cache
            if TOPICS_FILE.exists():
                with open(TOPICS_FILE, "r", encoding="utf-8") as f:
                    topics = json.load(f)
            else:
                print("No topics.json found. Run --phase 1 first.")
                return

        if args.phase == 2 or args.phase is None:
            questions = collect_all_posts(page, topics)
        elif args.phase == 3:
            # Load from cache
            questions = []
            for f in sorted(TOPIC_POSTS_DIR.glob("*.json")):
                with open(f, "r", encoding="utf-8") as fh:
                    questions.extend(json.load(fh))
            # Deduplicate
            seen = {}
            unique = []
            for q in questions:
                if q["url"] not in seen:
                    seen[q["url"]] = True
                    unique.append(q)
            questions = unique
        else:
            questions = []

        if args.phase == 3 or args.phase is None:
            scrape_all_questions(page, questions)

        browser.close()

    if args.phase is None or args.phase == 3:
        combine_data()

    print("\nDone!")


if __name__ == "__main__":
    main()
