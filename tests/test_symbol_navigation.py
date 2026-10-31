"""Tree-sitter `symbol_search` behavior: methods, Go, cross-file callers, and noise rejection."""

from __future__ import annotations

import asyncio
from pathlib import Path

from contextwell_tools import symbols
from copilot_fusion.server import create_server


def _search(paths: list[Path], **args: object) -> list[dict]:
    async def _run() -> object:
        result = await create_server().call_tool("symbol_search", {"paths": [str(p) for p in paths], **args})
        return result.structured_content

    payload = asyncio.run(_run())
    assert isinstance(payload, dict) and "error" not in payload, payload
    return payload["results"]


def _by_name(rows: list[dict], name: str) -> dict:
    return next(row for row in rows if row["symbol"] == name)


def test_python_methods_have_parent_and_range(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "class Runner:\n    @staticmethod\n    def run(x):\n        return x\n\n\nVALUE = 1\n", encoding="utf-8"
    )
    rows = _search([tmp_path])
    run = _by_name(rows, "run")
    assert (run["kind"], run["parent"], run["line"], run["end_line"]) == ("function", "Runner", 3, 4)
    assert _by_name(rows, "VALUE")["kind"] == "variable"


def test_references_ignore_comments_and_strings(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        'def target():\n    pass\n\n# target is mentioned here\ntext = "target"\ntarget()\n', encoding="utf-8"
    )
    rows = _search([tmp_path], query="target", kinds=["function"], include_references=True, include_callsites=True)
    refs = rows[0]["references"]["items"]
    assert [ref["line"] for ref in refs] == [6]
    assert refs[0]["match_type"] == "callsite"


def test_cross_file_callers_and_callees_across_languages(tmp_path: Path) -> None:
    (tmp_path / "lib.py").write_text(
        "def load():\n    return parse(1)\n\n\ndef parse(x):\n    return x\n", encoding="utf-8"
    )
    (tmp_path / "use.py").write_text("from lib import load\n\n\nclass Svc:\n    def go(self):\n        return load()\n")
    (tmp_path / "api.ts").write_text(
        "export class Client {\n  fetch() { return this.send(); }\n  send() { return 1; }\n}\n"
        "export const run = () => new Client().fetch();\n",
        encoding="utf-8",
    )
    (tmp_path / "srv.go").write_text(
        "package srv\n\ntype Server struct{}\n\nfunc (s *Server) Handle() { s.log() }\n\nfunc (s *Server) log() {}\n\nfunc main() { (&Server{}).Handle() }\n",
        encoding="utf-8",
    )

    rows = _search([tmp_path], kinds=["function"], include_callgraph=True)
    assert "go" in _by_name(rows, "load")["callgraph"]["callers"]
    assert any(c["symbol"] == "parse" for c in _by_name(rows, "load")["callgraph"]["callees"])
    assert _by_name(rows, "send")["parent"] == "Client"
    assert "fetch" in _by_name(rows, "send")["callgraph"]["callers"]
    assert "run" in _by_name(rows, "fetch")["callgraph"]["callers"]
    handle = _by_name(rows, "Handle")
    assert handle["parent"] == "Server" and handle["language"] == "go"
    assert "main" in handle["callgraph"]["callers"]
    assert "Handle" in _by_name(rows, "log")["callgraph"]["callers"]


def test_typescript_and_go_type_kinds(tmp_path: Path) -> None:
    (tmp_path / "t.ts").write_text("interface Shape {}\nenum Mode { A }\ntype Id = string\n", encoding="utf-8")
    (tmp_path / "g.go").write_text("package g\n\ntype Point struct{}\n\nconst Max = 3\n", encoding="utf-8")
    names = {row["symbol"]: row["kind"] for row in _search([tmp_path])}
    assert names == {"Shape": "class", "Mode": "class", "Id": "class", "Point": "class", "Max": "variable"}


def test_vendored_directories_skipped_but_explicit_file_allowed(tmp_path: Path) -> None:
    vendored = tmp_path / "node_modules" / "pkg"
    vendored.mkdir(parents=True)
    (vendored / "x.js").write_text("function hidden() {}\n", encoding="utf-8")
    (tmp_path / "main.js").write_text("function shown() {}\n", encoding="utf-8")
    assert [row["symbol"] for row in _search([tmp_path])] == ["shown"]
    assert [row["symbol"] for row in _search([vendored / "x.js"])] == ["hidden"]


def test_same_name_hint_and_non_ascii_column(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("def build():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text('s = "é☃"; x = build()\n\n\ndef build():\n    pass\n', encoding="utf-8")
    rows = _search([tmp_path], query="build", include_references=True, include_callsites=True)
    assert all(row["same_name_definitions"] == 1 for row in rows)
    refs = next(r for r in rows if r["path"].endswith("b.py"))["references"]["items"]
    ref = next(r for r in refs if r["path"].endswith("b.py") and r["line"] == 1)
    assert ref["match_type"] == "callsite" and ref["column"] == len('s = "é☃"; x = ') + 1


def test_python_default_arguments_are_outside_function_scope(tmp_path: Path) -> None:
    (tmp_path / "defaults.py").write_text(
        "def load():\n    pass\n\ndef body():\n    pass\n\ndef run(value=load()):\n    body()\n",
        encoding="utf-8",
    )
    rows = _search([tmp_path], kinds=["function"], include_callgraph=True)
    run = _by_name(rows, "run")["callgraph"]
    load = _by_name(rows, "load")["callgraph"]
    assert [callee["symbol"] for callee in run["callees"]] == ["body"]
    assert load["callers"] == ["<module>"]


def test_typescript_class_fields_are_definitions_and_scopes(tmp_path: Path) -> None:
    (tmp_path / "client.ts").write_text(
        "class Client {\n  run = () => this.send();\n  send() {}\n}\n",
        encoding="utf-8",
    )
    rows = _search([tmp_path], kinds=["function"], include_callgraph=True)
    run = _by_name(rows, "run")
    send = _by_name(rows, "send")
    assert run["parent"] == "Client"
    assert "run" in send["callgraph"]["callers"]


def test_definition_only_search_indexes_files_lazily(tmp_path: Path, monkeypatch) -> None:
    first = tmp_path / "a.py"
    first.write_text("def target():\n    pass\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def another():\n    pass\n", encoding="utf-8")
    original = symbols.index_file
    indexed: list[Path] = []

    def track_index(path: Path):
        indexed.append(path)
        return original(path)

    monkeypatch.setattr(symbols, "index_file", track_index)
    rows = _search([tmp_path], query="target", kinds=["function"], max_results=1)
    assert [row["symbol"] for row in rows] == ["target"]
    assert indexed == [first]
