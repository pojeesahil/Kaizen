import re
from typing import List, Dict, Any
from agents.models import Deliverable, newId

ExtensionKind = {
    ".html": "ui_page",
    ".css": "stylesheet",
    ".js": "frontend_script",
    ".ts": "frontend_script",
    ".py": "backend_module",
    ".md": "documentation",
    ".yml": "ci_cd_workflow",
    ".yaml": "ci_cd_workflow",
    ".json": "config",
    ".env": "config",
    ".sql": "database_schema",
    ".sh": "deployment_script",
}

KeywordKind = {
    "backend": "backend",
    "api": "backend",
    "frontend": "frontend",
    "ui": "frontend",
    "database": "database_schema",
    "schema": "database_schema",
    "test": "tests",
    "readme": "documentation",
    "docker": "deployment_script",
    "ci": "ci_cd_workflow",
    "cd": "ci_cd_workflow",
    "pipeline": "ci_cd_workflow",
    "deploy": "deployment_script",
    "config": "config",
}


def _classify(Name: str) -> str:

    Lower = Name.strip().lower()
    for Ext, Kind in ExtensionKind.items():
        if Lower.endswith(Ext):
            return Kind
    for Keyword, Kind in KeywordKind.items():
        if Keyword in Lower:
            return Kind
    return "generic"


def _looksLikeFilename(Name: str) -> bool:

    return bool(re.match(r"^[\w\-]+\.[A-Za-z0-9]+$", Name.strip()))


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
        RawNames = list(PromptAgentOutput.get("deliverables", []) or [])

        SpecText = PromptAgentOutput.get("engineering_specification", "") or ""
        RawNames += re.findall(r"\b[\w\-]+\.[A-Za-z0-9]{1,5}\b", SpecText)

        RawNames = _dedupe(RawNames)

        Deliverables: List[Deliverable] = []
        for Name in RawNames:
            Kind = _classify(Name)
            Explicit = [Name] if _looksLikeFilename(Name) else []
            Deliverables.append(
                Deliverable(
                    id=newId(re.sub(r"\W+", "_", Name.lower()).strip("_") or "deliverable"),
                    name=Name,
                    kind=Kind,
                    goal=f"Create {Name}",
                    scope=self._inferScope(Kind, PromptAgentOutput),
                    requiredFiles=Explicit,
                    explicitFilenames=Explicit,
                )
            )
        return Deliverables

    @staticmethod
    def _inferScope(Kind: str, PromptAgentOutput: Dict[str, Any]) -> str:

        Architecture = PromptAgentOutput.get("architecture", "the project")
        ScopeByKind = {
            "ui_page": f"A single page within {Architecture}.",
            "backend": f"Server-side logic and API surface for {Architecture}.",
            "frontend": f"Client-side UI layer for {Architecture}.",
            "database_schema": f"Persistent data model for {Architecture}.",
            "documentation": f"Project documentation describing {Architecture}.",
            "deployment_script": f"Build/runtime packaging for {Architecture}.",
            "ci_cd_workflow": f"Automated pipeline for {Architecture}.",
            "tests": f"Automated test coverage for {Architecture}.",
            "config": f"Configuration values used by {Architecture}.",
        }
        return ScopeByKind.get(Kind, f"Independent artifact within {Architecture}.")
