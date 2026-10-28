"""Пакет геодезических преобразований и координатных систем."""

from src.geo.msk_converter import (
    MSK_PRESETS,
    ZONE_ALIASES,
    detect_msk_by_coordinates,
    get_msk_key_for_region,
    msk_to_wgs84_coords,
    resolve_zone_preset,
    wgs84_to_msk_coords,
)

__all__ = [
    "MSK_PRESETS",
    "ZONE_ALIASES",
    "resolve_zone_preset",
    "wgs84_to_msk_coords",
    "msk_to_wgs84_coords",
    "detect_msk_by_coordinates",
    "get_msk_key_for_region",
]
