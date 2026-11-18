"""REST + OpenAI 兼容 API。

2026-09-30 新增（供自建前端消费的结构化接口）：
  POST /v1/kb/ask/events          NDJSON 结构化事件流（trace / sources / reasoning / answer / done）
  GET  /v1/graph                  Neo4j 实体邻域（图可视化）
  GET  /v1/kb/{kb_id}/chunks/{doc_id}   原文片段预览（证据跳转）

原有接口保持向后兼容，Streamlit 前端与 OpenAI 兼容端点行为不变。
"""
import asyncio
import json
import time
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from ..core.config import settings
from ..core.model_router import router as model_router
from ..diagnose.patterns import diagnose
from ..generate.stream import ANSWER_SYSTEM, stream_answer
from ..graph.extract import extract_entities
from ..graph.store import graph_store
from ..ingest.chunker import chunk_text
from ..ingest.loader import load_file, load_url
from ..retrieve.retriever import retrieve
from ..stores.meta import meta_store
from ..stores.vector import vector_store
from .deps import require_auth

router = APIRouter()


class CreateKB(BaseModel):
    name: str
    embedding_model: str = "cloud"  # cloud | local


class DocumentIn(BaseModel):
    url: str | None = None
    text: str | None = None
    name: str | None = None


class AskIn(BaseModel):
    kb_id: str
    query: str


class RetrieveIn(BaseModel):
    kb_id: str
    query: str
    top_k: int = 8


class DiagnoseIn(BaseModel):
    bug: str


# ---------------------------------------------------------------- health
@router.get("/v1/health")
async def health():
    return {"status": "ok"}


# ---------------------------------------------------------------- 知识库
@router.post("/v1/kb", dependencies=[Depends(require_auth)])
async def create_kb(body: CreateKB):
    kb_id = meta_store.create_kb(body.name, body.embedding_model)
    return {"kb_id": kb_id, "name": body.name, "embedding_model": body.embedding_model}


@router.get("/v1/kb", dependencies=[Depends(require_auth)])
async def list_kbs():
    """知识库列表：附带文档数与块数，前端一次渲染完，避免 N+1 请求。"""
    items = meta_store.list_kbs()
    for kb in items:
        docs = meta_store.list_docs(kb["id"])
        kb["doc_count"] = len(docs)
        kb["chunk_count"] = sum(int(d.get("n_chunks") or 0) for d in docs)
    return {"items": items}


@router.get("/v1/kb/{kb_id}/documents", dependencies=[Depends(require_auth)])
async def list_documents(kb_id: str):
    return {"items": meta_store.list_docs(kb_id)}


