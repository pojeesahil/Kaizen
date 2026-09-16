import os
import ast
import re
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple, Any, Set, Optional

STDLIB_MODULES = {
    "os", "sys", "re", "json", "time", "math", "random", "datetime", "typing",
    "collections", "itertools", "functools", "pathlib", "shutil", "subprocess",
    "threading", "multiprocessing", "asyncio", "socket", "http", "urllib",
    "sqlite3", "hashlib", "base64", "copy", "io", "csv", "logging", "unittest",
    "inspect", "enum", "dataclasses", "uuid", "abc", "contextlib", "glob",
    "struct", "tempfile", "traceback", "warnings", "weakref", "bisect", "heapq"
}

BUILTIN_NAMES = {
    "print", "len", "range", "int", "float", "str", "bool", "list", "dict",
    "set", "tuple", "open", "type", "isinstance", "issubclass", "sum", "min",
    "max", "abs", "round", "all", "any", "zip", "enumerate", "map", "filter",
    "sorted", "reversed", "iter", "next", "hasattr", "getattr", "setattr",
    "delattr", "callable", "id", "hash", "dir", "vars", "repr", "ascii",
    "chr", "ord", "hex", "oct", "bin", "pow", "divmod", "format", "input",
    "super", "property", "staticmethod", "classmethod", "object", "Exception",
    "ValueError", "TypeError", "KeyError", "IndexError", "AttributeError",
    "ZeroDivisionError", "FileNotFoundError", "IOError", "RuntimeError",
    "StopIteration", "KeyboardInterrupt", "SystemExit", "True", "False", "None"
}

def parseFileAst(fpath: Path) -> Optional[ast.AST]:
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        return ast.parse(src, filename=str(fpath))
    except Exception:
        return None

def extractPySymbols(fpath: Path) -> Dict[str, Any]:
    res = {
        "functions": [],
        "classes": {},
        "imports": [],
        "fromImports": {},
        "globals": [],
        "syntaxError": None
    }
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        tree = ast.parse(src, filename=str(fpath))
    except SyntaxError as e:
        res["syntaxError"] = f"SyntaxError on line {e.lineno}: {e.msg}"
        return res
    except Exception as e:
        res["syntaxError"] = f"ParseError: {str(e)}"
        return res

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            args = [a.arg for a in node.args.args]
            ret = ""
            if node.returns:
                try:
                    ret = f" -> {ast.unparse(node.returns)}"
                except Exception:
                    pass
            res["functions"].append(f"{node.name}({', '.join(args)}){ret}")
        elif isinstance(node, ast.ClassDef):
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    margs = [a.arg for a in item.args.args]
                    methods.append(f"{item.name}({', '.join(margs)})")
            res["classes"][node.name] = methods
        elif isinstance(node, ast.Import):
            for alias in node.names:
                res["imports"].append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            names = [alias.name for alias in node.names]
            if mod in res["fromImports"]:
                res["fromImports"][mod].extend(names)
            else:
                res["fromImports"][mod] = names
        elif isinstance(node, ast.Assign):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    res["globals"].append(tgt.id)

    return res

def extractJsSymbols(fpath: Path) -> Dict[str, Any]:
    res = {"functions": [], "classes": {}, "exports": [], "imports": [], "globals": []}
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
    except Exception:
        return res

    for m in re.finditer(r"(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\(([^)]*)\)", src):
        res["functions"].append(f"{m.group(1)}({m.group(2).strip()})")

    for m in re.finditer(r"(?:export\s+)?const\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?\(([^)]*)\)\s*=>", src):
        res["functions"].append(f"{m.group(1)}({m.group(2).strip()})")

    for m in re.finditer(r"(?:export\s+)?class\s+([a-zA-Z0-9_$]+)", src):
        res["classes"][m.group(1)] = []

    for m in re.finditer(r"import\s+(?:\{([^}]+)\}|([a-zA-Z0-9_$]+))\s+from\s+['\"]([^'\"]+)['\"]", src):
        imported = m.group(1) or m.group(2)
        mod = m.group(3)
        res["imports"].append(f"{imported.strip()} from {mod}")

    for m in re.finditer(r"module\.exports\s*=\s*\{([^}]+)\}", src):
        for sym in m.group(1).split(","):
            s = sym.strip()
            if s:
                res["exports"].append(s)

    return res

