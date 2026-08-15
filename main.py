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
from agents.hitl import HITLReview

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
            targs = tc.get("args", {})
            if tname in toolMap:
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
                targs = data.get("arguments") or data.get("args") or {}
                if tname in toolMap:
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
        # Fallback: extract code block if LLM generated raw markdown
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

    coderPretext = (
        "You are an autonomous software engineer with AST-level workspace tools.\n\n"
        "CRITICAL TOOL RULES:\n"
        "1. Output ONLY valid tool calls matching the format below. Do NOT use markdown code blocks.\n"
        "2. To add an import to a file, use 'addImport'.\n"
        "3. To define or update a function, use 'upsertFunction' (replaces that function without touching other code).\n"
        "4. To define or update a class, use 'upsertClass'.\n"
        "5. To append code before the main entrypoint, use 'appendToFile'.\n"
        "6. To create a new file from scratch, use 'createFile'.\n"
        "7. To edit an entire file, use 'editFile' (existing imports are preserved automatically).\n\n"
        "Tool Call Format Examples:\n"
        '{"name": "addImport", "arguments": {"path": "app.py", "module": "services.user", "name": "UserService"}}\n'
        '{"name": "upsertFunction", "arguments": {"path": "math_ops.py", "functionCode": "def add(a: float, b: float) -> float:\\n    return a + b"}}\n'
        '{"name": "upsertClass", "arguments": {"path": "models.py", "classCode": "class User:\\n    def __init__(self, name):\\n        self.name = name"}}\n'
        '{"name": "createFile", "arguments": {"path": "main.py", "content": "import sys\\n\\ndef main():\\n    pass\\n\\nif __name__ == \'__main__\':\\n    main()"}}\n\n'
        "Code Guidelines:\n"
        "- Write clean, concise, production code.\n"
        "- Connect all modules using the exact import strings shown in Prerequisite Context.\n"
        "- When writing entrypoints, place 'if __name__ == \"__main__\": main()' at the very bottom of the file.\n\n"
        f"Workspace Context:\n{state['context']}\n\n"
        f"Prerequisite Tasks Context:\n{state['taskContext'] if state['taskContext'] else 'None'}\n\n"
        f"Critic/Tester Feedback to address:\n{state['feedback']}"
    )

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

    filesInWork = []
    if WORK_DIR.exists():
        filesInWork = [f.name for f in WORK_DIR.glob("*") if f.is_file()]
    filesStr = ", ".join(filesInWork) if filesInWork else "None"

    runPretext = (
        "You are responsible for verifying code execution.\n"
        "CRITICAL RULES:\n"
        "- Output executeCommand tool calls to install required imports and run/verify the main application file.\n"
        "- The terminal execution directory (CWD) is ALREADY the work/ directory. Do NOT prefix filenames with 'work/'. Run files directly (e.g. 'python app.py' or 'node server.js').\n"
        f"- Files currently in workspace: {filesStr}\n"
        "- For applications requiring interactive console input (input()), verify non-interactively by testing imports (e.g. 'python -c \"import main\"') or piping simulated inputs.\n"
        "- If execution completes with Exit Code: 0 and no errors, respond strictly with 'PASS'.\n"
        "- If execution crashes, times out, or throws errors, respond strictly with 'FAIL' followed by error details."
    )

    runMessages = [
        SystemMessage(content=runPretext),
        *state["messages"],
        HumanMessage(content=f"Workspace files: [{filesStr}]. Install all required dependencies and execute or import the main entrypoint file directly.")
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
            runMessages.extend([
                testerResponse,
                HumanMessage(content="You did NOT use any tool calls. You MUST use executeCommand to install dependencies and run the main file.")
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
    print(f"\n[Batch Verification] Verifying {len(batchTasks)} completed coder task(s): {taskNames}")
    summaryText = "\n".join([f"- Task '{getattr(t, 'name', t.id)}': {res.get('coderMessage', '')}" for t, res in zip(batchTasks, coderResults)])
    combinedTools = sum([res.get("toolResults", []) for res in coderResults], [])

    initialState = {
        "messages": [HumanMessage(content=f"Verify batch tasks: {taskNames}\nCoder Summaries:\n{summaryText}")],
        "instruction": f"Batch Verification: {taskNames}",
        "taskContext": summaryText,
        "context": f"Files Created/Edited: {combinedTools}",
        "coderMessage": summaryText,
        "toolResults": combinedTools,
        "feedback": "",
        "iteration": 0,
        "success": False
    }

    finalState = evalWorkflow.invoke(initialState)
    if finalState.get("success"):
        return True, "Batch verified successfully."
    return False, finalState.get("feedback", "Batch evaluation failed.")

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
            promptOutput = promptAgent.process(query)

            plannerAgent = PlannerAgent()
            dagPlan = plannerAgent.plan(promptOutput)

            # HITL gate: let the user approve or edit tasks before execution
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
            scheduler = Scheduler(dag, query)
            asyncio.run(scheduler.run())