from collections import defaultdict, deque
from typing import List, Dict
from agents.models import taskNode


class dag:
    def __init__(self):
        self.tasks: Dict[str, taskNode] = {}
        self.inDegree: Dict[str, int] = defaultdict(int)
        self.graph: Dict[str, List[str]] = defaultdict(list)

    def addTask(self, taskItem: taskNode) -> None:
        self.tasks[taskItem.id] = taskItem
        if taskItem.id not in self.inDegree:
            self.inDegree[taskItem.id] = 0

    def build(self) -> None:
        for taskItem in self.tasks.values():
            depsList = getattr(taskItem, "dependencies", []) or []
            for depId in depsList:
                if depId in self.tasks:
                    self.graph[depId].append(taskItem.id)
                    self.inDegree[taskItem.id] += 1

    def topologicalSort(self) -> List[str]:
        inDegreeCopy = self.inDegree.copy()
        queue = deque([taskId for taskId, degreeVal in inDegreeCopy.items() if degreeVal == 0])
        sortedOrder: List[str] = []

        while queue:
            nodeId = queue.popleft()
            sortedOrder.append(nodeId)

            for neighborId in self.graph[nodeId]:
                inDegreeCopy[neighborId] -= 1
                if inDegreeCopy[neighborId] == 0:
                    queue.append(neighborId)

        return sortedOrder

    def getReadyTasks(self) -> List[taskNode]:
        return [
            taskItem
            for taskItem in self.tasks.values()
            if self.inDegree[taskItem.id] == 0 and getattr(taskItem, "status", "pending") == "pending"
        ]

    def markComplete(self, taskId: str) -> None:
        if taskId in self.tasks:
            setattr(self.tasks[taskId], "status", "completed")
            for neighborId in self.graph[taskId]:
                self.inDegree[neighborId] -= 1


DAG = dag