@router.get("/v1/kb/{kb_id}/chunks/{doc_id}", dependencies=[Depends(require_auth)])
async def get_document_chunks(
    kb_id: str,
    doc_id: str,
    limit: int = Query(40, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """取出某篇文档的原文片段，供前端做"证据跳原文"。

    块是按入库顺序排列的（chunk_index），因此可以直接当作页码/段落索引使用。
    """
    doc = next((d for d in meta_store.list_docs(kb_id) if d["id"] == doc_id), None)
    if not doc:
        raise HTTPException(404, "document not found")
    kb = meta_store.get_kb(kb_id)
    emb_model = (kb.get("embedding_model") or "cloud") if kb else "cloud"
    try:
        chunks = vector_store.list_doc_chunks(kb_id, doc["name"], emb_model)
    except Exception as e:  # 向量库异常不影响前端展示文档元数据
        return {"document": doc, "total": 0, "items": [], "error": str(e)}
    total = len(chunks)
    return {
        "document": doc,
        "total": total,
        "offset": offset,
        "items": chunks[offset : offset + limit],
    }


@router.delete("/v1/kb/{kb_id}", dependencies=[Depends(require_auth)])
async def delete_kb(kb_id: str):
    """删除知识库：元数据 + 向量一并清除。

    两者在同一请求内完成 —— 只删元数据会留下查不到的孤儿向量，只删向量则会留下幽灵知识库。
    """
    kb = meta_store.get_kb(kb_id)
    if not kb:
        raise HTTPException(404, "kb not found")
    removed = vector_store.delete_kb(kb_id, kb.get("embedding_model") or "cloud")
    meta_store.delete_kb(kb_id)
    return {"kb_id": kb_id, "name": kb.get("name"), "deleted_vectors": removed}


# ---------------------------------------------------------------- 文档摄取
@router.post("/v1/kb/{kb_id}/documents", dependencies=[Depends(require_auth)])
async def add_document(kb_id: str, body: DocumentIn):
    if body.url:
        text = load_url(body.url)
        name = body.name or body.url.rstrip("/").split("/")[-1] or "document"
        source = body.url
    elif body.text:
        text = body.text
        name = body.name or "pasted"
        source = "text"
    else:
        raise HTTPException(400, "provide url or text")
    return await _ingest(kb_id, name, source, text)


@router.post("/v1/kb/{kb_id}/upload", dependencies=[Depends(require_auth)])
async def upload_document(kb_id: str, file: UploadFile = File(...)):
    data = await file.read()
    try:
        text = load_file(file.filename, data)
    except ValueError as e:
        # 格式不支持 / 内容无法解析 —— 属调用方传错了文件，报 400 而非 500
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(400, f"文件解析失败：{e}")
    return await _ingest(kb_id, file.filename or "upload", "file", text)


async def _ingest(kb_id: str, name: str, source: str, text: str) -> dict:
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(400, "no content extracted")

    kb = meta_store.get_kb(kb_id)
    emb_model = (kb.get("embedding_model") or "cloud") if kb else "cloud"

    vectors = await model_router.embed(chunks, emb_model)
    vector_store.add(kb_id, name, chunks, vectors, emb_model)
    meta_store.add_doc(kb_id, name, source, len(chunks))

    # 图谱抽取（全量 chunk 并发处理，批量写入）
    entities: list[dict] = []
    relationships: list[dict] = []
    results = await asyncio.gather(
        *[extract_entities(ch) for ch in chunks],
        return_exceptions=True,
    )
    for r in results:
        if isinstance(r, Exception):
            continue
        es, rs = r
        entities.extend(es)
        relationships.extend(rs)
    if entities or relationships:
        try:
            await asyncio.to_thread(graph_store.add_all, entities, relationships, name)
        except Exception as e:
            return {"chunks": len(chunks), "entities": 0, "relationships": 0, "graph_error": str(e)}

    return {"chunks": len(chunks), "entities": len(entities), "relationships": len(relationships)}


# ---------------------------------------------------------------- 检索 / 问答
@router.post("/v1/kb/retrieve", dependencies=[Depends(require_auth)])
async def retrieve_only(body: RetrieveIn):
    context_text, source_map, trace = await retrieve(body.kb_id, body.query, body.top_k)
    return {
        "context": context_text,
        "sources": _sources_list(source_map),
        "trace": trace,
    }


@router.post("/v1/kb/ask", dependencies=[Depends(require_auth)])
async def ask(body: AskIn):
    context_text, source_map, trace = await retrieve(body.kb_id, body.query)
    gen = stream_answer(context_text, body.query, source_map, trace)
    return StreamingResponse(
        gen,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/v1/kb/ask/events", dependencies=[Depends(require_auth)])
async def ask_events(body: AskIn, request: Request):
    """结构化问答事件流（NDJSON，application/x-ndjson）。

    前端无需再解析文本尾部拼出来的"来源"块，可直接把
      trace  → 检索剧场时间线
      sources→ 证据台（含相似度、文档 id，可点开原文）
      reasoning / answer → 思维链与答案分区渲染
    """
    started = time.time()
    context_text, source_map, trace = await retrieve(body.kb_id, body.query)

    async def gen():
        yield _ev({"type": "start", "query": body.query, "kb_id": body.kb_id})
        for i, step in enumerate(trace):
            yield _ev({"type": "trace", "index": i, "text": step})
        yield _ev({"type": "sources", "items": _sources_list(source_map)})

        messages = [
            {"role": "system", "content": ANSWER_SYSTEM},
            {"role": "user", "content": f"上下文：\n{context_text}\n\n问题：{body.query}"},
        ]
        if await request.is_disconnected():
            return
        async for piece in model_router.chat_stream(messages):
            if piece.get("reasoning"):
                yield _ev({"type": "reasoning", "text": piece["reasoning"]})
            if piece.get("content"):
                yield _ev({"type": "answer", "text": piece["content"]})
        yield _ev(
            {
                "type": "done",
                "elapsed_ms": int((time.time() - started) * 1000),
                "n_sources": len(source_map),
            }
        )

    return StreamingResponse(
        gen(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------- 图谱（可视化）
@router.get("/v1/graph", dependencies=[Depends(require_auth)])
async def graph_view(
    q: str | None = Query(None, description="按实体名/描述过滤，留空取全图"),
    limit: int = Query(120, ge=1, le=500),
):
    """返回实体邻域，供前端力导向图渲染。

    node: {id, name, type, description, source_doc, degree}
    link: {source, target, type}
    """
    try:
        nodes, links = await asyncio.to_thread(graph_store.view, q, limit)
    except Exception as e:
        raise HTTPException(503, f"图谱不可用：{e}")
    return {"nodes": nodes, "links": links, "limit": limit, "filter": q}


# ---------------------------------------------------------------- 诊断
@router.post("/v1/diagnose", dependencies=[Depends(require_auth)])
async def diagnose_endpoint(body: DiagnoseIn):
    markdown = await diagnose(body.bug)
    return {"markdown": markdown}


# ---------------------------------------------------------------- OpenAI 兼容
@router.post("/v1/chat/completions", dependencies=[Depends(require_auth)])
async def chat_completions(request: Request):
    body = await request.json()
    kb_id = body.get("kb_id") or body.get("kb_ids")
    if isinstance(kb_id, list):
        kb_id = kb_id[0] if kb_id else None

    messages = body.get("messages", [])
    query = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            query = m.get("content", "")
            break
    if not kb_id or not query:
        raise HTTPException(400, "kb_id and a user message are required")

    context_text, source_map, trace = await retrieve(kb_id, query)
    sources_text = _format_sources(source_map)

    if body.get("stream"):
        return StreamingResponse(
            _openai_sse(context_text, query, sources_text, body.get("model", "kb-rag")),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    answer = await _generate_full(context_text, query)
    return _openai_completion(answer + sources_text, body.get("model", "kb-rag"))


# ---------------------------------------------------------------- 内部工具
def _ev(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _sources_list(source_map: dict) -> list[dict]:
    """把检索出来的 source_map 转成前端好用的数组（带相似度与文档 id）。"""
    out: list[dict] = []
    for key, s in source_map.items():
        doc_name = s.get("document", "") or ""
        doc_id = ""
        try:
            kb_id = s.get("kb_id")
            if kb_id:
                doc_id = next(
                    (d["id"] for d in meta_store.list_docs(kb_id) if d["name"] == doc_name),
                    "",
                )
        except Exception:
            doc_id = ""
        out.append(
            {
                "key": key,
                "document": doc_name,
                "doc_id": doc_id,
                "text": s.get("text", ""),
                "kind": s.get("kind", "vector"),
                "entity": s.get("entity"),
                "source": s.get("source"),
                "score": s.get("score"),
                "chunk_index": s.get("chunk_index"),
            }
        )
    return out


def _context_for_model(context_text: str, query: str) -> list[dict]:
    return [
        {"role": "system", "content": ANSWER_SYSTEM},
        {"role": "user", "content": f"上下文：\n{context_text}\n\n问题：{query}"},
    ]


def _format_sources(source_map: dict) -> str:
    if not source_map:
        return ""
    lines = ["\n\n---\n**来源**"]
    for key, s in source_map.items():
        doc = s.get("document", "") or "unknown"
        lines.append(f"- {key} {doc}: {s.get('text', '')[:120]}")
    return "\n".join(lines)


async def _generate_full(context_text: str, query: str) -> str:
    return await model_router.complete(_context_for_model(context_text, query))


def _cid() -> str:
    return "chatcmpl-" + uuid.uuid4().hex


def _chunk_obj(cid: str, model: str, delta: dict, finish_reason):
    return {
        "id": cid,
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


async def _openai_sse(context_text: str, query: str, sources_text: str, model: str):
    cid = _cid()
    yield "data: " + json.dumps(
        _chunk_obj(cid, model, {"role": "assistant", "content": ""}, None),
        ensure_ascii=False,
    ) + "\n\n"

    async for piece in model_router.chat_stream(_context_for_model(context_text, query)):
        delta = {}
        if piece.get("reasoning"):
            delta["reasoning_content"] = piece["reasoning"]
        if piece.get("content"):
            delta["content"] = piece["content"]
        if delta:
            yield "data: " + json.dumps(
                _chunk_obj(cid, model, delta, None), ensure_ascii=False
            ) + "\n\n"

    if sources_text:
        yield "data: " + json.dumps(
            _chunk_obj(cid, model, {"content": sources_text}, None), ensure_ascii=False
        ) + "\n\n"

    yield "data: " + json.dumps(
        _chunk_obj(cid, model, {}, "stop"), ensure_ascii=False
    ) + "\n\n"
    yield "data: [DONE]\n\n"


def _openai_completion(content: str, model: str) -> dict:
    return {
        "id": _cid(),
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }
