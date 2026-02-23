"""Dependency injection container for centralized service management.

This module provides a simple DI container that manages all application
services in one place, making testing and configuration easier.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar

from loguru import logger

T = TypeVar("T")


class DIContainer:
    """Simple dependency injection container with registration and resolution."""

    def __init__(self) -> None:
        self._services: dict[type, Any] = {}
        self._factories: dict[type, Callable[..., Any]] = {}

    def register_singleton(self, service_type: type[T], instance: T) -> None:
        """Register a singleton instance."""
        self._services[service_type] = instance
        logger.debug("Registered singleton: {}", service_type.__name__)

    def register_factory(self, service_type: type[T], factory: Callable[..., T]) -> None:
        """Register a factory function that creates instances on demand."""
        self._factories[service_type] = factory
        logger.debug("Registered factory: {}", service_type.__name__)

    def resolve(self, service_type: type[T]) -> T:
        """Resolve a service by type."""
        if service_type in self._services:
            return self._services[service_type]

        if service_type in self._factories:
            factory = self._factories[service_type]
            instance = factory()
            self._services[service_type] = instance
            return instance

        raise KeyError(f"No service registered for type: {service_type.__name__}")

    def has(self, service_type: type) -> bool:
        """Check if a service is registered."""
        return service_type in self._services or service_type in self._factories

    def clear(self) -> None:
        """Clear all registered services."""
        self._services.clear()
        self._factories.clear()


_global_container: DIContainer | None = None
_container_lock = threading.Lock()


def get_container() -> DIContainer:
    """Get the global DI container (thread-safe)."""
    global _global_container
    if _global_container is None:
        with _container_lock:
            if _global_container is None:
                _global_container = DIContainer()
    return _global_container
