import json
import re
from typing import Dict, List, Any
from core.config import get_llm, get_gemini_key, extract_text

ANALYSIS_PROMPT = """You are an expert software architect. Analyze the following user request and break it down into a minimal set of coarse-grained, modular deliverables (typically 2 to 4 deliverables total).

CRITICAL RULES:
- Group all related functions, state, and logic into cohesive, file-level deliverables (e.g. "Game Engine / Logic", "Interactive UI / Main Loop", "Documentation").
- NEVER create fragmented micro-deliverables (e.g. do NOT create separate deliverables for score, collision, movement, etc. — combine them into the core logic deliverable).
- Explicitly forbid generating speculative enterprise modules (like database migrations or separate auth microservices) unless explicitly requested.
- NEVER create deliverables for environment setup, runtime/package installation (e.g. "Install Node.js", "Install npm"), or creating directories. Focus strictly on source code deliverables.
- For games, terminal apps, or CLI tools, specify a concrete, runnable framework (e.g. curses, turtle, tkinter, pygame, or rich).

For each deliverable, provide:
- id: a short identifier (e.g. "coreLogic", "gameUi", "readme")
- name: human-readable name
- kind: a concise label (e.g. "core_logic", "ui", "readme")
- goal: one-sentence description of what this deliverable accomplishes
- requirements: list of specific things this deliverable needs or must support
- dependencies: list of ids of OTHER deliverables in this list that must be built before this one.
- priority: integer 1-5 where 1=highest (build first), 5=lowest (build last).

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

def validateDeliverables(data: Any) -> List[Dict]:
    if not isinstance(data, dict) or "deliverables" not in data:
        return []
    rawList = data["deliverables"]
    if not isinstance(rawList, list) or not rawList:
        return []

    validDeliverables = []
    for item in rawList:
        if not isinstance(item, dict):
            continue
        if not all(k in item for k in ("id", "name", "kind", "goal")):
            continue
        validDeliverables.append({
            "id": str(item["id"]).strip(),
            "name": str(item["name"]).strip(),
            "kind": str(item["kind"]).strip(),
            "goal": str(item["goal"]).strip(),
            "requirements": [str(r) for r in item.get("requirements", []) if r] if isinstance(item.get("requirements"), list) else [],
            "dependencies": [str(d) for d in item.get("dependencies", []) if d] if isinstance(item.get("dependencies"), list) else [],
            "priority": max(1, min(5, int(item.get("priority", 3)))) if isinstance(item.get("priority"), (int, float)) else 3,
        })
    return validDeliverables

def fallbackDeliverable(userPrompt: str) -> List[Dict]:
    return [{
        "id": "deliverable1",
        "name": userPrompt.strip()[:60],
        "kind": "generic",
        "goal": userPrompt.strip(),
        "requirements": [],
        "dependencies": [],
        "priority": 3,
    }]

def callLLMforDeliverables(userPrompt: str) -> List[Dict]:
    llm = getPlannerLLM()
    promptText = ANALYSIS_PROMPT + userPrompt.strip()

    for attempt in range(2):
        try:
            response = llm.invoke(promptText)
            content = response.content if hasattr(response, "content") else response
            parsed = parseLLMjson(content)
            deliverables = validateDeliverables(parsed)
            if deliverables:
                return deliverables
        except Exception as e:
            print(f"[PromptAgent] LLM call attempt {attempt + 1} failed: {e}")

    print("[PromptAgent] WARNING: LLM analysis failed, using fallback deliverable.")
    return fallbackDeliverable(userPrompt)

class PromptAgent:
    def process(self, userPrompt: str) -> Dict:
        deliverablesList = callLLMforDeliverables(userPrompt)
        names = [d["name"] for d in deliverablesList]
        intent = f"Deliver: {', '.join(names)}" if names else "Unclear request"
        projectType = deliverablesList[0]["kind"] if deliverablesList else "unclassified"
        count = len(deliverablesList)

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
            "deliverables": deliverablesList,
            "recommended_stack": {},
            "recommendedStack": {},
            "requirements": {"essential": [], "recommended": [], "optional": []},
            "missing_information": [],
            "missingInformation": [],
            "clarification_questions": [],
            "clarificationQuestions": [],
            "constraints": [],
            "success_criteria": [f"{d['name']} is implemented, reviewed, and passes tests" for d in deliverablesList],
            "successCriteria": [f"{d['name']} is implemented, reviewed, and passes tests" for d in deliverablesList],
            "enhanced_request": userPrompt.strip(),
            "enhancedRequest": userPrompt.strip(),
            "planner_notes": plannerNotes,
            "plannerNotes": plannerNotes,
        }

    run = process


@staticmethod
def summary(deliverablesList: List[Dict[str, Any]]) -> str:
    names = [d.get("name", str(d)).replace("_", " ") for d in deliverablesList]
    return f"Deliver: {', '.join(names)}" if names else "Unclear request"

if __name__ == "__main__":
    import json as _json
    agent = PromptAgent()
    example = "Create a README, Dockerfile, and a login page with authentication, offline only"
    print(_json.dumps(agent.process(example), indent = 2))
