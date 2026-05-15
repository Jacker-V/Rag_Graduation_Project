from llama_index.core.llms import CustomLLM, CompletionResponse, CompletionResponseGen, LLMMetadata
from llama_index.core.llms.callbacks import llm_completion_callback
from typing import Any, Optional
from azure.ai.inference import ChatCompletionsClient
from azure.ai.inference.models import SystemMessage, UserMessage
from azure.core.credentials import AzureKeyCredential
from rag_chatbot.utils.llm_resilience import run_with_retries


class GitHubLLM(CustomLLM):
    """Custom LLM for GitHub Models API using Azure AI Inference SDK"""
    
    model: str = "gpt-4o-mini"
    api_token: str = ""
    endpoint: str = "https://models.github.ai/inference"
    temperature: float = 0.1
    max_tokens: int = 1000
    context_window: int = 128000
    
    @property
    def metadata(self) -> LLMMetadata:
        return LLMMetadata(
            context_window=self.context_window,
            num_output=self.max_tokens,
            model_name=self.model,
        )
    
    @llm_completion_callback()
    def complete(self, prompt: str, **kwargs: Any) -> CompletionResponse:
        client = ChatCompletionsClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.api_token),
        )

        response = run_with_retries(
            lambda: client.complete(
                messages=[
                    SystemMessage("You are a helpful AI assistant."),
                    UserMessage(prompt),
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                model=self.model,
            )
        )
        
        return CompletionResponse(text=response.choices[0].message.content)
    
    @llm_completion_callback()
    def stream_complete(self, prompt: str, **kwargs: Any) -> CompletionResponseGen:
        client = ChatCompletionsClient(
            endpoint=self.endpoint,
            credential=AzureKeyCredential(self.api_token),
        )

        response = run_with_retries(
            lambda: client.complete(
                messages=[
                    SystemMessage("You are a helpful AI assistant."),
                    UserMessage(prompt),
                ],
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                model=self.model,
                stream=True,
            )
        )
        
        def gen():
            text = ""
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    delta = chunk.choices[0].delta.content
                    text += delta
                    yield CompletionResponse(text=text, delta=delta)
        
        return gen()


class LocalRAGModel:
    def __init__(self) -> None:
        pass

    @staticmethod
    def set(
        model_name: str = "",
        system_prompt: str | None = None,
        host: str = "localhost",
        setting: Any | None = None,
    ):
        raise NotImplementedError(
            "LocalRAGModel (Ollama/OpenRouter/OpenAI) has been removed. "
            "Use GitHubLLM or GeminiLLM via LLM_PROVIDER=github|gemini."
        )

    @staticmethod
    def pull(host: str, model_name: str):
        raise NotImplementedError("Model pulling is not supported (Ollama removed).")

    @staticmethod
    def check_model_exist(host: str, model_name: str) -> bool:
        return False
