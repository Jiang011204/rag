"""切分：先按段落；长段若含多行则按行切（保证表格行完整），纯长文本再按字符带重叠切。"""


def _split_by_lines(text: str, max_chars: int) -> list[str]:
    """多行块按行累积切分 —— 表格行绝不会被拦腰截断。"""
    lines = text.split("\n")
    blocks: list[str] = []
    buf: list[str] = []
    size = 0
    for line in lines:
        add = len(line) + 1
        if buf and size + add > max_chars:
            blocks.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += add
    if buf:
        blocks.append("\n".join(buf))
    return [b for b in blocks if b.strip()]


def _split_long(text: str, max_chars: int, overlap: int) -> list[str]:
    if len(text) <= max_chars:
        return [text] if text.strip() else []
    if "\n" in text:
        return _split_by_lines(text, max_chars)
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        if end == len(text):
            break
        start = end - overlap
    return chunks


def chunk_text(text: str, max_chars: int = 1200, overlap: int = 150) -> list[str]:
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    for para in paragraphs:
        chunks.extend(_split_long(para, max_chars, overlap))
    return [c for c in chunks if c.strip()]
