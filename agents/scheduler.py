import os
import heapq
import asyncio
from pathlib import Path
from typing import Callable, Optional
from agents.dag import DAG
from rag.rag import indexWorkspace
from core.connectedness import formatManifestContext, validateConnectedness, autoFixImports
from langchain_core.messages import HumanMessage
from core.config import get_llm

def runPreRepairTriage(feedback: str, techStack: str = "") -> str:
    trimmedFeedback = feedback.strip()
    lowerFb = trimmedFeedback.lower()
    if "critic feedback" in lowerFb or ("tester execution failed" not in lowerFb and "exit code:" not in lowerFb):
        return ""
    if "tester execution failed:" in lowerFb:
        idx = lowerFb.find("tester execution failed:")
        trimmedFeedback = trimmedFeedback[idx + len("tester execution failed:"):].strip()
    if len(trimmedFeedback) > 3000:
        trimmedFeedback = trimmedFeedback[:1500] + "\n...\n" + trimmedFeedback[-1500:]
    prompt = (
        f"A project build or verification failed with output:\n{trimmedFeedback}\n\n"
        f"Tech stack: {techStack}\n\n"
        "Diagnose the failure:\n"
        "1. Identify the root failure category (e.g. Compiler/Build Configuration, Missing Type Definitions/Dependencies, Syntax/Import Error, Application Runtime Defect).\n"
        "2. Identify the specific file(s) or manifests that should be adjusted (e.g. tsconfig, package manifest, build tool config, or source code).\n"
        "3. Provide direct, non-speculative instruction on the exact fix needed.\n"
        "Keep the response concise and actionable."
    )
    try:
        response = get_llm().invoke([HumanMessage(content=prompt)])
        content = response.content
        if isinstance(content, list):
            return "".join(p if isinstance(p, str) else p.get("text", "") for p in content).strip()
        return str(content).strip()
    except Exception:
        return ""

def decideRepairAgent(feedback: str, consecutiveTesterCount: int = 0) -> str:
    if consecutiveTesterCount >= 2:
        return "coder"
    lowerFb = feedback.lower()
    if "tester execution failed" not in lowerFb and "exit code:" not in lowerFb:
        return "coder"
    prompt = (
        f"Verification failed with output:\n{feedback[:2000]}\n\n"
        "Decide which agent should handle this failure:\n"
        "- TESTER: If this is an environmental issue, command timeout, transient execution error, port busy, or incomplete verification where the Tester should re-run verification commands.\n"
        "- CODER: If this is a source code bug, compilation error, syntax error, missing dependency, or application logic defect requiring code changes.\n"
        "Reply strictly with TESTER or CODER."
    )
    try:
        response = get_llm().invoke([HumanMessage(content=prompt)])
        content = response.content
        text = "".join(p if isinstance(p, str) else p.get("text", "") for p in content) if isinstance(content, list) else str(content)
        if "TESTER" in text.upper():
            return "tester"
        return "coder"
    except Exception:
        return "coder"

