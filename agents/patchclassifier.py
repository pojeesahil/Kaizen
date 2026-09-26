import os
import re
from pathlib import Path

INTENT_PROMPT = """You are an intelligent software development assistant. A developer gave an instruction in the workspace.
Decide if this instruction should be handled by:
- "direct": an operational task, tool action (git clone, pull, push, status, command, web search), inspection, query, bugfix, or modifying code in an existing project.
- "build": architecting and generating a brand new multi-module software project from complete scratch (e.g. building an entire game or full-stack application from zero).

Reply with a single lowercase word: direct or build

Examples:
- "pull data from my github from repo javatest" → direct
- "clone the repo" → direct
- "fix the dialogue system" → direct
- "check git status" → direct
- "add a helper function to utils.py" → direct
- "build a complete 2d minecraft game in java from scratch" → build
- "create a full-stack e-commerce web app in react and node from scratch" → build
- "start a brand new chess game in python from zero" → build

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
        if cleaned in ("direct", "patch", "build"):
            return "direct" if cleaned in ("direct", "patch") else "build"
    return "direct"


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
    from agents.github_mcp import getAuthenticatedUser
    authUser = getAuthenticatedUser()

    parts = [
        "DIRECT EXECUTION MODE - Execute the user instruction directly using your tools.",
        f"Connected GitHub Account: {authUser}" if authUser else "",
        "WORKSPACE BOUNDARY: All file creations, git clones, and modifications MUST strictly be located inside the 'work' directory.",
        "When cloning an external repository, clone directly into the workspace root (e.g. 'git clone <url> .') or inside work/.",
        "You have access to file tools, shell execution, and GitHub MCP tools (github_*).",
        "For coding tasks, use readFile, createFile, editFile, and replaceBlock for targeted modifications.",
        "",
        f"User instruction: {userInstruction.strip()}",
    ]
    parts = [p for p in parts if p]

    if workspaceSnapshot:
        parts.append("")
        parts.append("Current workspace files:")
        parts.append(workspaceSnapshot)

    return "\n".join(parts)
