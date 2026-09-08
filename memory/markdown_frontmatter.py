"""
Read/write markdown files with YAML frontmatter.

Uses pyyaml's real parser/dumper — not a hand-rolled flat-key-only regex
parser. That specific weakness was found in the cognitiveBrain reference
this design borrows from (docs/packages/cognitiveBrain/memory's
ObsidianVaultProvider only understands flat `key: value` and simple
`[a, b]` arrays; nested structures silently break it). There's no reason
to inherit that limitation — pyyaml is already a project dependency.
"""

from pathlib import Path
from typing import Any

import yaml

_DELIM = "---"


def read_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a markdown document into (frontmatter dict, body). Missing or
    malformed frontmatter returns an empty dict and the original text as body."""
    if not text.startswith(_DELIM):
        return {}, text

    parts = text.split(_DELIM, 2)
    if len(parts) < 3:
        return {}, text

    _, header, body = parts
    try:
        frontmatter = yaml.safe_load(header) or {}
    except yaml.YAMLError:
        return {}, text
    if not isinstance(frontmatter, dict):
        return {}, text
    return frontmatter, body.strip("\n")


def write_frontmatter(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize a (frontmatter dict, body) pair back into a markdown document."""
    header = yaml.safe_dump(
        frontmatter, sort_keys=False, default_flow_style=None, allow_unicode=True
    ).strip()
    return f"{_DELIM}\n{header}\n{_DELIM}\n\n{body.strip()}\n"


def read_markdown_file(path: Path) -> tuple[dict[str, Any], str]:
    return read_frontmatter(path.read_text(encoding="utf-8"))


def write_markdown_file(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    """Atomic write — matches store/skills_store.py's tmp-then-replace pattern."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(write_frontmatter(frontmatter, body), encoding="utf-8")
    tmp.replace(path)
