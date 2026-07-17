from pathlib import Path
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_chroma import Chroma
from config import WORKSPACE_DIR, VECTOR_DB_DIR, EMBEDDING_MODEL, CHUNK_SIZE, CHUNK_OVERLAP, SUPPORTED_EXTENSIONS

class Ingestor:
    def __init__(self):
        self.embedding = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        self.splitter = RecursiveCharacterTextSplitter(chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
        self.db = Chroma(persist_directory=str(VECTOR_DB_DIR), embedding_function=self.embedding)

    def load_documents(self):
        docs = []
        for path in WORKSPACE_DIR.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            docs.append(
                Document(
                    page_content=text,
                    metadata={"source": str(path.relative_to(WORKSPACE_DIR))}
                )
            )
        return docs

    def ingest(self):
        docs = self.load_documents()
        chunks = self.splitter.split_documents(docs)
        print(f"\nLoaded Files : {len(docs)}")
        print(f"Generated Chunks : {len(chunks)}")
        self.db.reset_collection()
        self.db.add_documents(chunks)
        print("\nRepository indexed successfully.")

def main():
    Ingestor().ingest()

if __name__ == "__main__":
    main()