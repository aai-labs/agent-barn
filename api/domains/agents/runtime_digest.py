from __future__ import annotations

import ast
import hashlib
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path

_API_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _API_ROOT.parent
_ENTRY_MODULE = "api.domains.agents.service"
_ENTRY_CLASS = "AgentService"
_ENTRY_METHOD = "_provision_and_start"
_PACKAGE_PREFIX = "api."
_MAX_RESOLVE_DEPTH = 8
_PYCACHE_DIR = "__pycache__"
_ASSET_ROOTS = (
    _API_ROOT / "domains" / "agents" / "scripts",
    _API_ROOT / "domains" / "agents" / "aai_cli_skills" / "bundled",
)
_DEFINITION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
_FUNCTION_NODES = (ast.FunctionDef, ast.AsyncFunctionDef)
_DOCSTRING_OWNERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)

_parse_cache: dict[Path, ast.Module] = {}


def _module_path(module: str) -> Path | None:
    base = _REPO_ROOT / Path(*module.split("."))
    single_file = base.with_suffix(".py")
    if single_file.is_file():
        return single_file
    package_init = base / "__init__.py"
    return package_init if package_init.is_file() else None


def _parse(path: Path) -> ast.Module:
    tree = _parse_cache.get(path)
    if tree is None:
        tree = ast.parse(path.read_text(encoding="utf-8"))
        _parse_cache[path] = tree
    return tree


def _package_of(module: str) -> str:
    path = _module_path(module)
    if path is not None and path.name == "__init__.py":
        return module
    return module.rpartition(".")[0]


def _import_target(node: ast.ImportFrom, module: str) -> str:
    if not node.level:
        return node.module or ""
    base = _package_of(module)
    for _ in range(node.level - 1):
        base = base.rpartition(".")[0]
    return f"{base}.{node.module}" if node.module else base


def _imported_names(tree: ast.Module, module: str) -> dict[str, str]:
    targets: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            target = _import_target(node, module)
            for alias in node.names:
                targets[alias.asname or alias.name] = target
        elif isinstance(node, ast.Import):
            for alias in node.names:
                targets[alias.asname or alias.name] = alias.name
    return targets


def _module_definitions(tree: ast.Module) -> dict[str, ast.stmt]:
    definitions: dict[str, ast.stmt] = {}
    for node in tree.body:
        if isinstance(node, _DEFINITION_NODES):
            definitions.setdefault(node.name, node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    definitions.setdefault(target.id, node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            definitions.setdefault(node.target.id, node)
    return definitions


def _referenced_names(node: ast.AST) -> set[str]:
    names: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            names.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name):
            names.add(child.value.id)
    return names


def _resolve(module: str, name: str, depth: int = 0) -> tuple[str, ast.stmt] | None:
    if depth > _MAX_RESOLVE_DEPTH:
        return None
    path = _module_path(module)
    if path is None:
        return None
    tree = _parse(path)
    definition = _module_definitions(tree).get(name)
    if definition is not None:
        return module, definition
    target = _imported_names(tree, module).get(name)
    if target is None or not target.startswith(_PACKAGE_PREFIX):
        return None
    return _resolve(target, name, depth + 1)


def _resolve_class(module: str, name: str) -> tuple[str, ast.ClassDef] | None:
    resolved = _resolve(module, name)
    if resolved is None:
        return None
    owner_module, node = resolved
    return (owner_module, node) if isinstance(node, ast.ClassDef) else None


def _methods_of(node: ast.ClassDef) -> dict[str, ast.stmt]:
    return {item.name: item for item in node.body if isinstance(item, _FUNCTION_NODES)}


def _annotated_attributes(node: ast.ClassDef) -> dict[str, str]:
    return {
        item.target.id: item.annotation.id
        for item in node.body
        if isinstance(item, ast.AnnAssign)
        and isinstance(item.target, ast.Name)
        and isinstance(item.annotation, ast.Name)
    }


def _self_method_calls(node: ast.AST, methods: dict[str, ast.stmt]) -> set[str]:
    called: set[str] = set()
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Name)
            and child.func.value.id == "self"
            and child.func.attr in methods
        ):
            called.add(child.func.attr)
    return called


def _collaborator_calls(node: ast.AST, attributes: dict[str, str]) -> dict[str, set[str]]:
    calls: dict[str, set[str]] = {}
    for child in ast.walk(node):
        if (
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and isinstance(child.func.value, ast.Attribute)
            and isinstance(child.func.value.value, ast.Name)
            and child.func.value.value.id == "self"
        ):
            annotation = attributes.get(child.func.value.attr)
            if annotation is not None:
                calls.setdefault(annotation, set()).add(child.func.attr)
    return calls


