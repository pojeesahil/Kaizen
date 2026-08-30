import time
import uuid
import chromadb
from chromadb.utils import embedding_functions
from langchain_core.messages import SystemMessage, HumanMessage
from core.config import get_llm
from agents.prompt import parseLLMjson

class MemoryManager:
    def __init__(self, persistDir : str = "./chroma_db"):
        self.persistDir = persistDir
        self.client = chromadb.PersistentClient(path = persistDir)
        self.embedFn = embedding_functions.DefaultEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name = "agent_memory",
            embedding_function = self.embedFn
        )

    def searchMemory(self, query : str, topK : int = 5) -> list[dict]:
        count = self.collection.count()
        if count == 0:
            return []

        results = self.collection.query(
            query_texts = [query],
            n_results = min(topK, count)
        )

        records = []
        if results and results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                docId = results["ids"][0][i]
                docContent = results["documents"][0][i]
                metadata = results["metadatas"][0][i] or {}
                
                records.append({
                    "memoryId" : docId,
                    "content" : docContent,
                    "memoryType" : metadata.get("memoryType", "episodic"),
                    "importance" : float(metadata.get("importance", 0.5)),
                    "timestamp" : float(metadata.get("timestamp", time.time())),
                    "sourceAgent" : metadata.get("sourceAgent", "unknown"),
                    "task": metadata.get("task", "")
                })
        return records

    def deleteMemory(self, memoryId : str) -> None:
        self.collection.delete(ids = [memoryId])

    def updateMemory(self, memoryId : str, content : str, memoryType : str, importance : float, sourceAgent : str, task : str) -> None:
        self.collection.update(
            ids = [memoryId],
            documents = [content],
            metadatas = [{
                "memoryType" : memoryType,
                "importance" : importance,
                "timestamp" : time.time(),
                "sourceAgent" : sourceAgent,
                "task" : task
            }]
        )

    def saveMemory(self, content : str, memoryType : str, importance : float, sourceAgent : str, task : str) -> None:
        similarRecords = self.searchMemory(content, topK=3)
        
        normalizedContent = content.strip().lower()
        for r in similarRecords:
            words1 = set(normalizedContent.split())
            words2 = set(r["content"].strip().lower().split())
            intersection = words1.intersection(words2)
            union = words1.union(words2)
            similarity = len(intersection) / len(union) if union else 0.0
            
            if similarity > 0.85:
                return

        if not similarRecords:
            memoryId = f"mem-{uuid.uuid4().hex[:8]}"
            self.collection.add(
                ids = [memoryId],
                documents = [content],
                metadatas = [{
                    "memoryType" : memoryType,
                    "importance" : importance,
                    "timestamp" : time.time(),
                    "sourceAgent": sourceAgent,
                    "task": task
                }]
            )
            return

        existingMemoriesStr = ""
        for r in similarRecords:
            existingMemoriesStr += f"- ID: {r['memoryId']}\n  Content: {r['content']}\n  Type: {r['memoryType']}\n  Importance: {r['importance']}\n\n"

        consolidationPrompt = f"""You are a memory manager for an AI agent.
We want to save a new memory record:
Content: {content}
Type: {memoryType}
Importance: {importance}
Source Agent: {sourceAgent}
Task: {task}

Here are the most similar existing memories from the persistent store:
{existingMemoriesStr}

Analyze if the new memory is:
1. A duplicate (meaning it covers the same learning or fact).
2. A contradiction (meaning the new memory corrects, updates, or conflicts with the old memory).
3. Completely new and compatible.

Respond ONLY with a JSON object containing these keys:
- action: one of ["insert", "update", "skip"]
- targetId: the ID of the existing memory to update (only if action is "update")
- content: the consolidated content to write (if action is "update" or "insert"). If "update", merge the old and new memory if helpful, preferring the newer information if they contradict.
- importance: a refined importance score between 0.0 and 1.0.
- memoryType: the memory type (one of ["working", "episodic", "semantic", "procedural"]).
"""
        try:            
            llmInstance = get_llm(temperature = 0)
            llmResponse = llmInstance.invoke([
                SystemMessage(content = "You are a precise JSON response generator."),
                HumanMessage(content = consolidationPrompt)
            ])
            
            parsed = parseLLMjson(llmResponse.content)
            
            if parsed and isinstance(parsed, dict):
                action = parsed.get("action", "insert")
                targetId = parsed.get("targetId")
                consolidatedContent = parsed.get("content", content)
                consolidatedImportance = float(parsed.get("importance", importance))
                consolidatedType = parsed.get("memoryType", memoryType)

                if action == "skip":
                    return
                elif action == "update" and targetId:
                    self.updateMemory(
                        memoryId = targetId,
                        content = consolidatedContent,
                        memoryType = consolidatedType,
                        importance = consolidatedImportance,
                        sourceAgent = sourceAgent,
                        task = task
                    )
                    return
                
        except Exception:
            pass

        memoryId = f"mem-{uuid.uuid4().hex[:8]}"
        self.collection.add(
            ids = [memoryId],
            documents = [content],
            metadatas = [{
                "memoryType": memoryType,
                "importance": importance,
                "timestamp": time.time(),
                "sourceAgent": sourceAgent,
                "task": task
            }]
        )

    def learnFromFailure(self, task : str, errorOutput : str) -> None:
        reflectionPrompt = f"""An agent was executing the following task:
"{task}"

However, the execution failed/tests failed with this output:
---
{errorOutput}
---

Write a short, concise, and actionable lesson learned (1-2 sentences) explaining the cause of the failure and how to avoid it next time.
Be specific about patterns, API details, or environment parameters.
Do not write generic advice like "check your code".
For example: "Authentication tests require a valid JWT token in the Authorization header."
"""
        try:
            from core.config import get_llm
            
            llmInstance = get_llm(temperature = 0)
            llmResponse = llmInstance.invoke([
                SystemMessage(content = "You are an expert software engineering mentor who distills failed attempts into concise lessons."),
                HumanMessage(content = reflectionPrompt)
            ])
            lesson = llmResponse.content.strip()
            
            self.saveMemory(
                content = lesson,
                memoryType = "procedural",
                importance = 0.9,
                sourceAgent = "TesterAgent",
                task = task
            )
        except Exception:
            pass
