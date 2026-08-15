import os
from typing import Dict, Any, Iterator
from agents.models import dagPlan, planningEvent
from agents.deliverabledetector import deliverableDetector
from agents.dependencyresolver import dependencyResolver
from agents.deliverableplanner import deliverablePlanner
from agents.dagmerger import dagMerger
from agents.streaming import streamingPlanner
from agents.dagvisualization import visualizeDag


class plannerAgent:
    def __init__(self):
        self.detector = deliverableDetector()
        self.resolver = dependencyResolver()
        self.planner = deliverablePlanner()
        self.merger = dagMerger()
        self.streamingPlanner = streamingPlanner(
            detector = self.detector,
            resolver = self.resolver,
            planner = self.planner,
            merger = self.merger,
        )
        self.lastResult = None

    def plan(self, promptAgentOutput: Dict[str, Any]) -> dagPlan:
        deliverablesList = self.detector.detect(promptAgentOutput)
        resolvedDeliverables = self.resolver.resolve(deliverablesList)

        plansList = []
        for targetDeliverable in resolvedDeliverables:
            planItem = self.planner.plan(targetDeliverable)
            plansList.append(planItem)

        combinedPlan = self.merger.merge(plansList, resolvedDeliverables)
        self.lastResult = combinedPlan
        self._autoVisualize(combinedPlan)
        return combinedPlan

    def planStream(self, promptAgentOutput: Dict[str, Any]) -> Iterator[planningEvent]:
        yield from self.streamingPlanner.planStream(promptAgentOutput)
        self.lastResult = self.streamingPlanner.lastResult
        if self.lastResult:
            self._autoVisualize(self.lastResult)

    plan_stream = planStream

    def _autoVisualize(self, plan: dagPlan) -> None:
        try:
            targetDirectory = os.path.join("work", "DAG")
            visualizeDag(plan, outputDirectory=targetDirectory, baseFilename="dag_flow")
        except Exception as err:
            print(f"PlannerAgent's DAG visualization auto-save notice: {err}")

    @property
    def LastResult(self):
        return self.lastResult

    @LastResult.setter
    def LastResult(self, value):
        self.lastResult = value


PlannerAgent = plannerAgent
