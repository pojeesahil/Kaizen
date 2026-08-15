import json
import re
from typing import List, Optional, Any, Dict
from agents.models import Deliverable, TaskNode, DeliverablePlan, newId, deliverable, taskNode, deliverablePlan
from core.config import get_llm

TASK_DECOMPOSITION_PROMPT = """You are an expert software engineer. Break down the following deliverable into a compact, coarse-grained list of implementation tasks (maximum 2-3 tasks per deliverable).

RULES:
- Do NOT generate fragmented micro-tasks. Group cohesive logic together.
- Focus strictly on concrete source files and functions needed for this deliverable.

Deliverable: {name}
Kind: {kind}
Goal: {goal}
Requirements: {requirements}

For each task, provide:
- objective: what the developer should do (one concise actionable sentence)
- output: what artifact or result this task produces
- completion_criteria: how to verify this task is done

Return ONLY a JSON object with this exact structure, no other text:
{{
  "tasks": [
    {{
      "objective": "...",
      "output": "...",
      "completion_criteria": "..."
    }}
  ]
}}"""

def getPlannerLLM():
    return get_llm(model_name="qwen2.5:latest", temperature=0)

def parseLLMjson(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None

parseLlmJson = parseLLMjson

def validateTasks(data) -> List[dict]:
    if not isinstance(data, dict) or "tasks" not in data:
        return []
    rawList = data["tasks"]
    if not isinstance(rawList, list) or not rawList:
        return []
    validTasks = []
    for item in rawList:
        if not isinstance(item, dict):
            continue
        if "objective" not in item:
            continue
        validTasks.append({
            "objective": str(item["objective"]).strip(),
            "output": str(item.get("output", "")).strip(),
            "completion_criteria": str(item.get("completion_criteria", "")).strip(),
        })
    return validTasks

def callLLMforTasks(deliverable: Deliverable) -> List[dict]:
    llm = getPlannerLLM()
    promptText = TASK_DECOMPOSITION_PROMPT.format(
        name=deliverable.name,
        kind=deliverable.kind,
        goal=deliverable.goal,
        requirements=", ".join(deliverable.requirements) if deliverable.requirements else "none specified",
    )

    for attempt in range(2):
        try:
            response = llm.invoke(promptText)
            text = response.content if hasattr(response, "content") else str(response)
            parsed = parseLLMjson(text)
            tasks = validateTasks(parsed)
            if tasks:
                return tasks
        except Exception as e:
            print(f"[DeliverablePlanner] LLM task decomposition attempt {attempt + 1} failed: {e}")

    print(f"[DeliverablePlanner] WARNING: LLM task decomposition failed for '{deliverable.name}', using fallback.")
    return [{"objective": f"Implement {deliverable.name}", "output": deliverable.name, "completion_criteria": f"{deliverable.name} exists, matches spec, and passes validation."}]

class DeliverablePlanner:

    def plan(self, deliverable: Deliverable) -> DeliverablePlan:
        llmTasks = callLLMforTasks(deliverable)
        priority = deliverable.priority
        tasks = self.buildTaskChain(deliverable, llmTasks, priority)
        return DeliverablePlan(deliverable=deliverable, tasks=tasks)

    plan_deliverable = plan

    def buildTaskChain(self, deliverable: Deliverable, llmTasks: List[dict], priority: int) -> List[TaskNode]:
        tasks: List[TaskNode] = []
        previousId: Optional[str] = None

        for index, llmTask in enumerate(llmTasks, start=1):
            taskId = newId(f"{deliverable.id}-t{index}")
            isLast = index == len(llmTasks)
            task = TaskNode(
                id=taskId,
                deliverableId=deliverable.id,
                objective=llmTask["objective"],
                output=llmTask.get("output", deliverable.name if isLast else f"step {index} for {deliverable.name}"),
                completionCriteria=llmTask.get("completion_criteria", self.completionCriteria(llmTask["objective"], deliverable, isLast)),
                parentTask=previousId,
                dependencies=[previousId] if previousId else [],
                priority=priority
            )
            if previousId:
                attachChild(tasks, previousId, taskId)
            tasks.append(task)
            previousId = taskId

        return tasks

    @staticmethod
    def completionCriteria(step: str, deliverable: Deliverable, isLast: bool) -> str:
        if isLast:
            return f"{deliverable.name} exists, matches spec, and passes validation."
        return f"'{step}' complete for {deliverable.name}."

def attachChild(tasks: List[TaskNode], parentId: str, childId: str) -> None:
    for task in tasks:
        if task.id == parentId:
            task.childTasks.append(childId)
            return

deliverablePlanner = DeliverablePlanner
