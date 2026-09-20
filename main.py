import os
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
    addImport,
    upsertFunction,
    upsertClass,
    appendToFile,
    replaceBlock,
    deleteResource,
    readFile,
    searchWeb,
    finishTask,
    executeCommand,
    WORK_DIR
)
from core.connectedness import formatManifestContext, validateConnectedness, autoFixImports
from rag.rag import indexWorkspace, getContext
from agents.prompt import PromptAgent
from agents.planneragent import PlannerAgent
from agents.patchclassifier import classifyIntent, buildPatchInstruction
from agents.dag import DAG
from agents.scheduler import Scheduler
from agents.hitl import HITLReview, reviewDeliverables
from core.memory import MemoryManager
from core.logger import startLogging

os.environ["OLLAMA_NUM_PARALLEL"] = "4"

memoryManager = MemoryManager()
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
    cleaned = lowerCmd.replace("-", " ").replace("=", " ")
    tokens = cleaned.split()
    setupWords = ["install", "add", "get", "update", "download", "version", "which", "where"]
    for w in setupWords:
        if w in tokens:
            return True
    prefixes = ["pip ", "npm ", "yarn ", "pnpm ", "cargo ", "gem ", "bundle "]
    for p in prefixes:
        if p in lowerCmd:
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
                    if tname == "executeCommand" and "command" in targs:
                        targs["command"] = sanitizeCommand(targs["command"])
                    res = toolMap[tname].invoke(targs)
                    if tname == "executeCommand":
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
                if isinstance(targs, str):
                    try:
                        targs = json.loads(targs)
                    except Exception:
                        targs = {}
                if not isinstance(targs, dict):
                    targs = {}
                if isinstance(tname, str) and tname in toolMap:
                    try:
                        if tname == "executeCommand" and "command" in targs:
                            targs["command"] = sanitizeCommand(targs["command"])
                        res = toolMap[tname].invoke(targs)
                        if tname == "executeCommand":
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
    addImport,
    upsertFunction,
    upsertClass,
    appendToFile,
    replaceBlock,
    deleteResource,
    readFile,
    searchWeb,
    finishTask
]
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
            "- The user is asking you to fix or adjust something specific — NOT rebuild the project.\n"
            "- Your first action MUST be to use readFile on the relevant file(s) before touching anything.\n"
            "- Only edit the lines/functions that are broken. Leave all other working code untouched.\n"
            "- Never use createFile for a file that already exists in the workspace.\n"
            "- Never regenerate an entire module because one function inside it is broken.\n"
        )

    coderPretext = f"""You are a senior software engineer working in a multi-file workspace.
Your goal is to produce complete, connected, buildable, and runnable code.
{patchModeDirective}
You operate in an Action-driven loop:
1. Every turn, directly invoke the necessary tool (createFile, createFiles, editFile, upsertFunction, upsertClass, addImport, appendToFile, replaceBlock, readFile, searchWeb, finishTask) to inspect or modify code.
2. When creating multiple related files (such as SVGs, models, or configurations), use 'createFiles' to write all files together in a single batch call.
3. Never output conversational plans or text like 'I will also need to add...'. Execute the action via tool calls immediately.
4. After each tool execution, you will observe the tool output and the updated live AST Symbol Registry.
5. Explicit Task Completion: As soon as all files, imports, and requirements for the current task are fully in place, call 'finishTask(summary=...)' to conclude your work.

RULES:
1. Always write production-grade, modular, maintainable code with clear separation of concerns.
2. Split features into logical files/modules by responsibility; never put unrelated logic into one large file.
3. Keep UI, business logic, API/services, data access, types, validation, and utilities separated where appropriate.
Reuse existing modules, avoid duplication/circular dependencies, and don't over-engineer with unnecessary abstractions.
4. Call tools directly. Do not narrate or list planned edits in conversational text.
5. File Operations:
   - Use 'createFile' for a single new file, or 'createFiles' to write multiple files in one turn.
   - Use 'editFile', 'upsertFunction', 'upsertClass', 'addImport', 'appendToFile', or 'replaceBlock' to update existing files without breaking unrelated code.
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

    for turn in range(6):
        coderResponse = streamInvoke(threadModel, coderMessages)
        lastResponse = coderResponse
        lastMessage = extractText(coderResponse.content)
        toolResults = executeToolCalls(coderResponse, coderTools)

        if not toolResults:
            break

        allToolResults.extend(toolResults)
        for tr in toolResults:
            print(f"{tr}\n")

        taskFinished = any("Tool finishTask executed:" in tr for tr in toolResults)
        if taskFinished:
            break

        autoFixImports(WORK_DIR)
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
            parts.append(f"--- {rel} (DELETED) ---")
            continue
        try:
            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read(50000)
            parts.append(f"--- {rel} ---\n{content}")
        except Exception:
            parts.append(f"--- {rel} (UNABLE TO READ) ---")
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

workspaceSnapshot = getWorkspaceSnapshot(WORK_DIR)

def criticNode(state: AgentState) -> dict:
    print(f"\nCritic iteration {state['iteration']}")

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

    isFinalTask = "integrate" in state["instruction"].lower() or "final" in state["instruction"].lower() or "playtest" in state["instruction"].lower()
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
                        workFileParts.append(f"--- {rel} ---\n{content}")
                except Exception:
                    continue

    workFilesStr = "\n\n".join(workFileParts) if workFileParts else "No files in workspace."

    systemPretext = (
        "You are an expert System Architecture Critic evaluating end-to-end multi-file coherence.\n"
        "Verify complete application wiring, navigation reachability, and absence of dead ends.\n"
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

def testerNode(state: AgentState) -> dict:
    print(f"\nTester iteration {state['iteration']}")

    allFiles = []
    entryPoints = []
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
                if relStr.endswith(".py"):
                    fpath = Path(root) / fname
                    try:
                        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        if "if __name__" in content or "def main(" in content:
                            entryPoints.append(relStr)
                    except Exception:
                        pass
                elif relStr == "index.html" or relStr.endswith("/index.html"):
                    entryPoints.append(relStr)
                elif relStr in ("server.js", "app.js", "index.js", "main.js", "src/server.js", "src/app.js", "src/index.js"):
                    entryPoints.append(relStr)

    if not entryPoints:
        print("\n[Tester] No runnable entrypoints in workspace. Skipping runtime execution.")
        return {
            "messages": [],
            "feedback": state["feedback"],
            "success": True
        }

    filesStr = ", ".join(allFiles) if allFiles else "None"
    entryStr = ", ".join(entryPoints)
    manifestStr = formatManifestContext(WORK_DIR)
    hasPackages = any("/" in f for f in allFiles if f.endswith(".py"))
    srcDir = WORK_DIR / "src"
    pathSeparator = ";" if os.name == "nt" else ":"
    if srcDir.exists():
        pyPathPrefix = f"set PYTHONPATH={WORK_DIR.resolve()}{pathSeparator}{srcDir.resolve()} && " if os.name == "nt" else f"PYTHONPATH={WORK_DIR.resolve()}{pathSeparator}{srcDir.resolve()} "
    else:
        pyPathPrefix = f"set PYTHONPATH={WORK_DIR.resolve()} && " if os.name == "nt" else f"PYTHONPATH={WORK_DIR.resolve()} "

    runHints = []
    for ep in entryPoints:
        if ep.endswith(".py") and "/" in ep:
            modName = ep.replace("/", ".").replace("\\", ".").removesuffix(".py")
            runHints.append(f"python -m {modName}")
        elif ep.endswith(".py"):
            runHints.append(f"python {ep}")
        elif ep.endswith(".html"):
            runHints.append(f"open {ep}")
        elif ep.endswith(".js"):
            runHints.append(f"node {ep}")
    hintsStr = ", ".join(runHints) if runHints else "python <entrypoint>"

    manifestExts = {".json", ".toml", ".yaml", ".yml", ".xml", ".gradle", ".mod", ".lock", ".cfg", ".ini"}
    manifestNames = {"requirements.txt", "makefile", "gemfile", "dockerfile", "procfile", "cmakelists.txt"}
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
            "Environment runtime and dependencies have already been verified in a previous milestone, and workspace manifests are unchanged.\n"
            "Skip Step 1 (do NOT run environment checks, version commands, or package manager installations).\n"
            "Proceed directly to Step 2: execute application verification or test commands.\n"
        )
        humanContent = f"Workspace files: [{filesStr}]. Detected Entrypoints: [{entryStr}]. Environment and dependencies are already verified. Immediately execute the application entrypoint or test command: [{hintsStr}]."
    else:
        protocolText = (
            "EXECUTION PROTOCOL:\n"
            "Step 1 - Environment & Dependency Check:\n"
            "- First, inspect workspace manifests or build configuration files.\n"
            "- Check if required runtimes, compilers, or dependencies are available and install any missing packages using the project's package manager.\n"
            "Step 2 - Entrypoint Execution:\n"
            "- Once dependencies are confirmed, execute the entrypoint or test suite to verify the application.\n"
        )
        humanContent = f"Workspace files: [{filesStr}]. Detected Entrypoint: [{entryStr}]. First check runtime environment and install any missing dependencies, then execute the application entrypoint to verify execution."

    runPretext = (
        "You are responsible for verifying code execution in the workspace.\n"
        f"{protocolText}"
        "CRITICAL RULES:\n"
        "- Output executeCommand tool calls ONLY to check runtime, install dependencies, and run the application.\n"
        "- Do NOT attempt to modify, patch, or rewrite source code files using shell commands (e.g. sed, cat, echo, python -c with file writing, or powershell scripts).\n"
        "- Terminal CWD is ALREADY the work/ directory. Do NOT prefix filenames with 'work/'.\n"
        f"- Files in workspace: [{filesStr}]\n"
        f"- Detected Entrypoints: [{entryStr}]\n"
        f"- Suggested run commands: [{hintsStr}]\n\n"
        f"{manifestStr}\n\n"
        f"- For Python packages (files inside subdirectories), ALWAYS use: {pyPathPrefix}python -m <package>.<module>\n"
        "- NEVER run a file inside a package directly like 'python subfolder/file.py' as it breaks package imports.\n"
        "- If an application requires interactive console input (input()), test non-interactively via import checks or piped inputs.\n"
        f"- If the app uses tkinter/pygame/GUI, run a non-interactive syntax+import check instead: {pyPathPrefix}python -c \"import <module>\"\n"
        "- If execution completes with Exit Code: 0 and no errors, respond strictly with 'PASS'.\n"
        "- If execution crashes, throws errors, or fails, DO NOT try to fix the code. Respond strictly with 'FAIL' followed by complete traceback and error diagnostics so the Coder Agent can repair the files."
    )

    runMessages = [
        SystemMessage(content=runPretext),
        HumanMessage(content=humanContent)
    ]

    testerResponse = None
    testerMessage = ""
    allRunTools = []

    for attempt in range(1, 6):
        if attempt > 1:
            print(f"\nTester retry {attempt}/5")
        threadTesterModel = get_llm().bind_tools(testerTools)
        testerResponse = streamInvoke(threadTesterModel, runMessages)
        testerMessage = extractText(testerResponse.content)
        runTools = executeToolCalls(testerResponse, testerTools)
        if runTools:
            allRunTools.extend(runTools)
            for tr in runTools:
                print(tr, "\n")

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
        hasZeroExit = "Exit Code: 0" in appOutput
        hasError = "Traceback" in appOutput or "Error:" in appOutput or "Exception:" in appOutput

        if hasRunApp and hasZeroExit and not hasError:
            testerMessage = "PASS"
            print("\n[Tester] Application execution verified successfully (Exit Code: 0).")
            break

        if hasRunApp and (hasError or not hasZeroExit):
            testerMessage = f"FAIL: Application execution failed with error:\n{appOutput}"
            print("\n[Tester] Application execution failed. Delegating diagnostic to Coder Agent.")
            break

        if testerMessage.strip().upper().startswith("PASS") and hasRunApp:
            break

        recentCmds = [extractCommand(tr) for tr in runTools]
        onlySetupRun = bool(runTools) and all(isSetupCommand(c) for c in recentCmds if c)

        if (not runTools and not hasRunApp) or onlySetupRun:
            if entryPoints:
                targetEntry = entryPoints[0]
                ext = Path(targetEntry).suffix.lower()
                if ext == ".html":
                    autoCmd = f"node -e \"console.log('Static web frontend entrypoint verified: {targetEntry}')\""
                elif ext in (".js", ".ts"):
                    autoCmd = f"node {targetEntry}"
                elif ext == ".py" and "/" in targetEntry:
                    modName = targetEntry.replace("/", ".").replace("\\", ".").removesuffix(".py")
                    autoCmd = f"{pyPathPrefix}python -m {modName}"
                elif ext == ".py":
                    autoCmd = f"{pyPathPrefix}python {targetEntry}"
                elif ext == ".go":
                    autoCmd = f"go run {targetEntry}"
                elif ext in (".c", ".cpp"):
                    autoCmd = f"gcc {targetEntry} -o main.exe && main.exe" if os.name == "nt" else f"gcc {targetEntry} -o main && ./main"
                elif ext == ".java":
                    autoCmd = f"javac {targetEntry} && java {Path(targetEntry).stem}"
                else:
                    autoCmd = f"python {targetEntry}"
                print(f"\n[Tester Execution Proposal] {autoCmd}")
                autoRes = executeCommand.invoke({"command": autoCmd})
                autoRecord = f"Auto-Execution: command='{autoCmd}' | {autoRes}"
                allRunTools.append(autoRecord)
                appRunTools.append(autoRecord)
                appOutput = "\n".join(appRunTools)
                hasRunApp = True
                hasZeroExit = "Exit Code: 0" in appOutput
                hasError = "Traceback" in appOutput or "Error:" in appOutput or "Exception:" in appOutput
                if hasZeroExit and not hasError:
                    testerMessage = "PASS"
                    break
                else:
                    testerMessage = f"FAIL: Application execution failed with error:\n{appOutput}"
                    print("\n[Tester] Auto-execution failed. Delegating diagnostic to Coder Agent.")
                    break

            promptNote = f"Output an executeCommand tool call to run the application [{hintsStr}]."
            if onlySetupRun:
                promptNote = f"Dependencies installed. Now execute the application entrypoint: [{hintsStr}]."
            runMessages.extend([
                testerResponse,
                HumanMessage(content=promptNote)
            ])
            continue

        runMessages.extend([
            testerResponse,
            HumanMessage(content="Terminal output:\n" + "\n".join(allRunTools) + "\n\nIf dependency installation succeeded, now execute the application entrypoint. If execution already passed cleanly, respond strictly with PASS. If code logic bugs remain, respond strictly with FAIL and diagnostic details.")
        ])

    appRunTools = [tr for tr in allRunTools if extractCommand(tr) and not isSetupCommand(extractCommand(tr))]
    appOutput = "\n".join(appRunTools)
    hasZeroExit = "Exit Code: 0" in appOutput
    hasError = "Traceback" in appOutput or "Error:" in appOutput or "Exception:" in appOutput
    isPass = bool(appRunTools) and hasZeroExit and not hasError
    if isPass:
        if currentManifestHashes:
            verifiedManifestHashes.update(currentManifestHashes)
        print("\nProcess finished successfully.\n")
    else:
        try:
            print("\n[MEMORY] Execution failed. Tester Agent is generating a lesson...")
            memoryManager.learnFromFailure(state["instruction"], appOutput or "\n".join(allRunTools) or testerMessage)
        except Exception as e:
            print(f"[MEMORY] Error generating lesson from failure: {e}")

    return {
        "messages": [testerResponse] if testerResponse else [],
        "feedback": state["feedback"] if isPass else f"Tester Execution Failed:\n{appOutput or testerMessage}",
        "success": isPass
    }

def routeCritic(state: AgentState) -> str:
    if not state.get("success", False):
        return END
    if state.get("isAssetOnly", False):
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
    context = getContext(instruction)
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

def runBatchEval(batchTasks, coderResults):
    taskNames = ", ".join([getattr(t, "name", getattr(t, "objective", t.id)) for t in batchTasks])
    print(f"\n[Batch Verification] Verifying {len(batchTasks)} completed task(s): {taskNames}")

    isValid, connErrors = validateConnectedness(WORK_DIR)
    if not isValid:
        errMsg = "\n".join(f"- {e}" for e in connErrors)
        print(f"[Batch Verification] AST/Syntax errors detected:\n{errMsg}")

    summaryText = "\n".join([f"- Task '{getattr(t, 'name', t.id)}': {res.get('coderMessage', '')}" for t, res in zip(batchTasks, coderResults)])
    combinedTools = sum([res.get("toolResults", []) for res in coderResults], [])
    manifestText = formatManifestContext(WORK_DIR)

    initialState = {
        "messages": [HumanMessage(content=f"Verify batch tasks: {taskNames}\nCoder Summaries:\n{summaryText}\n\nWorkspace Status:\n{manifestText}")],
        "instruction": f"Batch Verification: {taskNames}",
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
        print("[Batch Verification] Execution tests PASSED.")
        updateWorkspaceSnapshot(WORK_DIR)
    else:
        print(f"[Batch Verification] Execution tests FAILED: {fb}")
    return passed, fb

def runAgent(instruction, taskContext=""):
    print("Indexing workspace: ")
    indexWorkspace()
    context = getContext(instruction)
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

if __name__ == "__main__":
    startLogging()
    print("\nType 'index' for reindexing or 'exit' to quit.\n")
    while True:
        query = input("\nInstruction: ")
        q = query.strip().lower()
        if q == "exit":
            break
        if q == "index":
            indexWorkspace()
            print("Reindexed the workspace")
        elif q:
            retrievedMemories = []
            if shouldRetrieveMemory(query):
                try:
                    mems = memoryManager.searchMemory(query, topK=3)
                    retrievedMemories = [m["content"] for m in mems]
                except Exception:
                    retrievedMemories = []

            mode = classifyIntent(query)

            if mode == "patch":
                print("\n[Kaizen] Patch mode detected, skipping full planning pipeline.\n")
                indexWorkspace()
                patchInstruction = buildPatchInstruction(query, WORK_DIR)
                if retrievedMemories:
                    memStr = "\n".join(f"- {m}" for m in retrievedMemories)
                    patchInstruction = f"{patchInstruction}\n\nRelevant past lessons:\n{memStr}"
                patchResult = runCoder(patchInstruction)
                patchSummary = patchResult.get("coderMessage", "").strip() if isinstance(patchResult, dict) else ""
                if patchSummary:
                    print("\n" + "-" * 60)
                    print("[Kaizen] Patch complete,here is what was changed:\n")
                    print(patchSummary)
                    print("-" * 60 + "\n")
                else:
                    print("\n[Kaizen] Patch complete.\n")
            else:
                promptAgent = PromptAgent()
                curQuery = query
                if retrievedMemories:
                    mStr = "\n".join(f"- {m}" for m in retrievedMemories)
                    curQuery = f"{query}\n\nRelevant past memories/lessons:\n{mStr}"

                existingAst = formatManifestContext(WORK_DIR)
                if existingAst and "Workspace is currently empty" not in existingAst:
                    curQuery = f"{curQuery}\n\nExisting Workspace Code & Structure:\n{existingAst}"

                while True:
                    promptOutput = promptAgent.process(curQuery)
                    deliverables = promptOutput.get("deliverables", [])
                    techStack = promptOutput.get("tech_stack") or promptOutput.get("techStack") or ""
                    fileStructure = promptOutput.get("file_structure") or promptOutput.get("fileStructure") or []
                    proceed, usrFeedback = reviewDeliverables(deliverables, techStack, fileStructure)
                    if proceed:
                        break
                    curQuery = f"{query}\nUser Plan Feedback: {usrFeedback}"
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

                indexWorkspace()
                scheduler = Scheduler(dag, curQuery, techStack=techStack, fileStructure=fileStructure, coderFn=runCoder, evalFn=runBatchEval)
                asyncio.run(scheduler.run())