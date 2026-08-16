import os
from rag.interface import RAGInterface

SUPPORTED_EXTENSIONS = [
    ".py", ".js", ".ts", ".java", ".kt", ".go",
    ".cpp", ".c", ".h", ".jsx", ".tsx",
    ".html", ".css", ".json", ".yaml", ".yml", ".md", "txt", "cs"
]

SKIP_DIRS = {"__pycache__", "venv", ".git", ".venv"}


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
        lines = text.splitlines()
        blocks = []
        current = []

        for line in lines:
            stripped = line.lstrip()
            if stripped.startswith(("def ", "async def ", "class ")) and current:
                blocks.append(current)
                current = []
            current.append(line)
        if current:
            blocks.append(current)

        added = 0
        for block in blocks:
            if len(block) > 60:
                step = 50 
                for i in range(0, len(block), step):
                    chunk = "\n".join(block[i:i + 60])
                    if chunk.strip():
                        self.chunks.append({"content": chunk, "file_path": fpath})
                        added += 1
            else:
                chunk = "\n".join(block)
                if chunk.strip():
                    self.chunks.append({"content": chunk, "file_path": fpath})
                    added += 1

        if added == 0 and text.strip():
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

        parts = [] #stores formatted strings of results to return to the agent 
        for r in results:
            parts.append(f"--- {r['file_path']} (score: {r['score']}) ---\n{r['content']}")
        return "\n\n".join(parts)


if __name__ == "__main__": #this code runs only if this file is run as a script
    rag = BasicRAG()
    rag.index_codebase(".") #index the current directory
    print(rag.get_context_for_agent("retrieve search", top_k=2))