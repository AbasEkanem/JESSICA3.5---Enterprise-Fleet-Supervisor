import importlib.util

# Load Jessica app dynamically
spec = importlib.util.spec_from_file_location("jessica", "JESSICA3.5.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

# Instantiate compiled Jessica AI agent graph
graph = mod.create_jessicaAI()

# Print Mermaid graph definition
if __name__ == "__main__":
    mermaid_code = graph.get_graph().draw_mermaid()
    print("\n--- Jessica 3.5 Compiled LangGraph Mermaid Diagram ---\n")
    print(mermaid_code)
