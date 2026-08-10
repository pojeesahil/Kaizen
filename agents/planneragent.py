from typing import Dict, Any, Iterator
from agents.models import DAGPlan, PlanningEvent
from agents.deliverabledetector import DeliverableDetector
from agents.dependencyresolver import DependencyResolver
from agents.deliverableplanner import DeliverablePlanner
from agents.dagmerger import DAGMerger
from agents.streaming import StreamingPlanner


class PlannerAgent:

    def __init__(self):
        self.Detector = DeliverableDetector()
        self.Resolver = DependencyResolver()
        self.Planner = DeliverablePlanner()
        self.Merger = DAGMerger()
        self.StreamingPlanner = StreamingPlanner()

    def plan(self, PromptAgentOutput: Dict[str, Any]) -> DAGPlan:
        Deliverables = self.Detector.detect(PromptAgentOutput)
        ResolvedDeliverables = self.Resolver.resolve(Deliverables)

        Plans = []
        for Deliverable in ResolvedDeliverables:
            Plan = self.Planner.plan(Deliverable)
            Plans.append(Plan)

        CombinedPlan = self.Merger.merge(Plans, ResolvedDeliverables)
        return CombinedPlan

    def plan_stream(self, PromptAgentOutput: Dict[str, Any]) -> Iterator[PlanningEvent]:
        yield from self.StreamingPlanner.stream_plan(PromptAgentOutput)
