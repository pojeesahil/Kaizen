import time
from langchain.agents import create_agent 
from core.config import llm
from core.tools import tools
from rag.rag import indexWorkspace, getContext
import asyncio
from agents.planner import Planner
import asyncio
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

def runAgent(instruction, taskContext=""):
    context = getContext(instruction)
    
    maxIters = 4
    currentFeedback = "No feedback yet. This is your first attempt."
    
    for i in range(maxIters):
        time.sleep(2)
        print(f"\nCoder iteration {i+1}")
        coderPretext = (
            "You are a senior software engineer with tools to modify the workspace.\n"
            "Write production-grade code that looks authentic and handcrafted by an experienced developer:\n"
            "- Write clean, idiomatic, and concise code without AI boilerplate or generic templates.\n"
            "- Avoid robotic/redundant comments explaining obvious code lines. Only comment complex logic or business decisions.\n"
            "- Use natural, domain-specific variable and function names (avoid generic names like `temp_data_dict` or `process_item_obj`).\n"
            "- Maintain clean modular structure, proper error handling, and standard formatting.\n\n"
            f"Workspace Context:\n{context}\n\n"
            f"Prerequisite Tasks Context:\n{taskContext if taskContext else 'None'}\n\n"
            f"Critic/Tester Feedback to address:\n{currentFeedback}"
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
        
        if toolResults:
            print("Reindexing workspace after code modifications...")
            indexWorkspace()
        
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
        
        criticToolResults = executeToolCalls(criticResponse, tools)
        for tr in criticToolResults:
            print(tr)

        if criticToolResults:
            criticResponse = criticAgent.invoke({
                "messages": [
                    {"role": "user", "content": criticInstruction},
                    {"role": "assistant", "content": extractText(criticResponse["messages"][-1].content)},
                    {"role": "user", "content": "File inspection results:\n" + "\n".join(criticToolResults) + "\n\nEvaluate the file contents above. Respond with PASS or FAIL."}
                ]
            })

        criticMessage = extractText(criticResponse["messages"][-1].content)
        print("Critic output:", criticMessage)
        
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
            f"Coder Output / Changes: {coderMessage}\n"
            f"Coder Tool Execution Results: {toolResults}\n"
            f"Critic Evaluation: {criticMessage}\n\n"
            "Use the executeCommand tool to run the created/modified files to verify functionality."
        )
        
        testerResponse = testerAgent.invoke({
            "messages": [{"role": "user", "content": testerInstruction}]
        })
        
        testerToolResults = executeToolCalls(testerResponse, tools)
        for tr in testerToolResults:
            print(tr)

        if testerToolResults:
            testerResponse = testerAgent.invoke({
                "messages": [
                    {"role": "user", "content": testerInstruction},
                    {"role": "assistant", "content": extractText(testerResponse["messages"][-1].content)},
                    {"role": "user", "content": "Terminal execution output:\n" + "\n".join(testerToolResults) + "\n\nEvaluate the actual terminal execution output above. Respond strictly with PASS or FAIL followed by details if failed."}
                ]
            })
        
        testerMessage = extractText(testerResponse["messages"][-1].content)
        print("Tester output:", testerMessage)
        
        if testerMessage.strip().upper().startswith("PASS"):
            print("\nProcess finished successfully.")
            return True, coderMessage
        else:
            currentFeedback = f"Tester Execution Failed:\n{testerMessage}"
            
        if i == maxIters - 1:
            print("\nReached max iterations.")
    print(" ")
    return False, currentFeedback

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
            promptAgent = PromptAgent()
            enhancedPrompt = promptAgent.run(query)
            enhancedRequest = enhancedPrompt.get("enhanced_request", query)
            
            planner = Planner()
            asyncio.run(planner.run(enhancedRequest))