"""MCP demo CLI (Client #2) to showcase extensibility.

Goal: demonstrate that the same MCP server can be used by multiple clients,
not just the web UI.

Typical demo (Docker):
  docker exec knowledge-user python scripts/mcp_demo_cli.py list-tools
  docker exec knowledge-user python scripts/mcp_demo_cli.py list-docs
  docker exec knowledge-user python scripts/mcp_demo_cli.py search --query "Nhân sự có những quyền lợi gì" --top-k 5
  docker exec knowledge-user python scripts/mcp_demo_cli.py tail-audit --lines 5

You can also run from host if Python deps are installed:
  $env:MCP_URL="http://localhost:8000/mcp"; python scripts/mcp_demo_cli.py list-tools
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import urllib.request
import urllib.error
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


def _print_json(data: Any) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


async def _with_session(mcp_url: str, fn):
    async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            return await fn(session)


async def cmd_list_tools(mcp_url: str) -> int:
    async def _run(session: ClientSession) -> int:
        tools = await session.list_tools()
        out = []
        for t in tools.tools:
            out.append(
                {
                    "name": t.name,
                    "description": getattr(t, "description", None),
                    "inputSchema": getattr(t, "inputSchema", None),
                }
            )
        _print_json({"mcp_url": mcp_url, "tools": out})
        return 0

    return await _with_session(mcp_url, _run)


async def cmd_call_tool(mcp_url: str, tool_name: str, arguments: dict[str, Any]) -> int:
    async def _run(session: ClientSession) -> int:
        result = await session.call_tool(tool_name, arguments=arguments)
        structured = getattr(result, "structuredContent", None)
        if structured is not None:
            _print_json({"tool": tool_name, "arguments": arguments, "result": structured})
            return 0

        content = getattr(result, "content", None) or []
        texts: list[str] = []
        for part in content:
            text = getattr(part, "text", None)
            if text:
                texts.append(str(text))
        _print_json({"tool": tool_name, "arguments": arguments, "result": "\n".join(texts).strip()})
        return 0

    return await _with_session(mcp_url, _run)


def cmd_tail_audit(lines: int) -> int:
    # In Docker, MCP_AUDIT_LOG is typically /app/data/mcp_audit.log (volume-mounted).
    log_path = os.environ.get("MCP_AUDIT_LOG", "/app/data/mcp_audit.log")
    try:
        with open(log_path, "r", encoding="utf-8") as f:
            all_lines = f.readlines()
        tail = all_lines[-max(0, int(lines)) :]
        print("".join(tail).rstrip())
        return 0
    except FileNotFoundError:
        print(f"Audit log not found: {log_path}")
        print("Tip: if running on host, use ./data/mcp_audit.log instead, or set MCP_AUDIT_LOG.")
        return 2


def _http_post_json(url: str, payload: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
            **(headers or {}),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {"success": True}
    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8")
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"error": str(e)}
        return {"success": False, "status": getattr(e, "code", None), **parsed}


def cmd_doc_improve(user_api_base: str, internal_token: str, document_type: str, document_id: int, goal: str, top_k: int) -> int:
    url = user_api_base.rstrip("/") + "/api/internal/agent/doc-improve"
    headers = {"X-Internal-Token": internal_token} if internal_token else {}
    payload = {
        "document_type": document_type,
        "document_id": int(document_id),
        "goal": goal,
        "top_k": int(top_k),
    }
    out = _http_post_json(url, payload, headers=headers)
    _print_json({"url": url, "payload": payload, "result": out})
    return 0 if out.get("success") else 2


def main() -> int:
    parser = argparse.ArgumentParser(description="MCP Demo CLI (Client #2)")
    parser.add_argument(
        "--mcp-url",
        default=(os.environ.get("MCP_URL") or "http://localhost:8000/mcp").strip(),
        help="MCP Streamable HTTP URL (default: env MCP_URL or http://localhost:8000/mcp)",
    )

    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-tools", help="List available MCP tools + schemas")

    sub.add_parser("list-docs", help="Call tool: list_documents")

    p_meta = sub.add_parser("doc-meta", help="Call tool: get_document_metadata")
    p_meta.add_argument("--document-type", required=True, choices=["company", "personal"], help="Document type")
    p_meta.add_argument("--document-id", required=True, type=int, help="Document ID")

    p_search = sub.add_parser("search", help="Call tool: search_chunks")
    p_search.add_argument("--query", required=True, help="Search query")
    p_search.add_argument("--top-k", type=int, default=5, help="Top K results (default 5)")

    p_tail = sub.add_parser("tail-audit", help="Show last N lines of MCP audit log")
    p_tail.add_argument("--lines", type=int, default=10, help="How many lines to show")

    p_improve = sub.add_parser("doc-improve", help="Audit 1 document and propose improvements (internal endpoint)")
    p_improve.add_argument(
        "--user-api-base",
        default=(os.environ.get("USER_API_BASE") or "http://localhost:7861").strip(),
        help="User web base URL (default: env USER_API_BASE or http://localhost:7861)",
    )
    p_improve.add_argument(
        "--internal-token",
        default=(os.environ.get("INTERNAL_SERVICE_TOKEN") or os.environ.get("X_INTERNAL_TOKEN") or "").strip(),
        help="Internal token (default: env INTERNAL_SERVICE_TOKEN)",
    )
    p_improve.add_argument("--document-type", required=True, choices=["company", "personal"], help="Document type")
    p_improve.add_argument("--document-id", required=True, type=int, help="Document ID")
    p_improve.add_argument("--goal", default="policy", help="Goal (policy|sop|procedure)")
    p_improve.add_argument("--top-k", type=int, default=3, help="Top K chunks per check (default 3)")

    args = parser.parse_args()
    mcp_url: str = (args.mcp_url or "").strip()

    if args.cmd == "tail-audit":
        return cmd_tail_audit(args.lines)

    if args.cmd == "doc-improve":
        user_api_base = (args.user_api_base or "").strip()
        if not user_api_base:
            raise SystemExit("Missing --user-api-base")
        if not (args.internal_token or "").strip():
            print("Missing internal token. Set env INTERNAL_SERVICE_TOKEN or pass --internal-token.")
            return 2
        return cmd_doc_improve(
            user_api_base,
            args.internal_token,
            args.document_type,
            args.document_id,
            args.goal,
            args.top_k,
        )

    if not mcp_url:
        raise SystemExit("Missing MCP URL")

    if args.cmd == "list-tools":
        return asyncio.run(cmd_list_tools(mcp_url))

    if args.cmd == "list-docs":
        return asyncio.run(cmd_call_tool(mcp_url, "list_documents", {}))

    if args.cmd == "doc-meta":
        return asyncio.run(
            cmd_call_tool(
                mcp_url,
                "get_document_metadata",
                {"document_type": args.document_type, "document_id": args.document_id},
            )
        )

    if args.cmd == "search":
        return asyncio.run(cmd_call_tool(mcp_url, "search_chunks", {"query": args.query, "top_k": args.top_k}))

    raise SystemExit(f"Unknown command: {args.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
