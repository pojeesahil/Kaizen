from collections import defaultdict, deque
from typing import Dict, List

from agents.models import TaskNode


class DAG:

    def __init__(self):
        self.tasks: Dict[str, TaskNode] = {}
        self.graph: Dict[str, List[str]] = defaultdict(list)
        self.indegree: Dict[str, int] = defaultdict(int)

    def add_task(self, task: TaskNode) -> None:

        self.tasks[task.id] = task
        self.indegree.setdefault(task.id, 0)

    def add_dependency(self, parent: str, child: str) -> None:

        self.graph[parent].append(child)
        self.indegree[child] += 1

    def build(self) -> None:

        for task in self.tasks.values():
            for dependency in task.dependencies:
                self.add_dependency(dependency, task.id)

    def get_ready_tasks(self) -> List[TaskNode]:

        return [
            task
            for task in self.tasks.values()
            if task.status == "pending"
            and self.indegree[task.id] == 0
        ]

    def mark_complete(self, task_id: str) -> None:

        self.tasks[task_id].status = "completed"

        for child in self.graph[task_id]:
            self.indegree[child] -= 1

    def topological_sort(self) -> List[str]:

        indegree = self.indegree.copy()
        queue = deque(node for node, degree in indegree.items() if degree == 0)

        order = []

        while queue:
            node = queue.popleft()
            order.append(node)

            for child in self.graph[node]:
                indegree[child] -= 1

                if indegree[child] == 0:
                    queue.append(child)

        if len(order) != len(self.tasks):
            raise ValueError("Cycle detected in task DAG.")

        return order