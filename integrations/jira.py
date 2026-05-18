"""
Jira Integration — read-only.

Fetches epics, stories, and blockers per team/project.
Maps to TeamStatus.active_projects and TeamStatus.blockers.

Authentication: Basic auth with email + API token.
Docs: https://developer.atlassian.com/cloud/jira/platform/rest/v3/
"""

import base64
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_READ_ONLY_METHODS = frozenset({"GET"})


class JiraIntegration:
    """Read-only Jira client. Only GET requests are ever made."""

    def __init__(self, base_url: str, email: str, api_token: str):
        if not all([base_url, email, api_token]):
            raise ValueError("Jira requires base_url, email, and api_token.")
        self.base_url = base_url.rstrip("/")
        credentials  = f"{email}:{api_token}"
        encoded      = base64.b64encode(credentials.encode()).decode()
        self._headers = {
            "Authorization": f"Basic {encoded}",
            "Accept":        "application/json",
            "Content-Type":  "application/json",
        }

    def fetch_issues_by_project(
        self,
        project_keys: list[str],
        max_per_project: int = 50,
    ) -> dict[str, list[dict]]:
        """
        Fetch open issues grouped by project key.

        Returns: {project_key: [issue_dict, ...]}
        """
        result: dict[str, list[dict]] = {}
        for key in project_keys:
            result[key] = self._fetch_project_issues(key, max_per_project)
        return result

    def fetch_issues_by_label(
        self,
        labels: list[str],
        max_results: int = 100,
    ) -> dict[str, list[dict]]:
        """Fetch issues grouped by label (use to group by team/VP)."""
        result: dict[str, list[dict]] = {}
        for label in labels:
            jql = f'labels = "{label}" AND statusCategory != Done ORDER BY priority DESC'
            result[label] = self._search(jql, max_results)
        return result

    def fetch_board_sprints(self, board_id: int) -> list[dict]:
        """Fetch active and recent sprints from an agile board."""
        try:
            with httpx.Client(headers=self._headers, timeout=15) as client:
                r = self._get(client, f"/rest/agile/1.0/board/{board_id}/sprint",
                              params={"state": "active,closed", "maxResults": 5})
                return r.get("values", [])
        except Exception as e:
            logger.warning(f"Jira sprint fetch failed (board {board_id}): {e}")
            return []

    # ── Private ────────────────────────────────────────────────────────────────

    def _fetch_project_issues(self, project_key: str, max_results: int) -> list[dict]:
        jql = (
            f"project = {project_key} "
            f"AND statusCategory != Done "
            f"ORDER BY priority DESC, updated DESC"
        )
        return self._search(jql, max_results)

    def _search(self, jql: str, max_results: int) -> list[dict]:
        try:
            with httpx.Client(headers=self._headers, timeout=20) as client:
                data = self._get(
                    client,
                    "/rest/api/3/search",
                    params={
                        "jql":        jql,
                        "maxResults": max_results,
                        "fields":     "summary,status,assignee,priority,duedate,labels,comment",
                    },
                )
                return data.get("issues", [])
        except Exception as e:
            logger.warning(f"Jira search failed (jql={jql!r}): {e}")
            return []

    def _get(self, client: httpx.Client, path: str, params: Optional[dict] = None) -> dict:
        url = f"{self.base_url}{path}"
        r   = client.get(url, params=params)
        r.raise_for_status()
        return r.json()

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> Optional["JiraIntegration"]:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        jira = cfg.get("executive_board", {}).get("integrations", {}).get("jira", {})
        if not all([jira.get("base_url"), jira.get("email"), jira.get("api_token")]):
            return None
        return cls(
            base_url=jira["base_url"],
            email=jira["email"],
            api_token=jira["api_token"],
        )
