import json
import asyncio
import threading
from typing import Any, Optional
from pathlib import Path
from concurrent.futures import Future
from pydantic import BaseModel, create_model
from langchain_core.tools import BaseTool
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

backgroundLoop = asyncio.new_event_loop()
backgroundThread = threading.Thread(target=backgroundLoop.run_forever, daemon=True)
backgroundThread.start()

class McpWorker:
    def __init__(self, params: StdioServerParameters):
        self.params = params
        self.queue = None
        self.tools = []
        self.isReady = threading.Event()
        asyncio.run_coroutine_threadsafe(self.runLoop(), backgroundLoop)
        self.isReady.wait(timeout=10)

    async def runLoop(self):
        self.queue = asyncio.Queue()
        try:
            async with stdio_client(self.params) as (readStream, writeStream):
                async with ClientSession(readStream, writeStream) as session:
                    await session.initialize()
                    toolsRes = await session.list_tools()
                    self.tools = toolsRes.tools
                    self.isReady.set()
                    while True:
                        queueItem = await self.queue.get()
                        if queueItem is None:
                            break
                        toolName, toolArgs, completionFuture = queueItem
                        try:
                            callRes = await session.call_tool(toolName, toolArgs)
                            completionFuture.set_result(callRes)
                        except Exception as errVal:
                            completionFuture.set_exception(errVal)
        except Exception:
            self.isReady.set()

    def call(self, toolName: str, toolArgs: dict) -> Any:
        if not self.queue:
            return "Error: MCP worker process is not responding."
        callFuture = Future()
        asyncio.run_coroutine_threadsafe(self.queue.put((toolName, toolArgs, callFuture)), backgroundLoop)
        try:
            return callFuture.result(timeout=30)
        except Exception as errVal:
            return f"Error executing tool '{toolName}': {str(errVal)}"

class DynamicMcpTool(BaseTool):
    name: str
    description: str
    worker: Any
    rawName: str
    args_schema: Optional[type[BaseModel]] = None

    def _run(self, **kwargs) -> str:
        res = self.worker.call(self.rawName, kwargs)
        if hasattr(res, "content") and res.content and hasattr(res.content[0], "text"):
            return res.content[0].text
        return str(res)

def schemaToModel(modelName: str, schema: dict):
    typeMap = {
        "string": str,
        "integer": int,
        "boolean": bool,
        "number": float,
        "array": list,
        "object": dict
    }
    fields = {}
    requiredList = schema.get("required", [])
    for propName, propData in schema.get("properties", {}).items():
        propType = typeMap.get(propData.get("type", ""), Any)
        defaultVal = propData.get("default", ... if propName in requiredList else None)
        fields[propName] = (propType, defaultVal)
    if not fields:
        return None
    try:
        return create_model(modelName, **fields)
    except Exception:
        return None

_cachedMcpTools = []

def loadMcpTools() -> list[BaseTool]:
    global _cachedMcpTools
    if _cachedMcpTools:
        return _cachedMcpTools

    baseDir = Path(__file__).resolve().parent.parent
    configPath = baseDir / "mcp_config.json"
    if not configPath.exists():
        return []

    try:
        with open(configPath, "r", encoding="utf-8") as f:
            configData = json.load(f)
    except Exception:
        return []

    serverDict = configData.get("mcpServers", {})
    allTools = []

    for serverName, serverConfig in serverDict.items():
        cmdRaw = serverConfig.get("command", "")
        if not cmdRaw:
            continue
        cmdPath = (baseDir / cmdRaw).resolve() if not Path(cmdRaw).is_absolute() and (baseDir / cmdRaw).exists() else cmdRaw
        rawArgs = serverConfig.get("args", [])
        resolvedArgs = []
        for arg in rawArgs:
            resolvedArgPath = (baseDir / arg).resolve()
            if not Path(arg).is_absolute() and resolvedArgPath.exists():
                resolvedArgs.append(str(resolvedArgPath))
            else:
                resolvedArgs.append(arg)

        params = StdioServerParameters(
            command=str(cmdPath),
            args=resolvedArgs,
            env=serverConfig.get("env"),
            cwd=str((baseDir / "work").resolve())
        )

        worker = McpWorker(params)
        for t in worker.tools:
            argModel = schemaToModel(f"{serverName}_{t.name}Args", t.input_schema) if t.input_schema else None
            toolInstance = DynamicMcpTool(
                name=f"{serverName}_{t.name}",
                description=t.description or f"MCP tool {t.name} from {serverName}",
                worker=worker,
                rawName=t.name,
                args_schema=argModel
            )
            allTools.append(toolInstance)

    _cachedMcpTools = allTools
    return _cachedMcpTools

def getMcpTools() -> list[BaseTool]:
    return loadMcpTools()
