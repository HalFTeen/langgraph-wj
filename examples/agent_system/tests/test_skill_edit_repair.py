from __future__ import annotations

from examples.agent_system.skills.editor import SkillEditor
from examples.agent_system.skills.registry import SkillRegistry
from examples.agent_system.skills.reloader import SkillReloader
from examples.agent_system.skills.templates import arithmetic_template


def test_skill_edit_and_reload() -> None:
    registry = SkillRegistry()
    registry.register("arithmetic", "examples.agent_system.skills.arithmetic")
    editor = SkillEditor(registry)
    reloader = SkillReloader(registry)

    editor.update_source("arithmetic", arithmetic_template("add"))
    reloader.reload("arithmetic")

    skill = registry.get("arithmetic").module
    assert skill.add(10, 2) == 12
