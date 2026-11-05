---
name: urban-tep-engine
description: "Architectural rules for urban planning generators: calculation of Technical-Economic Parameters (TEP/ТЭП), Russian master-planning norms (СП 42.13330, СП 4.13130, СанПиН), computational geometry with Shapely, performant Streamlit state management, and clean DXF/GeoJSON CAD export."
---

# Urban TEP Engine & Computational Master-Planning

Specialized skill synthesizing best practices from `developing-with-streamlit`, `python-design-patterns`, `shapely`, and `cad-to-data`, specifically tailored for the «Генератор застройки по ТЭП» platform.

---

## 1. Urban Planning Norms & TEP Formulas (СП 42.13330 & СП 4.13130)

When generating or validating site layouts, strictly adhere to Russian urban planning standards:

### Key Metrics & Formulas
1. **Коэффициент застройки (КЗ / BCR - Building Coverage Ratio):**
   $$K_{3} = \frac{\sum S_{footprint}}{S_{site}}$$
   - Норматив СП 42: как правило, не более $0.40$ – $0.45$ (40–45% для жилых зон).
2. **Коэффициент использования территории (КИТ / FAR - Floor Area Ratio):**
   $$KИT = \frac{\sum S_{GFA}}{S_{site}}$$
   - Нормативная плотность: обычно от $1.2$ до $2.5$ тыс. м²/га (в зависимости от зоны и этажности).
3. **Общая площадь здания (GFA - Gross Floor Area):**
   - Сумма площадей всех надземных этажей по наружному контуру наружных стен.
4. **Жилая площадь (NSA / Net Saleable Area):**
   - Эффективная продаваемая жилая площадь: принимается как $0.65$ – $0.75 \times GFA$.
5. **Расчетное население:**
   $$N = \frac{S_{living}}{\text{норматив на человека (м²)}}$$
   - Стандартно: $25$ – $30$ м²/чел (или $28.2$ м²/чел по региональным нормативам РНГП).
6. **Обеспеченность парковочными местами:**
   - По СП 42: расчет на 1000 жителей (обычно 350–420 машиномест / 1000 чел) либо по квартирографии ($0.7$ – $1.0$ м/м на квартиру бизнес/комфорт-класса).
7. **Озеленение:**
   - Площадь озеленения территории жилой застройки: не менее $25\%$ территории микрорайона/квартала (или от 6 м² на 1 жителя).

### Пожарные разрывы (СП 4.13130)
- Между жилыми зданиями I–II степени огнестойкости: минимум **6.0 м** (глухие торцы) или **15.0–18.0 м** (фасады с оконными проемами).
- Противопожарные проезды для пожарной техники: ширина не менее **3.5–4.2 м** на расстоянии **5.0–8.0 м** от стен здания высотой до 28 м.

---

## 2. Shapely 2.0 & Computational Geometry Patterns

### Safe Boundary Offsets
Never assume a site polygon is convex or simple. Always ensure geometry validity before offsetting:

```python
from shapely.validation import make_valid
from shapely.geometry import Polygon, MultiPolygon

def get_buildable_envelope(site_poly: Polygon, setback: float = 3.0) -> Polygon | MultiPolygon:
    """Calculates allowable building footprint area considering boundary setback."""
    if not site_poly.is_valid:
        site_poly = make_valid(site_poly)
    
    # Negative buffer for building envelope
    envelope = site_poly.buffer(-setback, join_style=2) # 2 = mitre
    if envelope.is_empty:
        raise ValueError(f"Site is too small for a setback of {setback}m.")
    return envelope
```

### Spatial Indexing (STRtree) for Fast Collision Detection
Do not perform $O(N^2)$ pairwise intersection checks for building sections:
```python
from shapely.strtree import STRtree

def find_overlapping_sections(footprints: list[Polygon]):
    tree = STRtree(footprints)
    conflicts = []
    for i, poly in enumerate(footprints):
        # Query bounding boxes first, then exact intersection
        candidates = tree.query(poly)
        for j in candidates:
            if i < j and poly.intersects(footprints[j]):
                conflicts.append((i, j))
    return conflicts
```

---

## 3. High-Performance Streamlit Architecture

Streamlit apps run top-to-bottom on interaction. For a CAD/GIS generator, protect execution performance:

### Caching Strategy
- **`@st.cache_data`**: Use for pure calculations and heavy geometric generation (placement algorithm, TEP calculation, GeoJSON parsing).
- **`@st.cache_resource`**: Use for persistent connections, DXF parser singletons, and large reference datasets.

```python
@st.cache_data(show_spinner="Генерация мастер-плана...")
def run_masterplan_generation(site_coords_hash: str, target_tep: dict, constraints: dict):
    # Pure algorithmic function - returns serializable data dict or models
    ...
```

### Session State Discipline
Keep the generation state predictable:
```python
if "current_scenario" not in st.session_state:
    st.session_state.current_scenario = None
if "site_geometry" not in st.session_state:
    st.session_state.site_geometry = None
```

- When changing visual-only parameters (e.g., color scheme, filter by floor count, insolation time of day), update only the visualization layer without re-running the placement optimizer.

---

## 4. Professional CAD & GIS Data Interchange

### DXF Export Conventions (`ezdxf`)
Architects (ГАП) and engineers require structured CAD files. Strictly group entities into standard layers:

| Layer Name | Color (ACI) | Lineweight | Description |
| :--- | :--- | :--- | :--- |
| `01_SITE_BOUNDARY` | 7 (Белый/Черный) | 0.50 mm | Кадастровые границы участка |
| `02_BUILDABLE_ENVELOPE` | 8 (Серый) | 0.25 mm | Пятно допустимой застройки |
| `03_BUILDINGS_FOOTPRINT` | 3 (Зеленый / По секциям) | 0.70 mm | Контуры секций зданий |
| `04_FIRE_PASSAGE` | 1 (Красный) | 0.35 mm | Пожарные проезды и радиусы разворота |
| `05_TEP_ANNOTATIONS` | 4 (Циан) | 0.20 mm | Текстовые выноски: этажность, GFA, площадь |

Always specify DXF units (`$INSUNITS = 6` for Meters).

### GeoJSON Standards
When exporting for GIS (QGIS, NextGIS, Mapbox):
- Always use `EPSG:4326` (WGS84) for geographic coordinates, or provide explicit CRS for local coordinates.
- Include structured properties in every feature:
  `{"id": "BLD-01-A", "type": "residential", "floors": 12, "gfa": 4320.5, "living_area": 3100.0, "section_type": "T-1"}`.

---

## 5. Non-Destructive Code Evolution
- **Never break existing data models:** Preserve backward compatibility with `Site`, `SectionType`, `Building`, and `TEPResult`.
- **Preserve existing tests:** Any enhancements to algorithms or calculations must pass existing test suites in `tests/` and `test_run.py`.
