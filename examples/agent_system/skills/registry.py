from __future__ import annotations

import importlib
from dataclasses import dataclass
from types import ModuleType


@dataclass
class SkillModule:
    name: str
    module: ModuleType


class SkillRegistry:
    def __init__(self) -> None:
        self._modules: dict[str, SkillModule] = {}

    def register(self, name: str, module_path: str) -> SkillModule:
        module = importlib.import_module(module_path)
        record = SkillModule(name=name, module=module)
        self._modules[name] = record
        return record

    def get(self, name: str) -> SkillModule:
        return self._modules[name]

    def reload(self, name: str) -> SkillModule:
        record = self._modules[name]
        module = importlib.reload(record.module)
        updated = SkillModule(name=name, module=module)
        self._modules[name] = updated
        return updated
