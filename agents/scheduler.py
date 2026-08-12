import asyncio
import heapq
import re

from agents.dag import DAG
from agents.models import TaskNode


class Scheduler:

    def __init__(self, dag: DAG, goal: str = ""):
        self.dag = dag
        self.goal = goal
        self.queue: list[tuple[int, str]] = []
        self.taskOutputs: dict[str, str] = {}
        self.taskFeedbacks: dict[str, str] = {}

    def extractAffectedFiles(self, CoderResults: list, Feedback: str) -> list[str]:
        Files = []
        for Result in CoderResults:
            ToolLogs = Result.get("toolResults", [])
            for Log in ToolLogs:
                FoundPaths = re.findall(r"path['\"]?\s*:\s*['\"]([^'\"]+)['\"]", Log)
                for PathStr in FoundPaths:
                    if PathStr not in Files:
                        Files.append(PathStr)

        Pattern = r"\b[\w.-]+\.(?:py|js|ts|html|css|json|java|c|cpp)\b"
        FeedbackFiles = re.findall(Pattern, Feedback)
        for PathStr in FeedbackFiles:
            if PathStr not in Files:
                Files.append(PathStr)

        return Files

    def load_ready_tasks(self) -> None:
        for task in self.dag.get_ready_tasks():
            if getattr(task, "status", "pending") != "pending":
                continue
            task.status = "running"
            heapq.heappush(self.queue, (task.priority, task.id))

    def executeCoder(self, task: TaskNode) -> dict:
        tname = getattr(task, "name", getattr(task, "objective", task.id))
        print(f"\n[{getattr(task, 'agent', 'Coding')}] Starting Coder Agent for task: {tname}")
        from main import runCoder

        dependencyContext = ""
        for depId in getattr(task, "dependencies", []):
            if depId in self.taskOutputs:
                dependencyContext += f"\n- Parent task '{depId}' output: {self.taskOutputs[depId]}"

        instruction = f"Overall Goal: {self.goal}\nTask: {tname}" if self.goal else tname
        feedback = self.taskFeedbacks.get(task.id, "")
        return runCoder(instruction, taskContext=dependencyContext, feedback=feedback)

    async def run(self) -> None:
        self.loadReadyTasks()

        completedTasks = []
        allCoderResults = []

        while self.queue:
            batch = []

            while self.queue:
                _, task_id = heapq.heappop(self.queue)
                batch.append(self.dag.tasks[task_id])

            print(f"\nRunning {len(batch)} Coder Agent(s) in Parallel ")
            coderResults = await asyncio.gather(
                *(asyncio.to_thread(self.executeCoder, task) for task in batch)
            )

            for task, res in zip(batch, coderResults):
                self.dag.mark_complete(task.id)
                self.taskOutputs[task.id] = res.get("coderMessage", "Task completed.")
                self.taskFeedbacks.pop(task.id, None)

            completedTasks.extend(batch)
            allCoderResults.extend(coderResults)

            self.load_ready_tasks()

        if completedTasks:
            from main import runBatchEval
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
                        self.dag.add_task(NewTask)

                        TaskFb = f"Target File: {PathStr}\nQA Feedback:\n{feedback}"
                        self.taskFeedbacks[TaskId] = TaskFb

                    await self.run()
                else:
                    for task in completedTasks:
                        tname = getattr(task, "name", getattr(task, "objective", task.id))
                        print(f"[FAILED] {tname}")
                        task.status = "pending"
                        self.taskFeedbacks[task.id] = feedback
                    self.load_ready_tasks()
                    if self.queue:
                        await self.run()

