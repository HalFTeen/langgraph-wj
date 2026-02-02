from __future__ import annotations

from examples.agent_system.skills.reloader import SkillReloader
from examples.agent_system.skills.registry import SkillRegistry


def test_skill_reload_roundtrip() -> None:
    registry = SkillRegistry()
    registry.register("arithmetic", "examples.agent_system.skills.arithmetic")
    skill = registry.get("arithmetic").module
    assert skill.add(1, 2) == 3

    reloader = SkillReloader(registry)
    result = reloader.reload("arithmetic")
    assert result.success is True
    skill = registry.get("arithmetic").module
    assert skill.add(2, 4) == 6
