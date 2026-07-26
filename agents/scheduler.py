import asyncio
import heapq

from agents.dag import DAG
from agents.models import TaskNode, TaskResult

class Scheduler:

    def __init__(self, dag: DAG, goal: str = ""):
        self.dag = dag
        self.goal = goal
        self.queue: list[tuple[int, str]] = []

    def load_ready_tasks(self) -> None:

        for task in self.dag.get_ready_tasks():
            if task.status != "pending":
                continue
            task.status = "running"
            heapq.heappush(self.queue, (task.priority, task.id))

    async def execute(self, task: TaskNode) -> TaskResult:

        print(f"[{task.agent}] {task.name}")

        from main import runAgent

        instruction = f"Overall Goal: {self.goal}\nTask: {task.name}" if self.goal else task.name
        success = runAgent(instruction)

        return TaskResult(
            task_id=task.id,
            success=True if success is None or success else False,
            message=f"{task.name} completed."
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