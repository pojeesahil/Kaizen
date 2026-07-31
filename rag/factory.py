def create_rag(mode="basic"):

    if mode == "basic":
        from rag.basic_rag import BasicRAG
        return BasicRAG()
    elif mode == "graphify":
        from rag.graphify_vector_rag import GraphifyVectorRAG
        return GraphifyVectorRAG()
    else:
        raise ValueError(f"unknown mode: {mode}")
