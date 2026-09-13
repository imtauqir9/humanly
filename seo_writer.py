#!/usr/bin/env python3
"""
SEO Article Writer
==================
Generates a complete SEO article with web-sourced images for a given topic.

Mirrors the n8n "SEO Blog Writer Agent Technical Blog" workflow using Claude.

Usage:
    # With uv (no install needed):
    uv run --with anthropic --with requests seo_writer.py "Your Topic Here"
    uv run --with anthropic --with requests seo_writer.py "Your Topic Here" --intent "I want to explain to developers how ReAct agents work and why they're better than standard LLMs"
    uv run --with anthropic --with requests seo_writer.py "Your Topic Here" --keywords "kw1, kw2"

    # Or install deps first:
    pip install anthropic requests
    python seo_writer.py "Your Topic Here" --intent "natural language description of what you want" --output-dir ./articles

Environment Variables:
    ANTHROPIC_API_KEY   (required) Claude API key
    SERPAPI_KEY         (optional) SerpAPI key — enables live SERP data + Google Image search
                        Without it, Claude knowledge is used and Unsplash links are provided.
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import anthropic
import requests

# ---------------------------------------------------------------------------
# Load .env file if present (no python-dotenv required)
# ---------------------------------------------------------------------------

def _load_dotenv():
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        return
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

_load_dotenv()

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL = "claude-sonnet-5"

# Three roles argue about the article: the writer produces it, the auditor attacks
# it, the judge settles what they cannot. The point of the stage is decorrelated
# error, so the roles are resolved onto the most distinct weights the available
# keys allow, rather than being pinned to one vendor.
#
# The auditor matters more than the judge here. The judge only ever rules on
# findings the auditor already raised, so a blind spot shared between writer and
# auditor means the finding never exists to be argued about. Distinctness is
# therefore spent on the auditor first.

VERIFIER_MODEL = "claude-opus-5"    # Anthropic-side auditor: not the writer's weights
VERIFIER_EFFORT = "high"
JUDGE_MODEL = "claude-opus-5"
JUDGE_EFFORT = "high"

OPENAI_JUDGE_MODEL = os.getenv("OPENAI_JUDGE_MODEL", "gpt-5.5")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

# Per-role vendor override. "auto" picks the most distinct vendor that has a key.
#   auto | anthropic | openai | gemini
AUDITOR_PROVIDER = os.getenv("AUDITOR_PROVIDER", "auto").strip().lower()
JUDGE_PROVIDER = os.getenv("JUDGE_PROVIDER", "auto").strip().lower()

_PROVIDER_KEYS = {
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def available_providers() -> list[str]:
    """Vendors this machine actually holds a key for."""
    return [p for p, env in _PROVIDER_KEYS.items() if os.getenv(env)]


def _provider_model(provider: str, anthropic_model: str) -> str:
    if provider == "openai":
        return OPENAI_JUDGE_MODEL
    if provider == "gemini":
        return GEMINI_MODEL
    return anthropic_model


def resolve_agents() -> dict:
    """Assign writer, auditor and judge to the most distinct vendors available.

    The writer stays on Anthropic: the style prompts and sample-article matching
    were tuned against it, and swapping it changes the product rather than
    checking it. The other two are pushed off the writer's vendor, and off each
    other's, whenever a key exists to do so.
    """
    have = available_providers()

    def pick(override: str, avoid: list[list[str]], preference: list[str]) -> str:
        """avoid is tiered: the first list is the ideal, later lists relax it."""
        if override in _PROVIDER_KEYS:
            return override                      # explicit wins, key checked at call time
        for tier in avoid + [[]]:
            for p in preference:
                if p in have and p not in tier:
                    return p
        return "anthropic"

    auditor = pick(AUDITOR_PROVIDER, avoid=[["anthropic"]],
                   preference=["openai", "gemini", "anthropic"])
    # With only two vendors the judge has to reuse one. Reusing the writer's
    # vendor on a bigger model beats reusing the auditor's exact model, which
    # would have the judge rubber-stamp the finding it just made.
    judge = pick(JUDGE_PROVIDER, avoid=[["anthropic", auditor], [auditor]],
                 preference=["gemini", "openai", "anthropic"])

    return {
        "writer": {"provider": "anthropic", "model": MODEL, "effort": "low"},
        "auditor": {"provider": auditor,
                    "model": _provider_model(auditor, VERIFIER_MODEL),
                    "effort": VERIFIER_EFFORT},
        "judge": {"provider": judge,
                  "model": _provider_model(judge, JUDGE_MODEL),
                  "effort": JUDGE_EFFORT},
    }


def describe_agents(agents: dict) -> str:
    roles = " | ".join(f"{r}: {a['model']} ({a['provider']})" for r, a in agents.items())
    vendors = {a["provider"] for a in agents.values()}
    models = {a["model"] for a in agents.values()}
    return f"{roles}\n  {len(models)} distinct models across {len(vendors)} vendor(s)"


def judge_provider() -> str:
    """Which vendor rules on disputes, after resolving 'auto'. Kept for callers."""
    return resolve_agents()["judge"]["provider"]

# Publication identity. Used for the canonical URL, Open Graph tags and the
# Article/Person schema. Without SITE_URL the canonical and og:url are omitted
# rather than guessed - a wrong canonical is worse than none.
SITE_URL = os.getenv("SITE_URL", "").rstrip("/")
AUTHOR_NAME = os.getenv("AUTHOR_NAME", "Imran Tauqir")
AUTHOR_URL = os.getenv("AUTHOR_URL", "https://imrantauqir.com/")

# ---------------------------------------------------------------------------
# Token accounting
# ---------------------------------------------------------------------------
#
# A single article makes fifteen-plus calls across three vendors at two effort
# levels, and until now nothing counted them. Tokens are taken from what each
# API actually reports, never estimated. Cost is a second, softer layer: it is
# only as right as the table below, so an unpriced model still gets its tokens
# counted and simply reports no dollar figure rather than a wrong one.
#
# USD per million tokens, (input, output). The Anthropic rows are first-party
# list prices. VERIFY the OpenAI and Gemini rows against your provider's own
# pricing page before trusting the totals - override with MODEL_PRICES, a JSON
# object of {"model": [input, output]}.
MODEL_PRICES = {
    "claude-opus-5": (5.00, 25.00),
    "claude-sonnet-5": (2.00, 10.00),
    "claude-haiku-4-5": (1.00, 5.00),
    # ElevenLabs bills per character (one credit each). The Creator plan is
    # $22 for 100,000 credits: $0.22 per thousand, i.e. $220 per million
    # "input tokens" in this table. Override with MODEL_PRICES for another plan.
    "elevenlabs-tts": (220.0, 0.0),
}
try:
    MODEL_PRICES.update({k: tuple(v) for k, v in
                         json.loads(os.getenv("MODEL_PRICES", "{}")).items()})
except (ValueError, TypeError, AttributeError):
    print("Warning: MODEL_PRICES is not valid JSON; using built-in prices.")

# Anthropic bills a cache read at roughly a tenth of the input rate, and a cache
# write at roughly 1.25x. Close enough to be useful, flagged as approximate.
_CACHE_READ_MULTIPLIER = 0.10
_CACHE_WRITE_MULTIPLIER = 1.25

_USAGE_LOG: list[dict] = []
_CURRENT_STEP = "startup"


def _price(model: str, tokens_in: int, tokens_out: int,
           cache_read: int = 0, cache_write: int = 0) -> float | None:
    """Dollars for one call, or None when the model has no price on file."""
    rates = MODEL_PRICES.get(model)
    if not rates:
        return None
    rate_in, rate_out = rates
    billable_in = tokens_in + cache_read * _CACHE_READ_MULTIPLIER \
        + cache_write * _CACHE_WRITE_MULTIPLIER
    return (billable_in * rate_in + tokens_out * rate_out) / 1_000_000


def record_usage(provider: str, model: str, tokens_in: int, tokens_out: int,
                 cache_read: int = 0, cache_write: int = 0):
    """Append one call to the ledger. Called by every vendor wrapper."""
    entry = {
        "step": _CURRENT_STEP,
        "provider": provider,
        "model": model,
        "input_tokens": int(tokens_in or 0),
        "output_tokens": int(tokens_out or 0),
        "cache_read_tokens": int(cache_read or 0),
        "cache_write_tokens": int(cache_write or 0),
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
    entry["cost_usd"] = _price(model, entry["input_tokens"], entry["output_tokens"],
                               entry["cache_read_tokens"], entry["cache_write_tokens"])
    _USAGE_LOG.append(entry)


def reset_usage():
    _USAGE_LOG.clear()


def usage_summary() -> dict:
    """Totals overall, per model, and per pipeline step."""
    def blank():
        return {"calls": 0, "input_tokens": 0, "output_tokens": 0,
                "cache_read_tokens": 0, "cost_usd": 0.0, "priced": True}

    total, by_model, by_step = blank(), {}, {}
    for e in _USAGE_LOG:
        for bucket in (total,
                       by_model.setdefault(e["model"], blank()),
                       by_step.setdefault(e["step"], blank())):
            bucket["calls"] += 1
            bucket["input_tokens"] += e["input_tokens"]
            bucket["output_tokens"] += e["output_tokens"]
            bucket["cache_read_tokens"] += e["cache_read_tokens"]
            if e["cost_usd"] is None:
                bucket["priced"] = False
            else:
                bucket["cost_usd"] += e["cost_usd"]

    total["total_tokens"] = total["input_tokens"] + total["output_tokens"]
    return {"total": total, "by_model": by_model, "by_step": by_step,
            "calls": list(_USAGE_LOG)}


def print_usage_summary(summary: dict | None = None):
    summary = summary or usage_summary()
    t = summary["total"]
    if not t["calls"]:
        return
    print(f"\n  Tokens: {t['input_tokens']:,} in + {t['output_tokens']:,} out "
          f"= {t['total_tokens']:,} across {t['calls']} calls")
    for model, m in sorted(summary["by_model"].items(),
                           key=lambda kv: -kv[1]["output_tokens"]):
        cost = f"${m['cost_usd']:.3f}" if m["priced"] else "unpriced"
        print(f"    {model:<20} {m['calls']:>3} calls  "
              f"{m['input_tokens']:>8,} in  {m['output_tokens']:>7,} out  {cost}")
    if t["priced"]:
        print(f"  Estimated cost: ${t['cost_usd']:.2f}")
    else:
        print(f"  Estimated cost: ${t['cost_usd']:.2f} plus unpriced models "
              f"(add them to MODEL_PRICES for a complete figure)")


def write_usage(slug: str, output_dir: Path, title: str = "") -> Path:
    """Save this run's ledger, and append one line to the rolling usage log."""
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = usage_summary()
    path = output_dir / f"{slug}_usage.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    t = summary["total"]
    line = {
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "slug": slug, "title": title,
        "calls": t["calls"], "input_tokens": t["input_tokens"],
        "output_tokens": t["output_tokens"], "total_tokens": t["total_tokens"],
        "cost_usd": round(t["cost_usd"], 4), "fully_priced": t["priced"],
        "by_model": {m: {"calls": v["calls"],
                         "input_tokens": v["input_tokens"],
                         "output_tokens": v["output_tokens"],
                         "cost_usd": round(v["cost_usd"], 4)}
                     for m, v in summary["by_model"].items()},
    }
    with open(output_dir / "usage.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(line) + "\n")
    return path


# ---------------------------------------------------------------------------
# Article length
# ---------------------------------------------------------------------------
#
# Word count is not one instruction, it is a shape. Telling the writer "1,000
# words" while the outline still demands seven sections, eight images and five
# FAQ questions produces a thin, cramped article rather than a short one, so
# every structural number moves together.

LENGTH_PROFILES = {
    "default": {
        "label": "Default (2,500-3,500 words)",
        "words": "2,500-3,500",
        "sections": "5-7", "subsections": "2-3", "images": "6-8", "faq": "4-5",
        "intro": "150-200", "conclusion": "150-200",
    },
    "2000": {
        "label": "Medium (about 2,000 words)",
        "words": "1,800-2,200",
        "sections": "4-6", "subsections": "2", "images": "4-5", "faq": "4",
        "intro": "120-150", "conclusion": "120-150",
    },
    "1000": {
        "label": "Short (about 1,000 words)",
        "words": "900-1,100",
        "sections": "3-4", "subsections": "1-2", "images": "2-3", "faq": "3",
        "intro": "80-110", "conclusion": "80-110",
    },
}


def length_profile(name: str | None) -> dict:
    """Resolve a --words value to a profile, falling back to the default."""
    return LENGTH_PROFILES.get(str(name or "default").strip().lower(),
                               LENGTH_PROFILES["default"])


SERPAPI_BASE = "https://serpapi.com/search.json"
UNSPLASH_BASE = "https://unsplash.com/s/photos"

client = anthropic.Anthropic()

# ---------------------------------------------------------------------------
# Author branding blocks (prepended / appended to every article)
# ---------------------------------------------------------------------------

AUTHOR_INTRO_TEMPLATE = """\
👋 Hi everyone, Imran here.
Welcome to Edition #{edition} of a newsletter that people around the world actually look forward to reading.
"""

AUTHOR_CTA = """\

---

That's a wrap for this edition. If it gave you something useful, the best next step is to try one idea for real this week.

**Let's connect.** 👉 I share what I'm building and learning with AI agents on [LinkedIn](https://www.linkedin.com/in/imrantauqir/) — come say hi, and see my work in my portfolio at [imrantauqir.com](https://imrantauqir.com/).

Until next time,
**Imran**
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:80]


CONSOLE_LIMITS_URL = "https://console.anthropic.com/settings/limits"


class ClaudeError(RuntimeError):
    """An Anthropic API failure, already phrased for a human to read."""


def _api_message(e: "anthropic.APIStatusError") -> str:
    """The API's own error sentence.

    Prefer the parsed body over e.message, which the SDK builds as
    "Error code: 400 - {'type': 'error', ...}" — the whole payload repr.
    """
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        message = (body.get("error") or {}).get("message")
        if message:
            return str(message)
    return e.message


def call_claude(prompt: str, system: str = "", max_tokens: int = 16000,
                model: str = MODEL, effort: str = "low") -> str:
    messages = [{"role": "user", "content": prompt}]
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": messages,
        # Sonnet 5 runs adaptive thinking when `thinking` is omitted, so state it
        # explicitly. Low effort keeps the token cost close to the old no-thinking
        # behaviour while still buying Sonnet 5's better planning.
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": effort},
    }
    if system:
        kwargs["system"] = system
    try:
        response = client.messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        # The spend cap set in the Console arrives as a 400, not a 429, and the
        # SDK does not retry it — surface the reset date the API gives us.
        message = _api_message(e)
        if "usage limit" in message.lower():
            raise ClaudeError(
                f"Anthropic API usage limit reached. {message} "
                f"Raise or remove the cap here: {CONSOLE_LIMITS_URL}"
            ) from e
        raise ClaudeError(f"Anthropic rejected the request: {message}") from e
    except anthropic.AuthenticationError as e:
        raise ClaudeError(
            "Anthropic rejected the API key. Check that ANTHROPIC_API_KEY is set "
            f"to a current, un-revoked key. ({_api_message(e)})"
        ) from e
    except anthropic.PermissionDeniedError as e:
        detail = (
            "This usually means the account is out of credits."
            if e.type == "billing_error"
            else f"The key may lack access to {model}."
        )
        raise ClaudeError(
            f"Anthropic denied the request. {detail} ({_api_message(e)})"
        ) from e
    except anthropic.RateLimitError as e:
        # The SDK already retried this twice, so it is not a momentary spike.
        raise ClaudeError(
            f"Anthropic rate limit hit and retries were exhausted. Wait a minute "
            f"and run again. ({_api_message(e)})"
        ) from e
    except anthropic.APIStatusError as e:
        raise ClaudeError(
            f"Anthropic returned an error (HTTP {e.status_code}): {_api_message(e)}"
        ) from e
    except anthropic.APIConnectionError as e:
        raise ClaudeError(
            f"Could not reach the Anthropic API. Check your network connection. ({e})"
        ) from e

    u = getattr(response, "usage", None)
    if u is not None:
        record_usage("anthropic", model,
                     getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0),
                     getattr(u, "cache_read_input_tokens", 0) or 0,
                     getattr(u, "cache_creation_input_tokens", 0) or 0)

    if response.stop_reason == "refusal":
        raise ClaudeError(
            "Claude declined to answer this prompt for safety reasons. "
            "Try rephrasing the topic."
        )

    # With thinking enabled, content[0] is a thinking block — pick the text block
    # out rather than indexing blindly.
    text = next((b.text for b in response.content if b.type == "text"), None)

    # A response cut off at the cap used to be returned as if it were complete
    # whenever it had any text at all. Half a JSON object then failed further
    # down with a misleading error about the model "answering in prose". Thinking
    # tokens count toward this cap, so a high-effort step reaches it sooner than
    # its output length suggests.
    if response.stop_reason == "max_tokens":
        written = len((text or "").split())
        raise ClaudeError(
            f"{model} hit the {max_tokens:,}-token output cap and its answer was "
            f"cut off after about {written} words. Thinking tokens count toward "
            f"that cap, so raise max_tokens for this step or lower its effort."
        )

    if text is None or not text.strip():
        raise ClaudeError(
            f"Claude returned no text (stop_reason: {response.stop_reason})."
        )
    return text.strip()


def call_openai(prompt: str, system: str = "", max_tokens: int = 4000) -> str:
    """Second-vendor call, used only for judging disputes."""
    try:
        from openai import OpenAI
    except ImportError as e:
        raise ClaudeError(
            "JUDGE_PROVIDER is openai but the openai package is not installed. "
            "Run: pip install openai"
        ) from e

    if not os.getenv("OPENAI_API_KEY"):
        raise ClaudeError(
            "JUDGE_PROVIDER is openai but OPENAI_API_KEY is not set. Add it to .env, "
            "or set JUDGE_PROVIDER=anthropic to keep the Claude judge."
        )

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        response = OpenAI().chat.completions.create(
            model=OPENAI_JUDGE_MODEL,
            messages=messages,
            max_completion_tokens=max_tokens,
        )
    except Exception as e:
        raise ClaudeError(
            f"The OpenAI judge failed ({type(e).__name__}: {e}). If the model name is "
            f"wrong, set OPENAI_JUDGE_MODEL to one your key can reach "
            f"(currently '{OPENAI_JUDGE_MODEL}'), or set JUDGE_PROVIDER=anthropic."
        ) from e

    u = getattr(response, "usage", None)
    if u is not None:
        record_usage("openai", OPENAI_JUDGE_MODEL,
                     getattr(u, "prompt_tokens", 0), getattr(u, "completion_tokens", 0))

    text = (response.choices[0].message.content or "").strip()
    if not text:
        raise ClaudeError(f"The OpenAI judge returned no text (model: {OPENAI_JUDGE_MODEL}).")
    return text


def call_gemini(prompt: str, system: str = "", max_tokens: int = 4000) -> str:
    """Third-vendor call, used for the auditor or judge when a Gemini key is set."""
    try:
        from google import genai
        from google.genai import types
    except ImportError as e:
        raise ClaudeError(
            "A role is set to gemini but the google-genai package is not installed. "
            "Run: pip install google-genai"
        ) from e

    if not os.getenv("GEMINI_API_KEY"):
        raise ClaudeError(
            "A role is set to gemini but GEMINI_API_KEY is not set. Add it to .env, "
            "or set the role's provider to anthropic or openai."
        )

    config = {"max_output_tokens": max_tokens}
    if system:
        config["system_instruction"] = system

    try:
        response = genai.Client(api_key=os.getenv("GEMINI_API_KEY")).models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(**config),
        )
    except Exception as e:
        raise ClaudeError(
            f"The Gemini call failed ({type(e).__name__}: {e}). If the model name is "
            f"wrong, set GEMINI_MODEL to one your key can reach (currently "
            f"'{GEMINI_MODEL}'), or set the role's provider to anthropic."
        ) from e

    u = getattr(response, "usage_metadata", None)
    if u is not None:
        record_usage("gemini", GEMINI_MODEL,
                     getattr(u, "prompt_token_count", 0) or 0,
                     getattr(u, "candidates_token_count", 0) or 0,
                     getattr(u, "cached_content_token_count", 0) or 0)

    text = (getattr(response, "text", "") or "").strip()
    if not text:
        raise ClaudeError(f"Gemini returned no text (model: {GEMINI_MODEL}).")
    return text


def call_agent(role: dict, prompt: str, system: str = "", max_tokens: int = 4000,
               agents: dict | None = None) -> str:
    """Run one role on its assigned vendor, falling back to Claude if that vendor is down.

    A vendor outage must not destroy an article that already cost a dozen calls,
    so the fallback is unconditional - but it is announced, because an article
    audited by the writer's own family is a weaker article than the roster claims.
    """
    provider = role["provider"]

    if provider != "anthropic":
        caller = call_openai if provider == "openai" else call_gemini
        try:
            return caller(prompt, system=system, max_tokens=max_tokens)
        except ClaudeError as e:
            reason = " ".join(str(e).split())[:160]
            print(f"  {provider} unavailable, falling back to {JUDGE_MODEL}.")
            print(f"    {reason}")
            return call_claude(prompt, system=system, max_tokens=max_tokens,
                               model=JUDGE_MODEL, effort=role.get("effort", "high"))

    return call_claude(prompt, system=system, max_tokens=max_tokens,
                       model=role["model"], effort=role.get("effort", "high"))


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a model response.

    Eight call sites depend on this, and the responses now come from three
    vendors with different habits: fenced blocks, a sentence of preamble, a
    trailing note. A ValueError escaping here used to crash the pipeline with a
    bare traceback, so every failure now raises ClaudeError carrying the text
    that could not be parsed.
    """
    raw = (text or "").strip()

    # ```json ... ``` fences, which some models add and others never do.
    fenced = re.search(r"```(?:json)?\s*(.+?)```", raw, re.DOTALL)
    candidates = [fenced.group(1).strip()] if fenced else []
    candidates.append(raw)

    # Greedy: the outermost braces. Non-greedy: the first complete-looking
    # object, which survives a trailing "Let me know if..." with a brace in it.
    for pattern in (r"\{.*\}", r"\{.*?\}"):
        for source in list(candidates):
            match = re.search(pattern, source, re.DOTALL)
            if match:
                candidates.append(match.group())

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return parsed

    preview = " ".join(raw.split())[:300] or "(the response was empty)"
    raise ClaudeError(
        f"A model returned something that is not JSON, where JSON was required. "
        f"This usually means the model answered in prose. It said: {preview}"
    )


def log(step: str, msg: str = ""):
    # The ledger attributes each call to whichever step was last announced, so
    # the dashboard can say which stage of the pipeline spent the tokens.
    global _CURRENT_STEP
    _CURRENT_STEP = step
    print(f"\n[{step}] {msg}" if msg else f"\n[{step}]", flush=True)


# ---------------------------------------------------------------------------
# Intent → Search Query
# ---------------------------------------------------------------------------

def extract_search_query(topic: str, intent: str) -> str:
    """
    Use Claude to convert a natural language intent description into the best
    2–4 word search query for SerpAPI and keyword targeting.
    Returns a short keyword string.
    """
    prompt = f"""You are an SEO keyword research expert.

A writer wants to publish an article on this topic: "{topic}"

Their intent / what they want to achieve:
"{intent}"

Extract the single best search query (2–4 words) that:
1. Captures the core topic for Google search
2. Reflects the angle described in the intent
3. Has high search volume potential

Return ONLY the search query string — no explanation, no quotes, no punctuation."""

    return call_claude(prompt, max_tokens=2000).strip().strip('"').strip("'")


# ---------------------------------------------------------------------------
# Step 1: SERP Research
# ---------------------------------------------------------------------------

def serp_research(title: str, keywords: str, intent: str = "") -> dict:
    log("STEP 1", f"SERP Research for: {keywords}")

    serp_context = ""
    serpapi_key = os.getenv("SERPAPI_KEY")
    if serpapi_key:
        try:
            resp = requests.get(SERPAPI_BASE, params={
                "q": keywords, "num": 5, "api_key": serpapi_key
            }, timeout=15)
            resp.raise_for_status()
            results = resp.json().get("organic_results", [])
            snippets = "\n".join(
                f"- {r.get('title','')}: {r.get('snippet','')}"
                for r in results[:5]
            )
            serp_context = f"\nLive SERP results for '{keywords}':\n{snippets}\n"
            print("  Using live SerpAPI data.")
        except Exception as e:
            print(f"  SerpAPI error ({e}), falling back to Claude knowledge.")

    intent_context = f"\nWriter's intent: {intent}\n" if intent else ""

    prompt = f"""Analyze the topic and keyword below, then return a JSON object with research insights.

Title: {title}
Primary Keyword: {keywords}
{intent_context}{serp_context}

Return ONLY valid JSON, no extra text:
{{
  "search_intent": "<informational | transactional | navigational | commercial>",
  "writing_style": "<e.g. engaging and storytelling | data-driven and technical | etc.>",
  "writing_tone": "<e.g. friendly and conversational | formal and authoritative | etc.>",
  "hidden_insight": "<a unique angle or insight not covered by most articles, or 'No significant insights detected'>",
  "target_audience": "<who this article is for>",
  "article_goal": "<main objective of the article>",
  "semantic_analysis": {{
    "common_subtopics": ["<subtopic 1>", "<subtopic 2>", "<subtopic 3>", "<subtopic 4>"],
    "related_questions": ["<question 1>", "<question 2>", "<question 3>"]
  }},
  "keywords": {{
    "primary_keyword": "<main focus keyword>",
    "secondary_keywords": ["<kw 1>", "<kw 2>", "<kw 3>"],
    "semantic_keywords": ["<kw 1>", "<kw 2>", "<kw 3>"],
    "long_tail_keywords": ["<kw 1>", "<kw 2>", "<kw 3>"]
  }}
}}"""

    response = call_claude(prompt)
    result = extract_json(response)
    # Kept so the Step 6.5 auditor can check the article against what actually
    # ranks, not just against Claude's summary of it.
    result["serp_context"] = serp_context.strip()
    print("  Research complete.")
    return result


# ---------------------------------------------------------------------------
# Date context, style samples, the author's take
# ---------------------------------------------------------------------------
#
# Three things the earlier articles were missing, each for a plain reason:
#
#   * Dates. Nothing told the model what day it was, so a September 2026 article
#     said "in 2025" nine times and cited a projection that had already landed.
#   * Style. The README promised sample-article matching; no code loaded the
#     samples. The writer had a tone note and nothing else to imitate.
#   * A point of view. There was no input for what the author actually thinks,
#     so the output was a competent summary of what everyone else had written.

TODAY = datetime.now()
CURRENT_YEAR = TODAY.year


def date_context() -> str:
    return (
        f"Today's date is {TODAY.strftime('%B %d, %Y')}. Write for a reader in "
        f"{CURRENT_YEAR}: never describe {CURRENT_YEAR} as upcoming, never present "
        f"{CURRENT_YEAR - 1} as the current year, and never cite a projection for a "
        f"year that has already ended as if it were still a forecast. If a source "
        f"is dated, say when it is from."
    )


SAMPLE_DIR = Path(__file__).parent / "sample-articles"
STYLE_SAMPLE_WORDS = 1200
STYLE_SAMPLE_COUNT = 2


def _docx_text(path: Path) -> str:
    try:
        from docx import Document
    except ImportError:
        return ""
    try:
        doc = Document(str(path))
    except Exception:
        return ""
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


_BOILERPLATE_MARKS = ("hi everyone", "welcome to edition", "newsletter", "bootcamp",
                      "playlist on youtube", "up skill", "thanks for being part",
                      "join the next cohort")


def _strip_sample_boilerplate(text: str) -> str:
    """Drop the newsletter greeting and promo lines that open a published
    issue. They are not the author's prose, and a name in them is not the
    author's name."""
    lines = text.split("\n")
    # The greeting, the pitch and the promo links can be interleaved with a
    # paragraph that matches nothing, so cut to the last marked line in the
    # opening block rather than stopping at the first clean one.
    head = lines[:12]
    last_hit = max((i for i, l in enumerate(head)
                    if any(m in l.lower() for m in _BOILERPLATE_MARKS)), default=-1)
    lines = lines[last_hit + 1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines)


def load_style_samples(limit_words: int = STYLE_SAMPLE_WORDS,
                       count: int = STYLE_SAMPLE_COUNT) -> str:
    """The opening of up to `count` articles from sample-articles/, as a style
    exemplar block. Newest files first, so the author's current voice wins."""
    if not SAMPLE_DIR.exists():
        return ""
    files = sorted(
        [p for p in SAMPLE_DIR.iterdir()
         if p.suffix.lower() in {".md", ".txt", ".docx"} and not p.name.startswith("~$")],
        key=lambda p: p.stat().st_mtime, reverse=True,
    )[:count]
    blocks = []
    for p in files:
        text = _docx_text(p) if p.suffix.lower() == ".docx" else p.read_text(
            encoding="utf-8", errors="ignore")
        words = _strip_sample_boilerplate(text).split()
        if len(words) < 150:
            continue
        excerpt = " ".join(words[:limit_words])
        blocks.append(f"--- Sample: {p.stem[:80]} ---\n{excerpt}\n")
    if not blocks:
        return ""
    print(f"  Style samples loaded: {len(blocks)} file(s) from {SAMPLE_DIR.name}/")
    return "\n".join(blocks)


def style_block(samples: str, profile: str = "") -> str:
    parts = []
    if samples:
        parts.append(f"""
STYLE TO MATCH
Below are excerpts from articles this author actually published. Match their
sentence rhythm, their level of directness, how they open sections, and how
often they use first person. Do not copy sentences or facts from them.
{samples}
""")
    parts.append(voice_block(profile))
    return "".join(parts)


def take_block(take: str) -> str:
    """The author's own positions, formatted for the prompts that must honour them."""
    if not take or not take.strip():
        return ""
    items = [ln.strip(" -*•\t") for ln in take.strip().splitlines() if ln.strip()]
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(items, 1))
    return f"""
AUTHOR'S TAKE (mandatory)
These are the author's own positions and experiences. They are what makes this
article theirs rather than a summary of what everyone else wrote.
{numbered}
Rules: every item must appear in the article, in first person, in the section
where it belongs, with its substance intact. Do not soften an opinion into a
neutral observation. Do not quarantine them in one "my view" section; put each
where a reader would want to hear it. First person is the point, not a hedge:
"I think the X track is underrated" is correct; "The X track is underrated" is
the neutralised form that fails this rule.
"""


