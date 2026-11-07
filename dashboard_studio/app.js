/**
 * URBAN / TEP STUDIO — ШАГ 1: ПОСАДКА И ПРОВЕРКА УЧАСТКА
 * Архитектура:
 * - 3 режима ввода: 1. Кадастр | 2. CAD (DXF) | 3. Точки (ГПЗУ / Спутник)
 * - Чистый старт: по умолчанию окно карты пустое до ввода кадастрового номера или файла
 * - Интерактивная Leaflet-карта посадки с трансформацией контура (перетаскивание, оранжевый маркер вращения, HUD)
 * - Двусторонний postMessage мост между родителем и картой (isMapTransform, contourDigitized, mapPointPicked)
 * - Живой паспорт земельного участка со строгой CAD-версткой без вылезания текста
 * - Альтернативный 2D CAD Векторный вид (SVG) с pan & zoom
 */

(function () {
  'use strict';

  // --- STATE ---
  const state = {
    mode: 'cadastre', // 'cadastre' | 'cad' | 'points'
    cad_query: '',     // Пусто по умолчанию!
    custom_area: 42500,
    site_rotation: 0.0,
    override_lat: 0.0,
    override_lon: 0.0,
    userHasMovedSite: false,
    userHasEnteredManualCoords: false,
    boundary_setback: 6,
    red_line_setback: 5,
    enable_red_line: true,
    zouit_active: false,
    msk_zone: 'МСК-63 Зона 1',
    cad_file_base64: null,
    cad_filename: null,
    boundary_layer: null,
    red_lines_layer: null,
    assigned_cad_query: '',
    gpzu_coordinates: null,
    isLocked: false,
    activeView: 'osm', // 'osm' | 'svg'
    currentData: null,
    lastLeafletHtml: '',
    isBusy: false
  };

  // --- DOM REFERENCES ---
  const el = {
    // Header
    hdrParcelBadge: document.getElementById('hdr-parcel-badge'),
    stepperStep1: document.getElementById('stepper-step-1'),
    stepperStep2: document.getElementById('stepper-step-2'),
    backendStatusText: document.getElementById('backend-status-text'),

    // Hero
    panelHeroArea: document.getElementById('panel-hero-area'),

    // Mode Buttons & Panes
    modeBtns: document.querySelectorAll('.mode-btn'),
    panes: {
      cadastre: document.getElementById('pane-mode-cadastre'),
      cad: document.getElementById('pane-mode-cad'),
      points: document.getElementById('pane-mode-points')
    },

    // Mode 1: Cadastre
    inputCadNum: document.getElementById('input-cad-num'),
    btnLoadCadastre: document.getElementById('btn-load-cadastre'),
    btnFetchPkk: document.getElementById('btn-fetch-pkk'),
    pkkBadge: document.getElementById('pkk-badge'),
    inputCustomArea: document.getElementById('input-custom-area'),
    btnPickPointCadastre: document.getElementById('btn-pick-point-cadastre'),
    inputManualLat: document.getElementById('input-manual-lat'),
    inputManualLon: document.getElementById('input-manual-lon'),

    // Mode 2: CAD
    dxfDropzone: document.getElementById('dxf-dropzone'),
    dxfDropzoneText: document.getElementById('dxf-dropzone-text'),
    dxfFileInput: document.getElementById('dxf-file-input'),
    cadLayersGroup: document.getElementById('cad-layers-group'),
    selectCadLayer: document.getElementById('select-cad-layer'),
    cadRedlineGroup: document.getElementById('cad-redline-group'),
    selectCadRedline: document.getElementById('select-cad-redline'),
    selectMskZone: document.getElementById('select-msk-zone'),
    mskDetectedBadge: document.getElementById('msk-detected-badge'),
    inputCadAssigned: document.getElementById('input-cad-assigned'),

    // Mode 3: Points / GPZU
    btnDigitizeMap: document.getElementById('btn-digitize-map'),
    digitizeStatusBadge: document.getElementById('digitize-status-badge'),
    textareaCoords: document.getElementById('textarea-coords'),
    btnApplyCoords: document.getElementById('btn-apply-coords'),
    gpzuDropzone: document.getElementById('gpzu-dropzone'),
    gpzuDropzoneText: document.getElementById('gpzu-dropzone-text'),
    gpzuFileInput: document.getElementById('gpzu-file-input'),

    // Orientation & Setbacks
    sliderRotation: document.getElementById('slider-rotation'),
    valRotation: document.getElementById('val-rotation'),
    angleBtns: document.querySelectorAll('.angle-btn[data-rot]'),
    btnResetLanding: document.getElementById('btn-reset-landing'),
    sliderBoundarySetback: document.getElementById('slider-boundary-setback'),
    valBoundarySetback: document.getElementById('val-boundary-setback'),
    sliderRedlineSetback: document.getElementById('slider-redline-setback'),
    valRedlineSetback: document.getElementById('val-redline-setback'),
    chkRedlines: document.getElementById('chk-redlines'),
    chkZouit: document.getElementById('chk-zouit'),

    // Lock Site Button
    btnLockSite: document.getElementById('btn-lock-site'),
    btnLockText: document.getElementById('btn-lock-text'),

    // Center Canvas
    tabCanvasOsm: document.getElementById('tab-canvas-osm'),
    tabCanvasSvg: document.getElementById('tab-canvas-svg'),
    canvasPanes: {
      osm: document.getElementById('pane-osm'),
      svg: document.getElementById('pane-svg')
    },
    canvasEmptyState: document.getElementById('canvas-empty-state'),
    iframeOsm: document.getElementById('iframe-osm'),
    cadZoomControls: document.getElementById('cad-zoom-controls'),
    btnZoomIn: document.getElementById('btn-zoom-in'),
    btnZoomReset: document.getElementById('btn-zoom-reset'),
    btnZoomOut: document.getElementById('btn-zoom-out'),
    compassSvg: document.getElementById('compass-svg'),
    labelCoords: document.getElementById('label-coords'),
    labelDimensions: document.getElementById('label-dimensions'),

    // Right Panel: Passport & Geoportals
    verificationCard: document.getElementById('verification-card'),
    verifTitle: document.getElementById('verif-title'),
    verifDesc: document.getElementById('verif-desc'),
    pCad: document.getElementById('p-cad'),
    pAreaHa: document.getElementById('p-area-ha'),
    pAreaSqm: document.getElementById('p-area-sqm'),
    pRegion: document.getElementById('p-region'),
    pAddress: document.getElementById('p-address'),
    pDimensions: document.getElementById('p-dimensions'),
    pVertices: document.getElementById('p-vertices'),
    pBuildableArea: document.getElementById('p-buildable-area'),
    pZouitStatus: document.getElementById('p-zouit-status'),
    pCrs: document.getElementById('p-crs'),
    linkYandex: document.getElementById('link-yandex'),
    linkPkk: document.getElementById('link-pkk'),

    // SVG World
    svgCanvas: document.getElementById('svg-canvas'),
    svgWorld: document.getElementById('svg-world')
  };

  // --- NUMBER FORMATTERS ---
  const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
  const nfInt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

  function fmtNum(val) {
    if (val === undefined || val === null || isNaN(val)) return '—';
    return nf.format(val);
  }

  function fmtInt(val) {
    if (val === undefined || val === null || isNaN(val)) return '—';
    return nfInt.format(val);
  }

  // --- SVG PAN & ZOOM STATE ---
  const panZoom = {
    scale: 1,
    tx: 0,
    ty: 0,
    isDragging: false,
    startX: 0,
    startY: 0
  };

  function applySvgTransform() {
    if (!el.svgWorld) return;
    el.svgWorld.setAttribute(
      'transform',
      `matrix(${panZoom.scale} 0 0 ${panZoom.scale} ${panZoom.tx} ${panZoom.ty})`
    );
  }

  function fitSvgToViewport(viewBoxStr) {
    if (!viewBoxStr || !el.svgCanvas) return;
    const parts = viewBoxStr.split(/\s+|,/).map(parseFloat);
    if (parts.length < 4) return;
    const [, , vbW, vbH] = parts;

    const vpRect = el.svgCanvas.getBoundingClientRect();
    if (!vpRect.width || !vpRect.height) return;

    const pad = 60;
    const scaleX = (vpRect.width - pad * 2) / vbW;
    const scaleY = (vpRect.height - pad * 2) / vbH;
    const fitScale = Math.min(scaleX, scaleY);

    panZoom.scale = fitScale > 0 ? fitScale : 1;
    panZoom.tx = (vpRect.width - vbW * panZoom.scale) / 2;
    panZoom.ty = (vpRect.height - vbH * panZoom.scale) / 2;
    applySvgTransform();
  }

  // --- EMPTY INITIAL STATE ---
  function initEmptyState() {
    if (el.canvasEmptyState) el.canvasEmptyState.style.display = 'flex';
    if (el.iframeOsm) el.iframeOsm.style.display = 'none';

    if (el.hdrParcelBadge) el.hdrParcelBadge.textContent = 'Ожидание ввода ЗУ';
    if (el.panelHeroArea) el.panelHeroArea.textContent = '— га';

    if (el.verificationCard) {
      el.verificationCard.className = 'verification-card unverified';
      el.verifTitle.textContent = 'Участок не выбран';
      el.verifDesc.textContent = 'Введите кадастровый номер ЗУ в левой панели для получения параметров Росреестра и привязки.';
    }

    if (el.pCad) el.pCad.textContent = '—';
    if (el.pAreaHa) el.pAreaHa.textContent = '—';
    if (el.pAreaSqm) el.pAreaSqm.textContent = '—';
    if (el.pRegion) el.pRegion.textContent = '—';
    if (el.pAddress) el.pAddress.textContent = '—';
    if (el.pDimensions) el.pDimensions.textContent = '—';
    if (el.pVertices) el.pVertices.textContent = '—';
    if (el.pBuildableArea) el.pBuildableArea.textContent = '—';
    if (el.pZouitStatus) el.pZouitStatus.textContent = '—';
    if (el.pCrs) el.pCrs.textContent = '—';

    if (el.labelCoords) el.labelCoords.textContent = 'WGS-84: [—]';
    if (el.labelDimensions) el.labelDimensions.textContent = 'Габариты: —';

    if (el.btnLockSite) {
      el.btnLockSite.style.opacity = '0.5';
      el.btnLockSite.style.pointerEvents = 'none';
    }

    if (el.linkYandex) {
      el.linkYandex.style.pointerEvents = 'none';
      el.linkYandex.style.opacity = '0.35';
      el.linkYandex.removeAttribute('href');
    }
    if (el.linkPkk) {
      el.linkPkk.style.pointerEvents = 'none';
      el.linkPkk.style.opacity = '0.35';
      el.linkPkk.removeAttribute('href');
    }

    if (el.backendStatusText) el.backendStatusText.textContent = 'Бэкенд активен';
  }

  // --- FORM DATA PAYLOAD GENERATOR ---
  function getPayload() {
    let sendOverrideLat = 0.0;
    let sendOverrideLon = 0.0;

    if (state.userHasMovedSite && state.override_lat && state.override_lon) {
      sendOverrideLat = state.override_lat;
      sendOverrideLon = state.override_lon;
    } else if (state.userHasEnteredManualCoords) {
      const mLat = parseFloat(el.inputManualLat ? el.inputManualLat.value : '') || 0.0;
      const mLon = parseFloat(el.inputManualLon ? el.inputManualLon.value : '') || 0.0;
      if (mLat !== 0.0 && mLon !== 0.0) {
        sendOverrideLat = mLat;
        sendOverrideLon = mLon;
      }
    }

    const payload = {
      site_mode: state.mode === 'cad' ? 'cad' : 'cadastre',
      site_rotation: state.site_rotation,
      override_lat: sendOverrideLat,
      override_lon: sendOverrideLon,
      boundary_setback: state.boundary_setback,
      red_line_setback: state.red_line_setback,
      enable_red_line: state.enable_red_line,
      msk_zone: state.msk_zone,
      stage: 1,
      preview_only: true
    };

    if (state.mode === 'cadastre') {
      payload.cad_query = state.cad_query;
      payload.custom_area = state.custom_area;
      if (state.gpzu_coordinates) {
        payload.gpzu_coordinates = state.gpzu_coordinates;
      }
    } else if (state.mode === 'cad') {
      payload.cad_file_base64 = state.cad_file_base64;
      payload.cad_filename = state.cad_filename;
      payload.boundary_layer = state.boundary_layer;
      payload.red_lines_layer = state.red_lines_layer;
      payload.assigned_cad_query = state.assigned_cad_query || state.cad_query;
    } else if (state.mode === 'points') {
      payload.cad_query = state.cad_query;
      payload.gpzu_coordinates = state.gpzu_coordinates;
    }

    return payload;
  }

  // --- API CALL: SITE PREVIEW (ШАГ 1) ---
  let previewDebounceTimer = null;

  async function apiPreviewSite(isDirect = false) {
    if (!isDirect) {
      clearTimeout(previewDebounceTimer);
      previewDebounceTimer = setTimeout(() => apiPreviewSite(true), 150);
      return;
    }

    // Check if we have enough data to preview
    if (state.mode === 'cadastre' && !state.cad_query && !state.gpzu_coordinates) {
      initEmptyState();
      return;
    }
    if (state.mode === 'cad' && !state.cad_file_base64) {
      initEmptyState();
      if (el.backendStatusText) el.backendStatusText.textContent = 'Ожидание файла DXF';
      return;
    }
    if (state.mode === 'points' && !state.gpzu_coordinates && !state.cad_query) {
      initEmptyState();
      return;
    }

    try {
      state.isBusy = true;
      el.backendStatusText.textContent = 'Расчет посадки...';

      const payload = getPayload();

      const res = await fetch('/api/site-preview', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errText = await res.text();
        throw new Error(errText || 'Ошибка /api/site-preview');
      }

      const data = await res.json();
      state.currentData = data;
      renderSite(data);

      el.backendStatusText.textContent = 'Бэкенд активен';
    } catch (err) {
      console.error('apiPreviewSite error:', err);
      el.backendStatusText.textContent = 'Ошибка расчета посадки';
    } finally {
      state.isBusy = false;
    }
  }

  // --- RENDER SITE DATA ON MAP, CANVAS AND PASSPORT ---
  function renderSite(data) {
    if (!data) return;

    // 1. Hide Empty State, show Leaflet iframe
    if (el.canvasEmptyState) el.canvasEmptyState.style.display = 'none';
    if (el.iframeOsm) el.iframeOsm.style.display = 'block';

    const areaHa = data.site_area_ha ? `${fmtNum(data.site_area_ha)} га` : `${((data.site_area_sqm || 0) / 10000).toFixed(2)} га`;
    const cadNum = data.cadastral_number || state.cad_query || 'Не присвоен';
    const region = data.region_name || 'РФ';
    const district = data.district_name || data.address || '';

    // 2. Header & Hero Badges
    el.hdrParcelBadge.textContent = `${region.split(' ')[0]} • ${areaHa}`;
    el.panelHeroArea.textContent = areaHa;

    // 3. Right Panel: Land Passport
    el.pCad.textContent = cadNum;
    el.pAreaHa.textContent = areaHa;
    el.pAreaSqm.textContent = `${fmtInt(data.site_area_sqm || 0)} м²`;
    el.pRegion.textContent = region;
    el.pAddress.textContent = district || '—';

    // Dimensions
    if (data.site_dimensions && data.site_dimensions.length >= 2) {
      const dimStr = `${Math.round(data.site_dimensions[0])} × ${Math.round(data.site_dimensions[1])} м`;
      el.pDimensions.textContent = dimStr;
      el.labelDimensions.textContent = `Габариты: ${dimStr}`;
    }

    // Vertices count
    const vertCount = data.vertices_count || (data.boundary_coords ? data.boundary_coords.length : 0);
    el.pVertices.textContent = `${vertCount} точек`;

    // Buildable Area
    const buildable = data.buildable_area_sqm || Math.round((data.site_area_sqm || 0) * 0.82);
    el.pBuildableArea.textContent = `${fmtInt(buildable)} м²`;

    // ZOUIT Status
    const hasZouit = data.zouit_paths && data.zouit_paths.length > 0;
    el.pZouitStatus.textContent = hasZouit ? `Обнаружено: ${data.zouit_paths.length}` : 'Не обнаружены';
    el.pZouitStatus.style.color = hasZouit ? 'var(--warning)' : 'var(--text-secondary)';

    // Coordinate System (CRS)
    const mskName = (data.cad_info && data.cad_info.detected_msk) || state.msk_zone || 'WGS-84';
    el.pCrs.textContent = `${mskName}`;

    // Verification Card
    el.verificationCard.className = 'verification-card verified';
    el.verifTitle.textContent = state.isLocked ? 'Посадка зафиксирована' : 'Геопривязка подтверждена';
    el.verifDesc.textContent = state.isLocked
      ? `Контур ${areaHa} зафиксирован. Параметры переданы в расчет застройки и ТЭП.`
      : `Координаты проверены. Перетаскивайте контур или вращайте оранжевым маркером на карте.`;

    // 4. Center Canvas Status & Geoportals Links
    if (data.geo_center) {
      const { lat, lon } = data.geo_center;
      el.labelCoords.textContent = `WGS-84: [${lat.toFixed(5)}, ${lon.toFixed(5)}]`;

      if (el.linkYandex) {
        el.linkYandex.href = `https://yandex.ru/maps/?pt=${lon},${lat}&z=16&l=map`;
        el.linkYandex.style.pointerEvents = 'auto';
        el.linkYandex.style.opacity = '1';
      }
      if (el.linkPkk) {
        el.linkPkk.href = `https://pkk.rosreestr.ru/#/search/${lat},${lon}/16`;
        el.linkPkk.style.pointerEvents = 'auto';
        el.linkPkk.style.opacity = '1';
      }

      if (!state.userHasMovedSite && !state.userHasEnteredManualCoords) {
        if (el.inputManualLat) el.inputManualLat.placeholder = lat.toFixed(5);
        if (el.inputManualLon) el.inputManualLon.placeholder = lon.toFixed(5);
      }
    }

    // 5. Update Compass
    const rot = data.site_rotation !== undefined ? data.site_rotation : state.site_rotation;
    if (el.compassSvg) {
      el.compassSvg.style.transform = `rotate(${-rot}deg)`;
    }

    // 6. Populate CAD Layers (Mode 2)
    if (data.cad_info) {
      if (data.cad_info.detected_msk && el.selectMskZone) {
        const detMsk = data.cad_info.detected_msk;
        let opt = Array.from(el.selectMskZone.options).find(o => o.value === detMsk);
        if (!opt) {
          opt = document.createElement('option');
          opt.value = detMsk;
          opt.textContent = detMsk;
          el.selectMskZone.appendChild(opt);
        }
        el.selectMskZone.value = detMsk;
        if (el.mskDetectedBadge) {
          el.mskDetectedBadge.style.display = 'inline-block';
          el.mskDetectedBadge.textContent = detMsk.split(' ')[0];
          el.mskDetectedBadge.title = detMsk;
        }
      }

      if (data.cad_info.layers && data.cad_info.layers.length > 0) {
        populateCadLayers(data.cad_info.layers, data.cad_info.boundary_layer, data.cad_info.red_lines_layer);
      }
    }

    // 7. Center Canvas: Leaflet OSM Map Iframe
    if (data.leaflet_html && data.leaflet_html !== state.lastLeafletHtml) {
      state.lastLeafletHtml = data.leaflet_html;
      if (el.iframeOsm) {
        el.iframeOsm.srcdoc = data.leaflet_html;
      }
    }

    // 8. Enable Lock Site button
    if (el.btnLockSite) {
      el.btnLockSite.style.opacity = '1';
      el.btnLockSite.style.pointerEvents = 'auto';
    }

    // 9. Center Canvas: 2D Vector CAD SVG
    renderSvgWorld(data);
  }

  function populateCadLayers(layers, activeBoundary, activeRedline) {
    if (!el.cadLayersGroup || !el.selectCadLayer) return;
    el.cadLayersGroup.style.display = 'block';
    el.selectCadLayer.innerHTML = '<option value="">— Авто-выбор слоя границы —</option>';

    if (el.cadRedlineGroup && el.selectCadRedline) {
      el.cadRedlineGroup.style.display = 'block';
      el.selectCadRedline.innerHTML = '<option value="">— Без красных линий —</option>';
    }

    layers.forEach(lyr => {
      const bOpt = document.createElement('option');
      bOpt.value = lyr.name;
      bOpt.textContent = `${lyr.name} (${lyr.count} эл.)${lyr.is_candidate ? ' ★' : ''}`;
      if (activeBoundary && lyr.name === activeBoundary) bOpt.selected = true;
      el.selectCadLayer.appendChild(bOpt);

      if (el.selectCadRedline) {
        const rOpt = document.createElement('option');
        rOpt.value = lyr.name;
        rOpt.textContent = `${lyr.name} (${lyr.count} эл.)${lyr.is_redline ? ' [Красная линия]' : ''}`;
        if (activeRedline && lyr.name === activeRedline) rOpt.selected = true;
        el.selectCadRedline.appendChild(rOpt);
      }
    });
  }

  function renderSvgWorld(data) {
    if (!data || !el.svgWorld) return;

    let svgMarkup = '';

    // 1. ZOUIT Zones
    if (state.zouit_active && data.zouit_paths) {
      data.zouit_paths.forEach(p => {
        svgMarkup += `<path d="${p}" fill="rgba(239, 68, 68, 0.12)" stroke="#ef4444" stroke-width="1.5" stroke-dasharray="4,4" />`;
      });
    }

    // 2. Site Boundary
    if (data.site_path) {
      svgMarkup += `<path id="cad-site-bound" d="${data.site_path}" fill="rgba(56, 189, 248, 0.08)" stroke="#38bdf8" stroke-width="2.5" />`;
    }

    // 3. Buildable zone (Setback)
    if (data.buildable_path) {
      svgMarkup += `<path id="cad-setback-bound" d="${data.buildable_path}" fill="none" stroke="#f59e0b" stroke-width="1.5" stroke-dasharray="6,4" />`;
    }

    // 4. Red Lines
    if (state.enable_red_line && data.red_lines_paths) {
      data.red_lines_paths.forEach(p => {
        svgMarkup += `<path d="${p}" fill="none" stroke="#f43f5e" stroke-width="2.5" />`;
      });
    }

    el.svgWorld.innerHTML = svgMarkup;
    fitSvgToViewport(data.svg_viewbox || '0 0 1000 700');
  }

  // --- BI-DIRECTIONAL POSTMESSAGE LISTENER (LEAFLET IFRAME ↔ STUDIO) ---
  window.addEventListener('message', function (e) {
    if (!e.data) return;

    // 1. Интерактивная трансформация на карте (перетаскивание или вращение)
    if (e.data.isMapTransform) {
      const t = e.data.transform;
      if (!t) return;

      // Обновление поворота при вращении маркером
      if (t.map_rot !== undefined && !isNaN(t.map_rot)) {
        state.site_rotation = t.map_rot;
        el.sliderRotation.value = t.map_rot;
        el.valRotation.textContent = `${t.map_rot > 0 ? '+' : ''}${t.map_rot.toFixed(1)}°`;
        if (el.compassSvg) {
          el.compassSvg.style.transform = `rotate(${-t.map_rot}deg)`;
        }
      }

      // Обновление координат при перетаскивании полигона
      if (t.map_lat && t.map_lon && t.dist_m > 0.1) {
        state.userHasMovedSite = true;
        state.override_lat = t.map_lat;
        state.override_lon = t.map_lon;
        if (el.inputManualLat) el.inputManualLat.value = t.map_lat.toFixed(5);
        if (el.inputManualLon) el.inputManualLon.value = t.map_lon.toFixed(5);
        el.labelCoords.textContent = `WGS-84: [${t.map_lat.toFixed(5)}, ${t.map_lon.toFixed(5)}]`;
      }

      // Нажата кнопка «Зафиксировать» в HUD карты
      if (t.lock) {
        setSiteLocked(true);
      }
      return;
    }

    // 2. Оцифровка контура кликами по карте (Режим 3: Точки)
    if (e.data.type === 'contourDigitized' && e.data.points && e.data.points.length >= 3) {
      const pts = e.data.points; // массив [lat, lon]
      const txt = pts.map((p, idx) => `${idx + 1}\t${p[0].toFixed(6)}\t${p[1].toFixed(6)}`).join('\n');
      state.gpzu_coordinates = txt;
      el.textareaCoords.value = txt;
      state.userHasMovedSite = false;
      state.override_lat = 0.0;
      state.override_lon = 0.0;
      if (el.digitizeStatusBadge) {
        el.digitizeStatusBadge.style.display = 'block';
        el.digitizeStatusBadge.textContent = `✓ Контур оцифрован по карте: ${pts.length} точек`;
      }
      apiPreviewSite(true);
      return;
    }

    // 3. Выбор точки центра на карте
    if (e.data.type === 'mapPointPicked') {
      const pLat = Number(e.data.lat);
      const pLon = Number(e.data.lon);
      state.userHasMovedSite = true;
      state.userHasEnteredManualCoords = true;
      state.override_lat = pLat;
      state.override_lon = pLon;
      if (el.inputManualLat) el.inputManualLat.value = pLat.toFixed(5);
      if (el.inputManualLon) el.inputManualLon.value = pLon.toFixed(5);
      el.labelCoords.textContent = `WGS-84: [${pLat.toFixed(5)}, ${pLon.toFixed(5)}]`;
      apiPreviewSite(true);
      return;
    }
  });

  // --- LOCK / UNLOCK SITE ---
  function setSiteLocked(locked) {
    if (!state.currentData) return;
    state.isLocked = locked;
    if (state.isLocked) {
      el.btnLockSite.classList.add('locked');
      el.btnLockText.textContent = '✓ Участок зафиксирован (нажмите для смены)';
      el.stepperStep1.classList.remove('active');
      el.stepperStep2.classList.add('active');
      el.stepperStep2.style.opacity = '1';
      if (state.currentData) {
        el.verifTitle.textContent = 'Посадка зафиксирована';
        el.verifDesc.textContent = 'Параметры ЗУ готовы к переходу на Шаг 2 (Застройка и ТЭП).';
      }
    } else {
      el.btnLockSite.classList.remove('locked');
      el.btnLockText.textContent = '🔒 Зафиксировать посадку участка';
      el.stepperStep1.classList.add('active');
      el.stepperStep2.classList.remove('active');
      el.stepperStep2.style.opacity = '0.5';
      if (state.currentData) {
        el.verifTitle.textContent = 'Геопривязка подтверждена';
        el.verifDesc.textContent = 'Участок точно спозиционирован. Вращайте и перемещайте по спутнику.';
      }
    }
  }

  // --- CADASTRE INPUT ACTION HANDLERS ---
  function loadCadastreSite() {
    const val = el.inputCadNum.value.trim();
    if (!val) {
      el.inputCadNum.focus();
      return;
    }
    state.cad_query = val;
    state.userHasMovedSite = false;
    state.userHasEnteredManualCoords = false;
    state.override_lat = 0.0;
    state.override_lon = 0.0;
    if (el.inputManualLat) el.inputManualLat.value = '';
    if (el.inputManualLon) el.inputManualLon.value = '';
    apiPreviewSite(true);
  }

  if (el.btnLoadCadastre) {
    el.btnLoadCadastre.addEventListener('click', loadCadastreSite);
  }

  if (el.inputCadNum) {
    el.inputCadNum.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        loadCadastreSite();
      }
    });
  }

  // Quick hint chips
  document.querySelectorAll('.cad-hint-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const cad = chip.dataset.cad;
      if (cad) {
        el.inputCadNum.value = cad;
        loadCadastreSite();
      }
    });
  });

  // Mode Switcher (1. Кадастр | 2. CAD | 3. Точки)
  el.modeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.mode;
      state.mode = mode;

      el.modeBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      Object.keys(el.panes).forEach(paneKey => {
        el.panes[paneKey].classList.toggle('active', paneKey === mode);
      });

      apiPreviewSite();
    });
  });

  // Mode 1: Custom Area
  if (el.inputCustomArea) {
    el.inputCustomArea.addEventListener('change', () => {
      state.custom_area = parseFloat(el.inputCustomArea.value) || 42500;
      if (state.currentData) apiPreviewSite();
    });
  }

  // Mode 1: Fetch PKK
  el.btnFetchPkk.addEventListener('click', async () => {
    const cadNum = el.inputCadNum.value.trim();
    if (!cadNum) {
      el.inputCadNum.focus();
      return;
    }
    try {
      el.btnFetchPkk.textContent = '...';
      const res = await fetch('/api/pkk-lookup', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cadastral_number: cadNum })
      });
      const data = await res.json();
      if (data.success) {
        state.cad_query = cadNum;
        el.pkkBadge.style.display = 'block';
        el.pkkBadge.textContent = '✓ Границы подтверждены ПКК Росреестра';
        apiPreviewSite(true);
      } else {
        alert(data.error || 'Границы не найдены на Публичной кадастровой карте');
      }
    } catch (e) {
      console.error('PKK lookup error:', e);
    } finally {
      el.btnFetchPkk.textContent = '🌐 ПКК';
    }
  });

  // Mode 1: Manual Coordinates
  function onManualCoordsChange() {
    const lat = parseFloat(el.inputManualLat ? el.inputManualLat.value : '') || 0.0;
    const lon = parseFloat(el.inputManualLon ? el.inputManualLon.value : '') || 0.0;
    if (lat !== 0.0 && lon !== 0.0) {
      state.userHasMovedSite = true;
      state.userHasEnteredManualCoords = true;
      state.override_lat = lat;
      state.override_lon = lon;
      apiPreviewSite();
    }
  }

  if (el.inputManualLat) el.inputManualLat.addEventListener('change', onManualCoordsChange);
  if (el.inputManualLon) el.inputManualLon.addEventListener('change', onManualCoordsChange);

  // Mode 1: Pick Point on Map
  if (el.btnPickPointCadastre) {
    el.btnPickPointCadastre.addEventListener('click', () => {
      setCanvasView('osm');
      if (el.iframeOsm && el.iframeOsm.contentWindow) {
        el.iframeOsm.contentWindow.postMessage({ type: 'startPickPoint' }, '*');
      }
    });
  }

  // Mode 2: DXF Upload
  el.dxfDropzone.addEventListener('click', () => el.dxfFileInput.click());
  el.dxfFileInput.addEventListener('change', e => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      const b64 = reader.result.split(',')[1];
      state.cad_file_base64 = b64;
      state.cad_filename = file.name;
      el.dxfDropzoneText.textContent = `✓ Загружен: ${file.name}`;

      // Inspect CAD layers
      try {
        const res = await fetch('/api/inspect-cad', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_base64: b64, filename: file.name })
        });
        const d = await res.json();
        if (d.layers && d.layers.length) {
          populateCadLayers(d.layers, d.boundary_layer, d.red_lines_layer);
        }
      } catch (err) {
        console.warn('CAD inspect error:', err);
      }

      apiPreviewSite(true);
    };
    reader.readAsDataURL(file);
  });

  el.selectCadLayer.addEventListener('change', () => {
    state.boundary_layer = el.selectCadLayer.value || null;
    apiPreviewSite(true);
  });

  if (el.selectCadRedline) {
    el.selectCadRedline.addEventListener('change', () => {
      state.red_lines_layer = el.selectCadRedline.value || null;
      apiPreviewSite(true);
    });
  }

  el.selectMskZone.addEventListener('change', () => {
    state.msk_zone = el.selectMskZone.value;
    if (state.currentData) apiPreviewSite(true);
  });

  if (el.inputCadAssigned) {
    el.inputCadAssigned.addEventListener('change', () => {
      state.assigned_cad_query = el.inputCadAssigned.value.trim();
      if (state.currentData) apiPreviewSite(true);
    });
  }

  // Mode 3: Digitize on Satellite Map
  el.btnDigitizeMap.addEventListener('click', () => {
    setCanvasView('osm');
    if (!state.currentData) {
      // Инициализируем спутниковую карту для нанесения точек
      state.cad_query = '63:01:0709002:2320';
      apiPreviewSite(true).then(() => {
        setTimeout(() => {
          if (el.iframeOsm && el.iframeOsm.contentWindow) {
            el.iframeOsm.contentWindow.postMessage({ type: 'startDigitizeContour' }, '*');
          }
        }, 500);
      });
    } else {
      if (el.iframeOsm && el.iframeOsm.contentWindow) {
        el.iframeOsm.contentWindow.postMessage({ type: 'startDigitizeContour' }, '*');
      }
    }
  });

  // Mode 3: Apply Coordinates from textarea
  el.btnApplyCoords.addEventListener('click', async () => {
    const rawText = el.textareaCoords.value.trim();
    if (!rawText) return;
    try {
      const res = await fetch('/api/parse-gpzu', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: rawText, msk_zone: state.msk_zone })
      });
      const data = await res.json();
      if (data.success && data.coordinates && data.coordinates.length) {
        state.gpzu_coordinates = rawText;
        if (el.digitizeStatusBadge) {
          el.digitizeStatusBadge.style.display = 'block';
          el.digitizeStatusBadge.textContent = `✓ Загружено точек: ${data.coordinates.length}`;
        }
        apiPreviewSite(true);
      } else {
        alert(data.error || 'Не удалось распознать каталог координат');
      }
    } catch (e) {
      console.error('Parse coords error:', e);
    }
  });

  // Mode 3: GPZU upload (.pdf / .xlsx / .txt)
  el.gpzuDropzone.addEventListener('click', () => el.gpzuFileInput.click());
  el.gpzuFileInput.addEventListener('change', e => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = async () => {
      const b64 = reader.result.split(',')[1];
      try {
        const res = await fetch('/api/upload-gpzu', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_base64: b64, filename: file.name, msk_zone: state.msk_zone })
        });
        const d = await res.json();
        if (d.success && d.coordinates && d.coordinates.length) {
          const txt = d.coordinates.map((p, idx) => `${idx + 1}\t${p.x || p[0]}\t${p.y || p[1]}`).join('\n');
          state.gpzu_coordinates = txt;
          el.textareaCoords.value = txt;
          el.gpzuDropzoneText.textContent = `✓ Загружен: ${file.name}`;
          if (el.digitizeStatusBadge) {
            el.digitizeStatusBadge.style.display = 'block';
            el.digitizeStatusBadge.textContent = `✓ Извлечено точек: ${d.coordinates.length}`;
          }
          apiPreviewSite(true);
        } else {
          alert(d.error || 'Не удалось извлечь поворотные точки из ГПЗУ');
        }
      } catch (err) {
        console.error('Upload GPZU error:', err);
      }
    };
    reader.readAsDataURL(file);
  });

  // Orientation & Setbacks
  el.sliderRotation.addEventListener('input', () => {
    const val = parseFloat(el.sliderRotation.value);
    state.site_rotation = val;
    el.valRotation.textContent = `${val > 0 ? '+' : ''}${val.toFixed(1)}°`;
    if (el.compassSvg) {
      el.compassSvg.style.transform = `rotate(${-val}deg)`;
    }
  });

  el.sliderRotation.addEventListener('change', () => {
    if (state.currentData) apiPreviewSite(true);
  });

  el.angleBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const rot = parseFloat(btn.dataset.rot);
      state.site_rotation = rot;
      el.sliderRotation.value = rot;
      el.valRotation.textContent = `${rot > 0 ? '+' : ''}${rot.toFixed(1)}°`;
      if (el.compassSvg) {
        el.compassSvg.style.transform = `rotate(${-rot}deg)`;
      }
      if (state.currentData) apiPreviewSite(true);
    });
  });

  // Reset Landing Button
  if (el.btnResetLanding) {
    el.btnResetLanding.addEventListener('click', () => {
      state.site_rotation = 0.0;
      state.override_lat = 0.0;
      state.override_lon = 0.0;
      state.userHasMovedSite = false;
      state.userHasEnteredManualCoords = false;

      el.sliderRotation.value = 0;
      el.valRotation.textContent = '0.0°';
      if (el.compassSvg) el.compassSvg.style.transform = 'rotate(0deg)';
      if (el.inputManualLat) el.inputManualLat.value = '';
      if (el.inputManualLon) el.inputManualLon.value = '';

      if (state.currentData) apiPreviewSite(true);
    });
  }

  el.sliderBoundarySetback.addEventListener('input', () => {
    const val = parseInt(el.sliderBoundarySetback.value, 10);
    state.boundary_setback = val;
    el.valBoundarySetback.textContent = `${val} м`;
  });

  el.sliderBoundarySetback.addEventListener('change', () => {
    if (state.currentData) apiPreviewSite(true);
  });

  el.sliderRedlineSetback.addEventListener('input', () => {
    const val = parseInt(el.sliderRedlineSetback.value, 10);
    state.red_line_setback = val;
    el.valRedlineSetback.textContent = `${val} м`;
  });

  el.sliderRedlineSetback.addEventListener('change', () => {
    if (state.currentData) apiPreviewSite(true);
  });

  el.chkRedlines.addEventListener('change', () => {
    state.enable_red_line = el.chkRedlines.checked;
    if (state.currentData) apiPreviewSite(true);
  });

  el.chkZouit.addEventListener('change', () => {
    state.zouit_active = el.chkZouit.checked;
    if (state.currentData) renderSite(state.currentData);
  });

  // Lock Site Button
  el.btnLockSite.addEventListener('click', () => {
    setSiteLocked(!state.isLocked);
  });

  // Stepper Header click
  if (el.stepperStep1) {
    el.stepperStep1.addEventListener('click', () => {
      if (state.isLocked) setSiteLocked(false);
    });
  }
  if (el.stepperStep2) {
    el.stepperStep2.addEventListener('click', () => {
      if (!state.isLocked) setSiteLocked(true);
    });
  }

  // Center Canvas Viewport Switcher
  function setCanvasView(viewKey) {
    state.activeView = viewKey;

    el.tabCanvasOsm.classList.toggle('active', viewKey === 'osm');
    el.tabCanvasSvg.classList.toggle('active', viewKey === 'svg');

    el.canvasPanes.osm.classList.toggle('active', viewKey === 'osm');
    el.canvasPanes.svg.classList.toggle('active', viewKey === 'svg');

    if (el.cadZoomControls) {
      el.cadZoomControls.style.display = viewKey === 'svg' ? 'flex' : 'none';
    }

    if (viewKey === 'svg' && state.currentData) {
      fitSvgToViewport(state.currentData.svg_viewbox || '0 0 1000 700');
    }
  }

  el.tabCanvasOsm.addEventListener('click', () => setCanvasView('osm'));
  el.tabCanvasSvg.addEventListener('click', () => setCanvasView('svg'));

  // SVG Pan & Zoom Handlers (2D CAD Tab)
  el.svgCanvas.addEventListener(
    'wheel',
    e => {
      e.preventDefault();
      const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
      const rect = el.svgCanvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      panZoom.tx = mouseX - (mouseX - panZoom.tx) * zoomFactor;
      panZoom.ty = mouseY - (mouseY - panZoom.ty) * zoomFactor;
      panZoom.scale *= zoomFactor;
      applySvgTransform();
    },
    { passive: false }
  );

  el.svgCanvas.addEventListener('mousedown', e => {
    if (e.button !== 0) return;
    panZoom.isDragging = true;
    panZoom.startX = e.clientX - panZoom.tx;
    panZoom.startY = e.clientY - panZoom.ty;
  });

  window.addEventListener('mousemove', e => {
    if (!panZoom.isDragging) return;
    panZoom.tx = e.clientX - panZoom.startX;
    panZoom.ty = e.clientY - panZoom.startY;
    applySvgTransform();
  });

  window.addEventListener('mouseup', () => {
    panZoom.isDragging = false;
  });

  el.btnZoomIn.addEventListener('click', () => {
    panZoom.scale *= 1.25;
    applySvgTransform();
  });

  el.btnZoomOut.addEventListener('click', () => {
    panZoom.scale *= 0.8;
    applySvgTransform();
  });

  el.btnZoomReset.addEventListener('click', () => {
    if (state.currentData) {
      fitSvgToViewport(state.currentData.svg_viewbox || '0 0 1000 700');
    }
  });

  // --- INITIALIZATION ---
  initEmptyState();
})();
