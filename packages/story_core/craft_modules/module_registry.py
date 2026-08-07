"""Manifests and registry for craft modules.

A craft module is a self-contained, optional, stage-scoped
chunk of writing knowledge. The manifest is the contract;
the registry is the in-memory store. Installation is
explicit (a project must opt in), uninstallation is local
(no cascading), and exclusivity is a property of the purpose
key — not the module itself.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from pydantic import BaseModel, ConfigDict, Field


class CraftPurposeRegistry:
    """Track which purposes are exclusive.

    A purpose marked ``exclusive=True`` accepts at most one
    module per writer context. ``dialogue`` is exclusive by
    default; ``style`` is not (we may want two style
    perspectives in the same chapter).
    """

    _EXCLUSIVE: set[str] = {"dialogue"}
    _REGISTRY: dict[str, bool] = {}

    @classmethod
    def register(cls, name: str, *, exclusive: bool = False) -> str:
        if exclusive:
            cls._EXCLUSIVE.add(name)
        cls._REGISTRY[name] = exclusive
        return name

    @classmethod
    def is_exclusive(cls, name: str) -> bool:
        if name in cls._REGISTRY:
            return cls._REGISTRY[name]
        return name in cls._EXCLUSIVE

    @classmethod
    def reset(cls) -> None:
        """Test-only: clear the registry between tests."""
        cls._EXCLUSIVE.clear()
        cls._EXCLUSIVE.add("dialogue")
        cls._REGISTRY.clear()


class CraftModule(BaseModel):
    """One craft module's manifest.

    The ``purpose`` is the functional slot the module fills;
    exclusivity is decided by the purpose key, not the module.
    The ``content`` field is opaque to the registry — only the
    writer prompt builder reads it.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    purpose: str
    genre_ids: tuple[str, ...] = Field(default_factory=tuple)
    stages: tuple[str, ...] = Field(default_factory=tuple)
    priority: int = 50
    max_chars: int = 800
    conflicts_with: tuple[str, ...] = Field(default_factory=tuple)
    enabled_by_default: bool = False
    content: str = ""


class CraftModuleRegistry:
    """In-memory registry of installed craft modules.

    The registry answers two questions:

    * which modules are installed (``list_installed``) — useful
      for the workbench's installed-modules panel;
    * which modules a given project's settings should load
      (``list_for_project``) — what the writer context receives.

    The registry is intentionally not a database. The file
    project store and the migration script (Task 15) own
    durability.
    """

    def __init__(self) -> None:
        self._modules: dict[str, CraftModule] = {}

    def register(self, module: CraftModule) -> None:
        if module.id in self._modules:
            raise ValueError(f"craft_module_already_registered: {module.id}")
        self._modules[module.id] = module

    def unregister(self, module_id: str) -> bool:
        return self._modules.pop(module_id, None) is not None

    def get(self, module_id: str) -> Optional[CraftModule]:
        return self._modules.get(module_id)

    def list_installed(self) -> list[CraftModule]:
        return sorted(
            self._modules.values(),
            key=lambda module: (-module.priority, module.id),
        )

    def list_for_project(
        self,
        project: "ProjectCraftSettings",
    ) -> list[CraftModule]:
        """List modules the project has enabled and that pass
        every other static filter. The selector handles budget
        and exclusive-purpose resolution.
        """
        enabled: list[CraftModule] = []
        for module_id in project.enabled_ids:
            module = self._modules.get(module_id)
            if module is None:
                continue
            enabled.append(module)
        return sorted(enabled, key=lambda module: (-module.priority, module.id))


__all__ = [
    "CraftModule",
    "CraftModuleRegistry",
    "CraftPurposeRegistry",
]
