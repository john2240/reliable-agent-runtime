"""Application composition root."""

from __future__ import annotations

from dataclasses import dataclass

from reliable_agent_runtime.application.actions import ActionService
from reliable_agent_runtime.application.engine import ExecutionEngine
from reliable_agent_runtime.application.events import EventFactory
from reliable_agent_runtime.application.execution import (
    ApprovalCoordinator,
    CompensationCoordinator,
    RunJournal,
    StepExecutor,
    ToolInvoker,
)
from reliable_agent_runtime.application.policy import default_policy_engine
from reliable_agent_runtime.application.service import RunService
from reliable_agent_runtime.application.template import TemplateResolver
from reliable_agent_runtime.infrastructure.clock import SystemClock
from reliable_agent_runtime.infrastructure.identifiers import UuidIdGenerator
from reliable_agent_runtime.infrastructure.locks import InMemoryRunLockManager
from reliable_agent_runtime.infrastructure.persistence import Database, SqlAlchemyRuntimeStore
from reliable_agent_runtime.infrastructure.scheduling import AsyncioSleeper
from reliable_agent_runtime.infrastructure.tools.registry import InMemoryToolRegistry
from reliable_agent_runtime.infrastructure.tools.retail import RetailSystem, build_retail_tools
from reliable_agent_runtime.settings import Settings


@dataclass(slots=True)
class AppContainer:
    """Explicit dependency graph used by the API and tests."""

    settings: Settings
    database: Database
    store: SqlAlchemyRuntimeStore
    tools: InMemoryToolRegistry
    retail_system: RetailSystem
    run_service: RunService
    execution_engine: ExecutionEngine
    action_service: ActionService

    async def initialize(self) -> None:
        await self.store.initialize()

    async def close(self) -> None:
        await self.store.close()


def build_container(settings: Settings | None = None) -> AppContainer:
    """Build concrete adapters while keeping core code dependency-inverted."""

    resolved_settings = settings or Settings.from_env()
    clock = SystemClock()
    ids = UuidIdGenerator()
    database = Database(resolved_settings.database_url)
    store = SqlAlchemyRuntimeStore(database)
    journal = RunJournal(store=store, clock=clock)
    locks = InMemoryRunLockManager()

    retail_system = RetailSystem(
        refund_unknown_outcome_once=resolved_settings.demo_refund_unknown_outcome_once,
    )
    tools = InMemoryToolRegistry(build_retail_tools(retail_system))
    events = EventFactory(clock=clock, ids=ids)
    approvals = ApprovalCoordinator(
        store=store,
        journal=journal,
        clock=clock,
        ids=ids,
        events=events,
    )
    invoker = ToolInvoker()
    step_executor = StepExecutor(
        tools=tools,
        policy=default_policy_engine(),
        resolver=TemplateResolver(),
        approvals=approvals,
        invoker=invoker,
        journal=journal,
        sleeper=AsyncioSleeper(),
        clock=clock,
        ids=ids,
        events=events,
    )
    compensation = CompensationCoordinator(
        tools=tools,
        journal=journal,
        clock=clock,
        ids=ids,
        events=events,
    )
    run_service = RunService(
        store=store,
        locks=locks,
        clock=clock,
        ids=ids,
        events=events,
    )
    execution_engine = ExecutionEngine(
        store=store,
        locks=locks,
        journal=journal,
        approvals=approvals,
        steps=step_executor,
        compensation=compensation,
        events=events,
    )
    action_service = ActionService(
        runs=run_service,
        engine=execution_engine,
    )
    return AppContainer(
        settings=resolved_settings,
        database=database,
        store=store,
        tools=tools,
        retail_system=retail_system,
        run_service=run_service,
        execution_engine=execution_engine,
        action_service=action_service,
    )
