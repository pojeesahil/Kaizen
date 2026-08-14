from typing import Dict, Any, Iterator
from models import DAGPlan, PlanningEvent
from deliverabledetector import DeliverableDetector
from dependencyresolver import DependencyResolver
from deliverableplanner import DeliverablePlanner
from dagmerger import DAGMerger
from streaming import StreamingPlanner


class PlannerAgent:

    def __init__(self):
        self.Detector = DeliverableDetector()
        self.Resolver = DependencyResolver()
        self.Planner = DeliverablePlanner()
        self.Merger = DAGMerger()
        self.StreamingPlanner = StreamingPlanner(
            Detector = self.Detector,
            Resolver = self.Resolver,
            Planner = self.Planner,
            Merger = self.Merger,
        )
        self.LastResult = None

    def plan(self, PromptAgentOutput: Dict[str, Any]) -> DAGPlan:
        Deliverables = self.Detector.detect(PromptAgentOutput)
        ResolvedDeliverables = self.Resolver.resolve(Deliverables)

        Plans = []
        for Deliverable in ResolvedDeliverables:
            Plan = self.Planner.plan(Deliverable)
            Plans.append(Plan)

        CombinedPlan = self.Merger.merge(Plans, ResolvedDeliverables)
        self.LastResult = CombinedPlan
        return CombinedPlan

    def plan_stream(self, PromptAgentOutput: Dict[str, Any]) -> Iterator[PlanningEvent]:
        yield from self.StreamingPlanner.planStream(PromptAgentOutput)
        self.LastResult = self.StreamingPlanner.LastResult

    planStream = plan_stream
