import os
import ast
import re
import json
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

def buildSymbolManifest(workDir: Path) -> Dict[str, Any]:
    manifest = {}
    if not workDir.exists():
        return manifest

    for root, _, files in os.walk(workDir):
        for fname in sorted(files):
            fpath = Path(root) / fname
            rel = fpath.relative_to(workDir).as_posix()
            ext = fpath.suffix.lower()

            if ext == ".py":
                manifest[rel] = extractPySymbols(fpath)
            elif ext in (".js", ".ts", ".jsx", ".tsx"):
                manifest[rel] = extractJsSymbols(fpath)

    return manifest

def buildExactImportMap(workDir: Path) -> Dict[str, str]:
    manifest = buildSymbolManifest(workDir)
    importMap = {}
    for rel, data in manifest.items():
        if not rel.endswith(".py"):
            continue
        modPath = rel[:-3].replace("/", ".")
        if modPath.endswith(".__init__"):
            modPath = modPath[:-9]

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
        lines.append("\n=== EXACT IMPORT STRINGS (Use these exact imports) ===")
        for sym, impStr in sorted(importMap.items()):
            lines.append(f"- {sym}: {impStr}")

    lines.append("\nRULES FOR CROSS-FILE CONNECTEDNESS:")
    lines.append("- Import symbols using the exact strings listed above.")
    lines.append("- Do not redefine or rename existing functions or classes.")
    lines.append("- Keep 'if __name__ == \"__main__\":' at the very bottom of the file.")
    return "\n".join(lines)

def mergePythonImports(oldCode: str, newCode: str) -> str:
    try:
        oldTree = ast.parse(oldCode)
        newTree = ast.parse(newCode)
    except Exception:
        return newCode

    oldImportNodes = [n for n in oldTree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    newImportNodes = [n for n in newTree.body if isinstance(n, (ast.Import, ast.ImportFrom))]

    newImportSignatures = set()
    for n in newImportNodes:
        if isinstance(n, ast.Import):
            for alias in n.names:
                newImportSignatures.add(f"import {alias.name}")
        elif isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            for alias in n.names:
                newImportSignatures.add(f"from {mod} import {alias.name}")

    missingLines = []
    for n in oldImportNodes:
        if isinstance(n, ast.Import):
            for alias in n.names:
                sig = f"import {alias.name}"
                if sig not in newImportSignatures:
                    asPart = f" as {alias.asname}" if alias.asname else ""
                    missingLines.append(f"import {alias.name}{asPart}")
                    newImportSignatures.add(sig)
        elif isinstance(n, ast.ImportFrom):
            mod = n.module or ""
            for alias in n.names:
                sig = f"from {mod} import {alias.name}"
                if sig not in newImportSignatures:
                    asPart = f" as {alias.asname}" if alias.asname else ""
                    missingLines.append(f"from {mod} import {alias.name}{asPart}")
                    newImportSignatures.add(sig)

    if missingLines:
        return "\n".join(missingLines) + "\n" + newCode
    return newCode

def autoFixImports(workDir: Path) -> None:
    if not workDir.exists():
        return

    importMap = buildExactImportMap(workDir)
    if not importMap:
        return

    for root, _, files in os.walk(workDir):
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
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    usedSymbols.add(node.id)

            missingSymbols = usedSymbols - definedSymbols - importedSymbols - BUILTIN_NAMES - STDLIB_MODULES
            addedImports = []
            curMod = fpath.relative_to(workDir).as_posix()[:-3].replace("/", ".")

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

    pyFiles = {f: d for f, d in manifest.items() if f.endswith(".py")}
    moduleMap = {Path(f).stem: (f, d) for f, d in pyFiles.items()}

    for rel, data in pyFiles.items():
        if data.get("syntaxError"):
            errors.append(f"[{rel}] {data['syntaxError']}")
            continue

        for mod, symbols in data.get("fromImports", {}).items():
            if not mod or mod.startswith("."):
                continue
            rootMod = mod.split(".")[0]
            if rootMod in STDLIB_MODULES:
                continue

            if rootMod in moduleMap:
                targetRel, targetData = moduleMap[rootMod]
                targetSymbols = set(targetData.get("functions", []))
                targetSymNames = {f.split("(")[0].strip() for f in targetSymbols}
                targetSymNames.update(targetData.get("classes", {}).keys())
                targetSymNames.update(targetData.get("globals", []))

                for sym in symbols:
                    if sym != "*" and sym not in targetSymNames:
                        errors.append(
                            f"[{rel}] Broken Import: Symbol '{sym}' not found in '{targetRel}'. Available: {sorted(list(targetSymNames))}"
                        )

    isValid = len(errors) == 0
    return isValid, errors
