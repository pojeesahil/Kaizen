import os
import shutil
import re
import time
import json
import hashlib
import asyncio
from pathlib import Path
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from core.config import llm, get_llm
from core.tools import (
    tools,
    createFile,
    createFiles,
    editFile,
    upsertFunction,
    upsertClass,
    appendToFile,
    replaceBlock,
    deleteResource,
    readFile,
    grepFiles,
    searchWeb,
    downloadAsset,
    moveFile,
    finishTask,
    executeCommand,
    executor,
    WORK_DIR
)
from core.connectedness import formatManifestContext, validateConnectedness, autoFixImports
from cag.cag import (
    loadCag,
    getCagContext,
    updateCagFile,
    getCoderContext,
    indexWorkspace,
    getContext,
    updateWorkspaceFile
)
from agents.prompt import PromptAgent
from agents.planneragent import PlannerAgent
from agents.patchclassifier import classifyIntent, buildPatchInstruction
from agents.dag import DAG
from agents.scheduler import Scheduler
from agents.hitl import HITLReview, reviewDeliverables
from agents.githubagent import GitHubAgent
from core.memory import MemoryManager
from core.logger import startLogging

os.environ["OLLAMA_NUM_PARALLEL"] = "4"

memoryManager = MemoryManager()
gitHubAgent = GitHubAgent(WORK_DIR)
verifiedManifestHashes = {}

def shouldRetrieveMemory(instruction: str) -> bool:
    instructionLower = instruction.lower().strip()
    if len(instructionLower) < 15:
        return False
    greetings = {"hello", "hi", "hey", "good morning", "good afternoon", "how are you"}
    if any(instructionLower == g or instructionLower.startswith(g + " ") for g in greetings):
        return False
    keywords = {
        "fix", "error", "fail", "test", "debug", "auth", "jwt", "database", "db", 
        "run", "compile", "dependency", "import", "package", "config", "convention",
        "style", "preference", "success", "failure", "lesson", "build"
    }
    return any(word in instructionLower for word in keywords)


def extractText(content) -> str:
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

def sanitizeCommand(cmd: str) -> str:
    cmd = re.sub(r'(?<=\s)work[/\\]', '', cmd)
    cmd = re.sub(r'^work[/\\]', '', cmd)

    if cmd.strip().startswith("pytest ") or "&& pytest " in cmd or "; pytest " in cmd:
        cmd = re.sub(r'(^|\b&&?\s*)pytest\b', r'\1python -m pytest', cmd)

    if "pip install" in cmd:
        stdLibs = {"unittest", "sys", "os", "json", "math", "re", "asyncio", "sqlite3", "time", "typing", "collections"}
        parts = cmd.split("&&")
        cleanedParts = []
        for part in parts:
            if "pip install" in part:
                tokens = part.split()
                filtered = [tok for tok in tokens if tok.lower() not in stdLibs]
                if len(filtered) > 2:
                    cleanedParts.append(" ".join(filtered))
            else:
                cleanedParts.append(part)
        return " && ".join(cleanedParts) if cleanedParts else "echo Standard library module available by default"
    return cmd

def extractCommand(toolRecord: str) -> str:
    if "command='" in toolRecord:
        return toolRecord.split("command='", 1)[1].split("'", 1)[0].strip()
    if 'command="' in toolRecord:
        return toolRecord.split('command="', 1)[1].split('"', 1)[0].strip()
    return ""

def isSetupCommand(cmd: str) -> bool:
    lowerCmd = cmd.lower().strip()
    if any(lowerCmd.startswith(p) for p in ("echo ", "cat ", "type ", "head ", "tail ", "dir", "ls")):
        return True
    cleaned = lowerCmd.replace("-", " ").replace("=", " ").replace(";", " ")
    tokens = cleaned.split()
    execWords = {
        "test",
        "tests",
        "build",
        "start",
        "run",
        "serve",
        "server",
        "exec",
        "bench",
        "benchmark",
        "check",
        "compile",
        "dev"
    }
    for w in execWords:
        if w in tokens:
            return False
    setupWords = {
        "install",
        "add",
        "get",
        "update",
        "upgrade",
        "download",
        "sync",
        "ci",
        "fetch",
        "version",
        "which",
        "where"
    }
    for w in setupWords:
        if w in tokens:
            return True
    pkgManagers = {"npm", "yarn", "pnpm", "pip", "pip3", "cargo", "gem", "bundle"}
    for idx, token in enumerate(tokens):
        if token in pkgManagers:
            if idx + 1 < len(tokens):
                nextToken = tokens[idx + 1]
                if nextToken in {"i", "setup"}:
                    return True
            else:
                return True
    return False


def executeToolCalls(response, toolsList):
    toolMap = {t.name: t for t in toolsList}
    executed = []
    rawCalls = []
    try:
        if isinstance(response.tool_calls, list):
            rawCalls = response.tool_calls
    except Exception:
        rawCalls = []
    if rawCalls:
        for tc in rawCalls:
            tname = tc.get("name")
            if isinstance(tname, dict):
                tname = tname.get("name")
            targs = tc.get("args", {})
            if not isinstance(targs, dict):
                targs = {}
            if isinstance(tname, str) and tname in toolMap:
                try:
                    if tname in ("executeCommand", "executor") and "command" in targs:
                        targs["command"] = sanitizeCommand(targs["command"])
                    res = toolMap[tname].invoke(targs)
                    if tname in ("executeCommand", "executor"):
                        executed.append(f"Tool {tname} executed: command='{targs.get('command', '')}' | {res}")
                    else:
                        executed.append(f"Tool {tname} executed: {res}")
                except Exception as err:
                    executed.append(f"Tool {tname} execution error: {err}")
    if not executed:
        text = extractText(response.content).strip()
        decoder = json.JSONDecoder(strict=False)
        idx = 0
        while idx < len(text):
            start = text.find("{", idx)
            if start == -1:
                break

            data = None
            endOffset = 0

            try:
                data, endOffset = decoder.raw_decode(text[start:])
            except Exception:
                sub = text[start:]
                cleanedSub = re.sub(r"(?<!\\)\\'", "'", sub)
                try:
                    data, endOffset = decoder.raw_decode(cleanedSub)
                except Exception:
                    pass

            if data and isinstance(data, dict):
                tname = data.get("name")
                if isinstance(tname, dict):
                    tname = tname.get("name") or tname.get("function", {}).get("name")
                targs = data.get("arguments") or data.get("args") or {}
                if not tname and "summary" in data:
                    tname = "finishTask"
                    targs = {"summary": data.get("summary")}
                if isinstance(targs, str):
                    try:
                        targs = json.loads(targs)
                    except Exception:
                        targs = {}
                if not isinstance(targs, dict):
                    targs = {}
                if isinstance(tname, str) and tname in toolMap:
                    try:
                        if tname in ("executeCommand", "executor") and "command" in targs:
                            targs["command"] = sanitizeCommand(targs["command"])
                        res = toolMap[tname].invoke(targs)
                        if tname in ("executeCommand", "executor"):
                            executed.append(f"Tool {tname} executed: command='{targs.get('command', '')}' | {res}")
                        else:
                            executed.append(f"Tool {tname} executed: {res}")
                    except Exception as err:
                        executed.append(f"Tool {tname} execution error: {err}")
                idx = start + max(endOffset, 1)
            else:
                idx = start + 1

    return executed

