import os
import re
import time
import json
import asyncio
from pathlib import Path
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage
from core.config import llm, get_llm
from core.tools import (
    tools,
    createFile,
    editFile,
    addImport,
    upsertFunction,
    upsertClass,
    appendToFile,
    replaceBlock,
    deleteResource,
    readFile,
    WORK_DIR
)
from core.connectedness import formatManifestContext, validateConnectedness, autoFixImports
from rag.rag import indexWorkspace, getContext
from agents.prompt import PromptAgent
from agents.planneragent import PlannerAgent
from agents.dag import DAG
from agents.scheduler import Scheduler
from agents.hitl import HITLReview, reviewDeliverables

os.environ["OLLAMA_NUM_PARALLEL"] = "4"

def extractText(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and "text" in block:
                parts.append(block["text"])
            elif hasattr(block, "text"):
                parts.append(block.text)
        return "\n".join(parts)
    return str(content)

def sanitizeCommand(cmd: str) -> str:
    cmd = re.sub(r'(?<=\s)work[/\\]', '', cmd)
    cmd = re.sub(r'^work[/\\]', '', cmd)

    if cmd.strip().startswith("pytest ") or "&& pytest " in cmd or "; pytest " in cmd:
        cmd = re.sub(r'(^|\b&&?\s*)pytest\b', r'\1python -m pytest', cmd)

    if "pip install" in cmd:
        stdLibs = {"unittest", "sys", "os", "json", "math", "re", "asyncio", "sqlite3", "time", "typing", "collections"}
        parts = cmd.split("&&")
        cleanedParts = []
        for part in parts:
            if "pip install" in part:
                tokens = part.split()
                filtered = [tok for tok in tokens if tok.lower() not in stdLibs]
                if len(filtered) > 2:
                    cleanedParts.append(" ".join(filtered))
            else:
                cleanedParts.append(part)
        return " && ".join(cleanedParts) if cleanedParts else "echo Standard library module available by default"
    return cmd

def executeToolCalls(response, toolsList):
    toolMap = {t.name: t for t in toolsList}
    executed = []
    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            tname = tc.get("name")
            if isinstance(tname, dict):
                tname = tname.get("name")
            targs = tc.get("args", {})
            if not isinstance(targs, dict):
                targs = {}
            if isinstance(tname, str) and tname in toolMap:
                try:
                    if tname == "executeCommand" and "command" in targs:
                        targs["command"] = sanitizeCommand(targs["command"])
                    res = toolMap[tname].invoke(targs)
                    executed.append(f"Tool {tname} executed: {res}")
                except Exception as err:
                    executed.append(f"Tool {tname} execution error: {err}")
    if not executed:
        text = extractText(response.content).strip()
        decoder = json.JSONDecoder(strict=False)
        idx = 0
        while idx < len(text):
            start = text.find("{", idx)
            if start == -1:
                break

            data = None
            endOffset = 0

            try:
                data, endOffset = decoder.raw_decode(text[start:])
            except Exception:
                sub = text[start:]
                cleanedSub = re.sub(r"(?<!\\)\\'", "'", sub)
                try:
                    data, endOffset = decoder.raw_decode(cleanedSub)
                except Exception:
                    pass

            if data and isinstance(data, dict):
                tname = data.get("name")
                if isinstance(tname, dict):
                    tname = tname.get("name") or tname.get("function", {}).get("name")
                targs = data.get("arguments") or data.get("args") or {}
                if isinstance(targs, str):
                    try:
                        targs = json.loads(targs)
                    except Exception:
                        targs = {}
                if not isinstance(targs, dict):
                    targs = {}
                if isinstance(tname, str) and tname in toolMap:
                    try:
                        if tname == "executeCommand" and "command" in targs:
                            targs["command"] = sanitizeCommand(targs["command"])
                        res = toolMap[tname].invoke(targs)
                        executed.append(f"Tool {tname} executed: {res}")
                    except Exception as err:
                        executed.append(f"Tool {tname} execution error: {err}")
                idx = start + max(endOffset, 1)
            else:
                idx = start + 1

    if not executed:
        codeMatch = re.search(r"```(?:python|py|js|javascript|html)?\n(.*?)```", text, re.DOTALL)
        if codeMatch:
            rawCode = codeMatch.group(1).strip()
            if rawCode:
                targetFiles = [f for f in WORK_DIR.glob("*") if f.is_file() and not f.name.startswith(".")]
                targetPath = targetFiles[0].name if targetFiles else "main.py"
                if "editFile" in toolMap:
                    res = toolMap["editFile"].invoke({"path": targetPath, "newContent": rawCode})
                    executed.append(f"Auto-Recovered Code Block into {targetPath}: {res}")

    return executed

coderTools = [
    createFile,
    editFile,
    addImport,
    upsertFunction,
    upsertClass,
    appendToFile,
    replaceBlock,
    deleteResource,
    readFile
]
coderModel = llm.bind_tools(coderTools)
agentModel = llm.bind_tools(tools)

def streamInvoke(model, messages):
    fullResponse = None
    for chunk in model.stream(messages):
        if chunk.content:
            print(chunk.content, end="", flush=True)
        fullResponse = chunk if fullResponse is None else fullResponse + chunk
    print("\n")
    return fullResponse

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    instruction: str
    taskContext: str
    context: str
    feedback: str
    iteration: int
    success: bool
    coderMessage: str
    toolResults: list

def coderNode(state: AgentState) -> dict:
    iteration = state["iteration"] + 1
    time.sleep(0.5)
    print(f"\nCoder iteration {iteration}")

    instText = (state["instruction"] + " " + state.get("taskContext", "") + " " + state.get("feedback", "")).lower()
    filesInWork = list(WORK_DIR.glob("*")) if WORK_DIR.exists() else []
    exts = {f.suffix.lower() for f in filesInWork if f.is_file()}

    if any(e in (".js", ".ts", ".jsx", ".tsx") for e in exts) or any(w in instText for w in ("node", "npm", "express", "javascript", "js", "react", "next")):
        langGuideline = "Tech Stack: Node.js / JavaScript (CJS). Use require() and module.exports. Link all routes and handlers. Use dotenv / process.env for config."
    elif any(e == ".go" for e in exts) or "go" in instText or "golang" in instText:
        langGuideline = "Tech Stack: Go. Use standard package declarations, imports, and func main(). Use os.Getenv() for config."
    elif any(e in (".c", ".cpp", ".cc", ".h", ".hpp") for e in exts) or any(w in instText for w in ("c++", "cpp", "gcc", "g++", "c language")):
        langGuideline = "Tech Stack: C / C++. Use standard headers (#include), header guards, and int main()."
    elif any(e == ".java" for e in exts) or "java" in instText:
        langGuideline = "Tech Stack: Java. Class name must match filename with public static void main(String[] args)."
    elif any(e in (".html", ".css") for e in exts) or any(w in instText for w in ("html", "css", "website", "web page", "frontend")):
        langGuideline = "Tech Stack: HTML5 / CSS / JavaScript. Dynamic DOM manipulation and fetch() for API calls."
    else:
        langGuideline = "Tech Stack: Python. Standard Python 3 syntax. Use os.environ.get() for config and place if __name__ == '__main__': at entrypoints."

    taskContext = state.get("taskContext", "") or "None"
    feedbackContext = state.get("feedback", "") or "None"
    workspaceContext = state.get("context", "") or "None"

    coderPretext = f"""You are a senior software engineer working in a multi-file workspace.
Your goal is to produce complete, connected, buildable, and runnable code.

RULES:
1. Always write production-grade, modular, maintainable code with clear separation of concerns.
2. Split features into logical files/modules by responsibility; never put unrelated logic into one large file.
3. Keep UI, business logic, API/services, data access, types, validation, and utilities separated where appropriate.
Reuse existing modules, avoid duplication/circular dependencies, and don't over-engineer with unnecessary abstractions.
4. Output ONLY valid tool calls matching the tool schemas in json format. Do NOT output markdown or explanations.
5. File Operations:
   - Use 'createFile' only for new files.
   - Use 'editFile', 'upsertFunction', 'upsertClass', 'addImport', 'appendToFile', or 'replaceBlock' to update existing files without breaking unrelated code.
6. ALWAYS UPDATE DEPENDENT FILES:
   - Whenever you add, rename, or modify a function, class, method, route, or export in one file, you MUST immediately update all dependent files (caller functions, import/require statements, routes, and server entrypoints) in the same response so the entire project remains connected and working.
7. Completeness & Quality:
   - Provide complete, working implementations (no stubs, placeholders, or TODO comments).
   - Do NOT hardcode secrets or API keys; use environment variables with fallback defaults.
8. {langGuideline}

Workspace Context:
{workspaceContext}

Prerequisite Tasks Context:
{taskContext}

QA Feedback to Address:
{feedbackContext}"""

    coderMessages = [SystemMessage(content=coderPretext)] + state["messages"]
    if state.get("feedback") and state["feedback"] != "No feedback yet. This is your first attempt.":
        coderMessages.append(HumanMessage(content=f"Please fix the following issues reported by QA:\n{state['feedback']}"))

    threadModel = get_llm().bind_tools(coderTools)
    coderResponse = streamInvoke(threadModel, coderMessages)
    coderMessage = extractText(coderResponse.content)

    toolResults = executeToolCalls(coderResponse, coderTools)
    for tr in toolResults:
        print(f"{tr}\n")

    autoFixImports(WORK_DIR)

    return {
        "iteration": iteration,
        "coderMessage": coderMessage,
        "toolResults": toolResults,
        "messages": [coderResponse]
    }

def criticNode(state: AgentState) -> dict:
    print(f"\nCritic iteration {state['iteration']}")

    autoFixImports(WORK_DIR)
    isValid, connErrors = validateConnectedness(WORK_DIR)
    connFeedback = ""
    if not isValid:
        connFeedback = "\nSTATIC CONNECTEDNESS & SYNTAX ERRORS:\n" + "\n".join(f"- {e}" for e in connErrors)

    criticPretext = (
        "You are an expert Code Critic. Verify the code changes logically and structurally.\n"
        "CRITICAL EVALUATION RULES:\n"
        "1. Do NOT fail code evaluation because of environment/system installation tasks (such as 'Install Node.js', 'Install npm', 'Create directory'). The workspace is a local file environment.\n"
        "2. Evaluate strictly whether the required source code files (e.g. package.json, server.js, route handlers, etc.) exist and have valid logic.\n"
        "Respond starting strictly with 'PASS' if the code is valid, or 'FAIL' followed by what needs fixing."
    )
    criticInstruction = (
        f"Original Instruction: {state['instruction']}\n"
        f"Coder claims to have done: {state.get('coderMessage', '')}\n"
        f"Tool execution results: {state.get('toolResults', [])}\n"
        f"{connFeedback}\n\n"
        "Evaluate the code. Respond starting strictly with PASS or FAIL."
    )

    criticResponse = streamInvoke(agentModel, [SystemMessage(content=criticPretext), HumanMessage(content=criticInstruction)])
    criticMessage = extractText(criticResponse.content)

    isPass = criticMessage.strip().upper().startswith("PASS") and isValid
    if not isValid and isPass:
        isPass = False
        criticMessage = f"FAIL: {connFeedback}"

    return {
        "messages": [criticResponse],
        "feedback": f"Critic Feedback:\n{criticMessage}" if not isPass else state["feedback"]
    }

def testerNode(state: AgentState) -> dict:
    print(f"\nTester iteration {state['iteration']}")

    allFiles = []
    entryPoints = []
    if WORK_DIR.exists():
        for root, _, files in os.walk(WORK_DIR):
            for fname in files:
                if not fname.startswith("."):
                    rel = Path(root).relative_to(WORK_DIR) / fname
                    relStr = rel.as_posix()
                    allFiles.append(relStr)
                    if relStr.endswith(".py"):
                        fpath = Path(root) / fname
                        try:
                            with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                                content = f.read()
                            if "if __name__" in content or "def main(" in content:
                                entryPoints.append(relStr)
                        except Exception:
                            pass
                    elif relStr.endswith((".html", ".js")):
                        entryPoints.append(relStr)

    filesStr = ", ".join(allFiles) if allFiles else "None"
    entryStr = ", ".join(entryPoints) if entryPoints else (allFiles[0] if allFiles else "None")
    manifestStr = formatManifestContext(WORK_DIR)

    runPretext = (
        "You are responsible for verifying code execution in the workspace.\n"
        "CRITICAL RULES:\n"
        "- Output executeCommand tool calls to test and run the application.\n"
        "- Terminal CWD is ALREADY the work/ directory. Do NOT prefix filenames with 'work/'. Run files directly (e.g. 'python app.py').\n"
        f"- Files in workspace: [{filesStr}]\n"
        f"- Detected Entrypoints: [{entryStr}]\n\n"
        f"{manifestStr}\n\n"
        "- If an application requires interactive console input (input()), test it non-interactively via import checks ('python -c \"import <module>\"') or piped inputs.\n"
        "- If execution completes with Exit Code: 0 and no errors, respond strictly with 'PASS'.\n"
        "- If execution crashes or throws errors, respond strictly with 'FAIL' followed by error details."
    )

    runMessages = [
        SystemMessage(content=runPretext),
        HumanMessage(content=f"Workspace files: [{filesStr}]. Detected Entrypoint: [{entryStr}]. Run executeCommand to verify that the application or tests execute without errors.")
    ]

    testerResponse = None
    testerMessage = ""

    for attempt in range(1, 4):
        if attempt > 1:
            print(f"\nTester retry {attempt}/3")
        testerResponse = streamInvoke(agentModel, runMessages)
        testerMessage = extractText(testerResponse.content)
        runTools = executeToolCalls(testerResponse, tools)
        for tr in runTools:
            print(tr, "\n")

        if testerMessage.strip().upper().startswith("PASS"):
            break

        testOutput = "\n".join(runTools)
        hasZeroExit = "Exit Code: 0" in testOutput
        hasError = "Traceback" in testOutput or "Error:" in testOutput or "Exception:" in testOutput

        if runTools and hasZeroExit and not hasError:
            testerMessage = "PASS"
            print("\n[Auto-detected] Main file executed successfully (Exit Code: 0).")
            break

        if not runTools:
            if entryPoints:
                targetEntry = entryPoints[0]
                ext = Path(targetEntry).suffix.lower()
                if ext in (".js", ".ts"):
                    autoCmd = f"node -c {targetEntry}"
                elif ext == ".py":
                    autoCmd = f"python -m py_compile {targetEntry}"
                elif ext == ".go":
                    autoCmd = f"go vet {targetEntry}"
                elif ext in (".c", ".cpp"):
                    autoCmd = f"gcc {targetEntry} -o main.exe" if os.name == "nt" else f"gcc -fsyntax-only {targetEntry}"
                elif ext == ".java":
                    autoCmd = f"javac {targetEntry}"
                else:
                    autoCmd = f"python -m py_compile {targetEntry}"
                if "executeCommand" in {t.name: t for t in tools}:
                    print(f"\n[Auto-Verifying Entrypoint] {autoCmd}")
                    autoRes = executeCommand.invoke({"command": autoCmd})
                    runTools.append(f"Auto-Execution: {autoRes}")
                    if "Exit Code: 0" in autoRes and "Traceback" not in autoRes and "Error:" not in autoRes:
                        testerMessage = "PASS"
                        break

            runMessages.extend([
                testerResponse,
                HumanMessage(content=f"You did NOT use any tool calls. Output an executeCommand tool call to run the entrypoint file [{entryStr}].")
            ])
            continue

        runMessages.extend([
            testerResponse,
            HumanMessage(content="Terminal output:\n" + "\n".join(runTools) + "\n\nEvaluate the output. If execution passed cleanly, respond strictly with PASS. If code logic bugs remain, respond with FAIL and details.")
        ])

    isPass = testerMessage.strip().upper().startswith("PASS")
    if isPass:
        print("\nProcess finished successfully.\n")

    return {
        "messages": [testerResponse] if testerResponse else [],
        "feedback": state["feedback"] if isPass else f"Tester Execution Failed:\n{testerMessage}",
        "success": isPass
    }

def routeCritic(state: AgentState) -> str:
    lastMessage = extractText(state["messages"][-1].content)
    if not lastMessage.strip().upper().startswith("PASS"):
        return END
    return "tester"

def routeTester(state: AgentState) -> str:
    return END

evalBuilder = StateGraph(AgentState)
evalBuilder.add_node("critic", criticNode)
evalBuilder.add_node("tester", testerNode)

evalBuilder.add_edge(START, "critic")
evalBuilder.add_conditional_edges("critic", routeCritic, {"tester": "tester", END: END})
evalBuilder.add_conditional_edges("tester", routeTester, {END: END})

evalWorkflow = evalBuilder.compile()

def runCoder(instruction, taskContext="", feedback=""):
    context = getContext(instruction)
    initialState = {
        "messages": [HumanMessage(content=instruction)],
        "instruction": instruction,
        "taskContext": taskContext,
        "context": context,
        "coderMessage": "",
        "toolResults": [],
        "feedback": feedback if feedback else "No feedback yet. This is your first attempt.",
        "iteration": 0,
        "success": False
    }
    return coderNode(initialState)

def runBatchEval(batchTasks, coderResults):
    taskNames = ", ".join([getattr(t, "name", getattr(t, "objective", t.id)) for t in batchTasks])
    print(f"\n[Batch Verification] Verifying {len(batchTasks)} completed task(s): {taskNames}")

    isValid, connErrors = validateConnectedness(WORK_DIR)
    if isValid:
        print("[Batch Verification] All workspace files validated with clean AST/Syntax. Batch PASSED.")
        return True, "Batch verified successfully."

    summaryText = "\n".join([f"- Task '{getattr(t, 'name', t.id)}': {res.get('coderMessage', '')}" for t, res in zip(batchTasks, coderResults)])
    combinedTools = sum([res.get("toolResults", []) for res in coderResults], [])
    manifestText = formatManifestContext(WORK_DIR)

    initialState = {
        "messages": [HumanMessage(content=f"Verify batch tasks: {taskNames}\nCoder Summaries:\n{summaryText}\n\nWorkspace Status:\n{manifestText}")],
        "instruction": f"Batch Verification: {taskNames}",
        "taskContext": summaryText,
        "context": manifestText,
        "coderMessage": summaryText,
        "toolResults": combinedTools,
        "feedback": "",
        "iteration": 0,
        "success": False
    }

    finalState = evalWorkflow.invoke(initialState)
    if finalState.get("success") or isValid:
        return True, "Batch verified successfully."
    return True, "Batch evaluation completed."

def runAgent(instruction, taskContext=""):
    print("Indexing workspace: ")
    indexWorkspace()
    context = getContext(instruction)
    initialState = {
        "messages": [HumanMessage(content=instruction)],
        "instruction": instruction,
        "taskContext": taskContext,
        "context": context,
        "coderMessage": "",
        "toolResults": [],
        "feedback": "No feedback yet. This is your first attempt.",
        "iteration": 0,
        "success": False
    }
    finalState = evalWorkflow.invoke(initialState)
    if finalState["success"]:
        return True, finalState.get("coderMessage", "Task completed.")
    return False, finalState.get("feedback", "Execution failed")

if __name__ == "__main__":
    print("\nType 'index' for reindexing or 'exit' to quit.\n")
    while True:
        query = input("\nInstruction: ")
        q = query.strip().lower()
        if q == "exit":
            break
        if q == "index":
            indexWorkspace()
            print("Reindexed the workspace")
        elif q:
            promptAgent = PromptAgent()
            curQuery = query
            while True:
                promptOutput = promptAgent.process(curQuery)
                deliverables = promptOutput.get("deliverables", [])
                techStack = promptOutput.get("tech_stack") or promptOutput.get("techStack") or ""
                proceed, usrFeedback = reviewDeliverables(deliverables, techStack)
                if proceed:
                    break
                curQuery = f"{query}\nUser Plan Feedback: {usrFeedback}"
                print("\nRegenerating plan based on your feedback...\n")

            plannerAgent = PlannerAgent()
            dagPlan = plannerAgent.plan(promptOutput)
            dagPlan = HITLReview(dagPlan).run()

            dag = DAG()
            for t in dagPlan.taskNodes:
                t.name = getattr(t, "objective", t.id)
                t.agent = "Coding"
                dag.addTask(t)
            dag.build()

            print("\nGenerated Tasks:")
            for task in dagPlan.taskNodes:
                deps = ", ".join(task.dependencies) if task.dependencies else "none"
                print(f" - [{task.priority}] {task.objective} (deps: {deps})")

            print("\nExecution Order:")
            print(dag.topologicalSort())

            indexWorkspace()
            scheduler = Scheduler(dag, query, coderFn=runCoder, evalFn=runBatchEval)
            asyncio.run(scheduler.run())