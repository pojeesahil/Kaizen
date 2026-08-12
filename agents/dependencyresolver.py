from typing import List, Dict
from agents.models import Deliverable, newId

KindDependencies: Dict[str, List[str]] = {
    "frontend": ["backend"],
    "ui_page": ["backend"],
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

        Deliverables = self._addIntegrationDeliverables(Deliverables)
        return Deliverables

    def _addIntegrationDeliverables(self, Deliverables: List[Deliverable]) -> List[Deliverable]:
        CoreItems = []
        for Item in Deliverables:
            if Item.kind not in ("documentation", "tests", "integration", "ci_cd_workflow"):
                CoreItems.append(Item)

        if len(CoreItems) >= 2:
            for Index in range(len(CoreItems) - 1):
                ItemA = CoreItems[Index]
                ItemB = CoreItems[Index + 1]

                IntegrationName = f"Integration ({ItemA.name} and {ItemB.name})"
                ScopeMsg = (
                    f"Wire and connect {ItemA.name} and {ItemB.name} into a single unified application. "
                    f"CRITICAL: Use editFile to integrate them end-to-end — e.g. for backend files, import modules, initialize DB/service connections, and call functions; for backend and frontend, serve HTML/static routes and wire API endpoints."
                )
                IntegrationItem = Deliverable(
                    id=newId(f"integration_{Index}"),
                    name=IntegrationName,
                    kind="integration",
                    goal=f"Connect and integrate {ItemA.name} with {ItemB.name}",
                    scope=ScopeMsg,
                    dependencies=self._dedupe([ItemA.id, ItemB.id])
                )
                Deliverables.append(IntegrationItem)

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

