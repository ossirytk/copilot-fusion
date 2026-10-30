"""Core memory tool registration for copilot-fusion."""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from copilot_fusion_shared import app_data_dir, resolve_path
from fastmcp import FastMCP

MemoryType = Literal["code", "chat", "decision", "todo", "fact"]
MemoryScope = Literal["project", "global"]


def _db_path() -> Path:
    return app_data_dir() / "memories.sqlite3"


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS memories (
            id TEXT PRIMARY KEY,
            content TEXT NOT NULL,
            type TEXT NOT NULL,
            scope TEXT NOT NULL,
            scope_path TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL,
            source TEXT NOT NULL,
            expires_at TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    # Migrate older schemas that lack scope_path / expires_at columns.
    _NEW_COLUMNS = {
        "scope_path": "ALTER TABLE memories ADD COLUMN scope_path TEXT NOT NULL DEFAULT ''",
        "expires_at": "ALTER TABLE memories ADD COLUMN expires_at TEXT NOT NULL DEFAULT ''",
    }
    existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()}
    for col, stmt in _NEW_COLUMNS.items():
        if col not in existing_cols:
            conn.execute(stmt)
            conn.commit()
    _ensure_fts(conn)
    return conn


def _ensure_fts(conn: sqlite3.Connection) -> None:
    """Maintain a standalone FTS5 index (keyed by memory id) via triggers; backfill when out of sync."""
    conn.executescript(
        """
        CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
            USING fts5(id UNINDEXED, content, tags, tokenize='unicode61 remove_diacritics 2');
        CREATE TRIGGER IF NOT EXISTS memories_fts_ai AFTER INSERT ON memories BEGIN
            INSERT INTO memories_fts (id, content, tags) VALUES (new.id, new.content, new.tags);
        END;
        CREATE TRIGGER IF NOT EXISTS memories_fts_ad AFTER DELETE ON memories BEGIN
            DELETE FROM memories_fts WHERE id = old.id;
        END;
        CREATE TRIGGER IF NOT EXISTS memories_fts_au AFTER UPDATE OF content, tags ON memories BEGIN
            DELETE FROM memories_fts WHERE id = old.id;
            INSERT INTO memories_fts (id, content, tags) VALUES (new.id, new.content, new.tags);
        END;
        """
    )
    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    indexed = conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
    if total != indexed:
        conn.execute("DELETE FROM memories_fts")
        conn.execute("INSERT INTO memories_fts (id, content, tags) SELECT id, content, tags FROM memories")
        conn.commit()


def _fts_query(query: str) -> str:
    """Build an OR query of quoted tokens; longer tokens also match as prefixes."""
    terms = [f'"{tok}"*' if len(tok) >= 3 else f'"{tok}"' for tok in re.findall(r"\w+", query)]
    return " OR ".join(terms)


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_tags(tags: list[str] | None) -> list[str]:
    return [tag.strip() for tag in (tags or []) if tag.strip()]


