from __future__ import annotations

from io import BytesIO

from docx import Document


def build_docx_bytes(rendered_text: str) -> bytes:
    document = Document()
    for paragraph in str(rendered_text or "").split("\n\n"):
        cleaned = paragraph.strip()
        if cleaned:
            document.add_paragraph(cleaned)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()