def library_links(output_dir: Path, exclude_title: str = "", limit: int = 12) -> list[dict]:
    """Articles already published, as {title, url}, for the outline to link to.
    Needs SITE_URL: without a site there is nothing to link to, and the writer
    is told to plan no internal links rather than invent anchors."""
    if not SITE_URL or not output_dir.exists():
        return []
    links = []
    for meta_file in sorted(output_dir.glob("*_meta.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
        except Exception:
            continue
        slug = meta_file.stem[:-len("_meta")]
        title_ = (meta.get("seo_meta") or {}).get("title") or slug.replace("-", " ")
        if exclude_title and title_.strip().lower() == exclude_title.strip().lower():
            continue
        links.append({"title": title_, "url": f"{SITE_URL}/{slug}"})
        if len(links) >= limit:
            break
    return links


def internal_links_block(links: list[dict]) -> str:
    if not links:
        return """
INTERNAL LINKS
There are no published articles to link to. Plan no internal links and write
none: never invent an anchor, and never link to "#".
"""
    rows = "\n".join(f"- {l['title']} | {l['url']}" for l in links)
    return f"""
INTERNAL LINKS (the only pages that exist; link to nothing else internally)
{rows}
Link to one of these only where a reader would genuinely want the detour, with
the exact URL. Never write a link whose target is "#".
"""


def strip_placeholder_links(article: str) -> str:
    """[text](#) and [text](#anchor) become plain text. The writer used to
    render the outline's "internal linking opportunities" as dead anchors."""
    cleaned = re.sub(r"\[([^\]]+)\]\(#[^)]*\)", r"\1", article)
    n = len(re.findall(r"\]\(#[^)]*\)", article))
    if n:
        print(f"  Placeholder links removed: {n}")
    return cleaned


def read_take(value: str | None) -> str:
    """--take accepts inline text, or a path to a text file."""
    if not value:
        return ""
    p = Path(value)
    if p.exists() and p.is_file():
        return p.read_text(encoding="utf-8", errors="ignore")
    return value


# ---------------------------------------------------------------------------
# The author's voice, described
# ---------------------------------------------------------------------------
#
# Style samples show the model what the prose looks like; they do not say what
# makes it that way, and only the writer sees them. A short description of the
# voice - how sentences run, how the reader is addressed, what the author never
# does - is built once from the samples, cached beside them, and sent to every
# call that touches the prose, so the humanizer and the fix pass pull in the
# same direction as the writer instead of sanding the voice back off.

VOICE_PROFILE_PATH = SAMPLE_DIR / ".voice_profile.json"   # run() moves this into the output dir


def _voice_stats(samples: str) -> dict:
    """Numbers the profile is anchored to, so it is not just adjectives."""
    lengths = _sentence_lengths(samples.split("\n"))
    if not lengths:
        return {}
    words = max(1, len(samples.split()))
    return {
        "median_sentence_words": sorted(lengths)[len(lengths) // 2],
        "share_under_10_words": round(sum(1 for n in lengths if n <= 10) / len(lengths), 2),
        "share_over_25_words": round(sum(1 for n in lengths if n >= 25) / len(lengths), 2),
        "you_per_100_words": round(100 * len(re.findall(r"\b[Yy]ou(?:r|'ll|'re)?\b", samples)) / words, 1),
        "i_per_100_words": round(100 * len(re.findall(r"\b(?:I|I'm|I've|I'd|[Mm]y)\b", samples)) / words, 1),
    }


def build_voice_profile(samples: str) -> str:
    """One Claude call describing how the author writes. Cached next to the
    samples and rebuilt only when they change."""
    if not samples or not samples.strip():
        return ""
    import hashlib
    key = hashlib.sha256(samples.encode("utf-8")).hexdigest()[:16]
    try:
        cached = json.loads(VOICE_PROFILE_PATH.read_text(encoding="utf-8"))
        if cached.get("key") == key and cached.get("profile"):
            print("  Voice profile: loaded from cache.")
            return cached["profile"]
    except Exception:
        pass
    stats = _voice_stats(samples)
    prompt = f"""Read these excerpts from one author's published articles and describe their
voice precisely enough that a ghostwriter could reproduce it.

{samples}

MEASURED ON THE EXCERPTS
{json.dumps(stats)}

Ignore any newsletter greeting, edition number or promotional boilerplate at the
top of an excerpt; describe the body prose only.

Write 120-180 words as instructions to the ghostwriter. Cover: sentence rhythm
(typical length, how often a very short sentence lands); how the reader is
addressed; how a new idea is introduced; how technical terms are handled; how
first person is used; how much hedging there is; and three things this author
never does. Quote two short phrases from the excerpts that are unmistakably
theirs. Plain prose, no headings, no bullets."""
    try:
        profile = call_claude(prompt, max_tokens=1500).strip()
    except ClaudeError as e:
        print(f"  Voice profile skipped ({str(e)[:80]}).")
        return ""
    if len(profile.split()) < 40:
        return ""
    try:
        VOICE_PROFILE_PATH.write_text(
            json.dumps({"key": key, "stats": stats, "profile": profile}, indent=2),
            encoding="utf-8")
    except Exception:
        pass
    print("  Voice profile: built and cached.")
    return profile


def voice_block(profile: str) -> str:
    if not profile or not profile.strip():
        return ""
    return f"""
THE AUTHOR'S VOICE (write in it; the editor and the auditor check for it)
{profile.strip()}
One exception: if this profile says first person is rare, the AUTHOR'S TAKE items
are still written in first person. "I think X" and "in my experience" on a take
item are the required form, not hedges; do not flatten them into third person.
"""


# ---------------------------------------------------------------------------
# Teach in layers: the simple version first, then up a level
# ---------------------------------------------------------------------------
#
# The shipped articles were flat: every section pitched at the same reader,
# which is nobody. An instructor does it differently - the plain version first,
# with a picture, so a newcomer leaves knowing what the thing is; then the
# mechanics for people who will build it; then the part only experience
# teaches. The outline, the writer and the auditor all hold to this shape.

LEVELS_BLOCK = """
TEACH IN LAYERS (mandatory shape)
The article climbs three levels, in this order. Every H2 belongs to one of them.

LEVEL 1 - The simple version. The first H2 after the introduction. A good
  instructor explaining it to a smart person who has never met the topic: one
  everyday analogy, one concrete example, every term of art defined in plain
  words the first time it appears, sentences mostly under 15 words. It holds
  exactly one diagram marker:
  [DIAGRAM: <title> | Shows: <the one thing the picture must make obvious>]
LEVEL 2 - How it actually works. The middle H2s, for a practitioner: the moving
  parts, the numbers, the comparison table, the tradeoffs. Technical terms are
  fine here, and the fact pack does the talking.
LEVEL 3 - Where it gets hard. The last H2 before the FAQ. What experienced
  people argue about, where it breaks, what the author has seen first-hand.
  Most of the AUTHOR'S TAKE belongs here.

A reader who stops after Level 1 should still know what the thing is. A reader
who finishes should learn something a beginner's guide would never say.
"""

EXPLAINER_MAX_MEAN = 17        # words per sentence, averaged over the Level 1 section
EXPLAINER_MAX_SENTENCE = 30    # no single sentence longer than this


def explainer_section(article: str) -> tuple[str, str] | None:
    """(heading, body) of the Level 1 section: the H2 that holds the first
    diagram marker. Returns None when the article has no such section."""
    lines = article.split("\n")
    marker_at = next((i for i, l in enumerate(lines)
                      if l.lstrip().startswith("[DIAGRAM:")), None)
    if marker_at is None:
        return None
    start = next((i for i in range(marker_at, -1, -1) if lines[i].startswith("## ")), None)
    if start is None:
        return None
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")),
               len(lines))
    return lines[start][3:].strip(), "\n".join(lines[start + 1:end])


def check_explainer(article: str) -> dict:
    """Is the Level 1 section actually simple? Measured, not asked."""
    found = explainer_section(article)
    if not found:
        return {"found": False, "ok": True}
    heading, body = found
    lengths = _sentence_lengths(_scannable_lines(body))
    if not lengths:
        return {"found": True, "ok": True, "heading": heading}
    mean = sum(lengths) / len(lengths)
    long_count = sum(1 for n in lengths if n > EXPLAINER_MAX_SENTENCE)
    return {
        "found": True, "heading": heading, "sentences": len(lengths),
        "mean": round(mean, 1), "longest": max(lengths), "long_count": long_count,
        "ok": mean <= EXPLAINER_MAX_MEAN and long_count == 0,
    }


def simplify_explainer(article: str, stats: dict, research: dict | None = None) -> str:
    """Rewrite only the Level 1 section so it reads like an instructor talking."""
    heading = stats["heading"]
    log("STEP 6.2", f"Simplifying the Level 1 section: {stats['mean']} words per sentence, "
                    f"{stats['long_count']} over {EXPLAINER_MAX_SENTENCE}")
    prompt = f"""The section "## {heading}" is the article's simple version: the part a smart
beginner reads first. Its sentences average {stats['mean']} words and {stats['long_count']}
run past {EXPLAINER_MAX_SENTENCE}. Rewrite ONLY that section so an instructor could read it
aloud to a newcomer: sentences mostly under 15 words and none over {EXPLAINER_MAX_SENTENCE},
one idea per sentence, every technical term explained in plain words the first time it
appears, the analogy and the example kept.
{voice_block((research or {}).get("voice_profile", ""))}
Change nothing outside that section. Keep its heading, its [DIAGRAM: ...] marker, every
"(Source: ...)" citation and every number exactly as they are.

ARTICLE
{article}

Return ONLY the full revised article."""
    return call_claude(prompt, max_tokens=16000)


# ---------------------------------------------------------------------------
# Diagrams: drawn by the pipeline, not searched for
# ---------------------------------------------------------------------------
#
# A stock photo next to "the simple version" explains nothing. The writer
# leaves one [DIAGRAM: title | Shows: ...] marker in that section; Claude turns
# it into a small structured spec - boxes and arrows, a cycle, stacked layers or
# side-by-side columns, never free-form drawing - and one layout is emitted
# twice: SVG inline in the HTML, PNG for the Markdown and the DOCX. No browser,
# no cairo, no fonts to install: Pillow ships a scalable face of its own.

DIAGRAM_MARKER_RE = re.compile(
    r"\[DIAGRAM:\s*([^|\]]+?)\s*\|\s*Shows:\s*([^\]]+?)\s*\]", re.IGNORECASE)
DIAGRAM_MAX_NODES = 8

DIAGRAM_SPEC_SCHEMA = """{
  "type": "flow | cycle | layers | compare",
  "title": "<what the diagram is called, under 60 characters>",
  "nodes": [ {"label": "<2-5 words>", "note": "<optional detail, under 12 words>"} ],
  "edges": [ {"from": 0, "to": 2, "label": "<optional, under 4 words>"} ],
  "columns": [ {"title": "<column title>", "items": ["<under 8 words>", "..."]} ],
  "caption": "<the one sentence a reader should take away, under 20 words>"
}"""


def _section_around(content: str, pos: int) -> str:
    """The section text a marker sits in: from the nearest heading above it to
    the next H2 below."""
    before, after = content[:pos], content[pos:]
    start = max(before.rfind("\n## "), before.rfind("\n### "), 0)
    end = after.find("\n## ")
    return (before[start:] + (after if end < 0 else after[:end])).strip()


def _clean_diagram_spec(spec: dict) -> dict | None:
    if not isinstance(spec, dict):
        return None
    kind = str(spec.get("type", "flow")).strip().lower()
    if kind not in {"flow", "cycle", "layers", "compare"}:
        kind = "flow"
    out = {
        "type": kind,
        "title": " ".join(str(spec.get("title", "")).split())[:70],
        "caption": " ".join(str(spec.get("caption", "") or "").split())[:160],
        "nodes": [], "edges": [], "columns": [],
    }
    if kind == "compare":
        for c in (spec.get("columns") or [])[:3]:
            if not isinstance(c, dict):
                continue
            title = " ".join(str(c.get("title", "")).split())[:40]
            items = [" ".join(str(i).split())[:60]
                     for i in (c.get("items") or []) if str(i).strip()][:5]
            if title and items:
                out["columns"].append({"title": title, "items": items})
        return out if len(out["columns"]) >= 2 else None
    for n in (spec.get("nodes") or [])[:DIAGRAM_MAX_NODES]:
        if isinstance(n, str):
            n = {"label": n}
        if not isinstance(n, dict):
            continue
        label = " ".join(str(n.get("label", "")).split())[:40]
        if label:
            out["nodes"].append({"label": label,
                                 "note": " ".join(str(n.get("note", "") or "").split())[:70]})
    if len(out["nodes"]) < 2:
        return None
    count = len(out["nodes"])
    for e in (spec.get("edges") or []):
        try:
            a, b = int(e.get("from")), int(e.get("to"))
        except Exception:
            continue
        if 0 <= a < count and 0 <= b < count and a != b:
            out["edges"].append({"from": a, "to": b,
                                 "label": " ".join(str(e.get("label", "") or "").split())[:24]})
    return out


def generate_diagram_spec(title: str, shows: str, section_text: str) -> dict | None:
    prompt = f"""Design a simple explanatory diagram for an article section.

DIAGRAM TITLE: {title}
IT MUST MAKE OBVIOUS: {shows}

THE SECTION IT SITS IN
{section_text[:3500]}

Pick the one shape that fits:
- "flow": 3-{DIAGRAM_MAX_NODES} steps in order (a process, a pipeline, a request's path)
- "cycle": 3-6 steps that repeat (a loop, a lifecycle)
- "layers": 3-6 stacked levels (a stack, tiers, a hierarchy; top level first)
- "compare": 2-3 columns of 3-5 short items each (this versus that). If the
  section really contrasts just two things, this is the shape: a two-node flow
  or two-layer stack shows nothing.

Rules: labels are 2-5 words a beginner understands; a note adds one detail only
when it earns its place; no fact, price or figure that is not in the section;
at most {DIAGRAM_MAX_NODES} nodes. For "compare" fill "columns" and leave "nodes"
empty. For the others fill "nodes" and leave "columns" empty; "edges" is optional
and only for arrows that are not simply step-to-next-step.

Return ONLY valid JSON in exactly this shape:
{DIAGRAM_SPEC_SCHEMA}"""
    try:
        spec = extract_json(call_claude(prompt, max_tokens=2000))
    except Exception as e:
        print(f"  Diagram spec failed ({str(e)[:80]}).")
        return None
    if isinstance(spec, dict) and not spec.get("title"):
        spec["title"] = title
    return _clean_diagram_spec(spec)


# -- layout: one geometry, two renderers ------------------------------------

_DG_W = 1200
_DG_PAD = 48
_DG_FONT = {"title": 26, "label": 19, "note": 14, "item": 15, "col": 20,
            "edge": 13, "caption": 15, "credit": 12}
_DG_COLORS = {"bg": "#ffffff", "box": "#eef3fb", "border": "#3b5bdb",
              "text": "#1a1a1a", "muted": "#555555", "accent": "#3b5bdb",
              "headtext": "#ffffff", "credit": "#999999"}


def _wrap_chars(text: str, max_chars: int, max_lines: int) -> list[str]:
    words, lines, current = str(text).split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:max(1, max_chars - 1)].rstrip() + "…"
    return lines or [""]


def _dg_wrap(text: str, box_w: float, size: int, max_lines: int = 3) -> list[str]:
    # 0.55em is a fair average glyph width for a sans face; good enough to wrap on.
    return _wrap_chars(text, max(6, int((box_w - 24) / (size * 0.55))), max_lines)


def _t(x, y, text, role, bold=False, color=None, anchor="middle") -> dict:
    return {"kind": "text", "x": x, "y": y, "text": text, "size": _DG_FONT[role],
            "bold": bold, "color": color or _DG_COLORS["text"], "anchor": anchor}


def _r(x, y, w, h, fill=None, stroke=None, rx=10) -> dict:
    return {"kind": "rect", "x": x, "y": y, "w": w, "h": h,
            "fill": fill, "stroke": stroke, "rx": rx}


def _a(x1, y1, x2, y2, label="", dashed=False) -> dict:
    return {"kind": "arrow", "x1": x1, "y1": y1, "x2": x2, "y2": y2,
            "label": label, "dashed": dashed}


def _tint(t: float) -> str:
    """Blend from a deeper to a paler blue-grey as t goes 0 -> 1."""
    a, b = (0xDC, 0xE6, 0xFA), (0xF7, 0xF9, 0xFD)
    return "#" + "".join(f"{int(round(a[i] + (b[i] - a[i]) * t)):02x}" for i in range(3))


def _clip_to_rect(cx, cy, w, h, tx, ty):
    """Where the line from a box's centre (cx, cy) towards (tx, ty) leaves the box."""
    dx, dy = tx - cx, ty - cy
    if not dx and not dy:
        return cx, cy
    t = min((w / 2) / abs(dx) if dx else float("inf"),
            (h / 2) / abs(dy) if dy else float("inf"))
    return cx + dx * t, cy + dy * t


def _node_box(els: list, x, y, w, h, node: dict):
    els.append(_r(x, y, w, h, fill=_DG_COLORS["box"], stroke=_DG_COLORS["border"]))
    label_lines = _dg_wrap(node["label"], w, _DG_FONT["label"], 2)
    note_lines = _dg_wrap(node["note"], w, _DG_FONT["note"], 2) if node.get("note") else []
    lh, nh = _DG_FONT["label"] + 4, _DG_FONT["note"] + 3
    total = len(label_lines) * lh + (len(note_lines) * nh + 6 if note_lines else 0)
    ty = y + (h - total) / 2 + _DG_FONT["label"] - 3
    for line in label_lines:
        els.append(_t(x + w / 2, ty, line, "label", bold=True))
        ty += lh
    if note_lines:
        ty += 4
        for line in note_lines:
            els.append(_t(x + w / 2, ty, line, "note", color=_DG_COLORS["muted"]))
            ty += nh


def _lay_flow(spec: dict, els: list, y: float, cycle: bool = False) -> float:
    nodes, W, pad = spec["nodes"], _DG_W, _DG_PAD
    n = len(nodes)
    per_row = min(4, n)
    gap, row_gap = 60, 64
    box_w = (W - 2 * pad - (per_row - 1) * gap) / per_row
    box_h = 96 if any(nd["note"] for nd in nodes) else 76
    rows = -(-n // per_row)
    pos = []
    for i, nd in enumerate(nodes):
        r, c = divmod(i, per_row)
        if r % 2 == 1:
            c = per_row - 1 - c          # snake, so step i+1 sits next to step i
        x = pad + c * (box_w + gap)
        yy = y + r * (box_h + row_gap)
        pos.append((x, yy))
        _node_box(els, x, yy, box_w, box_h, nd)
    for i in range(n - 1):
        (x1, y1), (x2, y2) = pos[i], pos[i + 1]
        if abs(y1 - y2) < 1:
            if x2 > x1:
                els.append(_a(x1 + box_w, y1 + box_h / 2, x2, y2 + box_h / 2))
            else:
                els.append(_a(x1, y1 + box_h / 2, x2 + box_w, y2 + box_h / 2))
        else:
            els.append(_a(x1 + box_w / 2, y1 + box_h, x2 + box_w / 2, y2))
    for e in spec.get("edges", []):
        a, b = e["from"], e["to"]
        if b == a + 1:
            continue
        (x1, y1), (x2, y2) = pos[a], pos[b]
        c1 = (x1 + box_w / 2, y1 + box_h / 2)
        c2 = (x2 + box_w / 2, y2 + box_h / 2)
        # Start and end on the box borders, not at the centres, so the arrowhead
        # never lands on a label.
        sx, sy = _clip_to_rect(*c1, box_w, box_h, *c2)
        ex, ey = _clip_to_rect(*c2, box_w, box_h, *c1)
        els.append(_a(sx, sy, ex, ey, label=e["label"], dashed=True))
    bottom = y + (rows - 1) * (box_h + row_gap) + box_h
    if cycle and n >= 2:
        (xl, yl), (xf, yf) = pos[-1], pos[0]
        drop = bottom + 30
        els.append({"kind": "path", "label": "repeats", "points": [
            (xl + box_w / 2, yl + box_h), (xl + box_w / 2, drop), (pad / 2, drop),
            (pad / 2, yf + box_h / 2), (xf, yf + box_h / 2)]})
        bottom = drop + 18
    return bottom


def _lay_layers(spec: dict, els: list, y: float) -> float:
    nodes, W, pad = spec["nodes"], _DG_W, _DG_PAD
    band_w, gap = W - 2 * pad, 10
    n = len(nodes)
    for i, nd in enumerate(nodes):
        h = 84 if nd["note"] else 62
        els.append(_r(pad, y, band_w, h, fill=_tint(i / max(1, n - 1)),
                      stroke=_DG_COLORS["border"], rx=8))
        block = _DG_FONT["label"] + 4 + (_DG_FONT["note"] + 3 if nd["note"] else 0)
        ty = y + (h - block) / 2 + _DG_FONT["label"] - 3
        els.append(_t(pad + 24, ty, nd["label"], "label", bold=True, anchor="start"))
        if nd["note"]:
            ty += _DG_FONT["label"] + 6
            els.append(_t(pad + 24, ty, _dg_wrap(nd["note"], band_w - 120, _DG_FONT["note"], 1)[0],
                          "note", color=_DG_COLORS["muted"], anchor="start"))
        els.append(_t(W - pad - 20, y + h / 2 + 7, str(i + 1), "label",
                      color=_DG_COLORS["muted"], anchor="end"))
        y += h + gap
    return y - gap


def _lay_compare(spec: dict, els: list, y: float) -> float:
    cols, W, pad = spec["columns"], _DG_W, _DG_PAD
    k, gap = len(cols), 36
    col_w = (W - 2 * pad - (k - 1) * gap) / k
    head_h, line_h, item_gap = 52, _DG_FONT["item"] + 6, 12
    wrapped = [[_dg_wrap(it, col_w - 40, _DG_FONT["item"], 2) for it in c["items"]] for c in cols]
    max_items = max(len(w) for w in wrapped)
    # Rows align across columns, so a two-line item in one column pads the others.
    per_item = [max(len(wrapped[j][i]) if i < len(wrapped[j]) else 1 for j in range(k))
                for i in range(max_items)]
    body_h = 16 + sum(lines * line_h + item_gap for lines in per_item)
    for j, c in enumerate(cols):
        x = pad + j * (col_w + gap)
        els.append(_r(x, y, col_w, head_h + body_h, fill=_DG_COLORS["bg"], stroke=None))
        els.append(_r(x, y, col_w, head_h, fill=_DG_COLORS["accent"], stroke=None))
        els.append(_r(x, y + head_h / 2, col_w, head_h / 2, fill=_DG_COLORS["accent"],
                      stroke=None, rx=0))
        els.append(_t(x + col_w / 2, y + head_h / 2 + 7,
                      _dg_wrap(c["title"], col_w, _DG_FONT["col"], 1)[0],
                      "col", bold=True, color=_DG_COLORS["headtext"]))
        ty = y + head_h + 16
        for i, lines in enumerate(wrapped[j]):
            ty += line_h
            els.append(_t(x + 18, ty, "•", "item", color=_DG_COLORS["accent"], anchor="start"))
            for li, line in enumerate(lines):
                if li:
                    ty += line_h
                els.append(_t(x + 36, ty, line, "item", anchor="start"))
            ty += item_gap + (per_item[i] - len(lines)) * line_h
        els.append(_r(x, y, col_w, head_h + body_h, fill=None, stroke=_DG_COLORS["border"]))
    return y + head_h + body_h


def layout_diagram(spec: dict) -> dict:
    """Turn a cleaned spec into primitives (rects, text lines, arrows) on a
    1200-wide canvas. Both renderers draw exactly this."""
    W, pad = _DG_W, _DG_PAD
    els, y = [], pad
    if spec.get("title"):
        for line in _dg_wrap(spec["title"], W - 2 * pad, _DG_FONT["title"], 2):
            y += _DG_FONT["title"]
            els.append(_t(W / 2, y, line, "title", bold=True))
        y += 24
    kind = spec["type"]
    if kind == "compare":
        y = _lay_compare(spec, els, y)
    elif kind == "layers":
        y = _lay_layers(spec, els, y)
    else:
        y = _lay_flow(spec, els, y, cycle=(kind == "cycle"))
    if spec.get("caption"):
        y += 26
        for line in _dg_wrap(spec["caption"], W - 2 * pad, _DG_FONT["caption"], 2):
            y += _DG_FONT["caption"] + 5
            els.append(_t(W / 2, y, line, "caption", color=_DG_COLORS["muted"]))
    y += 22
    els.append(_t(W - pad, y, f"Diagram: {AUTHOR_NAME}", "credit",
                  color=_DG_COLORS["credit"], anchor="end"))
    return {"w": W, "h": int(y + pad - 10), "elements": els}


def diagram_svg(layout: dict) -> str:
    """The layout as one self-contained SVG, on a single line so it survives
    Markdown's raw-HTML handling."""
    W, H = layout["w"], layout["h"]
    stroke = _DG_COLORS["accent"]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" font-family="Arial, Helvetica, sans-serif">',
        '<defs><marker id="dgArrow" viewBox="0 0 10 10" refX="9" refY="5" '
        'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M0,0 L10,5 L0,10 z" fill="{stroke}"/></marker></defs>',
        f'<rect x="0" y="0" width="{W}" height="{H}" fill="{_DG_COLORS["bg"]}"/>',
    ]
    for e in layout["elements"]:
        k = e["kind"]
        if k == "rect":
            out.append(f'<rect x="{e["x"]:.1f}" y="{e["y"]:.1f}" width="{e["w"]:.1f}" '
                       f'height="{e["h"]:.1f}" rx="{e["rx"]}" fill="{e["fill"] or "none"}" '
                       f'stroke="{e["stroke"] or "none"}" stroke-width="2"/>')
        elif k == "text":
            weight = ' font-weight="bold"' if e["bold"] else ""
            out.append(f'<text x="{e["x"]:.1f}" y="{e["y"]:.1f}" font-size="{e["size"]}" '
                       f'text-anchor="{e["anchor"]}" fill="{e["color"]}"{weight}>'
                       f'{_svg_escape(e["text"])}</text>')
        elif k == "arrow":
            dash = ' stroke-dasharray="7 5"' if e["dashed"] else ""
            out.append(f'<line x1="{e["x1"]:.1f}" y1="{e["y1"]:.1f}" x2="{e["x2"]:.1f}" '
                       f'y2="{e["y2"]:.1f}" stroke="{stroke}" stroke-width="2.5"{dash} '
                       'marker-end="url(#dgArrow)"/>')
            if e["label"]:
                mx, my = (e["x1"] + e["x2"]) / 2, (e["y1"] + e["y2"]) / 2 - 8
                out.append(f'<text x="{mx:.1f}" y="{my:.1f}" font-size="{_DG_FONT["edge"]}" '
                           f'text-anchor="middle" fill="{_DG_COLORS["muted"]}">'
                           f'{_svg_escape(e["label"])}</text>')
        elif k == "path":
            pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in e["points"])
            out.append(f'<polyline points="{pts}" fill="none" stroke="{stroke}" '
                       'stroke-width="2.5" marker-end="url(#dgArrow)"/>')
            if e.get("label"):
                (x1, y1), (x2, y2) = e["points"][1], e["points"][2]
                out.append(f'<text x="{(x1 + x2) / 2:.1f}" y="{y1 + 17:.1f}" '
                           f'font-size="{_DG_FONT["edge"]}" text-anchor="middle" '
                           f'fill="{_DG_COLORS["muted"]}">{_svg_escape(e["label"])}</text>')
    out.append("</svg>")
    return "".join(out)


def _png_arrow(draw, pts: list, scale: float, color: str):
    draw.line(pts, fill=color, width=max(2, int(2.5 * scale)), joint="curve")
    (x1, y1), (x2, y2) = pts[-2], pts[-1]
    dx, dy = x2 - x1, y2 - y1
    length = (dx * dx + dy * dy) ** 0.5 or 1.0
    ux, uy = dx / length, dy / length
    size = 11 * scale
    base_x, base_y = x2 - ux * size, y2 - uy * size
    px, py = -uy * size * 0.55, ux * size * 0.55
    draw.polygon([(x2, y2), (base_x + px, base_y + py), (base_x - px, base_y - py)], fill=color)