coderTools = [
    createFile,
    createFiles,
    editFile,
    upsertFunction,
    upsertClass,
    appendToFile,
    replaceBlock,
    deleteResource,
    readFile,
    grepFiles,
    searchWeb,
    downloadAsset,
    moveFile,
    finishTask,
    executor
]
from core.mcp import getMcpTools
coderTools.extend(getMcpTools())
testerTools = [
    executeCommand
]
coderModel = llm.bind_tools(coderTools)
testerModel = llm.bind_tools(testerTools)
agentModel = llm.bind_tools(tools)

def streamInvoke(model, messages):
    fullResponse = None
    for chunk in model.stream(messages):
        if chunk.content:
            cleanChunk = extractText(chunk.content)
            if cleanChunk:
                print(cleanChunk, end="", flush=True)
        fullResponse = chunk if fullResponse is None else fullResponse + chunk
    print("\n")
    return fullResponse

class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    instruction: str
    taskContext: str
    context: str
    feedback: str
    iteration: int
    success: bool
    coderMessage: str
    toolResults: list
    memories: list
    isAssetOnly: bool


def coderNode(state: AgentState) -> dict:
    iteration = state["iteration"] + 1
    time.sleep(0.5)
    print(f"\nCoder iteration {iteration}")

    instLower = state["instruction"].lower()
    taskContextLower = state.get("taskContext", "").lower()
    combinedText = f"{instLower} {taskContextLower}"

    filesInWork = [
        f for f in WORK_DIR.glob("*")
        if f.name != "node_modules" and not f.name.startswith(".")
    ] if WORK_DIR.exists() else []
    exts = {f.suffix.lower() for f in filesInWork if f.is_file()}

    targetStackMatch = re.search(r"target tech stack:\s*([^\n]+)", combinedText, re.IGNORECASE)
    projStack = targetStackMatch.group(1).lower() if targetStackMatch else ""

    if projStack:
        if any(w in projStack for w in ("python", "pygame", "streamlit", "flask", "django", "fastapi")):
            langGuideline = "Tech Stack: Python 3. Standard Python syntax. All files in the workspace MUST be pure Python (.py). Never generate C++, Java, or JS files."
        elif any(w in projStack for w in ("html", "css", "react", "vue", "frontend", "website", "web app", "spa")):
            langGuideline = "Tech Stack: HTML5 / CSS3 / JavaScript. Build a standalone runnable web application with 'index.html' at the root as the main entrypoint, linked CSS, and browser-compatible JavaScript (DOM manipulation or ES Modules). Do NOT write unbundled React JSX with require()."
        elif any(w in projStack for w in ("node", "express", "backend")):
            langGuideline = "Tech Stack: Node.js / Express (CJS). Use require() and module.exports with server.js or app.js entrypoint."
        elif any(w in projStack for w in ("c++", "cpp", "c language")):
            langGuideline = "Tech Stack: C / C++. Use standard headers (#include), header guards, and int main()."
        elif any(w in projStack for w in ("go", "golang")):
            langGuideline = "Tech Stack: Go. Use standard package declarations, imports, and func main()."
        elif any(w in projStack for w in ("java",)):
            langGuideline = "Tech Stack: Java. Class name must match filename with public static void main(String[] args)."
        else:
            langGuideline = f"Tech Stack: {projStack}. Build all files strictly adhering to {projStack} standards."
    elif any(w in combinedText for w in ("website", "frontend", "html", "css", "ecommerce", "landing page", "web app")) or any(e in (".html", ".css") for e in exts):
        langGuideline = "Tech Stack: HTML5 / CSS3 / JavaScript. Build a standalone runnable web application with 'index.html' at the root as the main entrypoint, linked CSS, and browser-compatible JavaScript (DOM manipulation or ES Modules). Do NOT write unbundled React JSX with require()."
    elif "python" in combinedText or any(e == ".py" for e in exts):
        langGuideline = "Tech Stack: Python 3. Standard Python syntax. Place 'if __name__ == \"__main__\": main()' at entrypoints."
    elif any(e in (".js", ".ts") for e in exts) or any(w in combinedText for w in ("node", "express", "backend", "server")):
        langGuideline = "Tech Stack: Node.js / Express (CJS). Use require() and module.exports with server.js or app.js entrypoint."
    elif any(e == ".go" for e in exts) or re.search(r"\bgolang\b|\bgo language\b", combinedText):
        langGuideline = "Tech Stack: Go. Use standard package declarations, imports, and func main()."
    elif any(e in (".c", ".cpp", ".cc", ".h", ".hpp") for e in exts) or any(w in combinedText for w in ("c++", "cpp", "gcc", "g++", "c language")):
        langGuideline = "Tech Stack: C / C++. Use standard headers (#include), header guards, and int main()."
    elif any(e == ".java" for e in exts) or re.search(r"\bjava\b", combinedText):
        langGuideline = "Tech Stack: Java. Class name must match filename with public static void main(String[] args)."
    else:
        langGuideline = "Tech Stack: Python 3. Standard Python syntax. Place 'if __name__ == \"__main__\": main()' at entrypoints."

    taskContext = state.get("taskContext", "") or "None"
    feedbackContext = state.get("feedback", "") or "None"
    workspaceContext = state.get("context", "") or "None"
    initialAst = formatManifestContext(WORK_DIR)
    memoriesList = state.get("memories", [])
    memoriesStr = "\n".join(f"- {m}" for m in memoriesList) if memoriesList else "None"

    targetFilesMatch = re.search(r"planned file structure:\s*([^\n]+)", combinedText, re.IGNORECASE)
    fileLayoutRule = f" Target Layout: {targetFilesMatch.group(1).strip()}. Follow this exact file structure." if targetFilesMatch else ""

    isPatchMode = state["instruction"].strip().startswith("PATCH MODE")
    patchModeDirective = ""
    if isPatchMode:
        patchModeDirective = (
            "\nPATCH MODE ACTIVE:\n"
            "- You can create new files using createFile or createFiles whenever new assets, files, or components are needed.\n"
            "- For existing files, inspect them with readFile first and make targeted edits using editFile or replaceBlock.\n"
            "- Leave all other working code untouched.\n"
        )

    coderPretext = f"""You are a senior software engineer working in a multi-file workspace.
Your goal is to produce complete, connected, buildable, and runnable code.
{patchModeDirective}
You operate in an Action-driven loop:
1. Every turn, directly invoke the necessary tool (createFile, createFiles, editFile, upsertFunction, upsertClass, appendToFile, replaceBlock, readFile, grepFiles, searchWeb, downloadAsset, moveFile, finishTask, executor) to inspect or modify code.
2. When creating multiple related files (such as SVGs, models, or configurations), use 'createFiles' to write all files together in a single batch call.
3. Use 'grepFiles' to quickly locate symbols, functions, or text across files without reading entire files.
4. Never output conversational plans or text like 'I will also need to add...'. Execute the action via tool calls immediately.
5. After each tool execution, you will observe the tool output and the updated live AST Symbol Registry.
6. Explicit Task Completion: As soon as all files, imports, and requirements for the current task are fully in place, call 'finishTask(summary=...)' to conclude your work.

RULES:
1. Always write production-grade, modular, maintainable code with clear separation of concerns.
2. Split features into logical files/modules by responsibility; never put unrelated logic into one large file.
3. Keep UI, business logic, API/services, data access, types, validation, and utilities separated where appropriate.
Reuse existing modules, avoid duplication/circular dependencies, and don't over-engineer with unnecessary abstractions.
4. Call tools directly. Do not narrate or list planned edits in conversational text.
5. File Operations:
   - Use 'createFile' for a single new file, or 'createFiles' to write multiple files in one turn.
   - Use 'downloadAsset' to download assets or binary files from URLs.
   - Use 'moveFile' to move or rename files or directories from one path to another.
   - Use 'grepFiles' to find exact occurrences of functions, routes, and variables across the project.
   - Use 'editFile', 'upsertFunction', 'upsertClass', 'appendToFile', or 'replaceBlock' to update existing files without breaking unrelated code.
   - To add or modify imports in any language, use 'replaceBlock' to insert or update import statements near existing imports, or use 'editFile'.
   - Use 'executor' ONLY when code or project scaffolding can be generated via CLI (such as Vite setup or project templates). Do NOT use 'executor' for normal coding, file edits, reading files, or running tests.
6. ALWAYS UPDATE DEPENDENT FILES:
   - Whenever you add, rename, or modify a function, class, method, route, or export in one file, you MUST immediately update all dependent files (caller functions, import/require statements, routes, and server entrypoints) in the same response so the entire project remains connected and working.
7. Completeness & Quality:
   - Provide complete, working implementations (no stubs, placeholders, or TODO comments).
   - Do NOT hardcode secrets or API keys; use environment variables with fallback defaults.
8. SIGNATURE MATCHING:
   - Before calling ANY constructor or function, use 'readFile' to check the existing file and match the EXACT parameter names and order already defined.
   - When upsertClass modifies a class, also update ALL standalone code below it (like if __name__ blocks) that instantiates that class so arguments stay in sync.
9. FILE TARGETING:
   - Only modify files directly relevant to your current task objective. Do NOT touch unrelated files unless updating their imports/calls to match your changes.
10. SINGLE SOURCE OF TRUTH & DYNAMIC DERIVATION:
   - NEVER hardcode arbitrary geometric coordinates, entity start positions, screen boundaries, or tile counts across disconnected files.
   - All entity starting locations, grid dimensions, and screen bounds MUST be dynamically derived from the central data model or layout structure (e.g. read markers like player/enemy spawn from the map layout class, compute screen size from `cols * cellSize` and `rows * cellSize`).
11. DIRECTORY LAYOUT & LANGUAGE PURITY:
   - Keep all source files conforming to the planned layout.{fileLayoutRule}
   - All files created MUST match the project's target tech stack. Never create C/C++ files in a Python project or mix incompatible languages.
12. {langGuideline}
13. For Vite or modern web frontend projects, 'index.html' is the root entry point and MUST be placed at the root of the frontend subproject (e.g. client/index.html), NEVER inside public/ or client/public/.

Workspace Symbol Registry & AST:
{initialAst}

Workspace Context:
{workspaceContext}

Relevant memories from previous interactions:
{memoriesStr}

Prerequisite Tasks Context:
{taskContext}

QA Feedback to Address:
{feedbackContext}"""

    coderMessages = [SystemMessage(content=coderPretext)] + state["messages"]
    if state.get("feedback") and state["feedback"] != "No feedback yet. This is your first attempt.":
        coderMessages.append(HumanMessage(content=f"Please fix the following issues reported by QA:\n{state['feedback']}"))

    threadModel = get_llm().bind_tools(coderTools)
    allToolResults = []
    lastResponse = None
    lastMessage = ""

    for turn in range(50):
        coderResponse = streamInvoke(threadModel, coderMessages)
        lastResponse = coderResponse
        lastMessage = extractText(coderResponse.content)
        toolResults = executeToolCalls(coderResponse, coderTools)

        if not toolResults:
            if turn < 2 and not allToolResults:
                nudge = "You have not executed any tools yet. You must use tool calls (createFile, createFiles, editFile, replaceBlock, readFile) to inspect or modify code. Call the appropriate tool now."
                coderMessages.extend([coderResponse, HumanMessage(content=nudge)])
                continue
            break

        allToolResults.extend(toolResults)
        for tr in toolResults:
            print(f"{tr}\n")

        taskFinished = any("Tool finishTask executed:" in tr for tr in toolResults)
        if taskFinished:
            break

        if len(allToolResults) >= 50:
            print("\n[Coder] Maximum tool call limit (50) reached. Automatically completing task.")
            allToolResults.append("Tool finishTask executed: Task auto-completed after reaching maximum tool call limit (50).")
            break

        autoFixImports(WORK_DIR)
        loadCag(str(WORK_DIR))
        liveAst = formatManifestContext(WORK_DIR)
        obsText = "\n".join(toolResults)

        finalNudge = (
            f"Observation:\n{obsText}\n\nLive Workspace AST Context:\n{liveAst}\n\n"
            "Reflect on the updated AST and tool output. "
            "If further files, imports, or connections are needed to finish the task, take your next Action (tool call). "
            "If all requirements and files are complete, call 'finishTask(summary=...)'."
            if isPatchMode else
            f"Observation:\n{obsText}\n\nLive Workspace AST Context:\n{liveAst}\n\n"
            "Reflect on the updated AST and tool output. If further files, imports, or connections are needed to finish the task, take your next Action (tool call). If complete, call 'finishTask(summary=...)'."
        )

        coderMessages.extend([
            coderResponse,
            HumanMessage(content=finalNudge)
        ])

    autoFixImports(WORK_DIR)
    loadCag(str(WORK_DIR))

    return {
        "iteration": iteration,
        "coderMessage": lastMessage,
        "toolResults": allToolResults,
        "messages": [lastResponse] if lastResponse else []
    }

