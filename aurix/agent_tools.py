"""Capability-limited, read-only tools that specialist agents may request.

The model never receives shell or arbitrary Python execution. Tool calls are explicit
JSON requests, checked against a role allowlist, schema-validated, and bounded.
Repository content returned by tools is untrusted data, not instructions.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aurix.knowledge import KnowledgeIndex
from aurix.tools.git_inspection import git_status
from aurix.tools.project_map import inspect_project
from aurix.tools.workspace import (
    IGNORED_DIRS,
    _is_sensitive,
    list_files,
    read_text,
    safe_path,
    search_text,
)

# Role-level capabilities are intentionally read-only. No role can write files,
# run arbitrary commands, access credentials, or make network requests.
ROLE_TOOLS: dict[str, tuple[str, ...]] = {
    "generalist": ("project_map", "list_files", "search_workspace", "knowledge_search"),
    "researcher": ("project_map", "search_workspace", "knowledge_search"),
    "architect": ("project_map", "list_files", "search_workspace", "knowledge_search"),
    "coder": ("project_map", "list_files", "read_file", "search_workspace", "knowledge_search"),
    "reviewer": (
        "project_map",
        "list_files",
        "read_file",
        "search_workspace",
        "knowledge_search",
        "git_status",
    ),
    "tester": (
        "project_map",
        "list_files",
        "read_file",
        "search_workspace",
        "knowledge_search",
        "git_status",
    ),
    "security": (
        "project_map",
        "list_files",
        "read_file",
        "search_workspace",
        "knowledge_search",
        "git_status",
    ),
    "documenter": (
        "project_map",
        "list_files",
        "read_file",
        "search_workspace",
        "knowledge_search",
    ),
    "optimizer": (
        "project_map",
        "list_files",
        "read_file",
        "search_workspace",
        "knowledge_search",
        "git_status",
    ),
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "project_map": "Summarize project languages, manifests, tests, and CI. Arguments: {}",
    "list_files": 'List bounded workspace paths. Arguments: {"path": ".", "limit": 100}',
    "read_file": 'Read a non-sensitive text file inside the workspace. Arguments: {"path": "relative/path", "max_chars": 8000}',
    "search_workspace": 'Search literal text in safe text files. Arguments: {"query": "text", "limit": 10}',
    "knowledge_search": 'Search the local AURIX knowledge index. Arguments: {"query": "text", "limit": 5}',
    "git_status": "Read-only Git status; only available to review/security/test/optimization roles. Arguments: {}",
}
MAX_TOOL_CALLS = 3
MAX_TOOL_RESULT_CHARS = 9000


class AgentToolbox:
    def __init__(self, workspace: str | Path, *, knowledge_db: str | Path | None = None) -> None:
        self.workspace = Path(workspace).expanduser().resolve(strict=True)
        if not self.workspace.is_dir():
            raise ValueError("Agent tool workspace must be a directory")
        self.knowledge_db = (
            Path(knowledge_db) if knowledge_db else self.workspace / ".aurix" / "knowledge.db"
        )

    @staticmethod
    def allowed_for(role: str) -> tuple[str, ...]:
        return ROLE_TOOLS.get(role, ())

    def catalog(self, role: str) -> dict[str, str]:
        return {name: TOOL_DESCRIPTIONS[name] for name in self.allowed_for(role)}

    def execute(self, role: str, name: str, arguments: Any) -> dict[str, Any]:
        if name not in self.allowed_for(role):
            raise PermissionError(f"Tool '{name}' is not permitted for role '{role}'")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be a JSON object")
        if name == "project_map":
            self._require_keys(arguments, set())
            result = inspect_project(self.workspace, max_files=2000)
        elif name == "list_files":
            self._require_keys(arguments, {"path", "limit"})
            path = arguments.get("path", ".")
            limit = self._int_arg(arguments.get("limit", 100), "limit", 1, 200)
            if not isinstance(path, str) or len(path) > 500:
                raise ValueError("path must be a relative path of at most 500 characters")
            result = {"files": list_files(self.workspace, path, limit=limit)}
        elif name == "read_file":
            self._require_keys(arguments, {"path", "max_chars"})
            path = arguments.get("path")
            max_chars = self._int_arg(arguments.get("max_chars", 8000), "max_chars", 1, 12000)
            if not isinstance(path, str) or not path or len(path) > 500 or Path(path).is_absolute():
                raise ValueError("path must be a non-empty relative path of at most 500 characters")
            target = safe_path(self.workspace, path)
            relative_parts = target.relative_to(self.workspace).parts
            if any(part in IGNORED_DIRS for part in relative_parts) or _is_sensitive(target):
                raise PermissionError("Tool access to ignored or sensitive paths is not allowed")
            if target.suffix.lower() in {
                ".db",
                ".sqlite",
                ".sqlite3",
                ".pem",
                ".key",
                ".p12",
                ".pfx",
            }:
                raise PermissionError(
                    "Tool access to database or binary/credential files is not allowed"
                )
            result = {"path": path, "content": read_text(self.workspace, path, max_chars=max_chars)}
        elif name == "search_workspace":
            self._require_keys(arguments, {"query", "limit"})
            query = arguments.get("query")
            limit = self._int_arg(arguments.get("limit", 10), "limit", 1, 30)
            if not isinstance(query, str) or not query.strip() or len(query) > 300:
                raise ValueError("query must contain 1-300 characters")
            result = {"matches": search_text(self.workspace, query, limit=limit)}
        elif name == "knowledge_search":
            self._require_keys(arguments, {"query", "limit"})
            query = arguments.get("query")
            limit = self._int_arg(arguments.get("limit", 5), "limit", 1, 10)
            if not isinstance(query, str) or not query.strip() or len(query) > 500:
                raise ValueError("query must contain 1-500 characters")
            if not self.knowledge_db.exists():
                result = {"results": [], "note": "Local knowledge index does not exist yet."}
            else:
                result = {
                    "results": KnowledgeIndex(self.knowledge_db).search(
                        query, limit=limit, max_chars=1200
                    )
                }
        elif name == "git_status":
            self._require_keys(arguments, set())
            result = git_status(self.workspace)
        else:
            raise ValueError("Unknown tool")
        rendered = json.dumps(result, ensure_ascii=False, default=str)
        return {
            "tool": name,
            "status": "completed",
            "result": rendered[:MAX_TOOL_RESULT_CHARS],
            "truncated": len(rendered) > MAX_TOOL_RESULT_CHARS,
        }

    @staticmethod
    def _require_keys(arguments: dict[str, Any], allowed: set[str]) -> None:
        unknown = set(arguments) - allowed
        if unknown:
            raise ValueError(f"Unsupported argument(s): {', '.join(sorted(unknown))}")

    @staticmethod
    def _int_arg(value: Any, name: str, minimum: int, maximum: int) -> int:
        if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
            raise ValueError(f"{name} must be an integer between {minimum} and {maximum}")
        return value


def parse_tool_request(text: str) -> list[dict[str, Any]] | None:
    """Parse the strict single-object tool protocol; plain-text model answers remain valid."""
    if not isinstance(text, str) or len(text) > 30000:
        return None
    candidate = text.strip()
    if candidate.startswith("```json") and candidate.endswith("```"):
        candidate = candidate[7:-3].strip()
    elif candidate.startswith("```") and candidate.endswith("```"):
        candidate = candidate[3:-3].strip()
    try:
        obj = json.loads(candidate)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict) or set(obj) != {"tool_calls"}:
        return None
    calls = obj["tool_calls"]
    if not isinstance(calls, list) or not 1 <= len(calls) <= MAX_TOOL_CALLS:
        return None
    clean: list[dict[str, Any]] = []
    for call in calls:
        if not isinstance(call, dict) or set(call) != {"name", "arguments"}:
            return None
        if not isinstance(call["name"], str) or not isinstance(call["arguments"], dict):
            return None
        clean.append({"name": call["name"], "arguments": call["arguments"]})
    return clean
