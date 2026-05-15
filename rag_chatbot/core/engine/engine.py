from llama_index.core.chat_engine import CondensePlusContextChatEngine, SimpleChatEngine
from llama_index.core.memory import ChatMemoryBuffer
from llama_index.core.llms.llm import LLM
from llama_index.core.schema import BaseNode
from typing import List
import re
from .retriever import LocalRetriever
from ...setting import RAGSettings


def _clean_filename_in_metadata(filename: str) -> str:
    """Remove UUID prefix from filename for display to LLM.
    
    Example: 'fec52f6e9bc7403497b83f743dae7550_Chinh-sach-nghi-phep.docx' 
             -> 'Chinh-sach-nghi-phep.docx'
    """
    if not filename:
        return filename
    # Match UUID patterns: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx_ or 32 hex chars without dashes
    uuid_pattern = r'^[a-f0-9]{8}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{4}-?[a-f0-9]{12}_'
    cleaned = re.sub(uuid_pattern, '', filename, flags=re.IGNORECASE)
    return cleaned if cleaned else filename


def _clean_node_metadata(nodes: List[BaseNode]) -> List[BaseNode]:
    """Clean UUID prefixes from file_name in all node metadata."""
    for node in nodes:
        if hasattr(node, 'metadata') and node.metadata:
            if 'file_name' in node.metadata:
                node.metadata['file_name'] = _clean_filename_in_metadata(node.metadata['file_name'])
    return nodes


class LocalChatEngine:
    def __init__(
        self, setting: RAGSettings | None = None, host: str = "host.docker.internal"
    ):
        super().__init__()
        self._setting = setting or RAGSettings()
        self._retriever = LocalRetriever(self._setting)
        self._host = host

    def set_engine(
        self,
        llm: LLM,
        nodes: List[BaseNode],
        language: str = "eng",
    ) -> CondensePlusContextChatEngine | SimpleChatEngine:
        token_limit = max(
            self._setting.github.chat_token_limit,
            self._setting.gemini.chat_token_limit,
        )
        # Normal chat engine
        if len(nodes) == 0:
            return SimpleChatEngine.from_defaults(
                llm=llm,
                memory=ChatMemoryBuffer(
                    token_limit=token_limit
                ),
            )

        # Clean UUID prefixes from file_name metadata so LLM sees clean names
        nodes = _clean_node_metadata(nodes)

        # Chat engine with documents
        retriever = self._retriever.get_retrievers(
            llm=llm, language=language, nodes=nodes
        )
        return CondensePlusContextChatEngine.from_defaults(
            retriever=retriever,
            llm=llm,
            memory=ChatMemoryBuffer(token_limit=token_limit),
        )
