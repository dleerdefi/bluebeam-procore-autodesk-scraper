"""LLM client abstraction and batch extraction logic."""

import json
import re
import time
from abc import ABC, abstractmethod

from tqdm import tqdm

from .config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    BATCHES_DIR,
    LLM_API_KEY,
    LLM_BASE_URL,
    LLM_MODEL,
    LLM_PROVIDER,
    MAX_TOKENS,
    RESULTS_DIR,
    TEMPERATURE,
    TEST_BATCHES,
)
from .prompts import EXTRACTION_PROMPT, EXTRACTION_SCHEMA, SYSTEM_PROMPT


# --- LLM Client Interface ---

class LLMClient(ABC):
    """Provider-agnostic LLM client interface."""

    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = MAX_TOKENS,
                 temperature: float = TEMPERATURE, response_format: dict | None = None) -> tuple[str, int]:
        """Return (response_text, total_tokens)."""


class AnthropicClient(LLMClient):
    def __init__(self, model: str = ANTHROPIC_MODEL):
        import anthropic
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY not set. Add it to your .env file.")
        self.client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = MAX_TOKENS,
                 temperature: float = TEMPERATURE, response_format: dict | None = None) -> tuple[str, int]:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        text = response.content[0].text if response.content else ""
        tokens = (response.usage.input_tokens + response.usage.output_tokens) if response.usage else 0
        return text, tokens


class LocalLLMClient(LLMClient):
    def __init__(self, base_url: str = LLM_BASE_URL, model: str = LLM_MODEL):
        from openai import OpenAI
        self.client = OpenAI(base_url=base_url, api_key=LLM_API_KEY)
        self.model = model

    def complete(self, system: str, user: str, max_tokens: int = MAX_TOKENS,
                 temperature: float = TEMPERATURE, response_format: dict | None = None) -> tuple[str, int]:
        kwargs = dict(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if response_format is not None:
            kwargs["response_format"] = response_format
        response = self.client.chat.completions.create(**kwargs)
        text = response.choices[0].message.content or ""
        tokens = response.usage.total_tokens if response.usage else 0
        return text, tokens


def create_client(model: str | None = None, base_url: str | None = None) -> LLMClient:
    """Create an LLM client based on LLM_PROVIDER env var."""
    provider = LLM_PROVIDER.lower()
    if provider == "anthropic":
        return AnthropicClient(model=model or ANTHROPIC_MODEL)
    elif provider == "local":
        return LocalLLMClient(
            base_url=base_url or LLM_BASE_URL,
            model=model or LLM_MODEL,
        )
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider!r}. Use 'anthropic' or 'local'.")


# --- JSON Parsing ---

def extract_json_from_response(text: str) -> list | dict | None:
    """Try to parse JSON from LLM response, handling common issues."""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'```json\s*', '', text)
    text = re.sub(r'```\s*', '', text)
    text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


# --- Extraction ---

def run_extraction(platform: str, model: str, test_mode: bool = False,
                   base_url: str | None = None):
    """Run LLM extraction on preprocessed batches."""
    batches_dir = BATCHES_DIR / platform
    if not batches_dir.exists():
        print(f"  No batches found for {platform}. Run --preprocess first.")
        return

    if test_mode:
        model_label = model.replace("/", "_").replace(".", "_")
        results_dir = RESULTS_DIR / "ab_test" / model_label
    else:
        results_dir = RESULTS_DIR / platform

    results_dir.mkdir(parents=True, exist_ok=True)

    batch_files = sorted(batches_dir.glob("batch_*.json"))
    if test_mode:
        batch_files = batch_files[:TEST_BATCHES]

    client = create_client(model=model, base_url=base_url)
    use_schema = isinstance(client, LocalLLMClient)
    success = 0
    failures = 0

    for bf in tqdm(batch_files, desc=f"  {platform} extraction", unit="batch"):
        result_file = results_dir / bf.name
        if result_file.exists():
            success += 1
            continue

        with open(bf, "r", encoding="utf-8") as f:
            batch_data = json.load(f)

        threads = batch_data["threads"]
        threads_text = "\n\n".join(t["serialized_text"] for t in threads)
        user_prompt = EXTRACTION_PROMPT.format(
            platform=platform.title(),
            threads_text=threads_text,
        )

        start_time = time.time()
        try:
            raw_text, tokens_used = client.complete(
                system=SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=MAX_TOKENS,
                temperature=TEMPERATURE,
                response_format=EXTRACTION_SCHEMA if use_schema else None,
            )
            elapsed = time.time() - start_time

            parsed = extract_json_from_response(raw_text)
            if isinstance(parsed, dict) and "extractions" in parsed:
                parsed = parsed["extractions"]

            if parsed is None:
                raw_text, _ = client.complete(
                    system=SYSTEM_PROMPT,
                    user=user_prompt + "\n\nRespond with ONLY a JSON array. No other text.",
                    max_tokens=MAX_TOKENS,
                    temperature=0.1,
                )
                parsed = extract_json_from_response(raw_text)
                if isinstance(parsed, dict) and "extractions" in parsed:
                    parsed = parsed["extractions"]

            result = {
                "batch_id": batch_data["batch_id"],
                "platform": platform,
                "model": model,
                "elapsed_seconds": round(elapsed, 1),
                "tokens_used": tokens_used,
                "json_valid": parsed is not None,
                "raw_response": raw_text[:3000],
                "extractions": parsed if isinstance(parsed, list) else [],
                "thread_ids": [t["thread_id"] for t in threads],
                "thread_titles": [t["title"] for t in threads],
            }

            with open(result_file, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)

            if parsed is not None:
                success += 1
            else:
                failures += 1
                print(f"\n  Batch {batch_data['batch_id']}: JSON parse failed")

        except Exception as e:
            failures += 1
            print(f"\n  Batch {batch_data['batch_id']}: LLM error: {e}")

    print(f"\n  Results: {success} success, {failures} failures")