workspaceSnapshot = {}

def getWorkspaceSnapshot(workDir: Path) -> dict:
    if not workDir.exists():
        return {}
    snapshot = {}
    skipDirs = {
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".cache",
        "build",
        "dist"
    }
    for root, dirs, files in os.walk(workDir):
        dirs[:] = [d for d in dirs if d not in skipDirs and not d.startswith(".")]
        for fname in files:
            fpath = Path(root) / fname
            try:
                stat = fpath.stat()
                rel = fpath.relative_to(workDir).as_posix()
                snapshot[rel] = (stat.st_mtime, stat.st_size)
            except Exception:
                continue
    return snapshot

def getChangedFiles(workDir: Path, baselineSnapshot: dict) -> list:
    currentSnapshot = getWorkspaceSnapshot(workDir)
    changed = []
    for rel, meta in currentSnapshot.items():
        if rel not in baselineSnapshot:
            changed.append(rel)
        elif baselineSnapshot[rel] != meta:
            changed.append(rel)
    for rel in baselineSnapshot:
        if rel not in currentSnapshot:
            changed.append(rel)
    return sorted(changed)

def formatChangedFilesContent(workDir: Path, changedFiles: list) -> str:
    if not workDir.exists() or not changedFiles:
        return ""
    parts = []
    for rel in changedFiles:
        fpath = workDir / rel
        if not fpath.exists():
            parts.append(f"[File: {rel}] (DELETED)")
            continue
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(50000)
            parts.append(f"[File: {rel}]\n{content}")
        except Exception:
            parts.append(f"[File: {rel}] (UNABLE TO READ)")
    return "\n\n".join(parts)

