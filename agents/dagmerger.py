from typing import List, Dict
from agents.models import Deliverable, DeliverablePlan, TaskNode, DAGPlan


class DAGMerger:
    def merge(self, Plans: List[DeliverablePlan], Deliverables: List[Deliverable] = None) -> DAGPlan:
        Deliverables = Deliverables or [p.deliverable for p in Plans]
        AllTasks: List[TaskNode] = []
        FirstTaskByDeliverable: Dict[str, str] = {}
        LastTaskByDeliverable: Dict[str, str] = {}

        for Plan in Plans:
            if not Plan.tasks:
                continue
            FirstTaskByDeliverable[Plan.deliverable.id] = Plan.tasks[0].id
            LastTaskByDeliverable[Plan.deliverable.id] = Plan.tasks[-1].id
            AllTasks.extend(Plan.tasks)

        TaskById = {Task.id: Task for Task in AllTasks}

        for Deliverable in Deliverables:
            EntryTaskId = FirstTaskByDeliverable.get(Deliverable.id)
            if not EntryTaskId:
                continue
            EntryTask = TaskById[EntryTaskId]
            for DepDeliverableId in Deliverable.dependencies:
                DepExitId = LastTaskByDeliverable.get(DepDeliverableId)
                if DepExitId and DepExitId not in EntryTask.dependencies:
                    EntryTask.dependencies.append(DepExitId)

        return DAGPlan(taskNodes = AllTasks, deliverables = Deliverables)
