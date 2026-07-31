import time
import json
import asyncio
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, SystemMessage
from core.config import llm
from core.tools import tools
from rag.rag import indexWorkspace, getContext
from agents.prompt import PromptAgent
from agents.planner import Planner

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

def executeToolCalls(response, tools_list):
    toolMap = {t.name: t for t in tools_list}
    executed = []
    if hasattr(response, "tool_calls") and response.tool_calls:
        for tc in response.tool_calls:
            tname = tc.get("name")
            targs = tc.get("args", {})
            if tname in toolMap:
                try:
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
                        res = toolMap[tname].invoke(targs)
                        executed.append(f"Tool {tname} executed: {res}")
                    except Exception as err:
                        executed.append(f"Tool {tname} execution error: {err}")
                idx = start + max(end_offset, 1)
            except Exception:
                idx = start + 1
    return executed

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
    print(f"\n--- Coder Iteration {iteration} ---")
    
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
        "- Maintain clean modular structure and standard formatting.\n\n"
        f"Workspace Context:\n{state['context']}\n\n"
        f"Prerequisite Tasks Context:\n{state['taskContext'] if state['taskContext'] else 'None'}\n\n"
        f"Critic/Tester Feedback to address:\n{state['feedback']}"
    )
    
    coderResponse = streamInvoke(agentModel, [SystemMessage(content=coderPretext)] + state["messages"])
    coderMessage = extractText(coderResponse.content)
    
    toolResults = executeToolCalls(coderResponse, tools)
    for tr in toolResults:
        print(f"{tr}\n")
        
    if toolResults:
        print("Reindexing workspace after code modifications...\n")
        indexWorkspace()
        
    return {
        "iteration": iteration,
        "coderMessage": coderMessage,
        "toolResults": toolResults,
        "messages": [coderResponse]
    }

def criticNode(state: AgentState) -> dict:
    print(f"\n--- Critic Iteration {state['iteration']} ---")
    criticPretext = (
        "You are an expert Code Critic. Verify the code changes logically and structurally.\n"
        "You can use the readFile tool to inspect the file contents.\n"
        "If the work looks good statically, respond starting strictly with 'PASS'.\n"
        "If there are bugs, respond starting strictly with 'FAIL' followed by what needs to be fixed."
    )
    criticInstruction = (
        f"Original Instruction: {state['instruction']}\n"
        f"Coder claims to have done: {state.get('coderMessage', '')}\n"
        f"Tool execution results: {state.get('toolResults', [])}\n"
        "Evaluate the workspace files. Respond starting strictly with PASS or FAIL."
    )
    
    criticResponse = streamInvoke(agentModel, [SystemMessage(content=criticPretext)] + state["messages"] + [HumanMessage(content=criticInstruction)])
    criticToolResults = executeToolCalls(criticResponse, tools)
    for tr in criticToolResults:
        print(f"{tr}\n")
        
    if criticToolResults:
        criticResponse = streamInvoke(agentModel, [
            SystemMessage(content=criticPretext),
            *state["messages"],
            criticResponse,
            HumanMessage(content="File inspection results:\n" + "\n".join(criticToolResults) + "\n\nEvaluate the file contents above. Respond with PASS or FAIL.")
        ])
        
    criticMessage = extractText(criticResponse.content)
    
    isPass = criticMessage.strip().upper().startswith("PASS")
    return {
        "messages": [criticResponse],
        "feedback": f"Critic Feedback:\n{criticMessage}" if not isPass else state["feedback"]
    }

def testerNode(state: AgentState) -> dict:
    print(f"\n--- Tester Iteration {state['iteration']} ---")
    testerPretext = (
        "You are a strict QA Automation Engineer.\n"
        "Your job is to verify that code works:\n"
        "- For runnable scripts, backend code, or tests: Use executeCommand to run them in the terminal.\n"
        "- For static files (HTML, CSS, JS, Markdown, JSON): If the files were created cleanly and passed visual review, respond starting strictly with 'PASS'.\n"
        "- If execution fails or throws runtime errors, respond starting strictly with 'FAIL' followed by error details."
    )
    testerInstruction = (
        f"Original Instruction: {state['instruction']}\n"
        f"Coder Output / Changes: {state.get('coderMessage', '')}\n"
        f"Tool Execution Results: {state.get('toolResults', [])}\n"
        f"Critic Evaluation: {state.get('criticMessage', '')}\n\n"
        "Evaluate the changes. If runnable scripts exist, run them using executeCommand. Respond strictly starting with PASS or FAIL."
    )
    
    testerResponse = streamInvoke(agentModel, [SystemMessage(content=testerPretext)] + state["messages"] + [HumanMessage(content=testerInstruction)])
    testerToolResults = executeToolCalls(testerResponse, tools)
    for tr in testerToolResults:
        print(f"{tr}\n")
        
    if testerToolResults:
        testerResponse = streamInvoke(agentModel, [
            SystemMessage(content=testerPretext),
            *state["messages"],
            testerResponse,
            HumanMessage(content="Terminal execution output:\n" + "\n".join(testerToolResults) + "\n\nEvaluate the actual terminal execution output above. Respond strictly with PASS or FAIL followed by details if failed.")
        ])
        
    testerMessage = extractText(testerResponse.content)
    
    isPass = testerMessage.strip().upper().startswith("PASS")
    if isPass:
        print("\nProcess finished successfully.\n")
        
    return {
        "messages": [testerResponse],
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

def runAgent(instruction, taskContext=""):
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
            enhancedPrompt = promptAgent.run(query)
            enhancedRequest = enhancedPrompt.get("enhanced_request", query)
            
            planner = Planner()
            asyncio.run(planner.run(enhancedRequest))