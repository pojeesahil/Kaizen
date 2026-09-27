import os
import logging
import warnings
from dotenv import load_dotenv
from langchain_ollama import ChatOllama, OllamaEmbeddings
from pathlib import Path

warnings.filterwarnings("ignore")
os.environ["OLLAMA_NUM_PARALLEL"] = "4"
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("langchain_google_genai").setLevel(logging.ERROR)
logging.getLogger("langchain_google_vertexai").setLevel(logging.ERROR)

load_dotenv("secure.env")
load_dotenv(".env.gcp")
load_dotenv()

autoApprove = os.getenv("AUTO_APPROVE", "false").lower() in ("true", "1", "yes")
AUTO_APPROVE = autoApprove

gCreds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
if gCreds:
    credsPath = Path(gCreds)
    if not credsPath.is_absolute():
        credsPath = (Path(__file__).resolve().parent.parent / gCreds).resolve()
    if credsPath.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(credsPath)
    else:
        del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]


def extract_text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            else:
                parts.append(str(block))
        return "\n".join(parts)
    return str(content)


extractText = extract_text


def get_gemini_key(key_name=None):
    if key_name:
        key = os.getenv(f"GEMINI_API_KEY_{key_name}")
        if key:
            return key
    return os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")


def sanitize_messages(messages):
    """
    Sanitizes a message or list of messages for LLM invocations.
    Ensures every message has non-empty content and non-empty parts, preventing
    'INVALID_ARGUMENT: Unable to submit request because it must include at least one parts field' errors.
    """
    if messages is None:
        return "[Empty prompt]"
    if isinstance(messages, str):
        cleaned = messages.strip()
        return cleaned if cleaned else "[Empty prompt]"
    if not isinstance(messages, list):
        return messages

    sanitized = []
    for m in messages:
        if isinstance(m, str):
            clean_str = m.strip() if m else ""
            sanitized.append(clean_str if clean_str else "[Empty message]")
            continue

        content = getattr(m, "content", "")
        has_tool_calls = bool(
            getattr(m, "tool_calls", None)
            or getattr(m, "invalid_tool_calls", None)
            or (hasattr(m, "additional_kwargs") and isinstance(m.additional_kwargs, dict) and m.additional_kwargs.get("function_call"))
        )

        is_empty = False
        if content is None:
            is_empty = True
        elif isinstance(content, str) and not content.strip():
            is_empty = True
        elif isinstance(content, list) and len(content) == 0:
            is_empty = True

        if is_empty and not has_tool_calls:
            try:
                m.content = "[No text content]"
            except Exception:
                pass
        sanitized.append(m)

    return sanitized


class SanitizedLLM:
    def __init__(self, inner):
        self._inner = inner

    def stream(self, input, *args, **kwargs):
        return self._inner.stream(sanitize_messages(input), *args, **kwargs)

    def invoke(self, input, *args, **kwargs):
        return self._inner.invoke(sanitize_messages(input), *args, **kwargs)

    def bind_tools(self, tools, *args, **kwargs):
        bound = self._inner.bind_tools(tools, *args, **kwargs)
        return SanitizedLLM(bound)

    def __getattr__(self, name):
        return getattr(self._inner, name)


def get_llm(provider=None, model_name=None, temperature=0, api_key=None):
    provider = provider or os.getenv("LLM_PROVIDER", "gemini").lower()
    if provider in ("vertex", "vertexai"):
        from langchain_google_vertexai import ChatVertexAI
        model_name = model_name or os.getenv("LLM_MODEL", "gemini-2.5-flash")
        key_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
        if key_path and os.path.exists(key_path):
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = os.path.abspath(key_path)
        elif key_path and not os.path.exists(key_path):
            del os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
        raw_llm = ChatVertexAI(
            model_name=model_name,
            project=os.getenv("GOOGLE_CLOUD_PROJECT"),
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            temperature=temperature,
        )
    elif provider == "gemini":
        model_name = model_name or os.getenv("LLM_MODEL", "gemini-2.5-flash")
        from langchain_google_genai import ChatGoogleGenerativeAI
        resolved_key = api_key or get_gemini_key()
        raw_llm = ChatGoogleGenerativeAI(model=model_name, temperature=temperature, google_api_key=resolved_key)
    elif provider == "openai":
        model_name = model_name or os.getenv("LLM_MODEL", "gpt-4o")
        from langchain_openai import ChatOpenAI
        raw_llm = ChatOpenAI(model=model_name, temperature=temperature)
    elif provider == "anthropic":
        model_name = model_name or os.getenv("LLM_MODEL", "claude-3-5-sonnet-20241022")
        from langchain_anthropic import ChatAnthropic
        raw_llm = ChatAnthropic(model=model_name, temperature=temperature)
    else:
        model_name = model_name or os.getenv("LLM_MODEL", "qwen2.5-coder:7b")
        raw_llm = ChatOllama(model=model_name, temperature=temperature, num_thread=4)

    return SanitizedLLM(raw_llm)


def get_embeddings(provider=None):
    provider = provider or os.getenv("LLM_PROVIDER", "vertexai").lower()
    if provider in ("vertex", "vertexai"):
        try:
            from langchain_google_vertexai import VertexAIEmbeddings
            return VertexAIEmbeddings(
                model_name="text-embedding-004",
                project=os.getenv("GOOGLE_CLOUD_PROJECT"),
                location=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
            )
        except Exception:
            pass
    elif provider == "gemini":
        apiKey = get_gemini_key("2") or get_gemini_key()
        if apiKey:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings
            return GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=apiKey)
    elif provider == "openai":
        from langchain_openai import OpenAIEmbeddings
        return OpenAIEmbeddings()
    return OllamaEmbeddings(model="qwen2.5-coder:7b")


embeddings = get_embeddings()
llm = get_llm()