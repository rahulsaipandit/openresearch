"""
Unified LLM client — Anthropic Claude, OpenAI, or MiniMax, same interface.

Supports a fallback chain: try providers in order, falling back to the next
one when a rate limit is hit.

Single provider:
    llm = LLMClient.single("anthropic", api_key="sk-ant-...", model="claude-sonnet-4-20250514")
    llm = LLMClient.single("openai",    api_key="sk-...",     model="gpt-4o")
    llm = LLMClient.single("minimax",   api_key="...",        model="MiniMax-M2.5")

Fallback chain (Anthropic → OpenAI → MiniMax):
    llm = LLMClient([
        ("anthropic", "sk-ant-...", "claude-sonnet-4-20250514"),
        ("openai",    "sk-...",     "gpt-4o"),
        ("minimax",   "...",        "MiniMax-M2.5"),
    ])

    text = llm.create(system="...", messages=[...], max_tokens=500)

Rate limits:
    On 429 within a provider: wait Retry-After (or 60 s) and retry up to
    MAX_RETRIES times, then fall through to the next provider in the chain.
    If all providers are exhausted, re-raises the last error.
"""

import json
import logging
import time
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

MAX_RETRIES   = 4   # retries per provider before falling back to next

T = TypeVar("T")


def parse_llm_json(
    raw: str,
    agent_name: str,
    builder: Callable[[dict], T],
    fallback: Callable[[], T],
) -> T:
    """
    Shared "call an LLM, parse its JSON, build a typed result" pattern —
    previously hand-copied (with an identical log line, differing only in
    agent_name) across ~7 stock agents: adversarial_review, business_foundation,
    comparison_analyst, driver_debate, query_router, sec_qa, document_insights.

    `builder` does whatever construction that call site needs from the parsed
    dict (a plain `Model(**data)`, or something that pulls specific fields and
    validates nested lists) — any exception it raises (malformed JSON, a
    missing required field, a nested Pydantic validation error) is caught the
    same way a bad json.loads() would be, logs one consistent warning, and
    calls `fallback()` instead of propagating.
    """
    try:
        data = json.loads(raw)
        return builder(data)
    except Exception as e:
        logger.warning(f"{agent_name} JSON parse failed: {e}\nRaw: {raw[:300]}")
        return fallback()


# ── Token budget ───────────────────────────────────────────────────────────────

# Conservative context window limits per model family (input tokens).
# We use ~80% of the real limit to leave headroom for system prompt overhead.
_CONTEXT_LIMITS: dict[str, int] = {
    # OpenAI
    "gpt-5":        100_000,
    "gpt-4.1":      800_000,   # 1M context, use 80%
    "gpt-4o":       100_000,
    "gpt-4":         24_000,
    "o1":           160_000,
    "o3":           160_000,
    "o4":           160_000,
    # Anthropic
    "claude-opus":  160_000,
    "claude-sonnet":160_000,
    "claude-haiku":  80_000,
    # MiniMax
    "minimax-m2.5": 163_000,   # 204K context, use ~80%
    # Default fallback
    "_default":      24_000,
}

