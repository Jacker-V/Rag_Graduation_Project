import asyncio
import os

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def main() -> None:
    mcp_url = os.environ.get("MCP_URL", "http://localhost:8000/mcp").strip()
    print(f"Connecting to MCP: {mcp_url}")

    async with streamable_http_client(mcp_url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()

            tools = await session.list_tools()
            print("Tools:", [t.name for t in tools.tools])

            # Call search_chunks
            query = os.environ.get("QUERY", "What is the leave policy?")
            result = await session.call_tool("search_chunks", arguments={"query": query, "top_k": 3})
            structured = getattr(result, "structuredContent", None)
            print("search_chunks structuredContent:")
            print(structured)


if __name__ == "__main__":
    asyncio.run(main())
