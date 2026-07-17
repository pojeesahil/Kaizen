from ollama import chat
from config import MODEL_NAME

class Coder:
    def __init__(self):
        self.system_prompt = """You are an expert software engineer and AI coding assistant.

Rules:
1. Follow the user's request exactly.
2. Use the supplied repository context.
3. Never invent project files that don't exist unless asked.
4. If editing code, modify only what is necessary.
5. Generate clean, production-quality code.
6. When the user requests code generation or file creation, output ONLY the code.
7. Do NOT include explanations, introductions, markdown, or code fences.
8. Never begin responses with phrases like "Sure", "Here's the code", or "I will create...".
9. If the user requests an explanation, provide it separately.
10. If repository context is provided, use it before answering."""

    def generate(self, query, context=""):
        prompt = f"""Repository Context:

{context}

User Request:

{query}"""

        try:
            response = chat(
                model=MODEL_NAME,
                messages=[
                    {
                        "role": "system",
                        "content": self.system_prompt
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ]
            )
            return response.message.content
        except Exception as e:
            return f"LLM Error\n\n{e}"

def main():
    coder = Coder()
    print("=" * 60)
    print("Ollama Coding Agent")
    print("Type 'exit' or 'quit' to quit.")
    print("=" * 60)

    while True:
        query = input("\nPrompt > ").strip()
        if query.lower() in {"exit", "quit", "/bye", "/exit"}:
            print("\nExiting Ollama Coding Agent...")
            break
        print()
        print(coder.generate(query))
        print()

if __name__ == "__main__":
    main()