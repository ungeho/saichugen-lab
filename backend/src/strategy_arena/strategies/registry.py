"""新戦略はregister(name, factory)で登録する。大きなプラグイン基盤は不要。"""

from collections.abc import Callable

from .base import Strategy
from .baselines import Baseline, NAMES
from .descriptions import AlgorithmDescription, DESCRIPTIONS

_factories: dict[str, Callable[[], Strategy]] = {name: lambda n=name: Baseline(n) for name in NAMES}
_descriptions: dict[str, AlgorithmDescription] = dict(DESCRIPTIONS)


def register(name: str, factory: Callable[[], Strategy], description: AlgorithmDescription | None = None) -> None:
    if not name or name in _factories:
        raise ValueError("戦略名は空でなく、一意である必要があります")
    _factories[name] = factory
    if description is not None:
        _descriptions[name] = description


def strategy_names() -> tuple[str, ...]:
    return tuple(_factories)


def create_strategy(name: str) -> Strategy:
    try:
        return _factories[name]()
    except KeyError:
        raise ValueError(f"未知の戦略: {name}") from None


def algorithm_catalog() -> list[dict]:
    from dataclasses import asdict

    return [{"name": name, "version": create_strategy(name).version,
             "description_available": name in _descriptions,
             "description_origin": "実装コードに基づく図鑑用の解説（判断ログではありません）",
             **asdict(_descriptions.get(name, AlgorithmDescription()))} for name in strategy_names()]


def configured_parameters(names) -> dict:
    """設定を持つ戦略だけ記録し、既存戦略の空設定との互換性を保つ。"""
    parameters = {}
    for name in dict.fromkeys(names):
        values = getattr(create_strategy(name), "parameters", None)
        if values is not None:
            parameters[name] = values
    return parameters


from .monte_carlo import MonteCarloRollout, DESCRIPTION

register(MonteCarloRollout.name, MonteCarloRollout, DESCRIPTION)

from .hybrid import HybridSearch, METHOD_NAMES, description

for method, name in METHOD_NAMES.items():
    register(name, lambda m=method: HybridSearch(m), description(method))
