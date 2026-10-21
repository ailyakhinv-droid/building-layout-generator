"""Модуль экспорта 3D-визуализации в автономный HTML файл."""

from __future__ import annotations

from pathlib import Path

from src.models.building import Building
from src.models.site import Site
from src.models.tep import TEP
from src.visualization.viewer_3d import generate_3d_viewer_html


def export_3d_html(
    site: Site,
    buildings: list[Building],
    tep: TEP | None,
    filepath: str | Path,
    title: str = "3D-визуализация застройки участка",
    default_basemap: str = "none",
) -> Path:
    """Экспортировать интерактивную 3D-модель застройки в автономный HTML файл.

    Args:
        site: Земельный участок.
        buildings: Размещенные жилые корпуса.
        tep: Технико-экономические показатели.
        filepath: Путь для сохранения HTML.
        title: Заголовок страницы и проекта.
        default_basemap: Начальная подложка ('none', 'light', 'dark').

    Returns:
        Объект Path сохраненного файла.
    """
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    html_content = generate_3d_viewer_html(
        site=site,
        buildings=buildings,
        tep=tep,
        title=title,
        height="100%",
        default_basemap=default_basemap,
        standalone=True,
    )

    with path.open("w", encoding="utf-8") as f:
        f.write(html_content)

    return path
