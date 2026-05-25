"""
MCPClient — thin wrapper for MCP tool calls used by research pipeline agents.

Current implementation (Phase 6 + Equibles extension):
  - brave-search: direct HTTP to the Brave Search API
  - fetch: direct HTTP GET of any URL
  - equibles: JSON-RPC calls to the self-hosted Equibles MCP server (localhost:8081)
    Equibles provides SEC filings (full-text), 13F institutional holdings, insider
    trades (Form 3/4), congressional disclosures, FINRA short volume, SEC
    fails-to-deliver, FRED economic indicators, CFTC futures, CBOE VIX/put-call,
    and daily prices + technical indicators — all locally, no cloud dependency.

Phase 7 upgrade path:
  Replace _brave_search() with a real MCP stdio/SSE transport to the running
  MCP server process. The agent-facing call() / call_sync() API stays identical,
  so no agent changes are needed when upgrading.

Supported tools:
  brave-search          — web search via Brave Search API (requires api_key)
  fetch                 — direct HTTP GET of a URL (no key required)
  equibles              — self-hosted financial data (requires Equibles Docker running)

Graceful degradation:
  If no api_key / server is configured for a tool, call() returns None and the
  agent falls back to LLM-only knowledge. No exception is raised.

Usage:
    mcp = MCPClient.from_config("config.yaml")
    result = mcp.call_sync("brave-search", {"query": "Stripe interview culture 2025"})
    # result is a plain text string, or None if tool unavailable

    holders = mcp.equibles_institutional_holders("AAPL")
    # returns parsed dict/list or None if Equibles is not running
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Brave Search API endpoint
_BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"

# Max characters to return from a search result set
_MAX_RESULT_CHARS = 6000

# Number of results to request from Brave
_BRAVE_COUNT = 8


class MCPClient:
    """
    Agent-facing MCP tool client.

    Instantiate via MCPClient.from_config("config.yaml").
    If not configured (no api keys / servers), the client still works but returns
    None for tools that require authentication or a running service.
    """

    def __init__(
        self,
        brave_api_key: str | None = None,
        equibles_url: str | None = None,
    ):
        self.brave_api_key = brave_api_key or None
        self.equibles_url  = equibles_url or None

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> "MCPClient":
        """Build an MCPClient from config.yaml."""
        import yaml
        try:
            with open(config_path) as f:
                cfg = yaml.safe_load(f)
        except Exception:
            return cls()

        mcp_cfg = cfg.get("mcp", {})
        brave_key = mcp_cfg.get("brave_search_key", "") or None

        equibles_cfg = mcp_cfg.get("equibles", {})
        equibles_url = None
        if equibles_cfg.get("enabled", False):
            equibles_url = equibles_cfg.get("server_url", "http://localhost:8081") or None

        return cls(brave_api_key=brave_key, equibles_url=equibles_url)

    # ── Public API ────────────────────────────────────────────────────────────

    def call_sync(self, tool: str, args: dict) -> str | None:
        """
        Synchronous MCP tool call. Returns plain text result or None.

        tool: "brave-search" | "fetch"
        args: tool-specific dict, e.g. {"query": "..."} or {"url": "..."}
        """
        if tool == "brave-search":
            return self._brave_search(args.get("query", ""))
        elif tool == "fetch":
            return self._fetch_url(args.get("url", ""))
        else:
            logger.warning(f"MCPClient: unknown tool '{tool}'")
            return None

    def is_available(self, tool: str) -> bool:
        """Return True if the named tool has the required credentials / service configured."""
        if tool == "brave-search":
            return bool(self.brave_api_key)
        elif tool == "fetch":
            return True  # no key required
        elif tool == "equibles":
            return bool(self.equibles_url)
        return False

    # ── Equibles: high-level helper methods ───────────────────────────────────
    # Each method calls a specific Equibles MCP tool and returns parsed data.
    # Returns None (never raises) if Equibles is unavailable or the call fails.
    #
    # Tool names match the Equibles MCP server as documented at:
    #   https://github.com/daniel3303/Equibles
    # Verify tool names against your running instance via:
    #   POST http://localhost:8081/  body: {"jsonrpc":"2.0","id":1,"method":"tools/list"}

    def equibles_institutional_holders(self, ticker: str) -> dict | None:
        """
        13F institutional holders for a ticker.
        Returns: {holders: [{institution, shares, value, pct_outstanding, change_pct}], quarter}
        """
        return self._equibles_call("get_institutional_holders", {"ticker": ticker.upper()})

    def equibles_short_interest(self, ticker: str) -> dict | None:
        """
        FINRA short volume + SEC fails-to-deliver for a ticker.
        Returns: {short_volume_pct, days_to_cover, fails_to_deliver, trend}
        """
        return self._equibles_call("get_short_interest", {"ticker": ticker.upper()})

    def equibles_insider_transactions(self, ticker: str, days: int = 90) -> list | None:
        """
        SEC Form 3/4 insider transactions in the last N days.
        Returns: [{name, title, type, shares, price, value, date, form}]
        """
        result = self._equibles_call(
            "get_insider_transactions",
            {"ticker": ticker.upper(), "days": days},
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            # Some responses wrap the list in a "transactions" key
            return result.get("transactions") or result.get("data") or []
        return None

    def equibles_congressional_trades(self, ticker: str, days: int = 180) -> list | None:
        """
        Congressional trading disclosures for a ticker.
        Returns: [{member, party, chamber, trade_type, amount_range, date}]
        """
        result = self._equibles_call(
            "get_congressional_trades",
            {"ticker": ticker.upper(), "days": days},
        )
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("trades") or result.get("data") or []
        return None

    def equibles_technical_indicators(self, ticker: str) -> dict | None:
        """
        Computed technical indicators (RSI, MACD, Bollinger Bands, SMAs).
        Returns: {rsi_14, macd, macd_signal, bb_upper, bb_lower, sma_50, sma_200, ...}
        """
        return self._equibles_call("get_technical_indicators", {"ticker": ticker.upper()})

    def equibles_search_sec_filings(
        self,
        ticker: str,
        query: str,
        forms: list[str] | None = None,
        max_results: int = 5,
    ) -> list | None:
        """
        Full-text search across SEC filings (10-K, 10-Q, 8-K) for a ticker.
        Returns: [{form, filed_date, excerpt, url}]
        """
        args: dict = {
            "ticker": ticker.upper(),
            "query":  query,
            "limit":  max_results,
        }
        if forms:
            args["forms"] = forms

        result = self._equibles_call("search_sec_filings", args)
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            return result.get("results") or result.get("filings") or result.get("data") or []
        return None

    # ── Equibles: low-level JSON-RPC transport ────────────────────────────────

    def _equibles_call(self, tool_name: str, arguments: dict) -> dict | list | None:
        """
        Call an Equibles MCP tool via the MCP HTTP JSON-RPC transport.

        Equibles MCP server runs on port 8081. The MCP protocol over HTTP uses
        JSON-RPC 2.0: POST / with {"jsonrpc":"2.0","method":"tools/call","params":{...}}.
        The result arrives in the "result.content[0].text" field as a JSON string.
        """
        if not self.equibles_url:
            return None

        try:
            import httpx
        except ImportError:
            logger.warning("MCPClient: httpx not installed — cannot call Equibles")
            return None

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments,
            },
        }

        base = self.equibles_url.rstrip("/")

        try:
            with httpx.Client(timeout=20) as client:
                resp = client.post(
                    f"{base}/",
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                resp.raise_for_status()
                data = resp.json()
        except httpx.ConnectError:
            logger.debug(
                f"MCPClient: Equibles not reachable at {base} — "
                "ensure `docker compose up` is running (see .mcp.json for setup)"
            )
            return None
        except httpx.HTTPStatusError as e:
            logger.warning(f"MCPClient: Equibles tool '{tool_name}' HTTP {e.response.status_code}")
            return None
        except Exception as e:
            logger.warning(f"MCPClient: Equibles tool '{tool_name}' failed: {e}")
            return None

        # Parse MCP response: result.content[0].text holds the JSON payload
        rpc_error = data.get("error")
        if rpc_error:
            logger.warning(
                f"MCPClient: Equibles tool '{tool_name}' RPC error: {rpc_error.get('message')}"
            )
            return None

        result = data.get("result", {})
        content = result.get("content", [])
        if not content:
            return result if result else None

        text = content[0].get("text", "") if content[0].get("type") == "text" else ""
        if not text:
            return None

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # Return raw text wrapped in a dict so callers can still use it
            return {"raw": text}

    # ── Tool implementations: brave-search + fetch ────────────────────────────

    def _brave_search(self, query: str) -> str | None:
        """
        Execute a Brave Web Search query.

        Returns a plain text summary of the top results (title + URL + snippet).
        Returns None if brave_api_key is not configured.
        """
        if not self.brave_api_key:
            logger.debug("MCPClient: brave-search skipped — no api key configured")
            return None

        if not query.strip():
            return None

        try:
            import httpx
        except ImportError:
            logger.warning("MCPClient: httpx not installed — cannot call Brave Search")
            return None

        headers = {
            "Accept":               "application/json",
            "Accept-Encoding":      "gzip",
            "X-Subscription-Token": self.brave_api_key,
        }
        params = {
            "q":                query,
            "count":            _BRAVE_COUNT,
            "text_decorations": False,
            "search_lang":      "en",
        }

        try:
            with httpx.Client(timeout=10) as client:
                resp = client.get(_BRAVE_SEARCH_URL, headers=headers, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                logger.warning("MCPClient: Brave Search API key is invalid (401).")
            elif e.response.status_code == 429:
                logger.warning("MCPClient: Brave Search rate-limited (429). Using LLM fallback.")
            else:
                logger.warning(f"MCPClient: Brave Search HTTP {e.response.status_code}")
            return None
        except Exception as e:
            logger.warning(f"MCPClient: Brave Search failed: {e}")
            return None

        results = data.get("web", {}).get("results", [])
        if not results:
            return None

        lines: list[str] = [f"Web search results for: {query}\n"]
        for r in results:
            title   = r.get("title", "")
            url     = r.get("url", "")
            snippet = r.get("description", "") or r.get("extra_snippets", [""])[0]
            lines.append(f"• {title}\n  {url}\n  {snippet}\n")

        text = "\n".join(lines)
        return text[:_MAX_RESULT_CHARS]

    def _fetch_url(self, url: str) -> str | None:
        """
        Fetch the text content of a URL.

        Returns plain text (up to _MAX_RESULT_CHARS). Returns None on error.
        """
        if not url:
            return None

        try:
            import httpx
        except ImportError:
            logger.warning("MCPClient: httpx not installed — cannot fetch URL")
            return None

        try:
            headers = {"User-Agent": "Mozilla/5.0 (compatible; OpenResearch/1.0)"}
            with httpx.Client(timeout=10, follow_redirects=True) as client:
                resp = client.get(url, headers=headers)
                resp.raise_for_status()
                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type or "text/plain" in content_type:
                    import re
                    text = re.sub(r"<[^>]+>", " ", resp.text)
                    text = re.sub(r"\s+", " ", text).strip()
                    return text[:_MAX_RESULT_CHARS]
                return resp.text[:_MAX_RESULT_CHARS]
        except Exception as e:
            logger.warning(f"MCPClient: fetch {url} failed: {e}")
            return None
