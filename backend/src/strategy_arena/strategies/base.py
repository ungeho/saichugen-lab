from dataclasses import dataclass
from random import Random
from typing import Protocol

from ..game.cards import Card
from ..game.observation import Observation


@dataclass(frozen=True)
class Decision:
    card: Card
    desire_to_win: float | None = None
    estimated_turn_win: float | None = None
    explanation: str = ""


class Strategy(Protocol):
    name: str
    version: str

    def choose(self, observation: Observation, rng: Random) -> Decision: ...
