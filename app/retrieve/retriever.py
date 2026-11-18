"""检索：向量 + 图谱多跳，产出带 [N] 引用的上下文。"""
from ..core.model_router import router
from ..graph.store import graph_store
from ..stores.meta import meta_store
from ..stores.vector import vector_store


async def retrieve(kb_id: str, query: str, top_k: int = 8):
    trace: list[str] = []
    source_map: dict[str, dict] = {}
    context_parts: list[str] = []

    kb = meta_store.get_kb(kb_id)
    emb_model = (kb.get("embedding_model") or "cloud") if kb else "cloud"

    # 1) 向量检索
    trace.append(f"🔍 向量检索：{query}")
    qvec = (await router.embed([query], emb_model))[0]
    hits = vector_store.search(kb_id, qvec, top_k, emb_model)
    trace.append(f"📊 命中 {len(hits)} 个 chunk")

    for h in hits:
        key = f"[{len(context_parts) + 1}]"
        text = h.get("text", "")
        context_parts.append(f"{key} {text}")
        source_map[key] = {
            "document": h.get("doc_name", ""),
            "text": text,
            "kind": "vector",
            "kb_id": kb_id,
            "score": h.get("score"),
            "chunk_index": h.get("chunk_index"),
        }

    # 2) 图谱多跳
    try:
        names = graph_store.find_start_entities(query, limit=3)
        if names:
            trace.append(f"🔗 图谱实体：{', '.join(names)}")
            seen = set()
            for r in graph_store.expand(names, hops=2)[:8]:  # 控制上下文体积
                if r["name"] in seen:
                    continue
                seen.add(r["name"])
                key = f"[{len(context_parts) + 1}]"
                desc = (r.get("description") or "")[:100]
                context_parts.append(f"{key} {r['name']}: {desc}")
                source_map[key] = {
                    "document": r.get("source", ""),
                    "text": r.get("description", ""),
                    "kind": "graph",
                    "entity": r["name"],
                    "kb_id": kb_id,
                }
            trace.append(f"📈 图谱扩展 {len(seen)} 个实体")
    except Exception as e:  # 图谱不可用时不阻塞主链路
        trace.append(f"⚠️ 图谱不可用：{e}")

    context_text = "\n".join(context_parts)
    trace.append(f"📝 组装上下文 {len(context_parts)} 条")
    return context_text, source_map, trace
