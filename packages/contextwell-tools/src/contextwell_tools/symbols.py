"""Tree-sitter backed symbol indexing for `symbol_search`.

Each source file is parsed once into a `FileIndex` (definitions, calls, identifier occurrences) that is cached
by mtime/size. References and call graphs are answered from these indexes by name: comments and string literals
never match, but there is no type or import resolution, so same-named symbols in different scopes are conflated.
"""

from __future__ import annotations

import os
import re
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import tree_sitter as ts
import tree_sitter_go
import tree_sitter_javascript
import tree_sitter_python
import tree_sitter_typescript
from copilot_fusion_shared import resolve_path

_MAX_FILE_BYTES = 2_000_000
_CACHE_MAXSIZE = 2048
_SKIP_DIRS = {
    ".git",
    ".hg",
    ".jj",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
    "vendor",
}
_SUFFIX_LANGUAGE = {
    ".py": ("python", "py"),
    ".js": ("javascript", "js"),
    ".jsx": ("javascript", "js"),
    ".mjs": ("javascript", "js"),
    ".cjs": ("javascript", "js"),
    ".ts": ("typescript", "ts"),
    ".mts": ("typescript", "ts"),
    ".cts": ("typescript", "ts"),
    ".tsx": ("typescript", "tsx"),
    ".go": ("go", "go"),
}
_DOTTED_RE = re.compile(r"^[\w$]+(?:\.[\w$]+)*$")
_JS_FUNCTION_VALUES = {"arrow_function", "function_expression", "function", "generator_function"}

Position = tuple[int, int]  # raw tree-sitter (row, byte column)


@dataclass(slots=True)
class Definition:
    name: str
    kind: str  # function | class | variable
    line: int
    column: int
    end_line: int
    parent: str
    span: tuple[Position, Position]
    body_span: tuple[Position, Position] | None = None


@dataclass(slots=True)
class Call:
    name: str  # final identifier, e.g. "helper" for self.helper()
    callee: str  # dotted text when simple, e.g. "self.helper"
    line: int
    column: int
    owner: str  # enclosing named function, or "<module>"
    pos: Position


@dataclass(slots=True)
class FileIndex:
    path: Path
    language: str
    lines: list[str]
    definitions: list[Definition] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    calls_by_name: dict[str, list[Call]] = field(default_factory=lambda: defaultdict(list))
    identifiers: dict[str, list[tuple[int, int]]] = field(default_factory=lambda: defaultdict(list))


def _text(node: ts.Node | None) -> str:
    return node.text.decode("utf-8", "replace") if node is not None and node.text is not None else ""


class _Lang:
    """Per-language extraction rules; subclasses override the hooks."""

    identifier_types: frozenset[str] = frozenset({"identifier"})

    def definitions(self, node: ts.Node, owner: str | None, container: str | None) -> list[tuple[ts.Node, str, str]]:
        return []

    def scope(self, node: ts.Node, owner: str | None, container: str | None) -> tuple[str | None, str | None]:
        return owner, container

    def child_scope(
        self, node: ts.Node, child: ts.Node, owner: str | None, container: str | None
    ) -> tuple[str | None, str | None]:
        return self.scope(node, owner, container)

    def call_target(self, node: ts.Node) -> ts.Node | None:
        """Return (function-expression node) for call-like nodes, else None."""
        return None

    def call_name(self, target: ts.Node) -> str:
        return _text(target) if target.type in self.identifier_types else ""

    def skip_identifier(self, node: ts.Node) -> bool:
        return False


