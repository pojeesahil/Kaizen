from typing import List, Dict, Optional
from agents.models import deliverable, deliverablePlan, taskNode, dagPlan, newId


class dagMerger:
    def merge(self, plansList: List[deliverablePlan], deliverablesList: Optional[List[deliverable]] = None) -> dagPlan:
        deliverablesList = deliverablesList or [p.deliverable for p in plansList]
        allTasks: List[taskNode] = []
        firstTaskByDeliverable: Dict[str, str] = {}
        exitTasksByDeliverable: Dict[str, List[str]] = {}

        for planItem in plansList:
            if not planItem.tasks:
                continue
            firstTaskByDeliverable[planItem.deliverable.id] = planItem.tasks[0].id

            internalDepIds = set()
            for task in planItem.tasks:
                internalDepIds.update(task.dependencies)

            exitIds = [
                task.id for task in planItem.tasks
                if task.id not in internalDepIds
            ]
            if not exitIds:
                exitIds = [planItem.tasks[-1].id]

            exitTasksByDeliverable[planItem.deliverable.id] = exitIds
            allTasks.extend(planItem.tasks)

        taskByIdMap = {t.id: t for t in allTasks}

        for deliverableItem in deliverablesList:
            entryTaskId = firstTaskByDeliverable.get(deliverableItem.id)
            if not entryTaskId:
                continue
            entryTask = taskByIdMap[entryTaskId]
            for depDeliverableId in deliverableItem.dependencies:
                depExitIds = exitTasksByDeliverable.get(depDeliverableId, [])
                for exitId in depExitIds:
                    if exitId not in entryTask.dependencies:
                        entryTask.dependencies.append(exitId)

        if len(allTasks) > 1:
            allTaskIds = {t.id for t in allTasks}
            depTaskIds = set()
            for t in allTasks:
                depTaskIds.update(t.dependencies)
            leafTaskIds = list(allTaskIds - depTaskIds)
            if not leafTaskIds:
                leafTaskIds = [allTasks[-1].id]

            lastDeliverableId = deliverablesList[-1].id if deliverablesList else "orchestration"
            orchestrationTaskId = newId("task-orch")
            orchestrationTask = taskNode(
                id=orchestrationTaskId,
                deliverableId=lastDeliverableId,
                objective="Integrate, wire, and orchestrate all created components, services, and modules into the main application entrypoint and verify end-to-end execution flow.",
                output="Updated application entrypoint with connected modules and verified call flows.",
                completionCriteria="The main entrypoint imports and executes all primary modules, user interactions, and services without stubs or unwired components.",
                dependencies=leafTaskIds,
                priority=5
            )
            allTasks.append(orchestrationTask)

        return dagPlan(taskNodes=allTasks, deliverables=deliverablesList)


DAGMerger = dagMerger
