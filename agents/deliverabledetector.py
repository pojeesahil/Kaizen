import re
from typing import List, Dict, Any
from agents.models import deliverable, newId


def dedupe(itemsList: List[Any]) -> List[str]:
    seenKeys = set()
    resultList = []
    for item in itemsList:
        nameText = item.get("name", str(item)) if isinstance(item, dict) else str(item)
        keyText = nameText.strip().lower()
        if keyText and keyText not in seenKeys:
            seenKeys.add(keyText)
            resultList.append(nameText.strip())
    return resultList


class deliverableDetector:
    def detect(self, promptAgentOutput: Dict[str, Any]) -> List[deliverable]:
        rawDeliverables = list(promptAgentOutput.get("deliverables", []) or [])
        deliverablesList: List[deliverable] = []
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
            kind = str(item.get("kind", "generic")).strip()
            goal = str(item.get("goal", f"Create {name}")).strip()
            rawReqs = item.get("requirements", []) if isinstance(item.get("requirements"), list) else []
            rawDeps = item.get("dependencies", []) if isinstance(item.get("dependencies"), list) else []
            rawPriority = item.get("priority", 3)

            if not isinstance(rawPriority, int):
                try:
                    priorityVal = int(rawPriority)
                except (ValueError, TypeError):
                    priorityVal = 3
            else:
                priorityVal = rawPriority
            priorityVal = max(1, min(5, priorityVal))

            deliverablesList.append(
                deliverable(
                    id = deliverableId,
                    name = name,
                    kind = kind,
                    goal = goal,
                    requirements = [str(r) for r in rawReqs],
                    dependencies = [str(d) for d in rawDeps],
                    priority = priorityVal,
                )
            )

        return deliverablesList


DeliverableDetector = deliverableDetector
