"""Core domain types and algorithms."""

from .analysis import Analyzer, Slice
from .models import (
    EdgeType,
    Graph,
    GraphEdge,
    GraphNode,
    NodeKind,
    make_class_id,
    make_func_id,
    make_module_id,
)
from .state import (
    AnalysisState,
    CanvasState,
    Claim,
    Decision,
    Evidence,
    TaskSpec,
    clear_state,
    load_state,
    load_tasks_yaml,
    pick_task,
    save_state,
)

__all__ = [
    # models
    "EdgeType",
    "Graph",
    "GraphEdge",
    "GraphNode",
    "NodeKind",
    "make_class_id",
    "make_func_id",
    "make_module_id",
    # state
    "AnalysisState",
    "CanvasState",
    "Claim",
    "Decision",
    "Evidence",
    "TaskSpec",
    "clear_state",
    "load_state",
    "load_tasks_yaml",
    "pick_task",
    "save_state",
    # analysis
    "Analyzer",
    "Slice",
]
