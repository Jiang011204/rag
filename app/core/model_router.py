"""模型路由层：统一中转站（OpenAI 协议），按功能切换 model 名。

对外只暴露一个 base_url + 一个 api_key；不同功能只是传不同的 model。
流式输出里 reasoning_content（思维链）可能以多种形式存在，这里做稳健探测。
"""
import json
from typing import AsyncIterator, Optional

from openai import AsyncOpenAI

from .config import settings

# 中转站 text-embedding-v4 单次批量上限（超过会报 batch size invalid）
EMBED_BATCH_SIZE = 10


def _delta_field(delta, name: str) -> Optional[str]:
    """从流式 delta 稳健地取字段，兼容 reasoning_content 透传的多种写法。"""
    v = getattr(delta, name, None)
    if v:
        return v
    extra = getattr(delta, "model_extra", None) or {}
    v = extra.get(name)
    if v:
        return v
    dump = getattr(delta, "model_dump", None)
    if dump:
        try:
            return dump().get(name)
        except Exception:
            return None
    return None


class ModelRouter:
    def __init__(self):
        self.client = AsyncOpenAI(
            base_url=settings.gateway_base_url or None,
            api_key=settings.gateway_api_key,
        )
        self._local_model = None

    def _get_local_model(self):
        """懒加载本地 sentence-transformers 模型（首次调用时加载，常驻内存）。"""
        if self._local_model is None:
            from sentence_transformers import SentenceTransformer
            self._local_model = SentenceTransformer(settings.local_embedding_path)
        return self._local_model

    # ---- embedding（cloud=中转站 API；local=本地模型）----
    async def embed(self, texts: list[str], embedding_model: str = "cloud") -> list[list[float]]:
        if embedding_model == "local":
            import asyncio
            model = await asyncio.to_thread(self._get_local_model)
            vecs = await asyncio.to_thread(
                model.encode, texts, normalize_embeddings=True
            )
            return [v.tolist() for v in vecs]
        out: list[list[float]] = []
        for i in range(0, len(texts), EMBED_BATCH_SIZE):
            batch = texts[i : i + EMBED_BATCH_SIZE]
            resp = await self.client.embeddings.create(
                model=settings.model_embedding, input=batch
            )
            out.extend(d.embedding for d in resp.data)
        return out

    # ---- 实体/关系抽取（JSON）----
    async def extract(self, prompt: str) -> dict:
        resp = await self.client.chat.completions.create(
            model=settings.model_extract,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.1,
        )
        content = resp.choices[0].message.content or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {"entities": [], "relationships": []}

    # ---- 生成（流式，含思维链）----
    async def chat_stream(self, messages: list[dict]) -> AsyncIterator[dict]:
        stream = await self.client.chat.completions.create(
            model=settings.model_generate,
            messages=messages,
            stream=True,
            temperature=0.2,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = _delta_field(delta, "reasoning_content")
            content = getattr(delta, "content", None)
            if settings.reasoning_field == "none":
                reasoning = None
            if reasoning or content:
                yield {"reasoning": reasoning, "content": content}

    # ---- 非流式补全 ----
    async def complete(self, messages: list[dict], model: Optional[str] = None) -> str:
        resp = await self.client.chat.completions.create(
            model=model or settings.model_generate,
            messages=messages,
            temperature=0.2,
        )
        return resp.choices[0].message.content or ""


router = ModelRouter()
