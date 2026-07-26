# combines vector db + knowledge graph for better retrieval
import os
from rag.interface import RAGInterface
from rag.vector_store import VectorStore, read_and_chunk_codebase
from rag.graph_rag import GraphRAG


class GraphifyVectorRAG(RAGInterface):
    """The real RAG - uses chromadb for semantic search + graphify for structure."""

    def __init__(self, persist_dir="./chroma_db"):
        self.vector_store = VectorStore(persist_dir=persist_dir)
        self.graph = GraphRAG()
        self.indexed_path = None

    def index_codebase(self, path):
        self.indexed_path = os.path.abspath(path)

        # index into vector db
        print("indexing into vector db...")
        self.vector_store.clear()
        docs, metas, ids = read_and_chunk_codebase(path)
        if docs:
            self.vector_store.add_documents(docs, metas, ids)
        print(f"  {self.vector_store.count()} chunks stored")

        # load graph if graphify was already run
        gpath = os.path.join(path, "graphify-out", "graph.json")
        if os.path.exists(gpath):
            print("loading knowledge graph...")
            self.graph.load_graph(gpath)
        else:
            print("no graph found (run graphify to enable graph features)")

    def retrieve(self, query, top_k=5):
        results = []
        seen = set()

        # vector search first
        for r in self.vector_store.search(query, top_k=top_k):
            results.append(r)
            seen.add(r["file_path"])

        # if graph is loaded, expand context using graph relationships
        if self.graph.nodes:
            matches = self.graph.search_nodes(query)
            for m in matches[:3]:
                related = self.graph.find_related(m["id"], depth=1)
                for rel in related[:3]:
                    fp = rel.get("file", "")
                    if fp and fp not in seen:
                        extra = self.vector_store.search(rel.get("label", ""), top_k=1)
                        if extra:
                            extra[0]["score"] *= 0.8  # lower priority than direct matches
                            results.append(extra[0])
                            seen.add(fp)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results[:top_k]

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
