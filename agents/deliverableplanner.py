import json
import re
from typing import List, Optional, Any, Dict
from agents.models import Deliverable, TaskNode, DeliverablePlan, newId, deliverable, taskNode, deliverablePlan
from core.config import get_llm, get_gemini_key, extract_text

TASK_DECOMPOSITION_PROMPT = """You are an expert software engineer. Break down the following deliverable into a cohesive list of implementation tasks (typically 2 to 5 tasks per deliverable).

RULES:
- Single Responsibility per Task: Decompose deliverables into distinct architectural layers. Never combine data models, business logic services, and user interaction handlers into a single task.
- Separation of Data vs Operations: If a feature requires data models and operations, split them into discrete tasks: (1) data models, schemas, and type definitions, (2) business logic, algorithms, and state mutations, (3) routing, controllers, or UI views.
- Asset Batching: When assets, SVGs, or media files are required, NEVER lump all assets into a single generic task. Group them into explicit batches of 2 to 4 assets per task (e.g. 'Create Player & Laser SVGs: assets/player_ship.svg and assets/laser.svg', 'Create Alien Enemy SVGs: assets/alien_scout.svg and assets/alien_boss.svg', 'Create UI & VFX SVGs: assets/shield.svg, assets/explosion.svg, assets/powerup.svg').
- Bounded Scope: Each task must be small enough to be fully implemented in 1-2 files (or 2-4 asset files) without placeholders, stubs, or unwritten methods.
- Do NOT generate micro-tasks for tiny elements (like single buttons or styling tweaks). Keep tasks scoped to cohesive modules or complete files.
- Focus strictly on concrete source files. Do NOT generate tasks for environment setup, runtime installs (Node, Python), or package manager commands. For web projects, include root configuration files (package.json, tsconfig.json, index.html) when necessary.

Deliverable: {name}
Kind: {kind}
Goal: {goal}
Requirements: {requirements}

For each task, provide:
- objective: what the developer should do (one concise actionable sentence specifying target files/pages)
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
    return get_llm(api_key=get_gemini_key("1"), temperature=0)

def parseLLMjson(text: Any) -> Any:
    text = extract_text(text).strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
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

INVALID_TASK_PATTERNS = (
    "install node", "install npm", "install python", "install express", "install dependency",
    "create directory", "create folder", "create a new directory",
    "start the server", "launch server", "run the server", "run server"
)

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
        obj = str(item.get("objective", "")).strip()
        if not obj:
            continue
        objLower = obj.lower()
        if any(pat in objLower for pat in INVALID_TASK_PATTERNS):
            continue
        validTasks.append({
            "objective": obj,
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
            content = response.content if hasattr(response, "content") else response
            parsed = parseLLMjson(content)
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

    def extractTargetFiles(self, text: str) -> List[str]:
        cleaned = text.replace("`", "").replace("'", "").replace('"', "")
        found = re.findall(
            r"[\w/\\]+\.(?:py|js|ts|jsx|tsx|html|css|json|yaml|yml|txt|md)",
            cleaned,
            re.IGNORECASE
        )
        normalized = []
        for item in found:
            normPath = item.replace("\\", "/").lower()
            if normPath not in normalized:
                normalized.append(normPath)
        return normalized

    def buildTaskChain(self, deliverable: Deliverable, llmTasks: List[dict], priority: int) -> List[TaskNode]:
        tasks: List[TaskNode] = []
        fileToLastTaskId: Dict[str, str] = {}
        firstTaskId: Optional[str] = None

        for index, llmTask in enumerate(llmTasks, start=1):
            taskId = newId(f"{deliverable.id}-t{index}")
            isLast = index == len(llmTasks)
            objectiveText = llmTask.get("objective", "")
            targetFiles = self.extractTargetFiles(objectiveText)

            taskDependencies: List[str] = []

            if index == 1:
                firstTaskId = taskId
            else:
                conflictingTaskIds = []
                for fpath in targetFiles:
                    if fpath in fileToLastTaskId:
                        lastId = fileToLastTaskId[fpath]
                        if lastId not in conflictingTaskIds:
                            conflictingTaskIds.append(lastId)

                if conflictingTaskIds:
                    taskDependencies = conflictingTaskIds
                elif firstTaskId:
                    taskDependencies = [firstTaskId]

            for fpath in targetFiles:
                fileToLastTaskId[fpath] = taskId

            parentTask = taskDependencies[0] if taskDependencies else None

            task = TaskNode(
                id = taskId,
                deliverableId = deliverable.id,
                objective = objectiveText,
                output = llmTask.get("output", deliverable.name if isLast else f"step {index} for {deliverable.name}"),
                completionCriteria = llmTask.get("completion_criteria", self.completionCriteria(objectiveText, deliverable, isLast)),
                parentTask = parentTask,
                dependencies = taskDependencies,
                priority = priority
            )

            for depId in taskDependencies:
                attachChild(tasks, depId, taskId)

            tasks.append(task)

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
