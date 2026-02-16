"""
RAG Ingestion Module - Phase 1

Provides database-driven context loading for LLM explanations.
Replaces external API document fetching with queryable database snapshots.
"""

from .database_context import (
    SourceStatus,
    ContextSnapshot,
    DatabaseContextLoader,
    SessionContextManager,
)

__all__ = [
    'SourceStatus',
    'ContextSnapshot',
    'DatabaseContextLoader',
    'SessionContextManager',
]