def diagram_png(layout: dict, path: Path, scale: float = 1.5) -> bool:
    """Rasterise the layout with Pillow. False when Pillow is missing, in which
    case the SVG stands alone."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        print("  Pillow not installed; diagram PNG skipped, SVG still written.")
        return False
    W, H = int(layout["w"] * scale), int(layout["h"] * scale)
    im = Image.new("RGB", (W, H), _DG_COLORS["bg"])
    draw = ImageDraw.Draw(im)
    fonts: dict = {}

    def font(size: int, bold: bool):
        key = (size, bold)
        if key not in fonts:
            px = int(size * scale)
            face, faux_bold = None, bold
            for name in (("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold
                         else ("arial.ttf", "DejaVuSans.ttf")):
                try:
                    face, faux_bold = ImageFont.truetype(name, px), False
                    break
                except Exception:
                    continue
            if face is None:
                face = ImageFont.load_default(size=px)   # Pillow's bundled scalable face
            fonts[key] = (face, faux_bold)
        return fonts[key]

    S = lambda v: v * scale
    for e in layout["elements"]:
        k = e["kind"]
        if k == "rect":
            draw.rounded_rectangle(
                [S(e["x"]), S(e["y"]), S(e["x"] + e["w"]), S(e["y"] + e["h"])],
                radius=S(e["rx"]), fill=e["fill"], outline=e["stroke"],
                width=max(2, int(2 * scale)) if e["stroke"] else 0)
        elif k == "text":
            face, faux = font(e["size"], e["bold"])
            draw.text((S(e["x"]), S(e["y"])), e["text"], font=face, fill=e["color"],
                      anchor={"middle": "ms", "start": "ls", "end": "rs"}[e["anchor"]],
                      stroke_width=1 if faux else 0, stroke_fill=e["color"])
        elif k == "arrow":
            _png_arrow(draw, [(S(e["x1"]), S(e["y1"])), (S(e["x2"]), S(e["y2"]))],
                       scale, _DG_COLORS["accent"])
            if e["label"]:
                face, _ = font(_DG_FONT["edge"], False)
                draw.text((S((e["x1"] + e["x2"]) / 2), S((e["y1"] + e["y2"]) / 2 - 8)),
                          e["label"], font=face, fill=_DG_COLORS["muted"], anchor="ms")
        elif k == "path":
            _png_arrow(draw, [(S(x), S(y)) for x, y in e["points"]], scale, _DG_COLORS["accent"])
            if e.get("label"):
                (x1, y1), (x2, _) = e["points"][1], e["points"][2]
                face, _ = font(_DG_FONT["edge"], False)
                draw.text((S((x1 + x2) / 2), S(y1 + 17)), e["label"], font=face,
                          fill=_DG_COLORS["muted"], anchor="ms")
    im.save(path, "PNG", optimize=True)
    return True


def render_diagrams(content: str, slug: str, output_dir: Path) -> dict[str, dict]:
    """Every [DIAGRAM: ...] marker -> a spec from Claude -> SVG and PNG on disk.
    Returns marker -> {alt, caption, svg, png, svg_name}."""
    markers = list(DIAGRAM_MARKER_RE.finditer(content))
    if not markers:
        print("  No [DIAGRAM: ...] markers found in article.")
        return {}
    log("STEP 8.5", f"Drawing {len(markers)} diagram(s)")
    output_dir.mkdir(parents=True, exist_ok=True)
    out = {}
    for n, m in enumerate(markers, 1):
        title, shows = m.group(1).strip(), m.group(2).strip()
        spec = generate_diagram_spec(title, shows, _section_around(content, m.start()))
        if not spec:
            print(f"  Diagram {n}: no usable spec; the marker will be dropped.")
            continue
        layout = layout_diagram(spec)
        svg_name, png_name = f"{slug}_diagram_{n}.svg", f"{slug}_diagram_{n}.png"
        svg = diagram_svg(layout)
        (output_dir / svg_name).write_text(svg, encoding="utf-8")
        png_ok = diagram_png(layout, output_dir / png_name)
        parts = len(spec["nodes"]) or len(spec["columns"])
        out[m.group(0)] = {
            "alt": spec["title"] or title, "caption": spec["caption"] or shows,
            "type": spec["type"], "svg": svg, "svg_name": svg_name,
            "png": png_name if png_ok else None,
        }
        print(f"  Diagram {n}: {spec['type']} with {parts} parts -> "
              f"{png_name if png_ok else svg_name}")
    return out


def inject_diagrams(content: str, diagrams: dict[str, dict]) -> str:
    """Replace each marker with an image block that points at the rendered file.
    The caption line starts with *Diagram: so the HTML and DOCX writers can tell
    it from a sourced photo."""
    for marker, d in diagrams.items():
        src = d["png"] or d["svg_name"]
        content = content.replace(marker, f"\n![{d['alt']}]({src})\n*Diagram: {d['caption']}*\n")
    return content


# ---------------------------------------------------------------------------
# Step 1.5: Fact pack
# ---------------------------------------------------------------------------
#
# Step 1 reads the titles and snippets of what ranks. It never opens a page, so
# every specific a reader wants - a price, an exam code, a version, a date - was
# left to the model's memory and came out hedged: "typically $200-$400",
# "several hundred dollars". This stage opens the primary pages and pulls the
# actual figures out, each tied to the URL and the sentence it came from. The
# writer is then held to the pack: no number that is not in it, no range where
# the pack has a value.

FACT_PACK_MAX_FACTS = 24
FACT_PACK_SEARCHES = 6
FACT_PACK_FETCHES = 8

FACT_PACK_SCHEMA = """{
  "facts": [
    {
      "id": "f1",
      "claim": "<what the fact establishes, one sentence, specific>",
      "value": "<the exact figure, name, date or version - never a range unless the source itself gives a range>",
      "source_url": "<the page the figure appears on>",
      "source_title": "<page or document title>",
      "quote": "<the sentence on the page that states it, verbatim, under 40 words>",
      "as_of": "<date the source states or was published, YYYY-MM-DD or YYYY-MM, or 'undated'>",
      "kind": "price | date | version | spec | statistic | quote | policy | name"
    }
  ],
  "primary_sources": ["<urls actually opened>"],
  "gaps": ["<specifics the reader will want that no opened source states>"]
}"""


def _fact_pack_brief(title: str, keywords: str, intent: str, research: dict) -> str:
    subtopics = research.get("semantic_analysis", {}).get("common_subtopics", [])
    questions = research.get("semantic_analysis", {}).get("related_questions", [])
    return f"""TOPIC: {title}
PRIMARY KEYWORD: {keywords}
WRITER'S INTENT: {intent or '(none given)'}
SUBTOPICS THE ARTICLE WILL COVER: {"; ".join(subtopics) or "(none)"}
QUESTIONS READERS ASK: {"; ".join(questions) or "(none)"}
{date_context()}"""


def _fact_pack_via_claude_tools(brief: str) -> dict:
    """One Claude call with server-side search and fetch. Returns the pack, or
    raises so the caller can fall back."""
    prompt = f"""You are a research assistant building the evidence pack for an article.

{brief}

Do this:
1. Search for the primary sources: the vendor's own pricing, documentation,
   exam or product pages; official announcements; standards bodies; peer-reviewed
   or first-party reports. Prefer these over blogs and aggregators. Prefer pages
   dated in the last 18 months.
2. Open the {FACT_PACK_FETCHES} most authoritative pages and read them.
3. Extract every specific figure a reader of this article would want: prices,
   fees, dates, deadlines, version numbers, exam codes, question counts, durations,
   validity periods, limits, percentages, named products and tiers.
4. Record each one with the URL you read it on and the verbatim sentence.

Rules:
- Only facts you actually read on a page you opened. Nothing from memory.
- Exact values. If a page says "$250", the value is "$250", not "$200-$400".
- If two sources disagree, include both facts and say so in "claim".
- If you cannot find something the reader will want, put it in "gaps" rather
  than guessing.
- Up to {FACT_PACK_MAX_FACTS} facts.

Return ONLY valid JSON in exactly this shape:
{FACT_PACK_SCHEMA}"""

    pack = _claude_web_call(prompt, max_tokens=12000, searches=FACT_PACK_SEARCHES,
                            fetches=FACT_PACK_FETCHES, label="fact-pack",
                            schema=FACT_PACK_SCHEMA)
    pack["method"] = "claude-web-tools"
    return pack


def _page_text(url: str, limit_chars: int = 12000) -> str:
    """A crude but dependency-free HTML-to-text for the fallback path."""
    try:
        r = requests.get(url, timeout=20, headers={
            "User-Agent": "Mozilla/5.0 (compatible; HumanlyResearch/1.0)"})
        r.raise_for_status()
    except Exception:
        return ""
    html = r.text
    html = re.sub(r"(?is)<(script|style|nav|footer|header|noscript).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"&nbsp;|&#160;", " ", text)
    text = re.sub(r"&amp;", "&", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()[:limit_chars]


def _fact_pack_via_serpapi(brief: str, keywords: str) -> dict:
    """Fallback: SerpAPI for URLs, plain HTTP for pages, Claude for extraction."""
    key = os.getenv("SERPAPI_KEY")
    if not key:
        raise ClaudeError("No SERPAPI_KEY for the fact-pack fallback.")
    resp = requests.get(SERPAPI_BASE, params={"q": keywords, "num": 10, "api_key": key},
                        timeout=15)
    resp.raise_for_status()
    results = resp.json().get("organic_results", [])
    urls = [r.get("link") for r in results if r.get("link")][:FACT_PACK_FETCHES]
    pages = []
    for url in urls:
        text = _page_text(url)
        if len(text) > 400:
            pages.append(f"=== {url} ===\n{text}\n")
            print(f"  fetched {url[:70]}")
    if not pages:
        raise ClaudeError("Fact-pack fallback fetched no readable pages.")
    prompt = f"""You are extracting the evidence pack for an article from pages already fetched.

{brief}

PAGES
{"".join(pages)[:90000]}

Extract every specific figure a reader would want (prices, dates, versions, codes,
counts, durations, validity, limits, named tiers). Only what the pages state;
exact values; verbatim quote; the URL it came from. Put wanted-but-missing
specifics in "gaps". Up to {FACT_PACK_MAX_FACTS} facts.

Return ONLY valid JSON in exactly this shape:
{FACT_PACK_SCHEMA}"""
    pack = extract_json(call_claude(prompt, max_tokens=12000))
    pack.setdefault("primary_sources", urls)
    pack["method"] = "serpapi-fetch"
    return pack


def _clean_fact_pack(pack: dict) -> dict:
    facts = []
    seen = set()
    for i, f in enumerate(pack.get("facts", []) or [], 1):
        if not isinstance(f, dict):
            continue
        url = str(f.get("source_url", "")).strip()
        value = str(f.get("value", "")).strip()
        if not url.startswith("http") or not value:
            continue
        key = (value.lower(), url)
        if key in seen:
            continue
        seen.add(key)
        f["id"] = f"f{len(facts) + 1}"
        facts.append(f)
        if len(facts) >= FACT_PACK_MAX_FACTS:
            break
    return {
        "facts": facts,
        "primary_sources": [u for u in (pack.get("primary_sources") or []) if str(u).startswith("http")],
        "gaps": [str(g) for g in (pack.get("gaps") or [])][:12],
        "method": pack.get("method", "unknown"),
        "built_at": TODAY.isoformat(timespec="seconds"),
    }


def build_fact_pack(title: str, keywords: str, intent: str, research: dict) -> dict:
    log("STEP 1.5", "Building the fact pack (opening primary sources)")
    brief = _fact_pack_brief(title, keywords, intent, research)
    pack = None
    try:
        pack = _fact_pack_via_claude_tools(brief)
    except Exception as e:
        print(f"  Web-tool path unavailable ({str(e)[:120]}); trying SerpAPI fallback.")
        try:
            pack = _fact_pack_via_serpapi(brief, keywords)
        except Exception as e2:
            print(f"  Fallback failed too ({str(e2)[:120]}). Continuing without a fact pack; "
                  f"the writer will be told to state no figures it cannot cite.")
            pack = {"facts": [], "primary_sources": [], "gaps": [], "method": "none"}
    pack = _clean_fact_pack(pack)
    n = len(pack["facts"])
    print(f"  Fact pack: {n} fact(s) from {len(pack['primary_sources'])} page(s) "
          f"via {pack['method']}; {len(pack['gaps'])} gap(s) noted.")
    for f in pack["facts"][:8]:
        print(f"    {f['id']} {f.get('kind','?'):9} {f['value'][:28]:28} {f.get('claim','')[:60]}")
    return pack


def fact_pack_text(research: dict) -> str:
    """The pack as the writer, outliner and auditor see it."""
    pack = research.get("fact_pack") or {}
    facts = pack.get("facts") or []
    if not facts:
        return """
FACT PACK
No verified facts were collected for this article. Therefore: state no price,
date, version, count or statistic as fact. Where a figure is needed, say plainly
that it should be checked on the vendor's page and link the page, or leave it
out. Do not fill the gap from memory.
"""
    lines = []
    for f in facts:
        as_of = f.get("as_of") or "undated"
        lines.append(f"[{f['id']}] {f.get('claim','')} | value: {f['value']} | "
                     f"as of {as_of} | {f['source_url']}\n"
                     f"     quote: \"{str(f.get('quote',''))[:200]}\"")
    gaps = pack.get("gaps") or []
    gap_text = ("\nKNOWN GAPS (no opened source states these - do not invent them):\n"
                + "\n".join(f"- {g}" for g in gaps)) if gaps else ""
    return f"""
FACT PACK (the only permitted source of specifics)
{chr(10).join(lines)}
{gap_text}
Rules for using it:
- Every number, price, date, version, exam code, count and named tier in the
  article must come from a fact above, cited inline as (Source: <source_url>).
- Use the exact value. Never widen a value into a range, and never hedge a
  pack value with "typically", "approximately", "around" or "several".
- If the pack has no fact for something, either omit it or tell the reader to
  check the linked page. Never guess.
- Prefer the most recent fact when two conflict, and say which is newer.
"""


# ---------------------------------------------------------------------------
# Topic Radar: what to write, from what the AI industry is talking about
# ---------------------------------------------------------------------------
#
# The pipeline writes whatever topic it is handed. This runs before it and
# answers the prior question - what is worth writing this week - by reading
# what the industry is actually talking about: the most-watched AI videos,
# the podcasts engineers listen to, the newsletters and posts of the people
# they follow, and the two forums where they argue. Signals come from code
# where a free API exists (Hacker News, Reddit) and from Claude's web tools
# where none does (YouTube, podcasts, newsletters); one synthesis call then
# clusters them into themes and says, for each, the angle an engineer-author
# could own. Every evidence link is one the radar actually saw.

RADAR_DAYS = 14
RADAR_MAX_THEMES = 8
RADAR_LENS = os.getenv(
    "RADAR_LENS",
    "engineers who build with LLMs, agents and RAG in production and want to know "
    "what actually works")
RADAR_PODCASTS = [
    "Latent Space", "Lex Fridman Podcast", "No Priors", "The a16z Podcast",
    "Practical AI", "Dwarkesh Podcast", "The Cognitive Revolution", "AI Engineer",
    "How I AI", "Training Data (Sequoia)",
]
RADAR_YOUTUBE_CHANNELS = [
    "Fireship", "Matthew Berman", "AI Explained", "Wes Roth", "Two Minute Papers",
    "Andrej Karpathy", "3Blue1Brown", "IndyDevDan", "Cole Medin", "Sam Witteveen",
]
RADAR_VOICES = [
    "Simon Willison", "Andrej Karpathy", "Ethan Mollick", "swyx", "Hamel Husain",
    "Jeremy Howard", "Nathan Lambert", "Sebastian Raschka", "Andrew Ng's The Batch",
    "Ben's Bites", "The Rundown AI", "Import AI",
]
RADAR_SUBREDDITS = ["LocalLLaMA", "MachineLearning", "artificial", "ClaudeAI", "LangChain"]
RADAR_HN_QUERIES = ["AI", "LLM", "agents", "GPT", "Claude", "RAG", "open source model"]
REDDIT_PAUSE_SECS = 6.0
_RADAR_UA = {"User-Agent": "humanly-radar/1.0 (topic research; +https://imrantauqir.com)"}


WEB_CALL_DEBUG_DIR = Path(os.getenv("WEB_CALL_DEBUG_DIR", "output"))


def _claude_web_call(prompt: str, max_tokens: int, searches: int, fetches: int,
                     label: str, schema: str = "") -> dict:
    """One Claude call with server-side web search and fetch, returning the JSON
    object it was asked for. Shared by the fact pack and the radar.

    After a dozen page reads the model sometimes answers in prose with the
    findings in it. That is not a failure of the research, only of the format,
    so a second, tool-free call reshapes the text into the schema before the
    step gives up. The raw text is kept on disk either way."""
    tools = [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": searches},
        {"type": "web_fetch_20250910", "name": "web_fetch",
         "max_uses": fetches, "max_content_tokens": 12000},
    ]
    kwargs = dict(
        model=MODEL, max_tokens=max_tokens, tools=tools,
        messages=[{"role": "user", "content": prompt}],
        thinking={"type": "adaptive"}, output_config={"effort": "medium"},
    )
    try:
        response = client.messages.create(**kwargs)
    except anthropic.BadRequestError as e:
        message = _api_message(e).lower()
        if "beta" in message or "web_fetch" in message or "tool" in message:
            # Older API surface: the fetch tool wants a beta header.
            response = client.beta.messages.create(
                betas=["web-fetch-2025-09-10"], **kwargs)
        else:
            raise ClaudeError(f"Anthropic rejected the {label} request: {_api_message(e)}") from e
    u = getattr(response, "usage", None)
    if u is not None:
        record_usage("anthropic", MODEL,
                     getattr(u, "input_tokens", 0), getattr(u, "output_tokens", 0),
                     getattr(u, "cache_read_input_tokens", 0) or 0,
                     getattr(u, "cache_creation_input_tokens", 0) or 0)
    text = "\n".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    try:
        WEB_CALL_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        (WEB_CALL_DEBUG_DIR / f"_last_{label.replace(' ', '_')}.txt").write_text(
            text, encoding="utf-8")
    except Exception:
        pass
    if not text.strip():
        raise ClaudeError(f"The {label} call returned no text.")
    if getattr(response, "stop_reason", "") == "max_tokens":
        print(f"  The {label} call hit its output limit; repairing what it wrote.")
    try:
        return extract_json(text)
    except ClaudeError:
        if not schema:
            raise
    print(f"  The {label} call answered in prose; reshaping it into JSON.")
    repair = f"""Below is a research assistant's answer that should have been JSON.
Reformat it into ONLY the JSON shape given. Keep every item that has a real
URL in the text; invent nothing; drop items with no URL.

SHAPE
{schema}

ANSWER
{text[:60000]}"""
    return extract_json(call_claude(repair, max_tokens=max_tokens))


def _hn_top(days: int, limit: int = 40) -> list[dict]:
    """Top Hacker News stories about AI in the window, by points plus comments."""
    since = int(time.time()) - days * 86400
    seen, out = set(), []
    for q in RADAR_HN_QUERIES:
        try:
            r = requests.get("https://hn.algolia.com/api/v1/search", params={
                "query": q, "tags": "story", "hitsPerPage": 30,
                "numericFilters": f"created_at_i>{since}",
            }, headers=_RADAR_UA, timeout=20)
            r.raise_for_status()
            hits = r.json().get("hits", [])
        except Exception as e:
            print(f"  Hacker News query '{q}' failed ({str(e)[:60]})")
            continue
        for h in hits:
            key = str(h.get("objectID", ""))
            if not key or key in seen or not h.get("title"):
                continue
            seen.add(key)
            discussion = f"https://news.ycombinator.com/item?id={key}"
            out.append({
                "source": "Hacker News", "kind": "forum", "title": str(h["title"])[:160],
                "url": h.get("url") or discussion, "discussion": discussion,
                "signal": int(h.get("points") or 0), "comments": int(h.get("num_comments") or 0),
                "date": str(h.get("created_at") or "")[:10], "gist": "",
            })
    out.sort(key=lambda x: x["signal"] + x["comments"], reverse=True)
    return out[:limit]


def _reddit_top(days: int, limit: int = 40) -> list[dict]:
    """Top posts from the AI subreddits, read from the RSS feeds. Reddit blocks
    the JSON endpoints for anything that is not a logged-in browser; the feeds
    answer, in top-of-window order, without vote counts. Whatever it blocks is
    skipped, not fatal."""
    import html as html_lib
    import xml.etree.ElementTree as ET
    window = "week" if days <= 7 else "month"
    ns = {"a": "http://www.w3.org/2005/Atom"}
    out = []
    for n, sub in enumerate(RADAR_SUBREDDITS):
        if n:
            time.sleep(REDDIT_PAUSE_SECS)      # the feeds 429 when hit back to back
        try:
            r = requests.get(f"https://www.reddit.com/r/{sub}/top/.rss",
                             params={"t": window, "limit": 12}, headers=_RADAR_UA, timeout=20)
            if r.status_code == 429:
                time.sleep(REDDIT_PAUSE_SECS * 4)
                r = requests.get(f"https://www.reddit.com/r/{sub}/top/.rss",
                                 params={"t": window, "limit": 12}, headers=_RADAR_UA, timeout=20)
            if r.status_code != 200 or b"<feed" not in r.content[:400]:
                print(f"  Reddit r/{sub}: HTTP {r.status_code}, skipped")
                continue
            root = ET.fromstring(r.content)
        except Exception as e:
            print(f"  Reddit r/{sub} failed ({str(e)[:60]})")
            continue
        for rank, entry in enumerate(root.findall("a:entry", ns), 1):
            title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
            link_el = entry.find("a:link", ns)
            discussion = link_el.get("href", "") if link_el is not None else ""
            if not title or not discussion:
                continue
            # A link post carries its target as <a href="...">[link]</a> in the body.
            body = entry.findtext("a:content", default="", namespaces=ns) or ""
            m = re.search(r'href="([^"]+)">\[link\]', body)
            target = html_lib.unescape(m.group(1)) if m else ""
            url = target if target.startswith("http") and "reddit.com" not in target else discussion
            out.append({
                "source": f"r/{sub}", "kind": "forum", "title": title[:160],
                "url": url, "discussion": discussion,
                "signal": f"top {rank} of the {window} on r/{sub}", "comments": 0,
                "date": (entry.findtext("a:updated", default="", namespaces=ns) or "")[:10],
                "gist": "",
            })
    return out[:limit]


RADAR_SCAN_SCHEMA = """{
  "items": [
    {
      "kind": "youtube | podcast | newsletter | post | linkedin | article",
      "title": "<title of the video, episode, issue or post>",
      "url": "<the real url>",
      "who": "<channel, show or person>",
      "signal": "<views, listens or likes as stated on the page, or 'unknown'>",
      "date": "<YYYY-MM-DD or unknown>",
      "gist": "<one sentence: what it says or argues>"
    }
  ]
}"""


def _radar_web_scan(days: int) -> list[dict]:
    """YouTube, podcasts and newsletters, via Claude's own search and fetch."""
    prompt = f"""You are scanning what the AI industry has talked about in the last {days} days,
for an author who writes for {RADAR_LENS}.
{date_context()}

Find, by searching and opening pages:
1. The most-watched YouTube videos about AI from the last {days} days. Search for
   the week's most viewed AI videos and for these channels: {", ".join(RADAR_YOUTUBE_CHANNELS)}.
   Record the view count the page shows.
2. New episodes of these podcasts and what each discussed: {", ".join(RADAR_PODCASTS)}.
3. What widely followed AI voices published or argued this fortnight, in newsletters
   and posts: {", ".join(RADAR_VOICES)}.
4. Public LinkedIn posts and articles by AI practitioners from the last {days} days:
   search site:linkedin.com/posts and site:linkedin.com/pulse with the week's AI
   topics, open only pages that display without a login, and record who wrote it.
5. Anything from the last {days} days that several of the above discuss independently.

Rules: only items you actually saw on a page you opened or in a search result; real
URLs only, never constructed; 20 to 35 items; prefer the last {days} days and give
the date; "signal" is what the page states, never a guess.

Return ONLY valid JSON in exactly this shape:
{RADAR_SCAN_SCHEMA}"""
    data = _claude_web_call(prompt, max_tokens=16000, searches=12, fetches=10,
                            label="radar scan", schema=RADAR_SCAN_SCHEMA)
    items = []
    for it in (data.get("items") or []):
        if not isinstance(it, dict):
            continue
        url = str(it.get("url", "")).strip()
        if not url.startswith("http") or not it.get("title"):
            continue
        items.append({
            "source": str(it.get("who") or it.get("kind") or "web")[:60],
            "kind": str(it.get("kind") or "web")[:20],
            "title": str(it["title"])[:160], "url": url, "discussion": "",
            "signal": str(it.get("signal") or "unknown")[:40], "comments": 0,
            "date": str(it.get("date") or "")[:10], "gist": str(it.get("gist") or "")[:240],
        })
    return items


RADAR_SCHEMA = """{
  "themes": [
    {
      "title": "<the theme as a reader would name it, under 10 words>",
      "why_now": "<what happened in the window that makes this live, 1-2 sentences>",
      "who_is_talking": "<which kinds of voices carry it: videos, podcasts, forums, newsletters>",
      "evidence": [ {"source": "<who or where>", "title": "<item title>", "url": "<url from the signals>", "signal": "<views, points, comments>"} ],
      "saturation": "low | medium | high",
      "engineer_angle": "<the angle this author's readers need that the sources are not giving, 1-2 sentences>",
      "suggested_title": "<a working title>",
      "suggested_intent": "<what the reader should be able to do after reading, one sentence>",
      "suggested_take": ["<a first-person position the author could hold, specific enough to disagree with>", "..."],
      "score": <1-100>
    }
  ],
  "skipped": ["<a hot topic deliberately left out, and why>"]
}"""


def _norm_url(url: str) -> str:
    return str(url or "").strip().rstrip("/").lower()


# -- the radar's memory --------------------------------------------------------
#
# Without this every run started from zero: a theme the author had rejected,
# or already written, came back the next week with a fresh score. Decisions
# live in output/radar_decisions.json, keyed by a normalised title, and reach
# the synthesis prompt as well as a similarity filter on what comes back.

DECISION_STATUSES = ("approved", "skipped", "written")


def _decision_key(title: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]+", " ", str(title).lower()).split())


