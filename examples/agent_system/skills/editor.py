from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from examples.agent_system.skills.registry import SkillRegistry


@dataclass
class EditResult:
    name: str
    module_path: str
    file_path: str
    success: bool


class SkillEditor:
    def __init__(self, registry: SkillRegistry) -> None:
        self.registry = registry

    def update_source(self, name: str, new_source: str) -> EditResult:
        record = self.registry.get(name)
        module_file = Path(record.module.__file__ or "")
        if module_file.suffix == ".pyc":
            module_file = module_file.with_suffix(".py")
        module_file.write_text(new_source, encoding="utf-8")
        return EditResult(
            name=record.name,
            module_path=record.module.__name__,
            file_path=str(module_file),
            success=True,
        )
