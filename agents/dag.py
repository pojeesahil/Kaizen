from collections import defaultdict, deque
from agents.models import TaskNode


class DAG:

    def __init__(self):
        self.tasks = {}
        self.in_degree = defaultdict(int)
        self.graph = defaultdict(list)

    def add_task(self, task: TaskNode):
        self.tasks[task.id] = task
        if task.id not in self.in_degree:
            self.in_degree[task.id] = 0

    def build(self):
        for task in self.tasks.values():
            deps = getattr(task, "dependencies", []) or []
            for dep in deps:
                if dep in self.tasks:
                    self.graph[dep].append(task.id)
                    self.in_degree[task.id] += 1

    def topological_sort(self):
        in_degree = self.in_degree.copy()
        queue = deque([task_id for task_id, deg in in_degree.items() if deg == 0])
        sorted_order = []

        while queue:
            node = queue.popleft()
            sorted_order.append(node)

            for neighbor in self.graph[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return sorted_order

    def get_ready_tasks(self):
        return [
            task
            for task in self.tasks.values()
            if self.in_degree[task.id] == 0 and getattr(task, "status", "pending") == "pending"
        ]

    def mark_complete(self, task_id: str):
        if task_id in self.tasks:
            setattr(self.tasks[task_id], "status", "completed")
            for neighbor in self.graph[task_id]:
                self.in_degree[neighbor] -= 1