def load_decisions(output_dir: Path) -> dict:
    path = output_dir / "radar_decisions.json"
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def record_decision(output_dir: Path, title: str, status: str, slug: str = "", note: str = "") -> dict:
    """Remember what the author decided about a theme. Returns the record."""
    if status not in DECISION_STATUSES:
        raise ValueError(f"status must be one of {DECISION_STATUSES}")
    output_dir.mkdir(parents=True, exist_ok=True)
    decisions = load_decisions(output_dir)
    record = {"title": " ".join(str(title).split())[:140], "status": status,
              "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
    if slug:
        record["slug"] = slug
    if note:
        record["note"] = str(note)[:300]
    decisions[_decision_key(title)] = record
    (output_dir / "radar_decisions.json").write_text(
        json.dumps(decisions, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def _title_similarity(a: str, b: str) -> float:
    """Word overlap (Jaccard) between two titles, stop words removed."""
    stop = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "vs", "with", "why", "how", "what"}
    wa = {w for w in _decision_key(a).split() if w not in stop}
    wb = {w for w in _decision_key(b).split() if w not in stop}
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def decision_for(title: str, decisions: dict, threshold: float = 0.6) -> dict | None:
    """The decision that applies to a theme: an exact key, else the most
    similar decided title above the threshold."""
    key = _decision_key(title)
    if key in decisions:
        return decisions[key]
    best, best_score = None, 0.0
    for rec in decisions.values():
        score = _title_similarity(title, rec.get("title", ""))
        if score > best_score:
            best, best_score = rec, score
    return best if best_score >= threshold else None


def decisions_block(decisions: dict) -> str:
    if not decisions:
        return ""
    groups = {st: [r["title"] for r in decisions.values() if r.get("status") == st] for st in DECISION_STATUSES}
    lines = ["\nTHE AUTHOR'S DECISIONS ON EARLIER THEMES"]
    if groups["written"]:
        lines.append("Already written (do not propose again unless something genuinely new happened this window):")
        lines += [f"- {t}" for t in groups["written"][-25:]]
    if groups["skipped"]:
        lines.append("Skipped by the author (do not re-propose; a close variant counts as the same theme):")
        lines += [f"- {t}" for t in groups["skipped"][-25:]]
    if groups["approved"]:
        lines.append("Approved and queued to write (fine to keep, but rank fresh themes above them):")
        lines += [f"- {t}" for t in groups["approved"][-25:]]
    return "\n".join(lines) + "\n"


def _clean_radar(data: dict, signals: list[dict], decisions: dict | None = None) -> dict:
    """Keep only themes whose evidence points at signals the radar actually saw."""
    known = {_norm_url(s["url"]): s for s in signals}
    for s in signals:
        if s.get("discussion"):
            known.setdefault(_norm_url(s["discussion"]), s)
    themes = []
    for t in (data.get("themes") or []) if isinstance(data, dict) else []:
        if not isinstance(t, dict) or not str(t.get("title", "")).strip():
            continue
        evidence = []
        for e in (t.get("evidence") or []):
            if not isinstance(e, dict):
                continue
            seen = known.get(_norm_url(e.get("url", "")))
            if not seen:
                continue
            evidence.append({
                "source": str(e.get("source") or seen["source"])[:60],
                "title": str(e.get("title") or seen["title"])[:160],
                "url": seen["url"],
                "discussion": seen.get("discussion") or "",
                "signal": str(e.get("signal") or seen["signal"])[:40],
            })
        if len(evidence) < 2:
            continue
        try:
            score = max(1, min(100, int(t.get("score") or 0)))
        except (TypeError, ValueError):
            score = 1
        saturation = str(t.get("saturation") or "medium").strip().lower()
        title_clean = " ".join(str(t["title"]).split())[:90]
        decided = decision_for(title_clean, decisions or {})
        if decided and decided.get("status") in ("skipped", "written"):
            # The author already ruled on this; the prompt was told, but the
            # model does not always listen. Drop it here, deterministically.
            print(f"  Dropped ({decided['status']} earlier): {title_clean}")
            continue
        themes.append({
            "title": title_clean,
            "decision": decided.get("status") if decided else None,
            "why_now": str(t.get("why_now") or "").strip()[:400],
            "who_is_talking": str(t.get("who_is_talking") or "").strip()[:200],
            "evidence": evidence[:6],
            "saturation": saturation if saturation in {"low", "medium", "high"} else "medium",
            "engineer_angle": str(t.get("engineer_angle") or "").strip()[:400],
            "suggested_title": str(t.get("suggested_title") or t["title"]).strip()[:140],
            "suggested_intent": str(t.get("suggested_intent") or "").strip()[:300],
            "suggested_take": [str(x).strip() for x in (t.get("suggested_take") or [])
                               if str(x).strip()][:3],
            "score": score,
        })
    themes.sort(key=lambda t: t["score"], reverse=True)
    skipped = [str(x).strip() for x in (data.get("skipped") or []) if str(x).strip()][:8] \
        if isinstance(data, dict) else []
    return {"themes": themes[:RADAR_MAX_THEMES], "skipped": skipped}


def synthesize_radar(signals: list[dict], days: int, decisions: dict | None = None) -> dict:
    lines = []
    for s in signals[:140]:
        line = f"- [{s['kind']}/{s['source']}] {s['title']} | {s['url']} | signal {s['signal']}"
        if s.get("comments"):
            line += f", {s['comments']} comments"
        if s.get("date"):
            line += f" | {s['date']}"
        if s.get("gist"):
            line += f" | {s['gist']}"
        lines.append(line)
    prompt = f"""You are the editor for an author who writes for {RADAR_LENS}.
{date_context()}

Below are {len(lines)} signals from the last {days} days: the most-viewed videos, podcast
episodes, newsletters and posts, and the top forum threads, each with the attention it got.

SIGNALS
{chr(10).join(lines)}

Do this:
1. Cluster the signals into themes. A theme needs at least two independent sources;
   a single viral item is not a theme unless engineers are arguing about it.
2. Score each theme 1-100 on breadth (how many kinds of source carry it), heat (the
   size of the signals), freshness, and - weighted most - the gap: whether the sources
   already treat it the way an engineer who ships would. If they do, saturation is
   high and the score drops.
3. For each theme, name the angle this author's readers need that the sources are not
   giving: the how, the failure mode, the cost, what you learn only by running it.
4. Draft a working title, an intent, and 2-3 first-person takes the author could hold.
   They will edit these, so make them specific enough to disagree with.

{decisions_block(decisions or {})}
Rules: every evidence url must be copied exactly from the signals above; at most
{RADAR_MAX_THEMES} themes, best first; leave out themes that are pure product news
with no engineering question in them, and say so in "skipped".

Return ONLY valid JSON in exactly this shape:
{RADAR_SCHEMA}"""
    data = extract_json(call_claude(prompt, max_tokens=12000))
    return _clean_radar(data, signals, decisions)


def format_radar(radar: dict, days: int, signal_count: int, stamp: str) -> str:
    out = [f"# What to write - {stamp}", "",
           f"_{signal_count} signals from the last {days} days, read for {RADAR_LENS}._", ""]
    for i, t in enumerate(radar.get("themes", []), 1):
        out += [f"## {i}. {t['title']}", "",
                f"**Score {t['score']}** · saturation {t['saturation']}", "",
                f"**Why now.** {t['why_now']}", ""]
        if t.get("who_is_talking"):
            out += [f"**Who is talking.** {t['who_is_talking']}", ""]
        out += [f"**Your angle.** {t['engineer_angle']}", "",
                f"**Working title:** {t['suggested_title']}  ",
                f"**Intent:** {t['suggested_intent']}", "",
                "**Takes to edit:**"]
        out += [f"- {x}" for x in t.get("suggested_take", [])]
        out += ["", "**Evidence:**"]
        out += [f"- [{e['title']}]({e['url']}) - {e['source']}, {e['signal']}" for e in t["evidence"]]
        out.append("")
    if radar.get("skipped"):
        out += ["## Left out", ""] + [f"- {x}" for x in radar["skipped"]] + [""]
    return "\n".join(out)


def write_radar(radar: dict, output_dir: Path, days: int, signal_count: int) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = TODAY.strftime("%Y-%m-%d")
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "days": days, "lens": RADAR_LENS, "signals": signal_count, **radar,
    }
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    json_path = output_dir / f"radar_{stamp}.json"
    json_path.write_text(text, encoding="utf-8")
    # The app and the weekly callback read the latest by a fixed name.
    (output_dir / "radar_latest.json").write_text(text, encoding="utf-8")
    md_path = output_dir / f"radar_{stamp}.md"
    md_path.write_text(format_radar(radar, days, signal_count, stamp), encoding="utf-8")
    return md_path, json_path


def run_radar(output_dir: Path, days: int = RADAR_DAYS):
    reset_usage()
    print(f"\n{'='*60}")
    print("Topic Radar")
    print(f"Window  : last {days} days")
    print(f"Lens    : {RADAR_LENS}")
    print(f"Output  : {output_dir}")
    print(f"{'='*60}")

    log("RADAR 1", "Forums: Hacker News and Reddit")
    hn = _hn_top(days)
    print(f"  Hacker News: {len(hn)} stories")
    reddit = _reddit_top(days)
    print(f"  Reddit: {len(reddit)} posts")

    log("RADAR 2", "YouTube, podcasts and newsletters (Claude web search)")
    try:
        web = _radar_web_scan(days)
    except ClaudeError as e:
        print(f"  Web scan failed ({str(e)[:120]}); continuing with the forums only.")
        web = []
    print(f"  Web scan: {len(web)} items")

    signals = web + hn + reddit
    if not signals:
        raise ClaudeError("The radar found no signals at all. Check the network and the API key.")

    log("RADAR 3", f"Synthesising {len(signals)} signals into themes")
    decisions = load_decisions(output_dir)
    if decisions:
        print(f"  Remembering {len(decisions)} earlier decision(s)")
    radar = synthesize_radar(signals, days, decisions)
    md_path, json_path = write_radar(radar, output_dir, days, len(signals))
    stamp = TODAY.strftime("%Y-%m-%d")
    usage_path = write_usage(f"radar_{stamp}", output_dir, "Topic radar")

    print(f"\n{'='*60}")
    print("DONE")
    for i, t in enumerate(radar["themes"], 1):
        print(f"  {i}. [{t['score']:3d}] {t['title']}  ({t['saturation']} saturation, "
              f"{len(t['evidence'])} sources)")
    if not radar["themes"]:
        print("  No theme had two sources behind it. Try a longer window with --radar-days 30.")
    print(f"  Radar      : {md_path}")
    print(f"  Radar JSON : {json_path}")
    print(f"  Usage JSON : {usage_path}")
    print_usage_summary()
    print(f"{'='*60}\n")
    return md_path, json_path


# ---------------------------------------------------------------------------
# Dig in: deep research on one radar theme
# ---------------------------------------------------------------------------
#
# The radar knows what people are talking about; it has not read the
# arguments. Dig in takes one theme and reads them: the Hacker News comment
# threads (Algolia's item API), the Reddit threads (feeds, when they answer),
# the episode and video pages and their transcripts, public LinkedIn posts
# and articles, and practitioners' own write-ups. It returns a one-page brief
# - the strongest claims with quotes, the counter-arguments, what people who
# ran it reported, the numbers, the questions nobody answers - and a sharper
# angle, title, intent and takes. The brief is stored on the theme, so
# "Write this" picks it up.

DIG_MAX_COMMENTS = 30
DIG_SCHEMA = """{
  "summary": "<what this theme is really about once you have read the arguments, 2-3 plain sentences>",
  "claims": [ {"claim": "<a strong claim being made>", "who": "<who makes it>", "url": "<where>", "quote": "<verbatim, under 40 words>"} ],
  "counterarguments": [ {"point": "<the pushback>", "who": "<who>", "url": "<where>"} ],
  "practitioners_said": [ {"said": "<what someone who actually built or ran it reported>", "who": "<who>", "url": "<where>"} ],
  "numbers": [ {"value": "<the figure>", "what": "<what it measures>", "url": "<where>"} ],
  "linkedin": [ {"who": "<name and role>", "gist": "<what they argued>", "url": "<the public post or article>"} ],
  "unanswered": ["<a question the sources raise and nobody answers>"],
  "sharper_angle": "<the angle, now that you have read the arguments, 1-2 sentences>",
  "suggested_title": "<working title>",
  "suggested_intent": "<what the reader should be able to do after reading, one sentence>",
  "suggested_take": ["<first person, specific enough to disagree with>", "..."],
  "sources_opened": ["<url>", "..."]
}"""


def _strip_html(text: str) -> str:
    import html as html_lib
    return re.sub(r"\s+", " ", html_lib.unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def _hn_comments(discussion_url: str, limit: int = DIG_MAX_COMMENTS) -> list[str]:
    """Top-level comments and one level of replies from a Hacker News thread."""
    m = re.search(r"item\?id=(\d+)", discussion_url or "")
    if not m:
        return []
    try:
        r = requests.get(f"https://hn.algolia.com/api/v1/items/{m.group(1)}",
                         headers=_RADAR_UA, timeout=20)
        r.raise_for_status()
        item = r.json()
    except Exception as e:
        print(f"  Hacker News thread {m.group(1)} failed ({str(e)[:60]})")
        return []
    out: list[str] = []

    def walk(node: dict, depth: int):
        for c in node.get("children") or []:
            if len(out) >= limit:
                return
            text = _strip_html(c.get("text"))
            if len(text) >= 80:
                out.append(f"{c.get('author') or 'anon'}: {text[:600]}")
            if depth < 1:
                walk(c, depth + 1)

    walk(item, 0)
    return out[:limit]


def _reddit_comments(discussion_url: str, limit: int = 20) -> list[str]:
    """Comments from a Reddit thread's feed. Reddit rate-limits these hard, so
    an empty answer is normal, not an error."""
    if "reddit.com" not in (discussion_url or ""):
        return []
    import xml.etree.ElementTree as ET
    ns = {"a": "http://www.w3.org/2005/Atom"}
    time.sleep(REDDIT_PAUSE_SECS)
    try:
        r = requests.get(discussion_url.rstrip("/") + "/.rss", params={"limit": limit},
                         headers=_RADAR_UA, timeout=20)
        if r.status_code != 200 or b"<feed" not in r.content[:400]:
            print(f"  Reddit thread skipped (HTTP {r.status_code})")
            return []
        entries = ET.fromstring(r.content).findall("a:entry", ns)
    except Exception as e:
        print(f"  Reddit thread failed ({str(e)[:60]})")
        return []
    out = []
    for e in entries[1:]:                      # the first entry is the post itself
        body = _strip_html(e.findtext("a:content", default="", namespaces=ns))
        who = e.findtext("a:author/a:name", default="anon", namespaces=ns)
        if len(body) >= 60:
            out.append(f"{who}: {body[:500]}")
    return out[:limit]


def _gather_discussions(theme: dict) -> str:
    """Every forum thread behind the theme's evidence, read by code."""
    blocks = []
    for e in theme.get("evidence", []):
        d = e.get("discussion") or ""
        if "news.ycombinator.com" in d:
            comments = _hn_comments(d)
        elif "reddit.com" in d:
            comments = _reddit_comments(d)
        else:
            continue
        if comments:
            print(f"  {len(comments)} comments read: {str(e.get('title', ''))[:60]}")
            blocks.append(f"=== Discussion of: {e.get('title', '')} ({d}) ===\n"
                          + "\n".join(f"- {c}" for c in comments))
    return "\n\n".join(blocks)[:30000]


def _clean_dig(data: dict) -> dict:
    if not isinstance(data, dict):
        data = {}

    def rows(key: str, fields: tuple, url_required: bool = True) -> list[dict]:
        out = []
        for row in (data.get(key) or [])[:12]:
            if not isinstance(row, dict):
                continue
            cleaned = {f: " ".join(str(row.get(f, "") or "").split())[:400] for f in fields}
            if url_required and not cleaned.get("url", "").startswith("http"):
                continue
            if not any(cleaned[f] for f in fields if f != "url"):
                continue
            out.append(cleaned)
        return out[:8]

    return {
        "summary": " ".join(str(data.get("summary", "") or "").split())[:600],
        "claims": rows("claims", ("claim", "who", "url", "quote")),
        "counterarguments": rows("counterarguments", ("point", "who", "url")),
        "practitioners_said": rows("practitioners_said", ("said", "who", "url")),
        "numbers": rows("numbers", ("value", "what", "url")),
        "linkedin": rows("linkedin", ("who", "gist", "url")),
        "unanswered": [" ".join(str(x).split())[:300] for x in (data.get("unanswered") or [])
                       if str(x).strip()][:8],
        "sharper_angle": " ".join(str(data.get("sharper_angle", "") or "").split())[:400],
        "suggested_title": " ".join(str(data.get("suggested_title", "") or "").split())[:140],
        "suggested_intent": " ".join(str(data.get("suggested_intent", "") or "").split())[:300],
        "suggested_take": [" ".join(str(x).split())[:300] for x in (data.get("suggested_take") or [])
                           if str(x).strip()][:3],
        "sources_opened": [str(u).strip() for u in (data.get("sources_opened") or [])
                           if str(u).strip().startswith("http")][:30],
    }


def dig_theme(theme: dict, days: int = RADAR_DAYS) -> dict:
    log("DIG 1", "Reading the discussion threads")
    discussions = _gather_discussions(theme)
    if not discussions:
        print("  No forum thread could be read; working from the pages alone.")
    evidence = "\n".join(
        f"- {e.get('source', '')}: {e.get('title', '')} | {e['url']}"
        + (f" | discussion: {e['discussion']}" if e.get("discussion") else "")
        for e in theme.get("evidence", []))

    log("DIG 2", "Opening the sources, transcripts, LinkedIn and practitioners' write-ups")
    prompt = f"""You are doing the deep research on one theme for an author who writes for {RADAR_LENS}.
{date_context()}

THEME: {theme['title']}
WHY IT IS LIVE: {theme.get('why_now', '')}
THE ANGLE SO FAR: {theme.get('engineer_angle', '')}

EVIDENCE THE RADAR FOUND
{evidence}

WHAT PEOPLE SAID IN THE DISCUSSIONS (already read for you)
{discussions or '(no discussion threads could be read)'}

Do this, searching and opening pages:
1. Open every evidence URL above that is not a discussion thread and read what it
   actually claims.
2. For any podcast episode or video, find the transcript or show notes (search
   "<title> transcript") and read the part about this theme.
3. Search LinkedIn for public posts and articles by AI practitioners on this theme
   from the last {days} days, with queries like site:linkedin.com/posts <keywords>
   and site:linkedin.com/pulse <keywords>. Open only pages that display without a
   login; record who wrote it and what they argued.
4. Search for write-ups by people who actually built or ran the thing - engineering
   blogs, GitHub issues, postmortems - from the last {days} days.
5. From all of it, extract: the strongest claims with a verbatim quote and who made
   them; the counter-arguments; what practitioners reported; every number with its
   source; the questions nobody answers; and, now that you have read the arguments,
   a sharper angle, a title, an intent, and 2-3 first-person takes specific enough
   to disagree with.

Rules: only what you read on a page you opened or in the discussion text above;
every url real; quotes verbatim and under 40 words; at most 8 items per list.

Return ONLY valid JSON in exactly this shape:
{DIG_SCHEMA}"""
    data = _claude_web_call(prompt, max_tokens=16000, searches=14, fetches=12,
                            label="dig in", schema=DIG_SCHEMA)
    return _clean_dig(data)


def format_brief(theme: dict, brief: dict, stamp: str) -> str:
    out = [f"# Brief: {theme['title']}", "", f"_Dug on {stamp}. Radar score {theme.get('score', '?')}._", "",
           brief["summary"], "",
           f"**Sharper angle.** {brief['sharper_angle']}", "",
           f"**Working title:** {brief['suggested_title']}  ",
           f"**Intent:** {brief['suggested_intent']}", "",
           "**Takes to edit:**"] + [f"- {x}" for x in brief["suggested_take"]] + [""]
    sections = [
        ("What is being claimed", brief["claims"], lambda r: f"- {r['claim']} — {r['who']}: \"{r['quote']}\" ({r['url']})"),
        ("The pushback", brief["counterarguments"], lambda r: f"- {r['point']} — {r['who']} ({r['url']})"),
        ("What practitioners reported", brief["practitioners_said"], lambda r: f"- {r['said']} — {r['who']} ({r['url']})"),
        ("The numbers", brief["numbers"], lambda r: f"- **{r['value']}** — {r['what']} ({r['url']})"),
        ("On LinkedIn", brief["linkedin"], lambda r: f"- {r['who']}: {r['gist']} ({r['url']})"),
    ]
    for title, rows, fmt in sections:
        if rows:
            out += [f"## {title}", ""] + [fmt(r) for r in rows] + [""]
    if brief["unanswered"]:
        out += ["## Nobody answers", ""] + [f"- {q}" for q in brief["unanswered"]] + [""]
    if brief["sources_opened"]:
        out += ["## Sources opened", ""] + [f"- {u}" for u in brief["sources_opened"]] + [""]
    return "\n".join(out)


def write_brief(index: int, theme: dict, brief: dict, output_dir: Path) -> tuple[Path, Path]:
    """Save the brief and attach its essentials to the theme in radar_latest.json
    (and the dated copy), so the app and "Write this" see it."""
    stamp = TODAY.strftime("%Y-%m-%d")
    md_path = output_dir / f"radar_{stamp}_brief_{index}.md"
    json_path = output_dir / f"radar_{stamp}_brief_{index}.json"
    md_path.write_text(format_brief(theme, brief, stamp), encoding="utf-8")
    json_path.write_text(json.dumps({"theme": theme["title"], "index": index, **brief},
                                    indent=2, ensure_ascii=False), encoding="utf-8")
    attached = {
        "file": md_path.name, "json": json_path.name,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "summary": brief["summary"], "sharper_angle": brief["sharper_angle"],
        "suggested_title": brief["suggested_title"] or theme.get("suggested_title", ""),
        "suggested_intent": brief["suggested_intent"] or theme.get("suggested_intent", ""),
        "suggested_take": brief["suggested_take"] or theme.get("suggested_take", []),
        "unanswered": brief["unanswered"],
        "counts": {k: len(brief[k]) for k in
                   ("claims", "counterarguments", "practitioners_said", "numbers", "linkedin")},
    }
    latest = output_dir / "radar_latest.json"
    for path in {latest, output_dir / f"radar_{stamp}.json"}:
        if not path.exists():
            continue
        try:
            radar = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        themes = radar.get("themes") or []
        if 1 <= index <= len(themes) and themes[index - 1].get("title") == theme["title"]:
            themes[index - 1]["brief"] = attached
            path.write_text(json.dumps(radar, indent=2, ensure_ascii=False), encoding="utf-8")
    return md_path, json_path


def run_dig(output_dir: Path, index: int, days: int = RADAR_DAYS):
    latest = output_dir / "radar_latest.json"
    if not latest.exists():
        raise ClaudeError("No radar to dig into yet. Run --radar first.")
    radar = json.loads(latest.read_text(encoding="utf-8"))
    themes = radar.get("themes") or []
    if not 1 <= index <= len(themes):
        raise ClaudeError(f"--dig wants a theme number between 1 and {len(themes)}.")
    theme = themes[index - 1]
    reset_usage()
    print(f"\n{'='*60}")
    print("Dig in")
    print(f"Theme   : {index}. {theme['title']}")
    print(f"Sources : {len(theme.get('evidence', []))} from the radar")
    print(f"{'='*60}")
    brief = dig_theme(theme, days=days)
    md_path, json_path = write_brief(index, theme, brief, output_dir)
    usage_path = write_usage(f"radar_brief_{index}", output_dir, f"Dig in: {theme['title']}")
    c = {k: len(brief[k]) for k in ("claims", "counterarguments", "practitioners_said",
                                    "numbers", "linkedin", "unanswered")}
    print(f"\n{'='*60}")
    print("DONE")
    print(f"  Claims {c['claims']}, pushback {c['counterarguments']}, practitioners "
          f"{c['practitioners_said']}, numbers {c['numbers']}, LinkedIn {c['linkedin']}, "
          f"open questions {c['unanswered']}")
    print(f"  Angle      : {brief['sharper_angle'][:110]}")
    print(f"  Brief      : {md_path}")
    print(f"  Usage JSON : {usage_path}")
    print_usage_summary()
    print(f"{'='*60}\n")
    return md_path, json_path


# ---------------------------------------------------------------------------
# Step 2: Refine Title
# ---------------------------------------------------------------------------

def refine_title(title: str, keywords: str, research: dict, intent: str = "") -> str:
    log("STEP 2", "Refining title")

    secondary_kws = research.get("keywords", {}).get("secondary_keywords", [])
    intent_note = (
        f"\nWriter's intent (IMPORTANT — use this to stay on topic): {intent}\n"
        f"The revised title must reflect this intent. Do NOT overweight incidental "
        f"details or hardware/product names mentioned in the working title unless "
        f"they are genuinely central to the article's purpose.\n"
        if intent else ""
    )
    prompt = f"""Revise the blog post title to be more SEO-optimized and compelling.

Working title: {title}
Primary keyword: {keywords}
Secondary keywords: {", ".join(secondary_kws)}
Search intent: {research.get("search_intent")}
Writing style: {research.get("writing_style")}
Writing tone: {research.get("writing_tone")}
Article goal: {research.get("article_goal")}
{intent_note}
Rules:
- The title must clearly reflect what the article is ACTUALLY about
- Do not latch onto incidental details, hardware names, or asides from the working title
- Keep the primary subject (the main tool, concept, or framework) front and center

Return ONLY valid JSON:
{{
  "revised_title": "<improved title>",
  "reasoning": "<brief explanation>"
}}"""

    response = call_claude(prompt, max_tokens=4000)
    result = extract_json(response)
    refined = result.get("revised_title", title)
    print(f"  New title: {refined}")
    return refined


# ---------------------------------------------------------------------------
# Step 3: Key Takeaways
# ---------------------------------------------------------------------------

def generate_key_takeaways(title: str, keywords: str, research: dict) -> str:
    log("STEP 3", "Generating key takeaways")

    secondary_kws = research.get("keywords", {}).get("secondary_keywords", [])
    prompt = f"""Create 4–5 key takeaways for this article.

Title: {title}
Primary keyword: {keywords}
Secondary keywords: {", ".join(secondary_kws)}
Search intent: {research.get("search_intent")}
Semantic analysis: {json.dumps(research.get("semantic_analysis", {}))}
Writing style: {research.get("writing_style")}
Writing tone: {research.get("writing_tone")}
Article goal: {research.get("article_goal")}

Write the takeaways as a concise bullet list (4–5 items). Each should be a clear, actionable insight a reader will gain. Start each with "- "."""

    result = call_claude(prompt, max_tokens=4000)
    print(f"  Takeaways generated ({len(result.split(chr(10)))} lines).")
    return result


# ---------------------------------------------------------------------------
# Step 4: Outline
# ---------------------------------------------------------------------------

def generate_outline(title: str, keywords: str, research: dict, key_takeaways: str,
                     profile: dict | None = None) -> str:
    profile = profile or length_profile(None)
    log("STEP 4", f"Generating article outline - {profile['label']}")

    kw_data = research.get("keywords", {})
    secondary_kws = ", ".join(kw_data.get("secondary_keywords", []))
    semantic_kws = ", ".join(kw_data.get("semantic_keywords", []))
    long_tail_kws = ", ".join(kw_data.get("long_tail_keywords", []))

    prompt = f"""You are an expert SEO content strategist. Create a detailed article outline.

ARTICLE SPECIFICATIONS
Title: {title}
Primary Keyword: {keywords}
Target Word Count: {profile['words']} words
Writing Tone: {research.get("writing_tone")}
Writing Style: {research.get("writing_style")}

STRATEGIC FOUNDATION
Search Intent: {research.get("search_intent")}
Semantic Context: {json.dumps(research.get("semantic_analysis", {}))}
Article Goal: {research.get("article_goal")}
Hidden Insight to Weave In: {research.get("hidden_insight")}
Target Audience: {research.get("target_audience")}

KEY CONTENT ELEMENTS
Key Takeaways (must be featured prominently):
{key_takeaways}
{fact_pack_text(research)}
{take_block(research.get("take", ""))}
Build the sections around the evidence that actually exists in the fact pack. A
section the pack cannot support with at least one specific should be cut or
reframed, not padded. Note next to each section which fact ids it will use.
{LEVELS_BLOCK}
{internal_links_block(research.get("internal_links", []))}
{date_context()}

SEO KEYWORD STRATEGY
Primary Keyword: {keywords}
Secondary Keywords: {secondary_kws}
Semantic Keywords: {semantic_kws}
Long-tail Keywords: {long_tail_kws}

OUTLINE REQUIREMENTS
Produce a detailed markdown outline with:
1. H1 (the article title)
2. Introduction section ({profile['intro']} words)
3. {profile['sections']} H2 main sections, each with {profile['subsections']} H3 subsections,
   arranged as the three LEVELS above: the first H2 is Level 1, the last H2 before
   the FAQ is Level 3, the rest are Level 2. Write "Level: 1", "Level: 2" or
   "Level: 3" directly under each H2 so the writer knows the altitude.
4. For each section: brief description of what to cover (1–2 sentences)
5. Exactly one diagram marker inside the Level 1 section, and optionally one more
   in a Level 2 section where a process, a stack or a comparison is clearer drawn
   than described, each formatted as:
   [DIAGRAM: <title> | Shows: <the one thing the picture must make obvious>]
   and {profile['images']} image placement markers elsewhere (never in Level 1), formatted as:
   [IMAGE: <descriptive alt text> | Query: <google image search query>]
6. At least one comparison table, placed in whichever section it genuinely belongs
   to. Note its columns in the outline. Tables are the passage an answer engine is
   most likely to quote whole, so give it real rows: prices, versions, tradeoffs,
   or a this-vs-that. Do not invent a table where the topic has nothing to compare.
7. A FAQ section with {profile['faq']} questions. Each MUST be an H3 phrased as a real question
   ending in a question mark, and each answer must stand on its own without the
   surrounding page - they are extracted into FAQPage structured data.
8. Conclusion section ({profile['conclusion']} words with CTA)
9. Supplementary metadata block at the end:
   - URL slug suggestion
   - Internal links to place, chosen only from the INTERNAL LINKS list above (or
     "none" when that list is empty)
   - Keyword density targets

Format as clean markdown. Be specific — each section note should guide the writer clearly."""

    result = call_claude(prompt, max_tokens=8000)
    print(f"  Outline generated ({len(result.split(chr(10)))} lines).")
    return result


# ---------------------------------------------------------------------------
# Step 5: Write Content
# ---------------------------------------------------------------------------

def write_content(title: str, keywords: str, outline: str, research: dict,
                  key_takeaways: str, profile: dict | None = None) -> str:
    profile = profile or length_profile(None)
    log("STEP 5", f"Writing article content, target {profile['words']} words "
                  f"(this may take a moment...)")

    kw_data = research.get("keywords", {})
    secondary_kws = ", ".join(kw_data.get("secondary_keywords", []))

    system = f"""You are an expert content writer with a point of view. Write clear, structured, value-driven articles that rank well in search engines. Use active voice, short paragraphs (3–4 sentences max), and cite sources inline as 'Source: https://...' when referencing external data or studies. You never state a figure you cannot cite, and you never hedge a figure you can. {date_context()}
{style_block(research.get("style_samples", ""), research.get("voice_profile", ""))}"""

    prompt = f"""Write a complete, high-quality SEO article based on the inputs below.

INPUTS
Title: {title}
Primary Keyword: {keywords}
Secondary Keywords: {secondary_kws}
Outline to follow strictly:
{outline}

Key Takeaways (must be reflected in writing):
{key_takeaways}
{fact_pack_text(research)}
{take_block(research.get("take", ""))}{LEVELS_BLOCK}
WRITING CONTEXT
Writing Style: {research.get("writing_style")}
Writing Tone: {research.get("writing_tone")}
Search Intent: {research.get("search_intent")}
Hidden Insight to highlight: {research.get("hidden_insight")}
Target Audience: {research.get("target_audience")}
Article Goal: {research.get("article_goal")}

INSTRUCTIONS
1. Follow the outline structure strictly (H1, H2, H3 headings).
2. Keep each paragraph to 3–4 sentences maximum.
3. Integrate keywords naturally — no stuffing.
4. Cite sources inline where relevant: "Source: https://..."
5. Preserve all [IMAGE: ...] and [DIAGRAM: ...] markers from the outline exactly as-is — do not remove them.
6. Include the FAQ section and Conclusion from the outline. Every FAQ question must
   be an H3 ending in a question mark, and its answer must make sense quoted on its
   own - those pairs become FAQPage structured data.
7. Build any comparison table the outline calls for as a real markdown table with a
   header row. It is the passage most likely to be quoted whole by an answer engine.
8. Target {profile['words']} words total. This is a real constraint, not a
   suggestion: cut depth rather than sections, and never pad to reach it.
9. Bold key terms on first use.
10. End with a strong call-to-action.
11. Specifics come only from the FACT PACK, cited with the exact source_url. Where
    the pack is silent, say so or leave it out. A reader should never meet
    "typically", "approximately" or "several hundred" where a real number exists.
12. The AUTHOR'S TAKE items are not optional and not to be neutralised. Write them
    in first person where they belong.
13. Teach in layers, as the outline marks them. Level 1 is the simple version: an
    instructor talking to a smart beginner, one analogy, one concrete example, every
    term defined in plain words on first use, sentences mostly under 15 words. Level 2
    is for practitioners. Level 3 is where it gets hard, and where most of the
    AUTHOR'S TAKE belongs. Do not write "Level: n" into the article itself.
14. Keep every [DIAGRAM: ... | Shows: ...] marker exactly where the outline puts it.
15. Internal links only to the URLs in INTERNAL LINKS, if any. Never write a link
    whose target is "#" or a page that does not exist.
{internal_links_block(research.get("internal_links", []))}
Write the full article now. Output the article content ONLY."""

    # `system` was built and never sent before this change, so the writer had
    # no persona, no citation rule and (now) no style samples. Send it.
    result = strip_placeholder_links(call_claude(prompt, system=system, max_tokens=16000))
    word_count = len(result.split())
    print(f"  Article written ({word_count} words).")
    return result


# ---------------------------------------------------------------------------
# Step 6: Humanize
# ---------------------------------------------------------------------------

_HUMANIZER_PATTERNS = """
## AI writing patterns to detect and fix

### Content patterns
1. Significance inflation — "stands as", "serves as a testament", "pivotal moment", "evolving landscape",
   "underscores", "highlights its importance", "setting the stage for", "indelible mark", "deeply rooted"
   → Replace with plain factual statements.

2. Notability puffery — "active social media presence", "written by a leading expert", "featured in X, Y, Z"
   → Keep only if specific and sourced; otherwise cut.

3. Superficial -ing analyses — tacking "-ing" participle phrases onto sentences to fake depth:
   "highlighting...", "symbolizing...", "contributing to...", "showcasing...", "underscoring..."
   → Delete or fold the point into the sentence directly.

4. Promotional language — "boasts", "vibrant", "rich cultural heritage", "nestled", "breathtaking",
   "groundbreaking", "renowned", "stunning", "must-visit"
   → Replace with neutral, specific description.

5. Vague attributions — "Experts argue", "Industry reports", "Some critics say", "Observers note"
   → Name the source or cut the claim.

6. Formulaic challenges sections — "Despite its X, it faces challenges… Despite these challenges…"
   → Describe the specific problem with specifics; drop the frame.

### Language / grammar patterns
7. AI vocabulary — additionally, align with, crucial, delve, emphasizing, enduring, enhance, fostering,
   garner, highlight (verb), interplay, intricate/intricacies, key (adj.), landscape (abstract), pivotal,
   showcase, tapestry, testament, underscore (verb), valuable, vibrant
   → Use plain alternatives or cut.

8. Copula avoidance — "serves as", "stands as", "marks", "represents", "boasts", "features", "offers"
   used where "is/are/has" would do → Replace with simple copulas.

9. Negative parallelisms — "Not only X but Y", "It's not just about X; it's about Y"
   → Flatten into a direct statement.

10. Rule of three overuse — forcing ideas into groups of three
    → Use as many items as there actually are.

11. Synonym cycling — rotating synonyms to avoid repeating a word ("the protagonist… the main character…
    the central figure… the hero") → Repeat the word or restructure.

12. False ranges — "from X to Y, from A to B" where X/Y aren't on a meaningful scale → List or summarize plainly.

### Style patterns
13. Em dash overuse — replace em dashes (—) with commas, parentheses, or restructured sentences where possible.

14. Excessive boldface — bold only terms that genuinely need emphasis; remove decorative bolding.

15. Inline-header bullet lists — "- **Speed:** Faster because…" → Convert to prose or clean bullets without bold headers.

16. Title Case In Headings — change to sentence case (first word + proper nouns only).

17. Emojis in headings/bullets → Remove unless they are in the original brand intro block.

18. Curly quotation marks → Keep as-is (they're fine); just don't introduce new ones inconsistently.

### Communication patterns
19. Chatbot artifacts — "Great question!", "I hope this helps!", "Let me know if…", "Here is a…"
    → Delete entirely.

20. Knowledge-cutoff disclaimers — "As of my last update…", "While specific details are limited…"
    → Delete or replace with a real source.

21. Sycophantic tone — "You're absolutely right", "That's an excellent point", "Of course!"
    → Delete.

### Filler and hedging
22. Filler phrases — "In order to" → "To"; "Due to the fact that" → "Because"; "At this point in time" → "Now";
    "It is important to note that" → cut it; "has the ability to" → "can".

23. Excessive hedging — "could potentially possibly be argued that… might" → pick one hedge or none.

24. Generic positive conclusions — "The future looks bright", "exciting times lie ahead", "a step in the right direction"
    → End with a specific fact, next step, or genuine observation.

### Voice and personality (beyond removing patterns)
- Vary sentence length. Short punchy sentences mixed with longer ones.
- Have opinions where appropriate — "I keep coming back to…", "Here's what gets me…"
- Acknowledge complexity — "This is impressive but also kind of unsettling."
- Be specific about feelings rather than vague ("there's something unsettling about…" not "this is concerning").
- Let some imperfection in — perfect parallel structure feels algorithmic.
"""


def humanize_content(content: str, research: dict | None = None) -> str:
    log("STEP 6", "Humanizing content (pass 1 — pattern removal)")

    system = (
        "You are an expert human editor. Your job is to make AI-generated writing sound like it was "
        "written by a knowledgeable, opinionated human blogger. You know every tell-tale AI pattern "
        "and ruthlessly eliminate them while keeping the article's structure, SEO value, and accuracy intact."
    )

    prompt = f"""Rewrite the article below to remove AI writing patterns and add genuine human voice.

STRUCTURAL CONSTRAINTS (never break these):
- Preserve ALL markdown headings (H1, H2, H3) exactly as written
- Preserve ALL [IMAGE: ...] and [DIAGRAM: ...] markers exactly — do not move, rename, or remove them
- Preserve ALL "Source: ..." citations exactly
- Keep short paragraphs (3–4 sentences max)
- Do NOT remove any sections or change the article structure
- Do NOT add new factual claims
- Do NOT change any number, price, date, version or "(Source: ...)" citation
- Do NOT soften, hedge or remove first-person opinions ("I think", "in my experience"):
  those are the author's own and are the point

{voice_block((research or {}).get("voice_profile", ""))}
AI PATTERN CHECKLIST — fix every instance you find:
{_HUMANIZER_PATTERNS}

ARTICLE TO REWRITE:
{content}

Return ONLY the rewritten article. No preamble, no commentary."""

    draft = call_claude(prompt, max_tokens=16000)
    print(f"  Pass 1 complete ({len(draft.split())} words). Running self-audit...")

    # Pass 2: self-audit and final polish
    log("STEP 6", "Humanizing content (pass 2 — self-audit)")

    audit_prompt = f"""You are a sharp editor. Read the article below and answer:

QUESTION 1: What still makes this obviously AI-generated? List the remaining tells as brief bullet points (5 words max each). If none, say "None found."

QUESTION 2: Now rewrite the article fixing those remaining tells. Apply the same structural constraints:
- Preserve ALL markdown headings (H1, H2, H3) exactly
- Preserve ALL [IMAGE: ...] and [DIAGRAM: ...] markers exactly
- Preserve ALL "Source: ..." citations exactly
- Keep paragraphs to 3–4 sentences max
- Do NOT add new factual claims or remove sections
{voice_block((research or {}).get("voice_profile", ""))}
Output format — use these exact labels:
REMAINING TELLS:
<bullet list or "None found">

FINAL ARTICLE:
<the full rewritten article>

ARTICLE:
{draft}"""

    audit_result = call_claude(audit_prompt, max_tokens=16000)

    # Extract the final article from the audit output
    if "FINAL ARTICLE:" in audit_result:
        tells_section = audit_result.split("FINAL ARTICLE:")[0]
        final = audit_result.split("FINAL ARTICLE:", 1)[1].strip()
        # Log the remaining tells for visibility
        if "REMAINING TELLS:" in tells_section:
            tells = tells_section.split("REMAINING TELLS:", 1)[1].strip()
            print(f"  Remaining tells fixed: {tells[:200]}")
    else:
        # Fallback: use the draft if audit output is malformed
        final = draft
        print("  Self-audit parse failed, using pass 1 output.")

    final = _strip_em_dashes(final)

    # Pass 3: repair the tells a scanner can name, rather than asking again in general.
    scan = scan_ai_tells(final)
    print_tell_scan(scan, "Scan after pass 2")

    uniform = scan["sentence_count"] > 4 and scan["sentence_cv"] < 0.45
    if scan["total"] or uniform:
        log("STEP 6", "Humanizing content (pass 3 - targeted repair)")
        repaired = _strip_em_dashes(repair_ai_tells(final, scan))
        after = scan_ai_tells(repaired)
        print_tell_scan(after, "Scan after pass 3")
        # A repair pass that made the article worse is not a repair. Keep pass 2.
        if after["total"] > scan["total"]:
            print(f"  Pass 3 raised the count {scan['total']} -> {after['total']}; "
                  f"keeping the pass 2 text.")
        else:
            print(f"  Pass 3 removed {scan['total'] - after['total']} tell(s).")
            final = repaired
    else:
        print("  Scanner found nothing to repair.")

    word_count = len(final.split())
    print(f"  Humanized ({word_count} words).")
    return final


def repair_ai_tells(article: str, scan: dict) -> str:
    """Rewrite only the phrases the scanner named. Everything else stays put."""
    report = format_tell_report(scan)

    prompt = f"""A scanner found these AI tells in your article. Fix each one where it is
genuinely a tell, and leave it alone where the word is doing real work.

WHAT THE SCANNER FOUND
{report}

These are candidates, not verdicts. A scanner cannot read context: "key" in "API key" is
correct, a heading of proper nouns is not title case, and a technical term with no plain
synonym should stay. Judge each one, then fix the genuine ones.

STRUCTURAL CONSTRAINTS (never break these):
- Preserve ALL markdown headings unless the finding is that a heading is title-cased,
  in which case change only its capitalisation
- Preserve ALL [IMAGE: ...] and [DIAGRAM: ...] markers exactly
- Preserve ALL "Source: ..." citations exactly
- Do NOT add new factual claims, and do NOT remove sections
- Do NOT rewrite sentences that contain none of the phrases above, except where the
  finding is that sentence length is too uniform

If the scanner reported uniform sentence length, vary it for real: cut some sentences to
under eight words, let others run long. Do not simply split every sentence in half.

ARTICLE
{article}

Return ONLY the revised article. No preamble, no list of what you changed."""

    return call_claude(prompt, max_tokens=16000)


def _strip_em_dashes(text: str) -> str:
    """
    Replace em dashes with natural punctuation.
    Rules:
      " — "  (spaced em dash mid-sentence)  → ", "
      "—"    (tight em dash, e.g. compound) → "-"
    Headings get their own rule. A comma reads wrong in a heading, so a spaced em
    dash there becomes a colon, or a hyphen when the heading already has one. This
    used to skip headings entirely, which is why every shipped article still had
    nine to thirteen em dashes in its section titles - the exact tell the verifier
    is told to look for.
    Image markers and source citations are still skipped: those are structural
    strings the rest of the pipeline matches on, not prose.
    """
    lines = text.split("\n")
    result = []
    for line in lines:
        stripped = line.lstrip()
        if (stripped.startswith(("[IMAGE:", "[DIAGRAM:"))
                or stripped.startswith("*Source:")
                or stripped.startswith("Source:")
                or stripped == "---"):
            result.append(line)
            continue
        if stripped.startswith("#"):
            if "—" in line:
                sep = " - " if ":" in line else ": "
                line = line.replace(" — ", sep).replace("—", "-")
            result.append(line)
            continue
        # Spaced em dash: a comma when the right-hand side is a fragment, a
        # semicolon when it is a whole clause. Blindly using a comma produced
        # splices such as "they are course-bound credentials, they validate what
        # you learned" in every shipped article.
        line = _replace_spaced_em_dashes(line)
        # Tight em dash → hyphen (compound words / ranges)
        line = line.replace("—", "-")
        result.append(line)

    removed = text.count("—")
    if removed:
        print(f"  Em dashes removed/replaced: {removed}")
    return "\n".join(result)


# Words that open a dependent fragment rather than a new clause. A dash followed
# by one of these reads correctly as a comma.
_FRAGMENT_OPENERS = {
    "and", "but", "or", "nor", "so", "yet", "which", "who", "whose", "where",
    "when", "while", "because", "since", "although", "though", "unless", "until",
    "if", "as", "than", "like", "unlike", "especially", "particularly", "notably",
    "including", "such", "for", "from", "with", "without", "to", "at", "in", "on",
    "of", "by", "not", "no", "even", "just", "only", "mostly", "usually", "often",
    "e.g.", "i.e.", "e.g", "i.e", "the", "a", "an", "one", "two", "three",
}

_CLAUSE_SUBJECTS = {
    "it", "its", "they", "this", "that", "these", "those", "you", "we", "i",
    "he", "she", "there", "here", "most", "some", "each", "every", "many", "few",
    "nobody", "everyone", "everything", "nothing", "what", "my", "our", "your",
    "their", "his", "her",
}


def _replace_spaced_em_dashes(line: str) -> str:
    def choose(m: re.Match) -> str:
        before = m.group(1)
        after = m.group(2)
        right = after.strip()
        first = right.split(" ", 1)[0].lower().strip("\"'([")
        rest_words = right.split()
        if first in _FRAGMENT_OPENERS or len(rest_words) < 4:
            return f"{before}, {after}"
        # A capitalised opener or a pronoun/determiner subject followed by a verb
        # is a clause of its own: join with a semicolon, never a comma.
        looks_like_clause = (
            first in _CLAUSE_SUBJECTS
            or (right[:1].isupper() and not right.split(" ", 1)[0].isupper())
        )
        if looks_like_clause and not before.rstrip().endswith((",", ";", ":")):
            # Lower-case the clause opener after the semicolon, except the
            # pronoun "I" (and I'd / I've / I'm), which stays capitalised.
            if after[:1].isupper() and first in _CLAUSE_SUBJECTS and first != "i":
                after = after[0].lower() + after[1:]
            return f"{before}; {after}"
        return f"{before}, {after}"

    # Handle every " — " on the line, left to right.
    while " — " in line:
        new = re.sub(r"^(.*?) — (.*)$", choose, line, count=1)
        if new == line:
            line = line.replace(" — ", ", ", 1)
        else:
            line = new
    return line


# ---------------------------------------------------------------------------
# Deterministic AI-tell scanner
# ---------------------------------------------------------------------------
#
# The self-audit in step 6 asks a model whether its own draft still reads as AI.
# That is the same judgment that produced the tells in the first place, and it
# has no way to be wrong out loud. This scanner is the boring counterweight: it
# holds no opinion, it counts. What it finds goes back to the model as an exact
# phrase list, so the repair pass fixes named strings instead of trying harder
# in general.
#
# These lists mirror the numbered items in _HUMANIZER_PATTERNS. Keep them in step.

_TELL_VOCAB = (
    # 7 - AI vocabulary
    "additionally", "crucial", "delve", "delves", "delving", "emphasizing",
    "enduring", "enhance", "enhances", "enhancing", "fostering", "garner",
    "interplay", "intricate", "intricacies", "pivotal", "showcase", "showcases",
    "showcasing", "tapestry", "testament", "underscore", "underscores",
    "underscoring", "vibrant", "boasts", "nestled", "renowned", "groundbreaking",
    "breathtaking", "myriad", "realm", "seamless", "seamlessly", "robust",
    "leverage", "leveraging", "navigate", "navigating", "unlock", "unlocking",
    "harness", "harnessing", "elevate", "profound", "paramount", "meticulous",
    "meticulously", "bustling", "captivating", "unwavering", "transformative",
)

_TELL_PHRASES = (
    # 1 - significance inflation
    "stands as", "serves as a testament", "pivotal moment", "evolving landscape",
    "setting the stage for", "indelible mark", "deeply rooted", "plays a vital role",
    "plays a crucial role", "in today's world", "in the world of",
    # 5 - vague attribution
    "experts say", "experts argue", "industry reports", "some critics say",
    "observers note", "studies show", "research suggests", "it is widely",
    # 6 / 24 - formulaic frames and conclusions
    "despite these challenges", "the future looks bright", "exciting times",
    "a step in the right direction", "only time will tell", "one thing is clear",
    "when it comes to", "at the end of the day",
    # 9 - negative parallelism
    "not only", "it's not just about", "it is not just about",
    # 19 / 21 / 22 - chatbot artifacts, sycophancy, filler
    "great question", "i hope this helps", "let me know if", "here is a",
    "you're absolutely right", "that's an excellent point",
    "it is important to note", "it's important to note", "in order to",
    "due to the fact that", "at this point in time", "has the ability to",
    "it is worth noting", "needless to say",
    # 20 - knowledge-cutoff disclaimers
    "as of my last update", "while specific details are limited",
)

# Words that stay lowercase in sentence case, so a heading full of them is not
# evidence of title casing.
_HEADING_STOPWORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into", "of",
    "on", "or", "the", "to", "vs", "with", "over", "via", "per",
}


def _scannable_lines(text: str) -> list[str]:
    """Body prose only. Citations, image markers and code are not the writer's voice."""
    lines, in_code = [], False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if (stripped.startswith(("[IMAGE:", "[DIAGRAM:"))
                or stripped.startswith("Source:")
                or stripped.startswith("*Source:")
                or stripped.startswith("> Source:")):
            continue
        lines.append(line)
    return lines


def _is_title_case(heading: str) -> bool:
    words = re.findall(r"[A-Za-z][A-Za-z'’-]*", heading)
    if len(words) < 3:
        return False
    # The first word is capitalised in both conventions, so it proves nothing.
    rest = [w for w in words[1:] if w.lower() not in _HEADING_STOPWORDS]
    if len(rest) < 2:
        return False
    capped = sum(1 for w in rest if w[0].isupper())
    return capped / len(rest) >= 0.7


def _sentence_lengths(lines: list[str]) -> list[int]:
    """Word counts per sentence, skipping headings, bullets and blank lines."""
    prose = [l for l in lines
             if l.strip() and not l.lstrip().startswith(("#", "-", "*", "|", ">"))]
    lengths = []
    for sentence in re.split(r"(?<=[.!?])\s+", " ".join(prose)):
        n = len(sentence.split())
        if n:
            lengths.append(n)
    return lengths


def scan_ai_tells(text: str) -> dict:
    """Count concrete AI tells. No model call, no judgment - just occurrences."""
    lines = _scannable_lines(text)
    body = "\n".join(lines)
    low = body.lower()

    hits = []

    for word in _TELL_VOCAB:
        n = len(re.findall(rf"\b{re.escape(word)}\b", low))
        if n:
            hits.append({"kind": "vocab", "phrase": word, "count": n})

    for phrase in _TELL_PHRASES:
        n = low.count(phrase)
        if n:
            hits.append({"kind": "phrase", "phrase": phrase, "count": n})

    structural = []
    title_cased = [l.strip() for l in lines
                   if l.lstrip().startswith("#") and _is_title_case(l.lstrip("# ").strip())]
    if title_cased:
        structural.append({"kind": "title_case_heading", "count": len(title_cased),
                           "examples": title_cased[:5]})

    inline_headers = [l.strip() for l in lines
                      if re.match(r"\s*[-*]\s+\*\*[^*]+:\*\*", l)]
    if inline_headers:
        structural.append({"kind": "inline_header_bullet", "count": len(inline_headers),
                           "examples": inline_headers[:5]})

    em_dashes = body.count("—")
    if em_dashes:
        structural.append({"kind": "em_dash", "count": em_dashes, "examples": []})

    emoji_headings = [l.strip() for l in lines
                      if l.lstrip().startswith("#")
                      and re.search(r"[\U0001F300-\U0001FAFF☀-➿]", l)]
    if emoji_headings:
        structural.append({"kind": "emoji_heading", "count": len(emoji_headings),
                           "examples": emoji_headings[:5]})

    # Uniform sentence length is the tell no wordlist catches. Human prose varies;
    # generated prose clusters around one comfortable length.
    lengths = _sentence_lengths(lines)
    cv = 0.0
    if len(lengths) > 4:
        mean = sum(lengths) / len(lengths)
        if mean:
            var = sum((n - mean) ** 2 for n in lengths) / len(lengths)
            cv = (var ** 0.5) / mean

    words = max(len(body.split()), 1)
    total = sum(h["count"] for h in hits) + sum(s["count"] for s in structural)

    return {
        "hits": sorted(hits, key=lambda h: -h["count"]),
        "structural": structural,
        "sentence_cv": round(cv, 3),
        "sentence_count": len(lengths),
        "words": words,
        "total": total,
        "per_1k": round(total / words * 1000, 2),
    }


def format_tell_report(scan: dict) -> str:
    """The scan as a phrase list a model can act on, most frequent first."""
    parts = []
    for h in scan["hits"][:40]:
        parts.append(f'- "{h["phrase"]}" x{h["count"]}')
    for s in scan["structural"]:
        line = f'- {s["kind"].replace("_", " ")} x{s["count"]}'
        for ex in s.get("examples", [])[:3]:
            line += f'\n    e.g. {ex[:90]}'
        parts.append(line)
    if scan["sentence_count"] > 4 and scan["sentence_cv"] < 0.45:
        parts.append(
            f'- sentence length is too uniform (variation {scan["sentence_cv"]}, '
            f'want 0.45+ across {scan["sentence_count"]} sentences)'
        )
    return "\n".join(parts)


def print_tell_scan(scan: dict, label: str):
    top = ", ".join(f'{h["phrase"]}x{h["count"]}' for h in scan["hits"][:6])
    print(f"  {label}: {scan['total']} tells ({scan['per_1k']}/1k words), "
          f"sentence variation {scan['sentence_cv']}")
    if top:
        print(f"    most frequent: {top}")
    for s in scan["structural"]:
        print(f"    {s['kind'].replace('_', ' ')}: {s['count']}")


# ---------------------------------------------------------------------------
# Step 7: Meta Description
# ---------------------------------------------------------------------------

def generate_meta(title: str, keywords: str, content: str) -> dict:
    log("STEP 7", "Generating SEO meta description")

    # Pass a trimmed preview of the article to stay within token limits
    content_preview = content[:3000]

    prompt = f"""Generate an SEO-optimized meta description for this article.

Title: {title}
Primary Keyword: {keywords}
Article Preview:
{content_preview}

Requirements:
- Exactly 150–160 characters including spaces
- Primary keyword in the first 30 characters, naturally integrated
- Include 1–2 secondary keywords organically
- Address what the reader will gain
- Sound conversational and human — not robotic

Return ONLY valid JSON:
{{
  "seo_meta": {{
    "title": "{title}",
    "description": "<150-160 char meta description>",
    "slug": "<url-friendly-slug>"
  }}
}}"""

    response = call_claude(prompt, max_tokens=4000)
    result = extract_json(response)
    meta = result.get("seo_meta", {})
    desc = meta.get("description", "")
    print(f"  Meta description ({len(desc)} chars): {desc[:80]}...")
    return meta


# ---------------------------------------------------------------------------
# Step 8: Image Search
# ---------------------------------------------------------------------------

def search_images(content: str, research: dict) -> dict[str, dict]:
    """
    Find image placements in the article and resolve URLs.
    Returns a dict mapping the original [IMAGE: ...] marker to image data.
    """
    log("STEP 8", "Resolving images")

    # Extract all [IMAGE: alt text | Query: search query] markers
    pattern = re.compile(r"\[IMAGE:\s*([^|]+)\|\s*Query:\s*([^\]]+)\]", re.IGNORECASE)
    markers = pattern.findall(content)

    if not markers:
        print("  No [IMAGE: ...] markers found in article.")
        return {}

    serpapi_key = os.getenv("SERPAPI_KEY")
    images = {}

    for alt_text, query in markers:
        alt_text = alt_text.strip()
        query = query.strip()
        marker_key = f"[IMAGE: {alt_text} | Query: {query}]"

        image_url = None
        source_url = None

        if serpapi_key:
            try:
                resp = requests.get(SERPAPI_BASE, params={
                    "engine": "google_images",
                    "q": query,
                    "api_key": serpapi_key,
                    "num": 3,
                }, timeout=15)
                resp.raise_for_status()
                img_results = resp.json().get("images_results", [])
                for top in img_results[:5]:
                    candidate = top.get("original") or ""
                    if usable_image_url(candidate):
                        image_url = candidate
                        source_url = top.get("source") or top.get("link")
                        break
                print(f"  [Google Images] {alt_text[:50]}: {image_url[:60] if image_url else 'no usable result'}")
            except Exception as e:
                print(f"  SerpAPI image search error ({e})")

        if not image_url:
            # No fallback: a search-page link or a blob URL is not an image, and
            # shipping one made the article look broken. The marker is dropped.
            print(f"  No usable image for: {alt_text[:50]}")
            continue

        images[marker_key] = {
            "alt": alt_text,
            "query": query,
            "url": image_url,
            "source": source_url,
        }

    print(f"  Resolved {len(images)} image(s).")
    return images


# ---------------------------------------------------------------------------
# Inject Images into Article
# ---------------------------------------------------------------------------

_BAD_IMAGE_HOSTS = ("media.licdn.com", "lookaside.", "fbsbx.com", "scontent.")


def usable_image_url(url: str) -> bool:
    """A URL a reader's browser can load a year from now: https, a real image
    path, not a blob, not a CDN link with an expiring token."""
    if not url or not url.startswith("https://"):
        return False
    low = url.lower()
    if low.startswith(("x-raw-image:", "data:")):
        return False
    if any(h in low for h in _BAD_IMAGE_HOSTS):
        return False
    if "&t=" in low and "e=" in low:          # signed, expiring
        return False
    path = low.split("?")[0]
    return path.endswith((".png", ".jpg", ".jpeg", ".webp", ".gif", ".avif")) or "/images/" in path or "/image" in path


def inject_images(content: str, images: dict[str, dict]) -> str:
    """Replace [IMAGE: ...] markers with actual markdown image blocks."""
    for marker, img in images.items():
        # Build markdown image with source attribution (matches sample article style)
        source_note = f"*Source: {img['source']}*"
        replacement = f"\n![{img['alt']}]({img['url']})\n{source_note}\n"

        # Match the marker even if the content slightly altered whitespace
        escaped = re.escape(marker)
        content = re.sub(escaped, replacement, content)

    return content


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

_IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".avif")


