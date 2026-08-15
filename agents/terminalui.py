import sys
import time
from typing import Dict, Any, Optional
from agents.planneragent import plannerAgent
from agents.models import planningEvent, dagPlan

resetColor = "\033[0m"
dimColor = "\033[2m"
boldColor = "\033[1m"
cyanColor = "\033[36m"
greenColor = "\033[32m"
yellowColor = "\033[33m"
greyColor = "\033[90m"

stageColor = {
    "understanding": cyanColor,
    "deliverable": yellowColor,
    "merging": cyanColor,
    "done": greenColor,
}

iconGlyph = {
    "Thinking": "\U0001F9E0",
    "OK": "\u2713",
    "Plan": "\U0001F4C4",
    "...": "\u2026",
    "Merge": "\U0001F500",
    "-": "\u2022",
    "Done": "\u2705",
}

barWidth = 24


class terminalUi:
    def __init__(self, stream=sys.stdout, paceSeconds: float = 0.02) -> None:
        self.stream = stream
        self.paceSeconds = paceSeconds
        self.currentDeliverable: Optional[str] = None

    def run(self, promptAgentOutput: Dict[str, Any]) -> dagPlan:
        agent = plannerAgent()
        self._divider()
        for eventItem in agent.planStream(promptAgentOutput):
            self.renderEvent(eventItem)
        self._divider()
        self._renderSummary(agent.lastResult)
        return agent.lastResult

    def renderEvent(self, eventItem: planningEvent) -> None:
        self._maybeRenderDeliverableHeader(eventItem)

        colorVal = stageColor.get(eventItem.stage, resetColor)
        glyphVal = iconGlyph.get(eventItem.icon, eventItem.icon)
        self._write(f"{colorVal}{glyphVal}{resetColor} {eventItem.message}")

        if eventItem.progress is not None:
            self._write(self._progressBar(eventItem.progress))

        if self.paceSeconds:
            time.sleep(self.paceSeconds)

    def _maybeRenderDeliverableHeader(self, eventItem: planningEvent) -> None:
        isNewDeliverable = (
            eventItem.stage == "deliverable" and eventItem.deliverableName != self.currentDeliverable
        )
        if not isNewDeliverable:
            return
        self.currentDeliverable = eventItem.deliverableName
        self._divider()
        self._write(f"{boldColor}\U0001F4C4 Planning{resetColor}")
        self._write(f"  {dimColor}\u2022{resetColor} {eventItem.deliverableName}")

    def _renderSummary(self, plan: Optional[dagPlan]) -> None:
        if plan is None:
            return
        self._write(f"{boldColor}Planner summary{resetColor}")
        for targetDeliverable in plan.deliverables:
            depNote = (
                f" (depends on {len(targetDeliverable.dependencies)})"
                if targetDeliverable.dependencies
                else " (independent)"
            )
            self._write(f"  {greenColor}\u2713{resetColor} {targetDeliverable.name}{greyColor}{depNote}{resetColor}")
        self._write(f"{boldColor}DAG summary{resetColor}")
        self._write(f"  {len(plan.taskNodes)} tasks ready for the Scheduler")

    def _progressBar(self, progressVal: float) -> str:
        filledCount = int(barWidth * progressVal)
        barStr = "\u2588" * filledCount + "\u2591" * (barWidth - filledCount)
        return f"  {dimColor}[{barStr}] {int(progressVal * 100)}%{resetColor}"

    def _divider(self) -> None:
        self._write(f"{greyColor}{'-' * 40}{resetColor}")

    def _write(self, textStr: str) -> None:
        print(textStr, file=self.stream, flush=True)


TerminalUI = terminalUi
