"""把 URL / 文本 / 文件解析成纯文本。

表格类内容（Word 表格 / Excel / CSV）按行分块，**每块都重复表头**，
以免切分之后检索到的数据行失去列名，变得无法理解。
"""
import csv
import io

import requests
from bs4 import BeautifulSoup

# 每个表格分块包含的数据行数（不含表头）
TABLE_ROWS_PER_CHUNK = 20

# 单元格分隔符
CELL_SEP = " | "


def load_url(url: str) -> str:
    resp = requests.get(
        url, timeout=30, headers={"User-Agent": "Mozilla/5.0"}
    )
    resp.raise_for_status()
    ctype = resp.headers.get("content-type", "")
    if "text/html" in ctype or "application/xhtml" in ctype:
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        return soup.get_text("\n", strip=True)
    return resp.text


# ---------------------------------------------------------------- 表格工具
def _table_rows(values) -> list[str]:
    """二维单元格 -> 行文本列表，跳过整行皆空的行。"""
    rows = []
    for row in values:
        cells = ["" if c is None else str(c).strip() for c in row]
        if any(cells):
            rows.append(CELL_SEP.join(cells))
    return rows


def _rows_to_blocks(rows: list[str], title: str = "") -> list[str]:
    """把表格行分组，每组都带上首行（表头）。

    行与行之间用单个换行，组与组之间由调用方用空行分隔，
    这样下游按段落切分时，天然以「组」为单位，不会把行拦腰截断。
    """
    if not rows:
        return []
    if len(rows) == 1:
        return [f"{title}\n{rows[0]}" if title else rows[0]]

    header, body = rows[0], rows[1:]
    blocks = []
    for i in range(0, len(body), TABLE_ROWS_PER_CHUNK):
        group = body[i:i + TABLE_ROWS_PER_CHUNK]
        block = "\n".join([header] + group)
        blocks.append(f"{title}\n{block}" if title else block)
    return blocks


# ---------------------------------------------------------------- 各格式解析
def _docx_to_text(data: bytes) -> str:
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
    for idx, table in enumerate(doc.tables, 1):
        rows = _table_rows([[c.text for c in row.cells] for row in table.rows])
        if rows:
            parts.extend(_rows_to_blocks(rows, title=f"[表格 {idx}]"))
    return "\n\n".join(parts)


def _xlsx_to_text(data: bytes) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    parts = []
    try:
        for ws in wb.worksheets:
            rows = _table_rows(ws.iter_rows(values_only=True))
            if rows:
                parts.extend(_rows_to_blocks(rows, title=f"# sheet: {ws.title}"))
    finally:
        wb.close()
    return "\n\n".join(parts)


def _xls_to_text(data: bytes) -> str:
    import xlrd

    book = xlrd.open_workbook(file_contents=data)
    parts = []
    for ws in book.sheets():
        rows = _table_rows([ws.row_values(r) for r in range(ws.nrows)])
        if rows:
            parts.extend(_rows_to_blocks(rows, title=f"# sheet: {ws.name}"))
    return "\n\n".join(parts)


def _csv_to_text(data: bytes) -> str:
    text = _decode_text(data)
    rows = _table_rows(csv.reader(io.StringIO(text)))
    return "\n\n".join(_rows_to_blocks(rows, title="# csv"))


def _decode_text(data: bytes) -> str:
    """中文环境常见编码依次尝试，避免 GBK 文件变成乱码。"""
    for enc in ("utf-8", "gbk", "gb18030", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


# ---------------------------------------------------------------- 入口
TEXT_SUFFIX = (".txt", ".md", ".markdown", ".json", ".log", ".html", ".htm")


def load_file(filename: str, data: bytes) -> str:
    name = (filename or "").lower()

    if name.endswith(".pdf"):
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(data))
        return "\n\n".join((page.extract_text() or "") for page in reader.pages)

    if name.endswith(".docx"):
        return _docx_to_text(data)

    if name.endswith((".xlsx", ".xlsm")):
        return _xlsx_to_text(data)

    if name.endswith(".xls"):
        return _xls_to_text(data)

    if name.endswith(".csv"):
        return _csv_to_text(data)

    if name.endswith(".doc"):
        raise ValueError("不支持 .doc（Word 97-2003 二进制格式），请另存为 .docx 后重传")

    if name.endswith(TEXT_SUFFIX):
        return _decode_text(data)

    # 未知类型：含二进制零字节的一律拒绝，绝不静默把乱码写进知识库
    if b"\x00" in data[:1024]:
        raise ValueError(f"暂不支持的文件类型：{filename or '未知'}")
    return _decode_text(data)
