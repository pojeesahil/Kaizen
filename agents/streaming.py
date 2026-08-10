from typing import Iterator, Dict, Any, List
from agents.models import PlanningEvent, Deliverable, DeliverablePlan
from agents.deliverabledetector import DeliverableDetector
from agents.dependencyresolver import DependencyResolver
from agents.deliverableplanner import DeliverablePlanner
from agents.dagmerger import DAGMerger

ThinkingSummaries = {
    "ui_page": "Designing layout and structure...",
    "frontend": "Identifying components and API calls...",
    "backend": "Designing API surface and logic...",
    "database_schema": "Designing data model...",
    "documentation": "Gathering project details to document...",
    "deployment_script": "Determining runtime requirements...",
    "ci_cd_workflow": "Drafting pipeline stages...",
    "tests": "Identifying test coverage needed...",
    "config": "Identifying required settings...",
}


class StreamingPlanner:

    def __init__(self) -> None:
        self.Detector = DeliverableDetector()
        self.Resolver = DependencyResolver()
        self.Planner = DeliverablePlanner()
        self.Merger = DAGMerger()
        self.LastResult = None

    def planStream(self, PromptAgentOutput: Dict[str, Any]) -> Iterator[PlanningEvent]:
        yield PlanningEvent(stage = "understanding", icon = "Thinking", message = "Understanding request...")

        Deliverables = self.Detector.detect(PromptAgentOutput)
        yield PlanningEvent(stage = "understanding", icon = "OK", message = f"Detected {PromptAgentOutput.get('project_type', 'project')}")
        yield PlanningEvent(stage = "understanding", icon = "OK", message = f"Found {len(Deliverables)} deliverable(s)")

        Deliverables = self.Resolver.resolve(Deliverables)

        Plans: List[DeliverablePlan] = []
        Total = len(Deliverables) or 1
        for Index, Deliverable in enumerate(Deliverables, start=1):
            yield PlanningEvent(stage = "deliverable", icon = "Plan", message = f"Planning {Deliverable.name}", deliverableName = Deliverable.name, progress = (Index - 1) / Total)
            yield PlanningEvent(stage = "deliverable", icon = "...", message = self._thinkingSummary(Deliverable), deliverableName = Deliverable.name)

            Plan = self.Planner.plan(Deliverable)
            Plans.append(Plan)

            yield PlanningEvent(stage = "deliverable", icon = "OK", message = f"Plan generated ({len(Plan.tasks)} tasks)", deliverableName = Deliverable.name, progress = Index / Total)

        yield PlanningEvent(stage = "merging", icon = "Merge", message = "Merging plans")
        yield PlanningEvent(stage = "merging", icon = "-", message = "Building DAG...")

        DagPlan = self.Merger.merge(Plans, Deliverables)

        yield PlanningEvent(stage = "merging", icon = "-", message = "Resolving dependencies...")
        yield PlanningEvent(stage = "merging", icon = "-", message = "Scheduling parallel tasks...")
        yield PlanningEvent(stage = "done", icon = "Done", message = f"Done. {len(DagPlan.taskNodes)} tasks across {len(Deliverables)} deliverables.", progress = 1.0)

        self.LastResult = DagPlan

    @staticmethod
    def _thinkingSummary(Deliverable: Deliverable) -> str:
        return ThinkingSummaries.get(Deliverable.kind, "Analysing requirements...")