def updateWorkspaceSnapshot(workDir: Path) -> None:
    global workspaceSnapshot
    workspaceSnapshot = getWorkspaceSnapshot(workDir)

def isAssetOnlyTask(instruction: str, changedFiles: list) -> bool:
    codeIntentWords = [
        "class ",
        "def ",
        "function",
        "method",
        "route",
        "endpoint",
        "logic",
        "algorithm",
        "handler",
        "controller",
        "service",
        "entrypoint",
        "entry point",
        "component",
        "backend",
        "frontend",
        "database",
        "schema",
        "import",
        "module",
        "implement",
        "code",
        "script",
        "loop"
    ]
    instLower = instruction.lower()
    for word in codeIntentWords:
        if word in instLower:
            return False
    if not changedFiles:
        return False
    assetExtensions = {
        ".svg",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".bmp",
        ".webp",
        ".tiff",
        ".mp3",
        ".wav",
        ".ogg",
        ".mp4",
        ".webm",
        ".flac",
        ".aac",
        ".ttf",
        ".otf",
        ".woff",
        ".woff2",
        ".eot",
        ".md",
        ".txt",
        ".rst",
        ".pdf",
        ".csv",
        ".tsv",
        ".dot",
        ".mmd"
    }
    for p in changedFiles:
        ext = Path(p).suffix.lower()
        if not ext:
            return False
        if ext not in assetExtensions:
            return False
    return True

def alignFrontendConventions(workDir: Path) -> None:
    if not workDir.exists():
        return
    for item in workDir.iterdir():
        if item.is_dir():
            publicIndex = item / "public" / "index.html"
            rootIndex = item / "index.html"
            isVite = (item / "vite.config.js").exists() or (item / "vite.config.ts").exists() or (item / "vite.config.mjs").exists()
            pkgJson = item / "package.json"
            if not isVite and pkgJson.exists():
                try:
                    with open(pkgJson, "r", encoding="utf-8") as f:
                        pkgContent = f.read()
                        if "vite" in pkgContent:
                            isVite = True
                except Exception:
                    pass
            if isVite and publicIndex.exists() and not rootIndex.exists():
                try:
                    shutil.copy2(str(publicIndex), str(rootIndex))
                    print(f"\n[Conventions] Synchronized Vite entry point to {rootIndex.as_posix()}")
                except Exception:
                    pass

workspaceSnapshot = getWorkspaceSnapshot(WORK_DIR)

def criticNode(state: AgentState) -> dict:
    print(f"\nCritic iteration {state['iteration']}")

    alignFrontendConventions(WORK_DIR)
    autoFixImports(WORK_DIR)
    isValid, connErrors = validateConnectedness(WORK_DIR)
    if not isValid:
        connFeedback = "STATIC CONNECTEDNESS & SYNTAX ERRORS:\n" + "\n".join(f"- {e}" for e in connErrors)
        return {
            "messages": [AIMessage(content=f"FAIL: {connFeedback}")],
            "feedback": f"Critic Feedback:\nFAIL: {connFeedback}",
            "success": False,
            "isAssetOnly": False
        }

    changedFiles = getChangedFiles(WORK_DIR, workspaceSnapshot)
    allSnapshot = getWorkspaceSnapshot(WORK_DIR)
    instLower = state["instruction"].lower()
    for rel in allSnapshot:
        if rel not in changedFiles:
            if rel.lower() in instLower or Path(rel).name.lower() in instLower:
                changedFiles.append(rel)
    changedFiles.sort()
    if not changedFiles:
        entryCandidates = ("main", "app", "index", "server")
        entryFiles = [f for f in allSnapshot if any(c in Path(f).stem.lower() for c in entryCandidates)]
        changedFiles = entryFiles if entryFiles else allSnapshot[:5]

    if isAssetOnlyTask(state["instruction"], changedFiles):
        print("\n[Critic Tier 1: Micro] Asset/Documentation task verified via workspace file state.")
        return {
            "messages": [AIMessage(content="PASS: Asset and documentation task verified via workspace file state.")],
            "feedback": state.get("feedback", ""),
            "success": True,
            "isAssetOnly": True
        }

    changedFilesContent = formatChangedFilesContent(WORK_DIR, changedFiles)
    manifestContext = formatManifestContext(WORK_DIR)

    microPretext = (
        "You are an expert Micro Code Critic reviewing task-level code modifications.\n"
        "Review the modified files and task instructions strictly for correctness, missing method calls, and stub implementations.\n"
        "Existing workspace files from prior completed milestones are established and do not need re-modification.\n"
        "If a task objective specifies a file or library that contradicts the primary Target Tech Stack or existing codebase, implementing the equivalent functionality using the project's designated language/stack is acceptable.\n"
        "If no files were modified because existing entrypoint files already fully satisfy the integration or wiring, respond strictly with PASS.\n"
        "Respond starting strictly with PASS if the changes fulfill the task without regressions, or FAIL followed by concise error details."
    )
    microInstruction = (
        f"Task Instruction: {state['instruction']}\n"
        f"Coder Summary: {state.get('coderMessage', '')}\n\n"
        f"Modified Files & Content:\n{changedFilesContent if changedFilesContent else 'No changed files detected; inspect symbol registry.'}\n\n"
        f"Symbol Registry:\n{manifestContext}\n\n"
        "Evaluate the changes. Respond starting strictly with PASS or FAIL."
    )

    print("\n[Critic Tier 1: Micro] Evaluating modified files against task contract...")
    microResponse = streamInvoke(agentModel, [SystemMessage(content=microPretext), HumanMessage(content=microInstruction)])
    microMessage = extractText(microResponse.content)
    microPass = microMessage.strip().upper().startswith("PASS")

    if not microPass:
        return {
            "messages": [microResponse],
            "feedback": f"Critic Feedback:\n{microMessage}",
            "success": False,
            "isAssetOnly": False
        }

    isFinalTask = any(w in state["instruction"].lower() for w in ("integrate", "final", "playtest", "verification"))
    if not isFinalTask:
        print("\n[Critic Tier 1: Micro] Passed. Skipping Tier 2 System Critic for incremental task.")
        return {
            "messages": [microResponse],
            "feedback": state.get("feedback", ""),
            "success": True,
            "isAssetOnly": False
        }

    print("\n[Critic Tier 2: System] Running full topology & architecture audit...")
    workFileParts = []
    skipDirs = {
        "node_modules", "__pycache__", "venv", ".git", ".venv",
        "chroma_db", "graphify-out", "dist", "build", ".next", ".nuxt", ".cache", "coverage"
    }
    skipFiles = {
        "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock", "cargo.lock", "poetry.lock"
    }
    supportedExts = {".py", ".js", ".ts", ".java", ".html", ".css", ".json", ".jsx", ".tsx", ".go", ".cpp", ".c", ".h", ".md", ".txt", ".svg", ".yaml", ".yml"}

    if WORK_DIR.exists():
        for root, dirs, files in os.walk(WORK_DIR):
            dirs[:] = [d for d in dirs if d not in skipDirs and not d.startswith(".")]
            for fname in sorted(files):
                if fname in skipFiles or fname.endswith((".min.js", ".min.css", ".map", ".pack")):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in supportedExts:
                    continue
                fpath = Path(root) / fname
                if fpath.stat().st_size > 100000:
                    continue
                rel = fpath.relative_to(WORK_DIR).as_posix()
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(50000)
                    if content.strip():
                        workFileParts.append(f"[File: {rel}]\n{content}")
                except Exception:
                    continue

    workFilesStr = "\n\n".join(workFileParts) if workFileParts else "No files in workspace."

    systemPretext = (
        "You are an expert System Architecture Critic evaluating end-to-end multi-file coherence.\n"
        "Verify complete application wiring, navigation reachability, and absence of dead ends.\n"
        "- Network: verify endpoints, ports, and CORS.\n"
        "- Persistence: verify DB schema, initialization, and seeding.\n"
        "- Mounting: verify routes and components connect to root.\n"
        "Respond starting strictly with PASS if the system architecture is coherent, or FAIL followed by diagnostics."
    )
    systemInstruction = (
        f"Overall Goal & Integration: {state['instruction']}\n\n"
        f"Workspace Symbol Registry:\n{manifestContext}\n\n"
        f"Workspace File Contents:\n{workFilesStr}\n\n"
        "Evaluate end-to-end architecture. Respond starting strictly with PASS or FAIL."
    )

    systemResponse = streamInvoke(agentModel, [SystemMessage(content=systemPretext), HumanMessage(content=systemInstruction)])
    systemMessage = extractText(systemResponse.content)
    systemPass = systemMessage.strip().upper().startswith("PASS")

    return {
        "messages": [systemResponse],
        "feedback": f"Critic Feedback:\n{systemMessage}" if not systemPass else state["feedback"],
        "success": systemPass,
        "isAssetOnly": False
    }

