import os
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
        "3. Output ONLY valid tool calls matching the tool format below.\n\n"
        "Tool Call Format Examples:\n"
        'To create a file:\n{"name": "createFile", "arguments": {"path": "filename.ext", "content": "code..."}}\n\n'
        'To edit a file:\n{"name": "editFile", "arguments": {"path": "filename.ext", "newContent": "updated code..."}}\n\n'
        "Code Guidelines:\n"
        "- Write clean, idiomatic, production-grade code without generic templates or redundant comments.\n"
        "- Use natural, domain-specific variable and function names.\n"
        "- Maintain clean modular structure and standard formatting.\n"
        "- Focus strictly on writing application/source code files (e.g. main.py, app.js). Do NOT create or edit test files (e.g. test_*.py, *.test.js); unit tests are managed strictly by the Tester Agent.\n"
        "- Do NOT attempt to readFile non-existent files like requirements.txt. Create new implementation files directly using createFile.\n\n"
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
    
    genPretext = (
        "You are an experienced QA engineer.\n"
        "Review the codebase and recent modifications.\n"
        "- If automated unit tests do not exist or require updating for the new code, generate or modify test files (e.g. test_*.py, *Test.java, *.test.js) using createFile or editFile.\n"
        "- For documentation or static HTML/CSS where unit tests do not apply, respond strictly with STATIC_ONLY."
    )
    genPrompt = (
        f"Instruction: {state['instruction']}\n"
        f"Coder changes: {state.get('coderMessage', '')}\n"
        f"Workspace files and context:\n{state.get('context', '')}\n\n"
        "Generate or update required unit tests now."
    )
    
    genResponse = streamInvoke(agentModel, [SystemMessage(content=genPretext)] + state["messages"] + [HumanMessage(content=genPrompt)])
    genTools = executeToolCalls(genResponse, tools)
    for tr in genTools:
        print(f"{tr}\n")
        
    runPretext = (
        "You are responsible for running test suites and verifying functionality.\n"
        "- Run the appropriate tests in terminal using executeCommand (e.g. pytest, python -m unittest, npm test, or javac/java).\n"
        "- For Node.js test files using BDD framework functions (describe/it), run them using npx jest, npx mocha, or node --test.\n"
        "- Only use build tools (like mvn or gradle) if project config files like pom.xml exist. For standalone Java files, compile and run directly using javac and java.\n"
        "- If execution fails due to missing modules or third-party dependencies, install the required library using executeCommand and re-run the tests.\n"
        "- When all tests pass cleanly without errors, respond starting strictly with 'PASS'.\n"
        "- If functional assertions or code bugs persist, respond starting strictly with 'FAIL' followed by what failed."
    )
    
    runMessages = [
        SystemMessage(content=runPretext),
        *state["messages"],
        genResponse,
        HumanMessage(content="Execute the test suite now. Automatically install any missing dependencies if import errors occur.")
    ]
    
    testerResponse = None
    testerMessage = ""
    
    for attempt in range(1, 4):
        if attempt > 1:
            print(f"\nTester retry {attempt}/3")
        testerResponse = streamInvoke(agentModel, runMessages)
        testerMessage = extractText(testerResponse.content)
        
        if testerMessage.strip().upper().startswith("PASS") or testerMessage.strip().upper().startswith("FAIL"):
            break
            
        runTools = executeToolCalls(testerResponse, tools)
        for tr in runTools:
            print(tr, "\n")
            
        if not runTools:
            break
            
        runMessages.extend([
            testerResponse,
            HumanMessage(content="Terminal output:\n" + "\n".join(runTools) + "\n\nEvaluate the output. If missing imports caused errors, install them and re-test. If tests passed cleanly, respond strictly with PASS. If code logic bugs remain, respond with FAIL and details.")
        ])
            
    isPass = testerMessage.strip().upper().startswith("PASS")
    if isPass:
        print("\nProcess finished successfully.\n")
        
    return {
        "messages": [testerResponse] if testerResponse else [genResponse],
        "feedback": state["feedback"] if isPass else f"Tester Execution Failed:\n{testerMessage}",
        "success": isPass
    }

def routeCritic(state: AgentState) -> str:
    lastMessage = extractText(state["messages"][-1].content)
    if not lastMessage.strip().upper().startswith("PASS"):
        return "coder" if state["iteration"] < 4 else END
    return "tester"

