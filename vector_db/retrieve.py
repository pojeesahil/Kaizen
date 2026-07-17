from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from config import VECTOR_DB_DIR, EMBEDDING_MODEL, TOP_K

class Retriever:
    def __init__(self):
        self.embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
        self.db = Chroma(
            persist_directory=str(VECTOR_DB_DIR),
            embedding_function=self.embeddings
        )

    def retrieve(self, query, k=TOP_K):
        return [
            {"content": doc.page_content, "source": doc.metadata.get("source", "Unknown"), "score": score}
            for doc, score in self.db.similarity_search_with_score(query, k=k)
        ]

def main():
    retriever = Retriever()
    while True:
        query = input("\nQuery > ").strip()
        if query.lower() in {"exit", "quit"}:
            break
        context = retriever.retrieve(query)
        print("\n" + "=" * 60)
        print("Retrieved Context")
        print("=" * 60)
        for result in context:
            print(f"\nSource: {result['source']}")
            print(f"Score : {result['score']:.4f}")
            print(result["content"])
            print("-" * 60)

if __name__ == "__main__":
    main()