class _Python(_Lang):
    def definitions(self, node, owner, container):
        kind = {"function_definition": "function", "class_definition": "class"}.get(node.type)
        if kind:
            name = node.child_by_field_name("name")
            return [(name, kind, container or "")] if name else []
        if node.type == "assignment" and owner is None and container is None:
            parent = node.parent
            left = node.child_by_field_name("left")
            if left is not None and left.type == "identifier" and parent is not None:
                if (
                    parent.type == "expression_statement"
                    and parent.parent is not None
                    and parent.parent.type == "module"
                ):
                    return [(left, "variable", "")]
        return []

    def scope(self, node, owner, container):
        if node.type == "function_definition":
            return _text(node.child_by_field_name("name")) or owner, None
        if node.type == "class_definition":
            return owner, _text(node.child_by_field_name("name")) or container
        return owner, container

    def child_scope(self, node, child, owner, container):
        if node.type == "function_definition":
            body = node.child_by_field_name("body")
            if body is None or child.start_byte != body.start_byte or child.end_byte != body.end_byte:
                return owner, container
        return self.scope(node, owner, container)

    def call_target(self, node):
        return node.child_by_field_name("function") if node.type == "call" else None

    def call_name(self, target):
        if target.type == "identifier":
            return _text(target)
        if target.type == "attribute":
            return _text(target.child_by_field_name("attribute"))
        return ""

    def skip_identifier(self, node):
        parent = node.parent
        return parent is not None and parent.type == "keyword_argument" and parent.child_by_field_name("name") == node


class _JavaScript(_Lang):
    identifier_types = frozenset(
        {"identifier", "property_identifier", "type_identifier", "shorthand_property_identifier"}
    )
    class_types = frozenset(
        {
            "class_declaration",
            "abstract_class_declaration",
            "interface_declaration",
            "enum_declaration",
            "type_alias_declaration",
        }
    )

    def definitions(self, node, owner, container):
        t = node.type
        name = node.child_by_field_name("name")
        if t in {"function_declaration", "generator_function_declaration"} and name:
            return [(name, "function", "")]
        if t in self.class_types and name:
            return [(name, "class", "")]
        if t == "method_definition" and name and name.type == "property_identifier":
            return [(name, "function", container or "")]
        if t in {"field_definition", "public_field_definition"}:
            prop = node.child_by_field_name("property") or node.child_by_field_name("name")
            value = node.child_by_field_name("value")
            if prop is not None and value is not None and value.type in _JS_FUNCTION_VALUES:
                return [(prop, "function", container or "")]
        if t == "variable_declarator" and name is not None and name.type == "identifier":
            if owner is None and container is None:
                value = node.child_by_field_name("value")
                is_fn = value is not None and value.type in _JS_FUNCTION_VALUES
                return [(name, "function" if is_fn else "variable", "")]
        return []

    def scope(self, node, owner, container):
        t = node.type
        if t in {"function_declaration", "generator_function_declaration", "method_definition"}:
            return _text(node.child_by_field_name("name")) or owner, None
        if t in {"variable_declarator", "field_definition", "public_field_definition"}:
            name = (
                node.child_by_field_name("name")
                if t == "variable_declarator"
                else node.child_by_field_name("property") or node.child_by_field_name("name")
            )
            value = node.child_by_field_name("value")
            if name is not None and value is not None and value.type in _JS_FUNCTION_VALUES:
                return _text(name), None
        if t in self.class_types or t == "class":
            return owner, _text(node.child_by_field_name("name")) or container
        return owner, container

    def call_target(self, node):
        if node.type == "call_expression":
            return node.child_by_field_name("function")
        if node.type == "new_expression":
            return node.child_by_field_name("constructor")
        return None

    def call_name(self, target):
        if target.type == "identifier":
            return _text(target)
        if target.type == "member_expression":
            return _text(target.child_by_field_name("property"))
        return ""


class _Go(_Lang):
    identifier_types = frozenset({"identifier", "field_identifier", "type_identifier"})

    def definitions(self, node, owner, container):
        t = node.type
        if t == "function_declaration":
            name = node.child_by_field_name("name")
            return [(name, "function", "")] if name else []
        if t == "method_declaration":
            name = node.child_by_field_name("name")
            return [(name, "function", self._receiver_type(node))] if name else []
        if t in {"type_spec", "type_alias"}:
            name = node.child_by_field_name("name")
            return [(name, "class", "")] if name else []
        if t in {"const_spec", "var_spec"} and owner is None:
            return [(n, "variable", "") for n in node.children_by_field_name("name")]
        return []

    @staticmethod
    def _receiver_type(node: ts.Node) -> str:
        stack = [node.child_by_field_name("receiver")]
        while stack:
            current = stack.pop()
            if current is None:
                continue
            if current.type == "type_identifier":
                return _text(current)
            stack.extend(reversed(current.children))
        return ""

    def scope(self, node, owner, container):
        if node.type in {"function_declaration", "method_declaration"}:
            return _text(node.child_by_field_name("name")) or owner, None
        return owner, container

    def call_target(self, node):
        return node.child_by_field_name("function") if node.type == "call_expression" else None

    def call_name(self, target):
        if target.type == "identifier":
            return _text(target)
        if target.type == "selector_expression":
            return _text(target.child_by_field_name("field"))
        return ""


