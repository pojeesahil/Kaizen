import os
import logging
from dotenv import load_dotenv
from langchain_ollama import ChatOllama, OllamaEmbeddings

os.environ["OLLAMA_NUM_PARALLEL"] = "4"
logging.getLogger("httpx").setLevel(logging.WARNING)

load_dotenv("secure.env")
load_dotenv()

def get_llm(provider=None, model_name=None, temperature=0):
    provider = provider or os.getenv("LLM_PROVIDER", "gemini").lower()
    if provider == "gemini":
        model_name = model_name or os.getenv("LLM_MODEL", "gemini-flash-latest")
        from langchain_google_genai import ChatGoogleGenerativeAI
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        return ChatGoogleGenerativeAI(model=model_name, temperature=temperature, google_api_key=api_key)
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
        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=api_key)
    elif provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings()
    else:
        return OllamaEmbeddings(model="qwen2.5-coder:7b")


embeddings = get_embeddings()
llm = get_llm()