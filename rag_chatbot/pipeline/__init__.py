from rag_chatbot.core import (
    LocalChatEngine,
    LocalDataIngestion,
    LocalEmbedding,
    LocalVectorStore,
    get_system_prompt,
    GeminiLLM,
)
from rag_chatbot.core.model.model import GitHubLLM
from llama_index.core import Settings
from llama_index.core.chat_engine.types import StreamingAgentChatResponse
from llama_index.core.prompts import ChatMessage, MessageRole
from rag_chatbot.setting import RAGSettings
import os


class LocalRAGPipeline:
    def __init__(self, host: str = "localhost", auto_init_docs: bool = True, use_gemini: bool = False, gemini_api_key: str = None) -> None:
        # Load settings
        self._settings = RAGSettings()
        self._host = host
        self._language = "eng"
        
        # Check USE_GEMINI toggle first (for quick switching)
        use_gemini_env = os.environ.get('USE_GEMINI', 'false').lower() in ('true', '1', 'yes')
        
        # Determine which LLM provider to use
        # Supported providers: github, gemini
        llm_provider = os.environ.get('LLM_PROVIDER', '').lower().strip()
        
        # USE_GEMINI toggle overrides LLM_PROVIDER if set to true
        if use_gemini_env or use_gemini:
            llm_provider = 'gemini'

        # Auto-detect provider if not set
        if not llm_provider:
            if (gemini_api_key or os.environ.get('GEMINI_API_KEY') or self._settings.gemini.api_key):
                llm_provider = 'gemini'
            elif (os.environ.get('LLM_TOKEN') or self._settings.github.api_token):
                llm_provider = 'github'

        if llm_provider in ('ollama', 'openrouter', 'openai'):
            print(f"[PIPELINE] Warning: LLM_PROVIDER={llm_provider} is not supported anymore; falling back to GitHub/Gemini")
            llm_provider = 'gemini' if (gemini_api_key or os.environ.get('GEMINI_API_KEY') or self._settings.gemini.api_key) else 'github'
        
        # Set up LLM based on provider
        if llm_provider == 'github':
            # GitHub LLM
            api_token = os.environ.get('LLM_TOKEN') or self._settings.github.api_token
            endpoint = os.environ.get('LLM_ENDPOINT') or self._settings.github.endpoint
            model = os.environ.get('LLM_MODEL') or self._settings.github.model
            
            if not api_token:
                raise ValueError("GitHub LLM token required. Set LLM_TOKEN environment variable or configure in settings.")
            
            self._default_model = GitHubLLM(
                api_token=api_token,
                endpoint=endpoint,
                model=model,
                temperature=self._settings.github.temperature,
                max_tokens=self._settings.github.max_tokens,
                context_window=self._settings.github.context_window,
            )
            self._model_name = model
            self._use_gemini = False
            Settings.llm = self._default_model
            print(f"[PIPELINE] Using GitHub LLM: {model}")
            
        elif llm_provider == 'gemini':
            # Gemini LLM
            api_key = gemini_api_key or os.environ.get('GEMINI_API_KEY') or self._settings.gemini.api_key
            gemini_model = os.environ.get('GEMINI_MODEL') or self._settings.gemini.model
            if not api_key:
                raise ValueError("Gemini API key required. Set GEMINI_API_KEY environment variable, pass gemini_api_key parameter, or configure in settings.")
            self._default_model = GeminiLLM(api_key=api_key, model=gemini_model)
            self._model_name = gemini_model
            self._use_gemini = True
            Settings.llm = self._default_model
            print(f"[PIPELINE] Using Gemini: {self._model_name}")
        else:
            raise ValueError(
                "No supported LLM provider configured. Set LLM_PROVIDER to 'github' or 'gemini', "
                "and provide credentials via LLM_TOKEN (GitHub) or GEMINI_API_KEY (Gemini)."
            )
        
        self._system_prompt = get_system_prompt("eng", is_rag_prompt=False)
        self._engine = LocalChatEngine(host=host)
        self._query_engine = None
        self._ingestion = LocalDataIngestion()
        self._vector_store = LocalVectorStore(host=host)
        # Defer embedding model loading until needed (when documents are uploaded)
        self._embed_model_loaded = False
        # Keep previous behavior: resolve project_root/data/data.
        self._data_dir = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'data', 'data')
        )
        
        # Initialize query engine with existing documents if available
        if auto_init_docs:
            self._initialize_existing_documents()
    
    def _initialize_existing_documents(self):
        """Load existing documents from database - uses cached embeddings when available"""
        try:
            from rag_chatbot.database import document_manager
            import os
            import time
            
            start_time = time.time()
            
            # Get all company documents from database
            docs = document_manager.get_all_documents()
            
            # Also get personal documents from user_documents table
            personal_docs = self._get_all_personal_documents()
            
            total_docs = len(docs) + len(personal_docs) if docs else len(personal_docs)
            
            if total_docs > 0:
                print(f"[STARTUP] Found {len(docs) if docs else 0} company documents and {len(personal_docs)} personal documents")
                # Documents exist, need to load them (cache will be used if available)
                self._ensure_embed_model()
                
                # Collect all file paths
                file_paths = []
                
                # Company documents
                if docs:
                    for doc in docs:
                        file_path = os.path.join("data/data", doc["filename"])
                        if os.path.exists(file_path):
                            file_paths.append(file_path)
                        else:
                            print(f"[STARTUP] Warning: Company file not found: {file_path}")
                
                # Personal documents
                for doc in personal_docs:
                    file_path = os.path.join("data/data", doc["filename"])
                    if os.path.exists(file_path):
                        file_paths.append(file_path)
                    else:
                        print(f"[STARTUP] Warning: Personal file not found: {file_path}")
                
                if file_paths:
                    print(f"[STARTUP] Loading {len(file_paths)} files (cached embeddings will be used when available)...")
                    # Process all documents at once - caching happens internally
                    all_nodes = self._ingestion.store_nodes(
                        input_files=file_paths,
                        embed_nodes=True,
                        embed_model=Settings.embed_model
                    )
                    
                    if all_nodes:
                        elapsed = time.time() - start_time
                        print(f"[STARTUP] Creating query engine with {len(all_nodes)} total nodes...")
                        # Create query engine with all nodes
                        self._query_engine = self._engine.set_engine(
                            llm=self._default_model,
                            nodes=all_nodes,
                            language=self._language
                        )
                        print(f"[STARTUP] ✓ Documents ready in {elapsed:.1f}s")
                    else:
                        print("[STARTUP] No nodes were extracted from documents")
            else:
                print("[STARTUP] No documents in database - ready for uploads")
        except Exception as e:
            print(f"[STARTUP] Error initializing documents: {e}")
            import traceback
            traceback.print_exc()
    
    def _get_all_personal_documents(self):
        """Get all personal documents from user_documents table"""
        try:
            from rag_chatbot.database import db
            conn = db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT id, filename, original_filename
                FROM user_documents
                WHERE status = 'approved'
            """)
            
            documents = []
            for row in cursor.fetchall():
                documents.append({
                    'id': row[0],
                    'filename': row[1],
                    'original_filename': row[2]
                })
            
            conn.close()
            return documents
        except Exception as e:
            print(f"[STARTUP] Error getting personal documents: {e}")
            return []

    def _ensure_embed_model(self):
        """Load embedding model only when needed"""
        if not self._embed_model_loaded:
            Settings.embed_model = LocalEmbedding.set(host=self._host)
            self._embed_model_loaded = True

    def get_model_name(self):
        return self._model_name

    def set_model_name(self, model_name: str):
        self._model_name = model_name

    def get_language(self):
        return self._language

    def set_language(self, language: str):
        self._language = language

    def get_system_prompt(self):
        return self._system_prompt

    def set_system_prompt(self, system_prompt: str | None = None):
        self._system_prompt = system_prompt or get_system_prompt(
            language=self._language, is_rag_prompt=self._ingestion.check_nodes_exist()
        )

    def set_model(self):
        Settings.llm = self._default_model

    def reset_engine(self):
        self._query_engine = self._engine.set_engine(
            llm=self._default_model, nodes=[], language=self._language
        )

    def reset_documents(self):
        self._ingestion.reset()

    def clear_conversation(self):
        if self._query_engine:
            self._query_engine.reset()

    def reset_conversation(self):
        self.reset_engine()
        self.set_system_prompt(
            get_system_prompt(language=self._language, is_rag_prompt=False)
        )

    def set_embed_model(self, model_name: str):
        Settings.embed_model = LocalEmbedding.set(model_name, self._host)

    def pull_model(self, model_name: str):
        raise NotImplementedError("Local model pulling is not supported (Ollama removed).")

    def pull_embed_model(self, model_name: str):
        return LocalEmbedding.pull(self._host, model_name)

    def check_exist(self, model_name: str) -> bool:
        return False

    def check_exist_embed(self, model_name: str) -> bool:
        return LocalEmbedding.check_model_exist(self._host, model_name)

    def store_nodes(self, input_files: list[str] = None) -> None:
        # Load embedding model when documents are first uploaded
        self._ensure_embed_model()
        self._ingestion.store_nodes(input_files=input_files)

    def set_chat_mode(self, system_prompt: str | None = None):
        self.set_language(self._language)
        self.set_system_prompt(system_prompt)
        self.set_model()
        self.set_engine()

    def set_engine(self):
        nodes = self._ingestion.get_all_nodes()
        if not nodes:
            nodes = self._ingestion.get_ingested_nodes()
        self._query_engine = self._engine.set_engine(
            llm=self._default_model,
            nodes=nodes,
            language=self._language,
        )

    def get_history(self, chatbot: list[list[str]]):
        history = []
        for chat in chatbot:
            if chat[0]:
                history.append(ChatMessage(role=MessageRole.USER, content=chat[0]))
                history.append(ChatMessage(role=MessageRole.ASSISTANT, content=chat[1]))
        return history

    def _load_missing_files(self, missing_files: list[str]) -> list[str]:
        if not missing_files:
            return []

        os.makedirs(self._data_dir, exist_ok=True)
        found_paths = [
            os.path.join(self._data_dir, name)
            for name in missing_files
            if name and os.path.exists(os.path.join(self._data_dir, name))
        ]

        if not found_paths:
            return []

        try:
            self.store_nodes(input_files=found_paths)
            self.set_chat_mode()
            return found_paths
        except Exception as exc:
            print(f"[PIPELINE] Failed to reload missing documents: {exc}")
            return []

    def _build_filtered_engine(self, selected_files: list[str]):
        nodes, missing_files = self._ingestion.get_nodes_for_files(selected_files)
        if missing_files:
            reloaded = self._load_missing_files(missing_files)
            if reloaded:
                nodes, missing_files = self._ingestion.get_nodes_for_files(selected_files)
        if nodes:
            print(
                f"[PIPELINE] Building filtered engine for {len(nodes)} nodes across {len(selected_files)} files"
            )
            filtered_engine = self._engine.set_engine(
                llm=self._default_model,
                nodes=nodes,
                language=self._language,
            )
            return filtered_engine, missing_files
        return None, missing_files

    def query(
        self,
        mode: str,
        message: str,
        chatbot: list[list[str]],
        selected_files: list[str] | None = None,
    ) -> StreamingAgentChatResponse:
        import time
        
        if not self._query_engine:
            raise RuntimeError("No documents loaded. Please upload documents first in the Admin interface.")

        query_engine = self._query_engine
        missing_files: list[str] = []
        if selected_files:
            filtered_engine, missing_files = self._build_filtered_engine(selected_files)
            if missing_files:
                print(f"[PIPELINE] Missing nodes for files: {missing_files}")
            if filtered_engine:
                query_engine = filtered_engine
            else:
                missing_display = ", ".join(missing_files) if missing_files else "the selected documents"
                raise ValueError(
                    f"The system couldn't find the selected documents ({missing_display}). Please refresh the page or contact an administrator."
                )

        start = time.time()
        print(f"[PIPELINE] Starting query: '{message[:50]}...'")
        if selected_files:
            print(f"[PIPELINE] Restricting retrieval to: {selected_files}")

        if mode == "chat":
            history = self.get_history(chatbot)
            result = query_engine.stream_chat(message, history)
        else:
            if hasattr(query_engine, "reset"):
                query_engine.reset()
            result = query_engine.stream_chat(message)
        
        print(f"[PIPELINE] Query engine returned in {time.time() - start:.2f}s")
        return result
