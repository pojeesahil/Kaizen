from agents.models import DAGPlan, TaskNode, newId

class HITLReview:
    def __init__(self, dagPlan: DAGPlan):
        self.dagPlan = dagPlan
        self.dag_plan = dagPlan

    def run(self) -> DAGPlan:
        while True:
            tasks = self.dagPlan.taskNodes
            print("\nPlan Review")
            for idx, task in enumerate(tasks, start=1):
                print(f"  {idx}. {task.objective}")

            print("\nOptions:")
            print("  [a] Approve and run")
            print("  [e] Edit tasks")

            choice = input("\nEnter choice (a/e): ").strip().lower()
            if choice == "a":
                print("\nPlan approved! Starting execution...\n")
                return self.dagPlan
            elif choice == "e":
                self.editTasks()
            else:
                print("Invalid choice! Please type 'a' to approve or 'e' to edit.")

    def editTasks(self):
        while True:
            tasks = self.dagPlan.taskNodes
            print("\n--- Current Tasks ---")
            for idx, task in enumerate(tasks, start=1):
                print(f"  {idx}. {task.objective}")

            print("\nEdit Menu:")
            print("  1. Edit a task")
            print("  2. Add a new task")
            print("  3. Delete a task")
            print("  4. Done editing (go back)")

            choice = input("\nEnter option (1-4): ").strip()
            if choice == "1":
                num = input("Enter task number to edit: ").strip()
                if num.isdigit():
                    idx = int(num) - 1
                    if 0 <= idx < len(tasks):
                        print(f"Current: {tasks[idx].objective}")
                        newText = input("Enter new objective: ").strip()
                        if newText:
                            tasks[idx].objective = newText
                            print("Task updated!")
                    else:
                        print("Invalid task number.")
                else:
                    print("Please enter a valid number.")

            elif choice == "2":
                newText = input("Enter new task objective: ").strip()
                if newText:
                    lastTask = tasks[-1] if len(tasks) > 0 else None
                    lastId = lastTask.id if lastTask else None
                    deliverableId = lastTask.deliverableId if lastTask else "manual"

                    newTask = TaskNode(
                        id=newId("task"),
                        deliverableId=deliverableId,
                        objective=newText,
                        output=newText,
                        completionCriteria=f"{newText} completed.",
                        parentTask=lastId,
                        dependencies=[lastId] if lastId else [],
                        priority=3,
                    )
                    tasks.append(newTask)
                    print("New task added!")

            elif choice == "3":
                num = input("Enter task number to delete: ").strip()
                if num.isdigit():
                    idx = int(num) - 1
                    if 0 <= idx < len(tasks):
                        removed = tasks.pop(idx)
                        print(f"Deleted: {removed.objective}")
                    else:
                        print("Invalid task number.")
                else:
                    print("Please enter a valid number.")

            elif choice == "4":
                print("Finished editing.")
                break
            else:
                print("Invalid option. Please enter 1, 2, 3, or 4.")

    edit_tasks = editTasks

def reviewDeliverables(deliverables: list, techStack: str = "") -> tuple[bool, str]:
    print("\nProposed Implementation Plan:")
    if techStack:
        print(f"Tech Stack: {techStack}\n")
    for idx, d in enumerate(deliverables, start=1):
        name = d.get("name", str(d)) if isinstance(d, dict) else getattr(d, "name", str(d))
        goal = d.get("goal", "") if isinstance(d, dict) else getattr(d, "goal", "")
        kind = d.get("kind", "") if isinstance(d, dict) else getattr(d, "kind", "")
        print(f"  {idx}. {name} [{kind}] - {goal}")

    print("\nOptions:")
    print("  [p] Proceed with plan")
    print("  [c] Change / adjust plan")

    while True:
        choice = input("\nEnter choice (p/c): ").strip().lower()
        if choice == "p":
            return True, ""
        elif choice == "c":
            fb = input("\nEnter adjustments/changes for the plan: ").strip()
            return False, fb
        else:
            print("Enter 'p' to proceed or 'c' to change.")

def finalReview() -> str:
    print("\n--- Final Review ---")
    print("Code is written and tested.")
    print("  [a] Accept")
    print("  [r] Reject")

    while True:
        choice = input("\nEnter choice (a/r): ").strip().lower()
        if choice == "a":
            print("\nAccepted! Work is complete.\n")
            return "accept"
        elif choice == "r":
            print("\nRejected. Re-running coder...\n")
            return "reject"
        else:
            print("Enter 'a' to accept or 'r' to reject.")

final_review = finalReview