def remember(
    content: str,
    type: MemoryType = "fact",
    scope: MemoryScope = "global",
    tags: list[str] | None = None,
    source: str = "",
    allow_duplicate: bool = False,
    expires_at: str = "",
    scope_path: str = "",
) -> dict[str, object]:
    now = _iso_now()
    memory_id = str(uuid.uuid4())
    parsed_tags = _parse_tags(tags)
    conn = _conn()
    if not allow_duplicate:
        existing = conn.execute(
            "SELECT id FROM memories WHERE content = ? AND scope = ? AND scope_path = ? LIMIT 1",
            (content, scope, scope_path),
        ).fetchone()
        if existing:
            return {"id": existing["id"], "duplicate": True}
    conn.execute(
        """
        INSERT INTO memories (id, content, type, scope, scope_path, tags, source, expires_at, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (memory_id, content, type, scope, scope_path, json.dumps(parsed_tags), source, expires_at, now, now),
    )
    conn.commit()
    conn.close()
    return {"id": memory_id, "created_at": now}


def recall(
    query: str,
    scope: MemoryScope | Literal[""] = "",
    type: MemoryType | str = "",
    tags: list[str] | None = None,
    k: int = 10,
    since: str = "",
    until: str = "",
    include_score: bool = False,
    scope_path: str = "",
) -> list[dict[str, object]]:
    conn = _conn()
    where = ["(m.expires_at = '' OR m.expires_at >= ?)"]
    params: list[object] = [_iso_now()]
    for column, value in (("scope", scope), ("scope_path", scope_path), ("type", type)):
        if value:
            where.append(f"m.{column} = ?")
            params.append(value)
    if since:
        where.append("m.created_at >= ?")
        params.append(since)
    if until:
        where.append("m.created_at <= ?")
        params.append(until)
    required_tags = set(_parse_tags(tags))
    q = query.strip()
    match = _fts_query(q)
    if match:
        # bm25() is lower-is-better (negative); exact phrase containment gets a fixed bonus.
        sql = (
            "SELECT m.*, -bm25(memories_fts, 0.0, 1.0, 0.5) + (CASE WHEN instr(lower(m.content), ?) > 0 "
            "THEN 1.0 ELSE 0.0 END) AS score FROM memories_fts JOIN memories m ON m.id = memories_fts.id "
            f"WHERE memories_fts MATCH ? AND {' AND '.join(where)} ORDER BY score DESC, m.updated_at DESC"
        )
        params = [q.lower(), match, *params]
    else:
        sql = f"SELECT m.*, 0.0 AS score FROM memories m WHERE {' AND '.join(where)} ORDER BY m.updated_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    result: list[dict[str, object]] = []
    for row in rows:
        row_tags = json.loads(row["tags"])
        if required_tags and not (required_tags & set(row_tags)):
            continue
        item = {
            "id": row["id"],
            "content": row["content"],
            "type": row["type"],
            "scope": row["scope"],
            "scope_path": row["scope_path"],
            "tags": row_tags,
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
        if include_score:
            item["score"] = row["score"]
        result.append(item)
        if len(result) >= max(1, k):
            break
    return result


def forget(memory_id: str) -> str:
    conn = _conn()
    # Try exact match first.
    exact = conn.execute("SELECT id FROM memories WHERE id = ?", (memory_id,)).fetchone()
    if exact:
        conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        conn.commit()
        conn.close()
        return "Memory deleted."
    # Fall back to prefix match, but only when unambiguous.
    prefix_rows = conn.execute(
        "SELECT id FROM memories WHERE substr(id, 1, ?) = ?", (len(memory_id), memory_id)
    ).fetchall()
    if len(prefix_rows) == 0:
        conn.close()
        return "No matching memory found."
    if len(prefix_rows) > 1:
        conn.close()
        return f"Ambiguous prefix '{memory_id}' matches {len(prefix_rows)} memories. Please provide the full ID."
    target_id = prefix_rows[0]["id"]
    conn.execute("DELETE FROM memories WHERE id = ?", (target_id,))
    conn.commit()
    conn.close()
    return "Memory deleted."


def list_memories(
    scope: MemoryScope | Literal[""] = "",
    type: MemoryType | str = "",
    tags: list[str] | None = None,
    limit: int = 50,
    since: str = "",
    until: str = "",
    scope_path: str = "",
) -> list[dict[str, object]]:
    conn = _conn()
    sql = "SELECT * FROM memories WHERE 1=1"
    params: list[object] = []
    if scope:
        sql += " AND scope = ?"
        params.append(scope)
    if scope_path:
        sql += " AND scope_path = ?"
        params.append(scope_path)
    if type:
        sql += " AND type = ?"
        params.append(type)
    if since:
        sql += " AND created_at >= ?"
        params.append(since)
    if until:
        sql += " AND created_at <= ?"
        params.append(until)
    required_tags = _parse_tags(tags)
    if required_tags:
        placeholders = ",".join("?" * len(required_tags))
        sql += f" AND EXISTS (SELECT 1 FROM json_each(tags) WHERE value IN ({placeholders}))"
        params.extend(required_tags)
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(max(1, limit))
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    output: list[dict[str, object]] = []
    for row in rows:
        row_tags = set(json.loads(row["tags"]))
        output.append(
            {
                "id": row["id"],
                "content": row["content"],
                "type": row["type"],
                "scope": row["scope"],
                "scope_path": row["scope_path"],
                "tags": list(row_tags),
                "source": row["source"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
        )
    return output


def update(
    memory_id: str,
    content: str | None = None,
    type: MemoryType | None = None,
    tags: list[str] | None = None,
    source: str | None = None,
) -> dict[str, object]:
    conn = _conn()
    row = conn.execute(
        "SELECT id, content, type, tags, source FROM memories WHERE id = ? OR substr(id, 1, 8) = ? LIMIT 1",
        (memory_id, memory_id),
    ).fetchone()
    if row is None:
        conn.close()
        return {"error": "Memory not found"}
    next_content = content if content is not None else row["content"]
    next_type = type if type is not None else row["type"]
    next_tags = _parse_tags(tags) if tags is not None else json.loads(row["tags"])
    next_source = source if source is not None else row["source"]
    now = _iso_now()
    conn.execute(
        "UPDATE memories SET content=?, type=?, tags=?, source=?, updated_at=? WHERE id=?",
        (next_content, next_type, json.dumps(next_tags), next_source, now, row["id"]),
    )
    conn.commit()
    conn.close()
    return {"id": row["id"], "updated_at": now}


def compress_memories(
    summary: str,
    type: MemoryType | str = "",
    scope: MemoryScope | str = "",
    threshold: float = 0.85,
    tags: list[str] | None = None,
    source: str = "",
    scope_path: str = "",
    dry_run: bool = False,
) -> dict[str, object]:
    del threshold
    listed = list_memories(scope=scope, type=type, tags=tags, limit=1000, scope_path=scope_path)
    if dry_run:
        return {"dry_run": True, "would_compress": len(listed), "memories": listed}
    for row in listed:
        forget(str(row["id"]))
    new_memory = remember(
        content=summary, type="decision", scope=scope or "global", tags=tags, source=source, scope_path=scope_path
    )
    return {"compressed": len(listed), "summary_memory": new_memory}


def export_memories(
    format: Literal["json", "markdown", "org"] = "json",
    scope: MemoryScope | str = "",
    type: MemoryType | str = "",
    tags: list[str] | None = None,
    since: str = "",
    until: str = "",
    path: str = "",
    limit: int = 1000,
    scope_path: str = "",
) -> dict[str, object]:
    memories = list_memories(
        scope=scope, type=type, tags=tags, since=since, until=until, limit=limit, scope_path=scope_path
    )
    if format == "json":
        payload = json.dumps(memories, indent=2)
    elif format == "markdown":
        payload = "\n".join(f"- `{m['id']}` ({m['type']}) {m['content']}" for m in memories)
    else:
        payload = "\n".join(f"* {m['type'].upper()} {m['id']}\n{m['content']}" for m in memories)
    if path:
        output_path = resolve_path(path)
        output_path.write_text(payload, encoding="utf-8")
        return {"exported": len(memories), "path": str(output_path)}
    return {"exported": len(memories), "content": payload}


def memory_stats(stale_days: int = 0) -> dict:
    del stale_days
    conn = _conn()
    total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    by_type_rows = conn.execute("SELECT type, COUNT(*) as c FROM memories GROUP BY type").fetchall()
    by_scope_rows = conn.execute("SELECT scope, COUNT(*) as c FROM memories GROUP BY scope").fetchall()
    oldest = conn.execute("SELECT MIN(created_at) FROM memories").fetchone()[0] or ""
    newest = conn.execute("SELECT MAX(created_at) FROM memories").fetchone()[0] or ""
    conn.close()
    return {
        "total": total,
        "by_type": {row["type"]: row["c"] for row in by_type_rows},
        "by_scope": {row["scope"]: row["c"] for row in by_scope_rows},
        "oldest": oldest,
        "newest": newest,
    }


def purge_expired() -> str:
    now = _iso_now()
    conn = _conn()
    result = conn.execute("DELETE FROM memories WHERE expires_at != '' AND expires_at < ?", (now,))
    conn.commit()
    conn.close()
    return f"Purged {result.rowcount} expired memories."


def register(mcp: FastMCP) -> None:
    """Register contextwell-core tools into the provided MCP server."""
    mcp.tool(remember)
    mcp.tool(recall)
    mcp.tool(forget)
    mcp.tool(list_memories)
    mcp.tool(update)
    mcp.tool(compress_memories)
    mcp.tool(export_memories)
    mcp.tool(memory_stats)
    mcp.tool(purge_expired)
