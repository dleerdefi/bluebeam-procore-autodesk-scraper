# I Scraped 488,850 Construction Forum Posts. Here's What Users Actually Want.

Scrapes community forums from **Bluebeam**, **Autodesk**, and **Procore** — the three platforms that run the AEC industry — then uses LLM-powered batch analysis to classify every thread by feature category, sentiment, and severity. Produces **9,361 structured extractions across 20 product categories**.

The result: a data-driven map of the biggest software gaps in construction tech.

## Results

### The Top 10 Pain Points Have Nothing to Do with AI

| Rank | Category | Gap Score | Mentions | Key Finding |
|------|----------|-----------|----------|-------------|
| 1 | Document Management | 749 | 997 | Pain felt equally across all 3 platforms |
| 2 | Markup & Annotation | 710 | 1,016 | Bluebeam dominates (687 posts) — their core product |
| 3 | UX & Usability | 703 | 1,034 | Highest volume; Autodesk users most frustrated (51% negative) |
| 4 | Performance | 658 | 551 | **Most severe — 84–90% negative sentiment** |
| 5 | Integrations | 613 | 761 | Procore leads (423 posts) — ecosystem gaps |
| 6 | BIM & 3D | 542 | 675 | Autodesk-heavy (573 posts) |
| 7 | Cost & Financial | 465 | 563 | Procore-dominated (544 posts) |
| 8 | Permissions & Security | 399 | 439 | 54–68% negative on Bluebeam & Autodesk |
| 9 | Measurement & Takeoff | 350 | 468 | Bluebeam's core use case (327 posts) |
| 10 | Mobile & Tablet | 335 | 385 | ~50% negative — field users are underserved |

AI doesn't crack the top 10. Users are asking for document handling that doesn't lose files, markup tools that don't freeze, and integrations that actually connect their stack.

### Platform Sentiment

| Platform | Negative | Positive | Neutral |
|----------|----------|----------|---------|
| Bluebeam | 34% | 11% | 54% |
| Procore | 30% | 8% | 62% |
| Autodesk | **46%** | **3%** | 51% |

Autodesk forums are nearly half negative with almost zero positive sentiment — a platform-wide usability crisis. Procore skews neutral and question-driven. Bluebeam users are loyal but vocal about markup and measurement gaps.

### Data Scale

| Platform | Posts Scraped | Batches | Extractions |
|----------|-------------|---------|-------------|
| Bluebeam | 3,195 | 320 | 3,056 |
| Autodesk | 482,361 | 300 | 2,997 |
| Procore | 3,294 | 330 | 3,308 |
| **Total** | **488,850** | **950** | **9,361** |

*Methodology: Forum posts scraped via REST API (Bluebeam Vanilla Forums, Autodesk Khoros/LiQL) and Playwright browser automation (Procore Salesforce Experience Cloud). Threads batched and processed through LLM extraction with structured JSON output. Each extraction classified by category, sentiment, severity (1-5), staff response, and user agreement.*

## Architecture

```
bluebeam-scraper/
├── main.py                      # Single entry point
├── aec_analysis/
│   ├── scrapers/
│   │   ├── bluebeam.py          # Bluebeam Community (REST API)
│   │   ├── autodesk.py          # Autodesk Forums (LiQL API)
│   │   └── procore.py           # Procore Community (Playwright)
│   ├── analysis/
│   │   ├── llm.py               # LLM extraction + synthesis + visualization
│   │   └── export.py            # CSV/HTML export
│   └── blog_export.py           # TypeScript blog data export
├── .env.example
├── requirements.txt
└── README.md
```

```
Scraping             Preprocessing        LLM Extraction       Synthesis           Visualization
────────────────    ────────────────    ────────────────    ──────────────    ────────────────
bluebeam.py     ─┐                     ┌─ Anthropic API    per-platform      feature_matrix.html
autodesk.py      ├─► llm.py           ─┤  (Claude Haiku)   summaries     ─►  feature_matrix.csv
procore.py      ─┘   --preprocess      └─ Local LLM        cross-platform    blog_export/
                                          (OpenAI-compat)   rankings
```

## Quick Start

```bash
git clone <repo-url> && cd bluebeam-scraper

python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate

pip install -r requirements.txt

# Only needed for Procore scraper (uses browser automation)
playwright install chromium
```

### Configure LLM

```bash
cp .env.example .env
```

Edit `.env` and choose your provider:

**Option A — Anthropic API (default):**
```
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

**Option B — Local LLM:**
```
LLM_PROVIDER=local
LLM_BASE_URL=http://localhost:1234/v1
LLM_MODEL=qwen/qwen3.5-35b-a3b
LLM_API_KEY=not-needed
```

## Usage

### Full pipeline (scrape + analyze + export)

```bash
python main.py all                  # Everything end-to-end
python main.py all --test           # Test mode (3 batches only)
```

### Individual commands

```bash
# Scrape forum data
python main.py scrape                           # All platforms
python main.py scrape --platform bluebeam       # Single platform

# LLM analysis pipeline
python main.py analyze --all                    # All analysis stages
python main.py analyze --preprocess             # Batch threads for LLM
python main.py analyze --extract --platform bluebeam
python main.py analyze --synthesize             # Aggregate results
python main.py analyze --visualize              # Generate HTML report
python main.py analyze --compare-models         # A/B test results

# Exports
python main.py export-csv                       # CSV + HTML report
python main.py export-blog                      # TypeScript blog data
```

### CLI flags (analyze subcommand)

| Flag | Description |
|------|-------------|
| `--preprocess` | Serialize threads into batches for LLM processing |
| `--extract` | Run LLM extraction on batches |
| `--synthesize` | Aggregate extraction results into summaries |
| `--visualize` | Generate interactive HTML report + CSV |
| `--all` | Run all analysis stages |
| `--platform` | Target a single platform (`bluebeam`, `autodesk`, `procore`) |
| `--model` | Override LLM model ID |
| `--base-url` | Override LLM server URL (local provider) |
| `--test` | Test mode — process only 3 batches |
| `--compare-models` | Compare A/B test results between models |

### View results

- **Interactive report:** open `data/feature_matrix.html` in a browser
- **CSV export:** `data/feature_matrix.csv` for spreadsheets / BI tools
- **Raw JSON:** `data/llm_synthesis/cross_platform.json`

## Output

| Path | Contents |
|------|----------|
| `data/llm_batches/` | Preprocessed thread batches (input to LLM) |
| `data/llm_results/` | Per-batch extraction results with metadata |
| `data/llm_synthesis/` | Aggregated summaries per platform + cross-platform |
| `data/feature_matrix.html` | Interactive Chart.js visualization |
| `data/feature_matrix.csv` | Flat CSV for analysis tools |

## Notes

- **Procore scraper** requires Playwright (headless Chromium) because the site is JavaScript-rendered via Salesforce Experience Cloud.
- **Rate limiting:** scrapers include built-in delays. The forum APIs are public but be respectful with request volume.
- **LLM extraction** is idempotent — existing result files are skipped on re-runs. Delete a batch result file to re-process it.
- All output directories are created automatically on first run — no manual setup needed.

## License

MIT