def _clean_url(url: str) -> str:
    """Trim the punctuation a regex drags along: 'https://x.com).' -> 'https://x.com'."""
    url = url.strip()
    while url and url[-1] in ").,;:'\"]>*":
        url = url[:-1]
    # A dangling "(" left by "(Source: https://x.com" without its close
    return url


def extract_sources(article: str) -> list[str]:
    """Every URL cited as evidence in the article, in order, once each.

    Image URLs are not sources: the picture is illustration, not support for a
    claim, and listing a CDN link with an expiring token under "Sources" made
    the earlier articles look padded.
    """
    image_urls = {_clean_url(m.group(1))
                  for m in re.finditer(r'!\[[^\]]*\]\((https?://[^\s\)]+)\)', article)}
    urls = []
    # (Source: https://...) and Source: https://... in any form
    for m in re.finditer(r'Source\s*:\s*\[?(https?://[^\s\)\]]+)', article):
        urls.append(_clean_url(m.group(1)))
    # Inline markdown links [text](url), excluding images
    for m in re.finditer(r'(?<!\!)\[[^\]]*\]\((https?://[^\s\)]+)\)', article):
        urls.append(_clean_url(m.group(1)))
    seen = set()
    result = []
    for u in urls:
        if not u or u in seen or u in image_urls:
            continue
        if u.lower().split("?")[0].endswith(_IMAGE_EXT):
            continue
        seen.add(u)
        result.append(u)
    return result


def strip_orphan_image_markers(article: str) -> str:
    """Remove any [IMAGE: ...] marker that survived image resolution.

    Markers without the "| Query:" half never match the resolver and used to
    ship verbatim in the body ("[IMAGE: Difficulty progression chart ...]").
    """
    cleaned = re.sub(r"^[ \t]*\[(?:IMAGE|DIAGRAM):[^\]\n]*\][ \t]*\n?", "", article,
                     flags=re.MULTILINE)
    cleaned = re.sub(r"\[(?:IMAGE|DIAGRAM):[^\]\n]*\]", "", cleaned)
    removed = (article.count("[IMAGE:") + article.count("[DIAGRAM:")
               - cleaned.count("[IMAGE:") - cleaned.count("[DIAGRAM:"))
    if removed:
        print(f"  Orphan image markers removed: {removed}")
    return re.sub(r"\n{3,}", "\n\n", cleaned)


# Domains whose display name is not just the second-level label capitalised.
_PUBLISHER_NAMES = {
    "arxiv.org": "arXiv", "nytimes.com": "The New York Times", "wsj.com": "The Wall Street Journal",
    "ft.com": "Financial Times", "bbc.co.uk": "BBC", "bbc.com": "BBC", "theverge.com": "The Verge",
    "techcrunch.com": "TechCrunch", "arstechnica.com": "Ars Technica", "github.com": "GitHub",
    "openai.com": "OpenAI", "anthropic.com": "Anthropic", "nvidia.com": "NVIDIA",
    "developer.nvidia.com": "NVIDIA Developer", "aws.amazon.com": "AWS", "cloud.google.com":
    "Google Cloud", "learn.microsoft.com": "Microsoft Learn", "en.wikipedia.org": "Wikipedia",
    "huggingface.co": "Hugging Face", "stackoverflow.com": "Stack Overflow",
}


def publisher_name(url: str) -> str:
    """A human name for the site behind a URL, for citations that read as citations."""
    host = re.sub(r"^www\.", "", re.sub(r"^https?://", "", url).split("/")[0].lower())
    if host in _PUBLISHER_NAMES:
        return _PUBLISHER_NAMES[host]
    for domain, name in _PUBLISHER_NAMES.items():
        if host.endswith("." + domain):
            return name
    label = host.split(".")[0] if host.count(".") <= 1 else host.split(".")[-2]
    if not label:
        return host
    # A three-letter domain is nearly always an acronym: idc, ibm, bbc, acm.
    if len(label) <= 3 and label.isalpha():
        return label.upper()
    return label.replace("-", " ").title()


