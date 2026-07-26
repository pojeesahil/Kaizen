import json
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama


class PromptAgent:

    def __init__(self):
        self.llm = ChatOllama(model="qwen2.5-coder:7b", temperature=0, format="json")

    def detect_intent(self, request: str) -> str:
        request = request.lower()

        if any(word in request for word in ["fix", "bug", "error"]):
            return "bug"

        if any(word in request for word in ["deploy", "docker", "kubernetes"]):
            return "deployment"

        if any(word in request for word in ["documentation", "readme"]):
            return "documentation"

        if any(word in request for word in ["test", "testing"]):
            return "testing"

        if any(word in request for word in ["build", "create", "develop", "implement", "feature"]):
            return "feature"

        return "general"

    def ask_choice(self, title: str, options: list[str]) -> str:
        print(f"\n{title}")

        for i, option in enumerate(options, start=1):
            print(f"{i}. {option}")

        while True:
            try:
                choice = int(input("\nEnter choice: "))
                if 1 <= choice <= len(options):
                    return options[choice - 1]
            except ValueError:
                pass

            print("Invalid choice. Try again.")

    def collect_preferences(self, request: str) -> dict:
        request = request.lower()
        preferences = {}

        if any(word in request for word in ["web", "website", "dashboard", "frontend", "backend", "api", "chatbot", "authentication"]):
            preferences["backend"] = self.ask_choice(
                "Choose Backend Framework",
                ["FastAPI", "Flask", "Django", "No Preference"]
            )

        if any(word in request for word in ["database", "backend", "authentication"]):
            preferences["database"] = self.ask_choice(
                "Choose Database",
                ["PostgreSQL", "MongoDB", "MySQL", "SQLite", "No Preference"]
            )

        if "deploy" in request:
            preferences["deployment"] = self.ask_choice(
                "Choose Deployment",
                ["Docker", "Railway", "Render", "AWS", "No Preference"]
            )

        return preferences

    def enhance_prompt(self, request: str, intent: str, preferences: dict) -> dict:
        prompt = f"""
You are the Prompt Agent of KAIZEN.

Your ONLY job is to improve the user's software development request.

Do NOT generate tasks.
Do NOT generate execution plans.

Use the user's selected preferences.

Return ONLY valid JSON.

Output Format:

{{
    "intent":"",
    "enhanced_request":"",
    "requirements":[]
}}

User Request:
{request}

Intent:
{intent}

User Preferences:
{json.dumps(preferences, indent=2)}
"""

        response = self.llm.invoke([
            SystemMessage(content="You improve software development prompts."),
            HumanMessage(content=prompt)
        ])

        result = json.loads(response.content)
        result["preferences"] = preferences
        return result

    def run(self, request: str) -> dict:

        intent = self.detect_intent(request)
        print(f"Detected Intent : {intent}")

        preferences = self.collect_preferences(request)
        result = self.enhance_prompt(request, intent, preferences)

        print("\nEnhanced Prompt Generated\n")
        return result


if __name__ == "__main__":
    agent = PromptAgent()
    result = agent.run(input("Enter your request: "))
    print(json.dumps(result, indent=4))