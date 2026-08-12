import os
import re
os.environ["OLLAMA_NUM_PARALLEL"] = "4"

import time
import json
import asyncio
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage
from core.config import llm, get_llm
from core.tools import tools, createFile, editFile, deleteResource, readFile
from rag.rag import indexWorkspace, getContext
from agents.prompt import PromptAgent
from agents.planneragent import PlannerAgent
from agents.dag import DAG
from agents.scheduler import Scheduler

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

def executeToolCalls(response, tools_list):
    toolMap = {t.name: t for t in tools_list}
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
            try:
                data, end_offset = decoder.raw_decode(text[start:])
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
                idx = start + max(end_offset, 1)
            except Exception:
                idx = start + 1
    return executed

coderTools = [createFile, editFile, deleteResource, readFile]
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
        "You are an autonomous senior software engineer with workspace tools.\n\n"
        "CRITICAL TOOL RULES:\n"
        "1. You MUST use tool calls to write or modify files in the workspace.\n"
        "2. DO NOT respond with markdown code blocks (```python ... ```) or conversational explanations.\n"
        "3. Output ONLY valid tool calls matching the tool format below.\n"
        "4. You can create or edit MULTIPLE files at once in a single task (outputting multiple tool calls in your response) if required to fulfill your task objective.\n\n"
        "Tool Call Format Examples:\n"
        'To create a file:\n{"name": "createFile", "arguments": {"path": "filename.ext", "content": "code..."}}\n\n'
        'To edit a file:\n{"name": "editFile", "arguments": {"path": "filename.ext", "newContent": "updated code..."}}\n\n'
        "Code Guidelines:\n"
        "- Write clean, idiomatic, production-grade code without generic templates or redundant comments.\n"
        "- Use natural, domain-specific variable and function names.\n"
        "- Maintain clean modular structure and standard formatting.\n"
        "- Focus strictly on writing application/source code files (e.g. main.py, app.js). Do NOT create or edit test files (e.g. test_*.py, *.test.js); unit tests are managed strictly by the Tester Agent.\n"
        "- Do NOT attempt to readFile non-existent files like requirements.txt. Create new implementation files directly using createFile.\n"
        "- Check Workspace Context first. If application code files ALREADY exist in workspace, do NOT overwrite or recreate them from scratch using createFile. Use editFile to apply specific modifications to fix feedback reported by QA.\n"
        "- For frontend tasks: use JavaScript fetch() or XMLHttpRequest to call backend API endpoints. Do NOT use <script src='/api/...'> tags. Display fetched data dynamically in the DOM.\n"
        "- For backend tasks: enable CORS (Access-Control-Allow-Origin header or flask-cors) so the frontend can call API endpoints.\n"
        "- For integration tasks: Connect files using editFile — e.g. for backend files, import modules, initialize DB/services, and call functions between them; for backend and frontend, serve HTML/static routes and enable CORS/API routes. Ensure all components work as a unified application.\n\n"
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
        
    return {
        "iteration": iteration,
        "coderMessage": coderMessage,
        "toolResults": toolResults,
        "messages": [coderResponse]
    }

def criticNode(state: AgentState) -> dict:
    print(f"\nCritic iteration {state['iteration']}")
    criticPretext = (
        "You are an expert Code Critic. Verify the code changes logically and structurally.\n"
        "IMPORTANT RULES:\n"
        "- Updating or modifying existing files (such as app.py or index.html) during integration tasks is EXPECTED and CORRECT. Do NOT flag this as creating duplicate files.\n"
        "- Only respond with FAIL if there are actual code syntax errors, missing routes, or broken functionality.\n"
        "If the work looks good statically, respond starting strictly with 'PASS'.\n"
        "If there are bugs, respond starting strictly with 'FAIL' followed by what needs to be fixed."
    )
    criticInstruction = (
        f"Original Instruction: {state['instruction']}\n"
        f"Coder claims to have done: {state.get('coderMessage', '')}\n"
        f"Tool execution results: {state.get('toolResults', [])}\n\n"
        "Evaluate ONLY the newly generated code changes above. Respond starting strictly with PASS or FAIL."
    )
    
    criticResponse = streamInvoke(agentModel, [SystemMessage(content=criticPretext), HumanMessage(content=criticInstruction)])
    criticMessage = extractText(criticResponse.content)
    
    isPass = criticMessage.strip().upper().startswith("PASS")
    return {
        "messages": [criticResponse],
        "feedback": f"Critic Feedback:\n{criticMessage}" if not isPass else state["feedback"]
    }

