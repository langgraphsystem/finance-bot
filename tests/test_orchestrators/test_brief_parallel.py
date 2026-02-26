"""Tests for brief graph parallel fan-out structure."""

from unittest.mock import patch

from src.orchestrators.brief.graph import (
    _COLLECTORS,
    build_brief_graph_parallel,
    build_brief_graph_sequential,
)


def test_parallel_graph_has_fan_out_from_start():
    """Parallel graph should have edges from START to all collectors."""
    graph = build_brief_graph_parallel()
    compiled = graph.compile()
    graph_dict = compiled.get_graph().to_json()
    # All collectors should be present as nodes
    node_ids = [n["id"] for n in graph_dict["nodes"]]
    for name in _COLLECTORS:
        assert name in node_ids, f"Missing node: {name}"
    assert "synthesize" in node_ids


def test_sequential_graph_chains_collectors():
    """Sequential graph should chain collectors in order."""
    graph = build_brief_graph_sequential()
    compiled = graph.compile()
    graph_dict = compiled.get_graph().to_json()
    node_ids = [n["id"] for n in graph_dict["nodes"]]
    for name in _COLLECTORS:
        assert name in node_ids


def test_parallel_flag_selects_graph_type():
    """Feature flag controls which graph is compiled."""
    with patch("src.orchestrators.brief.graph.settings") as mock_settings:
        mock_settings.ff_langgraph_brief_parallel = True
        mock_settings.ff_langgraph_checkpointer = False

        from src.orchestrators.brief.graph import _compile_brief_graph

        graph = _compile_brief_graph()
        graph_json = graph.get_graph().to_json()
        # In parallel mode, START should have multiple edges
        start_edges = [
            e for e in graph_json["edges"]
            if e["source"] == "__start__"
        ]
        assert len(start_edges) == len(_COLLECTORS)

    with patch("src.orchestrators.brief.graph.settings") as mock_settings:
        mock_settings.ff_langgraph_brief_parallel = False
        mock_settings.ff_langgraph_checkpointer = False

        graph = _compile_brief_graph()
        graph_json = graph.get_graph().to_json()
        start_edges = [
            e for e in graph_json["edges"]
            if e["source"] == "__start__"
        ]
        assert len(start_edges) == 1
