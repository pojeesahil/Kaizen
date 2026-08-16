import os
from typing import Dict, List
from agents.models import dagPlan, taskNode, deliverable


class dagVisualizer:
    def __init__(self, plan: dagPlan):
        self.plan = plan
        self.deliverableById: Dict[str, deliverable] = {d.id: d for d in plan.deliverables}
        self.tasksByDeliverable: Dict[str, List[taskNode]] = {}

        for task in plan.taskNodes:
            self.tasksByDeliverable.setdefault(task.deliverableId, []).append(task)

    def toMermaid(self) -> str:
        lines = ["flowchart TD"]

        for delivId, taskList in self.tasksByDeliverable.items():
            delivName = self.deliverableById[delivId].name if delivId in self.deliverableById else delivId
            safeDelivId = delivId.replace("-", "_")
            lines.append(f"subgraph sub_{safeDelivId} [\"{delivName}\"]")
            for task in taskList:
                safeTaskId = task.id.replace("-", "_")
                label = task.objective.replace('"', "'")
                lines.append(f"{safeTaskId}[\"{label}\"]")
            lines.append("end")

        for task in self.plan.taskNodes:
            safeTaskId = task.id.replace("-", "_")
            for depId in task.dependencies:
                safeDepId = depId.replace("-", "_")
                lines.append(f"{safeDepId} --> {safeTaskId}")

        return "\n".join(lines)

    def toDot(self) -> str:
        lines = ["digraph DAGPlan {", 'rankdir = "TB";', 'node [shape = box, style = rounded];']

        for delivId, taskList in self.tasksByDeliverable.items():
            delivName = self.deliverableById[delivId].name if delivId in self.deliverableById else delivId
            safeDelivId = delivId.replace("-", "_")
            lines.append(f"subgraph cluster_{safeDelivId} {{")
            lines.append(f'label="{delivName}";')
            lines.append('style=dashed;')
            for task in taskList:
                safeTaskId = task.id.replace("-", "_")
                label = task.objective.replace('"', "'")
                lines.append(f'        {safeTaskId} [label="{label}"];')
            lines.append("}")

        for task in self.plan.taskNodes:
            safeTaskId = task.id.replace("-", "_")
            for depId in task.dependencies:
                safeDepId = depId.replace("-", "_")
                lines.append(f"    {safeDepId} -> {safeTaskId};")

        lines.append("}")
        return "\n".join(lines)

    def toTextTree(self) -> str:
        lines = ["DAG VISUALIZATION"]

        for d in self.plan.deliverables:
            deps = ", ".join(d.dependencies) if d.dependencies else "none"
            lines.append(f"\nDeliverable: [{d.id}] {d.name} (Priority: {d.priority}, Depends on: {deps})")
            taskList = self.tasksByDeliverable.get(d.id, [])
            if not taskList:
                lines.append("(No tasks)")
            for t in taskList:
                tdeps = ", ".join(t.dependencies) if t.dependencies else "none"
                lines.append(f"  |-- Task [{t.id}]: {t.objective} (deps: {tdeps})")

        return "\n".join(lines)

    def toMarkdown(self) -> str:
        lines = [
            "# KAIZEN Plan & DAG Execution Flow",
            "",
            "## Overview",
            f"- **Deliverables Count**: {len(self.plan.deliverables)}",
            f"- **Tasks Count**: {len(self.plan.taskNodes)}",
            "",
            "## DAG Dependency Diagram",
            "",
            "```mermaid",
            self.toMermaid(),
            "```",
            "",
            "## Deliverables and Task Details",
        ]

        for d in self.plan.deliverables:
            deps = ", ".join(d.dependencies) if d.dependencies else "None"
            lines.append(f"\nDeliverable: `{d.name}` (`{d.id}`)")
            lines.append(f"- Kind: `{d.kind}`")
            lines.append(f"- Goal: {d.goal}")
            lines.append(f"- Priority: `{d.priority}`")
            lines.append(f"- Deliverable Dependencies: `{deps}`")
            lines.append("- Tasks: ")

            taskList = self.tasksByDeliverable.get(d.id, [])
            if not taskList:
                lines.append("  - *(No tasks)*")
            for indexVal, t in enumerate(taskList, start=1):
                tdeps = ", ".join(t.dependencies) if t.dependencies else "None"
                lines.append(f"{indexVal}. **{t.objective}** (`{t.id}`)")
                lines.append(f"- Output: `{t.output}`")
                lines.append(f"- Completion Criteria: {t.completionCriteria}")
                lines.append(f"- Task Dependencies: `{tdeps}`")

        lines.extend([
            "",
            "Execution Schedule Table",
            "",
            "| Priority | Task ID | Deliverable | Objective | Dependencies |",
            "",
        ])

        for t in self.plan.taskNodes:
            delivName = self.deliverableById[t.deliverableId].name if t.deliverableId in self.deliverableById else t.deliverableId
            tdeps = ", ".join(t.dependencies) if t.dependencies else "None"
            lines.append(f"| {t.priority} | `{t.id}` | {delivName} | {t.objective} | `{tdeps}` |")

        return "\n".join(lines)

    def saveVisualization(self, outputDirectory: str = ".", baseFilename: str = "dag_plan") -> Dict[str, str]:
        os.makedirs(outputDirectory, exist_ok=True)
        fileFormats = {
            "mermaid": (f"{baseFilename}.mmd", self.toMermaid()),
            "dot": (f"{baseFilename}.dot", self.toDot()),
            "text": (f"{baseFilename}.txt", self.toTextTree()),
            "markdown": (f"{baseFilename}.md", self.toMarkdown()),
        }

        savedPaths = {}
        for fmt, (filename, content) in fileFormats.items():
            filePath = os.path.join(outputDirectory, filename)
            with open(filePath, "w", encoding="utf-8") as f:
                f.write(content)
            savedPaths[fmt] = filePath

        return savedPaths


def visualizeDag(plan: dagPlan, outputDirectory: str = ".", baseFilename: str = "dag_plan") -> Dict[str, str]:
    visualizer = dagVisualizer(plan)
    return visualizer.saveVisualization(outputDirectory, baseFilename)

