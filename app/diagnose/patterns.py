"""RAG 失败诊断：P01-P12 失败模式（移植自 rag_failure_diagnostics_clinic）。"""
import textwrap

from ..core.config import settings
from ..core.model_router import router

PATTERNS = [
    {"id": "P01", "name": "Retrieval hallucination / grounding drift",
     "summary": "Answer confidently contradicts or ignores retrieved documents."},
    {"id": "P02", "name": "Chunk boundary or segmentation bug",
     "summary": "Relevant facts are split, truncated, or mis-grouped across chunks."},
    {"id": "P03", "name": "Embedding mismatch / semantic vs vector distance",
     "summary": "Vector similarity does not match true semantic relevance."},
    {"id": "P04", "name": "Index skew or staleness",
     "summary": "Index returns old or missing data relative to the source of truth."},
    {"id": "P05", "name": "Query rewriting or router misalignment",
     "summary": "Router or rewriter sends queries to the wrong tool or dataset."},
    {"id": "P06", "name": "Long-chain reasoning drift",
     "summary": "Multi-step tasks gradually forget earlier constraints or goals."},
    {"id": "P07", "name": "Tool-call misuse or ungrounded tools",
     "summary": "Tools are called with wrong arguments or without proper grounding."},
    {"id": "P08", "name": "Session memory leak / missing context",
     "summary": "Conversation loses important facts between turns or sessions."},
    {"id": "P09", "name": "Evaluation blind spots",
     "summary": "System passes tests but fails on real incidents or edge cases."},
    {"id": "P10", "name": "Startup ordering / dependency not ready",
     "summary": "Services crash or return 5xx during the first minutes after deploy."},
    {"id": "P11", "name": "Config or secrets drift across environments",
     "summary": "Works locally but breaks in staging or production because of settings."},
    {"id": "P12", "name": "Multi-tenant or multi-agent interference",
     "summary": "Requests or agents overwrite each other's state or resources."},
]


def build_system_prompt() -> str:
    header = """
You are an assistant that triages failures in LLM + RAG pipelines.

You have a library of reusable failure patterns P01–P12.
For each bug description, you must:

1. Choose exactly ONE primary pattern id from P01–P12.
2. Optionally choose up to TWO secondary candidate pattern ids.
3. Explain your reasoning in clear bullet points.
4. Propose a MINIMAL structural fix (retrieval, indexing, routing, eval, infra).

You are not allowed to invent new pattern ids.
Return your answer as structured Markdown with sections:
- Primary pattern
- Secondary candidates (optional)
- Reasoning
- Minimal structural fix
"""
    pattern_lines = [f"{p['id']}: {p['name']} — {p['summary']}" for p in PATTERNS]
    return textwrap.dedent(header).strip() + "\n\nFailure patterns:\n" + "\n".join(pattern_lines)


async def diagnose(bug: str) -> str:
    resp = await router.client.chat.completions.create(
        model=settings.model_diagnose,
        temperature=0.2,
        messages=[
            {"role": "system", "content": build_system_prompt()},
            {"role": "user", "content": "Here is the bug description. Follow the pattern rules.\n\n" + bug},
        ],
    )
    return resp.choices[0].message.content or ""
