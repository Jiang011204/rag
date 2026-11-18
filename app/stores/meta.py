"""SQLite 元数据：知识库、文档、审计日志。"""
import os
import sqlite3
import time
import uuid

from ..core.config import settings


class MetaStore:
    def __init__(self):
        os.makedirs(settings.data_dir, exist_ok=True)
        self.path = os.path.join(settings.data_dir, "meta.db")
        self._init()

    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self):
        with self._conn() as c:
            c.execute(
                "CREATE TABLE IF NOT EXISTS kb (id TEXT PRIMARY KEY, name TEXT, "
                "embedding_model TEXT DEFAULT 'cloud', created_at REAL)"
            )
            # 迁移：旧库 kb 表若无 embedding_model 列，则补上（旧数据视为 cloud）
            cols = [r[1] for r in c.execute("PRAGMA table_info(kb)")]
            if "embedding_model" not in cols:
                c.execute("ALTER TABLE kb ADD COLUMN embedding_model TEXT DEFAULT 'cloud'")
            c.execute(
                "CREATE TABLE IF NOT EXISTS docs (id TEXT PRIMARY KEY, kb_id TEXT, "
                "name TEXT, source TEXT, n_chunks INTEGER, created_at REAL)"
            )
            c.execute(
                "CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, kb_id TEXT, "
                "query TEXT, answer TEXT, created_at REAL)"
            )

    def create_kb(self, name: str, embedding_model: str = "cloud") -> str:
        kb_id = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute(
                "INSERT INTO kb (id,name,embedding_model,created_at) VALUES (?,?,?,?)",
                (kb_id, name, embedding_model, time.time()),
            )
        return kb_id

    def get_kb(self, kb_id: str) -> dict | None:
        with self._conn() as c:
            row = c.execute("SELECT * FROM kb WHERE id=?", (kb_id,)).fetchone()
            return dict(row) if row else None

    def list_kbs(self) -> list[dict]:
        with self._conn() as c:
            return [
                dict(r) for r in c.execute("SELECT * FROM kb ORDER BY created_at DESC")
            ]

    def add_doc(self, kb_id: str, name: str, source: str, n_chunks: int) -> str:
        doc_id = uuid.uuid4().hex[:12]
        with self._conn() as c:
            c.execute(
                "INSERT INTO docs (id,kb_id,name,source,n_chunks,created_at) "
                "VALUES (?,?,?,?,?,?)",
                (doc_id, kb_id, name, source, n_chunks, time.time()),
            )
        return doc_id

    def list_docs(self, kb_id: str) -> list[dict]:
        with self._conn() as c:
            return [
                dict(r)
                for r in c.execute(
                    "SELECT * FROM docs WHERE kb_id=? ORDER BY created_at DESC", (kb_id,)
                )
            ]

    def log_audit(self, kb_id: str, query: str, answer: str) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO audit (id,kb_id,query,answer,created_at) VALUES (?,?,?,?,?)",
                (uuid.uuid4().hex, kb_id, query, answer, time.time()),
            )

    def delete_kb(self, kb_id: str) -> bool:
        """删除知识库，连带清除其文档与审计记录。返回是否确有删除。

        向量数据不在此处处理（由 VectorStore 负责），但两者须在同一请求内完成，
        否则会留下查不到的孤儿向量。
        """
        with self._conn() as c:
            cur = c.execute("DELETE FROM kb WHERE id=?", (kb_id,))
            c.execute("DELETE FROM docs WHERE kb_id=?", (kb_id,))
            c.execute("DELETE FROM audit WHERE kb_id=?", (kb_id,))
            return cur.rowcount > 0


meta_store = MetaStore()
