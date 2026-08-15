from typing import List, Dict, Set
from agents.models import deliverable


class dependencyResolver:
    def resolve(self, deliverablesList: List[deliverable]) -> List[deliverable]:
        idSet = {d.id for d in deliverablesList}

        llmIdToActualMap: Dict[str, str] = {}
        for d in deliverablesList:
            parts = d.id.rsplit("-", 1)
            if len(parts) == 2:
                llmIdToActualMap[parts[0]] = d.id
            llmIdToActualMap[d.id] = d.id

        for d in deliverablesList:
            remappedDeps = []
            for depId in d.dependencies:
                actualId = llmIdToActualMap.get(depId)
                if actualId:
                    remappedDeps.append(actualId)

            d.dependencies = self.dedupe(remappedDeps)
            d.dependencies = [dep for dep in d.dependencies if dep != d.id]
            d.dependencies = [dep for dep in d.dependencies if dep in idSet]

        self.breakCycles(deliverablesList)
        self.alignPriorities(deliverablesList)
        return deliverablesList

    def breakCycles(self, deliverablesList: List[deliverable]) -> None:
        graphMap: Dict[str, List[str]] = {d.id: list(d.dependencies) for d in deliverablesList}
        whiteState, greyState, blackState = 0, 1, 2
        colorMap: Dict[str, int] = {d.id: whiteState for d in deliverablesList}
        backEdges: List[tuple] = []

        def dfsTraversal(nodeId: str) -> None:
            colorMap[nodeId] = greyState
            for neighborId in graphMap.get(nodeId, []):
                if neighborId not in colorMap:
                    continue
                if colorMap[neighborId] == greyState:
                    backEdges.append((nodeId, neighborId))
                elif colorMap[neighborId] == whiteState:
                    dfsTraversal(neighborId)
            colorMap[nodeId] = blackState

        for d in deliverablesList:
            if colorMap[d.id] == whiteState:
                dfsTraversal(d.id)

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
        seenSet: Set[str] = set()
        resultList = []
        for item in idsList:
            if item not in seenSet:
                seenSet.add(item)
                resultList.append(item)
        return resultList


DependencyResolver = dependencyResolver
