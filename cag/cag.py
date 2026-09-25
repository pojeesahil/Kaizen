import os
from pathlib import Path
from typing import Dict, Optional, Set

_cache: Dict[str, str] = {}

skipDirs: Set[str] = {
    "node_modules", "__pycache__", "venv", ".git", ".venv",
    "chroma_db", "graphify-out", "graphify_out", ".idea", ".vscode",
    "dist", "build", ".next", ".nuxt", ".cache", "coverage"
}

skipFiles: Set[str] = {
    "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock",
    "cargo.lock", "poetry.lock"
}

supportedExts: Set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css",
    ".json", ".go", ".c", ".cpp", ".cc", ".h", ".hpp",
    ".java", ".yaml", ".yml", ".md", ".txt", ".sql", ".sh", ".svg"
}

SKIP_DIRS = skipDirs
SKIP_FILES = skipFiles
SUPPORTED_EXTS = supportedExts

_currentWorkDir: str = "work"

def loadCag(path: Optional[str] = None) -> int:
    global _currentWorkDir
    targetPath = Path(path) if path else Path(_currentWorkDir)
    _currentWorkDir = str(targetPath)

    _cache.clear()
    if not targetPath.exists():
        return 0

    for root, dirs, files in os.walk(targetPath):
        dirs[:] = [d for d in dirs if d not in skipDirs and not d.startswith(".")]
        for fname in sorted(files):
            if fname in skipFiles or fname.endswith((".min.js", ".min.css", ".map", ".pack")):
                continue
            ext = os.path.splitext(fname)[1].lower()
            if ext not in supportedExts:
                continue

            filePath = Path(root) / fname
            try:
                if filePath.stat().st_size > 100000:
                    continue
                relPath = filePath.relative_to(targetPath).as_posix()
                with open(filePath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read(50000)
                _cache[relPath] = content
            except Exception:
                continue

    count = len(_cache)
    print(f"[CAG] Preloaded {count} file(s) into memory cache from '{targetPath}'.")
    return count

def updateCagFile(filePath: str, baseDir: Optional[str] = None) -> None:
    fpath = Path(filePath)
    base = Path(baseDir) if baseDir else Path(_currentWorkDir)

    try:
        relPath = fpath.relative_to(base).as_posix() if fpath.is_relative_to(base) else fpath.name
    except Exception:
        relPath = fpath.name

    if fpath.exists() and fpath.is_file():
        ext = fpath.suffix.lower()
        if ext in supportedExts or not ext:
            try:
                if fpath.stat().st_size <= 100000:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        _cache[relPath] = f.read(50000)
            except Exception:
                pass
    else:
        _cache.pop(relPath, None)

def getCagContext(instruction: str = "") -> str:
    if not _cache:
        return "No files in workspace."

    parts = []
    for relPath, content in sorted(_cache.items()):
        if content.strip():
            parts.append(f"--- {relPath} ---\n{content}")

    return "\n\n".join(parts) if parts else "No files in workspace."

def getCoderContext(instruction: str = "", workDir: Optional[str] = None) -> str:
    targetDir = workDir or _currentWorkDir
    if not _cache:
        loadCag(targetDir)
    return getCagContext(instruction)

def clearCag() -> None:
    _cache.clear()

def getCagCache() -> Dict[str, str]:
    return dict(_cache)

load_cag = loadCag
update_cag_file = updateCagFile
get_cag_context = getCagContext
get_coder_context = getCoderContext
clear_cag = clearCag
get_cag_cache = getCagCache

indexWorkspace = loadCag
getContext = getCoderContext
updateWorkspaceFile = updateCagFile

class CodebaseCache:
    def loadDirectory(self, path: str) -> int:
        return loadCag(path)

    load_directory = loadDirectory

    def updateFile(self, path: str, basePath: Optional[str] = None) -> None:
        updateCagFile(path, basePath)

    update_file = updateFile

    def getAll(self) -> Dict[str, str]:
        return getCagCache()

    get_all = getAll

    def clear(self) -> None:
        clearCag()

    def count(self) -> int:
        return len(_cache)

class CAG:
    def __init__(self, workDir: str = "work"):
        self.workDir = workDir
        self.work_dir = workDir

    def preload(self, path: Optional[str] = None) -> int:
        return loadCag(path or self.workDir)

    def getContext(self, instruction: str = "") -> str:
        return getCoderContext(instruction, self.workDir)

    get_context = getContext

    def updateFile(self, filePath: str) -> None:
        updateCagFile(filePath, self.workDir)

    update_file = updateFile

    def clear(self) -> None:
        clearCag()

def getCAG() -> CAG:
    return CAG()
