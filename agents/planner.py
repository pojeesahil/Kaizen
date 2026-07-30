import asyncio
import json

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama

from agents.dag import DAG
from agents.models import TaskNode
from agents.scheduler import Scheduler
from agents.prompt import PromptAgent
from rag.rag import getContext


class Planner:

    def __init__(self):
        self.llm = ChatOllama(
            model="qwen2.5-coder:7b",
            temperature=0,
            format="json"
        )
        self.prompt_agent = PromptAgent()
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

    def generate_plan(self, request: str, intent: str, context: str = "") -> list[dict]:

        prompt = f"""
You are the Planner Agent of KAIZEN.

Your ONLY job is to convert the user's request into a list of executable software development tasks.

Rules:

- Return ONLY valid JSON.
- Do NOT explain anything.
- Do NOT use markdown.
- Return ONLY a JSON array.
- Generate between 3 and 10 tasks whenever possible.
- Every task must represent ONE independently executable unit of work.
- Every task should produce ONE logical deliverable.
- Add dependencies only when necessary.

Always split the request if it contains:

- Multiple pages
- Multiple files
- Multiple APIs
- Multiple endpoints
- Multiple components
- Multiple modules
- Multiple services
- Multiple classes
- Multiple database tables
- Multiple screens

Examples

User:
Create three HTML pages.

Correct:

[
    {{
        "id":"page1",
        "name":"Create page1.html",
        "agent":"Coding",
        "priority":1,
        "dependencies":[],
        "tools":["filesystem"]
    }},
    {{
        "id":"page2",
        "name":"Create page2.html",
        "agent":"Coding",
        "priority":1,
        "dependencies":[],
        "tools":["filesystem"]
    }},
    {{
        "id":"page3",
        "name":"Create page3.html",
        "agent":"Coding",
        "priority":1,
        "dependencies":[],
        "tools":["filesystem"]
    }}
]

User:
Create login page, signup page and dashboard.

Correct:

[
    {{
        "id":"login",
        "name":"Create Login Page",
        "agent":"Coding",
        "priority":1,
        "dependencies":[],
        "tools":["filesystem"]
    }},
    {{
        "id":"signup",
        "name":"Create Signup Page",
        "agent":"Coding",
        "priority":1,
        "dependencies":[],
        "tools":["filesystem"]
    }},
    {{
        "id":"dashboard",
        "name":"Create Dashboard",
        "agent":"Coding",
        "priority":1,
        "dependencies":[],
        "tools":["filesystem"]
    }}
]

Every task MUST contain:

- id
- name
- agent
- priority
- dependencies
- tools

Priority:

1 = High
2 = Medium
3 = Low

Codebase Context:

{context if context else "No existing context available."}

User Request:

{request}

Intent:

{intent}
"""

        response = self.llm.invoke([
            SystemMessage(content="You are an expert software planning agent. Return ONLY valid JSON."), HumanMessage(content=prompt)])

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
                    id = item["id"],
                    name = item["name"],
                    agent = item["agent"],
                    priority = item["priority"],
                    dependencies = item.get("dependencies", []),
                    tools = item.get("tools", [])
                )
            )

        dag.build()
        dag.topological_sort()

        return dag

    async def run(self, request: str):

        self.state["goal"] = request

        print(f"\nUser Request : {request}")

        enhanced = self.prompt_agent.run(request)

        enhanced_request = enhanced["enhanced_request"]
        intent = enhanced["intent"]

        print(f"\nEnhanced Request : {enhanced_request}")
        print(f"Intent : {intent}")

        context = getContext(enhanced_request)

        plan = self.generate_plan(enhanced_request, intent, context)

        print("\nGenerated Tasks")

        for task in plan:
            print(f" - {task['name']}")

        dag = self.build_dag(plan)

        print("\nExecution Order")
        print(dag.topological_sort())

        scheduler = Scheduler(dag, enhanced_request)

        await scheduler.run()

        print("\nWorkflow Finished")


if __name__ == "__main__":

    planner = Planner()

    asyncio.run(
        planner.run(
            input("Enter your request: ")
        )
    )