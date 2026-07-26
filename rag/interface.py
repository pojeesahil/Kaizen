# base class so both basic and real rag follow same structure
from abc import ABC, abstractmethod

class RAGInterface(ABC):
    
    @abstractmethod
    def index_codebase(self, path):
        """Read code files from a folder and store them for search."""
        pass

    @abstractmethod
    def retrieve(self, query, top_k=5):
        """Return list of relevant chunks as dicts with content, file_path, score."""
        pass

    @abstractmethod
    def get_context_for_agent(self, query, top_k=5):
        """Return formatted string of code context ready for LLM prompt."""
        pass
