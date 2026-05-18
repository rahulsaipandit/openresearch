"""
Slack Integration — READ-ONLY.

Fetches messages from specified channels to surface team health signals,
blockers mentioned in stand-ups, and cross-team dependencies.

GUARDRAILS:
  - Only reads messages. No posting, reacting, deleting, or modifying anything.
  - Requires explicit channel list in config — never auto-discovers all channels.
  - Token must be a Bot Token with channels:history and channels:read scopes only.
  - Message content is summarized and anonymized before LLM processing.

Authentication: Slack Bot Token (xoxb-...)
Docs: https://api.slack.com/methods/conversations.history
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"

# Only these read-only API methods are ever called
_ALLOWED_METHODS = frozenset({
    "conversations.history",
    "conversations.list",
    "conversations.info",
    "users.info",
    "auth.test",
})


class SlackIntegration:
    """
    Read-only Slack client.

    NEVER posts, reacts, deletes, or modifies any Slack data.
    Only calls read methods in _ALLOWED_METHODS.
    """

    def __init__(self, bot_token: str, channel_ids: Optional[list[str]] = None):
        if not bot_token:
            raise ValueError("Slack requires a bot_token.")
        if not bot_token.startswith("xoxb-"):
            logger.warning(
                "Slack token does not look like a Bot Token (expected xoxb-...). "
                "Ensure this is a Bot Token with read-only scopes."
            )
        self._token    = bot_token
        self._headers  = {
            "Authorization": f"Bearer {bot_token}",
            "Content-Type":  "application/json",
        }
        self.channel_ids = channel_ids or []

    def fetch_recent_messages(
        self,
        channel_id: str,
        days_back: int = 7,
        max_messages: int = 100,
    ) -> list[dict]:
        """
        Fetch recent messages from a channel.

        Returns list of {user, username, text, ts, thread_ts}.
        Only reads — never writes.
        """
        oldest = (datetime.utcnow() - timedelta(days=days_back)).timestamp()

        try:
            with httpx.Client(headers=self._headers, timeout=15) as client:
                r = self._call(client, "conversations.history", {
                    "channel": channel_id,
                    "oldest":  str(oldest),
                    "limit":   max_messages,
                    "inclusive": True,
                })
                messages = r.get("messages", [])
                return [
                    {
                        "user":      m.get("user", ""),
                        "username":  m.get("username", m.get("user", "")),
                        "text":      m.get("text", ""),
                        "ts":        m.get("ts", ""),
                        "thread_ts": m.get("thread_ts", ""),
                    }
                    for m in messages
                    if m.get("type") == "message" and m.get("text")
                ]
        except Exception as e:
            logger.warning(f"Slack fetch failed (channel={channel_id}): {e}")
            return []

    def fetch_all_configured_channels(self, days_back: int = 7) -> dict[str, list[dict]]:
        """
        Fetch messages from all channels configured in config.yaml.

        Returns: {channel_id: [message, ...]}
        """
        if not self.channel_ids:
            logger.info("No Slack channel_ids configured — skipping Slack fetch.")
            return {}

        result: dict[str, list[dict]] = {}
        for channel_id in self.channel_ids:
            name = self._get_channel_name(channel_id)
            key  = name or channel_id
            result[key] = self.fetch_recent_messages(channel_id, days_back=days_back)
            logger.info(f"Slack: fetched {len(result[key])} messages from #{key}")
        return result

    def test_connection(self) -> bool:
        """Verify the token is valid and has read access."""
        try:
            with httpx.Client(headers=self._headers, timeout=10) as client:
                r = self._call(client, "auth.test", {})
                return r.get("ok", False)
        except Exception:
            return False

    # ── Private ────────────────────────────────────────────────────────────────

    def _call(self, client: httpx.Client, method: str, params: dict) -> dict:
        """Only calls methods in _ALLOWED_METHODS — hard guard against writes."""
        if method not in _ALLOWED_METHODS:
            raise PermissionError(
                f"Slack integration is read-only. Method '{method}' is not allowed. "
                f"Allowed methods: {sorted(_ALLOWED_METHODS)}"
            )
        r = client.get(f"{SLACK_API}/{method}", params=params)
        r.raise_for_status()
        data = r.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack API error: {data.get('error', 'unknown')}")
        return data

    def _get_channel_name(self, channel_id: str) -> Optional[str]:
        try:
            with httpx.Client(headers=self._headers, timeout=10) as client:
                r = self._call(client, "conversations.info", {"channel": channel_id})
                return r.get("channel", {}).get("name")
        except Exception:
            return None

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> Optional["SlackIntegration"]:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        slack = cfg.get("executive_board", {}).get("integrations", {}).get("slack", {})
        token = slack.get("bot_token", "")
        if not token:
            return None
        return cls(
            bot_token=token,
            channel_ids=slack.get("channel_ids", []),
        )
