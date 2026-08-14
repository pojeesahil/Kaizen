import asyncio
import heapq

from agents.dag import DAG
import os
from main import runBatchEval 
from rag.rag import indexWorkspace
from main import runCoder
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
        

        dependencyContext = ""
        for depId in getattr(task, "dependencies", []):
            if depId in self.taskOutputs:
                dependencyContext += f"\n- Parent task '{depId}' completed: {self.taskOutputs[depId]}"

       
        workFiles = self._readWorkspaceFiles()
        if workFiles:
            dependencyContext += "\n\nCurrent workspace file contents:\n" + workFiles

        instruction = f"Overall Goal: {self.goal}\nTask: {tname}" if self.goal else tname
        feedback = self.taskFeedbacks.get(task.id, "")
        return runCoder(instruction, taskContext=dependencyContext, feedback=feedback)

    def _readWorkspaceFiles(self) -> str:
        """Read all source files from the work directory and return their contents."""
        
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

               
                
                await asyncio.to_thread(indexWorkspace)

            completedTasks.extend(batch)
            allCoderResults.extend(coderResults)

            self.loadReadyTasks()

        if completedTasks:
           
            success, feedback = await asyncio.to_thread(runBatchEval, completedTasks, allCoderResults)

            if not success:
                AffectedFiles = self.extractAffectedFiles(allCoderResults, feedback)
                if len(AffectedFiles) > 1:
                    print(f"\n[QA Failure] Spawning {len(AffectedFiles)} file-specific repair agents:")
                    for PathStr in AffectedFiles:
                        print(f" - Target file: {PathStr}")

                    for PathStr in AffectedFiles:
                        CleanName = PathStr.replace(".", "_").replace("/", "_").replace("\\", "_")
                        TaskId = f"fix_{CleanName}_{len(self.dag.tasks)}"
                        NewTask = TaskNode(
                            id=TaskId,
                            deliverableId="repair",
                            objective=f"Fix issues in file: {PathStr}",
                            output=f"Repaired {PathStr}",
                            completionCriteria=f"Passes QA verification for {PathStr}",
                            priority=1
                        )
                        setattr(NewTask, "name", f"Fix {PathStr}")
                        setattr(NewTask, "agent", "Coding")
                        self.dag.addTask(NewTask)

                        TaskFb = f"Target File: {PathStr}\nQA Feedback:\n{feedback}"
                        self.taskFeedbacks[TaskId] = TaskFb

                    await self.run()
                else:
                    for task in completedTasks:
                        tname = getattr(task, "name", getattr(task, "objective", task.id))
                        print(f"[FAILED] {tname}")
                        task.status = "pending"
                        self.taskFeedbacks[task.id] = feedback
                    self.loadReadyTasks()
                    if self.queue:
                        await self.run()

