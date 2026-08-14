from typing import List, Dict, Set
from agents.models import Deliverable


class DependencyResolver:

    def resolve(self, Deliverables: List[Deliverable]) -> List[Deliverable]:
        IdSet = {d.id for d in Deliverables}

        LlmIdToActual: Dict[str, str] = {}
        for d in Deliverables:

            Parts = d.id.rsplit("-", 1)
            if len(Parts) == 2:
                LlmIdToActual[Parts[0]] = d.id
            LlmIdToActual[d.id] = d.id

        for d in Deliverables:

            Remapped = []
            for DepId in d.dependencies:
                ActualId = LlmIdToActual.get(DepId)
                if ActualId:
                    Remapped.append(ActualId)

            d.dependencies = Remapped

            d.dependencies = self._dedupe(d.dependencies)

            d.dependencies = [dep for dep in d.dependencies if dep != d.id]

            d.dependencies = [dep for dep in d.dependencies if dep in IdSet]

        self._breakCycles(Deliverables)

        self._alignPriorities(Deliverables)

        return Deliverables

    def _breakCycles(self, Deliverables: List[Deliverable]) -> None:

        Graph: Dict[str, List[str]] = {d.id: list(d.dependencies) for d in Deliverables}
        White, Grey, Black = 0, 1, 2
        Color: Dict[str, int] = {d.id: White for d in Deliverables}
        BackEdges: List[tuple] = []

        def Dfs(Node: str) -> None:
            Color[Node] = Grey
            for Neighbor in Graph.get(Node, []):
                if Neighbor not in Color:
                    continue
                if Color[Neighbor] == Grey:
                    BackEdges.append((Node, Neighbor))
                elif Color[Neighbor] == White:
                    Dfs(Neighbor)
            Color[Node] = Black

        for d in Deliverables:
            if Color[d.id] == White:
                Dfs(d.id)

        if BackEdges:
            ById = {d.id: d for d in Deliverables}
            for Source, Target in BackEdges:
                if Source in ById and Target in ById[Source].dependencies:
                    ById[Source].dependencies.remove(Target)
                    print(f"[DependencyResolver] Broke cycle: removed {Source} -> {Target}")

    def _alignPriorities(self, Deliverables: List[Deliverable]) -> None:

        ById = {d.id: d for d in Deliverables}
        Changed = True
        while Changed:
            Changed = False
            for d in Deliverables:
                for DepId in d.dependencies:
                    Dep = ById.get(DepId)
                    if Dep and Dep.priority > d.priority:
                        Dep.priority = d.priority
                        Changed = True

    @staticmethod
    def _dedupe(Ids: List[str]) -> List[str]:
        Seen: Set[str] = set()
        Result = []
        for Item in Ids:
            if Item not in Seen:
                Seen.add(Item)
                Result.append(Item)
        return Result
