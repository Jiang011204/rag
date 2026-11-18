# 企业知识库 · 部署手册

> 本手册描述一套自建 RAG 知识库的架构、配置与部署方式。
> 内网地址、账号、密钥等敏感信息已脱敏，实际值请从 `.env` 读取。

---

## 一、这套东西是什么

一个自建 RAG 知识库，融合四套能力：

| 能力 | 实现 |
|---|---|
| 文档接入 + 向量检索 + 问答 | LanceDB + FastAPI |
| 知识图谱多跳 + `[N]` 引用溯源 | Neo4j |
| 失败诊断闭环（P01–P12） | `app/diagnose/` |
| 实时思维链（SSE 流式） | Streamlit 左右分栏 |

**架构三容器**（默认运行状态）：

```
                    ┌──────────────────────┐
   浏览器 :8501 ──▶ │ web (Streamlit)      │
                    └──────────┬───────────┘
                               │ http://api:8000
                    ┌──────────▼───────────┐
   客户端 :8000 ──▶ │ api (FastAPI/uvicorn)│
                    └────┬────────────┬────┘
                         │            │
              ┌──────────▼──┐   ┌─────▼──────────────┐
              │ kb_data 卷   │   │ neo4j:5            │
              │ (/data)      │   │ :7474 / :7687      │
              │ LanceDB+SQLite│  └────────────────────┘
              └──────────────┘
```

| 容器 | 镜像 | 端口 | 挂载 |
|---|---|---|---|
| `enterprise-kb-api-1` | `enterprise-kb-api` | 8000→8000 | `kb_data`→`/data`；`./models`→`/models` |
| `enterprise-kb-web-1` | `enterprise-kb-web` | 8501→8501 | — |
| `enterprise-kb-neo4j-1` | `neo4j:5` | 7474 / 7687 | `neo4j_data`→`/data` |

---

## 二、仓库里有什么、没什么

**有**：FastAPI 后端（`app/`）、Streamlit 前端（`web/`）、验证脚本（`scripts/`）、三份 Dockerfile、`docker-compose.yml`、`requirements.txt`、配置样例 `.env.example`。

**没有**（需自行补齐）：

| 缺项 | 影响 | 补法 |
|---|---|---|
| `models/`（bge-small-zh-v1.5，约 92 MB） | 仅当 `EMBEDDING_MODE=local` 才需要 | 见 6.1 |
| `kb_data` 卷（LanceDB 向量 + SQLite） | 本地是**空库**，无任何已有文档 | 见 6.2 |
| `neo4j_data` 卷 | 本地图谱为空 | 随 kb_data 一起补，或重建 |
| 构建好的镜像 | 首次 `docker compose build` 需联网拉依赖 | 见 5.1 |

---

## 三、环境要求

| 项 | 建议 |
|---|---|
| OS | Linux / Windows 11 + WSL2 或 Docker Desktop |
| Python | **3.11**（勿用 3.13，lancedb / sentence-transformers 兼容性未验证） |
| 磁盘 | ≥ 20 G 空闲 |
| Docker | 需装 Docker Desktop（Linux 下 user 需在 docker 组） |
| 内存 | ≥ 8 G（Neo4j 单容器常驻约 1–2 G） |

---

## 四、配置项（`.env`）

从 `.env.example` 复制一份为 `.env`，填入真实值。键名如下：

| 键 | 作用 | 备注 |
|---|---|---|
| `GATEWAY_BASE_URL` | LLM 中转站地址（OpenAI 协议） | 自建中转 |
| `GATEWAY_API_KEY` | 中转站密钥 | **敏感** |
| `MODEL_EMBEDDING` | 向量化模型名 | 默认 `text-embedding-3-small` |
| `MODEL_EXTRACT` | 图谱抽取模型 | 默认 `gpt-4o-mini` |
| `MODEL_GENERATE` | 问答生成模型 | 默认 `gpt-4o-mini` |
| `MODEL_DIAGNOSE` | 诊断模型 | 默认 `gpt-4o-mini` |
| `REASONING_FIELD` | 思维链字段解析方式 | `auto` / `reasoning_content` / `none` |
| `APP_API_KEY` | 本服务自身鉴权 key（`/v1/*` 接口） | **敏感** |
| `NEO4J_URI` | 图库连接串 | 容器内应为 `bolt://neo4j:7687` |
| `NEO4J_USER` / `NEO4J_PASSWORD` | 图库账号 | **敏感**，须与 compose 中 `NEO4J_AUTH` 一致 |
| `DATA_DIR` | LanceDB + SQLite 落盘位置 | 容器内 `/data` |