def build_sources_section(article: str, accessed: str = "") -> str:
    """Sources as named, dated citations.

    A bare list of naked URLs is worth far less than the same list with a
    publisher and a date on it: answer engines weight attributable citations,
    and a reader cannot judge a link they cannot identify without clicking it.
    """
    urls = extract_sources(article)
    if not urls:
        return ""
    accessed = accessed or datetime.now().strftime("%B %d, %Y")
    lines = ["", "---", "", "## Sources", ""]
    for i, url in enumerate(urls, 1):
        lines.append(f"{i}. {publisher_name(url)} — [{url}]({url}) (accessed {accessed})")
    return "\n".join(lines) + "\n"


def parse_faq(article: str) -> list[dict]:
    """Pull question/answer pairs out of the article's FAQ section.

    Only the FAQ section, and only headings that are actually questions - a
    FAQPage schema containing things that are not questions is worse than none.
    """
    lines = article.split("\n")
    start = None
    for i, line in enumerate(lines):
        if re.match(r"^#{2,3}\s", line) and (
                "faq" in line.lower() or "frequently asked" in line.lower()):
            start = i + 1
            break
    if start is None:
        return []

    def clean(q: str) -> str:
        # Articles often label questions "Q: ...". The label is presentation;
        # a FAQPage question name that starts with "Q:" reads as malformed data.
        return re.sub(r"^\s*(Q\s*[:.\-]|Question\s*[:.\-])\s*", "", q).strip()

    faqs, question, answer = [], None, []
    for line in lines[start:]:
        heading = re.match(r"^(#{2,4})\s+(.*)", line)
        if heading:
            level, text = len(heading.group(1)), heading.group(2).strip()
            if question and answer:
                faqs.append({"question": question, "answer": " ".join(answer).strip()})
            question, answer = None, []
            if level <= 2:
                break                     # left the FAQ section
            if text.endswith("?"):
                question = clean(text)
            continue
        bold_q = re.match(r"^\*\*(.+\?)\*\*\s*$", line.strip())
        if bold_q:
            if question and answer:
                faqs.append({"question": question, "answer": " ".join(answer).strip()})
            question, answer = clean(bold_q.group(1)), []
            continue
        if question and line.strip() and not line.strip().startswith(("[IMAGE:", "[DIAGRAM:", "Source:", "!")):
            answer.append(line.strip())

    if question and answer:
        faqs.append({"question": question, "answer": " ".join(answer).strip()})
    return [f for f in faqs if f["answer"]]


def build_jsonld(slug: str, article: str, meta: dict, images: dict,
                 generated_at: str) -> str:
    """Article + FAQPage structured data.

    Everything here is already computed elsewhere in the pipeline and was
    previously written only to _meta.json, where no crawler will ever see it.
    """
    seo_title = meta.get("title") or ""
    description = meta.get("description") or ""
    canonical = f"{SITE_URL}/{slug}" if SITE_URL else ""

    article_node = {
        "@type": "Article",
        "headline": seo_title[:110],          # schema.org caps headline at 110 chars
        "description": description,
        "datePublished": generated_at,
        "dateModified": generated_at,
        "author": {"@type": "Person", "name": AUTHOR_NAME, "url": AUTHOR_URL},
        "publisher": {"@type": "Person", "name": AUTHOR_NAME, "url": AUTHOR_URL},
        "inLanguage": "en",
        "wordCount": len(article.split()),
    }
    if canonical:
        article_node["url"] = canonical
        article_node["mainEntityOfPage"] = {"@type": "WebPage", "@id": canonical}
    image_urls = [v["url"] for v in images.values() if str(v.get("url", "")).startswith("http")]
    if image_urls:
        article_node["image"] = image_urls[:6]
    citations = extract_sources(article)
    if citations:
        article_node["citation"] = [
            {"@type": "CreativeWork", "name": publisher_name(u), "url": u}
            for u in citations[:20]
        ]

    graph = [article_node]

    faqs = parse_faq(article)
    if faqs:
        graph.append({
            "@type": "FAQPage",
            "mainEntity": [
                {"@type": "Question", "name": f["question"],
                 "acceptedAnswer": {"@type": "Answer", "text": f["answer"]}}
                for f in faqs
            ],
        })

    payload = {"@context": "https://schema.org", "@graph": graph}
    # </script> inside a JSON string would close the tag early.
    return json.dumps(payload, indent=2, ensure_ascii=False).replace("</", "<\\/")


def generate_answer_block(title: str, article: str, research: dict) -> str:
    """A short, extractable answer placed directly under the H1.

    Answer engines quote the first self-contained passage that answers the
    query. Key takeaways are bullets about the article; this is an answer to the
    question, written to survive being lifted out of the page on its own.
    """
    log("STEP 6.4", "Writing the direct-answer block")

    kw = research.get("keywords", {})
    prompt = f"""Write the short answer that belongs directly under this article's title.

THE QUESTION A READER IS ASKING
{kw.get("primary_keyword", title)}

RULES
- 40 to 60 words. Not a word more.
- Answer the question in the first sentence. No preamble, no "in this article".
- Lead with a definition or a direct claim: "X is ...", "X costs ...", "Yes, because ...".
- Include the single most useful specific: a number, a price, a version, a timeframe,
  taken from the article's own cited facts. Never a range the article does not give.
- It must make complete sense quoted on its own, with no surrounding page.
- Plain sentences. No bullets, no heading, no bold, no em dashes.
- Claim nothing the article does not already support.
- {date_context()}

THE ARTICLE
{article[:6000]}

Return ONLY the answer paragraph."""

    answer = _strip_em_dashes(call_claude(prompt, max_tokens=600).strip())
    words = len(answer.split())
    print(f"  Answer block: {words} words")
    if words > 90:
        print("  Answer block came back too long; skipping it rather than "
              "burying the intro.")
        return ""
    return answer


def generate_linkedin_post(title: str, article: str, research: dict,
                           article_url: str = "") -> str:
    """A LinkedIn post drawn from the finished article.

    Written from the verified article rather than the topic, so the post can
    only claim things the article actually established - a post generated from
    the brief would be free to invent a statistic the article never supports.
    """
    log("STEP 9", "Writing the LinkedIn post")

    kw = research.get("keywords", {})
    link = article_url or (f"{SITE_URL}/{slugify(title)}" if SITE_URL else "")

    prompt = f"""Write a LinkedIn post for the article below, in the author's own voice.

WHO IS POSTING
Imran Tauqir, an engineer who builds with AI agents and writes about it. He posts
as a practitioner, not a commentator. He is not selling anything in this post.

WHAT THE POST HAS TO DO
Earn the click from someone scrolling past. LinkedIn shows roughly the first two
lines before "see more", so those two lines carry the entire post.

RULES
- 150 to 220 words. Longer gets truncated and skipped.
- Open with the single most surprising or useful specific thing in the article -
  a distinction, a number, a failure mode. Never open with a question, never with
  "I've been thinking about", never with "In today's world".
- One idea per line. Blank line between them. Dense paragraphs do not get read.
- Use only claims the article actually makes. Invent nothing.
- Plain language. No emoji except at most one, and only if it earns its place.
- No em dashes. No "game-changer", "unlock", "dive into", "leverage", "in the
  ever-evolving landscape".
- No engagement bait: no "thoughts?", no "agree?", no "comment below".
- End with one line pointing to the full article{f", linking {link}" if link else ""}.
- At most 3 hashtags, on the final line, specific rather than generic.

TOPIC
{kw.get("primary_keyword", title)}

THE ARTICLE
{article[:8000]}

Return ONLY the post text, ready to paste."""

    post = _strip_em_dashes(call_claude(prompt, max_tokens=1500).strip())
    words = len(post.split())
    print(f"  LinkedIn post: {words} words")
    if words > 320:
        print("  Post came back long; LinkedIn will truncate it in the feed.")
    return post


def generate_video_script(title: str, article: str, research: dict) -> str:
    """A 2-3 minute video script drawn from the finished article.

    Written as timed beats with a visual note per beat, because the failure mode
    of an AI-written script is a spoken list of abstractions that no footage can
    carry. Naming the visual next to the line forces the script to be about
    something showable.
    """
    log("STEP 10", "Writing the video script")

    kw = research.get("keywords", {})

    prompt = f"""Write a 2 to 3 minute video script from the article below.

WHO IS SPEAKING
Imran Tauqir, an engineer who builds with AI agents and writes about it. He
speaks to other engineers as a peer. Confident and plain-spoken, never hyped.

LENGTH
380 to 440 words of narration. That is 2:30 to 3:00 at a natural speaking pace.
Count them. Going over means the video runs long and gets abandoned halfway.

STRUCTURE
Six beats, each with a timestamp, the narration, and the visual that carries it.

1. HOOK, about 15 seconds. Open on the single most surprising or most useful
   specific in the article - a distinction people get wrong, a number, a failure
   mode. No throat-clearing, no "in today's world", no question.
2. THE CORE IDEA, about 30 seconds. Define the thing plainly.
3. WHY IT MATTERS, about 20 seconds. The problem it solves, concretely.
4. THE SUBSTANCE, about 45 seconds. The part a viewer could not have guessed.
5. THE DISTINCTION, about 30 seconds. The comparison or contrast the article
   makes best. This is the line people will repeat, so make it quotable.
6. WHAT BREAKS, AND CLOSE, about 30 seconds. Failure modes, then a single line
   pointing at the full article.

RULES
- Every claim must already be in the article. Invent nothing.
- Write for the ear. Short sentences. Vary their length. Contractions are fine.
- Do NOT narrate a list of abstract nouns. If a beat covers several components,
  give each one a concrete consequence rather than a label.
- No em dashes, no "delve", "unlock", "leverage", "game-changer",
  "in the ever-evolving landscape".
- The visual note must describe something actually showable: a diagram that
  builds, text on screen, a screen recording, a comparison filling in. Never
  "stock footage of a developer typing", which illustrates nothing.

TOPIC
{kw.get("primary_keyword", title)}

THE ARTICLE
{article[:10000]}

FORMAT - return exactly this markdown and nothing else:

# {title} - video script

**Runtime:** <your estimate>  **Narration:** <word count> words

## 1. Hook (0:00-0:15)
**Visual:** <what is on screen>

<the narration>

## 2. ... (and so on through beat 6)

---

## Narration only

<every narration block, in order, with nothing else - ready to paste into a
teleprompter or a text-to-speech tool>"""

    script = _strip_em_dashes(call_claude(prompt, max_tokens=4000).strip())

    # The narration block is what determines runtime, so measure that, not the
    # whole document with its headings and visual notes.
    tail = script.split("## Narration only")
    narration = tail[-1] if len(tail) > 1 else script
    words = len(narration.split())
    print(f"  Video script: {words} words of narration, "
          f"about {words // 150}:{(words % 150) * 60 // 150:02d} at 150 wpm")
    if words > 520:
        print("  That will run past three minutes.")
    return script


# ---------------------------------------------------------------------------
# Step 10.5: Voiceover, in the author's own voice
# ---------------------------------------------------------------------------
#
# The script's "Narration only" block is already written for the ear. This
# sends it to the author's cloned voice on ElevenLabs and saves the mp3 next
# to the script. Nothing else in the pipeline touches audio; without the two
# environment variables the step reports itself skipped and the run goes on.

ELEVENLABS_BASE = "https://api.elevenlabs.io/v1"
ELEVENLABS_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")


