from dataclasses import dataclass, field
from typing import List


@dataclass
class TaskNode:

    id: str
    name: str
    agent: str
    priority: int
    dependencies: List[str] = field(default_factory = list)
    tools: List[str] = field(default_factory = list)
    status: str = "pending"


@dataclass
class TaskResult:

    task_id: str
    success: bool
    message: str = ""