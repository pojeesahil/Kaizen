import asyncio
import heapq

from agents.dag import DAG


class Scheduler:

    def __init__(self, dag: DAG, goal: str = ""):
        self.dag = dag
        self.goal = goal
        self.queue: list[tuple[int, str]] = []
        self.taskOutputs: dict[str, str] = {}
        self.taskFeedbacks: dict[str, str] = {}

    def loadReadyTasks(self) -> None:
        for task in self.dag.getReadyTasks():
            if getattr(task, "status", "pending") != "pending":
                continue
            task.status = "running"
            heapq.heappush(self.queue, (task.priority, task.id))

    def executeCoder(self, task) -> dict:
        tname = getattr(task, "name", getattr(task, "objective", task.id))
        print(f"\n[{getattr(task, 'agent', 'Coding')}] Starting Coder Agent for task: {tname}")
        from main import runCoder

        dependencyContext = ""
        for depId in getattr(task, "dependencies", []):
            if depId in self.taskOutputs:
                dependencyContext += f"\n- Parent task '{depId}' completed: {self.taskOutputs[depId]}"

        # Provide actual file contents from workspace so the agent sees real code
        workFiles = self._readWorkspaceFiles()
        if workFiles:
            dependencyContext += "\n\nCurrent workspace file contents:\n" + workFiles

        instruction = f"Overall Goal: {self.goal}\nTask: {tname}" if self.goal else tname
        feedback = self.taskFeedbacks.get(task.id, "")
        return runCoder(instruction, taskContext=dependencyContext, feedback=feedback)

    def _readWorkspaceFiles(self) -> str:
        """Read all source files from the work directory and return their contents."""
        import os
        workDir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "work")
        if not os.path.exists(workDir):
            return ""

        SUPPORTED_EXTENSIONS = {
            ".py", ".js", ".ts", ".java", ".html", ".css", ".json",
            ".jsx", ".tsx", ".go", ".cpp", ".c", ".h", ".yaml", ".yml"
        }
        SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".git", ".venv", "chroma_db", "graphify-out"}

        parts = []
        for root, dirs, files in os.walk(workDir):
            dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
            for fname in sorted(files):
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue
                fpath = os.path.join(root, fname)
                relpath = os.path.relpath(fpath, workDir)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    if content.strip():
                        parts.append(f"--- {relpath} ---\n{content}")
                except Exception:
                    continue

        return "\n\n".join(parts)

    async def run(self) -> None:
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
                self.dag.markComplete(task.id)
                self.taskOutputs[task.id] = result.get("coderMessage", "Task completed.")
                self.taskFeedbacks.pop(task.id, None)

                # Re-index workspace so the next agent can see newly created/modified files
                from rag.rag import indexWorkspace
                await asyncio.to_thread(indexWorkspace)

            completedTasks.extend(batch)
            allCoderResults.extend(coderResults)

            self.loadReadyTasks()

        if completedTasks:
            from main import runBatchEval
            success, feedback = await asyncio.to_thread(runBatchEval, completedTasks, allCoderResults)

            if not success:
                print(f"\n[QA Failure] Retrying all {len(completedTasks)} task(s) with combined feedback")
                for task in completedTasks:
                    tname = getattr(task, "name", getattr(task, "objective", task.id))
                    print(f" - Retrying: {tname}")
                    task.status = "pending"
                    self.taskFeedbacks[task.id] = feedback
                self.loadReadyTasks()
                if self.queue:
                    await self.run()

