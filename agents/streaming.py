from typing import Iterator, Dict, Any, List
from agents.models import planningEvent, deliverable, deliverablePlan
from agents.deliverabledetector import deliverableDetector
from agents.dependencyresolver import dependencyResolver
from agents.deliverableplanner import deliverablePlanner
from agents.dagmerger import dagMerger

thinkingSummaries = {
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


class streamingPlanner:
    def __init__(self, detector=None, resolver=None, planner=None, merger=None) -> None:
        self.detector = detector or deliverableDetector()
        self.resolver = resolver or dependencyResolver()
        self.planner = planner or deliverablePlanner()
        self.merger = merger or dagMerger()
        self.lastResult = None

    def planStream(self, promptAgentOutput: Dict[str, Any]) -> Iterator[planningEvent]:
        yield planningEvent(stage="understanding", icon="Thinking", message="Understanding request...")

        deliverablesList = self.detector.detect(promptAgentOutput)
        yield planningEvent(stage="understanding", icon="OK", message=f"Detected {promptAgentOutput.get('project_type', 'project')}")
        yield planningEvent(stage="understanding", icon="OK", message=f"Found {len(deliverablesList)} deliverable(s)")

        deliverablesList = self.resolver.resolve(deliverablesList)

        plansList: List[deliverablePlan] = []
        totalCount = len(deliverablesList) or 1
        for indexVal, targetDeliverable in enumerate(deliverablesList, start=1):
            yield planningEvent(stage = "deliverable", icon = "Plan", message=f"Planning {targetDeliverable.name}", deliverableName = targetDeliverable.name, progress=(indexVal-1) / totalCount)
            yield planningEvent(stage = "deliverable", icon = "...", message=self._thinkingSummary(targetDeliverable), deliverableName = targetDeliverable.name)
            yield planningEvent(stage = "deliverable", icon = "...", message="Decomposing into tasks...", deliverableName = targetDeliverable.name)

            planItem = self.planner.plan(targetDeliverable)
            plansList.append(planItem)

            yield planningEvent(stage = "deliverable", icon="OK", message = f"Plan generated ({len(planItem.tasks)} tasks)", deliverableName=targetDeliverable.name, progress=indexVal / totalCount)

        yield planningEvent(stage = "merging", icon = "Merge", message = "Merging plans")
        yield planningEvent(stage = "merging", icon = "-", message = "Building DAG...")

        mergedDagPlan = self.merger.merge(plansList, deliverablesList)

        yield planningEvent(stage = "merging", icon = "-", message = "Resolving dependencies...")
        yield planningEvent(stage = "merging", icon = "-", message = "Scheduling parallel tasks...")
        yield planningEvent(stage = "done", icon = "Done", message = f"Done. {len(mergedDagPlan.taskNodes)} tasks across {len(deliverablesList)} deliverables.", progress = 1.0)

        self.lastResult = mergedDagPlan

    streamPlan = planStream
    stream_plan = planStream

    @staticmethod
    def _thinkingSummary(targetDeliverable: deliverable) -> str:
        return thinkingSummaries.get(targetDeliverable.kind, "Analysing requirements...")


StreamingPlanner = streamingPlanner
