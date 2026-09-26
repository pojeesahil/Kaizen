import os
import re
import ast
import time
import shutil
import threading
import subprocess
import urllib.request
from pathlib import Path
from langchain_core.tools import tool
from ddgs import DDGS
from core.connectedness import mergePythonImports
from core.config import autoApprove

WORK_DIR = Path(__file__).resolve().parent.parent / "work"

def syncCag(filePath: Path):
    try:
        from cag.cag import updateCagFile
        updateCagFile(str(filePath), baseDir=str(WORK_DIR))
    except Exception:
        pass

_syncCAG = syncCag

def resolvePath(path: str) -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    targetPath = Path(path)
    if targetPath.is_absolute():
        if str(targetPath.resolve()).startswith(str(WORK_DIR.resolve())):
            return targetPath.resolve()
        parts = [p for p in targetPath.parts if p not in ("work", ".", targetPath.anchor)]
        return (WORK_DIR / Path(*parts)).resolve() if parts else WORK_DIR
    parts = [p for p in targetPath.parts if p not in ("work", ".")]
    if parts:
        return (WORK_DIR / Path(*parts)).resolve()
    return (WORK_DIR / targetPath.name).resolve()

@tool
def createFile(path: str, content: str) -> str:
    """Create a new file with specified content in the workspace."""
    filePath = resolvePath(path)
    if "node_modules" in filePath.parts:
        return f"Error: Modifying files inside node_modules is not allowed."
    filePath.parent.mkdir(parents=True, exist_ok=True)
    with open(filePath, "w", encoding="utf-8") as f:
        f.write(content)
    syncCag(filePath)
    return f"Success: Created file at {filePath}"

@tool
def createFiles(files: dict) -> str:
    """Create multiple files at once in the workspace using a dictionary mapping relative file paths to their content."""
    createdPaths = []
    failedPaths = []
    for relPath, content in files.items():
        try:
            filePath = resolvePath(str(relPath))
            if "node_modules" in filePath.parts:
                failedPaths.append(f"{relPath}: modifying node_modules is not allowed")
                continue
            filePath.parent.mkdir(parents=True, exist_ok=True)
            with open(filePath, "w", encoding="utf-8") as f:
                f.write(str(content))
            syncCag(filePath)
            createdPaths.append(str(filePath))
        except Exception as err:
            failedPaths.append(f"{relPath}: {str(err)}")
    resultMessage = ""
    if createdPaths:
        joinedCreated = "\n".join(createdPaths)
        resultMessage += f"Success: Created {len(createdPaths)} file(s):\n{joinedCreated}"
    if failedPaths:
        joinedFailed = "\n".join(failedPaths)
        resultMessage += f"\nErrors:\n{joinedFailed}"
    return resultMessage