def extractGoSymbols(fpath: Path) -> Dict[str, Any]:
    res = {"functions": [], "structs": [], "imports": []}
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        for m in re.finditer(r"func\s+([a-zA-Z0-9_$]+)\s*\(", src):
            res["functions"].append(m.group(1))
        for m in re.finditer(r"type\s+([a-zA-Z0-9_$]+)\s+struct", src):
            res["structs"].append(m.group(1))
        for m in re.finditer(r"import\s+(?:\(\s*([^)]+)\s*\)|([^\n]+))", src):
            res["imports"].append((m.group(1) or m.group(2)).strip())
    except Exception:
        pass
    return res

def extractJavaSymbols(fpath: Path) -> Dict[str, Any]:
    res = {"classes": {}, "functions": [], "imports": []}
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        for m in re.finditer(r"(?:public|private|protected)?\s*class\s+([a-zA-Z0-9_$]+)", src):
            res["classes"][m.group(1)] = []
        for m in re.finditer(r"import\s+([a-zA-Z0-9_$.*]+);", src):
            res["imports"].append(m.group(1))
    except Exception:
        pass
    return res

def extractCSymbols(fpath: Path) -> Dict[str, Any]:
    res = {"functions": [], "includes": []}
    try:
        with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
            src = f.read()
        for m in re.finditer(r"#include\s+[<\"]([^>\" ]+)[>\"]", src):
            res["includes"].append(m.group(1))
        for m in re.finditer(r"(?:[a-zA-Z0-9_*]+\s+)+([a-zA-Z0-9_]+)\s*\([^)]*\)\s*\{", src):
            if m.group(1) not in ("if", "while", "for", "switch"):
                res["functions"].append(m.group(1))
    except Exception:
        pass
    return res

def buildSymbolManifest(workDir: Path) -> Dict[str, Any]:
    manifest = {}
    if not workDir.exists():
        return manifest

    skipDirs = {
        "node_modules",
        "__pycache__",
        "venv",
        ".git",
        ".venv",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".cache",
        "coverage"
    }
    for root, dirs, files in os.walk(workDir):
        dirs[:] = [d for d in dirs if d not in skipDirs and not d.startswith(".")]
        for fname in sorted(files):
            fpath = Path(root) / fname
            rel = fpath.relative_to(workDir).as_posix()
            ext = fpath.suffix.lower()

            if ext == ".py":
                manifest[rel] = extractPySymbols(fpath)
            elif ext in (".js", ".ts", ".jsx", ".tsx"):
                manifest[rel] = extractJsSymbols(fpath)
            elif ext == ".go":
                manifest[rel] = extractGoSymbols(fpath)
            elif ext == ".java":
                manifest[rel] = extractJavaSymbols(fpath)
            elif ext in (".c", ".cpp", ".cc", ".h", ".hpp"):
                manifest[rel] = extractCSymbols(fpath)
            else:
                manifest[rel] = {"file": rel}

    return manifest

def buildExactImportMap(workDir: Path) -> Dict[str, str]:
    manifest = buildSymbolManifest(workDir)
    importMap = {}
    for rel, data in manifest.items():
        if not rel.endswith(".py"):
            continue
        parts = rel[:-3].split("/")
        if parts[0] == "src" and not (workDir / "src" / "__init__.py").exists():
            parts = parts[1:]
        if not parts:
            continue
        modPath = ".".join(parts)
        if modPath.endswith(".__init__"):
            modPath = modPath[:-9]
        if not modPath:
            continue

        for func in data.get("functions", []):
            fname = func.split("(")[0].strip()
            if fname and not fname.startswith("_"):
                importMap[fname] = f"from {modPath} import {fname}"

        for cname in data.get("classes", {}).keys():
            if cname and not cname.startswith("_"):
                importMap[cname] = f"from {modPath} import {cname}"

        for gname in data.get("globals", []):
            if gname and not gname.startswith("_"):
                importMap[gname] = f"from {modPath} import {gname}"

    return importMap

def formatManifestContext(workDir: Path) -> str:
    manifest = buildSymbolManifest(workDir)
    importMap = buildExactImportMap(workDir)
    if not manifest:
        return "Workspace is currently empty."

    lines = ["=== Workspace Symbol Table & Connection Registry ==="]
    for rel, data in manifest.items():
        lines.append(f"\n[File: {rel}]")
        if data.get("syntaxError"):
            lines.append(f"  * SYNTAX ERROR: {data['syntaxError']}")
            continue

        funcs = data.get("functions", [])
        if funcs:
            lines.append("  Functions: " + ", ".join(funcs))

        classes = data.get("classes", {})
        if classes:
            for cname, methods in classes.items():
                mstr = f" ({', '.join(methods)})" if methods else ""
                lines.append(f"  Class: {cname}{mstr}")

        globalsList = data.get("globals", [])
        if globalsList:
            lines.append("  Variables: " + ", ".join(globalsList))

    if importMap:
        lines.append("\n=== EXACT PYTHON IMPORT STRINGS ===")
        for sym, impStr in sorted(importMap.items()):
            lines.append(f"- {sym}: {impStr}")

    lines.append("\nRULES FOR CROSS-FILE CONNECTEDNESS:")
    lines.append("- Connect modules and import symbols using valid, idiomatic import statements for the project's target language environment.")
    lines.append("- Do not redefine existing functions or classes across files unless extending them.")
    lines.append("- Write complete, runnable implementation files without placeholders.")
    return "\n".join(lines)