def _context_limit_for(model: str) -> int:
    """Return the safe input token budget for a given model name."""
    lower = model.lower()
    for prefix, limit in _CONTEXT_LIMITS.items():
        if lower.startswith(prefix):
            return limit
    return _CONTEXT_LIMITS["_default"]


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: 1 token ≈ 3.5 characters (conservative)."""
    return max(1, int(len(text) / 3.5))


class PromptBudget:
    """
    Manages token allocation for a single LLM call.

    Usage:
        budget = PromptBudget(model="gpt-5", reserved_output=4000)
        budget.reserve("system", system_prompt)
        sections = budget.fit([
            ("error",    error_text,    True),   # (name, text, required)
            ("code",     nb_code,       True),
            ("memory",   memory_hint,   False),  # optional — dropped first
        ])
        # sections is a dict name→fitted_text; dropped optionals are empty string

    The budget is consumed in priority order (required first, then optional).
    Each section is truncated if needed; optional sections are dropped entirely
    before any required section is truncated.
    """

    def __init__(self, model: str, reserved_output: int = 4000):
        self._limit   = _context_limit_for(model)
        self._used    = reserved_output   # reserve space for output
        self._model   = model

    def reserve(self, name: str, text: str) -> None:
        """Pre-consume tokens for a fixed section (system prompt, instructions)."""
        self._used += _estimate_tokens(text)

    def fit(self, sections: list[tuple[str, str, bool]]) -> dict[str, str]:
        """
        Fit sections into remaining budget.

        sections: list of (name, text, required)
        Returns dict of name → fitted text (truncated or empty).
        """
        remaining = max(0, self._limit - self._used)
        result: dict[str, str] = {name: "" for name, _, _ in sections}

        # Pass 1: required sections — truncate to fit
        for name, text, required in sections:
            if not required:
                continue
            tokens = _estimate_tokens(text)
            if tokens <= remaining:
                result[name] = text
                remaining -= tokens
            else:
                # Truncate to remaining budget (chars ≈ tokens * 3.5)
                chars = int(remaining * 3.5)
                result[name] = text[:chars] + "\n... [truncated to fit token limit]"
                remaining = 0

        # Pass 2: optional sections — include only if budget allows
        for name, text, required in sections:
            if required:
                continue
            tokens = _estimate_tokens(text)
            if tokens <= remaining:
                result[name] = text
                remaining -= tokens
            # else: leave as empty string — dropped

        self._used += (_limit_before := self._limit - remaining)  # noqa: F841
        return result


# ── Model discovery ────────────────────────────────────────────────────────────

def list_provider_models(provider: str, api_key: str) -> list[str]:
    """
    Fetch all available model IDs from the given provider.

    Returns model IDs sorted by the provider (Anthropic: newest first;
    OpenAI: chat/reasoning models only, newest first).

    Args:
        provider: "anthropic", "openai", or "minimax"
        api_key:  API key for that provider

    Returns:
        List of model ID strings, e.g. ["claude-opus-4-20250514", ...]
    """
    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        page = client.models.list(limit=100)
        return [m.id for m in page.data]

    elif provider == "openai":
        import openai
        client = openai.OpenAI(api_key=api_key)
        all_models = client.models.list()
        # Exclude known non-chat model families; keep everything else
        # (new model families like gpt-5, o5, etc. are included automatically)
        excluded_prefixes = (
            "dall-e", "whisper", "tts", "text-embedding",
            "text-moderation", "babbage", "davinci", "ada",
            "curie", "code-", "audio-",
        )
        ids = sorted(
            [
                m.id for m in all_models.data
                if not m.id.startswith(excluded_prefixes)
            ],
            reverse=True,
        )
        return ids

    elif provider == "minimax":
        # MiniMax supports two chat models with 204K context window
        return ["MiniMax-M2.5", "MiniMax-M2.5-highspeed"]

    else:
        raise ValueError(f"Unknown provider '{provider}'. Use 'anthropic', 'openai', or 'minimax'.")


def resolve_models(
    provider: str,
    api_key: str,
    requested: str,
    verbose: bool = True,
) -> list[str]:
    """
    Resolve a model specification for one provider.

    - If ``requested`` is ``"auto"``, call the provider API and return all
      available models (ordered best-first).
    - Otherwise return ``[requested]`` unchanged.

    Args:
        provider:  "anthropic", "openai", or "minimax"
        api_key:   API key
        requested: model name or "auto"
        verbose:   print discovered models

    Returns:
        List of model ID strings to use as a fallback sub-chain.
    """
    if requested.lower() != "auto":
        return [requested]

    logger.info(f"[{provider}] llm_model=auto — fetching available models...")
    models = list_provider_models(provider, api_key)

    if not models:
        raise RuntimeError(
            f"Provider '{provider}' returned no models. "
            "Check your API key and network connection."
        )

    if verbose:
        print(f"\n  🔍 [{provider}] Discovered {len(models)} model(s):")
        for m in models[:10]:          # show first 10 to avoid spam
            print(f"       • {m}")
        if len(models) > 10:
            print(f"       … and {len(models) - 10} more")

    return models
BASE_WAIT_SEC = 60  # default wait on rate limit (API may return a shorter value)


# ── Single-provider backend ────────────────────────────────────────────────────

class _Backend:
    """Wraps one (provider, model) pair and makes API calls."""

    def __init__(self, provider: str, api_key: str, model: str, base_url: Optional[str] = None):
        self.provider = provider
        self.model    = model

        if provider == "anthropic":
            import anthropic
            self._client         = anthropic.Anthropic(api_key=api_key)
            self._rate_limit_exc = anthropic.RateLimitError
        elif provider == "openai":
            import openai
            self._client         = openai.OpenAI(api_key=api_key)
            self._rate_limit_exc = openai.RateLimitError
        elif provider == "openai_compatible":
            # Local LLM via OpenAI-compatible endpoint (LM Studio, Ollama, etc.)
            import openai as _openai
            self._client         = _openai.OpenAI(
                api_key=api_key or "local",
                base_url=base_url or "http://localhost:1234/v1",
            )
            self._rate_limit_exc = _openai.RateLimitError
        elif provider == "minimax":
            import openai as _openai
            self._client         = _openai.OpenAI(
                api_key=api_key,
                base_url="https://api.minimax.io/v1",
            )
            self._rate_limit_exc = _openai.RateLimitError
        else:
            raise ValueError(f"Unknown LLM provider '{provider}'. Use 'anthropic', 'openai', 'openai_compatible', or 'minimax'.")

    def call(self, system: str, messages: list[dict], max_tokens: int,
             verbose: bool = False, images: Optional[list[dict]] = None) -> str:
        """
        Make a single API call with exponential back-off on rate limit.
        Raises the RateLimitError after MAX_RETRIES so the caller can try
        the next backend.

        images: optional list of {"media_type": str, "data": base64 str}
        attached to the last message in `messages`. Only meaningful via
        LLMClient.create_multimodal() — plain create() never passes this.
        """
        wait = BASE_WAIT_SEC
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                if self.provider == "anthropic":
                    return self._call_anthropic(system, messages, max_tokens, images)
                elif self.provider == "minimax":
                    return self._call_minimax(system, messages, max_tokens, images)
                elif self.provider == "openai_compatible":
                    return self._call_openai_compatible(system, messages, max_tokens, images)
                else:
                    return self._call_openai(system, messages, max_tokens, images)

            except Exception as e:
                if not isinstance(e, self._rate_limit_exc):
                    raise           # non-rate-limit errors propagate immediately
                if attempt == MAX_RETRIES:
                    raise           # exhausted retries — caller handles fallback

                retry_after = None
                if hasattr(e, "response") and e.response is not None:
                    retry_after = e.response.headers.get("retry-after")
                sleep_sec = int(retry_after) if retry_after else wait

                if verbose:
                    print(f"\n  ⏳ [{self.provider}/{self.model}] Rate limit — "
                          f"waiting {sleep_sec}s (attempt {attempt}/{MAX_RETRIES})...")
                time.sleep(sleep_sec)
                wait = min(wait * 2, 300)

    @staticmethod
    def _attach_images(messages: list[dict], images: Optional[list[dict]], image_block) -> list[dict]:
        """Rebuild the last message's content as [image blocks..., text block] —
        images attach to whatever the caller's current turn is. No-op if
        images is empty/None, so every existing plain-text call site is
        unaffected."""
        if not images:
            return messages
        last = messages[-1]
        blocks = [image_block(img) for img in images]
        blocks.append({"type": "text", "text": last["content"]})
        return [*messages[:-1], {**last, "content": blocks}]

    def _call_anthropic(self, system: str, messages: list[dict], max_tokens: int,
                         images: Optional[list[dict]] = None) -> str:
        messages = self._attach_images(
            messages, images,
            lambda img: {
                "type": "image",
                "source": {"type": "base64", "media_type": img["media_type"], "data": img["data"]},
            },
        )
        resp = self._client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return resp.content[0].text

    # Models that require 'developer' role instead of 'system'
    _DEVELOPER_ROLE_MODELS = ("o1", "o3", "o4", "gpt-5")

    def _uses_developer_role(self) -> bool:
        return any(self.model.startswith(p) for p in self._DEVELOPER_ROLE_MODELS)

    @staticmethod
    def _openai_image_block(img: dict) -> dict:
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{img['media_type']};base64,{img['data']}"},
        }

    def _call_openai(self, system: str, messages: list[dict], max_tokens: int,
                      images: Optional[list[dict]] = None) -> str:
        messages = self._attach_images(messages, images, self._openai_image_block)
        system_role = "developer" if self._uses_developer_role() else "system"
        kwargs = dict(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": system_role, "content": system}] + messages,
        )
        try:
            resp = self._client.chat.completions.create(**kwargs)
        except Exception as e:
            err = str(e)
            # Some models require max_completion_tokens instead of max_tokens
            if "max_tokens" in err and "max_completion_tokens" in err:
                kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
                resp = self._client.chat.completions.create(**kwargs)
            # Some models reject 'system' role — retry with 'developer'
            elif "system" in err and system_role == "system":
                kwargs["messages"][0]["role"] = "developer"
                resp = self._client.chat.completions.create(**kwargs)
            else:
                raise
        content = resp.choices[0].message.content
        # Some models (o-series, gpt-5) may return None content when the response
        # is carried entirely in reasoning tokens or was filtered; surface a clear error.
        if not content:
            finish = resp.choices[0].finish_reason
            raise ValueError(
                f"Model '{self.model}' returned an empty response (finish_reason={finish!r}). "
                "This can happen when the model's output was filtered or the prompt was too long."
            )
        return content

    def _call_openai_compatible(self, system: str, messages: list[dict], max_tokens: int,
                                 images: Optional[list[dict]] = None) -> str:
        """Call a local OpenAI-compatible server (LM Studio, Ollama, etc.).

        Vision support depends entirely on whichever model is loaded locally —
        if it doesn't accept image content blocks, the call raises and
        LLMClient.create_multimodal() falls back to text-only (§2.1)."""
        messages = self._attach_images(messages, images, self._openai_image_block)
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[{"role": "system", "content": system}] + messages,
        )
        content = resp.choices[0].message.content
        if not content:
            finish = resp.choices[0].finish_reason
            raise ValueError(
                f"Local model '{self.model}' returned empty response (finish_reason={finish!r})."
            )
        return content

    def _call_minimax(self, system: str, messages: list[dict], max_tokens: int,
                       images: Optional[list[dict]] = None) -> str:
        """Call MiniMax via its OpenAI-compatible API.

        Key differences from vanilla OpenAI:
        - temperature must be in (0.0, 1.0] — zero is not accepted
        - uses 'system' role (no 'developer' role)
        - no vision support in this client — raises so create_multimodal()
          treats it the same as any other backend that can't handle images.
        """
        if images:
            raise ValueError("MiniMax backend does not support image input in this client.")
        resp = self._client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=1.0,
            messages=[{"role": "system", "content": system}] + messages,
        )
        content = resp.choices[0].message.content
        if not content:
            finish = resp.choices[0].finish_reason
            raise ValueError(
                f"Model '{self.model}' returned an empty response (finish_reason={finish!r})."
            )
        return content


def _verify_images(images: Optional[list[dict]]) -> list[dict]:
    """
    Drop any image whose base64 bytes don't actually match its declared
    media_type (checked against real content via magika, not the client-
    supplied string) — an ImageAttachment.media_type is attacker-controlled
    input forwarded straight into a vision API call otherwise. Mismatched
    images are dropped rather than raising, consistent with
    create_multimodal()'s existing graceful degradation.
    """
    if not images:
        return images or []

    import base64
    from integrations.file_type_check import verify_image

    verified = []
    for img in images:
        try:
            raw = base64.b64decode(img["data"], validate=True)
        except Exception:
            logger.warning("Dropping image attachment: invalid base64 data.")
            continue
        ok, detected = verify_image(raw, img["media_type"])
        if not ok:
            logger.warning(
                f"Dropping image attachment: declared media_type="
                f"{img['media_type']!r} but content is actually {detected!r}."
            )
            continue
        verified.append(img)
    return verified


# ── Public LLMClient ───────────────────────────────────────────────────────────

class LLMClient:
    """
    Unified LLM client that supports a prioritised list of backends.

    Tries backends in order; falls back to the next one if the current one
    hits a rate limit and exhausts its retries.

    Usage:
        # Single provider
        llm = LLMClient.single("anthropic", "sk-ant-...", "claude-sonnet-4-20250514")
        llm = LLMClient.single("minimax",   "...",        "MiniMax-M2.5")

        # Fallback chain — Anthropic first, OpenAI, then MiniMax as backup
        llm = LLMClient([
            ("anthropic", "sk-ant-...", "claude-sonnet-4-20250514"),
            ("openai",    "sk-...",     "gpt-4o"),
            ("minimax",   "...",        "MiniMax-M2.5"),
        ])
    """

    def __init__(self, backends: list[tuple[str, str, str]]):
        """
        Args:
            backends: List of (provider, api_key, model) tuples tried in order.
        """
        if not backends:
            raise ValueError("At least one backend must be provided.")
        self._backends = [_Backend(p, k, m) for p, k, m in backends]
        # Expose primary model name for logging / display
        self.provider = self._backends[0].provider
        self.model    = self._backends[0].model

    @classmethod
    def single(cls, provider: str, api_key: str, model: str) -> "LLMClient":
        """Convenience constructor for a single provider."""
        return cls([(provider, api_key, model)])

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "LLMClient":
        """
        Build an LLMClient from the new config.yaml format.

        Reads the llm.provider_chain list and builds a fallback chain.
        Supports providers: anthropic, openai, openai_compatible, minimax.
        """
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)

        chain = cfg.get("llm", {}).get("provider_chain", [])
        if not chain:
            raise ValueError("No llm.provider_chain entries found in config.yaml.")

        backends: list[tuple] = []
        for entry in chain:
            provider = entry.get("provider", "")
            api_key  = entry.get("api_key", "") or ""
            model    = entry.get("model", "")
            base_url = entry.get("base_url")

            if not provider or not model:
                logger.warning(f"Skipping malformed provider chain entry: {entry}")
                continue

            # Build _Backend with base_url for openai_compatible
            if provider == "openai_compatible":
                backends.append((provider, api_key, model, base_url))
            else:
                backends.append((provider, api_key, model))

        if not backends:
            raise ValueError("No valid providers in llm.provider_chain.")

        # Build backends, threading base_url through for openai_compatible
        built: list[_Backend] = []
        for entry in backends:
            if len(entry) == 4:
                p, k, m, url = entry
                built.append(_Backend(p, k, m, base_url=url))
            else:
                p, k, m = entry
                built.append(_Backend(p, k, m))

        inst = cls.__new__(cls)
        inst._backends = built
        inst.provider  = built[0].provider
        inst.model     = built[0].model
        return inst

    def create(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int,
        verbose: bool = False,
    ) -> str:
        """
        Call the first available backend. Falls back to the next backend if
        a rate limit is hit after all retries.

        Returns the response text as a plain string.
        """
        last_error: Exception | None = None

        for backend in self._backends:
            try:
                return backend.call(system, messages, max_tokens, verbose)
            except Exception as e:
                # Check if it's a rate-limit error — if so, try next backend
                if isinstance(e, backend._rate_limit_exc):
                    last_error = e
                    if verbose:
                        print(f"\n  ⚠️  [{backend.provider}/{backend.model}] rate limit "
                              f"exhausted — trying next provider...")
                    continue
                raise   # any other error propagates immediately

        # All backends exhausted
        raise last_error

    def create_multimodal(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int,
        images: Optional[list[dict]] = None,
        verbose: bool = False,
    ) -> tuple[str, bool]:
        """
        Like create(), but accepts images attached to the last message
        (list of {"media_type": str, "data": base64 str}).

        Graceful degradation (docs/openresearch-integration-requirements.md
        §2.1): not every configured backend supports vision — a local model
        via openai_compatible in particular may not. Each backend is tried
        WITH the images first; if every one fails on the image-bearing call,
        this falls back to the plain text-only chain via create() rather than
        erroring, since a candidate's screenshot being unusable shouldn't
        break the whole answer. Returns (answer_text, images_were_used) so
        the caller can tell the candidate their image was dropped instead of
        silently losing it.

        Rate-limit handling matches create() (retries within a backend, falls
        through the chain); any other failure on the vision call is treated
        as "this backend can't do vision" and also falls through the chain,
        which is the one behavioral difference from create()'s "non-rate-limit
        errors propagate immediately" — expected here, since an unsupported-
        content-type error from a text-only local model is a normal outcome,
        not a bug to surface.
        """
        images = _verify_images(images)
        if not images:
            return self.create(system, messages, max_tokens, verbose), False

        for backend in self._backends:
            try:
                return backend.call(system, messages, max_tokens, verbose, images=images), True
            except Exception as e:
                if verbose:
                    print(f"\n  ⚠️  [{backend.provider}/{backend.model}] vision call failed "
                          f"({e}) — trying next backend...")
                continue

        # No backend could use the image — fall back to text-only, and tell
        # the caller so it can surface that to the candidate.
        if verbose:
            print("\n  ⚠️  No configured backend could use the attached image(s) — "
                  "answering from text only.")
        return self.create(system, messages, max_tokens, verbose), False


# ── Legacy shim ────────────────────────────────────────────────────────────────

def claude_create(client, verbose: bool = False, **kwargs):
    """Deprecated: direct Anthropic client wrapper. Use LLMClient instead."""
    import anthropic
    wait = BASE_WAIT_SEC
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            return client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            if attempt == MAX_RETRIES:
                raise
            retry_after = None
            if hasattr(e, "response") and e.response is not None:
                retry_after = e.response.headers.get("retry-after")
            sleep_sec = int(retry_after) if retry_after else wait
            if verbose:
                print(f"\n  ⏳ Rate limit hit — waiting {sleep_sec}s before retry "
                      f"(attempt {attempt}/{MAX_RETRIES})...")
            time.sleep(sleep_sec)
            wait = min(wait * 2, 300)
