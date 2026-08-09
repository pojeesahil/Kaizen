from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional
import uuid


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def newId(Prefix: str) -> str:

    return f"{Prefix}-{uuid.uuid4().hex[:6]}"


@dataclass
class TaskNode:

    id: str
    deliverableId: str
    objective: str
    output: str
    completionCriteria: str
    parentTask: Optional[str] = None
    childTasks: List[str] = field(default_factory = list)
    dependencies: List[str] = field(default_factory = list)
    priority: int = 3
    status: TaskStatus = TaskStatus.PENDING
    metadata: dict = field(default_factory = dict)


@dataclass
class Deliverable:

    id: str
    name: str
    kind: str
    goal: str
    scope: str
    requiredFiles: List[str] = field(default_factory = list)
    explicitFilenames: List[str] = field(default_factory = list)
    dependencies: List[str] = field(default_factory = list)
    metadata: dict = field(default_factory = dict)


@dataclass
class DeliverablePlan:

    deliverable: Deliverable
    tasks: List[TaskNode]


@dataclass
class PlanningEvent:

    stage: str
    message: str
    icon: str = "*"
    deliverableName: Optional[str] = None
    progress: Optional[float] = None


@dataclass
class DAGPlan:

    taskNodes: List[TaskNode]
    deliverables: List[Deliverable]