def shouldRetryTester(errorOutput: str) -> bool:
    if "rejected by user" in errorOutput.lower():
        return True
    cappedError = "\n".join(errorOutput.strip().splitlines()[:6])
    triagePrompt = (
        f"A command failed with output:\n{cappedError}\n\n"
        "Was this caused by a shell or command execution error (such as an invalid command on this operating system, missing executable, wrong flag, or wrong path) or by an application source code defect?\n"
        "Reply strictly with RETRY_TESTER if Tester should try a different shell command, or CODER if application source code needs to be repaired."
    )
    try:
        triageResp = get_llm().invoke([HumanMessage(content=triagePrompt)])
        return "RETRY_TESTER" in extractText(triageResp.content).upper()
    except Exception:
        return False

def testerNode(state: AgentState) -> dict:
    print(f"\nTester iteration {state['iteration']}")

    alignFrontendConventions(WORK_DIR)

    allFiles = []
    subprojectDirs = set()
    manifestNames = {
        "package.json",
        "pyproject.toml",
        "requirements.txt",
        "cargo.toml",
        "go.mod",
        "pom.xml",
        "build.gradle",
        "makefile",
        "cmakelists.txt"
    }
    skipDirs = {
        "node_modules",
        "__pycache__",
        "venv",
        ".git",
        ".venv",
        "chroma_db",
        "graphify-out",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".cache",
        "coverage"
    }
    if WORK_DIR.exists():
        for root, dirs, files in os.walk(WORK_DIR):
            dirs[:] = [d for d in dirs if d not in skipDirs and not d.startswith(".")]
            for fname in files:
                rel = Path(root).relative_to(WORK_DIR) / fname
                relStr = rel.as_posix()
                allFiles.append(relStr)
                if fname.lower() in manifestNames:
                    subRel = Path(root).relative_to(WORK_DIR).as_posix()
                    subprojectDirs.add(subRel if subRel != "." else ".")

    subprojects = sorted(list(subprojectDirs)) if subprojectDirs else ["."]

    if not allFiles:
        print("\n[Tester] No files in workspace. Skipping runtime execution.")
        return {
            "messages": [],
            "feedback": state["feedback"],
            "success": True
        }

    executableExts = {
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".rs",
        ".go",
        ".java",
        ".c",
        ".cpp",
        ".cs",
        ".rb",
        ".php"
    }
    hasExecutableCode = any(Path(f).suffix.lower() in executableExts for f in allFiles)
    hasManifest = bool(subprojectDirs)

    if not hasExecutableCode and not hasManifest:
        print("\n[Tester] No executables or project manifests found. Skipping runtime verification.")
        return {
            "messages": [],
            "feedback": state["feedback"],
            "success": True
        }

    filesStr = ", ".join(allFiles) if allFiles else "None"
    subprojectsStr = ", ".join(subprojects)
    manifestStr = formatManifestContext(WORK_DIR)
    srcDir = WORK_DIR / "src"
    pathSeparator = ";" if os.name == "nt" else ":"
    if srcDir.exists():
        pyPathPrefix = f"set PYTHONPATH={WORK_DIR.resolve()}{pathSeparator}{srcDir.resolve()} && " if os.name == "nt" else f"PYTHONPATH={WORK_DIR.resolve()}{pathSeparator}{srcDir.resolve()} "
    else:
        pyPathPrefix = f"set PYTHONPATH={WORK_DIR.resolve()} && " if os.name == "nt" else f"PYTHONPATH={WORK_DIR.resolve()} "

    manifestExts = {".json", ".toml", ".yaml", ".yml", ".xml", ".gradle", ".mod", ".lock", ".cfg", ".ini"}
    currentManifestHashes = {}
    if WORK_DIR.exists():
        for item in WORK_DIR.iterdir():
            if item.is_file():
                if item.suffix.lower() in manifestExts or item.name.lower() in manifestNames:
                    try:
                        with open(item, "rb") as f:
                            currentManifestHashes[item.name] = hashlib.md5(f.read()).hexdigest()
                    except Exception:
                        pass

    envAlreadyVerified = bool(currentManifestHashes and currentManifestHashes == verifiedManifestHashes)

    if envAlreadyVerified:
        protocolText = (
            "EXECUTION PROTOCOL:\n"
            "Environment runtime and dependencies were verified in a previous milestone.\n"
            f"Detected Subprojects to verify: [{subprojectsStr}].\n"
            "Execute application build, test, or verification commands directly for all subprojects.\n"
        )
        humanContent = f"Workspace files: [{filesStr}]. Detected Subprojects: [{subprojectsStr}]. Environment verified. Execute build, test, or verification commands directly across all subprojects."
    else:
        protocolText = (
            "EXECUTION PROTOCOL:\n"
            f"Detected Subprojects to verify: [{subprojectsStr}].\n"
            "Execute build, test, or runtime commands directly across all subprojects (e.g. install dependencies if needed, build frontend, start/test backend).\n"
            "Do NOT run shell commands to view or inspect file contents.\n"
        )
        humanContent = f"Workspace files: [{filesStr}]. Detected Subprojects: [{subprojectsStr}]. Execute build, test, or verification commands directly across all subprojects. Do not read or inspect files."

    platformName = "Windows" if os.name == "nt" else "Linux/macOS"
    runPretext = (
        "You are responsible for verifying code execution across all workspace subprojects.\n"
        f"Operating System: {platformName}\n"
        f"{protocolText}"
        "CRITICAL RULES:\n"
        "- Output executeCommand tool calls ONLY to install dependencies, build, and run the application.\n"
        "- Do NOT execute shell commands to view or inspect files (e.g. cat, type, head, tail, dir, ls). Inspecting file contents is not your job; execute build, test, and run commands directly.\n"
        f"- You must verify ALL detected subprojects [{subprojectsStr}]. Do not conclude after testing only one.\n"
        "- Terminal CWD is ALREADY the workspace root. Use 'cd <subproject> && ...' to target specific subprojects.\n"
        "- Do NOT attempt to modify or patch source code files using shell commands.\n"
        f"- For Python packages (files inside subdirectories), use: {pyPathPrefix}python -m <package>.<module>\n"
        "- If an application requires interactive input, test non-interactively.\n"
        "- If execution completes with Exit Code: 0 and no errors across all subprojects, respond strictly with 'PASS'.\n"
        "- If a command is rejected or denied by the user, immediately follow any user-provided instruction or try an alternative command.\n"
        "- If any command crashes, throws build errors, or fails, respond strictly with 'FAIL' followed by complete traceback and error diagnostics so the Coder Agent can repair the files."
    )

    runMessages = [
        SystemMessage(content=runPretext),
        HumanMessage(content=humanContent)
    ]

    testerResponse = None
    testerMessage = ""
    allRunTools = []

    for attempt in range(1, 11):
        if attempt > 1:
            print(f"\nTester retry {attempt}/10")
        threadTesterModel = get_llm().bind_tools(testerTools)
        testerResponse = streamInvoke(threadTesterModel, runMessages)
        testerMessage = extractText(testerResponse.content)
        runTools = executeToolCalls(testerResponse, testerTools)
        deniedTools = [tr for tr in runTools if "command execution rejected by user" in tr.lower()]
        activeRunTools = [tr for tr in runTools if "command execution rejected by user" not in tr.lower()]
        if activeRunTools:
            allRunTools.extend(activeRunTools)
        for tr in runTools:
            print(tr, "\n")

        if deniedTools:
            if attempt < 10:
                deniedDetails = "\n".join(deniedTools)
                promptNote = (
                    f"The user denied execution of the following command(s):\n{deniedDetails}\n\n"
                    "Do not run the rejected command again. Follow the user's instruction or run the alternative command to accomplish verification."
                )
                runMessages.extend([
                    testerResponse,
                    HumanMessage(content=promptNote)
                ])
                continue
            testerMessage = "FAIL: Command execution rejected by user:\n" + "\n".join(deniedTools)
            break

        appRunTools = []
        setupRunTools = []
        for tr in allRunTools:
            extractedCmd = extractCommand(tr)
            if extractedCmd and isSetupCommand(extractedCmd):
                setupRunTools.append(tr)
            elif extractedCmd:
                appRunTools.append(tr)

        hasRunApp = len(appRunTools) > 0
        appOutput = "\n".join(appRunTools)
        allAppExitsZero = bool(appRunTools) and all("Exit Code: 0" in tr for tr in appRunTools)
        hasError = "Traceback" in appOutput or "Error:" in appOutput or "Exception:" in appOutput or "error during build" in appOutput.lower()

        testedSubprojects = set()
        for tr in appRunTools:
            extractedCmd = extractCommand(tr)
            for sub in subprojects:
                if sub == "." or f"cd {sub}" in extractedCmd or f"/{sub}/" in extractedCmd or extractedCmd.startswith(f"{sub}/") or f" {sub}" in extractedCmd:
                    testedSubprojects.add(sub)

        allSubprojectsTested = bool(subprojects) and all(s in testedSubprojects for s in subprojects)

        failedRunTools = []
        for tr in allRunTools:
            hasZero = "Exit Code: 0" in tr
            hasErrToken = "Traceback" in tr or "Error:" in tr or "Exception:" in tr or "error during build" in tr.lower() or "SyntaxError" in tr or "Cannot find module" in tr or "MODULE_NOT_FOUND" in tr
            if not hasZero or hasErrToken:
                if hasZero and "STDERR:" in tr and "npm warn" in tr and not hasErrToken:
                    continue
                failedRunTools.append(tr)

        if (hasRunApp and (hasError or not allAppExitsZero)) or failedRunTools:
            failureDetails = "\n\n".join(failedRunTools) if failedRunTools else appOutput
            if attempt < 10 and shouldRetryTester(failureDetails):
                for ftr in failedRunTools:
                    if ftr in allRunTools:
                        allRunTools.remove(ftr)
                promptNote = f"The previous command failed:\n{failureDetails}\n\nThis appears to be a command execution or shell compatibility issue. Try an alternate, platform-compatible command or script."
                runMessages.extend([
                    testerResponse,
                    HumanMessage(content=promptNote)
                ])
                continue
            testerMessage = f"FAIL: Application execution failed with error:\n{failureDetails}"
            print("\n[Tester] Application execution failed. Delegating diagnostic to Coder Agent.")
            break

        if hasRunApp and allAppExitsZero and not hasError and not failedRunTools and allSubprojectsTested:
            testerMessage = "PASS"
            print("\n[Tester] All subprojects verified successfully (Exit Code: 0).")
            break

        if testerMessage.strip().upper().startswith("PASS") and hasRunApp and not failedRunTools and allSubprojectsTested:
            break

        untestedSubprojects = [s for s in subprojects if s not in testedSubprojects]
        recentCmds = [extractCommand(tr) for tr in runTools]
        onlySetupRun = bool(runTools) and all(isSetupCommand(c) for c in recentCmds if c)

        if untestedSubprojects and hasRunApp and allAppExitsZero and not hasError and not failedRunTools:
            promptNote = f"Subproject(s) {untestedSubprojects} have not been verified yet. Execute the build, test, or run command for {untestedSubprojects}."
            runMessages.extend([
                testerResponse,
                HumanMessage(content=promptNote)
            ])
            continue

        if (not runTools and not hasRunApp) or onlySetupRun:
            targetSub = untestedSubprojects[0] if untestedSubprojects else subprojects[0]
            promptNote = f"Dependencies installed. Now execute the build, test, or verification command for subproject '{targetSub}'."
            runMessages.extend([
                testerResponse,
                HumanMessage(content=promptNote)
            ])
            continue

        runMessages.extend([
            testerResponse,
            HumanMessage(content="Terminal output:\n" + "\n".join(allRunTools) + f"\n\nContinue verification for remaining subprojects {untestedSubprojects if untestedSubprojects else subprojects}. If all subprojects pass cleanly, respond strictly with PASS. If build or logic bugs remain, respond strictly with FAIL and diagnostic details.")
        ])

    appRunTools = [tr for tr in allRunTools if extractCommand(tr) and not isSetupCommand(extractCommand(tr))]
    appOutput = "\n".join(appRunTools)
    allAppExitsZero = bool(appRunTools) and all("Exit Code: 0" in tr for tr in appRunTools)
    hasError = "Traceback" in appOutput or "Error:" in appOutput or "Exception:" in appOutput or "error during build" in appOutput.lower()
    testedSubprojects = set()
    for tr in appRunTools:
        extractedCmd = extractCommand(tr)
        for sub in subprojects:
            if sub == "." or f"cd {sub}" in extractedCmd or f"/{sub}/" in extractedCmd or extractedCmd.startswith(f"{sub}/") or f" {sub}" in extractedCmd:
                testedSubprojects.add(sub)
    allSubprojectsTested = bool(subprojects) and all(s in testedSubprojects for s in subprojects)

    failedCommands = []
    for tr in allRunTools:
        hasZero = "Exit Code: 0" in tr
        hasErrToken = "Traceback" in tr or "Error:" in tr or "Exception:" in tr or "error during build" in tr.lower() or "SyntaxError" in tr or "Cannot find module" in tr or "MODULE_NOT_FOUND" in tr
        if not hasZero or hasErrToken:
            if hasZero and "STDERR:" in tr and "npm warn" in tr and not hasErrToken:
                continue
            failedCommands.append(tr)

    isPass = bool(appRunTools) and allAppExitsZero and not hasError and not failedCommands and allSubprojectsTested
    if isPass:
        if currentManifestHashes:
            verifiedManifestHashes.update(currentManifestHashes)
        print("\nProcess finished successfully.\n")
    else:
        if failedCommands:
            failureDetails = "\n\n".join(failedCommands)
        elif appOutput:
            failureDetails = appOutput
        elif allRunTools:
            failureDetails = "\n\n".join(allRunTools)
        else:
            failureDetails = testerMessage if testerMessage and testerMessage.strip() != "PASS" else "Execution failed: Application build or verification commands failed or were not executed."
        try:
            print("\n[MEMORY] Execution failed. Tester Agent is generating a lesson...")
            memoryManager.learnFromFailure(state["instruction"], failureDetails)
        except Exception as e:
            print(f"[MEMORY] Error generating lesson from failure: {e}")

    if not isPass:
        if failedCommands:
            failureFeedback = "\n\n".join(failedCommands)
        elif appOutput:
            failureFeedback = appOutput
        elif allRunTools:
            failureFeedback = "\n\n".join(allRunTools)
        else:
            failureFeedback = testerMessage if testerMessage and testerMessage.strip() != "PASS" else "Execution failed: Application build or verification commands failed or were not executed."
    else:
        failureFeedback = state["feedback"]

    return {
        "messages": [testerResponse] if testerResponse else [],
        "feedback": failureFeedback if isPass else f"Tester Execution Failed:\n{failureFeedback}",
        "success": isPass
    }

