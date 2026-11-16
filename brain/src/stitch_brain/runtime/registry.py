"""Organ registry: builds one client per organ from settings and ``organs.yaml``, starts them
without blocking, and reports health for ``GET /organs`` (design 3, BRN-R1)."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from stitch_brain.config import OrgansCfg
from stitch_brain.paths import recorded_dir
from stitch_brain.runtime.clock import Clock, RealClock
from stitch_brain.runtime.mcp_client import McpOrganClient
from stitch_brain.runtime.organs import (
    CallContext,
    CallOutcome,
    OrganClient,
    OrganHealth,
    TransportError,
)
from stitch_brain.runtime.recorded import DirectoryFixtureSource, FixtureSource, RecordedOrgan
from stitch_brain.settings import ORGANS, Settings
from stitch_common.organs import ORGAN_TOOLS

RESOURCES: dict[str, list[str]] = {"ledger": ["resource:districts"]}


class DisabledOrgan:
    """Placeholder for an organ named in ``STITCH_ORGANS_DISABLED``. Never called."""

    served_by: Any = "real"

    def __init__(self, organ: str) -> None:
        self.organ = organ

    async def start(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def list_tools(self) -> list[str]:
        return []

    async def call_tool(
        self, tool: str, args: dict[str, Any], *, timeout_s: float, ctx: CallContext
    ) -> CallOutcome:
        return CallOutcome(transport_error=TransportError("UNAVAILABLE", "organ disabled"))

    async def read_resource(self, uri: str, *, timeout_s: float, ctx: CallContext) -> CallOutcome:
        return CallOutcome(transport_error=TransportError("UNAVAILABLE", "organ disabled"))

    def health(self) -> OrganHealth:
        return OrganHealth(organ=self.organ, status="disabled", reason="STITCH_ORGANS_DISABLED")


def recorded_tools(organ: str) -> list[str]:
    return sorted([*ORGAN_TOOLS.get(organ, {}), *RESOURCES.get(organ, [])])


class OrganRegistry:
    def __init__(self, clients: Mapping[str, OrganClient], settings: Settings | None = None):
        self.clients: dict[str, OrganClient] = dict(clients)
        self.settings = settings or Settings()

    @classmethod
    def build(
        cls,
        settings: Settings,
        organs_cfg: OrgansCfg | None,
        *,
        clock: Clock | None = None,
        fixtures: FixtureSource | None = None,
        organs: Iterable[str] = ORGANS,
    ) -> OrganRegistry:
        clock = clock or RealClock()
        source = fixtures or DirectoryFixtureSource(recorded_dir())
        clients: dict[str, OrganClient] = {}
        for i, organ in enumerate(organs):
            if organ in settings.disabled_organs:
                clients[organ] = DisabledOrgan(organ)
            elif settings.is_recorded(organ):
                clients[organ] = RecordedOrgan(organ, source, recorded_tools(organ))
            elif organs_cfg is not None and organ in organs_cfg.organs:
                clients[organ] = McpOrganClient(
                    organ, organs_cfg.organs[organ], clock=clock, seed=i
                )
            else:
                clients[organ] = DisabledOrgan(organ)
        return cls(clients, settings)

    def get(self, organ: str) -> OrganClient | None:
        return self.clients.get(organ)

    async def start(self) -> None:
        """Start every client; connection failures never block (supervisors retry)."""
        await asyncio.gather(*(c.start() for c in self.clients.values()))

    async def close(self) -> None:
        await asyncio.gather(*(c.close() for c in self.clients.values()), return_exceptions=True)

    def health(self) -> dict[str, OrganHealth]:
        out: dict[str, OrganHealth] = {}
        for organ, c in self.clients.items():
            h = c.health()
            h.served_by = c.served_by
            if h.last_check is None:
                h.last_check = datetime.now(UTC)
            out[organ] = h
        return out

    def stub_organs(self) -> list[str]:
        return sorted(o for o, c in self.clients.items() if c.served_by == "recorded")

    def available(self) -> set[tuple[str, str]]:
        pairs: set[tuple[str, str]] = set()
        for organ, c in self.clients.items():
            if isinstance(c, DisabledOrgan):
                continue
            for tool in recorded_tools(organ):
                pairs.add((organ, tool))
        return pairs
