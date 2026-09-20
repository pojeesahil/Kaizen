import os
import re
from pathlib import Path

INTENT_PROMPT = """You are a software project assistant. A developer typed an instruction into a coding tool.
Your only job is to decide if the instruction is asking to:
- "patch": fix, adjust, or improve something that already exists in the project
- "build": create a new feature, file, or project from scratch

Reply with a single lowercase word: patch or build

Examples:
- "fix the dialogue system" → patch
- "the NPC movement is broken" → patch
- "player health doesn't reset on death" → patch
- "build a snake game in python" → build
- "create a login page" → build
- "implement a quest tracker" → build
- "add dark mode to the existing UI" → patch
- "start a new react app" → build

Instruction: {instruction}

Reply:"""

def classifyIntent(instruction: str) -> str:
    from core.config import get_llm, get_gemini_key, extract_text
    llm = get_llm(api_key=get_gemini_key("1"), temperature=0)
    promptText = INTENT_PROMPT.format(instruction=instruction.strip())
    response = llm.invoke(promptText)
    rawText = extract_text(response.content if hasattr(response, "content") else response)
    tokens = rawText.strip().lower().split()
    for token in tokens:
        cleaned = re.sub(r"[^\w]", "", token)
        if cleaned in ("patch", "build"):
            return cleaned
    return "build"


def readWorkspaceFiles(workDir: Path, maxBytes: int = 60000) -> str:
    if not workDir.exists():
        return ""

    supportedExts = {
        ".py", ".js", ".ts", ".java", ".html", ".css", ".json",
        ".jsx", ".tsx", ".go", ".cpp", ".c", ".h", ".yaml", ".yml",
        ".md", ".txt", ".svg", ".toml", ".ini"
    }
    skipDirs = {
        "node_modules", "__pycache__", "venv", ".git", ".venv",
        "chroma_db", "graphify-out", "dist", "build", ".next",
        ".nuxt", ".cache", "coverage", "DAG"
    }
    skipFiles = {
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml",
        "composer.lock", "cargo.lock", "poetry.lock"
    }

    accumulated = []
    totalBytes = 0

    for root, dirs, files in os.walk(workDir):
        dirs[:] = sorted(
            d for d in dirs
            if d not in skipDirs and not d.startswith(".")
        )
        for fname in sorted(files):
            if totalBytes >= maxBytes:
                break
            if fname in skipFiles:
                continue
            if fname.endswith((".min.js", ".min.css", ".map", ".pack")):
                continue

            ext = os.path.splitext(fname)[1].lower()
            if ext not in supportedExts:
                continue

            fpath = os.path.join(root, fname)
            size = os.path.getsize(fpath)
            if size > 80000:
                continue

            relpath = os.path.relpath(fpath, workDir)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as handle:
                    content = handle.read(40000)
                if content.strip():
                    snippet = f"--- {relpath} ---\n{content}"
                    accumulated.append(snippet)
                    totalBytes += len(snippet)
            except Exception:
                continue

    return "\n\n".join(accumulated)


def buildPatchInstruction(userInstruction: str, workDir: Path) -> str:
    workspaceSnapshot = readWorkspaceFiles(workDir)

    parts = [
        "PATCH MODE - Do NOT rebuild from scratch.",
        "Read the relevant existing files first using readFile, then make only the targeted changes needed.",
        "Never regenerate files that are already working.",
        "",
        f"User instruction: {userInstruction.strip()}",
    ]

    if workspaceSnapshot:
        parts.append("")
        parts.append("Current workspace files:")
        parts.append(workspaceSnapshot)

    return "\n".join(parts)
