import os
import logging
from dotenv import load_dotenv
from langchain_ollama import ChatOllama, OllamaEmbeddings

logging.getLogger("httpx").setLevel(logging.WARNING)

load_dotenv("secure.env")
load_dotenv()

def get_llm(provider=None, model_name=None, temperature=0):
    provider = provider or os.getenv("LLM_PROVIDER", "ollama").lower()
    model_name = model_name or os.getenv("LLM_MODEL", "qwen2.5-coder:7b")
    if provider == "openai":
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=temperature)
    elif provider == "anthropic":
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name, temperature=temperature)
    elif provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature)
    else:
        return ChatOllama(model=model_name, temperature=temperature)

embeddings = OllamaEmbeddings(model="qwen2.5-coder:7b")
llm = get_llm()