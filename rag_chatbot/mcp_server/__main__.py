import os

from dotenv import load_dotenv

from .server import mcp


def main() -> None:
    load_dotenv(override=True)

    host = os.environ.get("HOST", "0.0.0.0").strip() or "0.0.0.0"
    port_raw = os.environ.get("PORT", "8000").strip() or "8000"
    try:
        port = int(port_raw)
    except ValueError:
        port = 8000

    # Best-effort: configure settings if supported by the installed MCP version.
    try:
        mcp.settings.host = host
        mcp.settings.port = port
    except Exception:
        pass

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
