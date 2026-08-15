from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Any, Dict
import uuid


class taskStatus(str, Enum):
    pending = "pending"
    ready = "ready"
    running = "running"
    done = "done"
    failed = "failed"


def newId(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:6]}"


@dataclass
class taskResult:
    taskId: str
    success: bool
    message: str = ""


@dataclass
class taskNode:
    id: str
    deliverableId: str
    objective: str
    output: str
    completionCriteria: str
    parentTask: Optional[str] = None
    childTasks: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    priority: int = 3
    status: str = "pending"
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class deliverable:
    id: str
    name: str
    kind: str
    goal: str
    scope: str = ""
    requiredFiles: List[str] = field(default_factory=list)
    explicitFilenames: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    priority: int = 3
    requirements: List[str] = field(default_factory=list)
    reasoning: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class deliverablePlan:
    deliverable: deliverable
    tasks: List[taskNode]


@dataclass
class planningEvent:
    stage: str
    message: str
    icon: str = "*"
    deliverableName: Optional[str] = None
    progress: Optional[float] = None


@dataclass
class dagPlan:
    taskNodes: List[taskNode]
    deliverables: List[deliverable]


TaskStatus = taskStatus
TaskResult = taskResult
TaskNode = taskNode
Deliverable = deliverable
DeliverablePlan = deliverablePlan
PlanningEvent = planningEvent
DAGPlan = dagPlan