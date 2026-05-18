"""
Linear Integration — read-only.

Fetches issues, cycles (sprints), and projects per team.
Maps to TeamStatus.active_projects and velocity metrics.

Authentication: Linear API key (Bearer token).
Docs: https://developers.linear.app/docs/graphql/working-with-the-graphql-api
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

GRAPHQL_ENDPOINT = "https://api.linear.app/graphql"

ISSUES_QUERY = """
query TeamIssues($teamKey: String!) {
  teams(filter: { key: { eq: $teamKey } }) {
    nodes {
      id
      name
      members { nodes { name } }
      activeCycle {
        id
        number
        startsAt
        endsAt
        completedScopeHistory
        scopeHistory
      }
      issues(
        filter: { state: { type: { nin: ["completed", "cancelled"] } } }
        first: 50
        orderBy: updatedAt
      ) {
        nodes {
          id
          title
          state { name type }
          assignee { name }
          priority
          dueDate
          estimate
          labels { nodes { name } }
        }
      }
    }
  }
}
"""

ALL_TEAMS_QUERY = """
query {
  teams(first: 50) {
    nodes {
      id
      key
      name
    }
  }
}
"""


class LinearIntegration:
    """Read-only Linear client. Only GraphQL queries (not mutations) are sent."""

    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError("Linear requires an api_key.")
        self._headers = {
            "Authorization": api_key,
            "Content-Type":  "application/json",
        }

    def list_teams(self) -> list[dict]:
        """Return all teams: [{id, key, name}]"""
        data = self._query(ALL_TEAMS_QUERY, {})
        return data.get("data", {}).get("teams", {}).get("nodes", [])

    def fetch_issues_by_team(
        self,
        team_keys: list[str],
    ) -> dict[str, list[dict]]:
        """
        Fetch open issues grouped by team key.

        Returns: {team_key: [issue_dict, ...]}
        """
        result: dict[str, list[dict]] = {}
        for key in team_keys:
            raw = self._query(ISSUES_QUERY, {"teamKey": key})
            teams = raw.get("data", {}).get("teams", {}).get("nodes", [])
            if teams:
                team = teams[0]
                issues = team.get("issues", {}).get("nodes", [])
                result[key] = issues
                # Attach cycle info as a meta key for velocity tracking
                if team.get("activeCycle"):
                    result[f"_cycle_{key}"] = team["activeCycle"]
            else:
                result[key] = []
        return result

    def _query(self, query: str, variables: dict) -> dict:
        try:
            with httpx.Client(headers=self._headers, timeout=20) as client:
                r = client.post(
                    GRAPHQL_ENDPOINT,
                    json={"query": query, "variables": variables},
                )
                r.raise_for_status()
                return r.json()
        except Exception as e:
            logger.warning(f"Linear query failed: {e}")
            return {}

    @classmethod
    def from_config(cls, config_path: str = "config.yaml") -> Optional["LinearIntegration"]:
        import yaml
        with open(config_path) as f:
            cfg = yaml.safe_load(f)
        linear = cfg.get("executive_board", {}).get("integrations", {}).get("linear", {})
        api_key = linear.get("api_key", "")
        if not api_key:
            return None
        return cls(api_key=api_key)
