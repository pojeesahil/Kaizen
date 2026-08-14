import json
import re
from typing import List, Optional
from agents.models import Deliverable, TaskNode, DeliverablePlan, newId
from core.config import get_llm

TASK_DECOMPOSITION_PROMPT = """You are an expert software engineer. Break down the following deliverable into a small, ordered list of concrete implementation tasks.

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


def _get_planner_llm():
    return get_llm(model_name="qwen2.5:7b", temperature = 0)


def _parse_llm_json(text: str):
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


def validateTasks(data) -> List[dict]:
    if not isinstance(data, dict) or "tasks" not in data:
        return []
    raw = data["tasks"]
    if not isinstance(raw, list) or not raw:
        return []
    valid = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if "objective" not in item:
            continue
        valid.append({
            "objective": str(item["objective"]).strip(),
            "output": str(item.get("output", "")).strip(),
            "completion_criteria": str(item.get("completion_criteria", "")).strip(),
        })
    return valid


def _call_llm_for_tasks(deliverable: Deliverable) -> List[dict]:

    llm = _get_planner_llm()
    prompt_text = TASK_DECOMPOSITION_PROMPT.format(
        name = deliverable.name,
        kind = deliverable.kind,
        goal = deliverable.goal,
        requirements=", ".join(deliverable.requirements) if deliverable.requirements else "none specified",
    )

    for attempt in range(2):
        try:
            response = llm.invoke(prompt_text)
            text = response.content if hasattr(response, "content") else str(response)
            parsed = _parse_llm_json(text)
            tasks = validateTasks(parsed)
            if tasks:
                return tasks
        except Exception as e:
            print(f"[DeliverablePlanner] LLM task decomposition attempt {attempt + 1} failed: {e}")

    print(f"[DeliverablePlanner] WARNING: LLM task decomposition failed for '{deliverable.name}', using fallback.")
    return [{"objective": f"Implement {deliverable.name}", "output": deliverable.name, "completion_criteria": f"{deliverable.name} exists, matches spec, and passes validation."}]


class DeliverablePlanner:

    def plan(self, Deliverable: Deliverable) -> DeliverablePlan:
        LlmTasks = _call_llm_for_tasks(Deliverable)
        Priority = Deliverable.priority
        Tasks = self._buildTaskChain(Deliverable, LlmTasks, Priority)
        return DeliverablePlan(deliverable=Deliverable, tasks=Tasks)

    plan_deliverable = plan

    def _buildTaskChain(self, Deliverable: Deliverable, LlmTasks: List[dict], Priority: int) -> List[TaskNode]:

        Tasks: List[TaskNode] = []
        PreviousId: Optional[str] = None

        for Index, LlmTask in enumerate(LlmTasks, start=1):
            TaskId = newId(f"{Deliverable.id}-t{Index}")
            IsLast = Index == len(LlmTasks)
            Task = TaskNode(
                id = TaskId,
                deliverableId = Deliverable.id,
                objective = LlmTask["objective"],
                output = LlmTask.get("output", Deliverable.name if IsLast else f"step {Index} for {Deliverable.name}"),
                completionCriteria = LlmTask.get("completion_criteria", self._completionCriteria(LlmTask["objective"], Deliverable, IsLast)),
                parentTask = PreviousId,
                dependencies = [PreviousId] if PreviousId else [],
                priority = Priority
            )
            if PreviousId:
                _attachChild(Tasks, PreviousId, TaskId)
            Tasks.append(Task)
            PreviousId = TaskId

        return Tasks

    @staticmethod
    def _completionCriteria(Step: str, Deliverable: Deliverable, IsLast: bool) -> str:
        if IsLast:
            return f"{Deliverable.name} exists, matches spec, and passes validation."
        return f"'{Step}' complete for {Deliverable.name}."


def _attachChild(Tasks: List[TaskNode], ParentId: str, ChildId: str) -> None:
    for Task in Tasks:
        if Task.id == ParentId:
            Task.childTasks.append(ChildId)
            return
