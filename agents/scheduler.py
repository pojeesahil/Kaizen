import asyncio
import heapq

from agents.dag import DAG
from agents.models import TaskNode, TaskResult


class Scheduler:

    def __init__(self, dag: DAG, goal: str = ""):
        self.dag = dag
        self.goal = goal
        self.queue: list[tuple[int, str]] = []
        self.taskOutputs: dict[str, str] = {}
        self.taskFeedbacks: dict[str, str] = {}

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
        self.load_ready_tasks()

        while self.queue:
            batch = []

            while self.queue:
                _, task_id = heapq.heappop(self.queue)
                batch.append(self.dag.tasks[task_id])

            print(f"\n--- Running {len(batch)} Coder Agent(s) in Parallel ---")
            coderResults = await asyncio.gather(
                *(asyncio.to_thread(self.executeCoder, task) for task in batch)
            )

            from main import runBatchEval
            success, feedback = await asyncio.to_thread(runBatchEval, batch, coderResults)

            if success:
                for task, res in zip(batch, coderResults):
                    self.dag.mark_complete(task.id)
                    self.taskOutputs[task.id] = res.get("coderMessage", "Task completed.")
                    self.taskFeedbacks.pop(task.id, None)
            else:
                for task in batch:
                    tname = getattr(task, "name", getattr(task, "objective", task.id))
                    print(f"[FAILED] {tname}")
                    task.status = "pending"
                    self.taskFeedbacks[task.id] = feedback

            self.load_ready_tasks()
