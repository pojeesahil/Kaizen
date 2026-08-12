from prompt import PromptAgent
from terminalui import TerminalUI

DefaultRequest = "Create a README, Dockerfile, and a login page with authentication, offline only"


def getPromptAgentOutput(UserRequest: str):
    return PromptAgent().run(UserRequest)


def main() -> None:
    UserRequest = DefaultRequest
    PromptAgentOutput = getPromptAgentOutput(UserRequest)

    DagPlan = TerminalUI().run(PromptAgentOutput)

    print("\nRaw DAG (for DAG Builder): ")
    for Task in DagPlan.taskNodes:
        Deps = ", ".join(Task.dependencies) if Task.dependencies else "none"
        print(f"[{Task.priority}] {Task.objective}  (deps: {Deps})")


if __name__ == "__main__":
    main()