import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("friday.core.memory")
DEFAULT_MEMORY_DB = Path("D:/AI-Agents/Shared/memory/agency_memory.db")


@dataclass
class MemoryItem:
    id: int
    category: str
    key: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    access_count: int = 0


class AgencyMemory:
    """Persistent Long-Term Memory for FRIDAY & JARVIS using SQLite & FTS5 full-text search."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = Path(db_path or DEFAULT_MEMORY_DB).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    access_count INTEGER DEFAULT 0
                )
            """)
            cursor.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    key,
                    content,
                    content='memories',
                    content_rowid='id'
                )
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, key, content) VALUES (new.id, new.key, new.content);
                END;
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, key, content) VALUES('delete', old.id, old.key, old.content);
                END;
            """)
            cursor.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, key, content) VALUES('delete', old.id, old.key, old.content);
                    INSERT INTO memories_fts(rowid, key, content) VALUES (new.id, new.key, new.content);
                END;
            """)
            conn.commit()

    def seed_defaults(self) -> None:
        """Seed essential project preferences and rules if not already present."""
        defaults = [
            (
                "user_preference",
                "groq_model_preference",
                "User preferred Groq model is groq/openai/gpt-oss-120b. Do not change it unless explicitly requested.",
                {"source": "user_instruction"},
            ),
            (
                "error_fix",
                "powershell_statement_separator",
                "In Windows PowerShell, always use ';' instead of '&&' to separate multiple commands.",
                {"shell": "powershell", "os": "windows"},
            ),
            (
                "architecture_rule",
                "uvicorn_websockets_requirement",
                "FastAPI/Uvicorn requires the 'websockets' python library installed to support ASGI WebSocket connections.",
                {"package": "websockets"},
            ),
            (
                "architecture_rule",
                "multiagent_mailboxes",
                "FRIDAY (Lead) and JARVIS (Worker) communicate via D:/AI-Agents/Shared/mailboxes (friday_inbox and jarvis_inbox).",
                {"ipc": "file_bus"},
            ),
        ]
        with self._get_connection() as conn:
            cursor = conn.cursor()
            for cat, k, cont, meta in defaults:
                cursor.execute(
                    "SELECT id FROM memories WHERE category = ? AND key = ?",
                    (cat, k),
                )
                if not cursor.fetchone():
                    cursor.execute(
                        "INSERT INTO memories (category, key, content, metadata) VALUES (?, ?, ?, ?)",
                        (cat, k, cont, json.dumps(meta, ensure_ascii=False)),
                    )
            conn.commit()

    def remember(
        self,
        category: str,
        key: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Stores or updates a memory item."""
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Check if existing key in same category
            cursor.execute(
                "SELECT id FROM memories WHERE category = ? AND key = ?",
                (category, key),
            )
            row = cursor.fetchone()
            if row:
                m_id = row["id"]
                cursor.execute(
                    "UPDATE memories SET content = ?, metadata = ? WHERE id = ?",
                    (content, meta_json, m_id),
                )
            else:
                cursor.execute(
                    "INSERT INTO memories (category, key, content, metadata) VALUES (?, ?, ?, ?)",
                    (category, key, content, meta_json),
                )
                m_id = cursor.lastrowid
            conn.commit()
            return m_id

    def recall(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 5,
    ) -> List[MemoryItem]:
        """Search relevant memories using full-text search with fallback to substring."""
        if not query or not query.strip():
            return []

        clean_words = [w.strip() for w in query.replace("'", " ").replace('"', ' ').split() if len(w.strip()) > 1]
        results: List[MemoryItem] = []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            rows = []

            # 1. Try FTS5 MATCH
            if clean_words:
                fts_query = " OR ".join(f'"{w}"' for w in clean_words)
                try:
                    if category:
                        sql = """
                            SELECT m.* FROM memories m
                            JOIN memories_fts f ON m.id = f.rowid
                            WHERE m.category = ? AND memories_fts MATCH ?
                            ORDER BY rank LIMIT ?
                        """
                        cursor.execute(sql, (category, fts_query, limit))
                    else:
                        sql = """
                            SELECT m.* FROM memories m
                            JOIN memories_fts f ON m.id = f.rowid
                            WHERE memories_fts MATCH ?
                            ORDER BY rank LIMIT ?
                        """
                        cursor.execute(sql, (fts_query, limit))
                    rows = cursor.fetchall()
                except Exception as e:
                    logger.debug(f"FTS5 match failed, falling back to LIKE: {e}")

            # 2. Fallback to LIKE if FTS yielded 0 rows
            if not rows:
                like_pattern = f"%{query.strip()}%"
                if category:
                    cursor.execute(
                        "SELECT * FROM memories WHERE category = ? AND (key LIKE ? OR content LIKE ?) LIMIT ?",
                        (category, like_pattern, like_pattern, limit),
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM memories WHERE key LIKE ? OR content LIKE ? LIMIT ?",
                        (like_pattern, like_pattern, limit),
                    )
                rows = cursor.fetchall()

            for r in rows:
                meta = {}
                try:
                    meta = json.loads(r["metadata"]) if r["metadata"] else {}
                except Exception:
                    pass

                item = MemoryItem(
                    id=r["id"],
                    category=r["category"],
                    key=r["key"],
                    content=r["content"],
                    metadata=meta,
                    created_at=str(r["created_at"]),
                    access_count=r["access_count"] + 1,
                )
                results.append(item)
                # Increment access count
                cursor.execute(
                    "UPDATE memories SET access_count = access_count + 1 WHERE id = ?",
                    (r["id"],),
                )
            conn.commit()

        return results

    def list_all(self, category: Optional[str] = None) -> List[MemoryItem]:
        """Lists stored memories, optionally filtered by category."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if category:
                cursor.execute(
                    "SELECT * FROM memories WHERE category = ? ORDER BY id DESC",
                    (category,),
                )
            else:
                cursor.execute("SELECT * FROM memories ORDER BY id DESC")
            rows = cursor.fetchall()

            items = []
            for r in rows:
                meta = {}
                try:
                    meta = json.loads(r["metadata"]) if r["metadata"] else {}
                except Exception:
                    pass
                items.append(
                    MemoryItem(
                        id=r["id"],
                        category=r["category"],
                        key=r["key"],
                        content=r["content"],
                        metadata=meta,
                        created_at=str(r["created_at"]),
                        access_count=r["access_count"],
                    )
                )
            return items

    def get(self, memory_id: int) -> Optional[MemoryItem]:
        """Fetch a specific memory item by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE id = ?", (memory_id,))
            r = cursor.fetchone()
            if not r:
                return None
            meta = {}
            try:
                meta = json.loads(r["metadata"]) if r["metadata"] else {}
            except Exception:
                pass
            return MemoryItem(
                id=r["id"],
                category=r["category"],
                key=r["key"],
                content=r["content"],
                metadata=meta,
                created_at=str(r["created_at"]),
                access_count=r["access_count"],
            )

    def forget(self, memory_id: int) -> bool:
        """Deletes a memory item by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
            return cursor.rowcount > 0