def narration_text(script: str) -> str:
    """The spoken lines only. Prefers the script's "## Narration only" block;
    otherwise keeps every beat's narration and drops headings, the Runtime
    line, the **Visual:** notes and rules. Bold and link markup are not spoken."""
    tail = script.split("## Narration only")
    if len(tail) > 1:
        text = tail[-1]
    else:
        kept = []
        for line in script.split("\n"):
            stripped = line.strip()
            if (not stripped or stripped.startswith("#") or stripped == "---"
                    or stripped.startswith(("**Visual:", "**Runtime:"))):
                continue
            kept.append(stripped)
        text = "\n".join(kept)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def generate_voiceover(script: str, slug: str, output_dir: Path) -> Path | None:
    log("STEP 10.5", "Recording the voiceover")
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    voice = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    if not key or not voice:
        print("  Skipped: set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in .env.")
        return None
    text = narration_text(script)
    if len(text.split()) < 20:
        print("  Skipped: no narration found in the script.")
        return None
    try:
        resp = requests.post(
            f"{ELEVENLABS_BASE}/text-to-speech/{voice}",
            headers={"xi-api-key": key, "accept": "audio/mpeg"},
            json={"text": text, "model_id": ELEVENLABS_MODEL,
                  "voice_settings": {"stability": 0.5, "similarity_boost": 0.8,
                                     "style": 0.2, "use_speaker_boost": True}},
            timeout=180,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        body = getattr(getattr(e, "response", None), "text", "") or ""
        print(f"  ElevenLabs request failed: {str(e)[:120]} {body[:200]}")
        return None
    if not resp.headers.get("content-type", "").startswith("audio"):
        print("  ElevenLabs returned no audio.")
        return None
    record_usage("elevenlabs", "elevenlabs-tts", len(text), 0)
    path = output_dir / f"{slug}_voiceover.mp3"
    path.write_bytes(resp.content)
    words = len(text.split())
    print(f"  Voiceover: {words} words, {len(text):,} characters (credits) -> "
          f"{path.name}, {len(resp.content) // 1024} KB, about "
          f"{words // 150}:{(words % 150) * 60 // 150:02d}")
    return path


# ---------------------------------------------------------------------------
# Step 11: The finished video
# ---------------------------------------------------------------------------
#
# The script and the voiceover were the ingredients; this is the dish. Each
# beat becomes one slide (a headline drawn from the narration, the diagram
# where it belongs, the brand) under that beat's narration in the author's
# voice, with captions burned in - most of a LinkedIn feed plays muted - and
# the whole thing rendered twice: 16:9 for YouTube and the LinkedIn feed,
# 9:16 for Shorts and Reels. ElevenLabs returns per-character timings with
# the audio, so the captions land on the word, not on a guess. ffmpeg does
# the assembly; Pillow draws the slides.

VIDEO_FORMATS = {"16x9": (1920, 1080), "9x16": (1080, 1920)}
CAPTION_MAX_CHARS = 42
_VIDEO_BG = "#0f1115"
_VIDEO_FG = "#ffffff"
_VIDEO_MUTED = "#9aa3ad"
_VIDEO_ACCENT = "#3b5bdb"


def video_beats(script: str) -> list[dict]:
    """The script's beats: title, visual note, narration lines."""
    beats, current = [], None
    for line in script.splitlines():
        if line.startswith("## Narration only"):
            break
        heading = re.match(r"^##\s+(.*)", line)
        if heading:
            if current:
                beats.append(current)
            current = {"title": heading.group(1).strip(), "visual": "", "lines": []}
            continue
        if current is None:
            continue
        visual = re.match(r"^\*\*Visual:\*\*\s*(.*)", line)
        if visual:
            current["visual"] = visual.group(1).strip()
        elif line.strip() and not line.startswith("---"):
            current["lines"].append(line.strip())
    if current:
        beats.append(current)
    beats = [b for b in beats if b["lines"]]
    for b in beats:
        # "## 2. The core idea (0:15-0:45)" -> "The core idea"
        b["label"] = re.sub(r"^\d+\.\s*", "", re.sub(r"\s*\([^)]*\)\s*$", "", b["title"])).strip()
        text = " ".join(b["lines"])
        text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
        b["narration"] = text.strip()
    return beats


def slide_headline(beat: dict) -> str:
    """What goes on the slide: the on-screen text the visual note names, else
    the narration's first sentence."""
    m = re.search(r'[Tt]ext on screen:?\s*["“](.+?)["”]', beat.get("visual", ""))
    if m:
        return m.group(1).strip()
    first = re.split(r"(?<=[.!?])\s+", beat.get("narration", ""))[0].strip()
    return first[:140]


def _tts_with_timestamps(text: str) -> tuple[bytes, list[tuple[str, float, float]]]:
    """The narration as mp3 plus (character, start, end) for every character."""
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    voice = os.getenv("ELEVENLABS_VOICE_ID", "").strip()
    resp = requests.post(
        f"{ELEVENLABS_BASE}/text-to-speech/{voice}/with-timestamps",
        headers={"xi-api-key": key},
        json={"text": text, "model_id": ELEVENLABS_MODEL,
              "voice_settings": {"stability": 0.5, "similarity_boost": 0.8,
                                 "style": 0.2, "use_speaker_boost": True}},
        timeout=240,
    )
    resp.raise_for_status()
    data = resp.json()
    record_usage("elevenlabs", "elevenlabs-tts", len(text), 0)
    import base64
    audio = base64.b64decode(data["audio_base64"])
    al = data.get("alignment") or {}
    chars = list(zip(al.get("characters", []),
                     al.get("character_start_times_seconds", []),
                     al.get("character_end_times_seconds", [])))
    return audio, chars


def _split_balanced(chars: list[tuple[str, float, float]], max_chars: int) -> list[list]:
    """Cut one sentence's timed characters into near-equal parts at spaces."""
    n = len(chars)
    if n <= max_chars * 1.25:          # a little over is one caption; the renderer wraps it
        return [chars]
    parts = -(-n // max_chars)
    target = n / parts
    out, start = [], 0
    for k in range(1, parts):
        ideal = int(round(target * k))
        # nearest space to the ideal cut, searching outward
        cut = None
        for d in range(0, max_chars):
            for cand in (ideal - d, ideal + d):
                if start < cand < n and chars[cand][0].isspace():
                    cut = cand
                    break
            if cut is not None:
                break
        if cut is None:
            break
        out.append(chars[start:cut])
        start = cut + 1
    out.append(chars[start:])
    return [part for part in out if part]


def caption_cues(chars: list[tuple[str, float, float]], max_chars: int = CAPTION_MAX_CHARS
                 ) -> list[tuple[float, float, str]]:
    """Group timed characters into caption lines: one sentence per caption,
    long sentences cut into balanced parts at spaces. Returns (start, end, text)."""
    sentences, buf = [], []
    for i, item in enumerate(chars):
        ch = item[0]
        if not buf and ch.isspace():
            continue
        buf.append(item)
        at_end = ch in ".!?" and (i + 1 == len(chars) or chars[i + 1][0].isspace())
        if at_end or i + 1 == len(chars):
            sentences.append(buf)
            buf = []
    cues = []
    for sentence in sentences:
        for part in _split_balanced(sentence, max_chars):
            text = "".join(c for c, _, _ in part).strip()
            if text:
                cues.append((part[0][1], part[-1][2], text))
    # A caption that vanishes the instant its last word ends reads as a flicker.
    out = []
    for n, (s, e, t) in enumerate(cues):
        nxt = cues[n + 1][0] if n + 1 < len(cues) else e + 0.6
        out.append((round(s, 3), round(min(e + 0.35, nxt), 3), t))
    return out


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt(cues: list[tuple[float, float, str]], path: Path):
    lines = []
    for n, (s, e, text) in enumerate(cues, 1):
        lines += [str(n), f"{_srt_time(s)} --> {_srt_time(e)}", text, ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_ass(cues: list[tuple[float, float, str]], path: Path, width: int, height: int):
    """Captions as ASS with the video's own resolution, so sizes are pixels and
    the placement is deterministic: bottom-centre, above the safe margin."""
    portrait = height > width
    size = int(height * (0.030 if portrait else 0.046))
    margin_v = int(height * (0.16 if portrait else 0.085))
    margin_lr = int(width * 0.07)

    def t(x: float) -> str:
        cs = int(round(x * 100))
        h, cs = divmod(cs, 360000)
        m, cs = divmod(cs, 6000)
        sec, cs = divmod(cs, 100)
        return f"{h}:{m:02d}:{sec:02d}.{cs:02d}"

    head = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Cap,Arial,{size},&H00FFFFFF,&H00FFFFFF,&H00000000,&H99000000,-1,0,0,0,100,100,0,0,3,{max(2, size // 9)},0,2,{margin_lr},{margin_lr},{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = "".join(
        f"Dialogue: 0,{t(s)},{t(e)},Cap,,0,0,0,,{text.replace(chr(10), ' ')}\n" for s, e, text in cues)
    path.write_text(head + events, encoding="utf-8")


def _slide_font(size: int, bold: bool = False):
    from PIL import ImageFont
    for name in (("arialbd.ttf", "DejaVuSans-Bold.ttf") if bold else ("arial.ttf", "DejaVuSans.ttf")):
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            continue
    return ImageFont.load_default(size=size)


def _wrap_px(draw, text: str, font, max_w: float, max_lines: int) -> list[str]:
    words, lines, cur = text.split(), [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if draw.textlength(cand, font=font) <= max_w:
            cur = cand
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip(".,;:") + "…"
    return lines


def render_slide(beat: dict, index: int, total: int, size: tuple[int, int], path: Path,
                 diagram: Path | None = None, brand: str = ""):
    """One slide: brand and beat label at the top, the headline, the diagram
    where the beat calls for one, and room at the bottom for captions."""
    from PIL import Image, ImageDraw
    W, H = size
    portrait = H > W
    im = Image.new("RGB", (W, H), _VIDEO_BG)
    d = ImageDraw.Draw(im)
    pad = int(W * 0.06)
    unit = min(W, H) / 1080          # scale type against the short edge

    # Accent bar and header line
    d.rectangle([0, 0, W, int(10 * unit)], fill=_VIDEO_ACCENT)
    small = _slide_font(int(28 * unit))
    d.text((pad, int(44 * unit)), brand or "Humanly", font=small, fill=_VIDEO_MUTED)
    label = f"{index} / {total}  ·  {beat.get('label', '')}"
    d.text((W - pad, int(44 * unit)), label, font=small, fill=_VIDEO_MUTED, anchor="ra")

    caption_zone = int(H * (0.22 if portrait else 0.20))
    body_top = int(120 * unit)
    body_bottom = H - caption_zone

    wants_diagram = diagram is not None and diagram.exists() and (
        "diagram" in beat.get("visual", "").lower() or index == 2)
    head_size = int((58 if portrait else 62) * unit)
    head_font = _slide_font(head_size, bold=True)
    max_lines = 4 if portrait else 3
    lines = _wrap_px(d, slide_headline(beat), head_font, W - 2 * pad, max_lines)
    line_h = int(head_size * 1.22)
    text_h = line_h * len(lines)

    if wants_diagram:
        dg = Image.open(diagram).convert("RGB")
        # The diagram is 1200 wide with white ground; place it on a white panel.
        avail_h = body_bottom - body_top - text_h - int(48 * unit)
        avail_w = W - 2 * pad
        scale = min(avail_w / dg.width, avail_h / dg.height)
        if scale > 0.15:
            dg = dg.resize((int(dg.width * scale), int(dg.height * scale)))
            block_h = text_h + int(36 * unit) + dg.height
            y = body_top + max(0, (body_bottom - body_top - block_h) // 2)
            for ln in lines:
                d.text((pad, y), ln, font=head_font, fill=_VIDEO_FG)
                y += line_h
            y += int(36 * unit)
            x = (W - dg.width) // 2
            d.rounded_rectangle([x - 12, y - 12, x + dg.width + 12, y + dg.height + 12],
                                radius=int(18 * unit), fill="#ffffff")
            im.paste(dg, (x, y))
            im.save(path, "PNG")
            return
    # Headline only, vertically centred in the body
    y = body_top + max(0, (body_bottom - body_top - text_h) // 2)
    for ln in lines:
        d.text((pad, y), ln, font=head_font, fill=_VIDEO_FG)
        y += line_h
    im.save(path, "PNG")


def _ffmpeg() -> str | None:
    import shutil
    return shutil.which("ffmpeg")


def _run(cmd: list[str], cwd: Path):
    import subprocess
    r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    if r.returncode != 0:
        raise ClaudeError(f"ffmpeg failed: {(r.stderr or '')[-600:]}")


def _duration(path: Path, cwd: Path) -> float:
    import subprocess
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path.name], cwd=str(cwd), capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def make_video(script: str, slug: str, output_dir: Path, diagram: Path | None = None,
               formats: tuple[str, ...] = ("16x9", "9x16"),
               tts=None) -> dict:
    """Script -> per-beat narration with timings -> slides -> mp4 per format,
    with burned captions, plus the joined voiceover mp3 and an .srt.
    `tts` is injectable for tests; it defaults to ElevenLabs."""
    log("STEP 11", "Rendering the video")
    if not _ffmpeg():
        print("  Skipped: ffmpeg is not installed (apt-get install ffmpeg, or winget install ffmpeg).")
        return {}
    if tts is None:
        if not (os.getenv("ELEVENLABS_API_KEY", "").strip() and os.getenv("ELEVENLABS_VOICE_ID", "").strip()):
            print("  Skipped: set ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in .env.")
            return {}
        tts = _tts_with_timestamps
    beats = video_beats(script)
    if not beats:
        print("  Skipped: no beats found in the script.")
        return {}

    work = output_dir / f"{slug}_video"
    work.mkdir(parents=True, exist_ok=True)

    # 1. Narration per beat, with timings. Cached beside the render, so a
    #    re-render after a slide tweak costs no ElevenLabs credits.
    import hashlib
    cues, offset, seg_audio = [], 0.0, []
    for n, beat in enumerate(beats, 1):
        mp3 = work / f"beat_{n}.mp3"
        timing = work / f"beat_{n}.json"
        digest = hashlib.sha256(beat["narration"].encode("utf-8")).hexdigest()[:16]
        chars = None
        if mp3.exists() and timing.exists():
            try:
                cached = json.loads(timing.read_text(encoding="utf-8"))
                if cached.get("digest") == digest:
                    chars = [tuple(c) for c in cached["chars"]]
                    print(f"  Beat {n}: narration reused from the last render")
            except Exception:
                chars = None
        if chars is None:
            audio, chars = tts(beat["narration"])
            mp3.write_bytes(audio)
            timing.write_text(json.dumps({"digest": digest, "chars": chars}), encoding="utf-8")
        dur = _duration(mp3, work) or (chars[-1][2] if chars else 0.0)
        beat["duration"] = dur
        for s, e, text in caption_cues(chars):
            cues.append((s + offset, min(e, dur) + offset, text))
        offset += dur
        seg_audio.append(mp3)
        print(f"  Beat {n}: {len(beat['narration'].split())} words, {dur:.1f}s - {beat['label']}")
    total = offset
    srt = work / "captions.srt"
    write_srt(cues, srt)
    (output_dir / f"{slug}_captions.srt").write_text(srt.read_text(encoding="utf-8"), encoding="utf-8")

    # 2. The joined voiceover, so --mp4 does not pay for the narration twice
    (work / "audio.txt").write_text("".join(f"file '{p.name}'\n" for p in seg_audio), encoding="utf-8")
    _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", "audio.txt",
          "-c", "copy", f"../{slug}_voiceover.mp3"], work)

    # 3. Slides and segments per format, then one pass to join and burn captions
    out = {"captions": f"{slug}_captions.srt", "voiceover": f"{slug}_voiceover.mp3",
           "duration": round(total, 1), "beats": len(beats)}
    for fmt in formats:
        size = VIDEO_FORMATS[fmt]
        segs = []
        for n, beat in enumerate(beats, 1):
            slide = work / f"slide_{fmt}_{n}.png"
            render_slide(beat, n, len(beats), size, slide, diagram=diagram, brand=f"Humanly · {AUTHOR_NAME}")
            seg = work / f"seg_{fmt}_{n}.mp4"
            _run(["ffmpeg", "-y", "-loglevel", "error", "-loop", "1", "-framerate", "30", "-i", slide.name,
                  "-i", f"beat_{n}.mp3", "-c:v", "libx264", "-tune", "stillimage", "-preset", "veryfast",
                  "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                  "-t", f"{beat['duration']:.3f}",
                  "-vf", f"scale={size[0]}:{size[1]}", seg.name], work)
            segs.append(seg)
        (work / f"list_{fmt}.txt").write_text("".join(f"file '{p.name}'\n" for p in segs), encoding="utf-8")
        write_ass(cues, work / f"captions_{fmt}.ass", *size)
        final = f"{slug}_video_{fmt}.mp4"
        _run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", f"list_{fmt}.txt",
              "-vf", f"ass=captions_{fmt}.ass",
              "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", f"../{final}"], work)
        out[f"video_{fmt}"] = final
        print(f"  {fmt}: {final} ({(output_dir / final).stat().st_size // 1024} KB)")
    print(f"  Video: {len(beats)} beats, {total:.0f}s, {len(cues)} captions")
    return out


def generate_video_meta(title: str, script: str, article: str, research: dict,
                        beats: list[dict] | None = None) -> str:
    """YouTube title, description with chapters, tags, and a LinkedIn caption
    for the video post - all from the script, so nothing is claimed twice."""
    log("STEP 11.5", "Writing the YouTube and LinkedIn text for the video")
    beats = beats or video_beats(script)
    chapters, t = [], 0.0
    for b in beats:
        m, s = divmod(int(t), 60)
        chapters.append(f"{m}:{s:02d} {b['label']}")
        t += b.get("duration", 0.0)
    kw = research.get("keywords", {})
    prompt = f"""Write the publishing text for a short video made from the script below.
{date_context()}
{voice_block(research.get("voice_profile", ""))}
TOPIC: {kw.get("primary_keyword", title)}
ARTICLE TITLE: {title}
CHAPTERS (use exactly these timestamps):
{chr(10).join(chapters)}

THE SCRIPT
{script[:6000]}

Return exactly this markdown and nothing else:

# Video text: {title}

## YouTube title
<under 70 characters, the specific claim, no clickbait>

## YouTube description
<2-3 plain sentences on what the viewer learns, then a blank line, then the
chapters one per line as "m:ss Label", then a blank line, then "Full article: [link]">

## YouTube tags
<8-12 comma-separated tags>

## LinkedIn caption
<60-120 words in the author's voice for the post that carries this video:
open on the single most useful specific, one line on what the video shows,
end with a question that invites engineers to disagree. No hashtags in the
body; three at the end.>"""
    return _strip_em_dashes(call_claude(prompt, max_tokens=1500).strip())


def generate_thumbnail_copy(title: str, article: str, research: dict) -> dict:
    """Headline copy for the share card, drawn from the finished article.

    A thumbnail is read at a glance by someone scrolling past, so the copy is
    constrained hard: a label, two or three very short lines, and one line of
    substance. Anything longer stops being legible at feed size.
    """
    log("STEP 11", "Writing the thumbnail copy")

    kw = research.get("keywords", {})

    prompt = f"""Write the copy for a LinkedIn share card for the article below.

It is read at a glance, at about a third of full size, by someone scrolling. The
headline has to land the argument on its own.

RULES
- kicker: the subject, 3 to 5 words, no punctuation.
- lines: 2 or 3 headline lines. Each is AT MOST 22 characters including spaces -
  count them. Together they make one sentence or one contrast. Mark the
  connecting words (of, becomes, instead of, is not) as dim; the words carrying
  the meaning are not dim.
- subline: one sentence, at most 130 characters, saying something specific. Not a
  teaser, not a question, no "learn more". If the article makes a caveat worth
  keeping, keep it.
- No em dashes anywhere. No emoji. No hashtags.
- Every claim must already be in the article.

TOPIC
{kw.get("primary_keyword", title)}

THE ARTICLE
{article[:6000]}

Return ONLY valid JSON:
{{
  "kicker": "...",
  "lines": [{{"text": "...", "dim": false}}, {{"text": "...", "dim": true}}],
  "subline": "..."
}}"""

    copy = extract_json(call_claude(prompt, max_tokens=1500))

    # The model agrees to 22 characters and then writes 30. Truncating silently
    # would ship a broken card, so over-long lines are reported.
    lines = [l for l in (copy.get("lines") or []) if l.get("text")][:3]
    for line in lines:
        if len(line["text"]) > 26:
            print(f"  Line too long for the card ({len(line['text'])} chars): "
                  f"{line['text']}")
    copy["lines"] = lines or [{"text": title[:22], "dim": False}]
    copy["kicker"] = _strip_em_dashes(str(copy.get("kicker") or ""))[:44]
    copy["subline"] = _strip_em_dashes(str(copy.get("subline") or ""))[:150]
    print(f"  Kicker : {copy['kicker']}")
    print(f"  Lines  : {' / '.join(l['text'] for l in copy['lines'])}")
    return copy


def _svg_escape(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def _wrap(text: str, width: int) -> list[str]:
    """Greedy word wrap, for the subline."""
    words, lines, current = str(text).split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines[:3]


def build_thumbnail_svg(copy: dict) -> str:
    """The share card as one self-contained 1200x627 SVG.

    SVG rather than HTML so the page can rasterise it to PNG in the browser with
    a canvas, which means no headless browser has to exist on the server.
    """
    lines = copy.get("lines") or []
    y = 214 if len(lines) >= 3 else 250
    head = []
    for line in lines:
        colour = "#7a7a84" if line.get("dim") else "#ffffff"
        head.append(
            f'<text x="72" y="{y}" fill="{colour}" font-size="72" font-weight="800" '
            f'letter-spacing="-2">{_svg_escape(line.get("text", ""))}</text>')
        y += 86

    sub = []
    sy = y + 26
    for part in _wrap(copy.get("subline", ""), 52):
        sub.append(f'<text x="72" y="{sy}" fill="#b6b6bf" font-size="25">'
                   f'{_svg_escape(part)}</text>')
        sy += 36

    grid = "".join(
        f'<line x1="{x}" y1="0" x2="{x}" y2="627" stroke="#ffffff" stroke-opacity=".03"/>'
        for x in range(48, 1200, 48)) + "".join(
        f'<line x1="0" y1="{yy}" x2="1200" y2="{yy}" stroke="#ffffff" stroke-opacity=".03"/>'
        for yy in range(48, 627, 48))

    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="627"
     viewBox="0 0 1200 627" font-family="Segoe UI, Helvetica, Arial, sans-serif">
  <rect width="1200" height="627" fill="#0d0d0f"/>
  {grid}
  <rect x="0" y="0" width="8" height="627" fill="#6ee7a8"/>
  <text x="72" y="96" fill="#6ee7a8" font-size="17" font-weight="700"
        letter-spacing="2.6">{_svg_escape(str(copy.get("kicker", "")).upper())}</text>
  {"".join(head)}
  {"".join(sub)}
  <text x="72" y="566" fill="#e8e8ee" font-size="19" font-weight="700">{_svg_escape(AUTHOR_NAME)}</text>
  <text x="{72 + len(AUTHOR_NAME) * 11 + 18}" y="566" fill="#7c7c86" font-size="19">
    &#8226; {_svg_escape(AUTHOR_URL.replace("https://", "").strip("/"))}</text>
</svg>'''


def write_thumbnail(slug: str, copy: dict, output_dir: Path, title: str = "") -> Path:
    """A page holding the card, with a button that saves it as a 1200x627 PNG."""
    output_dir.mkdir(parents=True, exist_ok=True)
    svg = build_thumbnail_svg(copy)
    path = output_dir / f"{slug}_thumbnail.html"
    path.write_text(f'''<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<title>Thumbnail - {_svg_escape(title or slug)}</title>
<style>
  body {{ margin:0; background:#f5f5f5; font-family:"Segoe UI",Arial,sans-serif;
         display:flex; flex-direction:column; align-items:center; gap:18px; padding:30px; }}
  #card {{ box-shadow:0 4px 24px rgba(0,0,0,.25); max-width:100%; height:auto; }}
  .bar {{ display:flex; gap:10px; align-items:center; }}
  button {{ font:600 14px "Segoe UI",Arial; padding:10px 18px; border:none;
            border-radius:6px; background:#111; color:#fff; cursor:pointer; }}
  button:hover {{ background:#333; }}
  .note {{ font-size:13px; color:#777; max-width:640px; text-align:center; line-height:1.5; }}
</style></head><body>

{svg.replace("<svg ", '<svg id="card" ', 1)}

<div class="bar">
  <button onclick="savePng(1200,627)">Download 1200 &times; 627 (feed)</button>
  <button onclick="savePng(1280,720)">Download 1280 &times; 720 (article cover)</button>
</div>
<p class="note">The card is an SVG, so it is rasterised here in the browser
rather than on the server. Edit the text in this file and reload to respin it.</p>

<script>
function savePng(w, h) {{
  const svg = document.getElementById('card').outerHTML;
  const img = new Image();
  img.onload = () => {{
    const c = document.createElement('canvas');
    c.width = w; c.height = h;
    const ctx = c.getContext('2d');
    ctx.fillStyle = '#0d0d0f';
    ctx.fillRect(0, 0, w, h);
    // Letterbox rather than crop, so nothing is lost off the edge.
    const k = Math.min(w / 1200, h / 627);
    const dw = 1200 * k, dh = 627 * k;
    ctx.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
    c.toBlob(b => {{
      const a = document.createElement('a');
      a.href = URL.createObjectURL(b);
      a.download = '{slug}_' + w + 'x' + h + '.png';
      a.click();
    }}, 'image/png');
  }};
  img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svg);
}}
</script>
</body></html>''', encoding="utf-8")
    return path


def insert_answer_block(article: str, answer: str) -> str:
    """Put the answer immediately after the H1, before anything else."""
    if not answer:
        return article
    lines = article.split("\n")
    for i, line in enumerate(lines):
        if line.startswith("# "):
            rest = lines[i + 1:]
            # Skip blank lines so the block lands tight against the title.
            while rest and not rest[0].strip():
                rest.pop(0)
            return "\n".join(lines[:i + 1] + ["", answer, ""] + rest)
    return answer + "\n\n" + article


def wrap_with_branding(article: str, edition: int) -> str:
    """The newsletter greeting only when this is a newsletter edition; an
    article with edition 0 is a standalone post and starts at its title."""
    intro = AUTHOR_INTRO_TEMPLATE.format(edition=edition) if edition and edition > 0 else ""
    sources = build_sources_section(article)
    return intro + article + sources + AUTHOR_CTA


def write_outputs(slug: str, article: str, meta: dict, images: dict, output_dir: Path,
                  edition: int = 0, diagrams: dict | None = None):
    output_dir.mkdir(parents=True, exist_ok=True)

    # Wrap with author branding + sources
    branded = wrap_with_branding(article, edition)

    # Markdown article
    md_path = output_dir / f"{slug}.md"
    md_path.write_text(branded, encoding="utf-8")
    print(f"\n  Article saved: {md_path}")

    # Meta JSON
    generated_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    faqs = parse_faq(branded)
    meta_payload = {
        "generated_at": generated_at,
        "seo_meta": meta,
        "canonical": f"{SITE_URL}/{slug}" if SITE_URL else None,
        "author": {"name": AUTHOR_NAME, "url": AUTHOR_URL},
        "faq_count": len(faqs),
        "sources": [
            {"publisher": publisher_name(u), "url": u} for u in extract_sources(branded)
        ],
        "images": [
            {"alt": v["alt"], "url": v["url"], "source": v["source"]}
            for v in images.values()
        ],
    }
    meta_path = output_dir / f"{slug}_meta.json"
    meta_path.write_text(json.dumps(meta_payload, indent=2), encoding="utf-8")
    print(f"  Meta JSON saved: {meta_path}")

    # HTML export
    html_path = _write_html(slug, branded, output_dir, meta=meta, images=images,
                            generated_at=generated_at, diagrams=diagrams)
    print(f"  HTML saved:     {html_path}")
    print(f"  Structured data: Article"
          + (f" + FAQPage ({len(faqs)} questions)" if faqs else " (no FAQ found)")
          + ("" if SITE_URL else ", no canonical (set SITE_URL)"))

    # DOCX export
    docx_path = _write_docx(slug, branded, output_dir)
    print(f"  DOCX saved:     {docx_path}")

    return md_path, meta_path


def _linkify(text: str) -> str:
    """Convert bare URLs in text to HTML anchor tags."""
    return re.sub(
        r'(?<!["\(])(https?://[^\s<>")\]]+)',
        r'<a href="\1">\1</a>',
        text,
    )


def _esc(text: str) -> str:
    """Escape a value going into an HTML attribute."""
    return (str(text).replace("&", "&amp;").replace('"', "&quot;")
            .replace("<", "&lt;").replace(">", "&gt;"))


def _write_html(slug: str, branded: str, output_dir: Path, meta: dict | None = None,
                images: dict | None = None, generated_at: str = "",
                diagrams: dict | None = None) -> Path:
    try:
        import markdown as md_lib
    except ImportError:
        return None

    def replace_image_block(m):
        alt, img_url = m.group(1), m.group(2)
        src_txt = m.group(3).strip().lstrip('*Source:').strip().rstrip('*').strip()
        return (
            f'<figure>'
            f'<img src="{img_url}" alt="{alt}" style="max-width:100%;height:auto;">'
            f'<figcaption style="font-size:0.8em;color:#666;">'
            f'Source: {src_txt} &nbsp;|&nbsp; '
            f'<a href="{img_url}" style="color:#3366cc;word-break:break-all;">{img_url}</a>'
            f'</figcaption></figure>'
        )

    # A diagram block carries the SVG inline: crisp at any width, no file to host.
    by_src = {(d.get("png") or d.get("svg_name")): d for d in (diagrams or {}).values()}

    def replace_diagram_block(m):
        alt, src, cap = m.group(1), m.group(2), m.group(3).strip().rstrip("*").strip()
        d = by_src.get(src)
        inner = d["svg"] if d else (
            f'<img src="{src}" alt="{_esc(alt)}" style="max-width:100%;height:auto;">')
        return (f'<figure class="diagram">{inner}'
                f'<figcaption style="font-size:0.85em;color:#555;">Diagram: {cap}</figcaption>'
                f'</figure>')

    with_diagrams = re.sub(
        r'!\[([^\]]*)\]\(([^\)]+)\)\n\*Diagram:([^\n]+)\*',
        replace_diagram_block,
        branded,
    )
    src_patched = re.sub(
        r'!\[([^\]]*)\]\(([^\)]+)\)\n\*Source:([^\n]+)\*',
        replace_image_block,
        with_diagrams,
    )
    html_body = md_lib.markdown(src_patched, extensions=['tables', 'fenced_code'])
    html_body = _linkify(html_body)

    canonical = f"{SITE_URL}/{slug}" if SITE_URL else ""
    seo_title = (meta or {}).get("title") or slug.replace("-", " ").title()
    description = (meta or {}).get("description") or ""
    og_image = next((v["url"] for v in (images or {}).values()
                     if str(v.get("url", "")).startswith("http")), "")

    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{_esc(seo_title)}</title>",
    ]
    if description:
        head.append(f'<meta name="description" content="{_esc(description)}">')
    head.append(f'<meta name="author" content="{_esc(AUTHOR_NAME)}">')
    if canonical:
        head.append(f'<link rel="canonical" href="{_esc(canonical)}">')
    head += [
        '<meta property="og:type" content="article">',
        f'<meta property="og:title" content="{_esc(seo_title)}">',
    ]
    if description:
        head.append(f'<meta property="og:description" content="{_esc(description)}">')
    if canonical:
        head.append(f'<meta property="og:url" content="{_esc(canonical)}">')
    if og_image:
        head.append(f'<meta property="og:image" content="{_esc(og_image)}">')
    if generated_at:
        head.append(f'<meta property="article:published_time" content="{_esc(generated_at)}">')
    head.append(f'<meta property="article:author" content="{_esc(AUTHOR_NAME)}">')
    head.append('<meta name="twitter:card" content="summary_large_image">')
    head.append(f'<meta name="twitter:title" content="{_esc(seo_title)}">')
    if description:
        head.append(f'<meta name="twitter:description" content="{_esc(description)}">')
    if og_image:
        head.append(f'<meta name="twitter:image" content="{_esc(og_image)}">')

    jsonld = build_jsonld(slug, branded, meta or {}, images or {}, generated_at)
    head.append(f'<script type="application/ld+json">\n{jsonld}\n</script>')
    head_html = "\n".join(head)

    full_html = f"""<!DOCTYPE html>
<html lang="en"><head>
{head_html}
<style>
  body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 40px auto; padding: 0 20px; line-height: 1.7; color: #222; }}
  h1,h2,h3 {{ color: #111; }}
  a {{ color: #3366cc; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ccc; padding: 8px 12px; }}
  th {{ background: #f4f4f4; }}
  blockquote {{ border-left: 4px solid #ccc; margin: 0; padding: 0.5em 1em; color: #555; }}
  figure {{ margin: 1.5em 0; }}
  figcaption {{ margin-top: 6px; }}
  figure.diagram svg {{ max-width: 100%; height: auto; }}
  code {{ background: #f4f4f4; padding: 2px 5px; border-radius: 3px; font-size: 0.9em; }}
  ol li {{ margin-bottom: 4px; word-break: break-all; }}
</style>
</head><body>
{html_body}
</body></html>"""

    html_path = output_dir / f"{slug}.html"
    html_path.write_text(full_html, encoding="utf-8")
    return html_path


def _write_docx(slug: str, branded: str, output_dir: Path) -> Path:
    try:
        from docx import Document
        from docx.shared import Pt, RGBColor, Inches
        from docx.oxml.ns import qn
        import io, requests as req
    except ImportError:
        return None

    doc = Document()
    for s in doc.styles:
        try: s.font.name = 'Arial'
        except: pass
    for section in doc.sections:
        section.left_margin = section.right_margin = Inches(1.2)
        section.top_margin = section.bottom_margin = Inches(1)

    def set_arial(run, size=None):
        run.font.name = 'Arial'
        rPr = run._r.get_or_add_rPr()
        rFonts = rPr.find(qn('w:rFonts'))
        if rFonts is None:
            from docx.oxml import OxmlElement
            rFonts = OxmlElement('w:rFonts'); rPr.insert(0, rFonts)
        for attr in (qn('w:ascii'), qn('w:hAnsi'), qn('w:cs')):
            rFonts.set(attr, 'Arial')
        if size: run.font.size = size

    def add_inline(para, text):
        for part in re.split(r'(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)', text):
            if part.startswith('**') and part.endswith('**'):
                r = para.add_run(part[2:-2]); r.bold = True; set_arial(r)
            elif part.startswith('*') and part.endswith('*'):
                r = para.add_run(part[1:-1]); r.italic = True; set_arial(r)
            elif part.startswith('`') and part.endswith('`'):
                r = para.add_run(part[1:-1]); set_arial(r, Pt(10))
            else:
                r = para.add_run(part); set_arial(r)

    def embed_image(img_url, alt, src_txt, kind="Source"):
        # A diagram the pipeline drew lives next to the article, not on the web.
        local = output_dir / img_url
        if not img_url.startswith("http") and local.exists():
            try:
                doc.add_paragraph().add_run().add_picture(str(local), width=Inches(5.5))
                cap = doc.add_paragraph()
                cap.paragraph_format.space_after = Pt(12)
                r1 = cap.add_run(f"{kind}: {src_txt}"); r1.italic = True
                r1.font.color.rgb = RGBColor(0x55,0x55,0x55); set_arial(r1, Pt(9))
                return
            except Exception:
                pass
        try:
            resp = req.get(img_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
            resp.raise_for_status()
            if "image" in resp.headers.get("content-type","") and len(resp.content) > 1000:
                doc.add_paragraph().add_run().add_picture(io.BytesIO(resp.content), width=Inches(5.5))
                cap = doc.add_paragraph()
                cap.paragraph_format.space_after = Pt(12)
                r1 = cap.add_run(f"Source: {src_txt}  |  "); r1.italic = True
                r1.font.color.rgb = RGBColor(0x55,0x55,0x55); set_arial(r1, Pt(9))
                r2 = cap.add_run(img_url); r2.font.color.rgb = RGBColor(0x33,0x66,0xCC); set_arial(r2, Pt(9))
                return
        except: pass
        p = doc.add_paragraph()
        r = p.add_run(f"[ IMAGE: {alt} ]"); r.bold = True
        r.font.color.rgb = RGBColor(0x33,0x66,0xCC); set_arial(r, Pt(10))
        cap = doc.add_paragraph(); cap.paragraph_format.space_after = Pt(10)
        r1 = cap.add_run(f"Source: {src_txt}  |  "); r1.italic = True
        r1.font.color.rgb = RGBColor(0x55,0x55,0x55); set_arial(r1, Pt(9))
        r2 = cap.add_run(img_url); r2.font.color.rgb = RGBColor(0x33,0x66,0xCC); set_arial(r2, Pt(9))

    lines = branded.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if re.match(r'^-{3,}$', line.strip()): i += 1; continue
        img_m = re.match(r'!\[([^\]]*)\]\(([^\)]+)\)', line.strip())
        if img_m:
            alt, url = img_m.group(1), img_m.group(2)
            src_txt, kind = url, "Source"
            cap_m = (re.match(r'^\*(Source|Diagram):\s*(.*?)\*?$', lines[i+1].strip())
                     if i+1 < len(lines) else None)
            if cap_m:
                kind, src_txt = cap_m.group(1), cap_m.group(2); i += 1
            embed_image(url, alt, src_txt, kind); i += 1; continue
        if line.strip().startswith(('*Source:', '*Diagram:')): i += 1; continue
        if line.startswith('*') and line.endswith('*') and not line.startswith('**'):
            p = doc.add_paragraph(); r = p.add_run(line.strip('*')); r.italic = True; set_arial(r); i += 1; continue
        if line.startswith('# ') and not line.startswith('## '):
            h = doc.add_heading(line[2:], level=1); [set_arial(r) for r in h.runs]; i += 1; continue
        if line.startswith('## '):
            h = doc.add_heading(line[3:], level=2); [set_arial(r) for r in h.runs]; i += 1; continue
        if line.startswith('### '):
            h = doc.add_heading(line[4:], level=3); [set_arial(r) for r in h.runs]; i += 1; continue
        if line.startswith('|'):
            tbl_lines = []
            while i < len(lines) and lines[i].startswith('|'):
                if not re.match(r'^\|[-| :]+\|$', lines[i]): tbl_lines.append(lines[i])
                i += 1
            if tbl_lines:
                headers = [c.strip() for c in tbl_lines[0].strip('|').split('|')]
                tbl = doc.add_table(rows=1, cols=len(headers)); tbl.style = 'Table Grid'
                for j, h in enumerate(headers):
                    cell = tbl.rows[0].cells[j]; cell.text = ''
                    r = cell.paragraphs[0].add_run(h); r.bold = True; set_arial(r)
                for rl in tbl_lines[1:]:
                    cells = [c.strip() for c in rl.strip('|').split('|')]
                    rc = tbl.add_row().cells
                    for j, c in enumerate(cells[:len(headers)]): rc[j].text = c.replace('**','')
                doc.add_paragraph()
            continue
        if line.startswith('> '): p = doc.add_paragraph(style='Quote'); add_inline(p, line[2:]); i += 1; continue
        if line.startswith('- '): p = doc.add_paragraph(style='List Bullet'); add_inline(p, line[2:]); i += 1; continue
        if line.strip() == '': i += 1; continue
        p = doc.add_paragraph(); add_inline(p, line); p.paragraph_format.space_after = Pt(8); i += 1

    docx_path = output_dir / f"{slug}.docx"
    doc.save(docx_path)
    return docx_path


# ---------------------------------------------------------------------------
# Step 6.5: Verify -> Rebut -> Judge
#
# An independent auditor reads the finished article. Anything it flags goes
# back to the writer, which may accept the finding or dispute it. Disputes are
# settled by a third model that sees both sides and rules. Only findings that
# survive that process are applied.
# ---------------------------------------------------------------------------

VERIFY_SYSTEM = (
    "You are an independent editorial auditor. You did not write this article and you "
    "owe its author nothing. Find what is actually wrong with it: claims stated as fact "
    "without support, structure that drifted from the brief, AI writing tells that "
    "survived editing, coverage the brief required and the draft skipped. "
    "Do not pad the list with nitpicks - a short list of real problems beats a long list "
    "of style opinions. Report strict JSON only."
)

WRITER_SYSTEM = (
    "You are the writer who produced this article. An auditor has raised findings against "
    "it. Concede the ones that are right - defensiveness costs you nothing here and helps "
    "no one. Dispute only where the auditor is factually mistaken, misread the article, or "
    "is asserting a style preference as an error. Report strict JSON only."
)

JUDGE_SYSTEM = (
    "You are the deciding editor. An auditor and a writer disagree about specific findings "
    "on an article. You see the article, the finding, and the writer's response. Rule on "
    "each one. You are not splitting the difference and you are not deferring to either "
    "party - decide which reading of the text is correct. Report strict JSON only."
)


def verify_content(article: str, outline: str, key_takeaways: str, research: dict,
                   round_no: int = 1, agents: dict | None = None) -> dict:
    """Independent audit of the finished article. Returns {verdict, scores, issues}."""
    agents = agents or resolve_agents()
    auditor = agents["auditor"]
    log("STEP 6.5", f"Verification pass (round {round_no}) "
                    f"- auditor {auditor['model']} ({auditor['provider']})")

    kw = research.get("keywords", {})
    serp_context = research.get("serp_context") or "(no live SERP data was available)"

    prompt = f"""Audit the article below against the brief it was written from.

BRIEF IT WAS WRITTEN FROM
Primary keyword: {kw.get("primary_keyword", "")}
Secondary keywords: {", ".join(kw.get("secondary_keywords", []))}
Search intent: {research.get("search_intent")}
Target audience: {research.get("target_audience")}
Article goal: {research.get("article_goal")}

Required takeaways:
{key_takeaways}

Outline it was told to follow:
{outline}

What is currently ranking for this keyword:
{serp_context}
{fact_pack_text(research)}
{take_block(research.get("take", ""))}
{voice_block(research.get("voice_profile", ""))}
{LEVELS_BLOCK}
{date_context()}

WHAT TO CHECK
1. FACTUAL - Any claim presented as fact with no citation and no way for a reader to
   check it. Numbers, dates, prices, version names, and company claims are the highest
   risk. Flag anything you believe is outdated or wrong, and say why.
2. CITATIONS - "Source: <url>" lines that do not plausibly support the sentence they
   follow, or a bare domain (a homepage such as https://www.idc.com) used as if it
   were evidence. A citation must point at the page that states the figure.
7. PRECISION - A figure given as a range, or hedged with "typically", "approximately",
   "around", "several", "roughly", where the FACT PACK holds an exact value; and any
   number, price, date, version or code that appears in the article but in no fact.
   Both are high severity: they are the difference between a guide and a guess.
8. DATES - Any year treated as current or upcoming that is not {CURRENT_YEAR}; a
   past-year projection presented as a forecast; "in {CURRENT_YEAR - 1}" used to mean now.
9. VOICE - If an AUTHOR'S TAKE is given above, every item must appear in the body in
   first person with its substance intact. A missing or neutralised item is high
   severity. "I think", "I'd" and "in my experience" on a take item are the
   required first person, never a hedge to flag. If no take is given, skip this check. Where THE AUTHOR'S VOICE is
   described above, flag passages that read nothing like it (medium).
10. LAYERING - The first H2 after the introduction must be the simple version: a
   beginner could follow it, it has an analogy and a concrete example, it defines
   its terms, and it holds the [DIAGRAM: ...] marker. Flag jargon left undefined
   there, sentences a newcomer would have to reread, and a Level 3 section that
   never rises above what a beginner's guide would say.
3. STRUCTURE - Sections in the outline that are missing, merged, or renamed beyond
   recognition. Count the [IMAGE: ...] and [DIAGRAM: ...] markers still present and compare
   with the outline.
4. AI TELLS - Patterns that survived editing: significance inflation, vague attribution
   ("experts say"), participle padding, title case headings, em dashes inside headings,
   formulaic conclusions.
5. COVERAGE - Required takeaways that never actually land in the body, or a subtopic the
   ranking pages all cover and this article does not.
6. CONTRADICTION - Places where the article states two incompatible things.

ARTICLE
{article}

Return ONLY valid JSON in exactly this shape:
{{
  "verdict": "pass" or "revise",
  "scores": {{
    "factual_support": 0-10,
    "outline_fidelity": 0-10,
    "human_voice": 0-10,
    "coverage": 0-10
  }},
  "issues": [
    {{
      "id": "i1",
      "category": "factual|citation|structure|ai_tell|coverage|contradiction|precision|date|voice|layering",
      "severity": "high|medium|low",
      "quote": "<the exact phrase or heading from the article, under 15 words>",
      "problem": "<what is wrong, one sentence>",
      "fix": "<the specific change you want, one sentence>"
    }}
  ]
}}

Use "pass" only when there is nothing above low severity. Number the ids i1, i2, i3 in
order. Return at most 12 issues, most severe first."""

    response = call_agent(auditor, prompt, system=VERIFY_SYSTEM, max_tokens=16000)
    report = extract_json(response)

    issues = report.get("issues", []) or []

    # The loop that follows keys findings by id, so a finding the auditor left
    # unnumbered - or numbered the same as an earlier one - would vanish before
    # anyone argued about it. Give those a fresh id instead.
    seen = set()
    for issue in issues:
        iid = issue.get("id")
        if not iid or iid in seen:
            n = 1
            while f"x{n}" in seen:
                n += 1
            iid = f"x{n}"
            issue["id"] = iid
        seen.add(iid)

    scores = report.get("scores", {}) or {}
    if scores:
        print("  Scores: " + ", ".join(f"{k}={v}" for k, v in scores.items()))
    counts = {}
    for issue in issues:
        sev = issue.get("severity", "low")
        counts[sev] = counts.get(sev, 0) + 1
    summary = ", ".join(f"{n} {sev}" for sev, n in counts.items()) or "none"
    print(f"  Verdict: {report.get('verdict', 'revise')} ({summary})")
    for issue in issues:
        print(f"    [{issue.get('severity','?')}] {issue.get('id','?')} "
              f"{issue.get('category','?')}: {issue.get('problem','')[:110]}")
    return report


def writer_rebuttal(article: str, issues: list) -> dict:
    """Give the writer a right of reply. Returns {responses: [{id, stance, reason}]}."""
    log("STEP 6.5", f"Writer responding to {len(issues)} finding(s)")

    issue_block = json.dumps(
        [{k: i.get(k) for k in ("id", "category", "severity", "quote", "problem", "fix")}
         for i in issues],
        indent=2,
    )

    prompt = f"""An auditor raised these findings against your article.

FINDINGS
{issue_block}

YOUR ARTICLE
{article}

For each finding, decide:
- "accept" - the auditor is right, the change should be made.
- "dispute" - the auditor is wrong. Only use this when you can point to something concrete:
  the quoted text does not say what the auditor claims, the claim IS cited elsewhere in the
  article, the structure change was required by the brief, or the auditor is calling a
  deliberate stylistic choice an error.

A dispute with no concrete reason will be overruled, so do not dispute to save face.

Return ONLY valid JSON:
{{
  "responses": [
    {{"id": "i1", "stance": "accept" or "dispute", "reason": "<one sentence>"}}
  ]
}}

Include exactly one response per finding id."""

    response = call_claude(prompt, system=WRITER_SYSTEM, max_tokens=8000)
    result = extract_json(response)

    responses = result.get("responses", []) or []
    n_disputed = sum(1 for r in responses if r.get("stance") == "dispute")
    print(f"  Writer accepted {len(responses) - n_disputed}, disputed {n_disputed}.")
    for r in responses:
        if r.get("stance") == "dispute":
            print(f"    disputes {r.get('id')}: {r.get('reason','')[:110]}")
    return result


def judge_disputes(article: str, disputes: list, agents: dict | None = None) -> dict:
    """Settle contested findings with a third model. Returns {rulings: [...]}."""
    agents = agents or resolve_agents()
    judge = agents["judge"]
    log("STEP 6.5", f"Escalating {len(disputes)} dispute(s) to judge "
                    f"({judge['model']} / {judge['provider']})")

    case_block = json.dumps(disputes, indent=2)

    prompt = f"""An auditor and the writer disagree about the findings below. Rule on each.

CONTESTED FINDINGS
Each entry has the auditor's finding and the writer's reason for disputing it.
{case_block}

THE ARTICLE IN FULL
{article}

For each finding, read the article text yourself and decide who is right:
- "uphold" - the auditor's finding stands and the fix should be applied.
- "overrule" - the writer is right and the article should be left alone.

Judge the substance, not the confidence of either side. If the disputed text is a matter
of taste rather than accuracy or structure, overrule. If the writer's reason does not
survive a look at the actual text, uphold.

Return ONLY valid JSON:
{{
  "rulings": [
    {{"id": "i1", "ruling": "uphold" or "overrule", "reasoning": "<one sentence>"}}
  ]
}}

Include exactly one ruling per contested finding."""

    # call_agent carries the fallback: a judge outage must not destroy an article
    # that already cost a dozen calls to produce.
    response = call_agent(judge, prompt, system=JUDGE_SYSTEM, max_tokens=8000)
    result = extract_json(response)

    for r in result.get("rulings", []) or []:
        print(f"    {r.get('ruling','?').upper():8} {r.get('id','?')}: "
              f"{r.get('reasoning','')[:110]}")
    return result


def apply_fixes(article: str, upheld: list, research: dict | None = None) -> str:
    """Rewrite the article to address only the findings that survived."""
    log("STEP 6.5", f"Applying {len(upheld)} upheld finding(s)")

    fix_block = "\n".join(
        f"- [{i.get('severity','?')}] {i.get('quote','')}\n"
        f"  Problem: {i.get('problem','')}\n"
        f"  Fix: {i.get('fix','')}"
        for i in upheld
    )
    evidence = fact_pack_text(research) if research else ""
    take = take_block(research.get("take", "")) if research else ""
    voice = voice_block(research.get("voice_profile", "")) if research else ""

    prompt = f"""Revise the article to address the findings below. Change nothing else.

FINDINGS TO ADDRESS
{fix_block}
{evidence}{take}{voice}
STRUCTURAL CONSTRAINTS (never break these):
- Preserve ALL markdown headings unless a finding explicitly asks you to change one
- Preserve ALL [IMAGE: ...] and [DIAGRAM: ...] markers exactly
- Preserve ALL "Source: ..." citations except where a finding says one is wrong
- Keep paragraphs to 3-4 sentences
- Do NOT rewrite passages no finding mentions
- Do NOT invent a citation. If a finding says a claim is unsupported and you have no real
  source, soften the claim or cut it instead of attaching a made-up URL.
- When a finding asks for a precise figure, take it from the FACT PACK with its
  source_url. If the pack has no such fact, cut the figure rather than keep a guess.
- {date_context()}

ARTICLE
{article}

Return ONLY the revised article. No preamble, no list of what you changed."""

    revised = call_claude(prompt, max_tokens=16000)
    revised = _strip_em_dashes(revised)
    print(f"  Revised ({len(revised.split())} words).")
    return revised


def verification_loop(article: str, outline: str, key_takeaways: str, research: dict,
                      max_rounds: int = 2, record: dict | None = None) -> str:
    """Audit, argue, judge, fix - up to max_rounds times or until the audit passes.

    Pass a dict as `record` to keep the argument itself. Everything the three
    agents say is otherwise printed once and lost, which leaves you with a
    changed article and no way to see who changed it or why.
    """
    # Resolve the roster once so every round is argued by the same three agents.
    agents = resolve_agents()
    log("STEP 6.5", "Agents\n  " + describe_agents(agents))
    if len({a["provider"] for a in agents.values()}) == 1:
        print("  Warning: all three roles are on one vendor. The audit is weaker "
              "than it looks - set OPENAI_API_KEY or GEMINI_API_KEY.")

    if record is not None:
        record["agents"] = agents
        record["rounds"] = []
        record["started_at"] = datetime.now().isoformat()

    def close(outcome: str) -> str:
        if record is not None:
            record["outcome"] = outcome
            record["finished_at"] = datetime.now().isoformat()
        return article

    for round_no in range(1, max_rounds + 1):
        # The article at this point has cost a dozen calls to produce. A stage
        # whose whole job is to check it must not be the thing that destroys it,
        # so a failed round ends verification and keeps the text as it stands.
        try:
            report = verify_content(article, outline, key_takeaways, research,
                                    round_no, agents=agents)
        except ClaudeError as e:
            reason = " ".join(str(e).split())[:200]
            print(f"  Verification could not run: {reason}")
            print(f"  Keeping the article as written. It was not checked.")
            if record is not None:
                record["error"] = reason
            return close(f"verification failed on round {round_no}")

        issues = report.get("issues", []) or []

        entry = {"round": round_no, "verdict": report.get("verdict"),
                 "scores": report.get("scores", {}), "issues": issues,
                 "responses": [], "rulings": [], "applied": []}
        if record is not None:
            record["rounds"].append(entry)

        if report.get("verdict") == "pass" or not issues:
            print(f"  Verification passed on round {round_no}. No changes applied.")
            return close(f"passed on round {round_no}")

        by_id = {i.get("id"): i for i in issues if i.get("id")}
        try:
            rebuttal = writer_rebuttal(article, issues)
        except ClaudeError as e:
            print(f"  The writer could not answer: {' '.join(str(e).split())[:160]}")
            print("  Applying every finding unanswered, as silence implies.")
            rebuttal = {"responses": []}
        entry["responses"] = rebuttal.get("responses", []) or []

        upheld, disputed = [], []
        answered = set()
        for r in entry["responses"]:
            issue = by_id.get(r.get("id"))
            if not issue:
                continue
            answered.add(r.get("id"))
            if r.get("stance") == "dispute":
                disputed.append({**issue, "writer_reason": r.get("reason", "")})
            else:
                upheld.append(issue)
        # A finding the writer never answered is not a dispute - apply it.
        unanswered = [i for k, i in by_id.items() if k not in answered]
        entry["unanswered"] = [i.get("id") for i in unanswered]
        upheld += unanswered

        if disputed:
            try:
                rulings = judge_disputes(article, disputed, agents=agents)
            except ClaudeError as e:
                print(f"  The judge could not rule: {' '.join(str(e).split())[:160]}")
                print("  Unruled disputes leave the text standing.")
                rulings = {"rulings": []}
            entry["rulings"] = rulings.get("rulings", []) or []
            ruled = {r.get("id"): r.get("ruling") for r in entry["rulings"]}
            for issue in disputed:
                # An unruled dispute defaults to the writer keeping the text.
                if ruled.get(issue.get("id")) == "uphold":
                    upheld.append(issue)
                elif issue.get("id") not in ruled:
                    entry.setdefault("unruled", []).append(issue.get("id"))

        entry["applied"] = [i.get("id") for i in upheld]

        if not upheld:
            print("  Every finding was overruled. Article left as written.")
            return close(f"every finding overruled on round {round_no}")

        try:
            article = apply_fixes(article, upheld, research)
        except ClaudeError as e:
            reason = " ".join(str(e).split())[:200]
            print(f"  The fix pass failed: {reason}")
            print("  Keeping the last good version of the article.")
            if record is not None:
                record["error"] = reason
            return close(f"fix pass failed on round {round_no}")
        entry["words_after_fix"] = len(article.split())

    print(f"  Reached the {max_rounds}-round limit. Using the latest revision.")
    return close(f"hit the {max_rounds}-round limit")


# ---------------------------------------------------------------------------
# Step 6.5 review report
# ---------------------------------------------------------------------------

def format_review(record: dict, title: str = "") -> str:
    """The argument as a readable document: who said what, and what survived."""
    if not record.get("rounds"):
        return "# Verification review\n\nThe audit did not run.\n"

    heading = f"# Verification review: {title}" if title else "# Verification review"
    out = [heading, "", "## Who argued", "", "| Role | Model | Vendor |", "|---|---|---|"]
    for role, a in (record.get("agents") or {}).items():
        out.append(f"| {role} | `{a['model']}` | {a['provider']} |")
    out += ["", f"Outcome: **{record.get('outcome', 'unknown')}**", ""]

    for entry in record["rounds"]:
        out += [f"## Round {entry['round']} - verdict: {entry.get('verdict', '?')}", ""]
        scores = entry.get("scores") or {}
        if scores:
            out.append("| " + " | ".join(scores) + " |")
            out.append("|" + "---|" * len(scores))
            out.append("| " + " | ".join(str(v) for v in scores.values()) + " |")
            out.append("")

        issues = entry.get("issues") or []
        if not issues:
            out += ["No findings.", ""]
            continue

        stances = {r.get("id"): r.get("stance") for r in entry.get("responses") or []}
        reasons = {r.get("id"): r.get("reason", "") for r in entry.get("responses") or []}
        rulings = {r.get("id"): r.get("ruling") for r in entry.get("rulings") or []}
        why = {r.get("id"): r.get("reasoning", "") for r in entry.get("rulings") or []}
        applied = set(entry.get("applied") or [])

        for issue in issues:
            iid = issue.get("id")
            stance = stances.get(iid)
            out += [f"### {iid} - {issue.get('category', '?')} "
                    f"({issue.get('severity', '?')})", ""]
            if issue.get("quote"):
                out += [f'> {issue["quote"]}', ""]
            out.append(f"**Auditor:** {issue.get('problem', '')} "
                       f"_Wants:_ {issue.get('fix', '')}")
            if stance is None:
                out.append("**Writer:** did not respond - counted as accepted.")
            else:
                label = {"accept": "accepted", "dispute": "disputed"}.get(stance, stance)
                out.append(f"**Writer:** {label}. {reasons.get(iid, '')}")
            if iid in rulings:
                out.append(f"**Judge:** {rulings[iid]}. {why.get(iid, '')}")
            elif stance == "dispute":
                out.append("**Judge:** no ruling returned - the text stands.")
            out += ["", f"**Result:** {'applied' if iid in applied else 'not applied'}", ""]

    return "\n".join(out) + "\n"


def write_review(slug: str, record: dict, output_dir: Path, title: str = "") -> tuple:
    """Save the argument next to the article, as JSON and as something readable."""
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{slug}_review.json"
    md_path = output_dir / f"{slug}_review.md"
    json_path.write_text(json.dumps(record, indent=2, default=str), encoding="utf-8")
    md_path.write_text(format_review(record, title), encoding="utf-8")
    return md_path, json_path


def review_stats(record: dict) -> dict:
    """Headline numbers for the run summary."""
    stats = dict(rounds=0, raised=0, accepted=0, disputed=0, upheld=0,
                 overruled=0, applied=0)
    for entry in record.get("rounds", []):
        stats["rounds"] += 1
        stats["raised"] += len(entry.get("issues") or [])
        for r in entry.get("responses") or []:
            key = "disputed" if r.get("stance") == "dispute" else "accepted"
            stats[key] += 1
        for r in entry.get("rulings") or []:
            stats["upheld" if r.get("ruling") == "uphold" else "overruled"] += 1
        stats["applied"] += len(entry.get("applied") or [])
    return stats


# ---------------------------------------------------------------------------
# Main Pipeline
# ---------------------------------------------------------------------------

def run(title: str, keywords: str, output_dir: Path, edition: int = 0, intent: str = "",
        verify: bool = True, verify_rounds: int = 2, words: str = "default",
        linkedin: bool = False, video: bool = False, thumbnail: bool = False,
        take: str = "", facts: bool = True, diagram: bool = True,
        voiceover: bool = False, mp4: bool = False, from_theme: str = ""):
    profile = length_profile(words)
    take = (take or "").strip()
    if not take:
        print("  NOTE: no --take given. The article will carry no first-person point "
              "of view, which is the single biggest reason these read as generic.")
    # If intent is given and no explicit keywords, derive optimized search keywords
    if intent and not keywords:
        log("INTENT", "Extracting search keywords from intent...")
        keywords = extract_search_query(title, intent)
        print(f"  Derived keywords: {keywords}")
    elif not keywords:
        keywords = title

    print(f"\n{'='*60}")
    print(f"SEO Article Writer")
    print(f"Topic   : {title}")
    print(f"Keywords: {keywords}")
    if intent:
        print(f"Intent  : {intent[:80]}{'...' if len(intent) > 80 else ''}")
    print(f"Length  : {profile['label']}")
    print(f"Output  : {output_dir}")
    print(f"{'='*60}")

    # Step 1: SERP Research
    research = serp_research(title, keywords, intent=intent)
    research["take"] = take
    research["style_samples"] = load_style_samples()
    # The cache sits with the output, which on Fly is the persistent volume;
    # the code directory is rebuilt on every deploy.
    global VOICE_PROFILE_PATH
    VOICE_PROFILE_PATH = output_dir / ".voice_profile.json"
    research["voice_profile"] = build_voice_profile(research["style_samples"])
    research["internal_links"] = library_links(output_dir, exclude_title=title)

    # Step 1.5: Fact pack - open the primary pages and pin every specific to a URL.
    if facts:
        research["fact_pack"] = build_fact_pack(title, keywords, intent, research)
    else:
        log("STEP 1.5", "Fact pack skipped (--no-facts)")
        research["fact_pack"] = {"facts": [], "primary_sources": [], "gaps": [], "method": "skipped"}

    # Step 2: Refine Title
    refined_title = refine_title(title, keywords, research, intent=intent)

    # Step 3: Key Takeaways
    key_takeaways = generate_key_takeaways(refined_title, keywords, research)

    # Step 4: Outline
    outline = generate_outline(refined_title, keywords, research, key_takeaways,
                               profile=profile)

    # Step 5: Write Content
    content = write_content(refined_title, keywords, outline, research, key_takeaways,
                            profile=profile)

    # Step 6: Humanize
    humanized = humanize_content(content, research)

    # Step 6.2: the Level 1 section has to read like an instructor. Measured,
    # then rewritten on its own if it came out dense.
    explainer = check_explainer(humanized)
    if not explainer.get("found"):
        print("  WARNING: no [DIAGRAM: ...] marker survived, so there is no Level 1 section to check.")
    elif explainer.get("sentences"):
        print(f"  Level 1 section: {explainer['sentences']} sentences, mean {explainer['mean']} "
              f"words, longest {explainer['longest']}"
              + ("" if explainer["ok"] else " - too dense for a beginner"))
        if not explainer["ok"]:
            humanized = simplify_explainer(humanized, explainer, research)

    # Step 6.4: Direct-answer block. Inserted before verification, so the auditor
    # checks it against the brief like any other passage.
    humanized = insert_answer_block(
        humanized, generate_answer_block(refined_title, humanized, research)
    )

    # Step 6.5: Verify -> rebut -> judge -> fix
    record = {}
    if verify:
        humanized = verification_loop(
            humanized, outline, key_takeaways, research, max_rounds=verify_rounds,
            record=record,
        )
    else:
        log("STEP 6.5", "Verification skipped (--no-verify)")

    # Step 7: Meta
    meta = generate_meta(refined_title, keywords, humanized)

    slug = slugify(refined_title)

    # Step 8: Image Search
    images = search_images(humanized, research)

    # Step 8.5: Diagrams, drawn from the article's own [DIAGRAM: ...] markers
    if diagram:
        diagrams = render_diagrams(humanized, slug, output_dir)
    else:
        log("STEP 8.5", "Diagrams skipped (--no-diagram)")
        diagrams = {}

    # Inject images and diagrams, then drop any marker that found nothing
    final_article = strip_orphan_image_markers(
        inject_diagrams(inject_images(strip_placeholder_links(humanized), images), diagrams))

    # Write outputs. Diagrams ride along in the image list so _meta.json and the
    # callback payload know about them.
    all_images = dict(images)
    for marker, d in diagrams.items():
        all_images[marker] = {"alt": d["alt"], "url": d["png"] or d["svg_name"],
                              "source": "generated diagram", "query": ""}
    md_path, meta_path = write_outputs(slug, final_article, meta, all_images, output_dir,
                                       edition=edition, diagrams=diagrams)
    if from_theme:
        record_decision(output_dir, from_theme, "written", slug=slug)
        print(f"  Radar theme marked written: {from_theme[:70]}")

    # The evidence the article was held to, next to the article, so a reviewer
    # can check any figure without re-running the research.
    facts_path = output_dir / f"{slug}_facts.json"
    facts_path.write_text(json.dumps({
        "topic": title, "refined_title": refined_title, "intent": intent,
        "take": take, "fact_pack": research.get("fact_pack", {}),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    review_path = None
    if record.get("rounds"):
        review_path, _ = write_review(slug, record, output_dir, refined_title)
    linkedin_path = None
    if linkedin:
        post = generate_linkedin_post(refined_title, humanized, research)
        linkedin_path = output_dir / f"{slug}_linkedin.md"
        linkedin_path.write_text(post, encoding="utf-8")

    video_path = None
    voice_path = None
    video_files: dict = {}
    if video:
        script = generate_video_script(refined_title, humanized, research)
        video_path = output_dir / f"{slug}_video.md"
        video_path.write_text(script, encoding="utf-8")
        if mp4:
            # The video step records the narration beat by beat (with timings
            # for the captions) and joins it into the voiceover mp3 itself.
            first_diagram = output_dir / f"{slug}_diagram_1.png"
            video_files = make_video(script, slug, output_dir,
                                     diagram=first_diagram if first_diagram.exists() else None)
            if video_files:
                voice_path = output_dir / video_files["voiceover"]
                meta_text = generate_video_meta(refined_title, script, humanized, research,
                                                beats=video_beats(script))
                (output_dir / f"{slug}_video_meta.md").write_text(meta_text, encoding="utf-8")
        if voiceover and not voice_path:
            voice_path = generate_voiceover(script, slug, output_dir)

    thumb_path = None
    if thumbnail:
        copy = generate_thumbnail_copy(refined_title, humanized, research)
        thumb_path = write_thumbnail(slug, copy, output_dir, refined_title)

    usage_path = write_usage(slug, output_dir, refined_title)

    # Summary
    word_count = len(final_article.split())
    print(f"\n{'='*60}")
    print(f"DONE")
    print(f"  Title      : {refined_title}")
    print(f"  Word count : {word_count:,}")
    print(f"  Images     : {len(images)}")
    print(f"  Diagrams   : {len(diagrams)}")
    print(f"  Article    : {md_path}")
    print(f"  Meta JSON  : {meta_path}")
    fp = research.get("fact_pack", {})
    print(f"  Facts      : {facts_path} ({len(fp.get('facts', []))} facts via {fp.get('method')})")
    if review_path:
        s = review_stats(record)
        print(f"  Review     : {review_path}")
        print(f"  Argument   : {s['raised']} raised, {s['disputed']} disputed, "
              f"{s['upheld']} upheld, {s['overruled']} overruled, "
              f"{s['applied']} applied over {s['rounds']} round(s)")
    if linkedin_path:
        print(f"  LinkedIn   : {linkedin_path}")
    if video_path:
        print(f"  Video      : {video_path}")
    if voice_path:
        print(f"  Voiceover  : {voice_path}")
    for fmt in ("16x9", "9x16"):
        if video_files.get(f"video_{fmt}"):
            print(f"  Video {fmt}: {output_dir / video_files[f'video_{fmt}']}")
    if video_files:
        print(f"  Video text : {output_dir / f'{slug}_video_meta.md'}")
    if thumb_path:
        print(f"  Thumbnail  : {thumb_path}")
    print(f"  Usage JSON : {usage_path}")
    print_usage_summary()
    print(f"{'='*60}\n")


def audit_only(path: Path, output_dir: Path, topic: str = "", intent: str = "",
               verify_rounds: int = 2, apply: bool = False):
    """Point the three agents at a document you already have.

    The auditor works by comparing an article against the brief it was written
    from, and a file you hand it has no brief. So one call reconstructs the brief
    the document appears to be written to - its own outline and the takeaways it
    seems to promise - and the agents argue against that.
    """
    article = path.read_text(encoding="utf-8")
    title = topic or path.stem.replace("-", " ")

    print(f"\n{'='*60}")
    print(f"Audit only - no article is written")
    print(f"Document: {path}  ({len(article.split()):,} words)")
    print(f"Rounds  : {verify_rounds}   Apply fixes: {'yes' if apply else 'no'}")
    print(f"{'='*60}")

    log("BRIEF", "Reconstructing the brief this document was written to...")
    brief_prompt = f"""Read the document and infer the brief it appears to have been
written to. Do not judge it yet - only describe what it is trying to do.

{f"The author says the goal was: {intent}" if intent else ""}

Return ONLY valid JSON:
{{
  "primary_keyword": "<the phrase this is optimised for>",
  "secondary_keywords": ["<up to 6>"],
  "search_intent": "<informational | commercial | transactional | navigational>",
  "target_audience": "<one line>",
  "article_goal": "<one line>",
  "outline": "<the document's actual heading structure, as markdown headings>",
  "key_takeaways": "<the points it promises the reader, as a markdown list>"
}}

DOCUMENT
{article}"""
    brief = extract_json(call_claude(brief_prompt, max_tokens=4000))

    research = {
        "keywords": {"primary_keyword": brief.get("primary_keyword", title),
                     "secondary_keywords": brief.get("secondary_keywords", [])},
        "search_intent": brief.get("search_intent", ""),
        "target_audience": brief.get("target_audience", ""),
        "article_goal": brief.get("article_goal", ""),
        "serp_context": "(no live SERP data - this document was audited, not researched)",
    }
    print(f"  Keyword : {research['keywords']['primary_keyword']}")
    print(f"  Audience: {research['target_audience']}")

    record = {}
    revised = verification_loop(article, brief.get("outline", ""),
                                brief.get("key_takeaways", ""), research,
                                max_rounds=verify_rounds, record=record)

    slug = slugify(title)
    review_path, json_path = write_review(slug, record, output_dir, title)

    revised_path = None
    if apply and revised != article:
        revised_path = output_dir / f"{slug}_revised.md"
        revised_path.write_text(revised, encoding="utf-8")

    s = review_stats(record)
    print(f"\n{'='*60}")
    print(f"AUDIT COMPLETE")
    print(f"  Rounds     : {s['rounds']}")
    print(f"  Raised     : {s['raised']}")
    print(f"  Accepted   : {s['accepted']}   Disputed: {s['disputed']}")
    print(f"  Upheld     : {s['upheld']}   Overruled: {s['overruled']}")
    print(f"  Applied    : {s['applied']}")
    print(f"  Review     : {review_path}")
    print(f"  Raw JSON   : {json_path}")
    if revised_path:
        print(f"  Revised    : {revised_path}")
    elif apply:
        print(f"  Revised    : nothing changed, no file written")
    print(f"  Usage JSON : {write_usage(slug, output_dir, title)}")
    print_usage_summary()
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Generate a full SEO article with web-sourced images."
    )
    parser.add_argument(
        "topic",
        nargs="?",
        default=None,
        help=('Article topic, e.g. "What is RAG in AI". Optional with --audit, '
              'where it only names the document being audited.'),
    )
    parser.add_argument(
        "--intent",
        default=None,
        help=(
            'Natural language description of what you want to achieve, e.g. '
            '"I want to explain to developers how ReAct agents work and why '
            'they are better than standard LLMs for tool use". '
            'Claude will extract the best search keywords from this description.'
        ),
    )
    parser.add_argument(
        "--take",
        default=None,
        help=(
            "The author's own positions and experiences, one per line, or a path to "
            "a text file holding them. Every item is written into the article in "
            "first person and the auditor checks it survived. This is what turns a "
            "summary of the web into an article by you; the run warns when it is missing."
        ),
    )
    parser.add_argument(
        "--no-facts",
        action="store_true",
        help=(
            "Skip the Step 1.5 fact pack (opening primary sources and pinning every "
            "figure to a URL). The writer is then forbidden from stating any specific."
        ),
    )
    parser.add_argument(
        "--no-diagram",
        action="store_true",
        help=(
            "Skip the Step 8.5 diagram. The [DIAGRAM: ...] marker in the Level 1 "
            "section is then dropped instead of drawn."
        ),
    )
    parser.add_argument(
        "--keywords",
        default=None,
        help=(
            'Primary keyword(s) to target directly, e.g. "retrieval augmented generation". '
            'Use --intent instead for a richer, intent-driven search. '
            'If neither is provided, defaults to the topic.'
        ),
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory to save the article and meta JSON (default: ./output)",
    )
    parser.add_argument(
        "--edition",
        type=int,
        default=0,
        help="Newsletter edition number shown in the author intro (e.g. --edition 31)",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help=(
            "Skip the Step 6.5 audit. Faster and cheaper, but nothing checks the "
            "article's claims or structure before it is written to disk."
        ),
    )
    parser.add_argument(
        "--verify-rounds",
        type=int,
        default=2,
        help="Maximum audit/fix rounds before accepting the article (default: 2)",
    )
    parser.add_argument(
        "--words",
        choices=sorted(LENGTH_PROFILES),
        default="default",
        help=(
            "Article length. Every structural number moves with it - sections, "
            "subsections, images and FAQ count - so a short article is short "
            "rather than cramped. Default is 2,500-3,500 words."
        ),
    )
    parser.add_argument(
        "--linkedin",
        action="store_true",
        help=("Also write a LinkedIn post from the finished article, saved as "
              "<slug>_linkedin.md"),
    )
    parser.add_argument(
        "--video",
        action="store_true",
        help=("Also write a 2-3 minute video script from the finished article, "
              "with a visual note per beat, saved as <slug>_video.md"),
    )
    parser.add_argument(
        "--voiceover",
        action="store_true",
        help=("Also record the video script's narration in your own cloned voice "
              "via ElevenLabs, saved as <slug>_voiceover.mp3. Implies --video. Needs "
              "ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in .env"),
    )
    parser.add_argument(
        "--from-theme",
        default="",
        metavar="TITLE",
        help="The radar theme this article answers; it is marked written when the run ends",
    )
    parser.add_argument(
        "--mp4",
        action="store_true",
        help=("Also render the finished video: one slide per beat under your cloned "
              "voice, captions burned in, as <slug>_video_16x9.mp4 (YouTube, LinkedIn) "
              "and <slug>_video_9x16.mp4 (Shorts, Reels), plus the .srt and a "
              "<slug>_video_meta.md with the YouTube title, description, tags and a "
              "LinkedIn caption. Implies --video and --voiceover. Needs ffmpeg and "
              "the ElevenLabs keys"),
    )
    parser.add_argument(
        "--thumbnail",
        action="store_true",
        help=("Also write a LinkedIn share card from the finished article, as "
              "<slug>_thumbnail.html with a button to save it as a PNG"),
    )
    parser.add_argument(
        "--radar",
        action="store_true",
        help=(
            "Do not write an article; find out what to write. Reads the last two "
            "weeks of AI videos, podcasts, newsletters and forums and ranks the "
            "themes by what engineers need and nobody is covering. Writes "
            "radar_<date>.md and .json in the output folder."
        ),
    )
    parser.add_argument(
        "--dig",
        type=int,
        metavar="N",
        default=0,
        help=(
            "Deep research on theme N of the latest radar: reads the discussion "
            "threads, transcripts, public LinkedIn posts and practitioners' "
            "write-ups, and writes a one-page brief that 'Write this' then uses."
        ),
    )
    parser.add_argument(
        "--radar-days",
        type=int,
        default=RADAR_DAYS,
        help="How far back the radar looks (default 14)",
    )
    parser.add_argument(
        "--audit",
        metavar="FILE",
        default=None,
        help=(
            "Audit a document you already have instead of writing a new one. The "
            "three agents argue about your text and a review report is written; "
            "no article, images or meta are generated."
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="With --audit, also save the revised document as <slug>_revised.md",
    )
    args = parser.parse_args()

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ERROR: ANTHROPIC_API_KEY environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    if not args.audit and not args.radar and not args.dig and not args.topic:
        parser.error("a topic is required unless you pass --audit FILE, --radar or --dig N")

    # --intent takes priority; --keywords is the legacy shorthand; topic is the fallback
    intent = args.intent or ""
    keywords = args.keywords or ("" if intent else args.topic)
    output_dir = Path(args.output_dir)

    try:
        if args.dig:
            run_dig(output_dir, args.dig, days=max(3, min(60, args.radar_days)))
            return
        if args.radar:
            run_radar(output_dir, days=max(3, min(60, args.radar_days)))
            return
        if args.audit:
            doc = Path(args.audit)
            if not doc.exists():
                print(f"ERROR: no such file: {doc}", file=sys.stderr)
                sys.exit(1)
            audit_only(
                doc,
                output_dir=output_dir,
                topic=args.topic or "",
                intent=intent,
                verify_rounds=args.verify_rounds,
                apply=args.apply,
            )
            return
        run(
            title=args.topic,
            keywords=keywords,
            output_dir=output_dir,
            edition=args.edition,
            intent=intent,
            verify=not args.no_verify,
            verify_rounds=args.verify_rounds,
            words=args.words,
            linkedin=args.linkedin,
            video=args.video or args.voiceover or args.mp4,
            thumbnail=args.thumbnail,
            voiceover=args.voiceover or args.mp4,
            mp4=args.mp4,
            take=read_take(args.take),
            facts=not args.no_facts,
            diagram=not args.no_diagram,
            from_theme=args.from_theme,
        )
    except ClaudeError as e:
        # Flattened to one line so the web UI, which reads the log line by line,
        # can surface the whole message as a single error.
        print(f"ERROR: {' '.join(str(e).split())}", file=sys.stderr)
        sys.exit(2)
    except KeyboardInterrupt:
        print("ERROR: Interrupted.", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        # Anything unhandled used to leave the web UI showing "exited with code
        # 1" and nothing else, because a raw traceback carries no ERROR: line
        # for the job runner to pick up. Print both: a one-line summary it can
        # surface, and the traceback underneath for whoever reads the log.
        import traceback
        print(f"ERROR: {type(e).__name__}: {' '.join(str(e).split())[:300]}",
              file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
