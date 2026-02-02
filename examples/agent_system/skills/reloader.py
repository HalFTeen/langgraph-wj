from __future__ import annotations

from dataclasses import dataclass

from examples.agent_system.skills.registry import SkillRegistry


@dataclass
class ReloadResult:
    name: str
    module_path: str
    success: bool


class SkillReloader:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def reload(self, name: str) -> ReloadResult:
        record = self.registry.reload(name)
        return ReloadResult(
            name=record.name,
            module_path=record.module.__name__,
            success=True,
        )
