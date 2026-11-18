"""用中转站模型抽取实体与关系（结构化 JSON）。"""
from ..core.model_router import router

EXTRACT_PROMPT = """分析下面的文本，抽取实体和实体之间的关系。
对每个实体给出 name/type/description；对每个关系给出 source/target/type/description。
type 取值：PERSON/ORGANIZATION/CONCEPT/TECHNOLOGY/EVENT/LOCATION。
只输出 JSON：{{"entities":[{{"name":"...","type":"...","description":"..."}}],
"relationships":[{{"source":"...","target":"...","type":"...","description":"..."}}]}}

文本：
{text}
"""


async def extract_entities(text: str) -> tuple[list[dict], list[dict]]:
    data = await router.extract(EXTRACT_PROMPT.format(text=text[:8000]))
    entities = data.get("entities") or []
    relationships = data.get("relationships") or []
    return entities, relationships
