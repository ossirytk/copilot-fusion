"""Core memory tool registration for copilot-fusion."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP
from copilot_fusion_shared import app_data_dir, resolve_path


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
    return conn


def _iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _parse_tags(tags: list[str] | None) -> list[str]:
    return [tag.strip() for tag in (tags or []) if tag.strip()]


def register(mcp: FastMCP) -> None:
    """Register contextwell-core tools into the provided MCP server."""

    @mcp.tool
    def remember(
        content: str,
        type: MemoryType = "fact",  # noqa: A002
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

    @mcp.tool
    def recall(
        query: str,
        scope: MemoryScope | Literal[""] = "",
        type: MemoryType | str = "",
        tags: list[str] | None = None,
        k: int = 10,
        rerank: bool = False,
        since: str = "",
        until: str = "",
        include_score: bool = False,
        scope_path: str = "",
    ) -> list[dict[str, object]]:
        del rerank
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
        sql += " ORDER BY updated_at DESC"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        q = query.lower().strip()
        required_tags = set(_parse_tags(tags))
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            row_tags = set(json.loads(row["tags"]))
            if required_tags and not (required_tags & row_tags):
                continue
            content = str(row["content"]).lower()
            score = 1.0 if q and q in content else 0.0
            if q and score == 0.0:
                tokens = [tok for tok in q.split() if tok]
                hits = sum(1 for tok in tokens if tok in content)
                score = hits / max(1, len(tokens))
            if q and score == 0.0:
                continue
            scored.append((score, row))
        scored.sort(key=lambda item: item[0], reverse=True)
        result: list[dict[str, object]] = []
        for score, row in scored[: max(1, k)]:
            item = {
                "id": row["id"],
                "content": row["content"],
                "type": row["type"],
                "scope": row["scope"],
                "scope_path": row["scope_path"],
                "tags": json.loads(row["tags"]),
                "source": row["source"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            if include_score:
                item["score"] = score
            result.append(item)
        return result

    @mcp.tool
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

    @mcp.tool
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
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, limit))
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        required_tags = set(_parse_tags(tags))
        output: list[dict[str, object]] = []
        for row in rows:
            row_tags = set(json.loads(row["tags"]))
            if required_tags and not (required_tags & row_tags):
                continue
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

    @mcp.tool
    def update(
        memory_id: str,
        content: str | None = None,
        type: MemoryType | None = None,  # noqa: A002
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

    @mcp.tool
    def remember_file(
        path: str,
        scope: MemoryScope = "global",
        tags: list[str] | None = None,
        type_hint: MemoryType = "fact",
        source: str = "",
        scope_path: str = "",
        split_headers: bool = True,
    ) -> dict[str, object]:
        resolved = resolve_path(path)
        text = resolved.read_text(encoding="utf-8")
        is_markdown = resolved.suffix.lower() in {".md", ".markdown"}
        if split_headers and is_markdown:
            import re as _re
            sections = _re.split(r"(?m)^(#{1,6} .+)$", text)
            chunks: list[str] = []
            i = 0
            while i < len(sections):
                part = sections[i].strip()
                if _re.match(r"^#{1,6} ", part):
                    header = part
                    body = sections[i + 1].strip() if i + 1 < len(sections) else ""
                    i += 2
                    chunk = f"{header}\n\n{body}".strip() if body else header
                else:
                    chunk = part
                    i += 1
                if chunk:
                    chunks.append(chunk)
            if not chunks:
                chunks = [text]
        else:
            chunks = [text]
        stored: list[dict[str, object]] = []
        for chunk in chunks:
            stored.append(remember(content=chunk, type=type_hint, scope=scope, tags=tags, source=source, scope_path=scope_path))
        return {"stored": len(stored), "memories": stored}

    @mcp.tool
    def remember_batch(memories: list[dict], allow_duplicate: bool = False) -> dict[str, object]:
        stored: list[dict[str, object]] = []
        for item in memories:
            stored.append(
                remember(
                    content=str(item.get("content", "")),
                    type=item.get("type", "fact"),
                    scope=item.get("scope", "global"),
                    tags=item.get("tags"),
                    source=str(item.get("source", "")),
                    allow_duplicate=allow_duplicate,
                )
            )
        return {"stored": len(stored), "items": stored}

    @mcp.tool
    def compress_memories(
        summary: str,
        type: MemoryType | str = "",  # noqa: A002
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

    @mcp.tool
    def export_memories(
        format: Literal["json", "markdown", "org"] = "json",  # noqa: A002
        scope: MemoryScope | str = "",
        type: MemoryType | str = "",  # noqa: A002
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

    @mcp.tool
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

    @mcp.tool
    def purge_expired() -> str:
        now = _iso_now()
        conn = _conn()
        result = conn.execute("DELETE FROM memories WHERE expires_at != '' AND expires_at < ?", (now,))
        conn.commit()
        conn.close()
        return f"Purged {result.rowcount} expired memories."

    @mcp.tool
    def reembed_all(batch_size: int = 64) -> dict:
        del batch_size
        return {"status": "No embedding backend configured in initial migration."}

    @mcp.tool(name="fusion_core_health")
    def fusion_core_health() -> dict[str, str]:
        return {"domain": "core", "status": "ready"}
