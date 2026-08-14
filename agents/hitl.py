from agents.models import DAGPlan, TaskNode, newId


class HITLReview:
    """
    Simple Human-in-the-Loop review for the planner.
    Lets the user approve, edit, add, or delete tasks.
    """

    def __init__(self, dag_plan: DAGPlan):
        self.dag_plan = dag_plan

    def run(self) -> DAGPlan:
        """Main loop: shows tasks and asks the user to approve or edit."""
        while True:
            tasks = self.dag_plan.taskNodes

            print("\nPlan Review")
            for index, task in enumerate(tasks, start=1):
                print(f"  {index}. {task.objective}")

            print("\nOptions:")
            print("  [a] Approve and run")
            print("  [e] Edit tasks")

            choice = input("\nEnter choice (a/e): ").strip().lower()

            if choice == "a":
                print("\nPlan approved! Starting execution...\n")
                return self.dag_plan

            elif choice == "e":
                self.edit_tasks()

            else:
                print("Invalid choice! Please type 'a' to approve or 'e' to edit.")

    def edit_tasks(self):
        """Simple menu to edit, add, or delete tasks."""
        while True:
            tasks = self.dag_plan.taskNodes

            print("\n--- Current Tasks ---")
            for index, task in enumerate(tasks, start=1):
                print(f"  {index}. {task.objective}")

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
                        new_text = input("Enter new objective: ").strip()
                        if new_text:
                            tasks[idx].objective = new_text
                            print("Task updated!")
                    else:
                        print("Invalid task number.")
                else:
                    print("Please enter a valid number.")

            elif choice == "2":
                new_text = input("Enter new task objective: ").strip()
                if new_text:
                    last_task = tasks[-1] if len(tasks) > 0 else None
                    last_id = last_task.id if last_task else None
                    deliverable_id = last_task.deliverableId if last_task else "manual"

                    new_task = TaskNode(
                        id=newId("task"),
                        deliverableId=deliverable_id,
                        objective=new_text,
                        output=new_text,
                        completionCriteria=f"{new_text} completed.",
                        parentTask=last_id,
                        dependencies=[last_id] if last_id else [],
                        priority=3,
                    )
                    tasks.append(new_task)
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
