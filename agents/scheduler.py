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

        taskOutput = getattr(task, "output", "")
        if taskOutput:
            instParts.append(f"Required Artifacts: {taskOutput}")

        taskCrit = getattr(task, "completionCriteria", "") or getattr(task, "completion_criteria", "")
        if taskCrit:
            instParts.append(f"Completion Criteria: {taskCrit}")

        instruction = "\n".join(instParts)

        feedback = self.taskFeedbacks.get(task.id, "")

        if self.coderFn:
            result = self.coderFn(instruction, taskContext=depContext, feedback=feedback)
        else:
            result = {"coderMessage": "Task executed", "toolResults": []}

        return result

    async def executeCoderThrottled(self, task, semaphore):
        async with semaphore:
            result = await asyncio.to_thread(self.executeCoder, task)
        return task, result

    def readWorkspaceFiles(self) -> str:
        if not self.workDir.exists():
            return ""

        supportedExts = {
            ".py", ".js", ".ts", ".java", ".html", ".css", ".json",
            ".jsx", ".tsx", ".go", ".cpp", ".c", ".h", ".yaml", ".yml", ".md", ".txt", ".svg"
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
        halted = False

        while self.queue:
            batch = []
            while self.queue:
                _, taskId = heapq.heappop(self.queue)
                batch.append(self.dag.tasks[taskId])

            batchSize = len(batch)
            runMode = "in Parallel" if batchSize > 1 else "Sequentially"
            print(f"\nRunning {batchSize} Coder Agent(s) {runMode}")

            semaphore = asyncio.Semaphore(3)
            gathered = await asyncio.gather(
                *(self.executeCoderThrottled(task, semaphore) for task in batch)
            )

            coderResults = []
            for task, result in gathered:
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

            autoFixImports(self.workDir)
            isValid, batchErrors = validateConnectedness(self.workDir)
            if not isValid:
                errText = "\n".join(f"- {e}" for e in batchErrors)
                print(f"\n[Post-Batch AST Import Check Failed]:\n{errText}")
                if self.coderFn:
                    repairContext = ""
                    manifestSnapshot = formatManifestContext(self.workDir)
                    if manifestSnapshot:
                        repairContext += f"\n\n{manifestSnapshot}"
                    workSnapshot = self.readWorkspaceFiles()
                    if workSnapshot:
                        repairContext += "\n\nCurrent workspace file contents:\n" + workSnapshot
                    repairPrompt = f"Fix the following import and syntax errors in workspace files immediately:\n{errText}"
                    repairResult = await asyncio.to_thread(
                        self.coderFn, repairPrompt, taskContext=repairContext, feedback=errText
                    )
                    coderResults.append(repairResult)
                autoFixImports(self.workDir)

            await asyncio.to_thread(indexWorkspace)

            completedTasks.extend(batch)
            allCoderResults.extend(coderResults)

            if self.evalFn:
                passed, fb = await asyncio.to_thread(self.evalFn, batch, coderResults)
                if passed:
                    print(f"\n[Milestone Verification] Batch of {batchSize} task(s) verified successfully.")
                else:
                    repaired = False
                    for repair in range(1, 11):
                        print(f"\n[Milestone Repair {repair}/10] Triggering Coder Agent to fix verification failure...")
                        repairPrompt = (
                            f"Overall Goal: {self.goal}\n"
                            f"Target Tech Stack: {self.techStack}\n\n"
                            f"The project failed milestone verification after the latest batch of tasks.\n"
                            f"Critic/Tester feedback:\n{fb}\n\n"
                            "Inspect the current workspace files and use tool calls (createFile, editFile, upsertFunction, upsertClass, searchWeb) to fix all issues so the application runs correctly."
                        )
                        fixRes = await asyncio.to_thread(self.coderFn, repairPrompt, taskContext=self.readWorkspaceFiles(), feedback=fb)
                        coderResults.append(fixRes)
                        allCoderResults.append(fixRes)
                        await asyncio.to_thread(indexWorkspace)

                        passed, fb = await asyncio.to_thread(self.evalFn, batch, coderResults)
                        if passed:
                            print(f"\n[Milestone Repair] Repair {repair} succeeded. Continuing to next batch.")
                            repaired = True
                            break
                    if not repaired:
                        print(f"\n[Kaizen] Milestone verification could not be resolved after 10 repair attempts. Halting pipeline.")
                        halted = True
                        break

            self.loadReadyTasks()

        if halted:
            print("\n[Kaizen] Pipeline halted due to unresolvable milestone failure.\n")
        elif completedTasks:
            print("\n[Kaizen] All plan tasks executed and verified successfully.\n")

