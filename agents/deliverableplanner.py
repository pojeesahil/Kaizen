import json
import re
from typing import List, Optional, Any, Dict
from agents.models import deliverable, taskNode, deliverablePlan, newId
from core.config import get_llm

taskDecompositionPrompt = """You are an expert software engineer. Break down the following deliverable into a small, ordered list of concrete implementation tasks.

Deliverable: {name}
Kind: {kind}
Goal: {goal}
Requirements: {requirements}

For each task, provide:
- objective: what the developer should do (one sentence, actionable)
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


def getPlannerLlm() -> Any:
    return get_llm(model_name = "qwen2.5-coder:7b", temperature = 0)


def parseLlmJson(text: str) -> Any:
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


def validateTasks(data: Any) -> List[Dict[str, Any]]:
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


def callLlmForTasks(targetDeliverable: deliverable) -> List[Dict[str, Any]]:
    llmClient = getPlannerLlm()
    promptText = taskDecompositionPrompt.format(
        name = targetDeliverable.name,
        kind = targetDeliverable.kind,
        goal = targetDeliverable.goal,
        requirements = ", ".join(targetDeliverable.requirements) if targetDeliverable.requirements else "none specified",
    )

    for attempt in range(2):
        try:
            response = llmClient.invoke(promptText)
            responseText = response.content if hasattr(response, "content") else str(response)
            parsedJson = parseLlmJson(responseText)
            validatedTasks = validateTasks(parsedJson)
            if validatedTasks:
                return validatedTasks
        except Exception as err:
            print(f"[DeliverablePlanner] LLM task decomposition attempt {attempt + 1} failed: {err}")

    print(f"[DeliverablePlanner] WARNING: LLM task decomposition failed for '{targetDeliverable.name}', using fallback.")
    return [{
        "objective": f"Implement {targetDeliverable.name}",
        "output": targetDeliverable.name,
        "completion_criteria": f"{targetDeliverable.name} exists, matches spec, and passes validation."
    }]


def attachChild(taskList: List[taskNode], parentId: str, childId: str) -> None:
    for task in taskList:
        if task.id == parentId:
            task.childTasks.append(childId)
            return


class deliverablePlanner:
    def plan(self, targetDeliverable: deliverable) -> deliverablePlan:
        llmTasks = callLlmForTasks(targetDeliverable)
        priorityVal = targetDeliverable.priority
        taskList = self._buildTaskChain(targetDeliverable, llmTasks, priorityVal)
        return deliverablePlan(deliverable=targetDeliverable, tasks=taskList)

    plan_deliverable = plan

    def _buildTaskChain(self, targetDeliverable: deliverable, llmTasks: List[Dict[str, Any]], priorityVal: int) -> List[taskNode]:
        taskList: List[taskNode] = []
        previousId: Optional[str] = None

        for indexVal, llmTask in enumerate(llmTasks, start=1):
            taskId = newId(f"{targetDeliverable.id}-t{indexVal}")
            isLast = (indexVal == len(llmTasks))
            task = taskNode(
                id = taskId,
                deliverableId = targetDeliverable.id,
                objective = llmTask["objective"],
                output = llmTask.get("output", targetDeliverable.name if isLast else f"step {indexVal} for {targetDeliverable.name}"),
                completionCriteria = llmTask.get("completion_criteria", self._completionCriteria(llmTask["objective"], targetDeliverable, isLast)),
                parentTask = previousId,
                dependencies = [previousId] if previousId else [],
                priority = priorityVal,
            )
            if previousId:
                attachChild(taskList, previousId, taskId)
            taskList.append(task)
            previousId = taskId

        return taskList

    @staticmethod
    def _completionCriteria(stepText: str, targetDeliverable: deliverable, isLast: bool) -> str:
        if isLast:
            return f"{targetDeliverable.name} exists, matches spec, and passes validation."
        return f"'{stepText}' complete for {targetDeliverable.name}."


DeliverablePlanner = deliverablePlanner