_LANGS: dict[str, _Lang] = {
    "py": _Python(),
    "js": _JavaScript(),
    "ts": _JavaScript(),
    "tsx": _JavaScript(),
    "go": _Go(),
}


@lru_cache(maxsize=None)
def _language(grammar: str) -> ts.Language:
    capsule = {
        "py": tree_sitter_python.language,
        "js": tree_sitter_javascript.language,
        "ts": tree_sitter_typescript.language_typescript,
        "tsx": tree_sitter_typescript.language_tsx,
        "go": tree_sitter_go.language,
    }[grammar]()
    return ts.Language(capsule)


def _char_column(line: str, byte_col: int) -> int:
    """1-based character column from a tree-sitter byte column."""
    if line.isascii():
        return byte_col + 1
    return len(line.encode("utf-8")[:byte_col].decode("utf-8", "ignore")) + 1


def _line_at(lines: list[str], row: int) -> str:
    return lines[row] if 0 <= row < len(lines) else ""


def _build_index(path: Path, language: str, grammar: str, source: bytes) -> FileIndex:
    spec = _LANGS[grammar]
    root = ts.Parser(_language(grammar)).parse(source).root_node
    lines = [line.rstrip("\r") for line in source.decode("utf-8", "replace").split("\n")]
    index = FileIndex(path=path, language=language, lines=lines)
    stack: list[tuple[ts.Node, str | None, str | None]] = [(root, None, None)]
    while stack:
        node, owner, container = stack.pop()
        if node.type in spec.identifier_types and not spec.skip_identifier(node):
            row, col = node.start_point
            index.identifiers[_text(node)].append((row, col))
        for name_node, kind, parent in spec.definitions(node, owner, container):
            row, col = name_node.start_point
            body = node.child_by_field_name("body") if grammar == "py" and node.type == "function_definition" else None
            index.definitions.append(
                Definition(
                    name=_text(name_node),
                    kind=kind,
                    line=row + 1,
                    column=_char_column(_line_at(lines, row), col),
                    end_line=node.end_point[0] + 1,
                    parent=parent,
                    span=(node.start_point, node.end_point),
                    body_span=(body.start_point, body.end_point) if body is not None else None,
                )
            )
        target = spec.call_target(node)
        if target is not None:
            name = spec.call_name(target)
            if name:
                row, col = target.start_point
                callee = _text(target)
                call = Call(
                    name=name,
                    callee=callee if _DOTTED_RE.match(callee) else name,
                    line=row + 1,
                    column=_char_column(_line_at(lines, row), col),
                    owner=owner or "<module>",
                    pos=node.start_point,
                )
                index.calls.append(call)
                index.calls_by_name[name].append(call)
        stack.extend((child, *spec.child_scope(node, child, owner, container)) for child in reversed(node.children))
    return index


_CACHE: OrderedDict[Path, tuple[int, int, FileIndex]] = OrderedDict()


def language_for(path: Path) -> str | None:
    entry = _SUFFIX_LANGUAGE.get(path.suffix.lower())
    return entry[0] if entry else None


def invalidate(path: Path) -> None:
    _CACHE.pop(path, None)


def index_file(path: Path) -> FileIndex | None:
    entry = _SUFFIX_LANGUAGE.get(path.suffix.lower())
    if entry is None:
        return None
    try:
        stat = path.stat()
        if stat.st_size > _MAX_FILE_BYTES:
            return None
        cached = _CACHE.get(path)
        if cached and cached[0] == stat.st_mtime_ns and cached[1] == stat.st_size:
            _CACHE.move_to_end(path)
            return cached[2]
        source = path.read_bytes()
    except OSError:
        return None
    index = _build_index(path, entry[0], entry[1], source)
    if path not in _CACHE and len(_CACHE) >= _CACHE_MAXSIZE:
        _CACHE.popitem(last=False)
    _CACHE[path] = (stat.st_mtime_ns, stat.st_size, index)
    return index


