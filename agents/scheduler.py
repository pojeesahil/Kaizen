import os
import heapq
import asyncio
from pathlib import Path
from typing import Callable, Optional
from agents.dag import DAG
from rag.rag import indexWorkspace
from core.connectedness import formatManifestContext, validateConnectedness, autoFixImports

class Scheduler:

    def __init__(self, dag: DAG, goal: str = "", techStack: str = "", fileStructure: Optional[list] = None, coderFn: Optional[Callable] = None, evalFn: Optional[Callable] = None):
        self.dag = dag
        self.goal = goal
        self.techStack = techStack
        self.fileStructure = fileStructure or []
        self.coderFn = coderFn
        self.evalFn = evalFn
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
                depContext += f"\n- Parent task '{depId}' completed: {self.taskOutputs[depId]}"

        manifestContext = formatManifestContext(self.workDir)
        if manifestContext:
            depContext += f"\n\n{manifestContext}"

        workFiles = self.readWorkspaceFiles()
        if workFiles:
            depContext += "\n\nCurrent workspace file contents:\n" + workFiles

        instParts = []
        if self.goal:
            instParts.append(f"Overall Goal: {self.goal}")
        if self.techStack:
            instParts.append(f"Target Tech Stack: {self.techStack}")
        if self.fileStructure:
            instParts.append(f"Planned File Structure: {', '.join(self.fileStructure)}")
        instParts.append(f"Task: {tname}")
        instruction = "\n".join(instParts)

        feedback = self.taskFeedbacks.get(task.id, "")

        if self.coderFn:
            result = self.coderFn(instruction, taskContext=depContext, feedback=feedback)
        else:
            result = {"coderMessage": "Task executed", "toolResults": []}

        autoFixImports(self.workDir)

        isValid, errors = validateConnectedness(self.workDir)
        if not isValid:
            errText = "\n".join(f"- {e}" for e in errors)
            print(f"\n[Post-Task AST Import Check Failed for '{tname}']:\n{errText}")
            repairPrompt = f"Fix the following import and syntax errors in workspace files immediately:\n{errText}"
            if self.coderFn:
                result = self.coderFn(repairPrompt, taskContext=depContext, feedback=errText)
            autoFixImports(self.workDir)

        return result

    def readWorkspaceFiles(self) -> str:
        if not self.workDir.exists():
            return ""

        supportedExts = {
            ".py", ".js", ".ts", ".java", ".html", ".css", ".json",
            ".jsx", ".tsx", ".go", ".cpp", ".c", ".h", ".yaml", ".yml", ".md"
        }
        skipDirs = {
            "node_modules", "__pycache__", "venv", ".git", ".venv",
            "chroma_db", "graphify-out", "dist", "build", ".next", ".nuxt", ".cache", "coverage"
        }
        skipFiles = {
            "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock", "cargo.lock", "poetry.lock"
        }

        parts = []
        for root, dirs, files in os.walk(self.workDir):
            dirs[:] = [d for d in dirs if d not in skipDirs and not d.startswith(".")]
            for fname in sorted(files):
                if fname in skipFiles or fname.endswith((".min.js", ".min.css", ".map", ".pack")):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in supportedExts:
                    continue
                fpath = os.path.join(root, fname)
                if os.path.getsize(fpath) > 100000:
                    continue
                relpath = os.path.relpath(fpath, self.workDir)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(50000)
                    if content.strip():
                        parts.append(f"--- {relpath} ---\n{content}")
                except Exception:
                    continue

        return "\n\n".join(parts)

    async def run(self) -> None:
        self.workDir.mkdir(parents=True, exist_ok=True)
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
            if self.evalFn:
                passed, fb = await asyncio.to_thread(self.evalFn, completedTasks, allCoderResults)
                if passed:
                    print("\n[Kaizen] All plan tasks executed and verified successfully.\n")
                else:
                    for retry in range(1, 4):
                        print(f"\n[Kaizen Repair {retry}/3] Triggering Coder Agent to fix verification failure...")
                        repairPrompt = (
                            f"Overall Goal: {self.goal}\n"
                            f"Target Tech Stack: {self.techStack}\n\n"
                            f"The project implementation failed verification with the following Critic/Tester feedback:\n{fb}\n\n"
                            "Inspect the current workspace files and use tool calls (createFile, editFile, upsertFunction, upsertClass) to implement the missing components and resolve all issues."
                        )
                        fixRes = await asyncio.to_thread(self.coderFn, repairPrompt, taskContext=self.readWorkspaceFiles(), feedback=fb)
                        allCoderResults.append(fixRes)
                        await asyncio.to_thread(indexWorkspace)

                        passed, fb = await asyncio.to_thread(self.evalFn, completedTasks, allCoderResults)
                        if passed:
                            print("\n[Kaizen] All plan tasks executed and verified successfully.\n")
                            break
                    else:
                        print(f"\n[Kaizen] Verification could not be resolved after 3 repair attempts.\n")
            else:
                print("\n[Kaizen] All plan tasks executed.\n")
