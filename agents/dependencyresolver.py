from typing import List, Dict
from agents.models import Deliverable

KindDependencies: Dict[str, List[str]] = {
    "frontend": [],
    "ui_page": [],
    "tests": ["backend", "frontend", "ui_page"],
    "documentation": ["backend", "frontend", "ui_page", "database_schema", "deployment_script", "ci_cd_workflow", "tests", "config"],
    "ci_cd_workflow": ["tests"],
    "deployment_script": [],
    "config": [],
    "backend": ["database_schema"]
}


class DependencyResolver:

    def resolve(self, Deliverables: List[Deliverable]) -> List[Deliverable]:
        ByKind: Dict[str, List[Deliverable]] = {}
        for deliverable in Deliverables:
            ByKind.setdefault(deliverable.kind, []).append(deliverable)

        for deliverable in Deliverables:
            NeededKinds = KindDependencies.get(deliverable.kind, [])
            for Kind in NeededKinds:
                for Candidate in ByKind.get(Kind, []):
                    if Candidate.id != deliverable.id:
                        deliverable.dependencies.append(Candidate.id)
            deliverable.dependencies = self._dedupe(deliverable.dependencies)

        return Deliverables

    @staticmethod
    def _dedupe(Ids: List[str]) -> List[str]:
        Seen = set()
        Result = []
        for Item in Ids:
            if Item not in Seen:
                Seen.add(Item)
                Result.append(Item)
        return Result
