"""Retrieval-quality eval for `recall` on a small, representative memory corpus."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta, timezone

import pytest
from contextwell_core import registry

CORPUS = {
    "pytest": "Run tests with `uv run pytest -q`; coverage gate is enforced in CI.",
    "ruff": "Linting uses ruff with line length 120; run `uv run ruff check .` before committing.",
    "db-path": "Memories are stored in ~/.copilot-fusion/memories.sqlite3 using SQLite.",
    "terminal": "terminal_exec only runs commands from the FUSION_EXEC_ALLOWLIST exact argument arrays.",
    "jj": "Jujutsu colocated repositories are detected via a .jj directory and git_* maps to jj commands.",
    "symbols": "symbol_search parses Python with ast and JS/TS with regex; results are cached by mtime.",
    "decision-fts": "Decision: use SQLite FTS5 with bm25 ranking for memory retrieval instead of substring scoring.",
    "windows": "On Windows the server launches subprocesses without a shell and uses process groups for cleanup.",
    "summarize": "text_summarize can call a remote model via FUSION_TEXT_SUMMARIZER_URL for narrative summaries.",
    "patch": "apply_text_patch refuses to write when the expected text is not found exactly once.",
}

# (query, key of the memory that must appear in the top K)
QUERIES = [
    ("how do I run the tests", "pytest"),
    ("lint formatting ruff", "ruff"),
    ("where is the memory database stored", "db-path"),
    ("allowlist for running commands", "terminal"),
    ("jujutsu support", "jj"),
    ("which languages does symbol search understand", "symbols"),
    ("why did we choose bm25", "decision-fts"),
    ("windows subprocess process groups", "windows"),
    ("remote summarizer url", "summarize"),
    ("patch not found exactly once", "patch"),
    ("FUSION_EXEC_ALLOWLIST", "terminal"),
    ("memories.sqlite3", "db-path"),
]

TOP_K = 3
MIN_HIT_RATE = 0.9


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(registry, "_db_path", lambda: tmp_path / "memories.sqlite3")
    ids = {key: str(registry.remember(content=text, allow_duplicate=True)["id"]) for key, text in CORPUS.items()}
    return ids


def test_recall_hit_rate(corpus) -> None:
    misses = []
    for query, expected in QUERIES:
        got = [m["id"] for m in registry.recall(query, k=TOP_K)]
        if corpus[expected] not in got:
            misses.append((query, expected))
    hit_rate = 1 - len(misses) / len(QUERIES)
    assert hit_rate >= MIN_HIT_RATE, f"hit rate {hit_rate:.2f}; misses: {misses}"


def test_recall_ranks_exact_phrase_first(corpus) -> None:
    top = registry.recall("process groups for cleanup", k=1)
    assert top[0]["id"] == corpus["windows"]


def test_recall_skips_expired(corpus) -> None:
    registry.remember(content="stale-secret-token-note", expires_at="2000-01-01T00:00:00+00:00")
    assert registry.recall("stale-secret-token-note") == []


def test_recall_compares_expiry_instants_with_offsets(corpus) -> None:
    expired = (datetime.now(UTC) - timedelta(minutes=1)).astimezone(timezone(timedelta(hours=2))).isoformat()
    registry.remember(content="offset-expiry-entry", expires_at=expired)
    assert registry.recall("offset-expiry-entry") == []


def test_recall_tokenless_query_uses_literal_content(corpus) -> None:
    punctuation = registry.remember(content="Keep this marker !!!")
    emoji = registry.remember(content="Keep this marker ☃")
    assert [row["id"] for row in registry.recall("!!!")] == [punctuation["id"]]
    assert [row["id"] for row in registry.recall("☃")] == [emoji["id"]]


def test_index_tracks_update_and_forget(corpus) -> None:
    mid = corpus["ruff"]
    registry.update(mid, content="Formatting now handled by black")
    assert all(m["id"] != mid for m in registry.recall("ruff", k=5))
    assert registry.recall("black", k=1)[0]["id"] == mid
    registry.forget(mid)
    assert all(m["id"] != mid for m in registry.recall("black", k=5))


def test_index_backfills_preexisting_rows(tmp_path, monkeypatch) -> None:
    db = tmp_path / "old.sqlite3"
    monkeypatch.setattr(registry, "_db_path", lambda: db)
    registry.remember(content="legacy entry about backfill")
    with sqlite3.connect(db) as raw:
        raw.execute("DROP TABLE memories_fts")
    assert registry.recall("backfill")[0]["content"] == "legacy entry about backfill"
