# chromadb wrapper for storing and searching code embeddings
import os
import chromadb
from chromadb.utils import embedding_functions

SUPPORTED_EXTENSIONS = [
    ".py", ".js", ".ts", ".java", ".kt", ".go",
    ".cpp", ".c", ".h", ".jsx", ".tsx",
    ".html", ".css", ".json", ".yaml", ".yml", ".md"
]

SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".git", ".venv", "chroma_db"}


class VectorStore:
    """Thin wrapper over ChromaDB - handles add, search, clear."""

    def __init__(self, collection_name="codebase", persist_dir="./chroma_db"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embed_fn = embedding_functions.DefaultEmbeddingFunction()
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=self.embed_fn
        )

    def add_documents(self, documents, metadatas, ids):
        # chromadb chokes on big batches so we do 500 at a time
        for i in range(0, len(documents), 500):
            self.collection.add(
                documents=documents[i:i+500],
                metadatas=metadatas[i:i+500],
                ids=ids[i:i+500]
            )

    def search(self, query, top_k=5):
        n = self.collection.count()
        if n == 0:
            return []

        raw = self.collection.query(query_texts=[query], n_results=min(top_k, n))

        if not raw["documents"] or not raw["documents"][0]:
            return []

        results = []
        for i in range(len(raw["documents"][0])):
            dist = raw["distances"][0][i]
            results.append({
                "content": raw["documents"][0][i],
                "file_path": raw["metadatas"][0][i].get("file_path", "unknown"),
                "score": round(1.0 / (1.0 + dist), 4)  # convert distance to score
            })
        return results

    def clear(self):
        name = self.collection.name
        self.client.delete_collection(name)
        self.collection = self.client.get_or_create_collection(
            name=name, embedding_function=self.embed_fn
        )

    def count(self):
        return self.collection.count()


def read_and_chunk_codebase(path, chunk_size=40):
    """walk through codebase, read files, split into chunks of chunk_size lines"""
    documents, metadatas, ids = [], [], []
    idx = 0

    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]

        for fname in files:
            ext = os.path.splitext(fname)[1].lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            fpath = os.path.join(root, fname)
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except:
                continue

            lines = content.split("\n")
            for i in range(0, len(lines), chunk_size):
                chunk = "\n".join(lines[i:i+chunk_size]).strip()
                if not chunk:
                    continue
                documents.append(chunk)
                metadatas.append({"file_path": fpath, "start_line": i+1})
                ids.append(f"chunk_{idx}")
                idx += 1

    return documents, metadatas, ids


if __name__ == "__main__":
    docs, metas, doc_ids = read_and_chunk_codebase(".")
    print(f"found {len(docs)} chunks")

    store = VectorStore()
    store.clear()
    store.add_documents(docs, metas, doc_ids)
    print(f"stored {store.count()} in chromadb")

    for r in store.search("retrieve search", top_k=2):
        print(f"\n{r['file_path']} (score={r['score']})")
        print(r["content"][:80] + "...")
