from typing import List, Dict, Set
from agents.models import deliverable


class dependencyResolver:
    def resolve(self, deliverablesList: List[deliverable]) -> List[deliverable]:
        idSet = {d.id for d in deliverablesList}

        LLMidToActualMap: Dict[str, str] = {}
        for d in deliverablesList:
            parts = d.id.rsplit("-", 1)
            if len(parts) == 2:
                LLMidToActualMap[parts[0]] = d.id

        def isDoc(item: deliverable) -> bool:
            return any(
                k in item.kind.lower() or k in item.name.lower()
                for k in ("readme", "doc", "documentation")
            )

        codeDeliverableIds = [d.id for d in deliverablesList if not isDoc(d)]

        for d in deliverablesList:
            remappedDeps = [
                LLMidToActualMap[depId]
                for depId in d.dependencies
                if depId in LLMidToActualMap
            ]

            if isDoc(d) and codeDeliverableIds:
                remappedDeps.extend([cid for cid in codeDeliverableIds if cid != d.id])

            d.dependencies = [
                dep for dep in self.dedupe(remappedDeps)
                if dep != d.id and dep in idSet
            ]

        self.breakCycles(deliverablesList)
        self.alignPriorities(deliverablesList)
        return deliverablesList

    def breakCycles(self, deliverablesList: List[deliverable]) -> None:
        graphMap: Dict[str, List[str]] = {d.id: list(d.dependencies) for d in deliverablesList}
        whiteState, greyState, blackState = 0, 1, 2
        colorMap: Dict[str, int] = {d.id: whiteState for d in deliverablesList}
        backEdges: List[tuple] = []

        def DFStraversal(nodeId: str) -> None:
            colorMap[nodeId] = greyState
            for neighborId in graphMap.get(nodeId, []):
                if neighborId not in colorMap:
                    continue
                if colorMap[neighborId] == greyState:
                    backEdges.append((nodeId, neighborId))
                elif colorMap[neighborId] == whiteState:
                    DFStraversal(neighborId)
            colorMap[nodeId] = blackState

        for d in deliverablesList:
            if colorMap[d.id] == whiteState:
                DFStraversal(d.id)

        if backEdges:
            byId = {d.id: d for d in deliverablesList}
            for sourceId, targetId in backEdges:
                if sourceId in byId and targetId in byId[sourceId].dependencies:
                    byId[sourceId].dependencies.remove(targetId)
                    print(f"[DependencyResolver] Broke cycle: removed {sourceId} -> {targetId}")

    def alignPriorities(self, deliverablesList: List[deliverable]) -> None:
        byId = {d.id: d for d in deliverablesList}
        hasChanged = True
        while hasChanged:
            hasChanged = False
            for d in deliverablesList:
                for depId in d.dependencies:
                    depItem = byId.get(depId)
                    if depItem and depItem.priority > d.priority:
                        depItem.priority = d.priority
                        hasChanged = True

    @staticmethod
    def dedupe(idsList: List[str]) -> List[str]:
        return list(dict.fromkeys(idsList))


DependencyResolver = dependencyResolver