`config.py` 里另有三个键未出现在 `.env` 中（走默认值）：

| 键 | 默认 | 含义 |
|---|---|---|
| `EMBEDDING_MODE` | `cloud` | `cloud` 走中转站 embedding；`local` 走 `models/` 本地模型 |
| `LOCAL_EMBEDDING_MODEL` | `bge-small-zh-v1.5` | — |
| `LOCAL_EMBEDDING_PATH` | `/models/bge-small-zh-v1.5` | compose 已固定挂载 |

> 关键推论：`.env` 未设 `EMBEDDING_MODE` 时走 **cloud 模式**，本地模型非必需。

---

## 五、启动方式

### 5.1 方案 A：Docker Compose（推荐）

```bash
cd enterprise-kb
cp .env.example .env   # 填入真实配置
docker compose up -d --build
```

首次构建需联网拉 `python:3.11-slim` 与 pip 依赖（`sentence-transformers` 较大，约 2–3 GB 依赖树）。

**启动后**：
- Web：http://localhost:8501
- API 文档：http://localhost:8000/docs
- Neo4j Browser：http://localhost:7474

### 5.2 方案 B：本地 Python 直跑（无 Docker 时）

需手动起 Neo4j（或用 Neo4j Desktop / Docker 单独跑一个），再：

```bash
py -3.11 -m venv .venv
.venv\Scripts\activate       # Windows；Linux 用 source .venv/bin/activate
pip install -r requirements.txt

# 后端（另开终端）
uvicorn app.main:app --host 127.0.0.1 --port 8000

# 前端（另开终端）
streamlit run web/app.py --server.port 8501
```

方案 B 下 `.env` 里的 `NEO4J_URI` 若为 `bolt://neo4j:7687`（容器网络名），须改为 `bolt://localhost:7687`；`DATA_DIR` 改为本地路径如 `./data`。

---

## 六、补数据与补模型

### 6.1 补本地 embedding 模型（仅当要用 local 模式）

模型名 `BAAI/bge-small-zh-v1.5`（约 92 MB），从 HuggingFace 下载后放入 `models/bge-small-zh-v1.5`，并在 `.env` 加一行 `EMBEDDING_MODE=local`。

### 6.2 补已有文档与图谱

若要把已有知识从旧环境搬过来，需从旧环境导出 `kb_data`、`neo4j_data` 两个卷，再恢复到本地对应卷。注意：卷名前缀随 compose 目录名变化，用 `docker volume ls` 实际确认；Neo4j 卷须**先停容器再恢复**，否则库文件损坏。

### 6.3 `APP_API_KEY` 与接口鉴权

`/v1/*` 接口默认鉴权生效，请求须带与 `.env` 中 `APP_API_KEY` 相同的凭证（Header 名以 `app/api/deps.py` 为准）。

---

## 七、接口清单

标题：`Enterprise Knowledge Base` v0.1.0，共 12 个接口。

| 方法 | 路径 |
|---|---|
| GET | `/v1/health` |
| GET, POST | `/v1/kb` |
| GET, POST | `/v1/kb/{kb_id}/documents` |
| GET | `/v1/kb/{kb_id}/chunks/{doc_id}` |
| DELETE | `/v1/kb/{kb_id}` |
| POST | `/v1/kb/{kb_id}/upload` |
| POST | `/v1/kb/retrieve` |
| POST | `/v1/kb/ask` |
| POST | `/v1/kb/ask/events`（SSE 思维链） |
| GET | `/v1/graph` |
| POST | `/v1/diagnose` |
| POST | `/v1/chat/completions`（OpenAI 兼容） |

---

## 八、踩坑提示

1. **`models/` 目录必须存在**：compose 里 `./models:/models` 若不存在，Docker 会自建空目录，不报错；但若 `EMBEDDING_MODE=local`，会在运行时报模型找不到。cloud 模式下无碍。
2. **`DATA_DIR=/data` 是容器内路径**：本地直跑（方案 B）必须改掉，否则会往系统根目录写入。
3. **`.env` 含真实密钥**：本仓库**不含** `.env`，只有 `.env.example`。切勿把填好真实值的 `.env` 提交或外传。
4. **Neo4j 密码变了要同步两处**：`.env` 的 `NEO4J_PASSWORD` 与 compose 的 `NEO4J_AUTH`，缺一不可，否则 api 连不上图库。
5. **向量模型维度不可混用**：云上 1024 维与本地 BGE-small 512 维分表存储，切换需重新上传（重建索引）。
