import re
from pathlib import Path
from typing import List, Dict

def _clean_id(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9_.-]+", "-", text)
    return re.sub(r"-+", "-", text).strip("-") or "entity"

def _extract_frontmatter_value(text: str, key: str) -> str | None:
    for line in text.splitlines():
        match = re.match(rf"^{re.escape(key)}:\s*(.+)", line.strip(), re.I)
        if match:
            return match.group(1).strip().strip('"')
    return None

def _split_items(text: str) -> List[str]:
    text = text.replace("\r\n", "\n").strip()
    return [
        part.strip()
        for part in re.split(r"\n(?=## )", text)
        if part.strip()
    ]

def chunk_markdown(text: str, source: str) -> List[Dict]:
    if not text or not text.strip():
        return []

    blocks = _split_items(text)
    chunks: List[Dict] = []

    for block in blocks:
        lines = block.splitlines()
        title_line = None
        for line in lines:
            # Use the first heading as the chunk title.
            if line.startswith("#"):
                title_line = line.lstrip("#").strip()
                break
        if not title_line:
            continue

        # Read metadata from frontmatter-style lines inside the block.
        type_ = _extract_frontmatter_value(block, "type") or "section"
        name = _extract_frontmatter_value(block, "name") or title_line
        category = _extract_frontmatter_value(block, "category") or ""
        entity_id = _extract_frontmatter_value(block, "id") or _clean_id(title_line)

        # Build a globally unique chunk ID based on source file + entity.
        chunk_id = f"{Path(source).stem}-{entity_id}"

        chunks.append({
            "id": chunk_id,
            "source": source,
            "type": type_,
            "name": name,
            "category": category,
            "text": block.strip(),
        })

    return chunks