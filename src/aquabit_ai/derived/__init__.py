"""Расчёт производных гидравлических и эксплуатационных показателей по книге Walski et al. и СП 31.13330.2021."""

from __future__ import annotations

from aquabit_ai.derived.walski_features import (
    DerivedCityArtifacts,
    compute_and_write_derived_city_tables,
)

__all__ = [
    "DerivedCityArtifacts",
    "compute_and_write_derived_city_tables",
]