def testerNode(state: AgentState) -> dict:
    print(f"\nTester iteration {state['iteration']}")
    
    
    # genPretext = (
    #     "You are an experienced QA engineer.\n"
    #     "Review the codebase and recent modifications.\n"
    #     "- If automated unit tests do not exist or require updating for the new code, generate or modify test files (e.g. test_*.py, *Test.java, *.test.js) using createFile or editFile.\n"
    #     "- For documentation or static HTML/CSS where unit tests do not apply, respond strictly with STATIC_ONLY."
    # )
    # genPrompt = (
    #     f"Instruction: {state['instruction']}\n"
    #     f"Coder changes: {state.get('coderMessage', '')}\n"
    #     f"Workspace files and context:\n{state.get('context', '')}\n\n"
    #     "Generate or update required unit tests now."
    # )
    # genResponse = streamInvoke(agentModel, [SystemMessage(content=genPretext)] + state["messages"] + [HumanMessage(content=genPrompt)])
    # genTools = executeToolCalls(genResponse, tools)
    # for tr in genTools:
    #     print(f"{tr}\n")
        
    runPretext = (
        "You are responsible for verifying code execution.\n"
        "CRITICAL RULES:\n"
        "- Output executeCommand tool calls to install required imports and run the main application file.\n"
        "- Execution MUST be non-interactive. Do NOT run commands that wait for interactive stdin input.\n"
        "- If execution completes with Exit Code: 0 and no errors, respond strictly with 'PASS'.\n"
        "- If execution crashes, times out, or throws errors, respond strictly with 'FAIL' followed by error details."
    )
    
    runMessages = [
        SystemMessage(content=runPretext),
        *state["messages"],
        HumanMessage(content="Install all required dependencies/imports and execute the main file in non-interactive mode now (e.g. work/main.py, work/main.cpp, main.py).")
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
        has_zero_exit = "Exit Code: 0" in testOutput
        has_error = "Traceback" in testOutput or "Error:" in testOutput or "Exception:" in testOutput

        if runTools and has_zero_exit and not has_error:
            testerMessage = "PASS"
            print("\n[Auto-detected] Main file executed successfully (Exit Code: 0).")
            break

        if not runTools:
            runMessages.extend([
                testerResponse,
                HumanMessage(content="You did NOT use any tool calls. You MUST use executeCommand to install dependencies and run the main file. Output tool calls, not plain text instructions.")
            ])
            continue
            
        runMessages.extend([
            testerResponse,
            HumanMessage(content="Terminal output:\n" + "\n".join(runTools) + "\n\nEvaluate the output. If missing imports caused errors, install them and re-run. If execution passed cleanly, respond strictly with PASS. If code logic bugs remain, respond with FAIL and details.")
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
    finalState = workflow.invoke(initialState)
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
            
            dag = DAG()
            for t in dagPlan.taskNodes:
                t.name = getattr(t, "objective", t.id)
                t.agent = "Coding"
                dag.add_task(t)
            dag.build()
            
            print("\nGenerated Tasks:")
            for task in dagPlan.taskNodes:
                deps = ", ".join(task.dependencies) if task.dependencies else "none"
                print(f" - [{task.priority}] {task.objective} (deps: {deps})")
                
            print("\nExecution Order:")
            print(dag.topological_sort())
            
            indexWorkspace()
            scheduler = Scheduler(dag, query)
            asyncio.run(scheduler.run())