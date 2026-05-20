"""Core memory tool registration for copilot-fusion."""

from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastmcp import FastMCP


MemoryType = Literal["code", "chat", "decision", "todo", "fact"]
MemoryScope = Literal["project", "global"]


def _db_path() -> Path:
    base = Path.home() / ".copilot-fusion"
    base.mkdir(parents=True, exist_ok=True)
    return base / "memories.sqlite3"


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
            tags TEXT NOT NULL,
            source TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
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
        del expires_at, scope_path
        now = _iso_now()
        memory_id = str(uuid.uuid4())
        parsed_tags = _parse_tags(tags)
        conn = _conn()
        if not allow_duplicate:
            existing = conn.execute(
                "SELECT id FROM memories WHERE content = ? AND scope = ? LIMIT 1", (content, scope)
            ).fetchone()
            if existing:
                return {"id": existing["id"], "duplicate": True}
        conn.execute(
            """
            INSERT INTO memories (id, content, type, scope, tags, source, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (memory_id, content, type, scope, json.dumps(parsed_tags), source, now, now),
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
        del rerank, scope_path
        conn = _conn()
        rows = conn.execute("SELECT * FROM memories ORDER BY updated_at DESC").fetchall()
        conn.close()
        q = query.lower().strip()
        required_tags = set(_parse_tags(tags))
        scored: list[tuple[float, sqlite3.Row]] = []
        for row in rows:
            if scope and row["scope"] != scope:
                continue
            if type and row["type"] != type:
                continue
            if since and row["created_at"] < since:
                continue
            if until and row["created_at"] > until:
                continue
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
        result = conn.execute("DELETE FROM memories WHERE id = ? OR substr(id, 1, 8) = ?", (memory_id, memory_id))
        conn.commit()
        conn.close()
        if result.rowcount <= 0:
            return "No matching memory found."
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
        del scope_path
        conn = _conn()
        rows = conn.execute("SELECT * FROM memories ORDER BY updated_at DESC").fetchall()
        conn.close()
        required_tags = set(_parse_tags(tags))
        output: list[dict[str, object]] = []
        for row in rows:
            if scope and row["scope"] != scope:
                continue
            if type and row["type"] != type:
                continue
            if since and row["created_at"] < since:
                continue
            if until and row["created_at"] > until:
                continue
            row_tags = set(json.loads(row["tags"]))
            if required_tags and not (required_tags & row_tags):
                continue
            output.append(
                {
                    "id": row["id"],
                    "content": row["content"],
                    "type": row["type"],
                    "scope": row["scope"],
                    "tags": list(row_tags),
                    "source": row["source"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
            )
            if len(output) >= max(1, limit):
                break
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
    ) -> dict[str, object]:
        del scope_path
        text = Path(path).expanduser().read_text(encoding="utf-8")
        result = remember(content=text, type=type_hint, scope=scope, tags=tags, source=source)
        return {"stored": 1, "memory": result}

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
    ) -> dict[str, object]:
        del threshold, scope_path
        listed = list_memories(scope=scope, type=type, tags=tags, limit=1000)
        for row in listed:
            forget(str(row["id"]))
        new_memory = remember(content=summary, type="decision", scope=scope or "global", tags=tags, source=source)
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
        del scope_path
        memories = list_memories(scope=scope, type=type, tags=tags, since=since, until=until, limit=limit)
        if format == "json":
            payload = json.dumps(memories, indent=2)
        elif format == "markdown":
            payload = "\n".join(f"- `{m['id']}` ({m['type']}) {m['content']}" for m in memories)
        else:
            payload = "\n".join(f"* {m['type'].upper()} {m['id']}\n{m['content']}" for m in memories)
        if path:
            Path(path).expanduser().write_text(payload, encoding="utf-8")
            return {"exported": len(memories), "path": str(Path(path).expanduser())}
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
        return "No expiry support in initial migration."

    @mcp.tool
    def reembed_all(batch_size: int = 64) -> dict:
        del batch_size
        return {"status": "No embedding backend configured in initial migration."}

    @mcp.tool(name="fusion_core_health")
    def fusion_core_health() -> dict[str, str]:
        return {"domain": "core", "status": "ready"}
