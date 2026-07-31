import json
import os


class GraphRAG:

    def __init__(self):
        self.nodes = {}
        self.edges = []
        self.communities = {}
        self.neighbors = {}

    def load_graph(self, graph_json_path):
        if not os.path.exists(graph_json_path):
            print(f"graph not found: {graph_json_path}")
            return False

        with open(graph_json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        for n in data.get("nodes", []):
            nid = n.get("id", "")
            self.nodes[nid] = {
                "id": nid,
                "label": n.get("label", nid),
                "type": n.get("type", "unknown"),
                "file": n.get("source_file", ""),
                "description": n.get("description", ""),
                "community": n.get("community", -1)
            }

        self.edges = []
        for e in data.get("edges", []):
            self.edges.append({
                "source": e.get("source", ""),
                "target": e.get("target", ""),
                "type": e.get("type", "related")
            })

        self.neighbors = {}
        for e in self.edges:
            s, t = e["source"], e["target"]
            self.neighbors.setdefault(s, []).append(t)
            self.neighbors.setdefault(t, []).append(s)

        self.communities = {}
        for nid, nd in self.nodes.items():
            c = nd["community"]
            self.communities.setdefault(c, []).append(nid)

        print(f"graph loaded: {len(self.nodes)} nodes, {len(self.edges)} edges")
        return True

    def find_related(self, node_id, depth=1):

        if node_id not in self.nodes:
            return []

        visited = {node_id}
        queue = [(node_id, 0)]

        while queue:
            curr, d = queue.pop(0)
            if d >= depth:
                continue
            for nb in self.neighbors.get(curr, []):
                if nb not in visited:
                    visited.add(nb)
                    queue.append((nb, d + 1))

        visited.discard(node_id)
        return [self.nodes[n] for n in visited if n in self.nodes]

    def search_nodes(self, query):

        words = query.lower().split()
        results = []

        for nid, nd in self.nodes.items():
            text = f"{nd['label']} {nd['description']}".lower()
            score = sum(1 for w in words if w in text)
            if score > 0:
                r = dict(nd)
                r["score"] = score
                results.append(r)

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def get_community_nodes(self, node_id):

        if node_id not in self.nodes:
            return []
        comm = self.nodes[node_id]["community"]
        return [self.nodes[n] for n in self.communities.get(comm, []) if n != node_id]


if __name__ == "__main__":
    g = GraphRAG()
    if g.load_graph("./graphify-out/graph.json"):
        for r in g.search_nodes("database")[:5]:
            print(f"  {r['label']} ({r['type']})")
    else:
        print("no graph found - run graphify first")
