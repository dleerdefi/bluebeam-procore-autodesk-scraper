"""Configuration — environment variables, paths, and tuning constants."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- LLM Provider ---
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "anthropic")

# Anthropic settings
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")

# Local LLM settings (OpenAI-compatible server)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "http://localhost:1234/v1")
LLM_MODEL = os.getenv("LLM_MODEL", "")
LLM_API_KEY = os.getenv("LLM_API_KEY", "not-needed")

# --- Tuning ---
MAX_TOKENS = 4096
TEMPERATURE = 0.2
THREADS_PER_BATCH = 10
MAX_BODY_CHARS = 400
MAX_COMMENT_CHARS = 200
MAX_COMMENTS_PER_THREAD = 5
AUTODESK_SAMPLE_SIZE = 3000
TEST_BATCHES = 3

# --- Paths ---
DATA_DIR = Path("data")
BATCHES_DIR = DATA_DIR / "llm_batches"
RESULTS_DIR = DATA_DIR / "llm_results"
SYNTHESIS_DIR = DATA_DIR / "llm_synthesis"
