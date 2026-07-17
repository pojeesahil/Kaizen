from agents.planner import Planner, Task
from agents.coder import Coder
from vector_db.retrieve import Retriever
from tools.file_tools import FileTools
from validators.task_validator import TaskValidator

class TerminalAgent:

    def __init__(self):
        self.planner = Planner()
        self.validator = TaskValidator()
        self.retriever = Retriever()
        self.coder = Coder()
        self.tools = FileTools()

    def build_context(self, query):
        results = self.retriever.retrieve(query)

        return "\n\n".join(
            f"File: {r['source']}\nScore: {r['score']:.4f}\n\n{r['content']}"
            for r in results
        )

    def run(self):
        print("=" * 60)
        print("Terminal AI Coding Agent")
        print("Type 'exit' or 'quit' to stop.")

        while True:
            query = input("\nPrompt > ").strip()

            if query.lower() in {"exit", "quit"}:
                break

            plan = self.planner.plan(query)
            validation = self.validator.validate(plan)

            if not validation["valid"]:
                print(f"\nValidation Error: {validation['reason']}")
                continue

            plan["filename"] = validation["filename"]
            plan["language"] = validation["language"]

            if plan["task"] == Task.CREATE:
                self.handle_create(plan)

            elif plan["task"] == Task.EDIT:
                self.handle_edit(plan)

            elif plan["task"] == Task.DELETE:
                self.handle_delete(plan)

            elif plan["task"] == Task.QUERY:
                self.handle_query(plan)

            elif plan["task"] == Task.LIST:
                self.handle_list()

    def handle_create(self, plan):
        context = self.build_context(plan["query"]) if plan["use_rag"] else ""
        code = self.coder.generate(plan["query"], context)

        filename = plan["filename"]
        if not filename:
            filename = input("Filename: ").strip()

        self.tools.create_file(filename, code)
        print(f"\nCreated: {filename}")

    def handle_edit(self, plan):
        context = self.build_context(plan["query"])
        updated = self.coder.generate(plan["query"], context)

        filename = plan["filename"]
        if not filename:
            filename = input("Filename: ").strip()

        self.tools.edit_file(filename, updated)
        print(f"\nUpdated: {filename}")

    def handle_delete(self, plan):
        filename = plan["filename"]
        if not filename:
            filename = input("Filename: ").strip()

        self.tools.delete_file(filename)
        print(f"\nDeleted: {filename}")

    def handle_query(self, plan):
        context = self.build_context(plan["query"])
        answer = self.coder.generate(plan["query"], context)
        print("\n" + answer)

    def handle_list(self):
        files = self.tools.list_files()

        print()

        for file in files:
            print(file)

if __name__ == "__main__":
    TerminalAgent().run()