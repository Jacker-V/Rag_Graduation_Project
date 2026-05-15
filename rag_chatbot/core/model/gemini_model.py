"""
Gemini API adapter for RAG system
Provides a bridge between llama-index and Google's Gemini API
"""
from google import genai
from llama_index.core.llms import CustomLLM, CompletionResponse, CompletionResponseGen, LLMMetadata
from llama_index.core.llms.callbacks import llm_completion_callback
from typing import Any, Optional
from rag_chatbot.utils.llm_resilience import run_with_retries


class GeminiLLM(CustomLLM):
    """Gemini API wrapper for llama-index"""
    
    model: str = "gemini-2.5-flash"
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 2000
    
    class Config:
        arbitrary_types_allowed = True
    
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", **kwargs):
        super().__init__(api_key=api_key, model=model, **kwargs)
        # Initialize client after calling super().__init__
        object.__setattr__(self, '_client', genai.Client(api_key=api_key))
    
    @property
    def client(self):
        """Get the Gemini client"""
        if not hasattr(self, '_client'):
            object.__setattr__(self, '_client', genai.Client(api_key=self.api_key))
        return self._client
    
    @property
    def metadata(self) -> LLMMetadata:
        """LLM metadata."""
        return LLMMetadata(
            context_window=1000000,  # Gemini 2.0 Flash has 1M token context
            num_output=self.max_tokens,
            model_name=self.model,
            is_chat_model=True,
        )
    
    @llm_completion_callback()
    def complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        """Completion endpoint for Gemini."""
        try:
            response = run_with_retries(
                lambda: self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
            )
            return CompletionResponse(text=response.text)
        except Exception as e:
            print(f"Gemini API error: {e}")
            return CompletionResponse(text=f"Error: {str(e)}")
    
    @llm_completion_callback()
    def stream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponseGen:
        """Streaming completion endpoint for Gemini."""
        try:
            response = run_with_retries(
                lambda: self.client.models.generate_content_stream(
                    model=self.model,
                    contents=prompt,
                )
            )
            
            def gen():
                text = ""
                for chunk in response:
                    if chunk.text:
                        text += chunk.text
                        yield CompletionResponse(text=text, delta=chunk.text)
            
            return gen()
        except Exception as e:
            print(f"Gemini API streaming error: {e}")
            def error_gen():
                yield CompletionResponse(text=f"Error: {str(e)}")
            return error_gen()
    
    def chat(self, messages, **kwargs):
        """Chat endpoint for Gemini."""
        from llama_index.core.base.llms.types import ChatResponse, ChatMessage as LLMChatMessage
        
        # Convert messages to Gemini format
        prompt_parts = []
        for msg in messages:
            if hasattr(msg, 'role') and hasattr(msg, 'content'):
                role = msg.role
                content = msg.content
            else:
                role = 'user'
                content = str(msg)
            prompt_parts.append(f"{role}: {content}")
        
        prompt = "\n".join(prompt_parts)
        
        try:
            response = run_with_retries(
                lambda: self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                )
            )
            return ChatResponse(
                message=LLMChatMessage(role="assistant", content=response.text),
                raw=response
            )
        except Exception as e:
            print(f"Gemini chat error: {e}")
            return ChatResponse(
                message=LLMChatMessage(role="assistant", content=f"Error: {str(e)}"),
                raw=None
            )
    
    def stream_chat(self, messages, **kwargs):
        """Streaming chat endpoint for Gemini."""
        from llama_index.core.base.llms.types import ChatResponse, ChatMessage as LLMChatMessage
        
        # Convert messages to Gemini format
        prompt_parts = []
        for msg in messages:
            if hasattr(msg, 'role') and hasattr(msg, 'content'):
                role = msg.role
                content = msg.content
            else:
                role = 'user'
                content = str(msg)
            prompt_parts.append(f"{role}: {content}")
        
        prompt = "\n".join(prompt_parts)
        
        try:
            response = run_with_retries(
                lambda: self.client.models.generate_content_stream(
                    model=self.model,
                    contents=prompt,
                )
            )
            
            def gen():
                text = ""
                for chunk in response:
                    if chunk.text:
                        text += chunk.text
                        yield ChatResponse(
                            message=LLMChatMessage(role="assistant", content=text),
                            delta=chunk.text,
                            raw=chunk
                        )
            
            return gen()
        except Exception as e:
            print(f"Gemini stream chat error: {e}")
            def error_gen():
                yield ChatResponse(
                    message=LLMChatMessage(role="assistant", content=f"Error: {str(e)}"),
                    raw=None
                )
            return error_gen()
