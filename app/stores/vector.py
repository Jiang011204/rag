"""LanceDB 向量存储（嵌入式，零外部服务）。按 embedding 模型分表，隔离不同维度。"""
import os
import re
import uuid

import lancedb

from ..core.config import settings


def _table_name(embedding_model: str) -> str:
    """表名：chunks_<model>，非字母数字替换为下划线（如 bge-small-zh-v1.5 -> bge_small_zh_v1_5）。"""
    safe = re.sub(r"[^a-zA-Z0-9]", "_", embedding_model or "cloud")
    return "chunks_" + safe


class VectorStore:
    def __init__(self):
        os.makedirs(settings.data_dir, exist_ok=True)
        self.db = lancedb.connect(os.path.join(settings.data_dir, "lancedb"))

    def add(self, kb_id: str, doc_name: str, chunks: list[str], vectors: list[list[float]],
            embedding_model: str = "cloud"):
        table = _table_name(embedding_model)
        rows = [
            {
                "id": uuid.uuid4().hex,
                "kb_id": kb_id,
                "text": text,
                "vector": vec,
                "doc_name": doc_name,
                "chunk_index": i,
            }
            for i, (text, vec) in enumerate(zip(chunks, vectors))
        ]
        if table in self.db.table_names():
            self.db.open_table(table).add(rows)
        else:
            self.db.create_table(table, data=rows)

    def search(self, kb_id: str, vector: list[float], k: int = 8,
               embedding_model: str = "cloud") -> list[dict]:
        table = _table_name(embedding_model)
        if table not in self.db.table_names():
            return []
        t = self.db.open_table(table)
        try:
            result = t.search(vector).where(f"kb_id = '{kb_id}'").limit(k).to_list()
        except Exception:
            # LanceDB 版本差异兜底：不过滤 kb_id
            result = t.search(vector).limit(k).to_list()
        rows = [dict(r) for r in result]
        # LanceDB 默认字段为 _distance（越小越近）；换算成 0~1 的相似度便于前端展示
        for r in rows:
            d = r.pop("_distance", None)
            if d is None:
                d = r.pop("_score", None)
            if isinstance(d, (int, float)):
                r["score"] = round(1.0 / (1.0 + float(d)), 4)
        return rows

    def list_doc_chunks(self, kb_id: str, doc_name: str,
                        embedding_model: str = "cloud") -> list[dict]:
        """按 chunk_index 返回某篇文档的全部原文片段（供"证据跳原文"）。"""
        table = _table_name(embedding_model)
        if table not in self.db.table_names():
            return []
        t = self.db.open_table(table)
        rows = [
            {
                "chunk_index": r.get("chunk_index"),
                "text": r.get("text", ""),
                "doc_name": r.get("doc_name", ""),
            }
            for r in t.to_arrow().to_pylist()
            if r.get("kb_id") == kb_id and r.get("doc_name") == doc_name
        ]
        rows.sort(key=lambda r: (r["chunk_index"] is None, r["chunk_index"]))
        return rows

    def delete_kb(self, kb_id: str, embedding_model: str = "") -> int:
        """删除某知识库的全部向量，返回删除条数。

        未指定模型时，遍历所有 chunks_* 表清理，避免留下孤儿向量。
        """
        tables = self.db.table_names()
        if embedding_model:
            targets = [_table_name(embedding_model)]
        else:
            targets = [t for t in tables if t.startswith("chunks_")]

        deleted = 0
        for table in targets:
            if table not in tables:
                continue
            try:
                t = self.db.open_table(table)
                before = t.count_rows()
                t.delete(f"kb_id = '{kb_id}'")
                deleted += before - t.count_rows()
            except Exception:
                # 单表失败不阻断其余表，但计数会少记
                continue
        return deleted


vector_store = VectorStore()
