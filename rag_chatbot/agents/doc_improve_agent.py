from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _data_root_dir() -> Path:
    base = (os.environ.get("DATA_DIR") or "").strip()
    if base:
        base_path = Path(base)
        # Prefer shared root data volume when DATA_DIR points to .../data/data
        if base_path.name == "data" and base_path.parent.name == "data":
            return base_path.parent
        if base_path.name == "data" and (base_path.parent / "knowledge_base.db").exists():
            return base_path.parent
        return base_path

    # Best effort: walk up to find repo root containing data/
    current = Path(__file__).resolve()
    for _ in range(10):
        candidate = current.parent / "data"
        if candidate.exists():
            return candidate
        current = current.parent
    return Path.cwd() / "data"


def _improvements_dir() -> Path:
    explicit = (os.environ.get("DOC_IMPROVEMENTS_DIR") or "").strip()
    if explicit:
        return Path(explicit)
    return _data_root_dir() / "doc_improvements"


@dataclass(frozen=True)
class DocImproveRequest:
    document_type: str
    document_id: int
    goal: str = "policy"
    language: str = "vi"


def _normalize_goal(goal: str) -> str:
    g = (goal or "").strip().lower()
    return g or "policy"


def build_gap_checks(goal: str) -> list[dict[str, str]]:
    """Deterministic checklist so the demo is stable."""

    goal = _normalize_goal(goal)

    # Common internal doc structure.
    base = [
        {"key": "purpose", "title": "Mục đích", "query": "mục đích"},
        {"key": "scope", "title": "Phạm vi", "query": "phạm vi áp dụng"},
        {"key": "definitions", "title": "Định nghĩa / Thuật ngữ", "query": "định nghĩa thuật ngữ"},
        {"key": "roles", "title": "Vai trò & Trách nhiệm", "query": "vai trò trách nhiệm"},
        {"key": "procedure", "title": "Quy trình / Nội dung chính", "query": "quy trình"},
        {"key": "exceptions", "title": "Ngoại lệ", "query": "ngoại lệ"},
        {"key": "compliance", "title": "Tuân thủ / Vi phạm", "query": "vi phạm kỷ luật tuân thủ"},
        {"key": "security", "title": "Bảo mật", "query": "bảo mật dữ liệu"},
        {"key": "effective", "title": "Hiệu lực", "query": "hiệu lực"},
        {"key": "review", "title": "Rà soát / Cập nhật", "query": "rà soát cập nhật định kỳ"},
    ]

    if goal in {"sop", "procedure"}:
        base.insert(5, {"key": "forms", "title": "Biểu mẫu / Checklist", "query": "biểu mẫu checklist"})
    if goal in {"policy", "hr_policy"}:
        base.insert(6, {"key": "benefits", "title": "Quyền lợi / Phúc lợi", "query": "quyền lợi phúc lợi"})

    return base


def _sources_from_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, Any]] = set()
    for r in results or []:
        filename = r.get("filename")
        page = r.get("page")
        key = (str(filename), page)
        if key in seen:
            continue
        seen.add(key)
        out.append({"filename": filename, "page": page, "score": r.get("score")})
    return out


def build_improve_prompt(
    *,
    doc_label: str,
    goal: str,
    checks: list[dict[str, Any]],
) -> str:
    blocks: list[str] = []
    for c in checks:
        title = c.get("title")
        hits = c.get("results") or []
        if not hits:
            blocks.append(f"## {title}\n(Không tìm thấy đoạn nào liên quan trong tài liệu.)")
            continue

        lines: list[str] = [f"## {title}"]
        for idx, h in enumerate(hits, start=1):
            filename = h.get("filename")
            page = h.get("page")
            text = (h.get("text") or "").strip()
            lines.append(f"[{idx}] {filename} (page {page})\n{text}")
        blocks.append("\n".join(lines))

    context = "\n\n".join(blocks)

    return (
        "Bạn là AI Document Improvement Agent của công ty. Nhiệm vụ: đánh giá một tài liệu nội bộ, phát hiện phần thiếu/nhạt/không rõ, và đề xuất bổ sung.\n\n"
        f"Tài liệu đang rà soát: {doc_label}\n"
        f"Mục tiêu (goal): {goal}\n\n"
        "Nguyên tắc:\n"
        "- Khi nhận xét 'đã có' hoặc 'thiếu', phải dựa trên các snippets đã cung cấp.\n"
        "- Nếu thiếu nguồn cho một mục, đánh dấu rõ 'Thiếu trong tài liệu' và đề xuất nội dung bổ sung ở dạng **đề xuất** (không trích nguồn).\n"
        "- Xuất ra 3 phần: (1) Gap report; (2) Checklist bổ sung; (3) Bản nháp nội dung bổ sung (markdown).\n\n"
        "Snippets trích từ tài liệu (đã lọc theo filename):\n"
        f"{context}\n"
    )


async def improve_document(
    *,
    document_type: str,
    document_id: int,
    goal: str,
    call_mcp_tool,
    llm,
    top_k: int = 3,
) -> dict[str, Any]:
    """Audit a specific document and propose improvements.

    Requires MCP tools:
      - get_document_metadata
      - search_chunks (with optional filenames filter)
    """

    document_type = (document_type or "").strip().lower()
    if document_type not in {"company", "personal"}:
        raise ValueError("document_type must be 'company' or 'personal'")

    goal = _normalize_goal(goal)

    meta = await call_mcp_tool(
        "get_document_metadata",
        {"document_type": document_type, "document_id": int(document_id)},
    )

    doc = (meta or {}).get("document") or {}
    filename = (doc.get("original_filename") or doc.get("filename") or "").strip()
    if not filename:
        filename = f"{document_type}:{document_id}"

    doc_label = f"{filename} ({document_type}#{document_id})"

    checks_plan = build_gap_checks(goal)

    checks: list[dict[str, Any]] = []
    all_sources: list[dict[str, Any]] = []

    for c in checks_plan:
        q = c["query"]
        # Force search within this document by filename.
        resp = await call_mcp_tool(
            "search_chunks",
            {"query": f"{q}", "top_k": int(top_k), "filenames": [filename]},
        )
        results = (resp or {}).get("results") or []
        checks.append({
            "key": c["key"],
            "title": c["title"],
            "query": q,
            "results": results,
        })
        all_sources.extend(_sources_from_results(results))

    prompt = build_improve_prompt(doc_label=doc_label, goal=goal, checks=checks)

    if llm is None:
        raise ValueError("LLM not initialized")

    result = llm.complete(prompt)
    text = getattr(result, "text", "") if result is not None else ""
    report_md = (text or "").strip() or "(Không tạo được báo cáo. Vui lòng thử lại.)"

    top_k = int(top_k)

    improve_id = str(uuid.uuid4())
    record = {
        "id": improve_id,
        "created_at": _now_iso(),
        "document_type": document_type,
        "document_id": int(document_id),
        "filename": filename,
        "goal": goal,
        "top_k": top_k,
        "checks": checks,
        "report_markdown": report_md,
        "sources": all_sources,
        "mcp": True,
    }

    out_dir = _improvements_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{improve_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_dir / f"{improve_id}.md").write_text(report_md, encoding="utf-8")

    return {
        "success": True,
        "improve_id": improve_id,
        "document_type": document_type,
        "document_id": int(document_id),
        "filename": filename,
        "goal": goal,
        "top_k": top_k,
        "report_markdown": report_md,
        "sources": all_sources,
        "mcp": True,
    }
