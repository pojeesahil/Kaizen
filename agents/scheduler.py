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

    def load_ready_tasks(self) -> None:

        for task in self.dag.get_ready_tasks():
            if task.status != "pending":
                continue
            task.status = "running"
            heapq.heappush(self.queue, (task.priority, task.id))

    async def execute(self, task: TaskNode) -> TaskResult:

        print(f"[{task.agent}] {task.name}")

        from main import runAgent

        dependencyContext = ""
        for depId in task.dependencies:
            if depId in self.taskOutputs:
                dependencyContext += f"\n- Parent task '{depId}' output: {self.taskOutputs[depId]}"

        instruction = f"Overall Goal: {self.goal}\nTask: {task.name}" if self.goal else task.name
        runResult = runAgent(instruction, taskContext=dependencyContext)

        if isinstance(runResult, tuple):
            success, outputSummary = runResult
        else:
            success, outputSummary = bool(runResult), f"{task.name} completed."

        if success:
            self.taskOutputs[task.id] = outputSummary

        return TaskResult(
            task_id=task.id,
            success=True if success is None or success else False,
            message=outputSummary
        )

    async def run(self) -> None:
        self.load_ready_tasks()

        while self.queue:

            current_priority = self.queue[0][0]
            batch = []

            while self.queue and self.queue[0][0] == current_priority:
                _, task_id = heapq.heappop(self.queue)
                batch.append(self.dag.tasks[task_id])

            results = await asyncio.gather(
                *(self.execute(task) for task in batch)
            )

            for task, result in zip(batch, results):
                if result.success:
                    self.dag.mark_complete(task.id)
                else:
                    print(f"[FAILED] {task.name}")
                    task.status = "pending"

            self.load_ready_tasks()