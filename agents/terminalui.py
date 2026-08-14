import sys
import time
from typing import Dict, Any, Optional
from agents.planneragent import PlannerAgent
from agents.models import PlanningEvent, DAGPlan

Reset = "\033[0m"
Dim = "\033[2m"
Bold = "\033[1m"
Cyan = "\033[36m"
Green = "\033[32m"
Yellow = "\033[33m"
Grey = "\033[90m"

StageColor = {
    "understanding": Cyan,
    "deliverable": Yellow,
    "merging": Cyan,
    "done": Green,
}

IconGlyph = {
    "Thinking": "\U0001F9E0",
    "OK": "\u2713",
    "Plan": "\U0001F4C4",
    "...": "\u2026",
    "Merge": "\U0001F500",
    "-": "\u2022",
    "Done": "\u2705",
}

BarWidth = 24


class TerminalUI:

    def __init__(self, Stream = sys.stdout, PaceSeconds: float = 0.02) -> None:
        self.Stream = Stream
        self.PaceSeconds = PaceSeconds
        self.CurrentDeliverable: Optional[str] = None

    def run(self, PromptAgentOutput: Dict[str, Any]) -> DAGPlan:
        Agent = PlannerAgent()
        self._divider()
        for Event in Agent.planStream(PromptAgentOutput):
            self.renderEvent(Event)
        self._divider()
        self._renderSummary(Agent.LastResult)
        return Agent.LastResult

    def renderEvent(self, Event: PlanningEvent) -> None:
        self._maybeRenderDeliverableHeader(Event)

        Color = StageColor.get(Event.stage, Reset)
        Glyph = IconGlyph.get(Event.icon, Event.icon)
        self._write(f"{Color}{Glyph}{Reset} {Event.message}")

        if Event.progress is not None:
            self._write(self._progressBar(Event.progress))

        if self.PaceSeconds:
            time.sleep(self.PaceSeconds)

    def _maybeRenderDeliverableHeader(self, Event: PlanningEvent) -> None:
        IsNewDeliverable = (
            Event.stage == "deliverable" and Event.deliverableName != self.CurrentDeliverable
        )
        if not IsNewDeliverable:
            return
        self.CurrentDeliverable = Event.deliverableName
        self._divider()
        self._write(f"{Bold}\U0001F4C4 Planning{Reset}")
        self._write(f"  {Dim}\u2022{Reset} {Event.deliverableName}")

    def _renderSummary(self, DagPlan: Optional[DAGPlan]) -> None:
        if DagPlan is None:
            return
        self._write(f"{Bold}Planner summary{Reset}")
        for Deliverable in DagPlan.deliverables:
            DepNote = (
                f" (depends on {len(Deliverable.dependencies)})"
                if Deliverable.dependencies
                else " (independent)"
            )
            self._write(f"  {Green}\u2713{Reset} {Deliverable.name}{Grey}{DepNote}{Reset}")
        self._write(f"{Bold}DAG summary{Reset}")
        self._write(f"  {len(DagPlan.taskNodes)} tasks ready for the Scheduler")

    def _progressBar(self, Progress: float) -> str:
        Filled = int(BarWidth * Progress)
        Bar = "\u2588" * Filled + "\u2591" * (BarWidth - Filled)
        return f"  {Dim}[{Bar}] {int(Progress * 100)}%{Reset}"

    def _divider(self) -> None:
        self._write(f"{Grey}{'-' * 40}{Reset}")

    def _write(self, Text: str) -> None:
        print(Text, file = self.Stream, flush = True)
