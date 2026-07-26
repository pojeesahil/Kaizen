import os
import logging
from dotenv import load_dotenv
from langchain_ollama import ChatOllama, OllamaEmbeddings

logging.getLogger("httpx").setLevel(logging.WARNING)

load_dotenv("secure.env")

embeddings = OllamaEmbeddings(model="qwen2.5-coder:7b")
llm = ChatOllama(model="qwen2.5-coder:7b", temperature=0)