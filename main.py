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

    instText = (state["instruction"] + " " + state.get("taskContext", "") + " " + state.get("feedback", "")).lower()
    filesInWork = list(WORK_DIR.glob("*")) if WORK_DIR.exists() else []
    exts = {f.suffix.lower() for f in filesInWork if f.is_file()}

    if any(e in (".js", ".ts", ".jsx", ".tsx") for e in exts) or any(w in instText for w in ("node", "npm", "express", "javascript", "js", "react", "next")):
        langGuideline = (
            "- TECH STACK: Node.js / JavaScript. Write every file in pure JS/Node.js CJS syntax using require() and module.exports.\n"
            "- CRITICAL: NEVER use Python syntax. Do NOT write 'from x import y', '@app.route', 'def ', or 'if __name__' anywhere in a .js file.\n"
            "- CRITICAL: Every file that imports another must use require() with the correct relative path (e.g. const controller = require('./controller');).\n"
            "- CRITICAL: Every exported handler or router must be explicitly linked via require() in the parent file. No file should be left disconnected.\n"
            "- CRITICAL: Do NOT hardcode secrets, passwords, emails, API keys, or URIs. Read all configurable values from process.env with a safe fallback (e.g. process.env.PORT || 3000).\n"
            "- CRITICAL: Use dotenv at the top of the entrypoint file: require('dotenv').config();\n"
            "- All route handlers must be fully implemented functions, not empty stubs or TODO comments.\n"
        )
    elif any(e == ".go" for e in exts) or "go" in instText or "golang" in instText:
        langGuideline = (
            "- TECH STACK: Go (Golang). Use standard Go syntax, package declarations, and func main().\n"
            "- CRITICAL: Do NOT mix Python or JavaScript syntax in Go files.\n"
            "- CRITICAL: Do NOT hardcode configurable values. Use os.Getenv() with fallback defaults.\n"
        )
    elif any(e in (".c", ".cpp", ".cc", ".h", ".hpp") for e in exts) or any(w in instText for w in ("c++", "cpp", "gcc", "g++", "c language")):
        langGuideline = (
            "- TECH STACK: C / C++. Use standard C/C++ includes (#include <...>), header files, and int main().\n"
            "- CRITICAL: Do NOT hardcode configurable values. Use #define constants or command-line arguments.\n"
        )
    elif any(e == ".java" for e in exts) or "java" in instText:
        langGuideline = (
            "- TECH STACK: Java. Use public class matching filename and public static void main(String[] args).\n"
            "- CRITICAL: Do NOT hardcode configurable values. Read from System.getenv() or properties files.\n"
        )
    elif any(e in (".html", ".css") for e in exts) or any(w in instText for w in ("html", "css", "website", "web page", "frontend")):
        langGuideline = (
            "- TECH STACK: HTML / CSS / JS. Create semantic HTML5, CSS stylesheets, and client-side JS.\n"
            "- CRITICAL: Do NOT hardcode environment-specific URLs or API keys in HTML/JS. Use configurable constants at the top of JS files.\n"
        )
    else:
        langGuideline = (
            "- TECH STACK: Python. Use standard Python 3 syntax. Place 'if __name__ == \"__main__\": main()' at the very bottom of entrypoint files.\n"
            "- CRITICAL: Do NOT hardcode configurable values. Use os.environ.get() with fallback defaults.\n"
        )

    taskContext = state.get("taskContext", "") or "None"
    feedbackContext = state.get("feedback", "")
    workspaceContext = state.get("context", "")

    coderPretext = f"""You are an autonomous software engineer operating on a real multi-file workspace using AST-level workspace tools.
Your goal is NOT merely to generate files. Your goal is to produce a COMPLETE, CONNECTED, BUILDABLE, and RUNNABLE project.

CRITICAL TOOL RULES:
1. Output ONLY valid tool calls matching the available tool schemas. Do NOT output markdown, explanations, or plain text.
2. Use 'createFile' only when a file does not already exist.
3. Use 'editFile' when modifying an existing file while preserving its existing imports and unrelated code.
4. Use 'upsertFunction' to create or replace a function without unnecessarily modifying unrelated code.
5. Use 'upsertClass' to create or replace a class without unnecessarily modifying unrelated code.
6. Use 'addImport' whenever a file requires an import that does not already exist.
7. Use 'appendToFile' only when code must be appended at the appropriate location.
8. Never assume that creating a file automatically connects it to the rest of the project.
9. Never assume that an import exists merely because the target file exists.
10. Never overwrite unrelated existing code.

IMPLEMENTATION RULES:
1. Understand the existing workspace before making changes.
2. Reuse existing files, functions, classes, utilities, components, services, and configuration whenever appropriate.
3. Do not create duplicate implementations when an existing implementation can be reused.
4. Follow the existing project's framework conventions, directory structure, naming conventions, entrypoints, configuration, and dependency management.
5. Do not invent framework-specific structure when an existing project structure is already present.

DEPENDENCY AND LINKAGE RULES:
1. Every external symbol referenced by generated or modified code must be classified as one of:
   - locally defined symbol
   - imported workspace symbol
   - installed package/library
   - language/framework built-in
   - environment/global symbol
2. For every workspace symbol used by a file:
   - Find the actual file where the symbol is defined.
   - Verify that the target file exists.
   - Verify that the target file exports/provides the required symbol.
   - Verify that the current file imports the symbol.
   - If the import is missing, use 'addImport'.
   - Verify that the import path correctly resolves from the current file.
3. Never assume relative paths. Resolve them from the actual location of the importing file.
4. Never import a symbol from a file that does not export it.
5. Never create an import for a symbol that is not actually used.
6. Do not create unnecessary duplicate imports.
7. If a new file depends on an existing file, explicitly connect the two through the correct import/require mechanism.
8. If modifying a file introduces a new dependency, immediately update its imports.
9. If modifying or deleting an export, inspect files that depend on that export and repair broken references.
10. Do not consider a task complete while unresolved workspace symbols remain.

IMPORT RULES:
1. Imports/requires must be placed according to the language/framework convention.
2. Every imported workspace module must resolve to an existing file.
3. Every imported named symbol must exist in the target module's exports.
4. Preserve valid existing imports.
5. Do not blindly import every generated file.
6. Only import modules whose symbols are actually required.
7. If an import path is ambiguous, inspect the workspace rather than guessing.

PROJECT CONNECTIVITY:
1. Identify the project's actual entrypoints where possible.
2. Ensure newly created functionality is reachable from the appropriate entrypoint, route, component, service, command, or application flow.
3. Do NOT assume every file requires an incoming import. Entry points, configuration files, tests, scripts, generated files, and framework-discovered modules may legitimately have no incoming imports.
4. Do not create orphaned application modules that are intended to participate in the application but are unreachable from the relevant application flow.
5. Preserve framework-specific conventions such as automatic route discovery, dependency injection, plugin registration, configuration discovery, and file-based routing.

CONFIGURATION AND DEPENDENCY RULES:
1. Inspect package/dependency configuration before importing external packages.
2. Do not import a package that is not available in the project unless adding the dependency is explicitly required and supported by the available tools.
3. Check package manifests and project configuration when introducing dependencies.
4. Keep framework, runtime, compiler, and package versions compatible with the existing project.
5. Verify environment variables used by the generated code are consistently named and configured.
6. Never hardcode secrets, API keys, passwords, or credentials.
7. Do not invent configuration values when the project already defines them elsewhere.

CODE GUIDELINES:
{langGuideline}
- NAMING: Use strict camelCase for function names, method names, and variables where supported by the language. Follow language/framework conventions when camelCase is not appropriate.
- NO COMMENTS: Do not include comments, docstrings, or TODO placeholders in generated code unless explicitly required by the task.
- NO STUBS: Every generated function, class method, route handler, and component must contain complete implementation logic.
- NO HARDCODED SECRETS: Never hardcode passwords, secrets, API keys, credentials, or private tokens.
- Do not unnecessarily rewrite unrelated working code.

MANDATORY WORKFLOW:

PHASE 1 — UNDERSTAND:
1. Inspect the relevant workspace files.
2. Determine the existing project structure.
3. Identify relevant entrypoints.
4. Identify existing implementations that can be reused.
5. Identify relevant imports, exports, routes, APIs, services, models, configuration, and dependencies.

PHASE 2 — IMPLEMENT:
1. Create or modify only the files required for the task.
2. Use the appropriate AST-level tool for each modification.
3. Preserve unrelated working code.

PHASE 3 — DEPENDENCY LINKAGE AUDIT:
After EVERY file modification:
1. Inspect the modified code.
2. Identify every external symbol it references.
3. Resolve each workspace symbol to its defining file.
4. Verify the required export exists.
5. Verify the import exists.
6. Add missing imports using 'addImport'.
7. Verify import paths resolve correctly.
8. Check whether the modification broke existing imports or exports.
9. Repeat recursively for newly connected modules when necessary.

PHASE 4 — PROJECT CONSISTENCY:
Check:
1. File paths.
2. Imports.
3. Exports.
4. Relative import paths.
5. Function/class names.
6. Duplicate symbols.
7. Missing symbols.
8. Missing dependencies.
9. Configuration references.
10. Environment variable names.
11. Entry-point connectivity.
12. Framework-specific conventions.

PHASE 5 — VALIDATION:
Before considering the task complete:
1. Validate the modified files using available AST/workspace information.
2. Check for unresolved imports.
3. Check for unresolved symbols.
4. Check that imported symbols are actually exported.
5. Check that referenced workspace files exist.
6. Check for obvious circular dependency problems introduced by the changes.
7. Build or run the project when the available tools support it.
8. If build/runtime/test feedback reports an error, diagnose the root cause and repair it.
9. Re-run validation after repairs.

COMPLETION REQUIREMENT:
The task is NOT complete merely because the requested files were created.

The task is complete only when:
- required files exist
- required symbols exist
- imports resolve
- exports resolve
- workspace dependencies are connected
- configuration is consistent
- the relevant application flow reaches the new functionality
- no obvious unresolved symbols/imports remain
- build/tests/runtime validation passes when available

Never stop at 'code generated'. Continue until the generated code is properly connected and validated.

Workspace Context:
{workspaceContext}

Prerequisite Tasks Context:
{taskContext}

Critic/Tester Feedback:
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
            # Auto-fallback: if tester produced no tool call, run the entrypoint directly
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