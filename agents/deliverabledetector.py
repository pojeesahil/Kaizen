import re
from typing import List, Dict, Any
from agents.models import Deliverable, newId


def _dedupe(Items: List[Any]) -> List[str]:
    Seen = set()
    Result = []
    for Item in Items:
        Name = Item.get("name", str(Item)) if isinstance(Item, dict) else str(Item)
        Key = Name.strip().lower()
        if Key and Key not in Seen:
            Seen.add(Key)
            Result.append(Name.strip())
    return Result


class DeliverableDetector:

    def detect(self, PromptAgentOutput: Dict[str, Any]) -> List[Deliverable]:
        RawDeliverables = list(PromptAgentOutput.get("deliverables", []) or [])

        Deliverables: List[Deliverable] = []
        SeenIds = set()

        for Item in RawDeliverables:
            if not isinstance(Item, dict):
                continue

            RawId = str(Item.get("id", "")).strip()
            if not RawId:
                RawId = re.sub(r"\W+", "_", Item.get("name", "deliverable").lower()).strip("_")

            BaseId = RawId
            Counter = 1
            while RawId in SeenIds:
                RawId = f"{BaseId}_{Counter}"
                Counter += 1

            DeliverableId = newId(RawId)
            SeenIds.add(RawId)

            Name = str(Item.get("name", RawId)).strip()
            Kind = str(Item.get("kind", "generic")).strip()
            Goal = str(Item.get("goal", f"Create {Name}")).strip()
            Requirements = Item.get("requirements", []) if isinstance(Item.get("requirements"), list) else []
            Dependencies = Item.get("dependencies", []) if isinstance(Item.get("dependencies"), list) else []
            Priority = Item.get("priority", 3)
            if not isinstance(Priority, int):
                try:
                    Priority = int(Priority)
                except (ValueError, TypeError):
                    Priority = 3
            Priority = max(1, min(5, Priority))

            Deliverables.append(
                Deliverable(
                    id =DeliverableId,
                    name = Name,
                    kind = Kind,
                    goal = Goal,
                    requirements = [str(r) for r in Requirements],
                    dependencies = [str(d) for d in Dependencies],
                    priority = Priority,
                )
            )

        return Deliverables