class Scheduler:

    def __init__(self, dag: DAG, goal: str = "", techStack: str = "", fileStructure: Optional[list] = None, coderFn: Optional[Callable] = None, evalFn: Optional[Callable] = None):
        self.dag = dag
        self.goal = goal
        self.techStack = techStack
        self.fileStructure = fileStructure or []
        self.coderFn = coderFn
        self.evalFn = evalFn
        self.queue: list[tuple[int, str]] = []
        self.taskOutputs: dict[str, str] = {}
        self.taskFeedbacks: dict[str, str] = {}
        self.workDir = Path(__file__).resolve().parent.parent / "work"

    def loadReadyTasks(self) -> None:
        for task in self.dag.getReadyTasks():
            if getattr(task, "status", "pending") != "pending":
                continue
            task.status = "running"
            heapq.heappush(self.queue, (task.priority, task.id))

    def executeCoder(self, task) -> dict:
        tname = getattr(task, "name", getattr(task, "objective", task.id))
        print(f"\n[{getattr(task, 'agent', 'Coding')}] Starting Coder Agent for task: {tname}")

        depContext = ""
        for depId in getattr(task, "dependencies", []):
            if depId in self.taskOutputs:
                depContext += f"\n- Parent task '{depId}' completed: {self.taskOutputs[depId]}"

        manifestContext = formatManifestContext(self.workDir)
        if manifestContext:
            depContext += f"\n\n{manifestContext}"

        workFiles = self.readWorkspaceFiles()
        if workFiles:
            depContext += "\n\nCurrent workspace file contents:\n" + workFiles

        instParts = []
        if self.goal:
            instParts.append(f"Overall Goal: {self.goal}")
        if self.techStack:
            instParts.append(f"Target Tech Stack: {self.techStack}")
        if self.fileStructure:
            instParts.append(f"Planned File Structure: {', '.join(self.fileStructure)}")
        instParts.append(f"Task: {tname}")

        taskOutput = getattr(task, "output", "")
        if taskOutput:
            instParts.append(f"Required Artifacts: {taskOutput}")

        taskCrit = getattr(task, "completionCriteria", "") or getattr(task, "completion_criteria", "")
        if taskCrit:
            instParts.append(f"Completion Criteria: {taskCrit}")

        instruction = "\n".join(instParts)

        feedback = self.taskFeedbacks.get(task.id, "")

        if self.coderFn:
            result = self.coderFn(instruction, taskContext=depContext, feedback=feedback)
        else:
            result = {"coderMessage": "Task executed", "toolResults": []}

        return result

    async def executeCoderThrottled(self, task, semaphore):
        async with semaphore:
            result = await asyncio.to_thread(self.executeCoder, task)
        return task, result

    def readWorkspaceFiles(self) -> str:
        if not self.workDir.exists():
            return ""

        supportedExts = {
            ".py", ".js", ".ts", ".java", ".html", ".css", ".json",
            ".jsx", ".tsx", ".go", ".cpp", ".c", ".h", ".yaml", ".yml", ".md", ".txt", ".svg"
        }
        skipDirs = {
            "node_modules", "__pycache__", "venv", ".git", ".venv",
            "chroma_db", "graphify-out", "dist", "build", ".next", ".nuxt", ".cache", "coverage"
        }
        skipFiles = {
            "package-lock.json", "yarn.lock", "pnpm-lock.yaml", "composer.lock", "cargo.lock", "poetry.lock"
        }

        parts = []
        for root, dirs, files in os.walk(self.workDir):
            dirs[:] = [d for d in dirs if d not in skipDirs and not d.startswith(".")]
            for fname in sorted(files):
                if fname in skipFiles or fname.endswith((".min.js", ".min.css", ".map", ".pack")):
                    continue
                ext = os.path.splitext(fname)[1].lower()
                if ext not in supportedExts:
                    continue
                fpath = os.path.join(root, fname)
                if os.path.getsize(fpath) > 100000:
                    continue
                relpath = os.path.relpath(fpath, self.workDir)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(50000)
                    if content.strip():
                        parts.append(f"[File: {relpath}]\n{content}")
                except Exception:
                    continue

        return "\n\n".join(parts)

    async def run(self) -> None:
        self.workDir.mkdir(parents=True, exist_ok=True)
        self.loadReadyTasks()

        completedTasks = []
        allCoderResults = []
        halted = False

        while self.queue:
            batch = []
            while self.queue:
                _, taskId = heapq.heappop(self.queue)
                batch.append(self.dag.tasks[taskId])

            batchSize = len(batch)
            runMode = "in Parallel" if batchSize > 1 else "Sequentially"
            print(f"\nRunning {batchSize} Coder Agent(s) {runMode}")

            semaphore = asyncio.Semaphore(3)
            gathered = await asyncio.gather(
                *(self.executeCoderThrottled(task, semaphore) for task in batch)
            )

            coderResults = []
            for task, result in gathered:
                coderResults.append(result)
                toolResults = result.get("toolResults", [])
                if toolResults:
                    print(f"Task '{getattr(task, 'name', task.id)}' executed {len(toolResults)} tool(s).")
                self.dag.markComplete(task.id)
                coderMsg = result.get("coderMessage", "Task completed.")
                if toolResults:
                    coderMsg += "\nTool Executions: " + "; ".join(toolResults)
                self.taskOutputs[task.id] = coderMsg
                self.taskFeedbacks.pop(task.id, None)

            autoFixImports(self.workDir)
            isValid, batchErrors = validateConnectedness(self.workDir)
            if not isValid:
                errText = "\n".join(f"- {e}" for e in batchErrors)
                print(f"\n[Post-Batch AST Import Check Failed]:\n{errText}")
                if self.coderFn:
                    repairContext = ""
                    manifestSnapshot = formatManifestContext(self.workDir)
                    if manifestSnapshot:
                        repairContext += f"\n\n{manifestSnapshot}"
                    workSnapshot = self.readWorkspaceFiles()
                    if workSnapshot:
                        repairContext += "\n\nCurrent workspace file contents:\n" + workSnapshot
                    repairPrompt = f"Fix the following import and syntax errors in workspace files immediately:\n{errText}"
                    repairResult = await asyncio.to_thread(
                        self.coderFn, repairPrompt, taskContext=repairContext, feedback=errText
                    )
                    coderResults.append(repairResult)
                autoFixImports(self.workDir)

            await asyncio.to_thread(indexWorkspace)

            completedTasks.extend(batch)
            allCoderResults.extend(coderResults)

            if self.evalFn:
                passed, fb = await asyncio.to_thread(self.evalFn, batch, coderResults, False)
                if passed:
                    print(f"\n[Milestone Review] Batch of {batchSize} task(s) approved by Critic.")
                else:
                    repaired = False
                    for repair in range(1, 11):
                        print(f"\n[Milestone Repair {repair}/10] Triggering Coder Agent to fix Critic feedback...")
                        repairPrompt = (
                            f"Overall Goal: {self.goal}\n"
                            f"Target Tech Stack: {self.techStack}\n\n"
                            f"The latest batch of tasks failed Critic review.\n"
                            f"Critic feedback:\n{fb}\n\n"
                            "Inspect the current workspace files and use tool calls (createFile, createFiles, editFile, replaceBlock, upsertFunction, upsertClass, appendToFile, grepFiles, searchWeb) to fix all issues."
                        )
                        fixRes = await asyncio.to_thread(self.coderFn, repairPrompt, taskContext=self.readWorkspaceFiles(), feedback=fb)
                        coderResults.append(fixRes)
                        allCoderResults.append(fixRes)
                        await asyncio.to_thread(indexWorkspace)

                        passed, fb = await asyncio.to_thread(self.evalFn, batch, coderResults, False)
                        if passed:
                            print(f"\n[Milestone Repair] Repair {repair} succeeded. Continuing to next batch.")
                            repaired = True
                            break
                    if not repaired:
                        print("\n[Kaizen] Milestone review could not be resolved after 10 repair attempts. Halting pipeline.")
                        halted = True
                        break

            self.loadReadyTasks()

        if completedTasks and not halted:
            if self.evalFn:
                passed, fb = await asyncio.to_thread(self.evalFn, completedTasks, allCoderResults, True)
                if passed:
                    print("\n[Kaizen] All plan tasks executed and verified successfully.\n")
                else:
                    consecutiveTesterCount = 0
                    for repair in range(1, 11):
                        targetAgent = decideRepairAgent(fb, consecutiveTesterCount)
                        if targetAgent == "tester":
                            consecutiveTesterCount += 1
                            print(f"\n[Verification Repair {repair}/10] LLM routed failure to Tester Agent to re-run verification...")
                            passed, fb = await asyncio.to_thread(self.evalFn, completedTasks, allCoderResults, True)
                            if passed:
                                print(f"\n[Verification Repair] Repair {repair} succeeded.")
                                break
                            continue

                        consecutiveTesterCount = 0
                        print(f"\n[Verification Repair {repair}/10] LLM routed failure to Coder Agent to fix verification failure...")
                        triageDiagnosis = runPreRepairTriage(fb, self.techStack)
                        if triageDiagnosis:
                            print(f"\n[Pre-Repair Triage]:\n{triageDiagnosis}\n")
                        triageSection = f"Pre-Repair Triage Analysis:\n{triageDiagnosis}\n\n" if triageDiagnosis else ""
                        repairPrompt = (
                            f"Overall Goal: {self.goal}\n"
                            f"Target Tech Stack: {self.techStack}\n\n"
                            f"The project failed verification after all tasks completed.\n"
                            f"Critic/Tester feedback:\n{fb}\n\n"
                            f"{triageSection}"
                            "Inspect the current workspace files and use tool calls (createFile, createFiles, editFile, replaceBlock, upsertFunction, upsertClass, appendToFile, grepFiles, searchWeb) to fix all issues so the application runs correctly."
                        )
                        enhancedFb = f"{fb}\n\n[Pre-Repair Triage Analysis]:\n{triageDiagnosis}" if triageDiagnosis else fb
                        fixRes = await asyncio.to_thread(self.coderFn, repairPrompt, taskContext=self.readWorkspaceFiles(), feedback=enhancedFb)
                        allCoderResults.append(fixRes)
                        await asyncio.to_thread(indexWorkspace)

                        passed, fb = await asyncio.to_thread(self.evalFn, completedTasks, allCoderResults, True)
                        if passed:
                            print(f"\n[Verification Repair] Repair {repair} succeeded.")
                            break
                    else:
                        print("\n[Kaizen] Verification could not be resolved after 10 repair attempts.\n")
            else:
                print("\n[Kaizen] All plan tasks executed.\n")
        elif halted:
            print("\n[Kaizen] Pipeline halted due to unresolvable milestone failure.\n")

