"""Bounded, read-only Python structural analysis for the REA-Symbolic layer."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path
from typing import Any

from aurix.tools.structural_graph import build_structural_graph
from aurix.tools.workspace import list_files, read_text

MAX_PYTHON_FILES = 300
MAX_SOURCE_CHARS = 50_000
MAX_SYMBOLS = 500
MAX_RELATIONS = 1_000


def analyze_python_code(
    workspace: Path | str, *, path: str = ".", max_files: int = MAX_PYTHON_FILES
) -> dict[str, Any]:
    """Extract syntax-level evidence from Python files without importing or executing them.

    This is an initial structural model, not full type inference or whole-program semantics.
    Paths and file contents are obtained through the existing workspace safety policy.
    """
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be a directory")
    if not isinstance(path, str) or not path.strip():
        raise ValueError("Python analysis path must be a non-empty relative directory")
    if Path(path).is_absolute() or ".." in Path(path).parts:
        raise PermissionError("Python analysis path must remain inside the workspace")
    if isinstance(max_files, bool) or not isinstance(max_files, int):
        raise ValueError("max_files must be an integer")

    cap = max(1, min(max_files, MAX_PYTHON_FILES))
    entries = list_files(root, path, limit=1000)
    candidates = [item for item in entries if item.endswith(".py") and not item.endswith("/")]
    files: list[dict[str, Any]] = []
    symbols: list[dict[str, Any]] = []
    relations: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    truncated = len(candidates) > cap

    for relative in candidates[:cap]:
        try:
            source = read_text(root, relative, max_chars=MAX_SOURCE_CHARS)
        except (OSError, UnicodeError, ValueError, PermissionError) as exc:
            errors.append({"path": relative, "kind": "read_error", "message": str(exc)[:160]})
            continue

        if len(source) >= MAX_SOURCE_CHARS:
            files.append(
                {
                    "path": relative,
                    "characters": len(source),
                    "status": "source_limit_exceeded",
                }
            )
            errors.append(
                {
                    "path": relative,
                    "kind": "source_limit_exceeded",
                    "message": "Source reached the per-file analysis limit; syntax was not inferred.",
                }
            )
            continue

        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        record: dict[str, Any] = {
            "path": relative,
            "sha256": digest,
            "characters": len(source),
            "status": "parsed",
        }
        try:
            tree = ast.parse(source, filename=relative)
        except SyntaxError as exc:
            record["status"] = "syntax_error"
            errors.append(
                {
                    "path": relative,
                    "kind": "syntax_error",
                    "line": exc.lineno,
                    "message": (exc.msg or "invalid syntax")[:160],
                }
            )
            files.append(record)
            continue

        record["top_level_nodes"] = len(tree.body)
        files.append(record)
        module_name = relative[:-3].replace("/", ".")
        if module_name.endswith(".__init__"):
            module_name = module_name[: -len(".__init__")]

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if len(symbols) < MAX_SYMBOLS:
                    symbols.append(
                        {
                            "kind": (
                                "class" if isinstance(node, ast.ClassDef)
                                else "async_function" if isinstance(node, ast.AsyncFunctionDef)
                                else "function"
                            ),
                            "name": node.name,
                            "module": module_name,
                            "path": relative,
                            "line": node.lineno,
                            "end_line": getattr(node, "end_lineno", node.lineno),
                        }
                    )
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if len(relations) < MAX_RELATIONS:
                        relations.append(
                            {
                                "kind": "imports",
                                "source": module_name,
                                "target": alias.name,
                                "path": relative,
                                "line": node.lineno,
                            }
                        )
            elif isinstance(node, ast.ImportFrom):
                target = "." * node.level + (node.module or "")
                if len(relations) < MAX_RELATIONS:
                    relations.append(
                        {
                            "kind": "imports",
                            "source": module_name,
                            "target": target,
                            "path": relative,
                            "line": node.lineno,
                        }
                    )
            elif isinstance(node, ast.Call):
                if len(relations) < MAX_RELATIONS:
                    relations.append(
                        {
                            "kind": "calls",
                            "source": module_name,
                            "target": _call_name(node.func),
                            "path": relative,
                            "line": getattr(node, "lineno", 1),
                        }
                    )

    return {
        "status": "completed",
        "tool": "analyze_python_code",
        "workspace": str(root),
        "scope": path,
        "files_analyzed": len(files),
        "files": files,
        "symbols": symbols,
        "relations": relations,
        "graph": build_structural_graph(files, relations),
        "errors": errors[:100],
        "truncated": truncated or len(symbols) >= MAX_SYMBOLS or len(relations) >= MAX_RELATIONS,
        "execution_performed": False,
        "analysis_level": "python_ast_syntax",
        "limitations": [
            "Imports and calls are syntax-level references, not resolved runtime edges.",
            "No type inference, import execution, plugin loading, or project code execution occurs.",
        ],
    }


def _call_name(node: ast.expr) -> str:
    parts: list[str] = []
    current: ast.expr | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    elif isinstance(current, ast.Constant) and isinstance(current.value, str):
        parts.append(repr(current.value))
    else:
        parts.append(type(current).__name__ if current is not None else "unknown")
    return ".".join(reversed(parts))[:240]
