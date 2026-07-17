from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

WORKSPACE_DIR = Path(os.getenv("WORKSPACE", BASE_DIR/"workspace"))

VECTOR_DB_DIR = Path(os.getenv("CHROMA_DB", BASE_DIR/"chroma_db"))

MODEL_NAME = os.getenv("MODEL_NAME", "qwen2.5-coder:7b")

EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")

SUPPORTED_EXTENSIONS = [
    ".py",
    ".cpp",
    ".c",
    ".hpp",
    ".h",
    ".java",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".md",
    ".txt"
]

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200

TOP_K = 5

MAX_TOKENS = 4000

TEMPERATURE = 0

IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    "chroma_db"
}