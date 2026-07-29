import shutil
from pathlib import Path
from langchain_core.tools import tool
import subprocess

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
    try:
        WORK_DIR.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            command,
            shell=True,
            cwd=str(WORK_DIR.resolve()), 
            capture_output=True,
            text=True,
            timeout=60 
        )
        
        output = f"Exit Code: {result.returncode}\n"
        if result.stdout:
            output += f"STDOUT:\n{result.stdout}\n"
        if result.stderr:
            output += f"STDERR:\n{result.stderr}\n"
            
        return output
        
    except subprocess.TimeoutExpired:
        return f"Error: Command '{command}' timed out after 60 seconds."
    except Exception as e:
        return f"Error executing command: {str(e)}"

tools = [createFile, editFile, deleteResource, readFile, executeCommand]