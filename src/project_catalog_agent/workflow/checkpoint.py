"""Supported LangGraph checkpointer factories for local workflow operation."""

import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, closing, contextmanager
from enum import Enum
from pathlib import Path
from types import ModuleType

import aiosqlite
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from pydantic import BaseModel

from project_catalog_agent.catalog.contracts import (
    common,
    decision,
    extraction,
    profile,
    recovery,
    request,
    state,
    taxonomy,
    validation,
)
from project_catalog_agent.persistence import contracts as persistence_contracts
from project_catalog_agent.workflow import contracts as workflow_contracts

_CHECKPOINT_CONTRACT_MODULES: tuple[ModuleType, ...] = (
    common,
    decision,
    extraction,
    profile,
    recovery,
    request,
    state,
    taxonomy,
    validation,
    persistence_contracts,
    workflow_contracts,
)


def create_memory_checkpointer() -> InMemorySaver:
    """Create an isolated in-memory checkpointer for tests and short demos."""
    return InMemorySaver(serde=_checkpoint_serializer())


@contextmanager
def create_sqlite_checkpointer(path: Path) -> Iterator[SqliteSaver]:
    """Open and safely close a durable saver for synchronous graph invocation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path, check_same_thread=False)) as connection:
        yield SqliteSaver(connection, serde=_checkpoint_serializer())


@asynccontextmanager
async def open_async_sqlite_checkpointer(
    path: Path,
) -> AsyncIterator[AsyncSqliteSaver]:
    """Open and safely close a durable saver for the asynchronous facade."""
    path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(path) as connection:
        yield AsyncSqliteSaver(connection, serde=_checkpoint_serializer())


def _checkpoint_serializer() -> JsonPlusSerializer:
    """Allow only domain contract and enum types stored by this workflow."""
    allowed: list[tuple[str, str]] = []
    for module in _CHECKPOINT_CONTRACT_MODULES:
        for name, value in vars(module).items():
            if not isinstance(value, type):
                continue
            if value.__module__ != module.__name__:
                continue
            if issubclass(value, (BaseModel, Enum)):
                allowed.append((module.__name__, name))
    return JsonPlusSerializer(allowed_msgpack_modules=allowed)
