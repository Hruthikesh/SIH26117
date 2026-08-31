"""AppState: the wired object graph every subsystem hangs off."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from yantra_server.artifacts import ArtifactStore
from yantra_server.config import LoadedConfig
from yantra_server.db.base import Database
from yantra_server.gateway.profile_spec import ProfileSpec
from yantra_server.gateway.registry import ModelRegistry
from yantra_server.gateway.router import Router
from yantra_server.gateway.service import Gateway
from yantra_server.gateway.supervisor import Supervisor
from yantra_server.observe.audit_chain import AuditChain
from yantra_server.rpc import EventBus
from yantra_server.tools.mcp import MCPManager
from yantra_server.tools.permissions import PermissionBroker, PermissionPolicy
from yantra_server.tools.registry import ToolRegistry
from yantra_server.tools.runtime import ToolRuntime


@dataclass
class ToolsBundle:
    registry: ToolRegistry
    policy: PermissionPolicy
    broker: PermissionBroker
    runtime: ToolRuntime
    mcp: MCPManager


@dataclass
class AppState:
    loaded: LoadedConfig
    db: Database
    artifacts: ArtifactStore
    audit: AuditChain
    bus: EventBus
    version: str
    registry: ModelRegistry
    profile_spec: ProfileSpec
    supervisor: Supervisor
    router: Router
    gateway: Gateway
    tools: ToolsBundle
    # Wired by later milestones; typed as Any until each subsystem lands.
    conductor: Any = None
    knowledge: Any = None
    seal_monitor: Any = None
    memory: Any = None
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def config(self) -> Any:
        return self.loaded.config