def routeCritic(state: AgentState) -> str:
    if not state.get("success", False):
        return END
    if state.get("isAssetOnly", False):
        return END
    instText = state.get("instruction", "").lower()
    isFinal = any(w in instText for w in ("final", "integrate", "playtest", "verification"))
    if not isFinal:
        return END
    return "tester"

def routeTester(state: AgentState) -> str:
    return END

evalBuilder = StateGraph(AgentState)
evalBuilder.add_node("critic", criticNode)
evalBuilder.add_node("tester", testerNode)

evalBuilder.add_edge(START, "critic")
evalBuilder.add_conditional_edges("critic", routeCritic, {"tester": "tester", END: END})
evalBuilder.add_conditional_edges("tester", routeTester, {END: END})

evalWorkflow = evalBuilder.compile()

def runCoder(instruction, taskContext="", feedback=""):
    context = getCoderContext(instruction, workDir=str(WORK_DIR))
    retrievedMemories = []
    if shouldRetrieveMemory(instruction):
        try:
            mems = memoryManager.searchMemory(instruction, topK=3)
            retrievedMemories = [m["content"] for m in mems]
        except Exception:
            retrievedMemories = []
    initialState = {
        "messages": [HumanMessage(content=instruction)],
        "instruction": instruction,
        "taskContext": taskContext,
        "context": context,
        "coderMessage": "",
        "toolResults": [],
        "feedback": feedback if feedback else "No feedback yet. This is your first attempt.",
        "iteration": 0,
        "success": False,
        "memories": retrievedMemories,
        "isAssetOnly": False
    }
    return coderNode(initialState)

