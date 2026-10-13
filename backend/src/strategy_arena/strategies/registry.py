"""新戦略はregister(name, factory)で登録する。大きなプラグイン基盤は不要。"""

from collections.abc import Callable

from .base import Strategy
from .baselines import Baseline, NAMES

_factories: dict[str, Callable[[], Strategy]] = {name: lambda n=name: Baseline(n) for name in NAMES}


def register(name: str, factory: Callable[[], Strategy]) -> None:
    if not name or name in _factories:
        raise ValueError("戦略名は空でなく、一意である必要があります")
    _factories[name] = factory


def strategy_names() -> tuple[str, ...]:
    return tuple(_factories)


def create_strategy(name: str) -> Strategy:
    try:
        return _factories[name]()
    except KeyError:
        raise ValueError(f"未知の戦略: {name}") from None
