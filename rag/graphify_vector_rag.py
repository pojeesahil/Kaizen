import os
import shutil
import subprocess
import sys
from rag.interface import RAGInterface
from rag.vector_store import VectorStore, read_and_chunk_codebase
from rag.graph_rag import GraphRAG
from rag.reranker import SimpleLLMReranker, BaseRAGRetriever
from langchain_classic.retrievers import ContextualCompressionRetriever
from core.config import llm


class GraphifyVectorRAG(RAGInterface):

    def __init__(self, persist_dir="./chroma_db"):
        self.vector_store = VectorStore(persist_dir=persist_dir)
        self.graph = GraphRAG()
        self.indexed_path = None

    def index_codebase(self, path):
        self.indexed_path = os.path.abspath(path)

        print("\nRunning graphify on workspace...")

        abs_path = os.path.abspath(path)
        cmd = [sys.executable, "-m", "graphify", abs_path, "--code-only"]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, shell=(os.name == "nt"))
            if res.returncode == 0:
                print("  graphify completed successfully\n")
            else:
                print(f"  graphify note/output: {res.stdout[:200] if res.stdout else res.stderr[:200]}\n")
        except Exception as e:
            print(f"  graphify execution error: {e}\n")

        work_gpath = os.path.join(path, "graphify-out")
        root_gpath = "graphify-out"
        if os.path.exists(work_gpath) and os.path.abspath(work_gpath) != os.path.abspath(root_gpath):
            if os.path.exists(root_gpath):
                shutil.rmtree(root_gpath, ignore_errors=True)
            shutil.move(work_gpath, root_gpath)

        print("Indexing into vector DB...")
        self.vector_store.clear()
        docs, metas, ids = read_and_chunk_codebase(path)
        if docs:
            self.vector_store.add_documents(docs, metas, ids)
        print(f"  {self.vector_store.count()} chunks stored\n")

        gpath_root = os.path.join(root_gpath, "graph.json")
        gpath_work = os.path.join(work_gpath, "graph.json")
        target_gpath = gpath_root if os.path.exists(gpath_root) else (gpath_work if os.path.exists(gpath_work) else None)

        if target_gpath:
            print(f"Loading knowledge graph from {target_gpath}...")
            self.graph.load_graph(target_gpath)
            print()
        else:
            print("No graph found (run graphify to enable graph features)\n")

    def retrieve_candidates(self, query, top_k=15):
        """Retrieve a wider set of initial candidates for reranking."""
        results = []
        seen = set() #prevents duplication of results   

        for r in self.vector_store.search(query, top_k=top_k):
            results.append(r)
            seen.add(r["file_path"])

        if self.graph.nodes:
            matches = self.graph.search_nodes(query)
            for m in matches[:3]:
                related = self.graph.find_related(m["id"], depth=1)
                for rel in related[:3]:
                    fp = rel.get("file", "")
                    if fp and fp not in seen:
                        extra = self.vector_store.search(rel.get("label", ""), top_k=1)
                        if extra:
                            extra[0]["score"] *= 0.8
                            results.append(extra[0])
                            seen.add(fp)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

    def retrieve(self, query, top_k=5):
        """Retrieve and rerank candidates using LangChain ContextualCompressionRetriever."""
        base_retriever = BaseRAGRetriever(rag_instance=self)
        compressor = SimpleLLMReranker(llm=llm, top_n=top_k)
        compression_retriever = ContextualCompressionRetriever(
            base_compressor=compressor,
            base_retriever=base_retriever
        )

        try:
            print(f"[Reranker] Retrieving and reranking top {top_k} results...")
            compressed_docs = compression_retriever.invoke(query)
            results = []
            for doc in compressed_docs:
                results.append({
                    "content": doc.page_content,
                    "file_path": doc.metadata.get("file_path", "unknown"),
                    "score": doc.metadata.get("score", 1.0)
                })
            return results
        except Exception as e:
            print(f"[Reranker] ContextualCompressionRetriever failed: {e}. Falling back to default retrieval.")
            return self.retrieve_candidates(query, top_k=top_k)

    def get_context_for_agent(self, query, top_k=5):
        results = self.retrieve(query, top_k)
        if not results:
            return "No relevant code found."

        parts = []
        for r in results:
            parts.append(f"--- {r['file_path']} (score: {r['score']}) ---\n{r['content']}")
        return "\n\n".join(parts)


if __name__ == "__main__":
    rag = GraphifyVectorRAG()
    rag.index_codebase(".")
    print(rag.get_context_for_agent("retrieve search", top_k=2))