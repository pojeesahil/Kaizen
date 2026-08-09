from typing import List, Optional
from models import Deliverable, TaskNode, DeliverablePlan, newId

StepTemplates = {
    "ui_page": ["Analyse requirements", "Design layout", "Implement HTML/CSS", "Validate against requirements"],
    "frontend": ["Analyse requirements", "Design component structure", "Implement components", "Wire up API calls", "Validate UI behaviour"],
    "backend": ["Analyse requirements", "Design API surface", "Implement endpoints", "Implement business logic", "Validate against requirements"],
    "database_schema": ["Analyse data requirements", "Design schema", "Implement migrations", "Validate schema"],
    "documentation": ["Gather project details", "Draft documentation", "Review for accuracy"],
    "deployment_script": ["Analyse runtime requirements", "Draft configuration", "Validate build"],
    "ci_cd_workflow": ["Analyse pipeline requirements", "Draft workflow", "Validate workflow"],
    "tests": ["Identify test scope", "Write test cases", "Validate coverage"],
    "config": ["Identify required settings", "Draft configuration file", "Validate configuration"],
    "generic": ["Analyse requirements", "Design implementation", "Implement", "Validate"]
}

KindPriority = {
    "backend": 1,
    "database_schema": 1,
    "frontend": 2,
    "ui_page": 2,
    "config": 2,
    "deployment_script": 2,
    "tests": 3,
    "ci_cd_workflow": 3,
    "documentation": 4,
    "generic": 3,
}


class DeliverablePlanner:

    def plan(self, Deliverable: Deliverable) -> DeliverablePlan:

        Steps = self._generateAtomicSteps(Deliverable)
        Priority = KindPriority.get(Deliverable.kind, 3)
        Tasks = self._buildTaskChain(Deliverable, Steps, Priority)
        return DeliverablePlan(deliverable=Deliverable, tasks=Tasks)

    def _generateAtomicSteps(self, Deliverable: Deliverable) -> List[str]:
        return StepTemplates.get(Deliverable.kind, StepTemplates["generic"])

    def _buildTaskChain(self, Deliverable: Deliverable, Steps: List[str], Priority: int) -> List[TaskNode]:

        Tasks: List[TaskNode] = []
        PreviousId: Optional[str] = None

        for Index, Step in enumerate(Steps, start=1):
            TaskId = newId(f"{Deliverable.id}-t{Index}")
            IsLast = Index == len(Steps)
            Task = TaskNode(
                id = TaskId,
                deliverableId=Deliverable.id,
                objective = f"{Step}: {Deliverable.name}",
                output = Deliverable.name if IsLast else f"{Step.lower()} for {Deliverable.name}",
                completionCriteria = self._completionCriteria(Step, Deliverable, IsLast),
                parentTask = PreviousId,
                dependencies = [PreviousId] if PreviousId else [],
                priority = Priority,
            )
            if PreviousId:
                _attachChild(Tasks, PreviousId, TaskId)
            Tasks.append(Task)
            PreviousId = TaskId

        return Tasks

    @staticmethod
    def _completionCriteria(Step: str, Deliverable: Deliverable, IsLast: bool) -> str:
        if IsLast:
            return f"{Deliverable.name} exists, matches spec, and passes validation."
        return f"'{Step}' complete for {Deliverable.name}."


def _attachChild(Tasks: List[TaskNode], ParentId: str, ChildId: str) -> None:
    for Task in Tasks:
        if Task.id == ParentId:
            Task.childTasks.append(ChildId)
            return
