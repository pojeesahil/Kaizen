# simple keyword based rag - no external deps needed
import os
from rag.interface import RAGInterface

SUPPORTED_EXTENSIONS = [
    ".py", ".js", ".ts", ".java", ".kt", ".go",
    ".cpp", ".c", ".h", ".jsx", ".tsx",
    ".html", ".css", ".json", ".yaml", ".yml", ".md"
]

SKIP_DIRS = {"node_modules", "__pycache__", "venv", ".git", ".venv"}


class BasicRAG(RAGInterface):

    def __init__(self):
        self.chunks = []

    def index_codebase(self, path):
        self.chunks = []

        for root, dirs, files in os.walk(path):

            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in SKIP_DIRS]

            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext not in SUPPORTED_EXTENSIONS:
                    continue

                fpath = os.path.join(root, fname)
                try:
                    with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                except:
                    continue


                self._chunk_file(text, fpath)

        print(f"[BasicRAG] indexed {len(self.chunks)} chunks from {path}")

    def _chunk_file(self, text, fpath):
        lines = text.split("\n")
        buf = []

        for line in lines:
            buf.append(line)
            if len(buf) >= 50:
                chunk = "\n".join(buf)
                if chunk.strip():
                    self.chunks.append({"content": chunk, "file_path": fpath})
                buf = []

        if buf:
            chunk = "\n".join(buf)
            if chunk.strip():
                self.chunks.append({"content": chunk, "file_path": fpath})

        if not self.chunks and text.strip():
            self.chunks.append({"content": text, "file_path": fpath})

    def retrieve(self, query, top_k=5):
        if not self.chunks:
            return []

        words = query.lower().split()
        scored = []

        for chunk in self.chunks:
            text_lower = chunk["content"].lower()
            score = sum(1 for w in words if w in text_lower)
            if score > 0:
                scored.append({
                    "content": chunk["content"],
                    "file_path": chunk["file_path"],
                    "score": score
                })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:top_k]

    def get_context_for_agent(self, query, top_k=5):
        results = self.retrieve(query, top_k)
        if not results:
            return "No relevant code found."

        parts = []
        for r in results:
            parts.append(f"--- {r['file_path']} (score: {r['score']}) ---\n{r['content']}")
        return "\n\n".join(parts)


if __name__ == "__main__":
    rag = BasicRAG()
    rag.index_codebase(".")
    print(rag.get_context_for_agent("retrieve search", top_k=2))
