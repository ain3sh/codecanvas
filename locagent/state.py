"""State management that directly sets LocAgent's original global state."""
import os
import pickle
from pathlib import Path

# Set environment variables before importing core modules
CACHE_DIR = Path.home() / ".cache" / "locagent"
os.environ.setdefault("GRAPH_INDEX_DIR", str(CACHE_DIR / "graphs"))
os.environ.setdefault("BM25_INDEX_DIR", str(CACHE_DIR / "bm25"))

Path(os.environ["GRAPH_INDEX_DIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["BM25_INDEX_DIR"]).mkdir(parents=True, exist_ok=True)

from locagent.core.dependency_graph.build_graph import (
    build_graph,
    NODE_TYPE_FILE, NODE_TYPE_CLASS, NODE_TYPE_FUNCTION,
)
from locagent.core.dependency_graph.traverse_graph import RepoEntitySearcher, RepoDependencySearcher
from locagent.core.location_tools.repo_ops import repo_ops
from locagent.core.location_tools.retriever.bm25_retriever import (
    build_code_retriever_from_repo as build_code_retriever,
)


def _get_instance_id(repo_path: str) -> str:
    """Generate deterministic instance_id from repo path."""
    name = Path(repo_path).name
    path_hash = abs(hash(repo_path)) % 100000000
    return f"mcp_{name}_{path_hash}"


def _get_graph_cache_path(instance_id: str) -> Path:
    """Get graph cache file path."""
    return Path(os.environ["GRAPH_INDEX_DIR"]) / f"{instance_id}.pkl"


def init_repository(repo_path: str, force_rebuild: bool = False) -> str:
    """Initialize LocAgent's global state for a repository."""
    if not os.path.isabs(repo_path):
        return f"Error: repo_path must be absolute. Got '{repo_path}'. Use full path like '/home/user/project'"
    repo_path = str(Path(repo_path).resolve())
    if not os.path.isdir(repo_path):
        return f"Error: '{repo_path}' is not a valid directory. Check path exists and is accessible."
    
    instance_id = _get_instance_id(repo_path)
    graph_cache = _get_graph_cache_path(instance_id)
    bm25_path = os.path.join(os.environ["BM25_INDEX_DIR"], instance_id)
    
    # Set CURRENT_INSTANCE for BM25 content retriever compatibility
    repo_ops.CURRENT_INSTANCE = {"instance_id": instance_id}
    repo_ops.CURRENT_ISSUE_ID = instance_id
    
    G = None
    
    # Try loading graph from cache
    if not force_rebuild and graph_cache.exists():
        try:
            with open(graph_cache, 'rb') as f:
                G = pickle.load(f)
        except Exception:
            G = None
    
    # Build graph if needed
    if G is None:
        try:
            G = build_graph(repo_path, global_import=True)
            with open(graph_cache, 'wb') as f:
                pickle.dump(G, f)
        except Exception as e:
            return f"Error building graph: {e}"
    
    # Set graph-related globals
    repo_ops.DP_GRAPH = G
    repo_ops.DP_GRAPH_ENTITY_SEARCHER = RepoEntitySearcher(G)
    repo_ops.DP_GRAPH_DEPENDENCY_SEARCHER = RepoDependencySearcher(G)
    repo_ops.REPO_SAVE_DIR = repo_path
    
    repo_ops.ALL_FILE = repo_ops.DP_GRAPH_ENTITY_SEARCHER.get_all_nodes_by_type(NODE_TYPE_FILE)
    repo_ops.ALL_CLASS = repo_ops.DP_GRAPH_ENTITY_SEARCHER.get_all_nodes_by_type(NODE_TYPE_CLASS)
    repo_ops.ALL_FUNC = repo_ops.DP_GRAPH_ENTITY_SEARCHER.get_all_nodes_by_type(NODE_TYPE_FUNCTION)
    
    # Build BM25 content index so setup_repo() path is never hit
    if not os.path.exists(f'{bm25_path}/corpus.jsonl') or force_rebuild:
        try:
            build_code_retriever(repo_path, persist_path=bm25_path)
        except Exception as e:
            return f"Initialized graph ({G.number_of_nodes()} nodes) but BM25 index failed: {e}"
    
    return f"Initialized: {repo_path} ({G.number_of_nodes()} nodes, {G.number_of_edges()} edges)"


def is_initialized() -> bool:
    """Check if repository is initialized."""
    return repo_ops.DP_GRAPH is not None


def get_status() -> str:
    """Get current status."""
    if not is_initialized():
        return "No repository initialized. Call init_repository first."
    G = repo_ops.DP_GRAPH
    return f"Repository: {repo_ops.REPO_SAVE_DIR}\nNodes: {G.number_of_nodes()}\nEdges: {G.number_of_edges()}"
