"""
Notion Integration — read-only.

Pulls database pages (OKR trackers, risk registers, status pages) from Notion.
Maps to OrgSnapshot.active_initiatives, OrgSnapshot.open_risks.

Authentication: Notion integration token (Bearer).
Docs: https://developers.notion.com/reference/post-database-query
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


class NotionIntegration:
    """Read-only Notion client. Only queries database pages — never writes."""

    def __init__(self, api_key: str, database_ids: Optional[list[str]] = None):
        if not api_key:
            raise ValueError("Notion requires an api_key.")
        self._headers = {
            "Authorization":  f"Bearer {api_key}",
            "Notion-Version": NOTION_VERSION,
            "Content-Type":   "application/json",
        }
        self.database_ids = database_ids or []

    def query_database(
        self,
        database_id: str,
        filter_body: Optional[dict] = None,
        max_pages: int = 50,
    ) -> list[dict]:
        """
        Query a Notion database and return all page objects.
        Handles pagination automatically.
        """
        pages: list[dict] = []
        cursor: Optional[str] = None

        try:
            with httpx.Client(headers=self._headers, timeout=20) as client:
                while len(pages) < max_pages:
                    body: dict = {"page_size": min(100, max_pages - len(pages))}
                    if filter_body:
                        body["filter"] = filter_body
                    if cursor:
                        body["start_cursor"] = cursor

                    r = client.post(
                        f"{NOTION_API}/databases/{database_id}/query",
                        json=body,
                    )
                    r.raise_for_status()
                    data = r.json()

                    pages.extend(data.get("results", []))

                    if not data.get("has_more"):
                        break
                    cursor = data.get("next_cursor")

        except Exception as e:
            logger.warning(f"Notion query failed (db={database_id}): {e}")

        return pages

    def query_all_configured_databases(self) -> dict:
        """
        Query all database IDs configured in config.yaml.

        Returns: {"pages": [page, ...], "database_count": N}
        """
        all_pages: list[dict] = []
        for db_id in self.database_ids:
            pages = self.query_database(db_id)
            for page in pages:
                page["_database_id"] = db_id
            all_pages.extend(pages)
        return {"pages": all_pages, "database_count": len(self.database_ids)}

    def get_page_title(self, page: dict) -> str:
        """Extract the plain text title from a Notion page."""
        props = page.get("properties", {})
        for key in ("Name", "Title", "title"):
            prop = props.get(key, {})
            t = prop.get("title") or prop.get("rich_text", [])
            if t:
                return "".join(item.get("plain_text", "") for item in t)
        return "(untitled)"

    def get_property_text(self, page: dict, property_name: str) -> Optional[str]:
        """Extract text value from any property by name."""
        prop = page.get("properties", {}).get(property_name, {})
        ptype = prop.get("type")

        if ptype == "title":
            items = prop.get("title", [])
            return "".join(i.get("plain_text", "") for i in items) or None
        if ptype == "rich_text":
            items = prop.get("rich_text", [])
            return "".join(i.get("plain_text", "") for i in items) or None
        if ptype == "select":
            return (prop.get("select") or {}).get("name")
        if ptype == "multi_select":
            return ", ".join(s["name"] for s in prop.get("multi_select", []))
        if ptype == "date":
            d = prop.get("date") or {}
            return d.get("start")
        if ptype == "checkbox":
            return str(prop.get("checkbox", False))
        if ptype == "number":
            v = prop.get("number")
            return str(v) if v is not None else None
        if ptype == "url":
            return prop.get("url")
        if ptype == "email":
            return prop.get("email")
        if ptype == "people":
            people = prop.get("people", [])
            return ", ".join(p.get("name", "") for p in people) or None
        return None

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> Optional["NotionIntegration"]:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        notion = cfg.get("executive_board", {}).get("integrations", {}).get("notion", {})
        api_key = notion.get("api_key", "")
        if not api_key:
            return None
        return cls(
            api_key=api_key,
            database_ids=notion.get("database_ids", []),
        )
