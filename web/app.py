"""Streamlit 前端：左栏思维链 / 右栏带引用答案（实时流式）。"""
import json
import os

import requests
import streamlit as st

API = os.getenv("KB_API_URL", "http://localhost:8000")
API_KEY = os.getenv("APP_API_KEY", "")

st.set_page_config(page_title="企业知识库", page_icon="🏢", layout="wide")
st.title("🏢 企业知识库")


def _auth(key: str) -> dict:
    return {"Authorization": f"Bearer {key}"} if key else {}


# ---------------------------------------------------------------- 侧边栏
with st.sidebar:
    st.header("⚙️ 配置")
    api_base = st.text_input("API 地址", API)
    api_key = st.text_input("API Key", API_KEY, type="password")

    st.divider()
    kb_name = st.text_input("新建知识库名称")
    emb_mode = st.selectbox(
        "向量模型",
        ["云上 (text-embedding-v4 · 1024维)", "本地 (BGE-small-zh · 512维)"],
    )
    if emb_mode.startswith("本地"):
        st.warning("本地模型为 512 维，与云上 1024 维不同；不同模型的数据分表存储，互不通用，切换需重新上传（重建索引）。")
    if st.button("创建知识库") and kb_name:
        model = "local" if emb_mode.startswith("本地") else "cloud"
        r = requests.post(f"{api_base}/v1/kb", json={"name": kb_name, "embedding_model": model}, headers=_auth(api_key))
        if r.ok:
            st.success(f"kb_id: {r.json()['kb_id']}（{r.json().get('embedding_model')}）")
        else:
            st.error(r.text)

    try:
        r = requests.get(f"{api_base}/v1/kb", headers=_auth(api_key), timeout=5)
        kbs = r.json().get("items", []) if r.ok else []
        kb_choices = {f"{k['name']} ({k['id']})": k["id"] for k in kbs}
    except Exception:
        kb_choices = {}

    if kb_choices:
        kb_sel = st.selectbox("知识库", list(kb_choices.keys()))
        kb_id = kb_choices[kb_sel]
    else:
        kb_id = st.text_input("kb_id")

    # 删除知识库：两段式确认，防误触（此操作不可恢复）
    if kb_id:
        if st.session_state.get("confirm_del") == kb_id:
            st.warning(f"确定删除知识库「{kb_id}」？元数据与向量将一并清除，且不可恢复。")
            col_a, col_b = st.columns(2)
            if col_a.button("确认删除", type="primary"):
                r = requests.delete(
                    f"{api_base}/v1/kb/{kb_id}", headers=_auth(api_key), timeout=120
                )
                if r.ok:
                    d = r.json()
                    st.session_state.pop("confirm_del", None)
                    st.success(
                        f"已删除「{d.get('name')}」，清除 {d.get('deleted_vectors')} 条向量"
                    )
                    st.rerun()
                else:
                    st.error(r.text)
            if col_b.button("取消"):
                st.session_state.pop("confirm_del", None)
                st.rerun()
        else:
            if st.button("🗑️ 删除该知识库"):
                st.session_state["confirm_del"] = kb_id
                st.rerun()

    st.divider()
    st.subheader("📄 上传文档")
    url = st.text_input("URL")
    if st.button("上传 URL") and url and kb_id:
        with st.spinner("上传中..."):
            r = requests.post(
                f"{api_base}/v1/kb/{kb_id}/documents",
                json={"url": url},
                headers=_auth(api_key),
            )
        st.json(r.json() if r.ok else {"error": r.text})

    uploaded = st.file_uploader(
        "或上传文件",
        type=["txt", "md", "pdf", "docx", "xlsx", "xls", "csv"],
    )
    st.caption("支持 txt / md / pdf / docx / xlsx / xls / csv；.doc 请另存为 .docx")
    if st.button("上传文件") and uploaded and kb_id:
        with st.spinner("上传中..."):
            r = requests.post(
                f"{api_base}/v1/kb/{kb_id}/upload",
                files={"file": (uploaded.name, uploaded.getvalue())},
                headers=_auth(api_key),
            )
        st.json(r.json() if r.ok else {"error": r.text})


# ---------------------------------------------------------------- 主区
query = st.text_area("问题", height=80, placeholder="问点什么...")
show_reasoning = st.checkbox("显示思维链", value=True)

if st.button("🚀 提问", type="primary") and query and kb_id:
    col_left, col_right = st.columns([1, 1])
    with col_left:
        st.markdown("### 🧠 推理过程")
        left = st.empty()
    with col_right:
        st.markdown("### 💡 答案")
        right = st.empty()

    trace_buf: list[str] = []
    reasoning_buf: list[str] = []
    answer_buf: list[str] = []
    citations: list[dict] = []

    with requests.post(
        f"{api_base}/v1/kb/ask",
        json={"kb_id": kb_id, "query": query},
        headers=_auth(api_key),
        stream=True,
    ) as resp:
        if resp.status_code != 200:
            st.error(f"请求失败 {resp.status_code}: {resp.text}")
        else:
            for raw in resp.iter_lines(decode_unicode=True):
                if not raw or not raw.startswith("data:"):
                    continue
                try:
                    data = json.loads(raw[5:].strip())
                except json.JSONDecodeError:
                    continue

                t = data.get("type")
                if t == "trace":
                    trace_buf.append("• " + data["detail"])
                elif t == "reasoning":
                    reasoning_buf.append(data["delta"])
                elif t == "answer":
                    answer_buf.append(data["delta"])
                elif t == "citations":
                    citations = data.get("items", [])

                if show_reasoning:
                    left.markdown(
                        "\n\n".join(trace_buf) + "\n\n---\n\n" + "".join(reasoning_buf)
                    )
                else:
                    left.markdown("\n\n".join(trace_buf))
                right.markdown("".join(answer_buf))

    if citations:
        st.divider()
        st.subheader("📚 来源")
        for c in citations:
            doc = c.get("document", "") or "unknown"
            st.markdown(f"- **{c['key']}** {doc}: {c.get('text', '')[:150]}")
