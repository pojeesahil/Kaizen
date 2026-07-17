from enum import Enum

class Task(Enum):
    CREATE = "create"
    EDIT = "edit"
    DELETE = "delete"
    QUERY = "query"
    LIST = "list"

class Planner:

    def plan(self, query):
        q = query.lower()

        if any(word in q for word in ["create", "generate", "build", "make", "write"]):
            task = Task.CREATE
            use_rag = False
            use_llm = True

        elif any(word in q for word in ["edit", "modify", "change", "update", "refactor", "rewrite"]):
            task = Task.EDIT
            use_rag = True
            use_llm = True

        elif any(word in q for word in ["delete", "remove"]):
            task = Task.DELETE
            use_rag = False
            use_llm = False

        elif any(word in q for word in ["list", "show files", "show project", "project structure"]):
            task = Task.LIST
            use_rag = False
            use_llm = False

        else:
            task = Task.QUERY
            use_rag = True
            use_llm = True

        return {
            "task": task,
            "query": query,
            "use_rag": use_rag,
            "use_llm": use_llm
        }

def main():
    planner = Planner()

    while True:
        query = input("\nQuery > ").strip()

        if query.lower() in {"exit", "quit"}:
            break

        plan = planner.plan(query)

        print("\nExecution Plan")
        print("-" * 40)
        print(f"Task     : {plan['task'].value}")
        print(f"Use RAG  : {plan['use_rag']}")
        print(f"Use LLM  : {plan['use_llm']}")
        print(f"Query    : {plan['query']}")

if __name__ == "__main__":
    main()