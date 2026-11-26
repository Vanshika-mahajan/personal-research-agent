"""
Routing helpers.

There used to be a second, different should_continue() here that returned
"research" - a route the graph does not define. The one real implementation
lives in nodes.py; this module just re-exports it so old imports keep working.
"""

from app.graph.nodes import should_continue  # noqa: F401

__all__ = ["should_continue"]
