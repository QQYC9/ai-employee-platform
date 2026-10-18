from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from packages.models.domain import GeneratedDocument
from packages.tools.base import BaseRealTool
from packages.tools.contract import (
    ToolContract,
    ToolExecutionContext,
    ToolRiskLevel,
)

logger = logging.getLogger(__name__)


class DocumentSecurityError(PermissionError):
    """Raised when path traversal or unauthorized directory access is detected."""
    pass


class DocumentGeneratorInput(BaseModel):
    title: str = Field(min_length=1, max_length=255, description="Document title")
    document_type: str = Field(default="report", max_length=50, description="Type of document (e.g. report, summary, invoice, contract)")
    format: str = Field(default="html", description="Output format: html, md, txt, json, pdf")
    content: str | dict[str, Any] = Field(description="Document content (text, markdown, or JSON structure)")
    language: str = Field(default="ar", description="Language code (ar for Arabic/RTL, en for English/LTR)")
    metadata: dict[str, Any] | None = Field(default=None, description="Optional document metadata")


def _generate_minimal_pdf(title: str, text_content: str) -> bytes:
    """
    Generates a valid, standards-compliant PDF 1.4 document in pure Python.
    Does not require external C++ dependencies or heavy libraries.
    """
    clean_title = title.replace("(", "[").replace(")", "]")
    clean_text = text_content.replace("(", "[").replace(")", "]")
    lines = clean_text.splitlines()[:60]  # Limit to first 60 lines for single page preview

    stream_content = "BT\n/F1 16 Tf\n50 750 Td\n"
    stream_content += f"({clean_title}) Tj\n"
    stream_content += "/F1 10 Tf\n0 -25 Td\n"

    for line in lines:
        sanitized_line = line.strip()[:100]
        stream_content += f"({sanitized_line}) Tj\n0 -14 Td\n"
    stream_content += "ET\n"

    stream_bytes = stream_content.encode("latin-1", errors="replace")
    stream_len = len(stream_bytes)

    objects = [
        # 1: Catalog
        b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n",
        # 2: Pages
        b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n",
        # 3: Page
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>\nendobj\n",
        # 4: Stream
        f"4 0 obj\n<< /Length {stream_len} >>\nstream\n".encode("ascii") + stream_bytes + b"\nendstream\nendobj\n",
        # 5: Font
        b"5 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n",
    ]

    pdf = b"%PDF-1.4\n"
    offsets = []
    current_offset = len(pdf)

    for obj in objects:
        offsets.append(current_offset)
        pdf += obj
        current_offset += len(obj)

    xref_offset = len(pdf)
    pdf += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    pdf += b"0000000000 65535 f \n"
    for offset in offsets:
        pdf += f"{offset:010d} 00000 n \n".encode("ascii")

    pdf += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    return pdf


