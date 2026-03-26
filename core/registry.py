from __future__ import annotations

from typing import Any, Callable

HookFn = Callable[..., Any]

_hooks: dict[str, list[HookFn]] = {}


def register_hook(name: str, fn: HookFn) -> None:
    _hooks.setdefault(name, []).append(fn)


def run_hooks(name: str, *args: Any, **kwargs: Any) -> list[Any]:
    return [fn(*args, **kwargs) for fn in _hooks.get(name, [])]
