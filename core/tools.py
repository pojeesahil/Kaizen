import os
import shutil
import subprocess
from pathlib import Path
from langchain_core.tools import tool

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
    """Creates a new file with the specified content inside the work directory."""
    filePath = resolvePath(path)
    filePath.parent.mkdir(parents=True, exist_ok=True)
    with open(filePath, "w", encoding="utf-8") as f:
        f.write(content)
    return f"Success: Created file at {filePath}"

@tool
def editFile(path: str, newContent: str) -> str:
    """Modify an existing file contents with updated code inside the work directory."""
    filePath = resolvePath(path)
    if not filePath.exists():
        return f"Error: File {path} does not exist."
    with open(filePath, "w", encoding="utf-8") as f:
        f.write(newContent)
    return f"Success: Modified file at {filePath}"

@tool
def deleteResource(path: str) -> str:
    """Delete a specific file or entire directory from the work directory."""
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
    """Read the contents of a file from the work directory."""
    filePath = resolvePath(path)
    if not filePath.exists():
        return f"Error: File {path} does not exist."
    with open(filePath, "r", encoding="utf-8") as f:
        return f.read()

@tool
def executeCommand(command: str) -> str:
    """Executes a CLI command in the terminal inside the work directory and returns the output."""
    print(f"\n[Command Approval] {command}")
    confirm = input("Execute command? (y/n): ").strip().lower()
    if confirm != 'y':
        return "Command execution rejected by user."

    try:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        cmd_lower = command.lower()
        is_app_run = "python " in cmd_lower or "node " in cmd_lower or "flask " in cmd_lower
        cmd_timeout = 8 if is_app_run else 30

        proc = subprocess.Popen(
            command,
            shell=True,
            cwd=str(WORK_DIR.resolve()),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        try:
            stdout_data, stderr_data = proc.communicate(timeout=cmd_timeout)
            output = f"Exit Code: {proc.returncode}\n"
            if stdout_data:
                output += f"STDOUT:\n{stdout_data}\n"
            if stderr_data:
                output += f"STDERR:\n{stderr_data}\n"
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

            stdout_data, stderr_data = proc.communicate()
            stdout_text = stdout_data or ""
            stderr_text = stderr_data or ""
            has_error = "Traceback" in stderr_text or "Error:" in stderr_text or "SyntaxError" in stderr_text

            if not has_error:
                output = "Exit Code: 0 (Process started successfully)\n"
                if stdout_text:
                    output += f"STDOUT:\n{stdout_text}\n"
                return output
            return f"Error: Command '{command}' timed out with errors:\n{stderr_text}"

    except Exception as e:
        return f"Error executing command: {str(e)}"

tools = [createFile, editFile, deleteResource, readFile, executeCommand]