def routeTester(state: AgentState) -> str:
    if state["success"] or state["iteration"] >= 4:
        return END
    return "coder"

builder = StateGraph(AgentState)
builder.add_node("coder", coderNode)
builder.add_node("critic", criticNode)
builder.add_node("tester", testerNode)

builder.add_edge(START, "coder")
builder.add_edge("coder", "critic")
builder.add_conditional_edges("critic", routeCritic, {"tester": "tester", "coder": "coder", END: END})
builder.add_conditional_edges("tester", routeTester, {"coder": "coder", END: END})

workflow = builder.compile()

def runCoder(instruction, taskContext=""):
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
    return coderNode(initialState)

def runBatchEval(batchTasks, coderResults):
    taskNames = ", ".join([getattr(t, "name", getattr(t, "objective", t.id)) for t in batchTasks])
    print(f"\n[Batch Verification] Verifying {len(batchTasks)} completed coder task(s): {taskNames}")
    
    summaryText = "\n".join([f"- Task '{getattr(t, 'name', t.id)}': {res.get('coderMessage', '')}" for t, res in zip(batchTasks, coderResults)])
    combinedTools = sum([res.get("toolResults", []) for res in coderResults], [])
    
    print("\n--- Single Critic Agent Verification ---")
    criticPretext = (
        "You are an expert Code Critic. Verify all code changes made across the batch tasks.\n"
        "If all work looks good statically, respond starting strictly with 'PASS'.\n"
        "If there are bugs, respond starting strictly with 'FAIL' followed by what needs to be fixed."
    )
    criticInstruction = (
        f"Tasks Evaluated: {taskNames}\n"
        f"Coder Summaries:\n{summaryText}\n"
        f"Files Created/Edited: {combinedTools}\n\n"
        "Evaluate ALL newly generated code changes above. Respond starting strictly with PASS or FAIL."
    )
    
    criticRes = streamInvoke(llm, [SystemMessage(content=criticPretext), HumanMessage(content=criticInstruction)])
    criticMessage = extractText(criticRes.content)
    
    if not criticMessage.strip().upper().startswith("PASS"):
        return False, f"Critic Feedback:\n{criticMessage}"
        
    print("\n--- Single Tester Agent Verification ---")
    testerPretext = (
        "You are an experienced QA Automation Engineer.\n"
        "- If automated unit tests do not exist or need updating for the new code, generate or modify test files using createFile or editFile.\n"
        "- Run the appropriate tests in terminal using executeCommand (e.g. pytest, python -m unittest, npm test, or javac/java).\n"
        "- If missing modules or third-party dependencies cause errors, install them using executeCommand and re-run tests.\n"
        "- When all tests pass cleanly, respond starting strictly with 'PASS'.\n"
        "- If assertions or code bugs persist, respond starting strictly with 'FAIL' followed by details."
    )
    testerInstruction = (
        f"Tasks Evaluated: {taskNames}\n"
        f"Batch Coder Changes:\n{summaryText}\n\n"
        "Generate/update required unit tests, run test suite, and verify functionality for all batch tasks."
    )
    
    testMsgs = [
        SystemMessage(content=testerPretext),
        HumanMessage(content=testerInstruction)
    ]
    
    testerMessage = ""
    for attempt in range(1, 4):
        if attempt > 1:
            print(f"\n[Batch Verification] Tester retry {attempt}/3")
        testerRes = streamInvoke(agentModel, testMsgs)
        testerMessage = extractText(testerRes.content)
        
        runTools = executeToolCalls(testerRes, tools)
        for tr in runTools:
            print(tr, "\n")
            
        if testerMessage.strip().upper().startswith("PASS"):
            break
        if not runTools:
            break
            
        testMsgs.extend([
            testerRes,
            HumanMessage(content="Terminal output:\n" + "\n".join(runTools) + "\n\nEvaluate output. If missing imports caused errors, install them and re-test. If tests passed cleanly, respond strictly with PASS. Otherwise FAIL.")
        ])
        
    isPass = testerMessage.strip().upper().startswith("PASS")
    if isPass:
        print("\nBatch Verification finished successfully.\n")
        return True, "Batch verified successfully."
        
    return False, f"Tester Execution Failed:\n{testerMessage}"

def runAgent(instruction, taskContext=""):
    print("Indexing workspace...")
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