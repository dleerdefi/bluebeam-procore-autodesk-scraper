"""LLM Feature Gap Analysis Pipeline — CLI entry point.

Usage:
  python -m aec_analysis.analysis.llm --preprocess [--test]
  python -m aec_analysis.analysis.llm --extract --platform bluebeam [--test] [--model MODEL_ID]
  python -m aec_analysis.analysis.llm --compare-models
  python -m aec_analysis.analysis.llm --synthesize
  python -m aec_analysis.analysis.llm --visualize
  python -m aec_analysis.analysis.llm --all
"""

import argparse
import sys

from .config import ANTHROPIC_MODEL, LLM_MODEL, LLM_PROVIDER
from .extraction import compare_models, run_extraction
from .preprocessing import preprocess_autodesk, preprocess_bluebeam, preprocess_procore
from .synthesis import run_synthesis
from .visualization import run_visualization

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main(argv=None):
    parser = argparse.ArgumentParser(description="LLM Feature Gap Analysis Pipeline")
    parser.add_argument("--preprocess", action="store_true", help="Stage 1: Preprocess data into batches")
    parser.add_argument("--extract", action="store_true", help="Stage 2: Run LLM extraction")
    parser.add_argument("--synthesize", action="store_true", help="Stage 3: Synthesize results")
    parser.add_argument("--visualize", action="store_true", help="Stage 4: Generate visualization")
    parser.add_argument("--compare-models", action="store_true", help="Compare A/B test results")
    parser.add_argument("--all", action="store_true", help="Run full pipeline")
    parser.add_argument("--platform", type=str, choices=["bluebeam", "procore", "autodesk"],
                        help="Platform to process (for --extract)")
    parser.add_argument("--model", type=str, default=None, help="LLM model ID (overrides .env)")
    parser.add_argument("--base-url", type=str, default=None, help="LLM base URL (for local provider)")
    parser.add_argument("--test", action="store_true", help="Test mode: 3 batches only")
    args = parser.parse_args(argv)

    # Resolve model: CLI flag > env var > provider default
    if args.model is None:
        args.model = ANTHROPIC_MODEL if LLM_PROVIDER == "anthropic" else LLM_MODEL

    if args.compare_models:
        compare_models()
        return

    if args.preprocess or args.all:
        preprocess_bluebeam(args.test)
        preprocess_procore(args.test)
        preprocess_autodesk(args.test)

    if args.extract or args.all:
        platforms = [args.platform] if args.platform else ["bluebeam", "procore", "autodesk"]
        for p in platforms:
            print(f"\nExtracting {p}...")
            run_extraction(p, args.model, args.test, base_url=args.base_url)

    if args.synthesize or args.all:
        print("\nSynthesizing...")
        run_synthesis()

    if args.visualize or args.all:
        print("\nGenerating visualization...")
        run_visualization()

    print("\nDone!")


if __name__ == "__main__":
    main()
