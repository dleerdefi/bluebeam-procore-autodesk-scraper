# Bluebeam, Procore, Autodesk Forum Scraper

Scrapes community forums from **Bluebeam**, **Autodesk**, and **Procore**, then uses an LLM to extract structured product insights and generates interactive visualizations.

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