def iter_indexes(paths: list[str]) -> Iterator[FileIndex]:
    """Index supported files lazily under the given files/directories."""
    seen: set[Path] = set()
    for source in paths:
        resolved = resolve_path(source)
        if resolved.is_file():
            candidates = (resolved,)
        elif resolved.is_dir():

            def walk_files(root: Path) -> Iterator[Path]:
                for directory, dirs, names in os.walk(root):
                    dirs[:] = sorted(d for d in dirs if d not in _SKIP_DIRS)
                    for name in sorted(names):
                        if Path(name).suffix.lower() in _SUFFIX_LANGUAGE:
                            yield Path(directory) / name

            candidates = walk_files(resolved)
        else:
            continue
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            index = index_file(path)
            if index is not None:
                yield index


def collect_indexes(paths: list[str]) -> list[FileIndex]:
    """Index every supported file under the given files/directories (vendored/cache dirs are skipped)."""
    return list(iter_indexes(paths))


def signature_of(index: FileIndex, definition: Definition) -> tuple[str, int]:
    """Return (stripped declaration line, indentation width)."""
    line = _line_at(index.lines, definition.line - 1)
    return line.strip(), len(line) - len(line.lstrip(" "))


def count_same_name(indexes: list[FileIndex]) -> Counter[tuple[str, str]]:
    counts: Counter[tuple[str, str]] = Counter()
    for index in indexes:
        for definition in index.definitions:
            counts[(definition.name, definition.kind)] += 1
    return counts


def find_references(
    indexes: list[FileIndex],
    definition: Definition,
    declaration: FileIndex,
    include_callsites: bool,
    max_items: int,
) -> list[dict[str, object]]:
    references: list[dict[str, object]] = []
    name = definition.name
    for index in indexes:
        call_rows = {call.line - 1 for call in index.calls_by_name.get(name, ())} if include_callsites else set()
        seen_rows: set[int] = set()
        for row, col in sorted(index.identifiers.get(name, ())):
            if index is declaration and row + 1 == definition.line:
                continue
            if row in seen_rows:
                continue
            seen_rows.add(row)
            is_call = definition.kind == "function" and row in call_rows
            line = _line_at(index.lines, row)
            references.append(
                {
                    "path": str(index.path),
                    "line": row + 1,
                    "column": _char_column(line, col),
                    "language": index.language,
                    "snippet": line.strip(),
                    "match_type": "callsite" if is_call else "reference",
                }
            )
            if len(references) >= max_items:
                return references
    return references


def _within(span: tuple[Position, Position], pos: Position) -> bool:
    return span[0] <= pos <= span[1]


def build_callgraph(
    indexes: list[FileIndex],
    definition: Definition,
    declaration: FileIndex,
    max_items: int,
) -> dict[str, object]:
    name = definition.name
    callers: set[str] = set()
    sites: list[dict[str, object]] = []
    callee_counts: Counter[str] = Counter()
    callee_sites: list[dict[str, object]] = []
    truncated = False

    if definition.kind == "function":
        for index in indexes:
            for call in index.calls_by_name.get(name, ()):
                callers.add(call.owner)
                if len(sites) < max_items:
                    sites.append(_site(index, call, "caller", call.owner))
                else:
                    truncated = True
        for call in declaration.calls:
            span = definition.body_span or definition.span
            if call.name == name or not _within(span, call.pos):
                continue
            callee_counts[call.callee] += 1
            if len(callee_sites) < max_items:
                callee_sites.append(_site(declaration, call, "callee", call.callee))
            else:
                truncated = True

    return {
        "callers": sorted(callers),
        "sites": sites,
        "site_count": len(sites),
        "callees": [{"symbol": callee, "count": count} for callee, count in callee_counts.most_common()],
        "callee_sites": callee_sites,
        "truncated": truncated,
    }


def _site(index: FileIndex, call: Call, key: str, value: str) -> dict[str, object]:
    return {
        "path": str(index.path),
        "line": call.line,
        "column": call.column,
        "language": index.language,
        key: value,
        "snippet": _line_at(index.lines, call.line - 1).strip(),
    }
