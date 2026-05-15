"""Deprecated Ollama helpers.

Ollama support has been removed to reduce image size and simplify deployment.
This module remains as a compatibility shim for old imports.
"""


def run_ollama_server():
    raise NotImplementedError("Ollama support has been removed. Use LLM_PROVIDER=github|gemini.")


def is_port_open(port):
    return False
