"""SSE 流式生成：trace / reasoning / answer / citations / done。

事件格式统一为 data: {"type": ..., ...}，便于 Streamlit / 任意客户端解析。
"""
import json

from ..core.model_router import router

ANSWER_SYSTEM = """你是企业知识库助手。基于给定的上下文回答问题。
要求：
1. 每个事实性论断都要用 [N] 标注引用（N 是上下文条目的编号）。
2. 上下文不足以回答时，明确说明「知识库中没有相关信息」。
3. 用 Markdown 组织回答。
"""


def _sse(type_: str, data: dict) -> str:
    return "data: " + json.dumps({"type": type_, **data}, ensure_ascii=False) + "\n\n"


async def stream_answer(context_text: str, query: str, source_map: dict, trace: list):
    for step in trace:
        yield _sse("trace", {"detail": step})

    messages = [
        {"role": "system", "content": ANSWER_SYSTEM},
        {"role": "user", "content": f"上下文：\n{context_text}\n\n问题：{query}"},
    ]

    async for piece in router.chat_stream(messages):
        if piece.get("reasoning"):
            yield _sse("reasoning", {"delta": piece["reasoning"]})
        if piece.get("content"):
            yield _sse("answer", {"delta": piece["content"]})

    citations = [{"key": k, **v} for k, v in source_map.items()]
    yield _sse("citations", {"items": citations})
    yield _sse("done", {})
