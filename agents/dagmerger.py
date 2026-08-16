from typing import List, Dict, Optional
from agents.models import deliverable, deliverablePlan, taskNode, dagPlan


class dagMerger:
    def merge(self, plansList: List[deliverablePlan], deliverablesList: Optional[List[deliverable]] = None) -> dagPlan:
        deliverablesList = deliverablesList or [p.deliverable for p in plansList]
        allTasks: List[taskNode] = []
        firstTaskByDeliverable: Dict[str, str] = {}
        lastTaskByDeliverable: Dict[str, str] = {}

        for planItem in plansList:
            if not planItem.tasks:
                continue
            firstTaskByDeliverable[planItem.deliverable.id] = planItem.tasks[0].id
            lastTaskByDeliverable[planItem.deliverable.id] = planItem.tasks[-1].id
            allTasks.extend(planItem.tasks)

        taskByIdMap = {t.id: t for t in allTasks}

        for deliverableItem in deliverablesList:
            entryTaskId = firstTaskByDeliverable.get(deliverableItem.id)
            if not entryTaskId:
                continue
            entryTask = taskByIdMap[entryTaskId]
            for depDeliverableId in deliverableItem.dependencies:
                depExitId = lastTaskByDeliverable.get(depDeliverableId)
                if depExitId and depExitId not in entryTask.dependencies:
                    entryTask.dependencies.append(depExitId)

        return dagPlan(taskNodes=allTasks, deliverables=deliverablesList)


DAGMerger = dagMerger
