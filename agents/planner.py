import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from agents.dag import DAG
from agents.models import TaskNode
from agents.scheduler import Scheduler


class Planner:

    def __init__(self):
        self.llm = ChatOllama(model = "qwen2.5-coder:7b", temperature = 0, format = "json")
        self.state = {"goal": "", "completed": [], "failed": []}

    def detect_intent(self, request: str) -> str:
        request = request.lower()

        if "bug" in request:
            return "bug"

        if any(word in request for word in [
            "build",
            "create",
            "develop",
            "implement",
            "feature"
        ]):
            return "feature"

        if "deploy" in request:
            return "deployment"

        if "documentation" in request or "readme" in request:
            return "documentation"

        if request.startswith("test") or request.startswith("run test"):
            return "testing"

        return "general"

    def generate_plan(self, request: str, intent: str) -> list[dict]:
        prompt = f"""
        You are the Planner Agent of an AI coding assistant. Break the user's request into 3-10 small executable tasks.

        Rules:
        - Return ONLY valid JSON.
        - Do NOT explain anything.
        - Do NOT use markdown.
        - Do NOT wrap the output inside ```json.
        - The output MUST be a JSON array.
        - Even if there is only one task, return a JSON array.
        - Every task must be atomic.
        - Add dependencies where required.

        Each task MUST contain:

        id
        name
        agent
        priority
        dependencies
        tools

        Priority:
        1 = High
        2 = Medium
        3 = Low

        Example:

        [
        {{
            "id":"backend",
            "name":"Build Backend",
            "agent":"Coding",
            "priority":1,
            "dependencies":[],
            "tools":["filesystem","terminal"]
        }},
        {{
            "id":"frontend",
            "name":"Build Frontend",
            "agent":"Coding",
            "priority":1,
            "dependencies":[],
            "tools":["filesystem"]
        }},
        {{
            "id":"testing",
            "name":"Run Tests",
            "agent":"Testing",
            "priority":2,
            "dependencies":["backend","frontend"],
            "tools":["terminal"]
        }}
        ]

        User Request:
        {request}

        Intent:
        {intent}
        """

        response = self.llm.invoke([
            SystemMessage(content = "You are an expert software planning agent that ONLY outputs JSON."),
            HumanMessage(content = prompt)
        ])

        content = response.content.strip()

        print(content)

        try:
            plan = json.loads(content)
        except json.JSONDecodeError as e:
            raise ValueError(f"LLM did not return valid JSON.\n\n{content}") from e

        if isinstance(plan, dict):
            plan = [plan]

        return plan

    def build_dag(self, plan: list[dict]) -> DAG:
        dag = DAG()

        for item in plan:
            dag.add_task(
                TaskNode(
                    id=item["id"],
                    name=item["name"],
                    agent=item["agent"],
                    priority=item["priority"],
                    dependencies=item.get("dependencies", []),
                    tools=item.get("tools", [])
                )
            )

        dag.build()
        dag.topological_sort()
        return dag

    async def run(self, request: str):
        self.state["goal"] = request

        print(f"\nUser Request : {request}")

        intent = self.detect_intent(request)
        print(f"Intent : {intent}")

        plan = self.generate_plan(request, intent)

        print("\nGenerated Tasks")
        for task in plan:
            print(f" - {task['name']}")

        dag = self.build_dag(plan)

        print("\nExecution Order")
        print(dag.topological_sort())

        scheduler = Scheduler(dag, request)
        await scheduler.run()

        print("\nWorkflow Finished")


if __name__ == "__main__":
    planner = Planner()
    asyncio.run(
        planner.run(
            "Build a full-stack authentication system with documentation and tests."
        )
    )