@tool
def downloadAsset(url: str, path: str) -> str:
    """Download an asset or file from a URL to a specified workspace path."""
    try:
        dest = resolvePath(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        with open(dest, "wb") as f:
            f.write(data)
        syncCag(dest)
        return f"Success: Downloaded {url} to {dest}"
    except Exception as err:
        return f"Error downloading asset from '{url}': {err}"

@tool
def moveFile(sourcePath: str, destinationPath: str) -> str:
    """Move or rename a file or directory from sourcePath to destinationPath in the workspace."""
    try:
        src = resolvePath(sourcePath)
        dst = resolvePath(destinationPath)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        syncCag(src)
        syncCag(dst)
        return f"Success: Moved {src} to {dst}"
    except Exception as err:
        return f"Error moving file: {err}"

@tool
def finishTask(summary: str) -> str:
    """Explicitly declare that all task requirements, files, and connections are fully implemented and verified."""
    return f"Task Completed: {summary.strip()}"

@tool
def editFile(path: str, newContent: str) -> str:
    """Modify an existing file while automatically preserving existing imports."""
    filePath = resolvePath(path)
    if "node_modules" in filePath.parts:
        return f"Error: Modifying files inside node_modules is not allowed."
    filePath.parent.mkdir(parents=True, exist_ok=True)
    merged = newContent
    if filePath.exists() and filePath.suffix.lower() == ".py":
        try:
            with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
                existing = f.read()
            merged = mergePythonImports(existing, newContent)
        except Exception:
            merged = newContent

    with open(filePath, "w", encoding="utf-8") as f:
        f.write(merged)
    syncCag(filePath)
    return f"Success: Modified file at {filePath}"

def findBalancedBlock(src: str, openBraceIdx: int) -> int:
    depth = 0
    inStr = None
    i = openBraceIdx
    n = len(src)
    while i < n:
        ch = src[i]
        if inStr:
            if ch == "\\" and i + 1 < n:
                i += 2
                continue
            if ch == inStr:
                inStr = None
        else:
            if ch in ('"', "'", "`"):
                inStr = ch
            elif ch == "/" and i + 1 < n:
                if src[i + 1] == "/":
                    eol = src.find("\n", i)
                    i = eol if eol != -1 else n
                    continue
                elif src[i + 1] == "*":
                    closeComment = src.find("*/", i + 2)
                    i = closeComment + 2 if closeComment != -1 else n
                    continue
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i + 1
        i += 1
    return -1

def replaceFunctionInSrc(src: str, fnName: str, newCode: str, isPy: bool) -> tuple[bool, str]:
    if isPy:
        pat = rf"^[ \t]*(?:@\w+.*?\n[ \t]*)*(?:async\s+)?def\s+{re.escape(fnName)}\s*\([^)]*\)(?:\s*->\s*[^:]+)?:"
        match = re.search(pat, src, re.MULTILINE)
        if match:
            startIdx = match.start()
            sub = src[match.end():]
            lines = sub.splitlines(keepends=True)
            bodyLen = 0
            for line in lines:
                if line.strip() == "" or line.startswith((" ", "\t")):
                    bodyLen += len(line)
                else:
                    break
            endIdx = match.end() + bodyLen
            updated = src[:startIdx] + newCode.strip() + "\n" + src[endIdx:]
            return True, updated
        return False, src

    patterns = [
        rf"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+{re.escape(fnName)}\s*\(",
        rf"(?:export\s+)?(?:const|let|var)\s+{re.escape(fnName)}\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>",
        rf"(?:export\s+)?(?:const|let|var)\s+{re.escape(fnName)}\s*=\s*(?:async\s*)?function",
        rf"func\s+(?:\([^)]*\)\s+)?{re.escape(fnName)}\s*\(",
        r"(?:public|private|protected|static|final|native|synchronized|async|virtual|override|void|[a-zA-Z0-9_<>[\]*&]+)\s+" + re.escape(fnName) + r"\s*\([^;{}]*\)\s*(?:const\s*)?\{",
    ]

    for pat in patterns:
        match = re.search(pat, src)
        if match:
            startIdx = match.start()
            braceIdx = src.find("{", match.end() - 1)
            if braceIdx != -1:
                endIdx = findBalancedBlock(src, braceIdx)
                if endIdx != -1:
                    if endIdx < len(src) and src[endIdx] == ";":
                        endIdx += 1
                    updated = src[:startIdx] + newCode.strip() + "\n" + src[endIdx:].lstrip("\r\n")
                    return True, updated
    return False, src

def replaceClassInSrc(src: str, clsName: str, newCode: str, isPy: bool) -> tuple[bool, str]:
    if isPy:
        pat = rf"^[ \t]*(?:@\w+.*?\n[ \t]*)*class\s+{re.escape(clsName)}\b[^:]*:"
        match = re.search(pat, src, re.MULTILINE)
        if match:
            startIdx = match.start()
            sub = src[match.end():]
            lines = sub.splitlines(keepends=True)
            bodyLen = 0
            for line in lines:
                if line.strip() == "" or line.startswith((" ", "\t")):
                    bodyLen += len(line)
                else:
                    break
            endIdx = match.end() + bodyLen
            updated = src[:startIdx] + newCode.strip() + "\n" + src[endIdx:]
            return True, updated
        return False, src

    patterns = [
        rf"(?:export\s+)?(?:default\s+)?(?:abstract\s+)?(?:class|interface|struct|enum)\s+{re.escape(clsName)}\b",
        rf"type\s+{re.escape(clsName)}\s+(?:struct|interface)\b",
    ]

    for pat in patterns:
        match = re.search(pat, src)
        if match:
            startIdx = match.start()
            braceIdx = src.find("{", match.end() - 1)
            if braceIdx != -1:
                endIdx = findBalancedBlock(src, braceIdx)
                if endIdx != -1:
                    if endIdx < len(src) and src[endIdx] == ";":
                        endIdx += 1
                    updated = src[:startIdx] + newCode.strip() + "\n" + src[endIdx:].lstrip("\r\n")
                    return True, updated
    return False, src

@tool
def upsertFunction(path: str, functionCode: str) -> str:
    """Add or replace functions in a file across any language without modifying other code."""
    filePath = resolvePath(path)
    filePath.parent.mkdir(parents=True, exist_ok=True)
    isPy = filePath.suffix.lower() == ".py"

    fnNodes = []
    if isPy:
        try:
            fnTree = ast.parse(functionCode.strip())
            fnNodes = [n for n in fnTree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        except Exception:
            fnNodes = []

    if not filePath.exists():
        with open(filePath, "w", encoding="utf-8") as f:
            f.write(functionCode.strip() + "\n")
        syncCag(filePath)
        names = ", ".join(n.name for n in fnNodes) if fnNodes else "function"
        return f"Success: Created {filePath} with function(s) '{names}'"

    with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
        src = f.read()

    # Python AST-level replacement with regex fallback
    if isPy and fnNodes:
        processedNames = []
        for fnNode in fnNodes:
            fnName = fnNode.name
            processedNames.append(fnName)
            singleFnCode = ast.get_source_segment(functionCode.strip(), fnNode) or functionCode.strip()
            isMethod = bool(fnNode.args.args and fnNode.args.args[0].arg in ("self", "cls"))

            replaced = False
            try:
                fileTree = ast.parse(src, filename=str(filePath))
                for node in fileTree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fnName:
                        lines = src.splitlines(keepends=True)
                        before = lines[:node.lineno - 1]
                        after = lines[node.end_lineno:]
                        src = "".join(before) + singleFnCode.strip() + "\n" + "".join(after)
                        replaced = True
                        break
                    elif isinstance(node, ast.ClassDef):
                        for classChild in node.body:
                            if isinstance(classChild, (ast.FunctionDef, ast.AsyncFunctionDef)) and classChild.name == fnName:
                                lines = src.splitlines(keepends=True)
                                before = lines[:classChild.lineno - 1]
                                after = lines[classChild.end_lineno:]
                                indentedCode = "\n".join("    " + l if l.strip() else l for l in singleFnCode.strip().splitlines())
                                src = "".join(before) + indentedCode + "\n" + "".join(after)
                                replaced = True
                                break
                        if replaced:
                            break
            except Exception:
                pass

            if not replaced:
                replaced, src = replaceFunctionInSrc(src, fnName, singleFnCode, isPy=True)

            if not replaced and isMethod:
                try:
                    fileTree = ast.parse(src, filename=str(filePath))
                    classes = [n for n in fileTree.body if isinstance(n, ast.ClassDef)]
                    if classes:
                        targetClass = classes[0]
                        lines = src.splitlines(keepends=True)
                        insertLine = targetClass.end_lineno
                        indentedCode = "\n".join("    " + l if l.strip() else l for l in singleFnCode.strip().splitlines())
                        before = lines[:insertLine]
                        after = lines[insertLine:]
                        src = "".join(before) + "\n" + indentedCode + "\n" + "".join(after)
                        replaced = True
                except Exception:
                    pass

            if not replaced:
                mainMatch = re.search(r"\nif\s+__name__\s*==\s*['\"]__main__['\"]\s*:", src)
                if mainMatch:
                    splitIdx = mainMatch.start()
                    prefix = src[:splitIdx].rstrip()
                    mainBlock = src[splitIdx:].lstrip("\n")
                    src = f"{prefix}\n\n{singleFnCode.strip()}\n\n{mainBlock}\n"
                else:
                    spacing = "\n\n" if src and not src.endswith("\n\n") else "\n" if src and not src.endswith("\n") else ""
                    src = src + spacing + singleFnCode.strip() + "\n"

        with open(filePath, "w", encoding="utf-8") as f:
            f.write(src)
        syncCag(filePath)
        return f"Success: Upserted function(s) '{', '.join(processedNames)}' in {filePath}"

    # Universal non-Python or regex-based replacement
    namesFound = (
        re.findall(r"(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)", functionCode) or
        re.findall(r"(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=", functionCode) or
        re.findall(r"func\s+(?:\([^)]*\)\s+)?([a-zA-Z0-9_]+)\s*\(", functionCode) or
        re.findall(r"def\s+([a-zA-Z0-9_]+)", functionCode) or
        re.findall(r"(?:void|[a-zA-Z0-9_<>[\]*&]+)\s+([a-zA-Z0-9_]+)\s*\(", functionCode)
    )
    fnName = namesFound[0] if namesFound else "function"

    replaced, newSrc = replaceFunctionInSrc(src, fnName, functionCode, isPy=isPy)
    if replaced:
        with open(filePath, "w", encoding="utf-8") as f:
            f.write(newSrc)
        syncCag(filePath)
        return f"Success: Modified existing function '{fnName}' in-place in {filePath}"

    spacing = "\n\n" if src and not src.endswith("\n\n") else "\n" if src and not src.endswith("\n") else ""
    src = src + spacing + functionCode.strip() + "\n"

    with open(filePath, "w", encoding="utf-8") as f:
        f.write(src)
    syncCag(filePath)
    return f"Success: Added function '{fnName}' to {filePath}"

@tool
def upsertClass(path: str, classCode: str) -> str:
    """Add or replace classes in a file across any language without modifying other code."""
    filePath = resolvePath(path)
    filePath.parent.mkdir(parents=True, exist_ok=True)
    isPy = filePath.suffix.lower() == ".py"

    clsNodes = []
    if isPy:
        try:
            clsTree = ast.parse(classCode.strip())
            clsNodes = [n for n in clsTree.body if isinstance(n, ast.ClassDef)]
        except Exception:
            clsNodes = []

    if not filePath.exists():
        with open(filePath, "w", encoding="utf-8") as f:
            f.write(classCode.strip() + "\n")
        syncCag(filePath)
        names = ", ".join(n.name for n in clsNodes) if clsNodes else "class"
        return f"Success: Created {filePath} with class(es) '{names}'"

    with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
        src = f.read()

    # Python AST-level replacement with fallback
    if isPy and clsNodes:
        processedNames = []
        for clsNode in clsNodes:
            clsName = clsNode.name
            processedNames.append(clsName)
            singleClsCode = ast.get_source_segment(classCode.strip(), clsNode) or classCode.strip()

            replaced = False
            try:
                fileTree = ast.parse(src, filename=str(filePath))
                targetNode = next((n for n in fileTree.body if isinstance(n, ast.ClassDef) and n.name == clsName), None)
                if targetNode and hasattr(targetNode, "lineno") and hasattr(targetNode, "end_lineno"):
                    lines = src.splitlines(keepends=True)
                    before = lines[:targetNode.lineno - 1]
                    after = lines[targetNode.end_lineno:]
                    src = "".join(before) + singleClsCode.strip() + "\n" + "".join(after)
                    replaced = True
            except Exception:
                pass

            if not replaced:
                replaced, src = replaceClassInSrc(src, clsName, singleClsCode, isPy=True)

            if not replaced:
                mainMatch = re.search(r"\nif\s+__name__\s*==\s*['\"]__main__['\"]\s*:", src)
                if mainMatch:
                    splitIdx = mainMatch.start()
                    prefix = src[:splitIdx].rstrip()
                    mainBlock = src[splitIdx:].lstrip("\n")
                    src = f"{prefix}\n\n{singleClsCode.strip()}\n\n{mainBlock}\n"
                else:
                    spacing = "\n\n" if src and not src.endswith("\n\n") else "\n" if src and not src.endswith("\n") else ""
                    src = src + spacing + singleClsCode.strip() + "\n"

        with open(filePath, "w", encoding="utf-8") as f:
            f.write(src)
        syncCag(filePath)
        return f"Success: Upserted class(es) '{', '.join(processedNames)}' in {filePath}"

    # Universal non-Python or regex-based replacement
    namesFound = (
        re.findall(r"(?:class|interface|struct|enum)\s+([a-zA-Z0-9_$]+)", classCode) or
        re.findall(r"type\s+([a-zA-Z0-9_]+)\s+(?:struct|interface)", classCode)
    )
    clsName = namesFound[0] if namesFound else "class"

    replaced, newSrc = replaceClassInSrc(src, clsName, classCode, isPy=isPy)
    if replaced:
        with open(filePath, "w", encoding="utf-8") as f:
            f.write(newSrc)
        syncCag(filePath)
        return f"Success: Modified existing class '{clsName}' in-place in {filePath}"

    spacing = "\n\n" if src and not src.endswith("\n\n") else "\n" if src and not src.endswith("\n") else ""
    src = src + spacing + classCode.strip() + "\n"

    with open(filePath, "w", encoding="utf-8") as f:
        f.write(src)
    syncCag(filePath)
    return f"Success: Added class '{clsName}' to {filePath}"

@tool
def appendToFile(path: str, content: str) -> str:
    """Append content to a file before the main entrypoint block."""
    filePath = resolvePath(path)
    filePath.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if filePath.exists():
        with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
            existing = f.read()

    mainMatch = re.search(r"\nif\s+__name__\s*==\s*['\"]__main__['\"]\s*:", existing)
    if mainMatch:
        splitIdx = mainMatch.start()
        prefix = existing[:splitIdx].rstrip()
        mainBlock = existing[splitIdx:].lstrip("\n")
        newBody = f"{prefix}\n\n{content.strip()}\n\n{mainBlock}\n"
        with open(filePath, "w", encoding="utf-8") as f:
            f.write(newBody)
        syncCag(filePath)
        return f"Success: Appended content before main entrypoint in {filePath}"

    spacing = "\n\n" if existing and not existing.endswith("\n\n") else "\n" if existing and not existing.endswith("\n") else ""
    with open(filePath, "a", encoding="utf-8") as f:
        f.write(spacing + content.strip() + "\n")
    syncCag(filePath)
    return f"Success: Appended content to {filePath}"

@tool
def replaceBlock(path: str, targetSnippet: str, replacementSnippet: str) -> str:
    """Replace an exact block or snippet in a file without touching the rest of the file."""
    filePath = resolvePath(path)
    if "node_modules" in filePath.parts:
        return f"Error: Modifying files inside node_modules is not allowed."
    if not filePath.exists():
        return f"Error: File {path} does not exist."

    with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    if targetSnippet not in content:
        return f"Error: targetSnippet not found in {path}. Make sure the target text matches exactly."

    updated = content.replace(targetSnippet, replacementSnippet, 1)
    with open(filePath, "w", encoding="utf-8") as f:
        f.write(updated)
    syncCag(filePath)
    return f"Success: Replaced block in {filePath}"

@tool
def deleteResource(path: str) -> str:
    """Delete a specific file or folder from the workspace."""
    resPath = resolvePath(path)
    if "node_modules" in resPath.parts and resPath.name != "node_modules":
        return f"Error: Deleting inside node_modules is not allowed."
    if not resPath.exists():
        return f"Error: {path} not found."
    if resPath.is_dir():
        shutil.rmtree(resPath)
        syncCag(resPath)
        return f"Success: Deleted folder {resPath}"
    else:
        resPath.unlink()
        syncCag(resPath)
        return f"Success: Deleted file {resPath}"

@tool
def readFile(path: str) -> str:
    """Read the full content of a file in the workspace."""
    filePath = resolvePath(path)
    if "node_modules" in filePath.parts:
        return f"Error: Reading files inside node_modules is not allowed."
    if not filePath.exists():
        return f"Error: File {path} does not exist."
    with open(filePath, "r", encoding="utf-8") as f:
        return f.read()

@tool
def grepFiles(query: str, path: str = ".") -> str:
    """Search for matching lines of text or symbols across workspace files without reading entire files."""
    targetPath = resolvePath(path)
    if not targetPath.exists():
        return f"Error: Path '{path}' does not exist."

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

    matchedLines = []
    maxMatches = 50

    if targetPath.is_file():
        filesToSearch = [targetPath]
    else:
        filesToSearch = []
        for root, dirs, files in os.walk(targetPath):
            dirs[:] = [d for d in dirs if d not in skipDirs and not d.startswith(".")]
            for fname in sorted(files):
                filePath = Path(root) / fname
                filesToSearch.append(filePath)

    for filePath in filesToSearch:
        if "node_modules" in filePath.parts:
            continue
        try:
            relStr = filePath.relative_to(WORK_DIR).as_posix()
        except Exception:
            relStr = filePath.as_posix()
        try:
            with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
                for lineNum, line in enumerate(f, 1):
                    if query in line:
                        matchedLines.append(f"{relStr}:{lineNum}: {line.strip()}")
                        if len(matchedLines) >= maxMatches:
                            break
        except Exception:
            continue
        if len(matchedLines) >= maxMatches:
            break

    if not matchedLines:
        return f"No matches found for '{query}' in '{path}'."

    output = "\n".join(matchedLines)
    if len(matchedLines) >= maxMatches:
        output += f"\n(Results capped at {maxMatches} matches)"
    return output

@tool
def executeCommand(command: str) -> str:
    """Execute a shell command inside the workspace directory."""
    print(f"\n[Command Approval] {command}")
    if autoApprove:
        confirm = "y"
    else:
        confirm = input("Execute command? (y/n): ").strip()
    if confirm.lower() != "y":
        guidance = ""
        if confirm.lower() == "n":
            guidance = input("What should Tester execute instead? (press Enter to skip): ").strip()
        elif confirm:
            guidance = confirm
        if guidance:
            return f"Command execution rejected by user. User instruction on what to execute: '{guidance}'. Follow this instruction strictly."
        return "Command execution rejected by user."

    try:
        WORK_DIR.mkdir(parents=True, exist_ok=True)

        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(WORK_DIR.resolve()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        capturedStdout = []
        capturedStderr = []
        isReady = threading.Event()
        readinessMarkers = (
            "http://", "https://", "localhost", "127.0.0.1",
            "ready in", "listening on", "serving at", "compiled successfully"
        )

        def readStream(stream, targetList, checkReady=False):
            try:
                for line in iter(stream.readline, ""):
                    targetList.append(line)
                    if checkReady and any(m in line.lower() for m in readinessMarkers):
                        isReady.set()
            except Exception:
                pass

        tOut = threading.Thread(target=readStream, args=(proc.stdout, capturedStdout, True))
        tErr = threading.Thread(target=readStream, args=(proc.stderr, capturedStderr, False))
        tOut.daemon = True
        tErr.daemon = True
        tOut.start()
        tErr.start()

        cmdLower = command.lower()
        serverKeywords = ("dev", "serve", "start", "watch", "nodemon", "uvicorn", "flask")
        tokens = cmdLower.replace(";", " ").replace("&&", " ").split()
        isServerCmd = any(k in tokens for k in serverKeywords)
        livenessTimeout = 10.0 if isServerCmd else 180.0

        startTime = time.time()
        while True:
            elapsedTime = time.time() - startTime
            if proc.poll() is not None:
                break
            if isReady.is_set():
                time.sleep(0.3)
                break
            if elapsedTime >= livenessTimeout:
                break
            time.sleep(0.1)

        processRunning = proc.poll() is None

        if processRunning:
            if os.name == 'nt' and proc.pid:
                subprocess.run(
                    f"taskkill /F /T /PID {proc.pid}",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                proc.kill()

        stdoutText = "".join(capturedStdout)
        stderrText = "".join(capturedStderr)
        hasError = False
        errorMarkers = [
            "Traceback",
            "Error:",
            "SyntaxError",
            "Exception:"
        ]
        for marker in errorMarkers:
            if marker in stderrText:
                hasError = True
                break

        if isReady.is_set() or (isServerCmd and processRunning and not hasError):
            output = "Exit Code: 0 (Process started successfully)\n"
            if stdoutText:
                output += f"STDOUT:\n{stdoutText}\n"
            return output

        if processRunning and not isServerCmd:
            output = f"Exit Code: 1 (Command timed out after {int(livenessTimeout)}s)\n"
            if stdoutText:
                output += f"STDOUT:\n{stdoutText}\n"
            if stderrText:
                output += f"STDERR:\n{stderrText}\n"
            return output

        output = f"Exit Code: {proc.returncode}\n"
        if stdoutText:
            output += f"STDOUT:\n{stdoutText}\n"
        if stderrText:
            output += f"STDERR:\n{stderrText}\n"
        return output

    except Exception as e:
        return f"Error executing command: {str(e)}"

@tool
def executor(command: str) -> str:
    """Execute a scaffolding or code generation command to initialize project code via CLI."""
    cleanCmd = command.strip()
    lowerCmd = cleanCmd.lower()
    scaffoldTokens = [
        "create",
        "init",
        "new",
        "scaffold",
        "generate",
        "template",
        "setup",
        "vite",
        "install",
        "add",
        "bootstrap"
    ]
    tokens = lowerCmd.replace(";", " ").replace("&&", " ").replace("||", " ").split()
    isScaffold = False
    for tok in tokens:
        for st in scaffoldTokens:
            if st in tok:
                isScaffold = True
                break
        if isScaffold:
            break
    if not isScaffold:
        return "Executor rejected: Command is not a code generation or scaffolding command. Use standard file tools like createFile or editFile for regular coding."
    print(f"\n[Executor] Running generator command: {cleanCmd}")
    return executeCommand.invoke({"command": cleanCmd})

@tool
def searchWeb(query: str) -> str:
    """Search the web using DuckDuckGo for documentation, API usage, examples, and error solutions."""
    try:
        searchHits = list(DDGS().text(query, max_results=5))
        if not searchHits:
            return "No search results found."
        formattedResults = []
        for item in searchHits:
            title = item.get("title", "")
            link = item.get("href", "")
            body = item.get("body", "")
            formattedResults.append(f"Title: {title}\nURL: {link}\nSnippet: {body}")
        return "\n\n".join(formattedResults)
    except Exception as err:
        return f"Error searching web: {err}"

tools = [
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
    executor
]

from core.mcp import getMcpTools
tools.extend(getMcpTools())