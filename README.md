# 企业知识库（Enterprise Knowledge Base）

融合 awesome-llm-apps 四个 tutorial 的自建企业知识库：

| 来源 | 能力 |
|---|---|
| `rag-as-a-service` | 文档接入 + 向量检索 + 问答 |
| `knowledge_graph_rag_citations` | 知识图谱多跳 + `[N]` 引用溯源 |
| `rag_failure_diagnostics_clinic` | P01–P12 失败诊断闭环 |
| `agentic_rag_with_reasoning` | 实时思维链 + 左右分栏 UI |

特性：
- **双路索引**：LanceDB 向量 + Neo4j 图谱
- **实时思维链**：SSE 流式，左栏推理 / 右栏带引用答案
- **模型路由**：统一中转站（OpenAI 协议），按功能切 model
- **双入口**：Streamlit Web + OpenAI 兼容 API（`/v1/chat/completions`）

## 快速开始

```bash
cp .env.example .env   # 填入中转站配置 + Neo4j 密码 + APP_API_KEY
docker compose up -d --build
```

- Web：http://localhost:8501
- API 文档：http://localhost:8000/docs
- Neo4j Browser：http://localhost:7474

## Phase 0 验证中转站思维链

```bash
export GATEWAY_BASE_URL=... GATEWAY_API_KEY=... MODEL_GENERATE=deepseek-reasoner
python scripts/verify_gateway.py
```

## API 示例

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="kb-xxx")
resp = client.chat.completions.create(
    model="kb-rag",
    messages=[{"role": "user", "content": "我们的退货政策是什么？"}],
    extra_body={"kb_id": "<kb_id>"},
    stream=True,
)
for c in resp:
    d = c.choices[0].delta
    if getattr(d, "reasoning_content", None): ...   # 思维链
    if d.content: ...                                # 答案
```
