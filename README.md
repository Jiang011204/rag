# 企业知识库（Enterprise Knowledge Base）

一个自建的 RAG（检索增强生成）知识库，融合四个开源 tutorial 的能力：

| 来源 | 能力 |
|---|---|
| `rag-as-a-service` | 文档接入 + 向量检索 + 问答 |
| `knowledge_graph_rag_citations` | 知识图谱多跳 + `[N]` 引用溯源 |
| `rag_failure_diagnostics_clinic` | P01–P12 失败诊断闭环 |
| `agentic_rag_with_reasoning` | 实时思维链 + 左右分栏 UI |

## 特性

- **双路索引**：LanceDB 向量 + Neo4j 图谱
- **实时思维链**：SSE 流式，左栏推理 / 右栏带引用答案
- **模型路由**：统一中转站（OpenAI 协议），按功能切 model
- **双入口**：Streamlit Web + OpenAI 兼容 API（`/v1/chat/completions`）

## 架构

```
浏览器 :8501 ──▶ web (Streamlit) ──▶ api (FastAPI :8000)
                                      ├─▶ LanceDB + SQLite (kb_data 卷)
                                      ├─▶ Neo4j 图谱 (:7687)
                                      └─▶ LLM Gateway (OpenAI 协议中转)
```

## 目录结构

```
enterprise-kb/
├── app/
│   ├── main.py              # FastAPI 入口
│   ├── core/config.py       # 全部配置项定义
│   ├── core/model_router.py # 模型路由
│   ├── api/routes.py        # 12 个接口
│   ├── ingest/              # loader + chunker（文档解析与切分）
│   ├── retrieve/retriever.py# 双路检索
│   ├── stores/vector.py     # LanceDB
│   ├── stores/meta.py       # SQLite 元数据
│   ├── graph/               # Neo4j 图谱抽取与存储
│   ├── generate/stream.py   # SSE 思维链流式
│   └── diagnose/patterns.py # P01–P12 诊断
├── web/app.py               # Streamlit 前端
├── scripts/verify_gateway.py
├── Dockerfile / Dockerfile.cpu
├── docker-compose.yml
├── requirements.txt
├── .env.example             # 配置样例（复制为 .env 后填真实值）
├── DEPLOYMENT.md            # 部署手册
└── README.md
```

## 快速开始

```bash
cp .env.example .env   # 填入中转站配置 + Neo4j 密码 + APP_API_KEY
docker compose up -d --build
```

- Web：http://localhost:8501
- API 文档：http://localhost:8000/docs
- Neo4j Browser：http://localhost:7474

> 仓库**不含** `.env`，仅提供 `.env.example`。请勿提交含真实密钥的配置。
> 详细部署、配置、补数据与踩坑提示见 [DEPLOYMENT.md](DEPLOYMENT.md)。

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
