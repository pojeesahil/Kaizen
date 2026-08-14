import json
import re
from typing import Dict, List, Any
from core.config import get_llm

ANALYSIS_PROMPT = """You are an expert software architect. Analyze the following user request and break it down into concrete deliverables that need to be built.

For each deliverable, provide:
- id: a short snake_case identifier (unique within this list)
- name: human-readable name
- kind: a free-form label describing what this deliverable is (e.g. "api_server", "react_frontend", "dockerfile", "readme", "database_migration", "auth_module")
- goal: one-sentence description of what this deliverable accomplishes
- requirements: list of specific things this deliverable needs or must support
- dependencies: list of ids of OTHER deliverables in this list that must be built before this one. Only include genuine semantic dependencies, not artificial ordering. Deliverables that are truly independent should have an empty list.
- priority: integer 1-5 where 1=highest (build first), 5=lowest (build last). A dependency must always have a lower or equal priority number than anything that depends on it.

Return ONLY a JSON object with this exact structure, no other text:
{
  "deliverables": [
    {
      "id": "...",
      "name": "...",
      "kind": "...",
      "goal": "...",
      "requirements": ["..."],
      "dependencies": ["..."],
      "priority": 1
    }
  ]
}

User request:
"""


def _get_planner_llm():
    return get_llm(model_name="qwen2.5:7b", temperature=0)


def _parse_llm_json(text: str) -> Any:

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


def validateDeliverables(data: Any) -> List[Dict]:

    if not isinstance(data, dict) or "deliverables" not in data:
        return []
    raw = data["deliverables"]
    if not isinstance(raw, list) or not raw:
        return []

    valid = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        if not all(k in item for k in ("id", "name", "kind", "goal")):
            continue
        valid.append({
            "id": str(item["id"]).strip(),
            "name": str(item["name"]).strip(),
            "kind": str(item["kind"]).strip(),
            "goal": str(item["goal"]).strip(),
            "requirements": [str(r) for r in item.get("requirements", []) if r] if isinstance(item.get("requirements"), list) else [],
            "dependencies": [str(d) for d in item.get("dependencies", []) if d] if isinstance(item.get("dependencies"), list) else [],
            "priority": max(1, min(5, int(item.get("priority", 3)))) if isinstance(item.get("priority"), (int, float)) else 3,
        })
    return valid


def _fallback_deliverable(userPrompt: str) -> List[Dict]:

    return [{
        "id": "deliverable_1",
        "name": userPrompt.strip()[:60],
        "kind": "generic",
        "goal": userPrompt.strip(),
        "requirements": [],
        "dependencies": [],
        "priority": 3,
    }]


def _call_llm_for_deliverables(userPrompt: str) -> List[Dict]:

    llm = _get_planner_llm()
    prompt_text = ANALYSIS_PROMPT + userPrompt.strip()

    for attempt in range(2):
        try:
            response = llm.invoke(prompt_text)
            text = response.content if hasattr(response, "content") else str(response)
            parsed = _parse_llm_json(text)
            deliverables = validateDeliverables(parsed)
            if deliverables:
                return deliverables
        except Exception as e:
            print(f"[PromptAgent] LLM call attempt {attempt + 1} failed: {e}")

    print("[PromptAgent] WARNING: LLM analysis failed, using fallback deliverable.")
    return _fallback_deliverable(userPrompt)


class PromptAgent:
    def process(self, userPrompt: str) -> Dict:
        deliverables = _call_llm_for_deliverables(userPrompt)

        names = [d["name"] for d in deliverables]
        intent = f"Deliver: {', '.join(names)}" if names else "Unclear request"

        projectType = deliverables[0]["kind"] if deliverables else "unclassified"

        count = len(deliverables)
        if count >= 5:
            complexity = "enterprise"
        elif count >= 3:
            complexity = "large"
        elif count >= 2:
            complexity = "medium"
        else:
            complexity = "small"

        plannerNotes = f"{count} deliverable(s) identified by LLM analysis; planning can proceed."

        return {
            "intent": intent,
            "project_type": projectType,
            "projectType": projectType,
            "complexity": complexity,
            "architecture": [],
            "domain": [projectType],
            "deliverables": deliverables,
            "recommended_stack": {},
            "recommendedStack": {},
            "requirements": {"essential": [], "recommended": [], "optional": []},
            "missing_information": [],
            "missingInformation": [],
            "clarification_questions": [],
            "clarificationQuestions": [],
            "constraints": [],
            "success_criteria": [f"{d['name']} is implemented, reviewed, and passes tests" for d in deliverables],
            "successCriteria": [f"{d['name']} is implemented, reviewed, and passes tests" for d in deliverables],
            "enhanced_request": userPrompt.strip(),
            "enhancedRequest": userPrompt.strip(),
            "planner_notes": plannerNotes,
            "plannerNotes": plannerNotes,
        }

    run = process

    @staticmethod
    def summary(deliverables: List[Dict]) -> str:
        names = [d.get("name", str(d)).replace("_", " ") for d in deliverables]
        return f"Deliver: {', '.join(names)}" if names else "Unclear request"


if __name__ == "__main__":
    import json as _json
    agent = PromptAgent()
    example = "Create a README, Dockerfile, and a login page with authentication, offline only"
    print(_json.dumps(agent.process(example), indent = 2))