def runBatchEval(batchTasks, coderResults, isFinal=False):
    taskNames = ", ".join([getattr(t, "name", getattr(t, "objective", t.id)) for t in batchTasks])
    header = "[Project Verification]" if isFinal else "[Milestone Review]"
    print(f"\n{header} Evaluating {len(batchTasks)} completed task(s): {taskNames}")

    isValid, connErrors = validateConnectedness(WORK_DIR)
    if not isValid:
        errMsg = "\n".join(f"- {e}" for e in connErrors)
        print(f"{header} AST/Syntax errors detected:\n{errMsg}")

    summaryText = "\n".join([f"- Task '{getattr(t, 'name', t.id)}': {res.get('coderMessage', '')}" for t, res in zip(batchTasks, coderResults)])
    combinedTools = sum([res.get("toolResults", []) for res in coderResults], [])
    manifestText = formatManifestContext(WORK_DIR)

    instPrefix = "Final Project Verification" if isFinal else "Batch Review"
    initialState = {
        "messages": [HumanMessage(content=f"{instPrefix}: {taskNames}\nCoder Summaries:\n{summaryText}\n\nWorkspace Status:\n{manifestText}")],
        "instruction": f"{instPrefix}: {taskNames}",
        "taskContext": summaryText,
        "context": manifestText,
        "coderMessage": summaryText,
        "toolResults": combinedTools,
        "feedback": "",
        "iteration": 0,
        "success": False,
        "isAssetOnly": False
    }

    finalState = evalWorkflow.invoke(initialState)
    passed = finalState.get("success", False)
    fb = finalState.get("feedback", "")
    if passed:
        print(f"{header} PASSED.")
        updateWorkspaceSnapshot(WORK_DIR)
    else:
        print(f"{header} FAILED: {fb}")
    return passed, fb

