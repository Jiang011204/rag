"""全局配置：从 .env / 环境变量读取。"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


@dataclass
class Settings:
    # 中转站（OpenAI 协议）
    gateway_base_url: str = _env("GATEWAY_BASE_URL")
    gateway_api_key: str = _env("GATEWAY_API_KEY")

    # 模型路由（function -> model）
    model_embedding: str = _env("MODEL_EMBEDDING", "text-embedding-3-small")
    model_extract: str = _env("MODEL_EXTRACT", "gpt-4o-mini")
    model_generate: str = _env("MODEL_GENERATE", "gpt-4o-mini")
    model_diagnose: str = _env("MODEL_DIAGNOSE", "gpt-4o-mini")

    # embedding 本地化：embedding_mode = cloud | local
    embedding_mode: str = _env("EMBEDDING_MODE", "cloud")
    local_embedding_model: str = _env("LOCAL_EMBEDDING_MODEL", "bge-small-zh-v1.5")
    local_embedding_path: str = _env("LOCAL_EMBEDDING_PATH", "/models/bge-small-zh-v1.5")

    # 思维链字段：auto | reasoning_content | none
    reasoning_field: str = _env("REASONING_FIELD", "auto")

    # 应用自身 API key
    app_api_key: str = _env("APP_API_KEY", "")

    # Neo4j
    neo4j_uri: str = _env("NEO4J_URI", "bolt://localhost:7687")
    neo4j_user: str = _env("NEO4J_USER", "neo4j")
    neo4j_password: str = _env("NEO4J_PASSWORD", "please-change-me")

    # 数据目录（LanceDB + SQLite）
    data_dir: str = _env("DATA_DIR", "./data")


settings = Settings()
