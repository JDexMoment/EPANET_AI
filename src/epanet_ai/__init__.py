"""Пакет-псевдоним `epanet_ai` для проекта EPANET-AI (прозрачно экспортирует API и CLI `aquabit_ai`)."""

from aquabit_ai import __version__
from aquabit_ai.cli import app

__all__ = ["__version__", "app"]