def runAgent(instruction, taskContext=""):
    print("Preloading workspace into CAG cache: ")
    loadCag(str(WORK_DIR))
    context = getCoderContext(instruction, workDir=str(WORK_DIR))
    initialState = {
        "messages": [HumanMessage(content=instruction)],
        "instruction": instruction,
        "taskContext": taskContext,
        "context": context,
        "coderMessage": "",
        "toolResults": [],
        "feedback": "No feedback yet. This is your first attempt.",
        "iteration": 0,
        "success": False,
        "isAssetOnly": False
    }
    finalState = evalWorkflow.invoke(initialState)
    if finalState["success"]:
        updateWorkspaceSnapshot(WORK_DIR)
        return True, finalState.get("coderMessage", "Task completed.")
    return False, finalState.get("feedback", "Execution failed")

def printProjectSummary(goal: str, techStack: str, taskOutputs: dict, workDir: Path) -> None:
    skipDirs = {"node_modules", "__pycache__", "dist", "build", ".git", ".venv", "venv", "chroma_db", "graphify-out"}
    createdFiles = []
    if workDir.exists():
        for f in workDir.rglob("*"):
            if f.is_file() and not any(p.startswith(".") or p in skipDirs for p in f.parts):
                createdFiles.append(str(f.relative_to(workDir)))
    fileListStr = "\n".join(f"  - {f}" for f in sorted(createdFiles))
    taskSummaries = "\n".join(f"- {msg.splitlines()[0]}" for msg in taskOutputs.values() if msg)
    cleanGoal = goal.split("\n")[0] if goal else "Project Implementation"
    prompt = (
        f"Goal: {cleanGoal}\nTech Stack: {techStack}\nCreated Files:\n{fileListStr}\nTask Highlights:\n{taskSummaries}\n\n"
        "Generate a concise, user-friendly project completion summary for the terminal:\n"
        "1. What was built\n"
        "2. Key features & file structure\n"
        "3. How to run / verify the project\n"
        "Keep it crisp, professional, and well-structured."
    )
    print("\n" + "=" * 60)
    print("[Kaizen Project Summary]\n")
    try:
        resp = get_llm().invoke([HumanMessage(content=prompt)])
        content = resp.content
        summaryText = "".join(p if isinstance(p, str) else p.get("text", "") for p in content) if isinstance(content, list) else str(content)
        print(summaryText.strip())
    except Exception:
        print(f"Goal: {cleanGoal}\nTech Stack: {techStack}\n\nFiles Created:\n{fileListStr}\n")
    print("=" * 60 + "\n")

if __name__ == "__main__":
    startLogging()
    print("\nType 'index' for reindexing or 'exit' to quit.\n")
    while True:
        query = input("\nInstruction: ")
        q = query.strip().lower()
        if q == "exit":
            break
        if q == "index":
            loadCag(str(WORK_DIR))
            print("Preloaded workspace into CAG cache")
        elif q:
            targetBranch = ""
            ownerName, repoName, issueNum = gitHubAgent.parseIssueUrl(query)
            if ownerName and repoName and issueNum:
                issueData = gitHubAgent.fetchIssue(ownerName, repoName, issueNum)
                if issueData:
                    issueTitle = issueData.get("title", "")
                    issueBody = issueData.get("body", "")
                    print(f"\n[GitHub Agent] Loaded Issue #{issueNum}: {issueTitle}")
                    targetBranch = f"fix/issue-{issueNum}"
                    gitHubAgent.createBranch(targetBranch)
                    query = f"Fix GitHub Issue #{issueNum}: {issueTitle}\n\n{issueBody}" if issueBody else f"Fix GitHub Issue #{issueNum}: {issueTitle}"

            retrievedMemories = []
            if shouldRetrieveMemory(query):
                try:
                    mems = memoryManager.searchMemory(query, topK=3)
                    retrievedMemories = [m["content"] for m in mems]
                except Exception:
                    retrievedMemories = []

            mode = classifyIntent(query)

            if mode in ("direct", "patch"):
                print("\n[Kaizen] Direct execution mode, running tool-enabled agent loop.\n")
                loadCag(str(WORK_DIR))
                patchInstruction = buildPatchInstruction(query, WORK_DIR)
                if retrievedMemories:
                    memStr = "\n".join(f"- {m}" for m in retrievedMemories)
                    patchInstruction = f"{patchInstruction}\n\nRelevant past lessons:\n{memStr}"
                patchResult = runCoder(patchInstruction)
                patchSummary = patchResult.get("coderMessage", "").strip() if isinstance(patchResult, dict) else ""
                if patchSummary:
                    print("\n" + "=" * 60)
                    print("[Kaizen] Execution complete:\n")
                    print(patchSummary)
                    print("=" * 60 + "\n")
                else:
                    print("\n[Kaizen] Execution complete.\n")
                if targetBranch or any(w in query.lower() for w in ("publish", "push to github", "create pr")):
                    gitHubAgent.publish(query, targetBranch)
            else:
                promptAgent = PromptAgent()
                curQuery = query
                if retrievedMemories:
                    mStr = "\n".join(f"- {m}" for m in retrievedMemories)
                    curQuery = f"{query}\n\nRelevant past memories/lessons:\n{mStr}"

                existingAst = formatManifestContext(WORK_DIR)
                if existingAst and "Workspace is currently empty" not in existingAst:
                    curQuery = f"{curQuery}\n\nExisting Workspace Code & Structure:\n{existingAst}"

                baseQuery = curQuery
                while True:
                    promptOutput = promptAgent.process(curQuery)
                    deliverables = promptOutput.get("deliverables", [])
                    techStack = promptOutput.get("tech_stack") or promptOutput.get("techStack") or ""
                    fileStructure = promptOutput.get("file_structure") or promptOutput.get("fileStructure") or []
                    proceed, usrFeedback = reviewDeliverables(deliverables, techStack, fileStructure)
                    if proceed:
                        break
                    pastPlan = json.dumps({"tech_stack": techStack, "file_structure": fileStructure, "deliverables": deliverables}, indent=2)
                    curQuery = f"{baseQuery}\n\nPrevious Proposed Plan:\n{pastPlan}\n\nUser Plan Feedback: {usrFeedback}\nPlease update the plan by addressing the user feedback while referencing the previous plan."
                    print("\nRegenerating plan based on your feedback...\n")

                plannerAgent = PlannerAgent()
                dagPlan = plannerAgent.plan(promptOutput)
                dagPlan = HITLReview(dagPlan).run()

                dag = DAG()
                for t in dagPlan.taskNodes:
                    t.name = getattr(t, "objective", t.id)
                    t.agent = "Coding"
                    dag.addTask(t)
                dag.build()

                print("\nGenerated Tasks:")
                for task in dagPlan.taskNodes:
                    deps = ", ".join(task.dependencies) if task.dependencies else "none"
                    print(f" - [{task.priority}] {task.objective} (deps: {deps})")

                print("\nExecution Order:")
                print(dag.topologicalSort())

                loadCag(str(WORK_DIR))
                scheduler = Scheduler(dag, curQuery, techStack=techStack, fileStructure=fileStructure, coderFn=runCoder, evalFn=runBatchEval)
                asyncio.run(scheduler.run())
                printProjectSummary(query, techStack, scheduler.taskOutputs, WORK_DIR)
                gitHubAgent.publish(curQuery, targetBranch)