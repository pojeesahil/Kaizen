import json
import re
from typing import Sequence, Optional, List, Any
from langchain_classic.retrievers.contextual_compression import BaseDocumentCompressor
from langchain_core.documents import Document
from langchain_core.callbacks import Callbacks
from langchain_core.retrievers import BaseRetriever
from core.config import llm


class SimpleLLMReranker(BaseDocumentCompressor):
    """
    A simple listwise LLM-based document reranker implementing LangChain's BaseDocumentCompressor.
    It takes candidate documents and uses the configured LLM to sort them by relevance.
    """
    llm: Any
    top_n: int = 5

    class Config:
        arbitrary_types_allowed = True

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Optional[Callbacks] = None,
    ) -> Sequence[Document]:
        if not documents:
            return []


        prompt = (
            "You are an expert reranker. Given a user query and a list of code snippets (documents), "
            "determine which snippets are most relevant to the query.\n\n"
            f"Query: {query}\n\n"
            "Documents:\n"
        )
        for idx, doc in enumerate(documents):
            file_path = doc.metadata.get("file_path", "unknown")
            prompt += f"[{idx}] (File: {file_path}):\n{doc.page_content}\n---\n"

        prompt += (
            "\nTask: Return a JSON list of document indices ordered from MOST relevant to LEAST relevant. "
            "Only include indices that are relevant to answering the query.\n"
            "Format example: [2, 0, 4]\n"
            "Do not explain your answer, return ONLY the JSON list."
        )

        try:
            response = self.llm.invoke(prompt)
            content = response.content.strip()

            match = re.search(r"\[\s*\d+\s*(?:,\s*\d+\s*)*\]", content)
            if match:
                ordered_indices = json.loads(match.group(0))
            else:
                ordered_indices = [int(x) for x in re.findall(r"\d+", content)]

            seen_indices = set()
            reranked_docs = []
            for idx in ordered_indices:
                if 0 <= idx < len(documents) and idx not in seen_indices:
                    reranked_docs.append(documents[idx])
                    seen_indices.add(idx)

            for idx, doc in enumerate(documents):
                if idx not in seen_indices:
                    reranked_docs.append(doc)

            return reranked_docs[:self.top_n]
        except Exception as e:
            print(f"[SimpleLLMReranker] Reranking failed: {e}. Falling back to default retrieval order.")
            return documents[:self.top_n]


class BaseRAGRetriever(BaseRetriever):
    """
    A custom LangChain BaseRetriever wrapper around our existing RAG candidates retrieval.
    """
    rag_instance: Any

    class Config:
        arbitrary_types_allowed = True

    def _get_relevant_documents(
        self, query: str, *, run_manager: Optional[Any] = None
    ) -> List[Document]:

        candidates = self.rag_instance.retrieve_candidates(query, top_k=15)
        docs = []
        for r in candidates:
            docs.append(Document(
                page_content=r["content"],
                metadata={"file_path": r["file_path"], "score": r["score"]}
            ))
        return docs