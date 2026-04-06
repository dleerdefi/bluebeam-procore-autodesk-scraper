"""AEC Forum Feature Gap Analyzer — main entry point.

Usage:
  python main.py scrape [--platform bluebeam|autodesk|procore]
  python main.py analyze [--preprocess] [--extract] [--synthesize] [--visualize] [--all] ...
  python main.py export-csv
  python main.py export-blog
  python main.py all [--test] [--model MODEL] [--base-url URL]
"""

import argparse
import sys


def cmd_scrape(args):
    platforms = [args.platform] if args.platform else ["bluebeam", "autodesk", "procore"]
    for p in platforms:
        print(f"\n{'='*60}")
        print(f"  Scraping {p}...")
        print(f"{'='*60}")
        if p == "bluebeam":
            from aec_analysis.scrapers.bluebeam import main as run
            run()
        elif p == "autodesk":
            from aec_analysis.scrapers.autodesk import main as run
            run([])
        elif p == "procore":
            from aec_analysis.scrapers.procore import main as run
            run([])


def cmd_analyze(args):
    argv = []
    if args.preprocess:
        argv.append("--preprocess")
    if args.extract:
        argv.append("--extract")
    if args.synthesize:
        argv.append("--synthesize")
    if args.visualize:
        argv.append("--visualize")
    if args.run_all:
        argv.append("--all")
    if args.platform:
        argv.extend(["--platform", args.platform])
    if args.model:
        argv.extend(["--model", args.model])
    if args.base_url:
        argv.extend(["--base-url", args.base_url])
    if args.test:
        argv.append("--test")
    if args.compare_models:
        argv.append("--compare-models")

    from aec_analysis.analysis.llm import main as run
    run(argv)


def cmd_export_csv(args):
    from aec_analysis.analysis.export import main as run
    run()


def cmd_export_blog(args):
    from aec_analysis.blog_export import main as run
    run()


def cmd_all(args):
    """Run the full pipeline: scrape → analyze → export."""
    # Scrape all platforms
    cmd_scrape(argparse.Namespace(platform=None))

    # Analyze: preprocess → extract → synthesize → visualize
    analyze_argv = ["--all"]
    if args.test:
        analyze_argv.append("--test")
    if args.model:
        analyze_argv.extend(["--model", args.model])
    if args.base_url:
        analyze_argv.extend(["--base-url", args.base_url])

    from aec_analysis.analysis.llm import main as run_llm
    run_llm(analyze_argv)

    # CSV/HTML export
    from aec_analysis.analysis.export import main as run_export
    run_export()

    print("\nFull pipeline complete!")


def main():
    parser = argparse.ArgumentParser(
        description="AEC Forum Feature Gap Analyzer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # scrape
    sp_scrape = subparsers.add_parser("scrape", help="Scrape forum data")
    sp_scrape.add_argument("--platform", choices=["bluebeam", "autodesk", "procore"],
                           help="Scrape a single platform (default: all)")

    # analyze
    sp_analyze = subparsers.add_parser("analyze", help="Run LLM analysis pipeline")
    sp_analyze.add_argument("--preprocess", action="store_true", help="Preprocess data into batches")
    sp_analyze.add_argument("--extract", action="store_true", help="Run LLM extraction")
    sp_analyze.add_argument("--synthesize", action="store_true", help="Synthesize results")
    sp_analyze.add_argument("--visualize", action="store_true", help="Generate visualization")
    sp_analyze.add_argument("--all", dest="run_all", action="store_true", help="Run all analysis stages")
    sp_analyze.add_argument("--compare-models", action="store_true", help="Compare A/B test results")
    sp_analyze.add_argument("--platform", choices=["bluebeam", "procore", "autodesk"],
                            help="Target platform (for --extract)")
    sp_analyze.add_argument("--model", help="LLM model ID (overrides .env)")
    sp_analyze.add_argument("--base-url", help="LLM base URL (for local provider)")
    sp_analyze.add_argument("--test", action="store_true", help="Test mode: 3 batches only")

    # export-csv
    subparsers.add_parser("export-csv", help="Export data to CSV/HTML")

    # export-blog
    subparsers.add_parser("export-blog", help="Export TypeScript blog data")

    # all
    sp_all = subparsers.add_parser("all", help="Run full pipeline end-to-end")
    sp_all.add_argument("--test", action="store_true", help="Test mode: 3 batches only")
    sp_all.add_argument("--model", help="LLM model ID (overrides .env)")
    sp_all.add_argument("--base-url", help="LLM base URL (for local provider)")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "scrape": cmd_scrape,
        "analyze": cmd_analyze,
        "export-csv": cmd_export_csv,
        "export-blog": cmd_export_blog,
        "all": cmd_all,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
