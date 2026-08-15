import re
from typing import List, Dict, Any
from agents.models import Deliverable, newId

def dedupe(items: List[Any]) -> List[str]:
    seen = set()
    result = []
    for item in items:
        name = item.get("name", str(item)) if isinstance(item, dict) else str(item)
        key = name.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(name.strip())
    return result

class DeliverableDetector:

    def detect(self, promptAgentOutput: Dict[str, Any]) -> List[Deliverable]:
        rawDeliverables = list(promptAgentOutput.get("deliverables", []) or [])
        deliverables: List[Deliverable] = []
        seenIds = set()

        for item in rawDeliverables:
            if not isinstance(item, dict):
                continue

            rawId = str(item.get("id", "")).strip()
            if not rawId:
                rawId = re.sub(r"\W+", "_", item.get("name", "deliverable").lower()).strip("_")

            baseId = rawId
            counter = 1
            while rawId in seenIds:
                rawId = f"{baseId}_{counter}"
                counter += 1

            deliverableId = newId(rawId)
            seenIds.add(rawId)

            name = str(item.get("name", rawId)).strip()
            kind = str(item.get("kind", "generic")).strip().lower()
            goal = str(item.get("goal", f"Create {name}")).strip()
            requirements = item.get("requirements", []) if isinstance(item.get("requirements"), list) else []
            dependencies = item.get("dependencies", []) if isinstance(item.get("dependencies"), list) else []

            priority = item.get("priority", 3)
            if not isinstance(priority, int):
                try:
                    priority = int(priority)
                except (ValueError, TypeError):
                    priority = 3

            # Enforce core logic first, documentation last
            if any(k in kind or k in name.lower() for k in ("readme", "doc", "documentation")):
                priority = 5
            elif any(k in kind or k in name.lower() for k in ("core", "logic", "game", "server", "app")):
                priority = min(priority, 1)

            priority = max(1, min(5, priority))

            deliverables.append(
                Deliverable(
                    id=deliverableId,
                    name=name,
                    kind=kind,
                    goal=goal,
                    requirements=[str(r) for r in requirements],
                    dependencies=[str(d) for d in dependencies],
                    priority=priority,
                )
            )

        return deliverables
