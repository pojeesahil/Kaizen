from rag.graphify_vector_rag import GraphifyVectorRAG

_rag = GraphifyVectorRAG()

def indexWorkspace():
    _rag.index_codebase("work")

def getContext(instruction: str) -> str:
    return _rag.get_context_for_agent(instruction)