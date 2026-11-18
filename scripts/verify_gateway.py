"""Phase 0：验证中转站流式能否透传 reasoning_content（思维链）。

用法：
  export GATEWAY_BASE_URL=... GATEWAY_API_KEY=... [MODEL_GENERATE=deepseek-reasoner]
  python scripts/verify_gateway.py
"""
import asyncio
import os

from openai import AsyncOpenAI


async def main():
    base = os.getenv("GATEWAY_BASE_URL")
    key = os.getenv("GATEWAY_API_KEY")
    model = os.getenv("MODEL_GENERATE", "deepseek-reasoner")
    emb_model = os.getenv("MODEL_EMBEDDING", "text-embedding-3-small")

    if not base or not key:
        print("请先设置 GATEWAY_BASE_URL / GATEWAY_API_KEY")
        return

    client = AsyncOpenAI(base_url=base, api_key=key)
    print(f"base_url = {base}\ngenerate = {model}\nembedding = {emb_model}\n")

    # 1) embedding
    try:
        emb = await client.embeddings.create(model=emb_model, input=["hello"])
        print(f"[OK] embeddings 可用，维度 = {len(emb.data[0].embedding)}")
    except Exception as e:
        print(f"[FAIL] embeddings: {e}")

    # 2) 流式 + reasoning_content
    got_reasoning = False
    got_content = False
    try:
        stream = await client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "用一句话解释什么是 RAG"}],
            stream=True,
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            d = chunk.choices[0].delta
            rc = getattr(d, "reasoning_content", None) or (
                (getattr(d, "model_extra", None) or {}).get("reasoning_content")
            )
            if rc:
                got_reasoning = True
            if getattr(d, "content", None):
                got_content = True
        print(f"[OK] reasoning_content 透传: {got_reasoning}")
        print(f"[OK] content 流式: {got_content}")
    except Exception as e:
        print(f"[FAIL] chat stream: {e}")

    print("\n结论:", "✅ 支持原生思维链" if got_reasoning else "⚠️ 无 reasoning_content，思维链将退化为 agent 轨迹")


if __name__ == "__main__":
    asyncio.run(main())