def mergePythonImports(oldCode: str, newCode: str) -> str:
    try:
        oldTree = ast.parse(oldCode)
        newTree = ast.parse(newCode)
    except Exception:
        return newCode

    oldImportNodes = [
        item for item in oldTree.body
        if isinstance(item, (ast.Import, ast.ImportFrom))
    ]
    newImportNodes = [
        item for item in newTree.body
        if isinstance(item, (ast.Import, ast.ImportFrom))
    ]

    newImportedNames = set()
    for item in newImportNodes:
        for alias in item.names:
            newImportedNames.add(alias.asname or alias.name)

    newDefinedNames = set()
    for item in newTree.body:
        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            newDefinedNames.add(item.name)
        elif isinstance(item, ast.Assign):
            for target in item.targets:
                if isinstance(target, ast.Name):
                    newDefinedNames.add(target.id)

    usedNames = set()
    for node in ast.walk(newTree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            usedNames.add(node.id)

    missingLines = []
    addedSignatures = set()

    for item in oldImportNodes:
        if isinstance(item, ast.Import):
            for alias in item.names:
                importSymbol = alias.asname or alias.name
                if importSymbol in usedNames and importSymbol not in newImportedNames and importSymbol not in newDefinedNames:
                    asPart = f" as {alias.asname}" if alias.asname else ""
                    sig = f"import {alias.name}{asPart}"
                    if sig not in addedSignatures:
                        missingLines.append(sig)
                        addedSignatures.add(sig)
        elif isinstance(item, ast.ImportFrom):
            mod = item.module or ""
            for alias in item.names:
                importSymbol = alias.asname or alias.name
                if importSymbol in usedNames and importSymbol not in newImportedNames and importSymbol not in newDefinedNames:
                    asPart = f" as {alias.asname}" if alias.asname else ""
                    sig = f"from {mod} import {alias.name}{asPart}"
                    if sig not in addedSignatures:
                        missingLines.append(sig)
                        addedSignatures.add(sig)

    if missingLines:
        return "\n".join(missingLines) + "\n" + newCode
    return newCode

def autoFixImports(workDir: Path) -> None:
    if not workDir.exists():
        return

    importMap = buildExactImportMap(workDir)
    if not importMap:
        return

    skipDirs = {
        "node_modules",
        "__pycache__",
        "venv",
        ".git",
        ".venv",
        "dist",
        "build",
        ".next",
        ".nuxt",
        ".cache",
        "coverage"
    }
    for root, dirs, files in os.walk(workDir):
        dirs[:] = [d for d in dirs if d not in skipDirs and not d.startswith(".")]
        for fname in files:
            if not fname.endswith(".py"):
                continue
            fpath = Path(root) / fname
            try:
                with open(fpath, "r", encoding="utf-8") as f:
                    src = f.read()
                tree = ast.parse(src, filename=str(fpath))
            except Exception:
                continue

            definedSymbols = set()
            importedSymbols = set()
            usedSymbols = set()

            for node in tree.body:
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    definedSymbols.add(node.name)
                elif isinstance(node, ast.ClassDef):
                    definedSymbols.add(node.name)
                elif isinstance(node, ast.Assign):
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            definedSymbols.add(tgt.id)
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        importedSymbols.add(alias.asname or alias.name)
                elif isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        importedSymbols.add(alias.asname or alias.name)

            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    for alias in node.names:
                        importedSymbols.add(alias.asname or alias.name)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    definedSymbols.add(node.name)
                    for arg in node.args.args:
                        definedSymbols.add(arg.arg)
                    for arg in getattr(node.args, "posonlyargs", []):
                        definedSymbols.add(arg.arg)
                    for arg in getattr(node.args, "kwonlyargs", []):
                        definedSymbols.add(arg.arg)
                    if node.args.vararg:
                        definedSymbols.add(node.args.vararg.arg)
                    if node.args.kwarg:
                        definedSymbols.add(node.args.kwarg.arg)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    usedSymbols.add(node.id)

            missingSymbols = usedSymbols - definedSymbols - importedSymbols - BUILTIN_NAMES - STDLIB_MODULES
            addedImports = []
            curRel = fpath.relative_to(workDir).as_posix()
            curParts = curRel[:-3].split("/")
            if curParts[0] == "src" and not (workDir / "src" / "__init__.py").exists():
                curParts = curParts[1:]
            curMod = ".".join(curParts)

            for sym in sorted(missingSymbols):
                if sym in importMap:
                    impStr = importMap[sym]
                    if f"from {curMod} import" not in impStr:
                        addedImports.append(impStr)

            if addedImports:
                newHeader = "\n".join(addedImports) + "\n"
                updatedSrc = newHeader + src
                with open(fpath, "w", encoding="utf-8") as f:
                    f.write(updatedSrc)

    if shutil.which("ruff"):
        try:
            subprocess.run(
                ["ruff", "check", "--select", "I,F401", "--fix", str(workDir)],
                capture_output=True,
                text=True,
                timeout=5
            )
        except Exception:
            pass

def validateConnectedness(workDir: Path) -> Tuple[bool, List[str]]:
    manifest = buildSymbolManifest(workDir)
    errors = []

    hasJsFiles = any(
        f.endswith((".js", ".ts", ".jsx", ".tsx", "package.json"))
        for f in manifest.keys()
    )
    pyFiles = {
        f: d for f, d in manifest.items()
        if f.endswith(".py")
    }

    if hasJsFiles:
        for pyName in ("main.py", "app.py"):
            pyPath = workDir / pyName
            if pyPath.exists():
                try:
                    txt = pyPath.read_text(encoding="utf-8").strip()
                    if "def main():" in txt and "pass" in txt:
                        pyPath.unlink()
                        manifest.pop(pyName, None)
                        pyFiles.pop(pyName, None)
                except Exception:
                    pass

    moduleIndex = {}
    packageIndex = set()

    for rel, data in pyFiles.items():
        parts = rel[:-3].split("/")
        dotPath = ".".join(parts)
        moduleIndex[dotPath] = (rel, data)

        if parts[0] == "src" and len(parts) > 1:
            srcRelative = ".".join(parts[1:])
            moduleIndex[srcRelative] = (rel, data)

        if parts[-1] == "__init__":
            pkgParts = parts[:-1]
            if pkgParts:
                moduleIndex[".".join(pkgParts)] = (rel, data)
                if pkgParts[0] == "src" and len(pkgParts) > 1:
                    moduleIndex[".".join(pkgParts[1:])] = (rel, data)

        for i in range(1, len(parts)):
            packageIndex.add(".".join(parts[:i]))
            if parts[0] == "src" and i > 1:
                packageIndex.add(".".join(parts[1:i]))

    for rel, data in pyFiles.items():
        if data.get("syntaxError"):
            if hasJsFiles:
                continue
            errors.append(f"[{rel}] {data['syntaxError']}")
            continue

        for mod, symbols in data.get("fromImports", {}).items():
            if not mod or mod.startswith("."):
                continue

            rootMod = mod.split(".")[0]
            if rootMod in STDLIB_MODULES:
                continue

            if mod in moduleIndex:
                targetRel, targetData = moduleIndex[mod]
                targetSymbols = set(targetData.get("functions", []))
                targetSymNames = {
                    func.split("(")[0].strip()
                    for func in targetSymbols
                }
                targetSymNames.update(targetData.get("classes", {}).keys())
                targetSymNames.update(targetData.get("globals", []))

                for sym in symbols:
                    if sym == "*":
                        continue
                    subModCandidate = f"{mod}.{sym}"
                    if subModCandidate in moduleIndex or subModCandidate in packageIndex:
                        continue
                    if sym not in targetSymNames:
                        availableList = sorted(list(targetSymNames))
                        errors.append(
                            f"[{rel}] Broken Import: Symbol '{sym}' not found in '{targetRel}'. Available: {availableList}"
                        )
            elif mod in packageIndex:
                for sym in symbols:
                    if sym == "*":
                        continue
                    subModCandidate = f"{mod}.{sym}"
                    if subModCandidate not in moduleIndex and subModCandidate not in packageIndex:
                        errors.append(
                            f"[{rel}] Broken Import: Module '{sym}' not found in package '{mod}'."
                        )

    isValid = len(errors) == 0
    return isValid, errors
