from __future__ import annotations

from typing import Any, Callable, Dict, Generic, Optional, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    """
    A generic registry for storing and retrieving components by name.
    """

    def __init__(self, name: str = "Registry") -> None:
        self.name = name
        self._registry: Dict[str, T] = {}

    def register(self, name: str, component: T) -> T:
        """
        Register a component with a given name.
        Overwrites existing component if name already exists.
        """
        self._registry[name] = component
        return component

    def get(self, name: str) -> Optional[T]:
        """
        Get a component by name. Returns None if not found.
        """
        return self._registry.get(name)

    def list(self) -> Dict[str, T]:
        """
        Return all registered components.
        """
        return self._registry.copy()

    def clear(self) -> None:
        """
        Clear all registered components.
        """
        self._registry.clear()