class DocumentGeneratorTool(BaseRealTool):
    """
    Sandboxed document generation tool.
    Produces physical files (HTML, Markdown, Plain Text, JSON, and PDF) in a secure,
    tenant-isolated directory with path-traversal protection and DB metadata tracking.
    """

    ALLOWED_FORMATS = {"html", "md", "txt", "json", "pdf"}
    MIME_TYPES = {
        "html": "text/html; charset=utf-8",
        "md": "text/markdown; charset=utf-8",
        "txt": "text/plain; charset=utf-8",
        "json": "application/json",
        "pdf": "application/pdf",
    }
    MAX_FILE_BYTES = 5 * 1024 * 1024  # 5 MB

    def __init__(self, db: Session, base_storage_dir: str | Path | None = None):
        self.db = db
        self.base_dir = Path(base_storage_dir or Path.cwd() / "storage" / "documents").resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    @property
    def contract(self) -> ToolContract:
        return ToolContract(
            slug="generate_document",
            name="Document Generator Tool",
            version="1.0.0",
            description="Generates sandboxed, tenant-isolated documents (HTML, Markdown, PDF, JSON, TXT) from structured data.",
            risk_level=ToolRiskLevel.MEDIUM,
            requires_approval=False,
            input_schema=DocumentGeneratorInput.model_json_schema(),
            output_schema={
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "filename": {"type": "string"},
                    "format": {"type": "string"},
                    "file_size": {"type": "integer"},
                    "download_path": {"type": "string"},
                },
            },
            required_permissions=[("write", "documents")],
            default_timeout=15.0,
            max_timeout=45.0,
            supports_idempotency=True,
        )

    def validate_parameters(self, parameters: dict[str, Any]) -> dict[str, Any]:
        parsed = DocumentGeneratorInput(**parameters)
        fmt = parsed.format.strip().lower()
        if fmt not in self.ALLOWED_FORMATS:
            raise ValueError(f"Format '{parsed.format}' is not supported. Allowed: {sorted(self.ALLOWED_FORMATS)}")
        return parsed.model_dump()

    def run(self, context: ToolExecutionContext, **parameters: Any) -> dict[str, Any]:
        tenant_id = context.tenant_id
        title = parameters["title"].strip()
        doc_type = parameters.get("document_type", "report").strip().lower()
        fmt = parameters["format"].strip().lower()
        raw_content = parameters["content"]
        language = parameters.get("language", "ar").strip().lower()
        metadata = parameters.get("metadata") or {}

        # 1. Prepare Tenant Sandboxed Directory
        tenant_dir = (self.base_dir / str(tenant_id)).resolve()
        tenant_dir.mkdir(parents=True, exist_ok=True)

        # 2. Prevent Path Traversal
        doc_id = uuid4()
        clean_slug = re.sub(r"[^a-zA-Z0-9_\-\u0600-\u06FF]", "_", title).strip("_")[:40] or "doc"
        filename = f"{clean_slug}_{str(doc_id)[:8]}.{fmt}"
        target_path = (tenant_dir / filename).resolve()

        try:
            # Check canonical path containment
            common = os.path.commonpath([str(tenant_dir), str(target_path)])
            if common != str(tenant_dir):
                raise DocumentSecurityError("Target document path escapes tenant sandbox boundary")
        except ValueError:
            raise DocumentSecurityError("Target document path violates filesystem boundary")

        # 3. Format and render document content
        file_bytes: bytes
        text_repr: str = ""
        if fmt == "json":
            if isinstance(raw_content, (dict, list)):
                text_repr = json.dumps(raw_content, ensure_ascii=False, indent=2)
            else:
                text_repr = str(raw_content)
            file_bytes = text_repr.encode("utf-8")
        elif fmt == "html":
            text_repr = raw_content if isinstance(raw_content, str) else json.dumps(raw_content, ensure_ascii=False)
            is_rtl = language == "ar"
            direction = "rtl" if is_rtl else "ltr"
            align = "right" if is_rtl else "left"
            html_markup = f"""<!DOCTYPE html>
<html lang="{language}" dir="{direction}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
            background: #f8fafc;
            color: #0f172a;
            margin: 0;
            padding: 30px;
            direction: {direction};
            text-align: {align};
        }}
        .document-container {{
            max-width: 800px;
            margin: 0 auto;
            background: #ffffff;
            border-radius: 12px;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
            padding: 40px;
        }}
        h1 {{
            color: #1e293b;
            border-bottom: 2px solid #e2e8f0;
            padding-bottom: 12px;
        }}
        .content {{
            margin-top: 24px;
            line-height: 1.7;
            white-space: pre-wrap;
        }}
        .footer {{
            margin-top: 40px;
            border-top: 1px solid #e2e8f0;
            padding-top: 16px;
            font-size: 0.85em;
            color: #64748b;
        }}
    </style>
</head>
<body>
    <div class="document-container">
        <h1>{title}</h1>
        <div class="content">{text_repr}</div>
        <div class="footer">Generated by AI Employee Platform • ID: {str(doc_id)[:8]}</div>
    </div>
</body>
</html>"""
            file_bytes = html_markup.encode("utf-8")
        elif fmt == "pdf":
            text_repr = raw_content if isinstance(raw_content, str) else json.dumps(raw_content, ensure_ascii=False)
            file_bytes = _generate_minimal_pdf(title, text_repr)
        elif fmt == "md":
            text_repr = raw_content if isinstance(raw_content, str) else json.dumps(raw_content, ensure_ascii=False)
            md_text = f"# {title}\n\n{text_repr}\n\n---\n*Generated by AI Employee Platform*"
            file_bytes = md_text.encode("utf-8")
        else:  # txt
            text_repr = raw_content if isinstance(raw_content, str) else json.dumps(raw_content, ensure_ascii=False)
            txt_content = f"{title}\n{'=' * len(title)}\n\n{text_repr}\n"
            file_bytes = txt_content.encode("utf-8")

        # 4. Enforce max file size
        file_size = len(file_bytes)
        if file_size > self.MAX_FILE_BYTES:
            raise ValueError(f"Generated document size ({file_size} bytes) exceeds limit of {self.MAX_FILE_BYTES} bytes")

        # 5. Write file atomically
        temp_path = target_path.with_suffix(f".tmp_{str(uuid4())[:8]}")
        with open(temp_path, "wb") as f:
            f.write(file_bytes)
        temp_path.replace(target_path)

        sha256 = hashlib.sha256(file_bytes).hexdigest()
        mime = self.MIME_TYPES.get(fmt, "text/plain")

        # 6. Persist metadata in database
        doc_record = GeneratedDocument(
            id=doc_id,
            tenant_id=tenant_id,
            title=title,
            document_type=doc_type,
            format=fmt,
            filename=filename,
            file_path=str(target_path),
            file_size=file_size,
            mime_type=mime,
            sha256_hash=sha256,
            created_by_agent_id=context.agent_id,
            metadata_json=metadata,
        )
        self.db.add(doc_record)
        self.db.flush()

        return {
            "document_id": str(doc_id),
            "title": title,
            "filename": filename,
            "format": fmt,
            "file_size": file_size,
            "mime_type": mime,
            "sha256_hash": sha256,
            "download_url": f"/api/v1/documents/{doc_id}/download",
        }
