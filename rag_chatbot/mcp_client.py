import os
from typing import Any, Dict, Optional

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def call_mcp_tool(tool_name: str, arguments: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Call an MCP tool over Streamable HTTP and return structured output (preferred).

    Expects MCP_URL env var like: http://localhost:8000/mcp
    """

    mcp_url = os.environ.get("MCP_URL", "http://localhost:8000/mcp").strip()
    arguments = arguments or {}

    async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            result = await session.call_tool(tool_name, arguments=arguments)
            if getattr(result, "structuredContent", None):
                return result.structuredContent  # type: ignore[return-value]

            # Fallback: try to return text content as a dict
            content = getattr(result, "content", None) or []
            text_parts: list[str] = []
            for part in content:
                text = getattr(part, "text", None)
                if text:
                    text_parts.append(str(text))
            return {"success": True, "result": "\n".join(text_parts).strip()}
