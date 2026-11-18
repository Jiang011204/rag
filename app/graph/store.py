"""Neo4j 图谱存储：实体/关系写入 + 多跳遍历。"""
import re

from neo4j import GraphDatabase

from ..core.config import settings


class GraphStore:
    def __init__(self):
        # driver 惰性连接，Neo4j 未就绪时不会在 import 阶段报错
        self.driver = GraphDatabase.driver(
            settings.neo4j_uri,
            auth=(settings.neo4j_user, settings.neo4j_password),
        )

    def add_all(self, entities: list[dict], relationships: list[dict], doc_name: str):
        with self.driver.session() as s:
            for e in entities:
                s.run(
                    "MERGE (n:Entity {name:$name}) SET n.type=$type, "
                    "n.description=$description, n.source_doc=$doc",
                    name=e.get("name"),
                    type=e.get("type", "CONCEPT"),
                    description=e.get("description", ""),
                    doc=doc_name,
                )
            for r in relationships:
                s.run(
                    "MATCH (a:Entity {name:$a}) MATCH (b:Entity {name:$b}) "
                    "MERGE (a)-[rel:RELATES_TO {type:$t}]->(b) "
                    "SET rel.description=$d, rel.source_doc=$doc",
                    a=r.get("source"),
                    b=r.get("target"),
                    t=r.get("type", "RELATED"),
                    d=r.get("description", ""),
                    doc=doc_name,
                )

    # Generic words that match many entities and poison graph expansion.
    _GENERIC = {
        "\u7ba1\u7406", "\u7cfb\u7edf", "\u9700\u6c42", "\u529f\u80fd", "\u6a21\u5757",
        "\u95ee\u9898", "\u65b9\u6cd5", "\u65b9\u6848", "\u5185\u5bb9", "\u60c5\u51b5",
        "\u9879\u76ee", "\u5e73\u53f0", "\u6570\u636e", "\u4fe1\u606f", "\u670d\u52a1",
        "\u5ba2\u6237", "\u9500\u552e", "\u4eba\u5458", "\u4e1a\u52a1", "\u8bbe\u7f6e",
        "\u8bb0\u5f55", "\u94fe\u63a5", "\u4e2d\u5fc3", "\u90e8\u95e8", "\u8d1f\u8d23\u4eba",
        "\u7ba1\u7406\u5458", "\u4e3b\u7ba1", "\u7ecf\u7406", "\u5458\u5de5", "\u5de5\u4f5c",
        "\u65f6\u95f4", "\u5730\u70b9", "\u6570\u91cf", "\u540d\u79f0", "\u72b6\u6001",
    }

    @classmethod
    def _query_terms(cls, query: str) -> list[str]:
        # The old implementation treated the whole Chinese sentence as one term
        # (e.g. a full question string), while entity names are short words, so
        # CONTAINS never matched and graph hops were effectively dead. Now split
        # on punctuation/stopwords and add 2-4 char sliding windows.
        whole = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]{2,}", query) or [query]
        stop = "[\u7684\u548c\u4e0e\u53ca\u6216\u3001\uff0c,\u3002\uff1f?\uff01!:\uff1a\\s]+"
        filler = "|\u54ea\u4e9b|\u4ec0\u4e48|\u600e\u4e48|\u5982\u4f55|\u662f\u5426|\u6709\u6ca1\u6709|\u4ecb\u7ecd|\u5173\u4e8e"
        parts: list[str] = []
        for seg in whole:
            for piece in re.split(stop + filler, seg):
                if len(piece) >= 2:
                    parts.append(piece)
        terms: list[str] = []
        for piece in parts + whole:
            if 2 <= len(piece) <= 12:
                terms.append(piece)
            if re.search(r"[\u4e00-\u9fff]", piece):
                for n in (2, 3, 4):
                    for k in range(0, max(0, len(piece) - n + 1)):
                        terms.append(piece[k : k + n])
        seen, out = set(), []
        for t in terms:
            t = t.strip()
            if len(t) >= 2 and t not in seen:
                seen.add(t)
                out.append(t)
        return out

    def find_start_entities(self, query: str, limit: int = 3) -> list[str]:
        # Rank by how much of the entity NAME is covered by the query text, then
        # prefer the shortest (most specific) anchor. Without this a long
        # description-side hit such as "AI\u62dc\u8bbf\u52a9\u624b" can outrank the entity
        # actually named for the topic ("\u5ba2\u6237\u7ba1\u7406\u6a21\u5757").
        terms = self._query_terms(query)
        q = query.lower()
        with self.driver.session() as s:
            res = s.run(
                "MATCH (e:Entity) "
                "WHERE any(t IN $terms WHERE "
                "  toLower(e.name) CONTAINS toLower(t) "
                "  OR toLower(e.description) CONTAINS toLower(t)) "
                "WITH e, [t IN $terms WHERE toLower(e.name) CONTAINS toLower(t)] AS name_hits "
                "WHERE size(name_hits) > 0 "
                "  AND NOT any(t IN name_hits WHERE t IN $generic) "
                "  AND size(e.name) >= 2 "
                "WITH e, name_hits, "
                "     reduce(c = 0, t IN name_hits | CASE WHEN size(t) > c THEN size(t) ELSE c END) AS best_hit, "
                "     size(e.name) AS name_len "
                "RETURN e.name AS name "
                "ORDER BY toFloat(best_hit) / toFloat(name_len) DESC, best_hit DESC, name_len ASC "
                "LIMIT $limit",
                terms=terms,
                generic=list(self._GENERIC),
                limit=limit,
            )
            return [r["name"] for r in res]

    def expand(self, names: list[str], hops: int = 2) -> list[dict]:
        out = []
        for name in names:
            with self.driver.session() as s:
                res = s.run(
                    f"MATCH path=(start:Entity {{name:$name}})-[*1..{int(hops)}]-(rel:Entity) "
                    "RETURN rel.name AS name, rel.description AS description, "
                    "rel.source_doc AS source",
                    name=name,
                )
                for r in res:
                    out.append(
                        {
                            "name": r["name"],
                            "description": r["description"] or "",
                            "source": r["source"] or "",
                        }
                    )
        return out


    def view(self, q: str | None = None, limit: int = 120) -> tuple[list[dict], list[dict]]:
        """返回可渲染的实体邻域：节点带度数，边只保留两端都在节点集内的。"""
        with self.driver.session() as s:
            if q:
                rows = s.run(
                    "MATCH (e:Entity) WHERE toLower(e.name) CONTAINS toLower($q) "
                    "   OR toLower(e.description) CONTAINS toLower($q) "
                    "RETURN e.name AS name, e.type AS type, "
                    "       coalesce(e.description,'') AS description, "
                    "       coalesce(e.source_doc,'') AS source_doc, "
                    "       COUNT { (e)-[:RELATES_TO]-() } AS degree "
                    "ORDER BY degree DESC LIMIT $limit",
                    q=q, limit=int(limit),
                )
            else:
                rows = s.run(
                    "MATCH (e:Entity) "
                    "RETURN e.name AS name, e.type AS type, "
                    "       coalesce(e.description,'') AS description, "
                    "       coalesce(e.source_doc,'') AS source_doc, "
                    "       COUNT { (e)-[:RELATES_TO]-() } AS degree "
                    "ORDER BY degree DESC LIMIT $limit",
                    limit=int(limit),
                )
            nodes = [
                {
                    "id": r["name"],
                    "name": r["name"],
                    "type": r["type"] or "CONCEPT",
                    "description": r["description"],
                    "source_doc": r["source_doc"],
                    "degree": r["degree"],
                }
                for r in rows
            ]
            keep = {n["id"] for n in nodes}
            links = [
                {
                    "source": r["source"],
                    "target": r["target"],
                    "type": r["type"] or "RELATED",
                    "weight": r["weight"],
                }
                for r in s.run(
                    "MATCH (a:Entity)-[r:RELATES_TO]->(b:Entity) "
                    "RETURN a.name AS source, b.name AS target, "
                    "       coalesce(r.type,'RELATED') AS type, "
                    "       count(*) AS weight"
                )
                if r["source"] in keep and r["target"] in keep
            ]
        return nodes, links

graph_store = GraphStore()
