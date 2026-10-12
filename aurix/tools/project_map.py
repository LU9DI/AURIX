"""Bounded, read-only project inventory for planning engineering tasks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from aurix.tools.workspace import IGNORED_DIRS, _is_sensitive

MAX_FILES = 5000
MAX_MANIFEST_BYTES = 250_000

MANIFEST_ECOSYSTEMS = {
    "pyproject.toml": "python", "requirements.txt": "python", "Pipfile": "python",
    "package.json": "javascript", "pnpm-workspace.yaml": "javascript", "yarn.lock": "javascript",
    "package-lock.json": "javascript", "Cargo.toml": "rust", "go.mod": "go",
    "Gemfile": "ruby", "composer.json": "php", "pom.xml": "java", "build.gradle": "java",
    "build.gradle.kts": "kotlin", "*.csproj": "dotnet", "*.sln": "dotnet",
    "mix.exs": "elixir", "pubspec.yaml": "dart-flutter", "Package.swift": "swift",
}
TEST_DIR_NAMES = {"test", "tests", "__tests__", "spec", "specs", "e2e", "integration"}
CI_MARKERS = {".github/workflows", ".gitlab-ci.yml", "Jenkinsfile", ".circleci/config.yml", "azure-pipelines.yml"}


def inspect_project(workspace: Path | str, *, max_files: int = MAX_FILES) -> dict[str, Any]:
    """Summarize repository structure without executing project code or reading secrets."""
    root = Path(workspace).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be a directory")
    cap = max(100, min(int(max_files), MAX_FILES))
    ecosystems: set[str] = set()
    manifests: list[str] = []
    tests: list[str] = []
    ci: list[str] = []
    source_counts: dict[str, int] = {}
    package_scripts: dict[str, list[str]] = {}
    visited = 0
    truncated = False

    # Walk without following symlink directories; prune common generated/vendor trees.
    for current, dirs, files in _walk(root):
        relative_dir = Path(current).relative_to(root)
        dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS and not (Path(current) / d).is_symlink())
        for filename in sorted(files):
            path = Path(current) / filename
            rel = path.relative_to(root).as_posix()
            if path.is_symlink() or _is_sensitive(path):
                continue
            visited += 1
            if visited > cap:
                truncated = True
                break
            if filename in MANIFEST_ECOSYSTEMS:
                manifests.append(rel)
                ecosystems.add(MANIFEST_ECOSYSTEMS[filename])
            elif filename.endswith((".csproj", ".sln")):
                manifests.append(rel)
                ecosystems.add("dotnet")
            if filename in {"pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "Gemfile", "composer.json"}:
                ecosystems.add({"pyproject.toml": "python", "package.json": "javascript", "Cargo.toml": "rust", "go.mod": "go", "pom.xml": "java", "Gemfile": "ruby", "composer.json": "php"}[filename])
            suffix = path.suffix.lower()
            if suffix in {".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".rs", ".java", ".kt", ".rb", ".php", ".cs", ".swift", ".dart"}:
                source_counts[suffix] = source_counts.get(suffix, 0) + 1
            if (any(part.lower() in TEST_DIR_NAMES for part in Path(rel).parts[:-1])
                    or filename.lower().startswith(("test_", "spec_"))
                    or filename.lower().endswith((".test.js", ".test.ts", ".spec.js", ".spec.ts", "_test.go"))):
                if len(tests) < 300:
                    tests.append(rel)
            if rel in CI_MARKERS or rel.startswith(".github/workflows/"):
                if len(ci) < 100:
                    ci.append(rel)
            if filename == "package.json" and path.stat().st_size <= MAX_MANIFEST_BYTES:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    scripts = data.get("scripts", {}) if isinstance(data, dict) else {}
                    if isinstance(scripts, dict):
                        package_scripts[rel] = sorted(str(key)[:100] for key in scripts if isinstance(key, str))[:100]
                except (OSError, UnicodeError, json.JSONDecodeError):
                    pass
        if truncated:
            break

    return {
        "status": "completed", "tool": "inspect_project", "workspace": str(root),
        "ecosystems": sorted(ecosystems), "manifests": manifests[:200],
        "source_file_counts_by_extension": dict(sorted(source_counts.items())),
        "test_files": tests, "test_files_truncated": len(tests) >= 300,
        "ci_configuration": ci, "package_script_names": package_scripts,
        "files_inspected": min(visited, cap), "truncated": truncated,
        "execution_performed": False,
        "note": "Inventory is structural evidence only; no package scripts, tests, or project files were executed.",
    }


def _walk(root: Path):
    import os
    return os.walk(root, topdown=True, followlinks=False)
