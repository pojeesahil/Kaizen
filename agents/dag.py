from collections import defaultdict, deque
from agents.models import TaskNode


class DAG:

    def __init__(self):
        self.tasks = {}
        self.inDegree = defaultdict(int)
        self.graph = defaultdict(list)

    def addTask(self, task: TaskNode):
        self.tasks[task.id] = task
        if task.id not in self.inDegree:
            self.inDegree[task.id] = 0

    def build(self):
        for task in self.tasks.values():
            deps = getattr(task, "dependencies", []) or []
            for dep in deps:
                if dep in self.tasks:
                    self.graph[dep].append(task.id)
                    self.inDegree[task.id] += 1

    def topologicalSort(self):
        inDegree = self.inDegree.copy()
        queue = deque([taskId for taskId, deg in inDegree.items() if deg == 0])
        sorted_order = []

        while queue:
            node = queue.popleft()
            sorted_order.append(node)

            for neighbor in self.graph[node]:
                inDegree[neighbor] -= 1
                if inDegree[neighbor] == 0:
                    queue.append(neighbor)

        return sorted_order

    def getReadyTasks(self):
        return [
            task
            for task in self.tasks.values()
            if self.inDegree[task.id] == 0 and getattr(task, "status", "pending") == "pending"
        ]

    def markComplete(self, taskId: str):
        if taskId in self.tasks:
            setattr(self.tasks[taskId], "status", "completed")
            for neighbor in self.graph[taskId]:
                self.inDegree[neighbor] -= 1
