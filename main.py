import time
from langchain.agents import create_agent 
from core.config import llm
from core.tools import tools
from rag.rag import indexWorkspace, getContext

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

import json

def executeToolCalls(response, tools_list):
    toolMap = {t.name: t for t in tools_list}
    executed = []
    lastMsg = response["messages"][-1]
    if hasattr(lastMsg, "tool_calls") and lastMsg.tool_calls:
        for tc in lastMsg.tool_calls:
            tname = tc.get("name")
            targs = tc.get("args", {})
            if tname in toolMap:
                res = toolMap[tname].invoke(targs)
                executed.append(f"Tool {tname} executed: {res}")
    if not executed:
        text = extractText(lastMsg.content).strip()
        if "{" in text and "}" in text:
            try:
                start = text.find("{")
                end = text.rfind("}") + 1
                data = json.loads(text[start:end])
                tname = data.get("name")
                targs = data.get("arguments") or data.get("args") or {}
                if tname in toolMap:
                    res = toolMap[tname].invoke(targs)
                    executed.append(f"Tool {tname} executed: {res}")
            except Exception:
                pass
    return executed

def runAgent(instruction):
    context = getContext(instruction)
    
    maxIters = 4
    currentFeedback = "No feedback yet. This is your first attempt."
    
    for i in range(maxIters):
        time.sleep(2)
        print(f"\nCoder iteration {i+1}")
        coderPretext = (
            "You are an expert AI coding assistant with tools to modify the workspace.\n"
            "Analyze the current workspace context and critic/tester feedback. Use your tools to make changes directly.\n"
            "make no mistake\n"
            f"Context:\n{context}\n\n"
            f"Feedback to address:\n{currentFeedback}"
        )
        
        coderAgent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=coderPretext
        )
        coderResponse = coderAgent.invoke({
            "messages": [
                {"role": "user", "content": instruction}
            ]
        })
        
        coderMessage = extractText(coderResponse["messages"][-1].content)
        print("Coder output:", coderMessage)
        
        toolResults = executeToolCalls(coderResponse, tools)
        for tr in toolResults:
            print(tr)
        
        print(f"\nCritic iteration {i+1}")
        criticPretext = (
            "You are an expert Code Critic. Verify the code changes logically and structurally.\n"
            "You can use the readFile tool to inspect the file contents.\n"
            "If the work looks good statically, respond starting strictly with 'PASS'.\n"
            "If there are bugs, respond starting strictly with 'FAIL' followed by what needs to be fixed."
        )
        
        criticAgent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=criticPretext
        )
        criticInstruction = (
            f"Original Instruction: {instruction}\n"
            f"Coder claims to have done this: {coderMessage}\n"
            f"Tool execution results: {toolResults}\n"
            "Evaluate the workspace to see if it meets the requirements."
        )
        
        criticResponse = criticAgent.invoke({
            "messages": [{"role": "user", "content": criticInstruction}]
        })
        
        criticMessage = extractText(criticResponse["messages"][-1].content)
        print("Critic output:", criticMessage)
        
        criticToolResults = executeToolCalls(criticResponse, tools)
        for tr in criticToolResults:
            print(tr)
        
        if not criticMessage.strip().upper().startswith("PASS"):
            currentFeedback = f"Critic Feedback:\n{criticMessage}"
            continue 
            
        print(f"\nTester iteration {i+1}")
        testerPretext = (
            "You are a strict QA Automation Engineer.\n"
            "Your job is to PROVE the code works by running it. Use the executeCommand tool to run the code, tests, or scripts.\n"
            "If the terminal output is successful and does what was asked, respond starting strictly with 'PASS'.\n"
            "If the execution fails, throws an error, or behavior is wrong, respond starting strictly with 'FAIL' followed by the terminal output and error details."
        )
        
        testerAgent = create_agent(
            model=llm,
            tools=tools,
            system_prompt=testerPretext
        )
        
        testerInstruction = (
            f"Original Instruction: {instruction}\n"
            "The code has been written and passed visual review. Now, execute the relevant files or tests to ensure it runs without crashing."
        )
        
        testerResponse = testerAgent.invoke({
            "messages": [{"role": "user", "content": testerInstruction}]
        })
        
        testerMessage = extractText(testerResponse["messages"][-1].content)
        print("Tester output:", testerMessage)
        
        testerToolResults = executeToolCalls(testerResponse, tools)
        for tr in testerToolResults:
            print(tr)
        
        if testerMessage.strip().upper().startswith("PASS"):
            print("\nProcess finished successfully.")
            return True
        else:
            currentFeedback = f"Tester Execution Failed:\n{testerMessage}"
            
        if i == maxIters - 1:
            print("\nReached max iterations.")
    print(" ")
    return False

if __name__ == "__main__":
    print("Type 'index' for reindexing or 'exit' to quit.")
    while True:
        query = input("Instruction: ")
        q = query.strip().lower()
        if q == "exit":
            break
        if q == "index":
            indexWorkspace()
            print("Reindexed the workspace")
        elif q:
            import asyncio
            from agents.planner import Planner
            planner = Planner()
            asyncio.run(planner.run(query))