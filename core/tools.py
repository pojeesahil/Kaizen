import os
import re
import ast
import shutil
import subprocess
from pathlib import Path
from langchain_core.tools import tool
from core.connectedness import mergePythonImports

WORK_DIR = Path(__file__).resolve().parent.parent / "work"

def resolvePath(path: str) -> Path:
    WORK_DIR.mkdir(parents=True, exist_ok=True)
    targetPath = Path(path)
    if targetPath.is_absolute():
        return targetPath
    parts = [p for p in targetPath.parts if p not in ("work", ".")]
    if parts:
        return (WORK_DIR / Path(*parts)).resolve()
    return (WORK_DIR / targetPath.name).resolve()

@tool
def createFile(path: str, content: str) -> str:
    """Create a new file with specified content in the workspace."""
    filePath = resolvePath(path)
    filePath.parent.mkdir(parents=True, exist_ok=True)
    with open(filePath, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Success: Created file at {filePath}"

@tool
def editFile(path: str, newContent: str) -> str:
    """Modify an existing file while automatically preserving existing imports."""
    filePath = resolvePath(path)
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
    return f"Success: Modified file at {filePath}"

@tool
def addImport(path: str, module: str, name: str = "", alias: str = "") -> str:
    """Insert an import statement at the top of a file without touching existing code."""
    filePath = resolvePath(path)
    filePath.parent.mkdir(parents=True, exist_ok=True)
    if not filePath.exists():
        with open(filePath, "w", encoding="utf-8") as f:
            f.write("")

    with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
        src = f.read()

    importLine = f"from {module} import {name}" if name else f"import {module}"
    if alias:
        importLine += f" as {alias}"

    if importLine in src:
        return f"Success: Import '{importLine}' already present in {filePath}"

    lines = src.splitlines(keepends=True)
    insertIdx = 0
    for i, line in enumerate(lines):
        if line.startswith(("import ", "from ")):
            insertIdx = i + 1
        elif line.strip() and not line.startswith("#") and insertIdx > 0:
            break

    lines.insert(insertIdx, importLine + "\n")
    with open(filePath, "w", encoding="utf-8") as f:
        f.writelines(lines)
    return f"Success: Added import '{importLine}' to {filePath}"

@tool
def upsertFunction(path: str, functionCode: str) -> str:
    """Add or replace functions in a file at the AST level without modifying other code."""
    filePath = resolvePath(path)
    filePath.parent.mkdir(parents=True, exist_ok=True)
    try:
        fnTree = ast.parse(functionCode.strip())
        fnNodes = [n for n in fnTree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        if not fnNodes:
            return "Error: Provided code does not contain any valid function definitions."
    except Exception as e:
        return f"Error parsing function code: {str(e)}"

    if not filePath.exists():
        with open(filePath, "w", encoding="utf-8") as f:
            f.write(functionCode.strip() + "\n")
        names = ", ".join(n.name for n in fnNodes)
        return f"Success: Created {filePath} with function(s) '{names}'"

    with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
        src = f.read()

    processedNames = []
    for fnNode in fnNodes:
        fnName = fnNode.name
        processedNames.append(fnName)
        singleFnCode = ast.get_source_segment(functionCode.strip(), fnNode) or functionCode.strip()

        replaced = False
        try:
            fileTree = ast.parse(src, filename=str(filePath))
            targetNode = next((n for n in fileTree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == fnName), None)
            if targetNode and hasattr(targetNode, "lineno") and hasattr(targetNode, "end_lineno"):
                lines = src.splitlines(keepends=True)
                before = lines[:targetNode.lineno - 1]
                after = lines[targetNode.end_lineno:]
                src = "".join(before) + singleFnCode.strip() + "\n" + "".join(after)
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
    return f"Success: Upserted function(s) '{', '.join(processedNames)}' in {filePath}"

@tool
def upsertClass(path: str, classCode: str) -> str:
    """Add or replace classes in a file at the AST level without modifying other code."""
    filePath = resolvePath(path)
    filePath.parent.mkdir(parents=True, exist_ok=True)
    try:
        clsTree = ast.parse(classCode.strip())
        clsNodes = [n for n in clsTree.body if isinstance(n, ast.ClassDef)]
        if not clsNodes:
            return "Error: Provided code does not contain any valid class definitions."
    except Exception as e:
        return f"Error parsing class code: {str(e)}"

    if not filePath.exists():
        with open(filePath, "w", encoding="utf-8") as f:
            f.write(classCode.strip() + "\n")
        names = ", ".join(n.name for n in clsNodes)
        return f"Success: Created {filePath} with class(es) '{names}'"

    with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
        src = f.read()

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
    return f"Success: Upserted class(es) '{', '.join(processedNames)}' in {filePath}"

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
        return f"Success: Appended content before main entrypoint in {filePath}"

    spacing = "\n\n" if existing and not existing.endswith("\n\n") else "\n" if existing and not existing.endswith("\n") else ""
    with open(filePath, "a", encoding="utf-8") as f:
        f.write(spacing + content.strip() + "\n")
    return f"Success: Appended content to {filePath}"

@tool
def replaceBlock(path: str, targetSnippet: str, replacementSnippet: str) -> str:
    """Replace an exact block or snippet in a file without touching the rest of the file."""
    filePath = resolvePath(path)
    if not filePath.exists():
        return f"Error: File {path} does not exist."

    with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    if targetSnippet not in content:
        return f"Error: targetSnippet not found in {path}. Make sure the target text matches exactly."

    updated = content.replace(targetSnippet, replacementSnippet, 1)
    with open(filePath, "w", encoding="utf-8") as f:
        f.write(updated)
    return f"Success: Replaced block in {filePath}"

@tool
def deleteResource(path: str) -> str:
    """Delete a specific file or folder from the workspace."""
    resPath = resolvePath(path)
    if not resPath.exists():
        return f"Error: {path} not found."
    if resPath.is_dir():
        shutil.rmtree(resPath)
        return f"Success: Deleted folder {resPath}"
    else:
        resPath.unlink()
        return f"Success: Deleted file {resPath}"

@tool
def readFile(path: str) -> str:
    """Read the full content of a file in the workspace."""
    filePath = resolvePath(path)
    if not filePath.exists():
        return f"Error: File {path} does not exist."
    with open(filePath, "r", encoding="utf-8") as f:
        return f.read()

@tool
def executeCommand(command: str) -> str:
    """Execute a shell command inside the workspace directory."""
    print(f"\n[Command Approval] {command}")
    confirm = input("Execute command? (y/n): ").strip().lower()
    if confirm != 'y':
        return "Command execution rejected by user."

    try:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        cmdLower = command.lower()
        isAppRun = "python " in cmdLower or "node " in cmdLower or "flask " in cmdLower
        cmdTimeout = 8 if isAppRun else 30

        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(WORK_DIR.resolve()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        try:
            stdoutData, stderrData = proc.communicate(timeout=cmdTimeout)
            output = f"Exit Code: {proc.returncode}\n"
            if stdoutData:
                output += f"STDOUT:\n{stdoutData}\n"
            if stderrData:
                output += f"STDERR:\n{stderrData}\n"
            return output

        except subprocess.TimeoutExpired:
            if os.name == 'nt' and proc.pid:
                subprocess.run(
                    f"taskkill /F /T /PID {proc.pid}",
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
            else:
                proc.kill()

            stdoutData, stderrData = proc.communicate()
            stdoutText = stdoutData or ""
            stderrText = stderrData or ""
            hasError = "Traceback" in stderrText or "Error:" in stderrText or "SyntaxError" in stderrText

            if not hasError:
                output = "Exit Code: 0 (Process started successfully)\n"
                if stdoutText:
                    output += f"STDOUT:\n{stdoutText}\n"
                return output
            return f"Error: Command '{command}' timed out with errors:\n{stderrText}"

    except Exception as e:
        return f"Error executing command: {str(e)}"

tools = [
    createFile,
    editFile,
    addImport,
    upsertFunction,
    upsertClass,
    appendToFile,
    replaceBlock,
    deleteResource,
    readFile,
    executeCommand
]