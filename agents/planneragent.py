from typing import Dict, Any, Iterator
from models import DAGPlan, PlanningEvent
from deliverabledetector import DeliverableDetector
from dependencyresolver import DependencyResolver
from deliverableplanner import DeliverablePlanner
from dagmerger import DAGMerger
from streaming import StreamingPlanner


class PlannerAgent:

    def __init__(self) -> None:
        self.Detector = DeliverableDetector()
        self.Resolver = DependencyResolver()
        self.Planner = DeliverablePlanner()
        self.Merger = DAGMerger()
        self.LastResult = None

    def plan(self, PromptAgentOutput: Dict[str, Any]) -> DAGPlan:

        Deliverables = self.Detector.detect(PromptAgentOutput)
        Deliverables = self.Resolver.resolve(Deliverables)
        Plans = [self.Planner.plan(Deliverable) for Deliverable in Deliverables]
        self.LastResult = self.Merger.merge(Plans, Deliverables)
        return self.LastResult

    def planStream(self, PromptAgentOutput: Dict[str, Any]) -> Iterator[PlanningEvent]:

        Streaming = StreamingPlanner()
        yield from Streaming.planStream(PromptAgentOutput)
        self.LastResult = Streaming.LastResult
