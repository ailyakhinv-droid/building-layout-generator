"""Пакет ввода-вывода чертежей и пространственных данных."""

from src.io.cad_parser import (
    BOUNDARY_KEYWORDS,
    RED_LINE_KEYWORDS,
    CADLayerInfo,
    DWGConversionError,
    inspect_cad_layers,
    parse_cad_site,
)

__all__ = [
    "BOUNDARY_KEYWORDS",
    "RED_LINE_KEYWORDS",
    "CADLayerInfo",
    "DWGConversionError",
    "inspect_cad_layers",
    "parse_cad_site",
]
