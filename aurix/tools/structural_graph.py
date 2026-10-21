"""Conservative module dependency graph derived from Python AST evidence."""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import PurePosixPath
from typing import Any


def _module_name(path: str) -> str:
    module = path[:-3].replace("/", ".")
    if module.endswith(".__init__"):
        module = module[: -len(".__init__")]
    elif module == "__init__":
        return ""
    return module


def _resolve_import(source_path: str, target: str, modules: set[str]) -> str | None:
    """Resolve an import only when its target maps to a module in this snapshot."""
    level = len(target) - len(target.lstrip("."))
    module = target[level:]
    if level:
        source_module = _module_name(source_path)
        source_is_package = PurePosixPath(source_path).name == "__init__.py"
        package = source_module if source_is_package else source_module.rpartition(".")[0]
        parts = package.split(".") if package else []
        if not parts or level > len(parts):
            return None
        prefix = parts[: len(parts) - level + 1]
        candidate = ".".join(prefix + (module.split(".") if module else []))
    else:
        candidate = module
    return candidate if candidate in modules else None


def _cycles(nodes: set[str], edges: list[dict[str, Any]]) -> list[list[str]]:
    adjacency: dict[str, set[str]] = {node: set() for node in nodes}
    for edge in edges:
        if edge["kind"] == "imports":
            adjacency[edge["source"]].add(edge["target"])

    index = 0
    indexes: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    result: list[list[str]] = []

    def visit(node: str) -> None:
        nonlocal index
        indexes[node] = lowlinks[node] = index
        index += 1
        stack.append(node)
        on_stack.add(node)
        for neighbor in sorted(adjacency[node]):
            if neighbor not in indexes:
                visit(neighbor)
                lowlinks[node] = min(lowlinks[node], lowlinks[neighbor])
            elif neighbor in on_stack:
                lowlinks[node] = min(lowlinks[node], indexes[neighbor])
        if lowlinks[node] == indexes[node]:
            component: list[str] = []
            while True:
                neighbor = stack.pop()
                on_stack.remove(neighbor)
                component.append(neighbor)
                if neighbor == node:
                    break
            if len(component) > 1 or node in adjacency[node]:
                result.append(sorted(component))

    for node in sorted(nodes):
        if node not in indexes:
            visit(node)
    return sorted(result)


def build_structural_graph(
    files: list[dict[str, Any]],
    relations: list[dict[str, Any]],
    symbols: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a graph of modules and locally resolvable imports; unresolved edges stay explicit."""
    by_path = {
        item["path"]: item
        for item in files
        if item.get("status") == "parsed" and item.get("path", "").endswith(".py")
    }
    paths_by_module: dict[str, list[str]] = defaultdict(list)
    for path in by_path:
        module = _module_name(path)
        if module:
            paths_by_module[module].append(path)
    ambiguous_modules = sorted(
        module for module, paths in paths_by_module.items() if len(paths) > 1
    )
    module_to_path = {
        module: paths[0]
        for module, paths in paths_by_module.items()
        if len(paths) == 1
    }
    valid_paths = set(module_to_path.values())
    modules = set(module_to_path)
    nodes = [
        {"module": module, "path": module_to_path[module], "sha256": by_path[module_to_path[module]].get("sha256", "")}
        for module in sorted(modules)
    ]
    edges: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    symbol_counts: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for symbol in symbols or []:
        if symbol.get("module") in modules and isinstance(symbol.get("name"), str):
            symbol_counts[symbol["module"]][symbol["name"]] += 1
    resolved_calls: list[dict[str, Any]] = []
    for relation in relations:
        if relation.get("kind") == "calls":
            source = relation.get("source", "")
            target = relation.get("target", "")
            path = relation.get("path", "")
            if (
                source in modules
                and path in valid_paths
                and target.isidentifier()
                and symbol_counts[source].get(target, 0) == 1
            ):
                resolved_calls.append({
                    "source_module": source,
                    "target_symbol": f"{source}.{target}",
                    "path": path,
                    "line": relation.get("line", 1),
                    "resolution": "unique_same_module_name",
                })
            continue
        if relation.get("kind") != "imports":
            continue
        source = relation.get("source", "")
        path = relation.get("path", "")
        target = relation.get("target", "")
        if source not in modules or path not in valid_paths:
            continue
        resolved = _resolve_import(path, target, modules)
        imported_modules = sorted(
            {
                candidate
                for name in relation.get("imported_names", [])
                if isinstance(name, str) and name.isidentifier()
                for candidate in [_resolve_import(path, f"{target}.{name}", modules)]
                if candidate is not None
            }
        )
        evidence = {"source": source, "target": target, "path": path, "line": relation.get("line", 1)}
        if resolved is not None:
            edges.append({**evidence, "kind": "imports", "target": resolved})
        elif not imported_modules:
            unresolved.append(evidence)
        for imported_module in imported_modules:
            if imported_module != resolved:
                edges.append({
                    **evidence,
                    "kind": "imports",
                    "target": imported_module,
                    "resolution": "imported_submodule",
                })
    return {
        "nodes": nodes,
        "edges": sorted(edges, key=lambda item: (item["source"], item["target"], item["path"], item["line"])),
        "unresolved_imports": sorted(unresolved, key=lambda item: (item["path"], item["line"])),
        "resolved_calls": sorted(resolved_calls, key=lambda item: (item["path"], item["line"])),
        "cycles": _cycles(modules, edges),
        "ambiguous_modules": ambiguous_modules,
        "resolution": "local_modules_only",
    }


def compare_graph_snapshots(previous: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Compare graph snapshots and conservatively invalidate reverse dependents of changed modules."""
    old_nodes = {node["module"]: node for node in previous.get("nodes", [])}
    new_nodes = {node["module"]: node for node in current.get("nodes", [])}
    old_paths = {node["path"]: node for node in old_nodes.values()}
    new_paths = {node["path"]: node for node in new_nodes.values()}
    added = sorted(new_paths.keys() - old_paths.keys())
    removed = sorted(old_paths.keys() - new_paths.keys())
    changed = sorted(
        path for path in old_paths.keys() & new_paths.keys()
        if old_paths[path].get("sha256") != new_paths[path].get("sha256")
    )
    changed_modules = {
        node["module"]
        for path in added + changed
        for node in [new_paths[path]]
    }
    changed_modules.update(old_paths[path]["module"] for path in removed)

    reverse: dict[str, set[str]] = defaultdict(set)
    for snapshot in (previous, current):
        for edge in snapshot.get("edges", []):
            if edge.get("kind") == "imports":
                reverse[edge["target"]].add(edge["source"])
    affected = set(changed_modules)
    queue = deque(sorted(changed_modules))
    while queue:
        target = queue.popleft()
        for dependent in sorted(reverse[target]):
            if dependent not in affected:
                affected.add(dependent)
                queue.append(dependent)

    current_paths = {node["module"]: node["path"] for node in new_nodes.values()}
    invalidated = set(added + removed + changed)
    invalidated.update(current_paths[module] for module in affected if module in current_paths)
    return {
        "added_files": added,
        "removed_files": removed,
        "changed_files": changed,
        "affected_modules": sorted(affected),
        "invalidated_files": sorted(invalidated),
    }
