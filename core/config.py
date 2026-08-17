import os
import logging
from dotenv import load_dotenv
from langchain_ollama import ChatOllama, OllamaEmbeddings

os.environ["OLLAMA_NUM_PARALLEL"] = "4"
logging.getLogger("httpx").setLevel(logging.WARNING)

load_dotenv("secure.env")
load_dotenv()


def extract_text(content) -> str:
    """Safely extract plain text from various LangChain message content formats (str, list, dict)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts)
    return str(content)


extractText = extract_text


def get_gemini_key(key_name=None):
    """Retrieve a named Gemini API key.

    Args:
        key_name: "1" for planning agents, "2" for execution agents,
                  or None for the default key.
    """
    if key_name:
        key = os.getenv(f"GEMINI_API_KEY_{key_name}")
        if key:
            return key
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def get_llm(provider=None, model_name=None, temperature=0, api_key=None):
    """Create an LLM instance.

    Args:
        provider:    "gemini", "openai", "anthropic", or None (Ollama fallback).
        model_name:  Override the default model for the provider.
        temperature: Sampling temperature.
        api_key:     Explicit Gemini API key. If None, uses the default key.
    """
    provider = provider or os.getenv("LLM_PROVIDER", "gemini").lower()
    if provider == "gemini":
        model_name = model_name or os.getenv("LLM_MODEL", "gemini-3.5-flash")
        from langchain_google_genai import ChatGoogleGenerativeAI
        resolved_key = api_key or get_gemini_key()
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature, google_api_key=resolved_key)
    elif provider == "openai":
        model_name = model_name or os.getenv("LLM_MODEL", "gpt-4o")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model_name, temperature=temperature)
    elif provider == "anthropic":
        model_name = model_name or os.getenv("LLM_MODEL", "claude-3-5-sonnet-20241022")
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model_name, temperature=temperature)
    else:
        model_name = model_name or os.getenv("LLM_MODEL", "qwen2.5-coder:7b")
        return ChatOllama(model=model_name, temperature=temperature, num_thread=4)


def get_embeddings(provider=None):
    provider = provider or os.getenv("LLM_PROVIDER", "gemini").lower()
    if provider == "gemini":
        from langchain_google_genai import GoogleGenerativeAIEmbeddings
        api_key = get_gemini_key("2")
        return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=api_key)
    elif provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings()
    else:
        return OllamaEmbeddings(model="qwen2.5-coder:7b")


embeddings = get_embeddings()
llm = get_llm(api_key=get_gemini_key("2"))