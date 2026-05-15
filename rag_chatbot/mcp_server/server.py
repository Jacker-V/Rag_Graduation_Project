import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

import requests

load_dotenv(override=True)


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _audit_log(tool: str, arguments: dict[str, Any], ok: bool, detail: str | None = None) -> None:
    log_path = os.environ.get("MCP_AUDIT_LOG", "/app/data/mcp_audit.log")
    record = {
        "ts": _now_iso(),
        "tool": tool,
        "ok": ok,
        "arguments": arguments,
        "detail": detail,
    }
    try:
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        # Never crash tool execution due to logging.
        print(f"[MCP] Audit log failed: {exc}")


def _user_tools_base_url() -> str:
    base = os.environ.get("USER_TOOL_BASE_URL", "http://knowledge-user:7861/api/internal/tools").strip()
    return base.rstrip("/")


def _internal_headers() -> dict[str, str]:
    token = os.environ.get("INTERNAL_SERVICE_TOKEN", "").strip()
    if not token:
        return {}
    return {"Authorization": f"Bearer {token}"}


def _http_get_json(url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    resp = requests.get(url, headers=_internal_headers(), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _http_post_json(url: str, payload: dict[str, Any], *, timeout: float = 15.0) -> dict[str, Any]:
    resp = requests.post(url, json=payload, headers=_internal_headers(), timeout=timeout)
    resp.raise_for_status()
    return resp.json()


mcp = FastMCP(
    "Internal Knowledge MCP (Read-only)",
    stateless_http=True,
    json_response=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[
            h.strip()
            for h in os.environ
            .get(
                "MCP_ALLOWED_HOSTS",
                "127.0.0.1:*,localhost:*,[::1]:*,knowledge-mcp:*,knowledge-mcp",
            )
            .split(",")
            if h.strip()
        ],
    ),
)


@mcp.tool()
def list_documents() -> dict[str, Any]:
    """List available documents (company + approved personal)."""
    tool = "list_documents"
    args: dict[str, Any] = {}
    try:
        url = f"{_user_tools_base_url()}/documents"
        data = _http_get_json(url)
        _audit_log(tool, args, ok=True)
        return data
    except Exception as exc:
        _audit_log(tool, args, ok=False, detail=str(exc))
        return {"success": False, "error": str(exc)}


@mcp.tool()
def get_document_metadata(document_type: str, document_id: int) -> dict[str, Any]:
    """Get metadata for a document by type and id."""
    tool = "get_document_metadata"
    args = {"document_type": document_type, "document_id": document_id}
    try:
        url = f"{_user_tools_base_url()}/documents/{document_type}/{int(document_id)}"
        data = _http_get_json(url)
        _audit_log(tool, args, ok=True)
        return data
    except Exception as exc:
        _audit_log(tool, args, ok=False, detail=str(exc))
        return {"success": False, "error": str(exc)}


@mcp.tool()
def search_chunks(query: str, top_k: int = 5, filenames: Optional[List[str]] = None) -> dict[str, Any]:
    """Search and return top chunks relevant to a query.

    Optional:
      - filenames: restrict results to specific original filenames.
    """
    tool = "search_chunks"
    args = {"query": query, "top_k": top_k}
    if filenames:
        args["filenames"] = filenames
    try:
        url = f"{_user_tools_base_url()}/search"
        payload: dict[str, Any] = {"query": query, "top_k": top_k}
        if filenames:
            payload["filenames"] = filenames
        data = _http_post_json(url, payload)
        _audit_log(tool, args, ok=True)
        return data
    except Exception as exc:
        _audit_log(tool, args, ok=False, detail=str(exc))
        return {"success": False, "error": str(exc)}
