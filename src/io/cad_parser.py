"""Модуль импорта CAD чертежей (DXF/DWG). Фасад к src.core.cad_parser."""

from src.core.cad_parser import (
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