def _reachable_methods(methods: dict[str, ast.stmt], seed: Iterable[str]) -> set[str]:
    reached: set[str] = set()
    pending = list(seed)
    while pending:
        current = pending.pop()
        if current in reached or current not in methods:
            continue
        reached.add(current)
        pending.extend(_self_method_calls(methods[current], methods) - reached)
    return reached


def discover_closure() -> dict[tuple[str, str], ast.stmt]:
    entry = _resolve_class(_ENTRY_MODULE, _ENTRY_CLASS)
    if entry is None:
        raise RuntimeError(f"{_ENTRY_MODULE}.{_ENTRY_CLASS} could not be resolved")

    service_module, service_class = entry
    service_path = _module_path(service_module)
    if service_path is None:
        raise RuntimeError(f"{service_module} has no source file")

    methods = _methods_of(service_class)
    attributes = _annotated_attributes(service_class)
    assembly = _reachable_methods(methods, [_ENTRY_METHOD])
    if _ENTRY_METHOD not in assembly:
        raise RuntimeError(f"{_ENTRY_CLASS}.{_ENTRY_METHOD} was not found")

    collected: dict[tuple[str, str], ast.stmt] = {}
    queue: list[tuple[str, set[str]]] = []
    collaborators: dict[str, set[str]] = {}
    for name in sorted(assembly):
        collected[(service_module, f"{_ENTRY_CLASS}.{name}")] = methods[name]
        queue.append((service_module, _referenced_names(methods[name])))
        for annotation, called in _collaborator_calls(methods[name], attributes).items():
            collaborators.setdefault(annotation, set()).update(called)

    service_imports = _imported_names(_parse(service_path), service_module)
    for annotation, called in collaborators.items():
        origin = service_imports.get(annotation)
        if origin is None or not origin.startswith(_PACKAGE_PREFIX):
            continue
        resolved = _resolve_class(origin, annotation)
        if resolved is None:
            continue
        owner_module, owner_class = resolved
        owner_methods = _methods_of(owner_class)
        for method_name in _reachable_methods(owner_methods, called):
            method = owner_methods[method_name]
            key = (owner_module, f"{annotation}.{method_name}")
            if key not in collected:
                collected[key] = method
                queue.append((owner_module, _referenced_names(method)))

    visited: set[tuple[str, frozenset[str]]] = set()
    while queue:
        module, names = queue.pop()
        marker = (module, frozenset(names))
        if marker in visited:
            continue
        visited.add(marker)
        path = _module_path(module)
        if path is None:
            continue
        tree = _parse(path)
        imports = _imported_names(tree, module)
        definitions = _module_definitions(tree)
        for name in names:
            origin = imports.get(name)
            if origin is not None and origin.startswith(_PACKAGE_PREFIX):
                resolved = _resolve(origin, name)
            elif name in definitions:
                resolved = (module, definitions[name])
            else:
                resolved = None
            if resolved is None:
                continue
            key = (resolved[0], name)
            if key not in collected:
                collected[key] = resolved[1]
                queue.append((resolved[0], _referenced_names(resolved[1])))
    return collected


def _strip_docstrings(node: ast.AST) -> ast.AST:
    for child in ast.walk(node):
        if not isinstance(child, _DOCSTRING_OWNERS):
            continue
        body = child.body
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            child.body = body[1:]
    return node


def normalize_python_source(source: str) -> str:
    return ast.dump(_strip_docstrings(ast.parse(source)))


def asset_files() -> list[Path]:
    files = [
        path for root in _ASSET_ROOTS for path in root.rglob("*") if path.is_file() and _PYCACHE_DIR not in path.parts
    ]
    return sorted(files, key=lambda path: path.relative_to(_API_ROOT).as_posix())


def _static_digest() -> str:
    digest = hashlib.sha256()
    closure = discover_closure()
    for key in sorted(closure):
        module, symbol = key
        digest.update(f"{module}.{symbol}=".encode())
        digest.update(ast.dump(_strip_docstrings(closure[key])).encode())
        digest.update(b"\0")
    for path in asset_files():
        digest.update(path.relative_to(_API_ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


_STATIC_DIGEST = _static_digest()
_parse_cache.clear()


@lru_cache(maxsize=8)
def agent_runtime_config_digest(openclaw_image: str, hermes_image: str) -> str:
    """Identify the code and images an Agent pod would be built from right now."""
    digest = hashlib.sha256()
    digest.update(_STATIC_DIGEST.encode())
    digest.update(b"\0")
    digest.update(openclaw_image.encode())
    digest.update(b"\0")
    digest.update(hermes_image.encode())
    return digest.hexdigest()