# --- Model Comparison ---

def compare_models():
    """Compare A/B test results between models."""
    ab_dir = RESULTS_DIR / "ab_test"
    if not ab_dir.exists():
        print("No A/B test results found. Run --extract --test with different models first.")
        return

    model_dirs = [d for d in ab_dir.iterdir() if d.is_dir()]
    if len(model_dirs) < 2:
        print(f"Only {len(model_dirs)} model(s) tested. Need at least 2 for comparison.")
        print(f"Found: {[d.name for d in model_dirs]}")
        return

    print("\n" + "=" * 70)
    print("  MODEL A/B COMPARISON")
    print("=" * 70)

    for model_dir in sorted(model_dirs):
        model_name = model_dir.name
        results = []
        for f in sorted(model_dir.glob("batch_*.json")):
            with open(f, "r", encoding="utf-8") as fh:
                results.append(json.load(fh))

        total_batches = len(results)
        json_valid = sum(1 for r in results if r.get("json_valid"))
        total_extractions = sum(len(r.get("extractions", [])) for r in results)
        avg_time = sum(r.get("elapsed_seconds", 0) for r in results) / max(total_batches, 1)
        avg_tokens = sum(r.get("tokens_used", 0) for r in results) / max(total_batches, 1)

        all_extractions = []
        for r in results:
            all_extractions.extend(r.get("extractions", []))

        severities = [e.get("severity", 0) for e in all_extractions if isinstance(e.get("severity"), (int, float))]
        categories = [e.get("category", "") for e in all_extractions]
        sentiments = [e.get("sentiment", "") for e in all_extractions]

        print(f"\n  Model: {model_name}")
        print(f"  {'─' * 50}")
        print(f"  Batches:          {total_batches}")
        print(f"  JSON valid:       {json_valid}/{total_batches} ({json_valid/max(total_batches,1)*100:.0f}%)")
        print(f"  Extractions:      {total_extractions}")
        print(f"  Avg time/batch:   {avg_time:.1f}s")
        print(f"  Avg tokens/batch: {avg_tokens:.0f}")
        if severities:
            print(f"  Avg severity:     {sum(severities)/len(severities):.1f}")
        print(f"  Categories used:  {len(set(categories))}")
        print(f"  Sentiments:       {dict(sorted(((s, sentiments.count(s)) for s in set(sentiments)), key=lambda x: -x[1]))}")

        print(f"\n  Sample extractions:")
        for i, (r, ext_list) in enumerate(zip(results[:2], [r.get("extractions", [])[:3] for r in results[:2]])):
            for j, ext in enumerate(ext_list):
                title = r.get("thread_titles", [""])[j] if j < len(r.get("thread_titles", [])) else "?"
                print(f"    [{ext.get('category', '?')}] sev={ext.get('severity', '?')} {ext.get('sentiment', '?')}")
                print(f"      Thread: {title[:60]}")
                print(f"      Need: {ext.get('need', '?')}")

    print(f"\n{'=' * 70}")
