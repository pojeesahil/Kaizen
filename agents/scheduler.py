import os
import heapq
import asyncio
from pathlib import Path
from agents.dag import DAG
from rag.rag import indexWorkspace
from core.connectedness import formatManifestContext, validateConnectedness, autoFixImports

class Scheduler:

    def __init__(self, dag: DAG, goal: str = ""):
        self.dag = dag
        self.goal = goal
        self.queue: list[tuple[int, str]] = []
        self.taskOutputs: dict[str, str] = {}
        self.taskFeedbacks: dict[str, str] = {}
        self.workDir = Path(__file__).resolve().parent.parent / "work"

    def loadReadyTasks(self) -> None:
        for task in self.dag.getReadyTasks():
            if getattr(task, "status", "pending") != "pending":
                continue
            task.status = "running"
            heapq.heappush(self.queue, (task.priority, task.id))

    def executeCoder(self, task) -> dict:
        tname = getattr(task, "name", getattr(task, "objective", task.id))
        print(f"\n[{getattr(task, 'agent', 'Coding')}] Starting Coder Agent for task: {tname}")

        depContext = ""
        for depId in getattr(task, "dependencies", []):
            if depId in self.taskOutputs:
                depContext += f"\n- Parent task '{depId}' output: {self.taskOutputs[depId]}"

        manifestContext = formatManifestContext(self.workDir)
        if manifestContext:
            depContext += f"\n\n{manifestContext}"

        workFiles = self.readWorkspaceFiles()
        if workFiles:
            depContext += "\n\nCurrent workspace file contents:\n" + workFiles

        instruction = f"Overall Goal: {self.goal}\nTask: {tname}" if self.goal else tname
        feedback = self.taskFeedbacks.get(task.id, "")
        from main import runCoder

        result = runCoder(instruction, taskContext=depContext, feedback=feedback)
        autoFixImports(self.workDir)

        isValid, errors = validateConnectedness(self.workDir)
        if not isValid:
            errText = "\n".join(f"- {e}" for e in errors)
            print(f"\n[Post-Task AST Import Check Failed for '{tname}']:\n{errText}")
            repairPrompt = f"Fix the following import and syntax errors in workspace files immediately:\n{errText}"
            result = runCoder(repairPrompt, taskContext=depContext, feedback=errText)
            autoFixImports(self.workDir)

        return result

    def readWorkspaceFiles(self) -> str:
        if not self.workDir.exists():
            return ""

        supportedExts = {
            ".py", ".js", ".ts", ".java", ".html", ".css", ".json",
            ".jsx", ".tsx", ".go", ".cpp", ".c", ".h", ".yaml", ".yml"
        }
        skipDirs = {"node_modules", "__pycache__", "venv", ".git", ".venv", "chroma_db", "graphify-out"}

        parts = []
        for root, dirs, files in os.walk(self.workDir):
            dirs[:] = [d for d in dirs if d not in skipDirs and not d.startswith(".")]
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in supportedExts:
                    continue
                fpath = os.path.join(root, fname)
                relpath = os.path.relpath(fpath, self.workDir)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    if content.strip():
                        parts.append(f"--- {relpath} ---\n{content}")
                except Exception:
                    continue

        return "\n\n".join(parts)

    def scaffoldWorkspace(self) -> None:
        self.workDir.mkdir(parents=True, exist_ok=True)
        files = [f for f in self.workDir.glob("*") if f.is_file() and not f.name.startswith(".")]
        if not files:
            goalLower = self.goal.lower()
            if any(w in goalLower for w in ("node", "npm", "express", "javascript", "js", "react", "next")):
                entryName = "server.js"
                entryContent = "const express = require('express');\nconst app = express();\n\napp.use(express.json());\n\nconst PORT = process.env.PORT || 3000;\napp.listen(PORT, () => {\n    console.log(`Server running on port ${PORT}`);\n});\n"
                pkgPath = self.workDir / "package.json"
                if not pkgPath.exists():
                    with open(pkgPath, "w", encoding="utf-8") as f:
                        f.write('{\n  "name": "kaizen-app",\n  "version": "1.0.0",\n  "main": "server.js",\n  "dependencies": {\n    "express": "^4.18.2"\n  }\n}\n')
            elif any(w in goalLower for w in ("go", "golang")):
                entryName = "main.go"
                entryContent = "package main\n\nimport \"fmt\"\n\nfunc main() {\n\tfmt.Println(\"Application started\")\n}\n"
            elif any(w in goalLower for w in ("java",)):
                entryName = "Main.java"
                entryContent = "public class Main {\n    public static void main(String[] args) {\n        System.out.println(\"Application started\");\n    }\n}\n"
            elif any(w in goalLower for w in ("c++", "cpp")):
                entryName = "main.cpp"
                entryContent = "#include <iostream>\n\nint main() {\n    std::cout << \"Application started\" << std::endl;\n    return 0;\n}\n"
            elif any(w in goalLower for w in ("c language", "gcc")):
                entryName = "main.c"
                entryContent = "#include <stdio.h>\n\nint main() {\n    printf(\"Application started\\n\");\n    return 0;\n}\n"
            elif any(w in goalLower for w in ("html", "css", "website", "web page")):
                entryName = "index.html"
                entryContent = "<!DOCTYPE html>\n<html>\n<head>\n<title>Web App</title>\n</head>\n<body>\n<h1>App</h1>\n</body>\n</html>\n"
            elif "snake" in goalLower:
                entryName = "snake_game.py"
                entryContent = "# Main entrypoint\n\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
            elif "tictactoe" in goalLower or "tic tac toe" in goalLower:
                entryName = "tictactoe.py"
                entryContent = "# Main entrypoint\n\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
            elif "calc" in goalLower:
                entryName = "calculator.py"
                entryContent = "# Main entrypoint\n\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
            elif any(w in goalLower for w in ("flask", "fastapi", "django", "python")):
                entryName = "app.py"
                entryContent = "# Main entrypoint\n\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"
            else:
                entryName = "main.py"
                entryContent = "# Main entrypoint\n\ndef main():\n    pass\n\nif __name__ == '__main__':\n    main()\n"

            entryPath = self.workDir / entryName
            if not entryPath.exists():
                with open(entryPath, "w", encoding="utf-8") as f:
                    f.write(entryContent)
                print(f"[Scaffold] Initialized primary entrypoint: {entryName}")

    async def run(self) -> None:
        self.scaffoldWorkspace()
        self.loadReadyTasks()

        completedTasks = []
        allCoderResults = []

        while self.queue:
            batch = []
            while self.queue:
                _, taskId = heapq.heappop(self.queue)
                batch.append(self.dag.tasks[taskId])

            print(f"\nRunning {len(batch)} Coder Agent(s) Sequentially")
            coderResults = []
            for task in batch:
                result = await asyncio.to_thread(self.executeCoder, task)
                coderResults.append(result)
                toolResults = result.get("toolResults", [])
                if toolResults:
                    print(f"Task '{getattr(task, 'name', task.id)}' executed {len(toolResults)} tool(s).")
                self.dag.markComplete(task.id)
                coderMsg = result.get("coderMessage", "Task completed.")
                if toolResults:
                    coderMsg += "\nTool Executions: " + "; ".join(toolResults)
                self.taskOutputs[task.id] = coderMsg
                self.taskFeedbacks.pop(task.id, None)

                await asyncio.to_thread(indexWorkspace)

            completedTasks.extend(batch)
            allCoderResults.extend(coderResults)
            self.loadReadyTasks()

        if completedTasks:
            from main import runBatchEval
            await asyncio.to_thread(runBatchEval, completedTasks, allCoderResults)
            print("\n[Kaizen] All plan tasks executed and verified successfully.\n")
