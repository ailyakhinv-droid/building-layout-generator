/**
 * URBAN / TEP STUDIO — ПОШАГОВЫЙ ПАЙПЛАЙН:
 * - Шаг 1: Посадка и проверка участка (Кадастр, CAD DXF, Точки ГПЗУ, спутник OSM)
 * - Шаг 2: Нарезка улично-дорожной сети (УДС) и подкварталов (СП 42.13330, СП 4.13130, CAD черчение)
 * - Шаг 3: Генерация застройки и ТЭП (Подготовка к следующему этапу)
 *
 * Архитектура: Impeccable CAD Slate / shadcn Light, tabular numbers, zero-latency feedback.
 */

(function () {
  'use strict';

  // --- APPLICATION STATE ---
  
  const REGIONAL_NORMS_DATA = {
    russia_sp42: {
      badge: 'СП 42',
      name: 'РФ (СП 42.13330.2016)',
      desc: '350 м/м на 1000 жителей (25% гостевые), 25.0 м² жилья на человека, норма озеленения ≥ 25%.'
    },
    moscow_mngp: {
      badge: 'МНГП',
      name: 'Москва (МНГП № 945-ПП)',
      desc: '350 м/м на 1000 жителей (20% гостевые), 28.2 м² жилья на человека, озеленение ≥ 25%.'
    },
    moscow_oblast_rngp: {
      badge: 'РНГП МО',
      name: 'Московская обл. (РНГП МО № 713/30)',
      desc: '420 м/м на 1000 жителей (25% гостевые), 28.0 м² жилья на человека, озеленение ≥ 25%.'
    },
    spb_rngp: {
      badge: 'РНГП СПб',
      name: 'Санкт-Петербург (РНГП СПб)',
      desc: '1 м/м на 80 м² жилой площади, 30.0 м² на человека, озеленение ≥ 30%.'
    },
    tyumen_mngp: {
      badge: 'МНГП ТО',
      name: 'Тюмень (МНГП г. Тюмени)',
      desc: '1 м/м на квартиру либо 350 м/м на 1000 жит., 25.0 м² на чел., озеленение ≥ 25%.'
    }
  };

  const state = {
    // Pipeline Step: 1 = Посадка ЗУ | 2 = Нарезка УДС | 3 = Застройка и ТЭП
    currentStep: 1,

    // Step 1: Посадка ЗУ
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
    enable_red_line: false,
    currentScenario: null,
    currentScenarios: [],
    activeVariantIndex: 0,
    lastVariantsMatrix: null,
    zouit_active: true,
    activeZouitZones: [],
    currentGpzuParsedData: null,
    max_floors: 14,
    max_height_m: 50.0,
    max_bcr: 40.0,
    max_far: 2.5,
    green_ratio: 25.0,
    msk_zone: 'МСК-63 Зона 1',
    cad_file_base64: null,
    cad_filename: null,
    boundary_layer: null,
    red_lines_layer: null,
    assigned_cad_query: '',
    gpzu_coordinates: null,
    isLocked: false,

    // Step 2 & 3: Нарезка УДС и Принципы застройки (как в обычном дашборде)
    road_preset: 'none', // 'none' | 'longitudinal' | 'transverse' | 'cross_2x2' | 'custom'
    road_category: 'district', // 'district' | 'arterial' | 'local' | 'custom'
    typology: 'AUTO', // 'AUTO' | 'PERIMETER' | 'TOWER' | 'U_SHAPE' | 'SECTIONAL'
    courtyard_orientation: 'SOUTH', // 'SOUTH' | 'EAST'
    preferred_section_ids: [], // Whitelist секций (пусто = все типы из библиотеки)
    sectionCatalog: [], // Полный каталог типовых секций из /api/library
    section_overrides: {}, // Численные переопределения min_floors, max_floors
    cascade_floors: true, // Каскадная форма с пониженными крыльями по СанПиН
    asymmetric_wings: true,
    variable_insolation: true,
    surrounding_height_overrides: {}, // Ручные переопределения высот окружающих зданий { osm_id: height_m }
    allow_towers_in_mixed: true,
    car_free_courtyard: true, // СП 113 Концепция «Двор без машин»
    only_ground_parking: false,
    allow_parking_in_zouit: false,
    regional_norm_id: 'russia_sp42',
    floor_height: 3.0,
    urban_block_size: 100.0,
    internal_road_width: 16.0,
    perimeter_layout_style: 'U_SHAPE',
    fire_gap_end_to_end: 10.0,
    fire_gap_parallel: 18.0,
    road_width: 15.0,
    road_setback: 4.0,
    road_pos: 0.5,
    road_pos_x: 0.5,
    road_pos_y: 0.5,
    custom_roads: [],
    isDrawingRoad: false,
    drawingRoadStart: null,
    activeHandleDrag: null,

    // Step 2: Entry Points (Въезды на границе)
    uds_mode: 'entries', // 'entries' | 'free_draw'
    isAddingEntryPoint: false,
    entry_points: [], // [{ id, name, x, y, category, width, setback }]
    activeEntryDrag: null,
    activePresetTemplate: null, // 'longitudinal' | 'transverse' | 'cross_2x2' | null

    // Max sections per building
    max_sections: 8,

    // Layer visibility
    layerVisibility: {
      fire: true,
      parking: true,
      tko: true,
      san: true
    },

    // Custom regional norms (RNGP)
    custom_regional_norm: null,

    // Viewport & Canvas
    activeView: 'osm', // 'osm' | 'svg'
    activeBasemap: 'osm', // 'osm' | 'satellite' | 'light' | 'none'
    basemapOpacity: 0.8,
    currentData: null,
    lastLeafletHtml: '',
    isBusy: false
  };

  // --- ENGINEERING LAYERS VISIBILITY CONTROLS ---
  function applyLayerVisibility() {
    if (el.svgFireSafetyLayer) {
      el.svgFireSafetyLayer.style.display = state.layerVisibility.fire ? '' : 'none';
    }
    if (el.svgParkingLayer) {
      el.svgParkingLayer.style.display = state.layerVisibility.parking ? '' : 'none';
    }
    if (el.svgTkoLayer) {
      el.svgTkoLayer.style.display = state.layerVisibility.tko ? '' : 'none';
    }
    if (el.svgParkingSanLayer) {
      el.svgParkingSanLayer.style.display = state.layerVisibility.san ? '' : 'none';
    }
  }

  function setupLayerToggleButtons() {
    const layerDefs = [
      { btn: el.btnToggleFire, key: 'fire' },
      { btn: el.btnToggleParking, key: 'parking' },
      { btn: el.btnToggleTko, key: 'tko' },
      { btn: el.btnToggleSan, key: 'san' }
    ];

    layerDefs.forEach(({ btn, key }) => {
      if (!btn) return;
      btn.addEventListener('click', () => {
        state.layerVisibility[key] = !state.layerVisibility[key];
        btn.classList.toggle('active', state.layerVisibility[key]);
        applyLayerVisibility();
      });
    });
  }

  // --- NUMBER FORMATTERS ---
  const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 1 });
  const nf2 = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 2 });
  const nfInt = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });

  function fmtNum(val) {
    if (val === undefined || val === null || isNaN(val)) return '—';
    return nf.format(val);
  }
  function fmtNum2(val) {
    if (val === undefined || val === null || isNaN(val)) return '—';
    return nf2.format(val);
  }
  function fmtInt(val) {
    if (val === undefined || val === null || isNaN(val)) return '—';
    return nfInt.format(val);
  }
  function round1(v) { return Math.round(v * 10) / 10; }
  function round2(v) { return Math.round(v * 100) / 100; }

  // --- DOM REFERENCES ---
  const el = {
    // Header & Stepper
    hdrParcelBadge: document.getElementById('hdr-parcel-badge'),
    stepperStep1: document.getElementById('stepper-step-1'),
    stepperStep2: document.getElementById('stepper-step-2'),
    stepperStep3: document.getElementById('stepper-step-3'),
    backendStatusText: document.getElementById('backend-status-text'),
    btnThemeToggle: document.getElementById('btn-theme-toggle'),
    themeIcon: document.getElementById('theme-icon'),
    themeLabel: document.getElementById('theme-label'),

    // Hero Badges
    panelHeroArea: document.getElementById('panel-hero-area'),
    panelHeroBlocks: document.getElementById('panel-hero-blocks'),

    // Step Panels (Left Panel)
    panelStep1Content: document.getElementById('panel-step-1-content'),
    panelStep2Content: document.getElementById('panel-step-2-content'),

    // Step 1: Mode Segmented Control
    modeBtns: document.querySelectorAll('.mode-btn'),
    panes: {
      cadastre: document.getElementById('pane-mode-cadastre'),
      cad: document.getElementById('pane-mode-cad'),
      points: document.getElementById('pane-mode-points')
    },

    // Step 1: Mode 1 Cadastre
    inputCadNum: document.getElementById('input-cad-num'),
    btnLoadCadastre: document.getElementById('btn-load-cadastre'),
    btnFetchPkk: document.getElementById('btn-fetch-pkk'),
    pkkBadge: document.getElementById('pkk-badge'),
    cadGpzuDropzone: document.getElementById('cad-gpzu-dropzone'),
    cadGpzuDropzoneText: document.getElementById('cad-gpzu-dropzone-text'),
    cadGpzuFileInput: document.getElementById('cad-gpzu-file-input'),
    cadGpzuStatusBadge: document.getElementById('cad-gpzu-status-badge'),
    inputCustomArea: document.getElementById('input-custom-area'),
    btnPickPointCadastre: document.getElementById('btn-pick-point-cadastre'),
    inputManualLat: document.getElementById('input-manual-lat'),
    inputManualLon: document.getElementById('input-manual-lon'),

    // Step 1: Mode 2 CAD
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
    chkCadSwapXy: document.getElementById('chk-cad-swap-xy'),

    // Step 1: Mode 3 Points / GPZU
    btnDigitizeMap: document.getElementById('btn-digitize-map'),
    digitizeStatusBadge: document.getElementById('digitize-status-badge'),
    textareaCoords: document.getElementById('textarea-coords'),
    btnApplyCoords: document.getElementById('btn-apply-coords'),
    gpzuDropzone: document.getElementById('gpzu-dropzone'),
    gpzuDropzoneText: document.getElementById('gpzu-dropzone-text'),
    gpzuFileInput: document.getElementById('gpzu-file-input'),

    // Step 1: Orientation & Setbacks
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
    btnLockSite: document.getElementById('btn-lock-site'),
    btnLockText: document.getElementById('btn-lock-text'),

    // Step 2: Roads Presets & Controls
    valPresetBadge: document.getElementById('val-preset-badge'),
    presetBtns: document.querySelectorAll('.road-preset-btn'),
    catPills: document.querySelectorAll('.cat-pill'),
    valCategoryPillTag: document.getElementById('val-category-pill-tag'),
    sliderRoadWidth: document.getElementById('slider-road-width'),
    valRoadWidth: document.getElementById('val-road-width'),
    sliderRoadSetback: document.getElementById('slider-road-setback'),
    valRoadSetback: document.getElementById('val-road-setback'),
    groupRoadPos: document.getElementById('group-road-pos'),
    sliderRoadPos: document.getElementById('slider-road-pos'),
    valRoadPos: document.getElementById('val-road-pos'),
    groupRoadPosGrid: document.getElementById('group-road-pos-grid'),
    sliderRoadPosX: document.getElementById('slider-road-pos-x'),
    sliderRoadPosY: document.getElementById('slider-road-pos-y'),
    valRoadPosXY: document.getElementById('val-road-pos-xy'),

    // Step 2: Custom Roads Drawing & Entry Points
    valCustomCount: document.getElementById('val-custom-count'),
    btnTabEntryPoints: document.getElementById('btn-tab-entry-points'),
    btnTabFreeDraw: document.getElementById('btn-tab-free-draw'),
    subviewEntryPoints: document.getElementById('subview-entry-points'),
    subviewFreeDraw: document.getElementById('subview-free-draw'),
    btnAddEntryPoint: document.getElementById('btn-add-entry-point'),
    btnEntryIcon: document.getElementById('btn-entry-icon'),
    btnEntryText: document.getElementById('btn-entry-text'),
    btnClearEntries: document.getElementById('btn-clear-entries'),
    entryRoadHint: document.getElementById('entry-road-hint'),
    entryPointsList: document.getElementById('entry-points-list'),
    svgEntryPointsLayer: document.getElementById('svg-entry-points-layer'),

    btnDrawRoad: document.getElementById('btn-draw-road'),
    btnDrawIcon: document.getElementById('btn-draw-icon'),
    btnDrawText: document.getElementById('btn-draw-text'),
    btnClearRoads: document.getElementById('btn-clear-roads'),
    drawRoadHint: document.getElementById('draw-road-hint'),
    customRoadsList: document.getElementById('custom-roads-list'),

    // Step 2: Navigation Footer
    btnStep2Back: document.getElementById('btn-step2-back'),
    btnStep2Proceed: document.getElementById('btn-step2-proceed'),

    // Center Canvas
    tabCanvasOsm: document.getElementById('tab-canvas-osm'),
    tabCanvasSvg: document.getElementById('tab-canvas-svg'),
    tabCanvas3d: document.getElementById('tab-canvas-3d'),
    canvasPanes: {
      osm: document.getElementById('pane-osm'),
      svg: document.getElementById('pane-svg'),
      view3d: document.getElementById('pane-3d')
    },
    iframe3d: document.getElementById('iframe-3d'),
    dock3dScenarios: document.getElementById('dock-3d-scenarios'),
    dockScenarioButtons: document.getElementById('dock-scenario-buttons'),
    canvasLoadingOverlay: document.getElementById('canvas-loading-overlay'),
    canvasLoadingText: document.getElementById('canvas-loading-text'),
    canvasEmptyState: document.getElementById('canvas-empty-state'),
    iframeOsm: document.getElementById('iframe-osm'),
    cadZoomControls: document.getElementById('cad-zoom-controls'),
    btnZoomIn: document.getElementById('btn-zoom-in'),
    btnZoomReset: document.getElementById('btn-zoom-reset'),
    btnZoomOut: document.getElementById('btn-zoom-out'),
    compassSvg: document.getElementById('compass-svg'),
    labelCoords: document.getElementById('label-coords'),
    labelDimensions: document.getElementById('label-dimensions'),

    // Canvas Engineering Layer Toggles
    canvasLayersBar: document.getElementById('canvas-layers-bar'),
    btnToggleFire: document.getElementById('btn-toggle-fire'),
    btnToggleParking: document.getElementById('btn-toggle-parking'),
    btnToggleTko: document.getElementById('btn-toggle-tko'),
    btnToggleSan: document.getElementById('btn-toggle-san'),

    // Step 3 Building sliders
    sliderStep3MaxSections: document.getElementById('slider-step3-max-sections'),
    labelStep3MaxSections: document.getElementById('label-step3-max-sections'),

    // RNGP Fine-tuning Inputs
    inputRngpChildren: document.getElementById('input-rngp-children'),
    inputRngpSport: document.getElementById('input-rngp-sport'),
    inputRngpRelax: document.getElementById('input-rngp-relax'),
    inputRngpUtility: document.getElementById('input-rngp-utility'),
    inputRngpLiving: document.getElementById('input-rngp-living'),
    inputRngpParkingRatio: document.getElementById('input-rngp-parking-ratio'),
    inputRngpGuestShare: document.getElementById('input-rngp-guest-share'),
    inputRngpAreaPerCar: document.getElementById('input-rngp-area-per-car'),

    // SVG Layers in Center Canvas
    svgCanvas: document.getElementById('svg-canvas'),
    svgWorld: document.getElementById('svg-world'),
    svgBasemapLayer: document.getElementById('svg-basemap-layer'),
    svgSiteBoundLayer: document.getElementById('svg-site-bound-layer'),
    svgZouitLayer: document.getElementById('svg-zouit-layer'),
    svgRedlinesLayer: document.getElementById('svg-redlines-layer'),
    svgRoadCorridorLayer: document.getElementById('svg-road-corridor-layer'),
    svgRoadBufferLayer: document.getElementById('svg-road-buffer-layer'),
    svgRoadCenterlinesLayer: document.getElementById('svg-road-centerlines-layer'),
    svgSubBlocksLayer: document.getElementById('svg-sub-blocks-layer'),
    svgParkingLayer: document.getElementById('svg-parking-layer'),
    svgFireSafetyLayer: document.getElementById('svg-fire-safety-layer'),
    svgBuildingsLayer: document.getElementById('svg-buildings-layer'),
    svgSectionsLayer: document.getElementById('svg-sections-layer'),
    svgRoadHandlesLayer: document.getElementById('svg-road-handles-layer'),
    svgRoadDrawingLayer: document.getElementById('svg-road-drawing-layer'),

    // Canvas Basemap Controls
    canvasBasemapBar: document.getElementById('canvas-basemap-bar'),
    btnBmOsm: document.getElementById('btn-bm-osm'),
    btnBmSatellite: document.getElementById('btn-bm-satellite'),
    btnBmLight: document.getElementById('btn-bm-light'),
    btnBmNone: document.getElementById('btn-bm-none'),
    sliderBasemapOpacity: document.getElementById('slider-basemap-opacity'),
    labelBasemapOpacity: document.getElementById('label-basemap-opacity'),

    // Right Panel: Step 3 TEP & Explication
    rightPanelStep3: document.getElementById('right-panel-step-3'),
    btnRunMaximize: document.getElementById('btn-run-maximize'),
    optProgressPanel: document.getElementById('opt-progress-panel'),
    optBadgePct: document.getElementById('opt-badge-pct'),
    optBarFill: document.getElementById('opt-bar-fill'),
    optStatusMsg: document.getElementById('opt-status-msg'),
    optValCount: document.getElementById('opt-val-count'),
    optValGfa: document.getElementById('opt-val-gfa'),
    optValFloors: document.getElementById('opt-val-floors'),
    btnCalcVariants: document.getElementById('btn-calc-variants'),
    tbodyVariantsMatrix: document.getElementById('tbody-variants-matrix'),
    tbodyApartmentsBreakdown: document.getElementById('tbody-apartments-breakdown'),
    sectionInspectorCard: document.getElementById('section-inspector-card'),
    inspSecTitle: document.getElementById('insp-sec-title'),
    inspSecCategory: document.getElementById('insp-sec-category'),
    inspSecBuilding: document.getElementById('insp-sec-building'),
    inspSecType: document.getElementById('insp-sec-type'),
    inspSecFloors: document.getElementById('insp-sec-floors'),
    inspSecGfa: document.getElementById('insp-sec-gfa'),
    inspSecApts: document.getElementById('insp-sec-apts'),
    inspSecBreakdown: document.getElementById('insp-sec-breakdown'),
    inspSecGround: document.getElementById('insp-sec-ground'),
    tepSanTko: document.getElementById('tep-san-tko'),
    badgeSanStatus: document.getElementById('badge-san-status'),
    tepSanBuffer: document.getElementById('tep-san-buffer'),
    svgParkingSanLayer: document.getElementById('svg-parking-san-layer'),
    svgTkoLayer: document.getElementById('svg-tko-layer'),
    verifBuildingsCount: document.getElementById('verif-buildings-count'),
    verifSectionsCount: document.getElementById('verif-sections-count'),
    valTepTypologyBadge: document.getElementById('val-tep-typology-badge'),
    tepGfa: document.getElementById('tep-gfa'),
    tepLiving: document.getElementById('tep-living'),
    tepComm: document.getElementById('tep-comm'),
    tepFar: document.getElementById('tep-far'),
    tepBcr: document.getElementById('tep-bcr'),
    tepFootprint: document.getElementById('tep-footprint'),
    tepPop: document.getElementById('tep-pop'),
    tepApts: document.getElementById('tep-apts'),
    tepParkingReq: document.getElementById('tep-parking-req'),
    tepParkingGround: document.getElementById('tep-parking-ground'),
    tepParkingUnderground: document.getElementById('tep-parking-underground'),
    tepParkingTotal: document.getElementById('tep-parking-total'),
    tepGreenFact: document.getElementById('tep-green-fact'),
    tepPlayChildren: document.getElementById('tep-play-children'),
    tepPlaySport: document.getElementById('tep-play-sport'),
    tepPlayRelax: document.getElementById('tep-play-relax'),
    tbodyBuildingsExplication: document.getElementById('tbody-buildings-explication'),
    valBuildingsCountBadge: document.getElementById('val-buildings-count-badge'),

    // Export Buttons (Step 3)
    btnExportDxf: document.getElementById('btn-export-dxf'),
    btnExport3d: document.getElementById('btn-export-3d'),
    btnExportGeojson: document.getElementById('btn-export-geojson'),
    btnExportReport: document.getElementById('btn-export-report'),

    // Right Panel: Step 1 Passport
    rightPanelStep1: document.getElementById('right-panel-step-1'),
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

    // Right Panel: Step 2 Territory Balance & Sub-blocks
    rightPanelStep2: document.getElementById('right-panel-step-2'),
    verifCardStep2: document.getElementById('verif-card-step2'),
    verifTitleStep2: document.getElementById('verif-title-step2'),
    verifDescStep2: document.getElementById('verif-desc-step2'),
    verifBlocksCount: document.getElementById('verif-blocks-count'),
    tbSiteArea: document.getElementById('tb-site-area'),
    tbRoadsArea: document.getElementById('tb-roads-area'),
    tbRoadsShare: document.getElementById('tb-roads-share'),
    tbBufferArea: document.getElementById('tb-buffer-area'),
    tbBlocksArea: document.getElementById('tb-blocks-area'),
    tbBlocksShare: document.getElementById('tb-blocks-share'),
    tbRoadsLength: document.getElementById('tb-roads-length'),
    tbBlocksCount: document.getElementById('tb-blocks-count'),
    tbBlocksBadge: document.getElementById('tb-blocks-badge'),
    tbodySubBlocks: document.getElementById('tbody-sub-blocks'),
    linkYandexStep2: document.getElementById('link-yandex-step2'),
    linkPkkStep2: document.getElementById('link-pkk-step2'),

    // GPZU Modal Elements
    gpzuModal: document.getElementById('gpzu-modal'),
    gpzuModalClose: document.getElementById('gpzu-modal-close'),
    btnModalGpzuApply: document.getElementById('btn-modal-gpzu-apply'),
    btnModalGpzuBoundaryOnly: document.getElementById('btn-modal-gpzu-boundary-only'),
    btnModalGpzuCancel: document.getElementById('btn-modal-gpzu-cancel'),
    btnModalAddZouit: document.getElementById('btn-modal-add-zouit'),
    modalGpzuTitle: document.getElementById('modal-gpzu-title'),
    modalGpzuPointsBadge: document.getElementById('modal-gpzu-points-badge'),
    modalGpzuAreaBadge: document.getElementById('modal-gpzu-area-badge'),
    modalGpzuZonesCount: document.getElementById('modal-gpzu-zones-count'),
    modalGpzuZonesList: document.getElementById('modal-gpzu-zones-list'),
    modalGpzuZouitList: document.getElementById('modal-gpzu-zouit-list'),
    modalGpzuChkSetback: document.getElementById('modal-gpzu-chk-setback'),
    modalGpzuValSetback: document.getElementById('modal-gpzu-val-setback'),
    modalGpzuSnipSetback: document.getElementById('modal-gpzu-snip-setback'),
    modalGpzuChkRedline: document.getElementById('modal-gpzu-chk-redline'),
    modalGpzuValRedline: document.getElementById('modal-gpzu-val-redline'),
    modalGpzuSnipRedline: document.getElementById('modal-gpzu-snip-redline'),
    modalGpzuChkFloors: document.getElementById('modal-gpzu-chk-floors'),
    modalGpzuValFloors: document.getElementById('modal-gpzu-val-floors'),
    modalGpzuSnipFloors: document.getElementById('modal-gpzu-snip-floors'),
    modalGpzuChkMaxH: document.getElementById('modal-gpzu-chk-max-h'),
    modalGpzuValMaxH: document.getElementById('modal-gpzu-val-max-h'),
    modalGpzuSnipMaxH: document.getElementById('modal-gpzu-snip-max-h'),
    modalGpzuChkBcr: document.getElementById('modal-gpzu-chk-bcr'),
    modalGpzuValBcr: document.getElementById('modal-gpzu-val-bcr'),
    modalGpzuSnipBcr: document.getElementById('modal-gpzu-snip-bcr'),
    modalGpzuChkFar: document.getElementById('modal-gpzu-chk-far'),
    modalGpzuValFar: document.getElementById('modal-gpzu-val-far'),
    modalGpzuSnipFar: document.getElementById('modal-gpzu-snip-far'),
    modalGpzuChkGreen: document.getElementById('modal-gpzu-chk-green'),
    modalGpzuValGreen: document.getElementById('modal-gpzu-val-green'),
    modalGpzuSnipGreen: document.getElementById('modal-gpzu-snip-green'),
    btnOpenGpzuModalCad: document.getElementById('btn-open-gpzu-modal-cad'),
    btnOpenGpzuModalPoints: document.getElementById('btn-open-gpzu-modal-points'),
    zouitActiveBanner: document.getElementById('zouit-active-banner'),
    zouitActiveCount: document.getElementById('zouit-active-count'),
    zouitActiveArea: document.getElementById('zouit-active-area'),
    zouitActiveDesc: document.getElementById('zouit-active-desc'),
    pMaxHeight: document.getElementById('p-max-height'),
    pMaxBcr: document.getElementById('p-max-bcr'),
    pMaxFar: document.getElementById('p-max-far'),
    tbZouitArea: document.getElementById('tb-zouit-area'),

    // Step 3 Left Panel
    panelStep3Content: document.getElementById('panel-step-3-content'),
    step3CardFloors: document.getElementById('step3-card-floors'),
    step3CardFar: document.getElementById('step3-card-far'),
    step3CardBcr: document.getElementById('step3-card-bcr'),
    step3CardGreen: document.getElementById('step3-card-green'),
    btnStep3EditRegs: document.getElementById('btn-step3-edit-regs'),
    valTypologyTag: document.getElementById('val-typology-tag'),
    chkStep3Cascade: document.getElementById('chk-step3-cascade'),
    chkStep3CarFree: document.getElementById('chk-step3-car-free'),
    chkStep3OnlyGround: document.getElementById('chk-step3-only-ground'),
    chkStep3AllowZouit: document.getElementById('chk-step3-allow-zouit'),
    selectStep3RegionalNorm: document.getElementById('select-step3-regional-norm'),
    badgeStep3NormTag: document.getElementById('badge-step3-norm-tag'),
    step3NormSummary: document.getElementById('step3-norm-summary'),
    chkStep3TowersMixed: document.getElementById('chk-step3-towers-mixed'),
    selectStep3CourtOrient: document.getElementById('select-step3-court-orient'),
    prefSectionsContainer: document.getElementById('pref-sections-container'),
    hintPrefSections: document.getElementById('hint-pref-sections'),
    sliderStep3Floors: document.getElementById('slider-step3-floors'),
    labelStep3Floors: document.getElementById('label-step3-floors'),
    valStep3FloorsTag: document.getElementById('val-step3-floors-tag'),
    sliderStep3Setback: document.getElementById('slider-step3-setback'),
    labelStep3Setback: document.getElementById('label-step3-setback'),
    typologyBtns: document.querySelectorAll('.typology-btn'),
    btnGenerateLayout: document.getElementById('btn-generate-layout'),
    btnStep3Back: document.getElementById('btn-step3-back'),

    // Modal Sections Catalog & Heights
    btnHeaderSections: document.getElementById('btn-header-sections'),
    btnOpenSectionsModal: document.getElementById('btn-open-sections-modal'),
    modalSectionsTable: document.getElementById('modal-sections-table'),
    modalSectionsClose: document.getElementById('modal-sections-close'),
    btnModalSectionsCancel: document.getElementById('btn-modal-sections-cancel'),
    btnModalSectionsSave: document.getElementById('btn-modal-sections-save'),
    modalSectionsTbody: document.getElementById('modal-sections-tbody'),
    modalSectionsStatus: document.getElementById('modal-sections-status'),

    // Step 3 Regulations Popup Modal
    modalStep3Regs: document.getElementById('modal-step3-regulations'),
    modalStep3RegsClose: document.getElementById('modal-step3-regs-close'),
    modalStep3SiteSummary: document.getElementById('modal-step3-site-summary'),
    modalStep3BlocksSummary: document.getElementById('modal-step3-blocks-summary'),
    inputStep3Floors: document.getElementById('input-step3-floors'),
    valStep3Floors: document.getElementById('val-step3-floors'),
    snipStep3Floors: document.getElementById('snip-step3-floors'),
    inputStep3Height: document.getElementById('input-step3-height'),
    valStep3Height: document.getElementById('val-step3-height'),
    snipStep3Height: document.getElementById('snip-step3-height'),
    inputStep3Bcr: document.getElementById('input-step3-bcr'),
    valStep3Bcr: document.getElementById('val-step3-bcr'),
    snipStep3Bcr: document.getElementById('snip-step3-bcr'),
    inputStep3Far: document.getElementById('input-step3-far'),
    valStep3Far: document.getElementById('val-step3-far'),
    snipStep3Far: document.getElementById('snip-step3-far'),
    inputStep3Green: document.getElementById('input-step3-green'),
    valStep3Green: document.getElementById('val-step3-green'),
    inputStep3SetbackBound: document.getElementById('input-step3-setback-bound'),
    inputStep3SetbackRedline: document.getElementById('input-step3-setback-redline'),
    valStep3Setback: document.getElementById('val-step3-setback'),
    modalStep3ZouitCount: document.getElementById('modal-step3-zouit-count'),
    modalStep3ZouitSummary: document.getElementById('modal-step3-zouit-summary'),
    btnStep3OpenFullGpzu: document.getElementById('btn-step3-open-full-gpzu'),
    btnStep3RegsBack: document.getElementById('btn-step3-regs-back'),
    btnStep3RegsConfirm: document.getElementById('btn-step3-regs-confirm')
  };

  // --- SVG PAN & ZOOM STATE ---
  let panZoom = {
    scale: 1.0,
    tx: 0.0,
    ty: 0.0,
    isDragging: false,
    startX: 0.0,
    startY: 0.0
  };

  function applySvgTransform() {
    if (el.svgWorld) {
      el.svgWorld.setAttribute('transform', `matrix(${panZoom.scale} 0 0 ${panZoom.scale} ${panZoom.tx} ${panZoom.ty})`);
    }
  }

  function fitSvgToViewport(viewBoxStr) {
    if (!viewBoxStr) viewBoxStr = '0 0 1000 700';
    const parts = viewBoxStr.split(' ').map(Number);
    const vbW = parts[2] || 1000;
    const vbH = parts[3] || 700;

    const rect = el.svgCanvas.getBoundingClientRect();
    const canW = rect.width || 800;
    const canH = rect.height || 600;

    const s = Math.min((canW - 40) / vbW, (canH - 40) / vbH);
    panZoom.scale = s > 0 ? s : 1.0;
    panZoom.tx = (canW - vbW * panZoom.scale) / 2;
    panZoom.ty = (canH - vbH * panZoom.scale) / 2;

    applySvgTransform();
  }

  // --- COORDINATE TRANSFORMATION HELPERS (SVG <-> SITE METERS) ---
  function getCoordHelpers() {
    const meta = (state.currentData && state.currentData.svg_meta) || {
      minx: -15, miny: -15, maxx: 255, maxy: 195, width: 1000, height: 700
    };
    const dx = meta.maxx - meta.minx;
    const dy = meta.maxy - meta.miny;
    const pad = 40;
    const scale = Math.min((meta.width - 2 * pad) / (dx || 1), (meta.height - 2 * pad) / (dy || 1));
    const ox = pad + ((meta.width - 2 * pad) - dx * scale) / 2;
    const oy = pad + ((meta.height - 2 * pad) - dy * scale) / 2;

    function svgToSite(sx, sy) {
      const x = meta.minx + (sx - ox) / scale;
      const y = meta.maxy - (sy - oy) / scale;
      return [round2(x), round2(y)];
    }

    function siteToSvg(x, y) {
      const sx = ox + (x - meta.minx) * scale;
      const sy = oy + (meta.maxy - y) * scale;
      return [round1(sx), round1(sy)];
    }

    return { svgToSite, siteToSvg, scale, ox, oy, meta };
  }

  // --- LOCAL METRIC (METERS) TO WGS-84 (LON, LAT) ---
  function localMetersToWgs84(x, y, centerLat, centerLon) {
    const a = 6378137.0;
    const e2 = 0.00669437999014;
    const latRad = (centerLat * Math.PI) / 180.0;
    const sinLat = Math.sin(latRad);
    const cosLat = Math.cos(latRad);
    const den = 1.0 - e2 * sinLat * sinLat;
    const sqrtDen = Math.sqrt(den);
    const N = a / sqrtDen;
    const M = (a * (1.0 - e2)) / (den * sqrtDen);

    const dlat = (y / M) * (180.0 / Math.PI);
    const dlon = (x / (N * cosLat)) * (180.0 / Math.PI);

    return [centerLon + dlon, centerLat + dlat];
  }

  // --- WGS-84 (LON, LAT) TO LOCAL METRIC (METERS) ---
  function wgs84ToLocalMeters(lon, lat, centerLat, centerLon) {
    const a = 6378137.0;
    const e2 = 0.00669437999014;
    const latRad = (centerLat * Math.PI) / 180.0;
    const sinLat = Math.sin(latRad);
    const cosLat = Math.cos(latRad);
    const den = 1.0 - e2 * sinLat * sinLat;
    const sqrtDen = Math.sqrt(den);
    const N = a / sqrtDen;
    const M = (a * (1.0 - e2)) / (den * sqrtDen);

    const dlatRad = ((lat - centerLat) * Math.PI) / 180.0;
    const dlonRad = ((lon - centerLon) * Math.PI) / 180.0;

    return [dlonRad * N * cosLat, dlatRad * M];
  }

  // Slippy Map Tile Calculations (Web Mercator EPSG:3857)
  function lon2tile(lon, zoom) {
    return Math.floor(((lon + 180) / 360) * Math.pow(2, zoom));
  }
  function lat2tile(lat, zoom) {
    return Math.floor(
      ((1 - Math.log(Math.tan((lat * Math.PI) / 180) + 1 / Math.cos((lat * Math.PI) / 180)) / Math.PI) / 2) *
        Math.pow(2, zoom)
    );
  }
  function tile2lon(x, zoom) {
    return (x / Math.pow(2, zoom)) * 360 - 180;
  }
  function tile2lat(y, zoom) {
    const n = Math.PI - (2 * Math.PI * y) / Math.pow(2, zoom);
    return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
  }

  // --- RENDER DYNAMIC SLIPPY-MAP BASEMAP ON 2D CAD SVG CANVAS ---
  function updateSvgBasemap() {
    if (!el.svgBasemapLayer) return;
    if (state.activeBasemap === 'none' || !state.currentData) {
      el.svgBasemapLayer.innerHTML = '';
      return;
    }

    const helpers = getCoordHelpers();
    const meta = helpers.meta;
    const geoCenter = state.currentData.geo_center || { lat: 57.161069, lon: 65.674079 };

    // Pad bounding box around site by 50% so user sees surrounding city streets & intersections
    const padX = (meta.maxx - meta.minx) * 0.5;
    const padY = (meta.maxy - meta.miny) * 0.5;
    const bboxMinX = meta.minx - padX;
    const bboxMaxX = meta.maxx + padX;
    const bboxMinY = meta.miny - padY;
    const bboxMaxY = meta.maxy + padY;

    // Convert corners to WGS-84
    const [minLon, minLat] = localMetersToWgs84(bboxMinX, bboxMinY, geoCenter.lat, geoCenter.lon);
    const [maxLon, maxLat] = localMetersToWgs84(bboxMaxX, bboxMaxY, geoCenter.lat, geoCenter.lon);

    // Dynamic zoom level matched to site scale (15 to 18)
    const spanM = Math.max(bboxMaxX - bboxMinX, bboxMaxY - bboxMinY);
    let z = 17;
    if (spanM > 1000) z = 15;
    else if (spanM > 450) z = 16;
    else if (spanM < 160) z = 18;

    const minTx = lon2tile(minLon, z);
    const maxTx = lon2tile(maxLon, z);
    const minTy = lat2tile(maxLat, z);
    const maxTy = lat2tile(minLat, z);

    let tilesMarkup = '';
    for (let tx = minTx; tx <= maxTx; tx++) {
      for (let ty = minTy; ty <= maxTy; ty++) {
        const tMinLon = tile2lon(tx, z);
        const tMaxLon = tile2lon(tx + 1, z);
        const tMaxLat = tile2lat(ty, z);
        const tMinLat = tile2lat(ty + 1, z);

        const [mX1, mY1] = wgs84ToLocalMeters(tMinLon, tMaxLat, geoCenter.lat, geoCenter.lon);
        const [mX2, mY2] = wgs84ToLocalMeters(tMaxLon, tMinLat, geoCenter.lat, geoCenter.lon);

        const [sX1, sY1] = helpers.siteToSvg(mX1, mY1);
        const [sX2, sY2] = helpers.siteToSvg(mX2, mY2);

        const tileW = Math.max(1, sX2 - sX1);
        const tileH = Math.max(1, sY2 - sY1);

        let tileUrl = '';
        if (state.activeBasemap === 'osm') {
          // OpenStreetMap — exact same tile service as in the "Спутник OSM" tab!
          tileUrl = `https://tile.openstreetmap.org/${z}/${tx}/${ty}.png`;
        } else if (state.activeBasemap === 'satellite') {
          // Esri World Imagery tiles — exact same satellite service as in Leaflet!
          tileUrl = `https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/${z}/${ty}/${tx}`;
        } else if (state.activeBasemap === 'light') {
          // Esri Light Gray Canvas tiles
          tileUrl = `https://services.arcgisonline.com/arcgis/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/${z}/${ty}/${tx}`;
        }

        tilesMarkup += `
          <image href="${tileUrl}"
                 x="${round1(sX1)}"
                 y="${round1(sY1)}"
                 width="${round1(tileW)}"
                 height="${round1(tileH)}"
                 opacity="${state.basemapOpacity}"
                 preserveAspectRatio="none"
                 class="svg-basemap-tile"
                 style="pointer-events: none;" />
        `;
      }
    }

    el.svgBasemapLayer.innerHTML = tilesMarkup;
  }

  // --- CLIENT GEOMETRY & HTML HELPERS ---
  function escapeHtml(str) {
    if (str === null || str === undefined) return '';
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function calculatePolygonAreaClient(pts) {
    if (!pts || pts.length < 3) return 0;
    let area = 0;
    for (let i = 0; i < pts.length; i++) {
      const j = (i + 1) % pts.length;
      area += pts[i][0] * pts[j][1];
      area -= pts[j][0] * pts[i][1];
    }
    return Math.abs(area) / 2.0;
  }

  function parseCoordinateTextClient(text) {
    if (!text) return [];
    const lines = text.trim().split(/[\r\n]+/);
    const pts = [];
    for (const line of lines) {
      const clean = line.trim();
      if (!clean || clean.startsWith('#')) continue;
      const words = clean.match(/[а-яА-ЯёЁa-zA-Z]{2,}/g);
      if (words && words.length >= 2) continue;
      const lineNorm = clean.replace(/,/g, '.');
      const parts = lineNorm.split(/[\s\t;,|]+/);
      const nums = [];
      for (const p of parts) {
        const pClean = p.replace(/[()\[\]{}:X=Y=x=y=Х=У=х=у=]/g, '').trim();
        const n = parseFloat(pClean);
        if (!isNaN(n) && pClean !== '') nums.push(n);
      }
      if (nums.length >= 2) {
        if (nums.length >= 5 && Number.isInteger(nums[0]) && nums[0] < 5000) {
          pts.push([nums[3], nums[4]]);
        } else if (nums.length === 4) {
          pts.push([nums[2], nums[3]]);
        } else if (nums.length >= 3 && Number.isInteger(nums[0]) && nums[0] < 5000) {
          pts.push([nums[1], nums[2]]);
        } else {
          pts.push([nums[0], nums[1]]);
        }
      }
    }
    return pts;
  }

  function ensureMskOption(zoneName) {
    if (!el.selectMskZone || !zoneName) return;
    let opt = Array.from(el.selectMskZone.options).find(o => o.value === zoneName);
    if (!opt) {
      opt = document.createElement('option');
      opt.value = zoneName;
      opt.textContent = zoneName;
      el.selectMskZone.appendChild(opt);
    }
    el.selectMskZone.value = zoneName;
  }

  // --- INITIAL EMPTY STATE ---
  function initEmptyState() {
    if (el.canvasEmptyState) el.canvasEmptyState.style.display = 'flex';
    if (el.iframeOsm) el.iframeOsm.style.display = 'none';

    el.hdrParcelBadge.textContent = 'Ожидание ввода ЗУ';
    el.panelHeroArea.textContent = '— га';

    el.pCad.textContent = '—';
    el.pAreaHa.textContent = '—';
    el.pAreaSqm.textContent = '—';
    el.pRegion.textContent = '—';
    el.pAddress.textContent = '—';
    el.pDimensions.textContent = '—';
    el.pVertices.textContent = '—';
    el.pBuildableArea.textContent = '—';
    el.pZouitStatus.textContent = '—';
    el.pCrs.textContent = '—';
    if (el.pMaxHeight) el.pMaxHeight.textContent = '14 эт. (50.0 м)';
    if (el.pMaxBcr) el.pMaxBcr.textContent = '40.0%';
    if (el.pMaxFar) el.pMaxFar.textContent = '2.50';
    if (el.zouitActiveBanner) el.zouitActiveBanner.style.display = 'none';
    if (el.tbZouitArea) el.tbZouitArea.textContent = '—';

    state.road_preset = 'none';
    if (el.presetBtns) el.presetBtns.forEach(b => b.classList.toggle('active', b.dataset.preset === 'none'));
    if (el.valPresetBadge) el.valPresetBadge.textContent = 'Без дорог';
    if (el.groupRoadPos) el.groupRoadPos.style.display = 'none';
    if (el.groupRoadPosGrid) el.groupRoadPosGrid.style.display = 'none';

    if (el.step3CardFloors) el.step3CardFloors.textContent = '14 эт. (50.0 м)';
    if (el.step3CardFar) el.step3CardFar.textContent = '2.50';
    if (el.step3CardBcr) el.step3CardBcr.textContent = '40.0%';
    if (el.step3CardGreen) el.step3CardGreen.textContent = '≥ 25%';

    el.verificationCard.className = 'verification-card unverified';
    el.verifTitle.textContent = 'Участок не выбран';
    el.verifDesc.textContent = 'Введите кадастровый номер ЗУ в левой панели для получения параметров и привязки.';

    if (el.linkYandex) {
      el.linkYandex.href = '#';
      el.linkYandex.style.pointerEvents = 'none';
      el.linkYandex.style.opacity = '0.4';
    }
    if (el.linkPkk) {
      el.linkPkk.href = '#';
      el.linkPkk.style.pointerEvents = 'none';
      el.linkPkk.style.opacity = '0.4';
    }

    if (el.btnLockSite) {
      el.btnLockSite.style.opacity = '0.5';
      el.btnLockSite.style.pointerEvents = 'none';
    }
  }

  // --- STEP SWITCHER (STEP 1 -> STEP 2 -> STEP 3) ---
  function setStep(step) {
    if ((step === 2 || step === 3) && !state.currentData) {
      alert('Пожалуйста, сначала посадите участок (введите кадастровый номер или загрузите чертеж / ГПЗУ).');
      return;
    }

    state.currentStep = step;

    // 1. Stepper UI
    if (el.stepperStep1) {
      el.stepperStep1.classList.toggle('active', step === 1);
      el.stepperStep1.style.opacity = step === 1 ? '1' : '0.85';
    }
    if (el.stepperStep2) {
      el.stepperStep2.classList.toggle('active', step === 2);
      el.stepperStep2.style.opacity = step === 2 ? '1' : (state.currentData ? '0.85' : '0.5');
    }
    if (el.stepperStep3) {
      el.stepperStep3.classList.toggle('active', step === 3);
      el.stepperStep3.style.opacity = step === 3 ? '1' : (state.currentData ? '0.85' : '0.35');
    }

    // 2. Left panel visibility
    if (el.panelStep1Content) el.panelStep1Content.style.display = step === 1 ? 'flex' : 'none';
    if (el.panelStep2Content) el.panelStep2Content.style.display = step === 2 ? 'flex' : 'none';
    if (el.panelStep3Content) el.panelStep3Content.style.display = step === 3 ? 'flex' : 'none';

    // 3. Right panel visibility
    if (el.rightPanelStep1) el.rightPanelStep1.style.display = step === 1 ? 'flex' : 'none';
    if (el.rightPanelStep2) el.rightPanelStep2.style.display = step === 2 ? 'flex' : 'none';
    if (el.rightPanelStep3) el.rightPanelStep3.style.display = step === 3 ? 'flex' : 'none';

    // 4. Viewport defaults
    if (step === 1) {
      setCanvasView('osm');
      apiPreviewSite(true);
    } else if (step === 2) {
      setCanvasView('svg');
      apiPreviewSite(true);
    } else if (step === 3) {
      setCanvasView('3d');
      if (state.currentData && !state.currentScenario && !state.isGenerating) {
        apiGenerateLayout();
      }
    }
  }

  // --- API PAYLOAD BUILDER ---
  function getPayload() {
    const sendOverrideLat = state.userHasMovedSite ? state.override_lat : 0.0;
    const sendOverrideLon = state.userHasMovedSite ? state.override_lon : 0.0;

    const payload = {
      site_mode: state.mode === 'cad' ? 'cad' : (state.mode === 'points' ? 'points' : 'cadastre'),
      site_rotation: state.site_rotation,
      override_lat: sendOverrideLat,
      override_lon: sendOverrideLon,
      boundary_setback: state.boundary_setback,
      red_line_setback: state.red_line_setback,
      enable_red_line: state.currentStep > 1 && state.enable_red_line,
      msk_zone: state.msk_zone,
      cad_swap_xy: el.chkCadSwapXy ? !!el.chkCadSwapXy.checked : false,
      stage: 1,
      preview_only: true,

      // Step 2: Roads (strictly inactive on Step 1)
      road_preset: state.currentStep === 1 ? 'none' : state.road_preset,
      road_width: state.road_width,
      road_setback: state.road_setback,
      road_pos: state.road_pos,
      road_pos_x: state.road_pos_x,
      road_pos_y: state.road_pos_y,

      // Regulatory restrictions
      max_building_height_m: state.max_height_m,
      target_floors: state.max_floors,
      max_bcr: state.max_bcr,
      max_far: state.max_far
    };

    // ZOUIT zones
    if (state.zouit_active && state.activeZouitZones && state.activeZouitZones.length > 0) {
      payload.zouit_zones = state.activeZouitZones;
      payload.zouit_list = state.activeZouitZones;
    } else {
      payload.zouit_zones = [];
      payload.zouit_list = [];
    }

    if (state.currentStep > 1 && state.custom_roads && state.custom_roads.length > 0) {
      payload.custom_roads = state.custom_roads;
    }

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

  // --- API CALL: PREVIEW SITE ---
  let previewDebounceTimer = null;

  async function apiPreviewSite(isDirect = false) {
    if (!isDirect) {
      clearTimeout(previewDebounceTimer);
      previewDebounceTimer = setTimeout(() => apiPreviewSite(true), 150);
      return;
    }

    // Guard conditions
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
      if (el.backendStatusText) el.backendStatusText.textContent = 'Расчет геометрии...';

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

      if (el.backendStatusText) el.backendStatusText.textContent = 'Бэкенд активен';
    } catch (err) {
      console.error('apiPreviewSite error:', err);
      if (el.backendStatusText) el.backendStatusText.textContent = 'Ошибка расчета';
    } finally {
      state.isBusy = false;
    }
  }

  // --- RENDER COMPLETE SITE (STEP 1 & STEP 2) ---
  function renderSite(data) {
    if (!data) return;

    // 1. Hide Empty State, show Map & SVG
    if (el.canvasEmptyState) el.canvasEmptyState.style.display = 'none';
    if (el.iframeOsm) el.iframeOsm.style.display = 'block';

    const areaHa = data.site_area_ha ? `${fmtNum(data.site_area_ha)} га` : `${((data.site_area_sqm || 0) / 10000).toFixed(2)} га`;
    const cadNum = data.cadastral_number || state.cad_query || 'Не присвоен';
    const region = data.region_name || 'РФ';
    const district = data.district_name || data.address || '';

    // 2. Header & Hero Badges
    if (el.hdrParcelBadge) el.hdrParcelBadge.textContent = `${region.split(' ')[0]} • ${areaHa}`;
    if (el.panelHeroArea) el.panelHeroArea.textContent = areaHa;

    // 3. Step 1 Passport
    if (el.pCad) el.pCad.textContent = cadNum;
    if (el.pAreaHa) el.pAreaHa.textContent = areaHa;
    if (el.pAreaSqm) el.pAreaSqm.textContent = `${fmtInt(data.site_area_sqm || 0)} м²`;
    if (el.pRegion) el.pRegion.textContent = region;
    if (el.pAddress) el.pAddress.textContent = district || '—';

    // Dimensions
    if (data.site_dimensions && data.site_dimensions.length >= 2) {
      const dimStr = `${Math.round(data.site_dimensions[0])} × ${Math.round(data.site_dimensions[1])} м`;
      if (el.pDimensions) el.pDimensions.textContent = dimStr;
      if (el.labelDimensions) el.labelDimensions.textContent = `Габариты: ${dimStr}`;
    }

    // Vertices
    const vertCount = data.vertices_count || (data.boundary_coords ? data.boundary_coords.length : 0);
    if (el.pVertices) el.pVertices.textContent = `${vertCount} точек`;

    // Buildable Area
    const buildable = data.buildable_area_sqm || Math.round((data.site_area_sqm || 0) * 0.82);
    if (el.pBuildableArea) el.pBuildableArea.textContent = `${fmtInt(buildable)} м²`;

    // ZOUIT & Restrictions
    const zouits = data.zouit_paths || [];
    const zouitInfoList = data.zouit_info || [];
    const zouitArea = zouitInfoList.reduce((acc, z) => acc + (z.area_sqm || 0), 0);
    const hasZouit = state.zouit_active && zouits.length > 0;

    if (el.pZouitStatus) {
      if (hasZouit) {
        el.pZouitStatus.innerHTML = `<span style="color:var(--danger); font-weight:600;">${zouits.length} зон (${zouitArea > 0 ? '-' + fmtInt(zouitArea) + ' м²' : 'активны'})</span>`;
      } else {
        el.pZouitStatus.textContent = 'Не обнаружены';
        el.pZouitStatus.style.color = 'var(--text-secondary)';
      }
    }

    if (el.pMaxHeight) el.pMaxHeight.textContent = `${state.max_floors} эт. (${state.max_height_m} м)`;
    if (el.pMaxBcr) el.pMaxBcr.textContent = `${state.max_bcr}%`;
    if (el.pMaxFar) el.pMaxFar.textContent = `${state.max_far.toFixed(2)}`;

    // ZOUIT Active Banner in Step 1
    if (el.zouitActiveBanner) {
      if (state.activeZouitZones && state.activeZouitZones.length > 0) {
        el.zouitActiveBanner.style.display = 'block';
        if (el.zouitActiveCount) el.zouitActiveCount.textContent = state.activeZouitZones.length;
        if (el.zouitActiveArea) el.zouitActiveArea.textContent = zouitArea > 0 ? `${fmtInt(zouitArea)} м²` : '—';
        if (el.zouitActiveDesc) el.zouitActiveDesc.textContent = state.activeZouitZones.map(z => z.name).join('; ');
      } else {
        el.zouitActiveBanner.style.display = 'none';
      }
    }

    // Step 2 territory balance row for ZOUIT
    if (el.tbZouitArea) {
      if (zouitArea > 0) {
        const pct = data.site_area_sqm > 0 ? ((zouitArea / data.site_area_sqm) * 100).toFixed(1) : '0';
        el.tbZouitArea.textContent = `-${fmtInt(zouitArea)} м² (${pct}%)`;
      } else {
        el.tbZouitArea.textContent = '0 м²';
      }
    }

    // Synchronize Step 3 summary card with state
    if (el.step3CardFloors) el.step3CardFloors.textContent = `${state.max_floors} эт. (${state.max_height_m} м)`;
    if (el.step3CardFar) el.step3CardFar.textContent = state.max_far.toFixed(2);
    if (el.step3CardBcr) el.step3CardBcr.textContent = `${state.max_bcr}%`;
    if (el.step3CardGreen) el.step3CardGreen.textContent = `≥ ${state.green_ratio}%`;

    // CRS
    const mskName = (data.cad_info && data.cad_info.detected_msk) || state.msk_zone || 'WGS-84';
    if (el.pCrs) el.pCrs.textContent = `${mskName}`;

    // Verification Card Step 1
    if (el.verificationCard) {
      el.verificationCard.className = 'verification-card verified';
      if (el.verifTitle) el.verifTitle.textContent = state.isLocked ? 'Посадка зафиксирована' : 'Геопривязка подтверждена';
      if (el.verifDesc) {
        el.verifDesc.textContent = state.isLocked
          ? `Контур ${areaHa} зафиксирован. Участок передан на Шаг 2 (Нарезка УДС).`
          : `Координаты проверены. Перетаскивайте контур или вращайте оранжевым маркером на карте.`;
      }
    }

    // Geoportals links
    if (data.geo_center) {
      const { lat, lon } = data.geo_center;
      if (el.labelCoords) el.labelCoords.textContent = `WGS-84: [${lat.toFixed(5)}, ${lon.toFixed(5)}]`;

      const yUrl = `https://yandex.ru/maps/?pt=${lon},${lat}&z=16&l=map`;
      const pkkUrl = `https://pkk.rosreestr.ru/#/search/${lat},${lon}/16`;

      if (el.linkYandex) { el.linkYandex.href = yUrl; el.linkYandex.style.pointerEvents = 'auto'; el.linkYandex.style.opacity = '1'; }
      if (el.linkPkk) { el.linkPkk.href = pkkUrl; el.linkPkk.style.pointerEvents = 'auto'; el.linkPkk.style.opacity = '1'; }
      if (el.linkYandexStep2) { el.linkYandexStep2.href = yUrl; el.linkYandexStep2.style.pointerEvents = 'auto'; el.linkYandexStep2.style.opacity = '1'; }
      if (el.linkPkkStep2) { el.linkPkkStep2.href = pkkUrl; el.linkPkkStep2.style.pointerEvents = 'auto'; el.linkPkkStep2.style.opacity = '1'; }

      if (!state.userHasMovedSite && !state.userHasEnteredManualCoords) {
        if (el.inputManualLat) el.inputManualLat.placeholder = lat.toFixed(5);
        if (el.inputManualLon) el.inputManualLon.placeholder = lon.toFixed(5);
      }
    }

    // Compass
    const rot = data.site_rotation !== undefined ? data.site_rotation : state.site_rotation;
    if (el.compassSvg) el.compassSvg.style.transform = `rotate(${-rot}deg)`;

    // CAD Layers & MSK Information
    if (data.cad_info) {
      if (data.cad_info.layers && data.cad_info.layers.length > 0) {
        populateCadLayers(data.cad_info.layers, data.cad_info.boundary_layer, data.cad_info.red_lines_layer);
      }
      if (data.cad_info.detected_msk) {
        state.msk_zone = data.cad_info.detected_msk;
        ensureMskOption(data.cad_info.detected_msk);
        if (el.mskDetectedBadge) {
          el.mskDetectedBadge.style.display = 'inline-block';
          el.mskDetectedBadge.style.background = '';
          el.mskDetectedBadge.style.color = '';
          el.mskDetectedBadge.textContent = data.cad_info.detected_msk;
        }
      } else {
        if (el.mskDetectedBadge) {
          el.mskDetectedBadge.style.display = 'inline-block';
          el.mskDetectedBadge.style.background = 'rgba(234, 88, 12, 0.15)';
          el.mskDetectedBadge.style.color = '#ea580c';
          el.mskDetectedBadge.textContent = 'Выберите зону МСК';
        }
      }
      if (data.cad_info.detected_cadastre && el.inputCadAssigned && !el.inputCadAssigned.value) {
        el.inputCadAssigned.value = data.cad_info.detected_cadastre;
        state.assigned_cad_query = data.cad_info.detected_cadastre;
      }
    }

    // Leaflet HTML (only reload iframe if on Step 1 or OSM tab is active)
    if (data.leaflet_html && data.leaflet_html !== state.lastLeafletHtml) {
      state.lastLeafletHtml = data.leaflet_html;
      if (el.iframeOsm && (state.currentStep === 1 || state.activeView === 'osm')) {
        el.iframeOsm.srcdoc = data.leaflet_html;
      }
    }

    // Enable lock button
    if (el.btnLockSite) {
      el.btnLockSite.style.opacity = '1';
      el.btnLockSite.style.pointerEvents = 'auto';
    }

    // Render 2D CAD SVG Elements
    renderSvgWorld(data);

    // Render Step 2 Roads & Territory Balance
    renderStep2Roads(data);

    // Sync 3D viewer only if 3D tab is currently visible (saves 150ms per road change)
    if (data.viewer_3d_data && state.activeView === '3d') {
      sync3dViewer(data.viewer_3d_data);
    }
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
      const cnt = lyr.total_entities != null ? lyr.total_entities : (lyr.count != null ? lyr.count : (lyr.polylines_count || 0));
      const isCand = lyr.is_candidate;
      const isRed = lyr.is_red_line_candidate || lyr.is_redline;
      const bOpt = document.createElement('option');
      bOpt.value = lyr.name;
      bOpt.textContent = `${lyr.name} (${cnt} эл.)${isCand ? ' ★' : ''}`;
      if (activeBoundary && lyr.name === activeBoundary) bOpt.selected = true;
      el.selectCadLayer.appendChild(bOpt);

      if (el.selectCadRedline) {
        const rOpt = document.createElement('option');
        rOpt.value = lyr.name;
        rOpt.textContent = `${lyr.name} (${cnt} эл.)${isRed ? ' [Красная линия]' : ''}`;
        if (activeRedline && lyr.name === activeRedline) rOpt.selected = true;
        el.selectCadRedline.appendChild(rOpt);
      }
    });
  }

  // --- RENDER 2D VECTOR CAD (SVG WORLD) ---
  function renderSvgWorld(data) {
    if (!data) return;

    // 0. Basemap Underlay (Satellite / Streets / Light)
    updateSvgBasemap();

    // 1. ZOUIT
    if (el.svgZouitLayer) {
      let zouitMarkup = '';
      if (state.zouit_active && data.zouit_paths && data.zouit_paths.length > 0) {
        data.zouit_paths.forEach((p, idx) => {
          const zInfo = (data.zouit_info && data.zouit_info[idx]) || {};
          const zName = zInfo.name || `Охранная зона ${idx + 1}`;
          zouitMarkup += `<path class="svg-zouit-poly" d="${p}" fill="rgba(239, 68, 68, 0.16)" stroke="#ef4444" stroke-width="1.8" stroke-dasharray="5,4"><title>${escapeHtml(zName)}</title></path>`;
        });
      }
      el.svgZouitLayer.innerHTML = zouitMarkup;
    }

    // 2. Red Lines
    if (el.svgRedlinesLayer) {
      let rlMarkup = '';
      if (state.enable_red_line && data.red_lines_paths) {
        data.red_lines_paths.forEach(p => {
          rlMarkup += `<path d="${p}" fill="none" stroke="#f43f5e" stroke-width="2.5" />`;
        });
      }
      el.svgRedlinesLayer.innerHTML = rlMarkup;
    }

    // 3. Site Boundary
    if (el.svgSiteBoundLayer) {
      let bMarkup = '';
      if (data.site_path) {
        bMarkup += `<path id="cad-site-bound" d="${data.site_path}" fill="rgba(56, 189, 248, 0.06)" stroke="#38bdf8" stroke-width="2.5" />`;
      }
      el.svgSiteBoundLayer.innerHTML = bMarkup;
    }

    // 4. Roads Corridor & Buffer
    const isStep1 = state.currentStep === 1;
    const roads = isStep1 ? null : data.roads;
    if (el.svgRoadCorridorLayer) {
      let cMarkup = '';
      if (roads && roads.corridor_path) {
        cMarkup = `<path id="cad-roads-corridor" d="${roads.corridor_path}" fill="rgba(30, 41, 59, 0.75)" stroke="#475569" stroke-width="1.5" />`;
      }
      el.svgRoadCorridorLayer.innerHTML = cMarkup;
    }

    if (el.svgRoadBufferLayer) {
      let bufMarkup = '';
      if (roads && roads.buffer_path) {
        bufMarkup = `<path id="cad-roads-buffer" d="${roads.buffer_path}" fill="rgba(245, 158, 11, 0.06)" stroke="#f59e0b" stroke-width="1.2" stroke-dasharray="6,4" />`;
      }
      el.svgRoadBufferLayer.innerHTML = bufMarkup;
    }

    // 5. Road Centerlines
    if (el.svgRoadCenterlinesLayer) {
      let clMarkup = '';
      if (roads && roads.centerlines_paths) {
        roads.centerlines_paths.forEach(p => {
          clMarkup += `<path class="cad-centerline" d="${p}" fill="none" stroke="#f8fafc" stroke-width="2" stroke-dasharray="8,5" />`;
        });
      }
      el.svgRoadCenterlinesLayer.innerHTML = clMarkup;
    }

    // 6. Sub-blocks (Planning Quarters - strictly Step 2 & 3)
    if (el.svgSubBlocksLayer) {
      let sbMarkup = '';
      if (!isStep1 && roads && roads.sub_blocks_data && roads.sub_blocks_data.length > 0) {
        roads.sub_blocks_data.forEach(b => {
          // Polygon
          sbMarkup += `<path class="sub-block-poly" data-block-idx="${b.index}" d="${b.path}" fill="rgba(16, 185, 129, 0.12)" stroke="#10b981" stroke-width="2" />`;
          // Centroid Badge
          if (b.centroid_svg && b.centroid_svg.length >= 2) {
            sbMarkup += `
              <g class="sub-block-badge" data-block-idx="${b.index}" transform="translate(${b.centroid_svg[0]}, ${b.centroid_svg[1]})" style="pointer-events: none;">
                <circle r="14" fill="#0f172a" stroke="#10b981" stroke-width="1.8" />
                <text text-anchor="middle" dy="4" fill="#10b981" font-size="11" font-weight="bold">${b.index}</text>
                <rect x="-32" y="18" width="64" height="18" rx="4" fill="#0f172a" stroke="rgba(255,255,255,0.18)" stroke-width="1" />
                <text text-anchor="middle" dy="31" fill="#f8fafc" font-size="10" font-family="monospace">${fmtNum2(b.area_ha)} га</text>
              </g>
            `;
          }
        });
      } else if (!isStep1 && data.buildable_path) {
        // Fallback: single buildable area if no sub-blocks on Step 2/3
        sbMarkup = `<path id="cad-setback-bound" d="${data.buildable_path}" fill="rgba(16, 185, 129, 0.08)" stroke="#10b981" stroke-width="1.8" stroke-dasharray="6,4" />`;
      }
      el.svgSubBlocksLayer.innerHTML = sbMarkup;
      bindSubBlockPolyEvents();
    }

    // 7. Render Custom Road Handles & Entry Points
    if (!isStep1) {
      renderCustomRoadHandles();
      renderEntryPointsOnSvg();
    } else {
      if (el.svgRoadHandlesLayer) el.svgRoadHandlesLayer.innerHTML = '';
      if (el.svgEntryPointsLayer) el.svgEntryPointsLayer.innerHTML = '';
      if (el.svgBuildingsLayer) el.svgBuildingsLayer.innerHTML = '';
      if (el.svgSectionsLayer) el.svgSectionsLayer.innerHTML = '';
      if (el.svgParkingLayer) el.svgParkingLayer.innerHTML = '';
      if (el.svgFireSafetyLayer) el.svgFireSafetyLayer.innerHTML = '';
    }

    fitSvgToViewport(data.svg_viewbox || '0 0 1000 700');
  }

  // --- RENDER STEP 2: TERRITORY BALANCE & SUB-BLOCKS TABLE ---
  function renderStep2Roads(data) {
    if (!data) return;
    const roads = data.roads || {};
    const subBlocks = roads.sub_blocks_data || [];
    const count = roads.sub_blocks_count || (subBlocks.length || 1);

    // Hero tag & Verif card
    if (el.panelHeroBlocks) el.panelHeroBlocks.textContent = `${count} ${pluralBlocks(count)}`;
    if (el.verifBlocksCount) el.verifBlocksCount.textContent = count;
    if (el.tbBlocksCount) el.tbBlocksCount.textContent = count;
    if (el.tbBlocksBadge) el.tbBlocksBadge.textContent = `${count} ${pluralBlocks(count)}`;

    // Territory Balance
    const siteArea = data.site_area_sqm || 0;
    const siteAreaHa = data.site_area_ha || (siteArea / 10000.0);
    const roadsArea = roads.area_sqm || 0.0;
    const bufferArea = roads.buffer_area_sqm || 0.0;
    const roadsLength = roads.length_m || 0.0;

    let subAreaSum = subBlocks.reduce((acc, b) => acc + (b.area_sqm || 0), 0);
    if (subAreaSum <= 0 && data.buildable_area_sqm) subAreaSum = data.buildable_area_sqm;

    const roadsShare = siteArea > 0 ? ((roadsArea / siteArea) * 100).toFixed(1) : '0.0';
    const blocksShare = siteArea > 0 ? ((subAreaSum / siteArea) * 100).toFixed(1) : '0.0';

    if (el.tbSiteArea) el.tbSiteArea.textContent = `${fmtNum2(siteAreaHa)} га (${fmtInt(siteArea)} м²)`;
    if (el.tbRoadsArea) el.tbRoadsArea.textContent = `${fmtInt(roadsArea)} м²`;
    if (el.tbRoadsShare) el.tbRoadsShare.textContent = `${roadsShare} %`;
    if (el.tbBufferArea) el.tbBufferArea.textContent = `${fmtInt(bufferArea)} м²`;
    if (el.tbBlocksArea) el.tbBlocksArea.textContent = `${fmtInt(subAreaSum)} м² (${(subAreaSum / 10000).toFixed(2)} га)`;
    if (el.tbBlocksShare) el.tbBlocksShare.textContent = `${blocksShare} %`;
    if (el.tbRoadsLength) el.tbRoadsLength.textContent = `${Math.round(roadsLength)} м`;

    // Sub-blocks Table
    if (el.tbodySubBlocks) {
      if (subBlocks.length === 0) {
        el.tbodySubBlocks.innerHTML = `
          <tr class="sub-block-row" data-block-idx="1">
            <td style="padding:6px 8px;"><span class="block-num-badge">1</span></td>
            <td style="padding:6px 8px; text-align:right;">${fmtNum2(siteAreaHa * 0.8)} га <span style="color:var(--text-muted); font-size:10px;">(${fmtInt(subAreaSum)} м²)</span></td>
            <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono); font-weight:600; color:var(--success);">${blocksShare}%</td>
          </tr>
        `;
      } else {
        let rowsHtml = '';
        subBlocks.forEach(b => {
          const share = siteArea > 0 ? ((b.area_sqm / siteArea) * 100).toFixed(1) : '—';
          rowsHtml += `
            <tr class="sub-block-row" data-block-idx="${b.index}">
              <td style="padding:6px 8px;"><span class="block-num-badge">${b.index}</span></td>
              <td style="padding:6px 8px; text-align:right;">
                <b>${fmtNum2(b.area_ha)} га</b>
                <span style="color:var(--text-muted); font-size:10px; margin-left:3px;">(${fmtInt(b.area_sqm)} м²)</span>
              </td>
              <td style="padding:6px 8px; text-align:right; font-family:var(--font-mono); font-weight:600; color:var(--success);">${share}%</td>
            </tr>
          `;
        });
        el.tbodySubBlocks.innerHTML = rowsHtml;
      }
      bindSubBlockTableEvents();
    }
  }

  function pluralBlocks(n) {
    const mod10 = n % 10;
    const mod100 = n % 100;
    if (mod10 === 1 && mod100 !== 11) return 'квартал';
    if (mod10 >= 2 && mod10 <= 4 && (mod100 < 10 || mod100 >= 20)) return 'квартала';
    return 'кварталов';
  }

  // --- BIDIRECTIONAL HOVER (SUB-BLOCKS TABLE <-> SVG PLAN) ---
  function bindSubBlockPolyEvents() {
    const polys = el.svgSubBlocksLayer ? el.svgSubBlocksLayer.querySelectorAll('.sub-block-poly') : [];
    polys.forEach(p => {
      const idx = p.dataset.blockIdx;
      p.addEventListener('mouseenter', () => {
        p.classList.add('highlighted');
        const row = el.tbodySubBlocks ? el.tbodySubBlocks.querySelector(`.sub-block-row[data-block-idx="${idx}"]`) : null;
        if (row) row.classList.add('active');
      });
      p.addEventListener('mouseleave', () => {
        p.classList.remove('highlighted');
        const row = el.tbodySubBlocks ? el.tbodySubBlocks.querySelector(`.sub-block-row[data-block-idx="${idx}"]`) : null;
        if (row) row.classList.remove('active');
      });
    });
  }

  function bindSubBlockTableEvents() {
    const rows = el.tbodySubBlocks ? el.tbodySubBlocks.querySelectorAll('.sub-block-row') : [];
    rows.forEach(r => {
      const idx = r.dataset.blockIdx;
      r.addEventListener('mouseenter', () => {
        r.classList.add('active');
        const poly = el.svgSubBlocksLayer ? el.svgSubBlocksLayer.querySelector(`.sub-block-poly[data-block-idx="${idx}"]`) : null;
        if (poly) poly.classList.add('highlighted');
      });
      r.addEventListener('mouseleave', () => {
        r.classList.remove('active');
        const poly = el.svgSubBlocksLayer ? el.svgSubBlocksLayer.querySelector(`.sub-block-poly[data-block-idx="${idx}"]`) : null;
        if (poly) poly.classList.remove('highlighted');
      });
    });
  }

  // --- STEP 2: ROAD PRESETS & CATEGORIES CONTROLS ---
  el.presetBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const preset = btn.dataset.preset;
      el.presetBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const presetLabels = {
        none: 'Без дорог',
        longitudinal: 'Продольная (редактируемая)',
        transverse: 'Поперечная (редактируемая)',
        cross_2x2: 'Сетка 2×2 (редактируемая)',
        custom: 'На чертеже'
      };
      if (el.valPresetBadge) el.valPresetBadge.textContent = presetLabels[preset] || preset;

      if (preset === 'none') {
        state.activePresetTemplate = null;
        state.road_preset = 'none';
        state.custom_roads = [];
        state.entry_points = [];
        state.currentScenario = null;
        if (el.groupRoadPos) el.groupRoadPos.style.display = 'none';
        if (el.groupRoadPosGrid) el.groupRoadPosGrid.style.display = 'none';
        updateCustomRoadsUI();
        if (typeof updateEntryPointsUI === 'function') updateEntryPointsUI();
        if (typeof renderEntryPointsOnSvg === 'function') renderEntryPointsOnSvg();
        apiPreviewSite(true);
      } else if (preset === 'longitudinal' || preset === 'transverse' || preset === 'cross_2x2') {
        if (el.groupRoadPos && el.groupRoadPosGrid) {
          if (preset === 'cross_2x2') {
            el.groupRoadPos.style.display = 'none';
            el.groupRoadPosGrid.style.display = 'block';
          } else {
            el.groupRoadPos.style.display = 'block';
            el.groupRoadPosGrid.style.display = 'none';
          }
        }
        applyPresetToEntryPoints(preset);
      } else if (preset === 'custom') {
        state.activePresetTemplate = null;
        state.road_preset = 'custom';
        if (el.groupRoadPos) el.groupRoadPos.style.display = 'none';
        if (el.groupRoadPosGrid) el.groupRoadPosGrid.style.display = 'none';
        apiPreviewSite(true);
      }
    });
  });

  // Road Norm Categories Pills (СП 42.13330)
  el.catPills.forEach(pill => {
    pill.addEventListener('click', () => {
      const cat = pill.dataset.cat;
      state.road_category = cat;

      el.catPills.forEach(p => p.classList.remove('active'));
      pill.classList.add('active');

      if (cat === 'district') {
        state.road_width = 15.0;
        state.road_setback = 4.0;
        if (el.valCategoryPillTag) el.valCategoryPillTag.textContent = 'Внутриквартальная 15м';
      } else if (cat === 'arterial') {
        state.road_width = 22.0;
        state.road_setback = 6.0;
        if (el.valCategoryPillTag) el.valCategoryPillTag.textContent = 'Магистральная 22м';
      } else if (cat === 'local') {
        state.road_width = 8.0;
        state.road_setback = 3.0;
        if (el.valCategoryPillTag) el.valCategoryPillTag.textContent = 'Проезд 8м';
      } else {
        if (el.valCategoryPillTag) el.valCategoryPillTag.textContent = 'Настраиваемая';
      }

      if (el.sliderRoadWidth) el.sliderRoadWidth.value = state.road_width;
      if (el.valRoadWidth) el.valRoadWidth.textContent = `${state.road_width.toFixed(1)} м`;
      if (el.sliderRoadSetback) el.sliderRoadSetback.value = state.road_setback;
      if (el.valRoadSetback) el.valRoadSetback.textContent = `${state.road_setback.toFixed(1)} м`;

      apiPreviewSite(true);
    });
  });

  // Road Width Slider
  if (el.sliderRoadWidth) {
    el.sliderRoadWidth.addEventListener('input', () => {
      const val = parseFloat(el.sliderRoadWidth.value);
      state.road_width = val;
      if (el.valRoadWidth) el.valRoadWidth.textContent = `${val.toFixed(1)} м`;
      apiPreviewSite();
    });
    el.sliderRoadWidth.addEventListener('change', () => {
      apiPreviewSite(true);
    });
  }

  // Road Setback Slider
  if (el.sliderRoadSetback) {
    el.sliderRoadSetback.addEventListener('input', () => {
      const val = parseFloat(el.sliderRoadSetback.value);
      state.road_setback = val;
      if (el.valRoadSetback) el.valRoadSetback.textContent = `${val.toFixed(1)} м`;
      apiPreviewSite();
    });
    el.sliderRoadSetback.addEventListener('change', () => {
      apiPreviewSite(true);
    });
  }

  // Single Pos Ratio Slider
  if (el.sliderRoadPos) {
    el.sliderRoadPos.addEventListener('input', () => {
      const val = parseInt(el.sliderRoadPos.value, 10);
      state.road_pos = val / 100.0;
      if (el.valRoadPos) el.valRoadPos.textContent = `${val}%`;
      if (state.activePresetTemplate === 'longitudinal' || state.activePresetTemplate === 'transverse') {
        applyPresetToEntryPoints(state.activePresetTemplate);
      } else {
        apiPreviewSite();
      }
    });
    el.sliderRoadPos.addEventListener('change', () => {
      if (state.activePresetTemplate === 'longitudinal' || state.activePresetTemplate === 'transverse') {
        applyPresetToEntryPoints(state.activePresetTemplate);
      } else {
        apiPreviewSite(true);
      }
    });
  }

  // Dual Pos Grid Sliders (X & Y)
  function onGridPosChange() {
    const px = parseInt(el.sliderRoadPosX ? el.sliderRoadPosX.value : '50', 10);
    const py = parseInt(el.sliderRoadPosY ? el.sliderRoadPosY.value : '50', 10);
    state.road_pos_x = px / 100.0;
    state.road_pos_y = py / 100.0;
    if (el.valRoadPosXY) el.valRoadPosXY.textContent = `${px}% / ${py}%`;
    if (state.activePresetTemplate === 'cross_2x2') {
      applyPresetToEntryPoints('cross_2x2');
    } else {
      apiPreviewSite(true);
    }
  }

  if (el.sliderRoadPosX) {
    el.sliderRoadPosX.addEventListener('input', () => {
      const px = parseInt(el.sliderRoadPosX.value, 10);
      const py = parseInt(el.sliderRoadPosY ? el.sliderRoadPosY.value : '50', 10);
      if (el.valRoadPosXY) el.valRoadPosXY.textContent = `${px}% / ${py}%`;
    });
    el.sliderRoadPosX.addEventListener('change', onGridPosChange);
  }

  if (el.sliderRoadPosY) {
    el.sliderRoadPosY.addEventListener('input', () => {
      const px = parseInt(el.sliderRoadPosX ? el.sliderRoadPosX.value : '50', 10);
      const py = parseInt(el.sliderRoadPosY.value, 10);
      if (el.valRoadPosXY) el.valRoadPosXY.textContent = `${px}% / ${py}%`;
    });
    el.sliderRoadPosY.addEventListener('change', onGridPosChange);
  }

  // --- STEP 2: INTERACTIVE ROAD DRAWING (CANVAS CAD) ---
  if (el.btnDrawRoad) {
    el.btnDrawRoad.addEventListener('click', () => {
      toggleDrawingMode(!state.isDrawingRoad);
    });
  }

  // =========================================================================
  // ENTRY POINTS (ВЪЕЗДЫ НА ГРАНИЦЕ УЧАСТКА ДЛЯ АВТО-ТРАССИРОВКИ УДС)
  // =========================================================================

  function projectPointToBoundary(px, py, boundaryCoords) {
    if (!boundaryCoords || boundaryCoords.length < 2) return [px, py];
    let bestDistSq = Infinity;
    let bestPt = [px, py];
    const n = boundaryCoords.length;
    for (let i = 0; i < n; i++) {
      const p1 = boundaryCoords[i];
      const p2 = boundaryCoords[(i + 1) % n];
      const x1 = p1[0], y1 = p1[1];
      const x2 = p2[0], y2 = p2[1];
      const dx = x2 - x1;
      const dy = y2 - y1;
      const lenSq = dx * dx + dy * dy;
      if (lenSq === 0) continue;
      let t = ((px - x1) * dx + (py - y1) * dy) / lenSq;
      t = Math.max(0, Math.min(1, t));
      const projX = x1 + t * dx;
      const projY = y1 + t * dy;
      const distSq = (px - projX) * (px - projX) + (py - projY) * (py - projY);
      if (distSq < bestDistSq) {
        bestDistSq = distSq;
        bestPt = [projX, projY];
      }
    }
    return bestPt;
  }

  function findSegmentIntersection(p1, p2, p3, p4) {
    const x1 = p1[0], y1 = p1[1];
    const x2 = p2[0], y2 = p2[1];
    const x3 = p3[0], y3 = p3[1];
    const x4 = p4[0], y4 = p4[1];

    const denom = (y4 - y3) * (x2 - x1) - (x4 - x3) * (y2 - y1);
    if (Math.abs(denom) < 1e-9) return null;

    const ua = ((x4 - x3) * (y1 - y3) - (y4 - y3) * (x1 - x3)) / denom;
    const ub = ((x2 - x1) * (y1 - y3) - (y2 - y1) * (x1 - x3)) / denom;

    if (ua >= 0 && ua <= 1 && ub >= 0 && ub <= 1) {
      return [x1 + ua * (x2 - x1), y1 + ua * (y2 - y1)];
    }
    return null;
  }

  function getBoundaryCutPoints(lineP1, lineP2, boundaryCoords) {
    if (!boundaryCoords || boundaryCoords.length < 3) return [];
    const hits = [];
    const n = boundaryCoords.length;
    for (let i = 0; i < n; i++) {
      const b1 = boundaryCoords[i];
      const b2 = boundaryCoords[(i + 1) % n];
      const pt = findSegmentIntersection(lineP1, lineP2, b1, b2);
      if (pt) {
        if (!hits.some(h => Math.hypot(h[0] - pt[0], h[1] - pt[1]) < 0.5)) {
          hits.push([round2(pt[0]), round2(pt[1])]);
        }
      }
    }
    return hits;
  }

  function applyPresetToEntryPoints(preset) {
    if (!state.currentData || !state.currentData.boundary_coords || state.currentData.boundary_coords.length < 3) {
      return;
    }
    const bCoords = state.currentData.boundary_coords;
    let minx = Infinity, miny = Infinity, maxx = -Infinity, maxy = -Infinity;
    bCoords.forEach(p => {
      if (p[0] < minx) minx = p[0];
      if (p[1] < miny) miny = p[1];
      if (p[0] > maxx) maxx = p[0];
      if (p[1] > maxy) maxy = p[1];
    });

    const width = maxx - minx;
    const height = maxy - miny;
    const pad = Math.max(width, height) * 0.2;

    const rx = Math.max(0.15, Math.min(0.85, state.road_pos_x != null ? state.road_pos_x : (state.road_pos != null ? state.road_pos : 0.5)));
    const ry = Math.max(0.15, Math.min(0.85, state.road_pos_y != null ? state.road_pos_y : (state.road_pos != null ? state.road_pos : 0.5)));

    const cx = minx + width * rx;
    const cy = miny + height * ry;

    const newEntries = [];

    if (preset === 'longitudinal') {
      state.activePresetTemplate = 'longitudinal';
      if (width >= height) {
        const cuts = getBoundaryCutPoints([minx - pad, cy], [maxx + pad, cy], bCoords);
        cuts.sort((a, b) => a[0] - b[0]);
        if (cuts.length >= 2) {
          newEntries.push({
            id: 'ep_w',
            name: 'Въезд Запад',
            x: cuts[0][0],
            y: cuts[0][1],
            category: state.road_category || 'district',
            width: state.road_width || 15.0,
            setback: state.road_setback || 4.0
          });
          newEntries.push({
            id: 'ep_e',
            name: 'Въезд Восток',
            x: cuts[cuts.length - 1][0],
            y: cuts[cuts.length - 1][1],
            category: state.road_category || 'district',
            width: state.road_width || 15.0,
            setback: state.road_setback || 4.0
          });
        }
      } else {
        const cuts = getBoundaryCutPoints([cx, miny - pad], [cx, maxy + pad], bCoords);
        cuts.sort((a, b) => a[1] - b[1]);
        if (cuts.length >= 2) {
          newEntries.push({
            id: 'ep_s',
            name: 'Въезд Юг',
            x: cuts[0][0],
            y: cuts[0][1],
            category: state.road_category || 'district',
            width: state.road_width || 15.0,
            setback: state.road_setback || 4.0
          });
          newEntries.push({
            id: 'ep_n',
            name: 'Въезд Север',
            x: cuts[cuts.length - 1][0],
            y: cuts[cuts.length - 1][1],
            category: state.road_category || 'district',
            width: state.road_width || 15.0,
            setback: state.road_setback || 4.0
          });
        }
      }
    } else if (preset === 'transverse') {
      state.activePresetTemplate = 'transverse';
      if (width >= height) {
        const cuts = getBoundaryCutPoints([cx, miny - pad], [cx, maxy + pad], bCoords);
        cuts.sort((a, b) => a[1] - b[1]);
        if (cuts.length >= 2) {
          newEntries.push({
            id: 'ep_s',
            name: 'Въезд Юг',
            x: cuts[0][0],
            y: cuts[0][1],
            category: state.road_category || 'district',
            width: state.road_width || 15.0,
            setback: state.road_setback || 4.0
          });
          newEntries.push({
            id: 'ep_n',
            name: 'Въезд Север',
            x: cuts[cuts.length - 1][0],
            y: cuts[cuts.length - 1][1],
            category: state.road_category || 'district',
            width: state.road_width || 15.0,
            setback: state.road_setback || 4.0
          });
        }
      } else {
        const cuts = getBoundaryCutPoints([minx - pad, cy], [maxx + pad, cy], bCoords);
        cuts.sort((a, b) => a[0] - b[0]);
        if (cuts.length >= 2) {
          newEntries.push({
            id: 'ep_w',
            name: 'Въезд Запад',
            x: cuts[0][0],
            y: cuts[0][1],
            category: state.road_category || 'district',
            width: state.road_width || 15.0,
            setback: state.road_setback || 4.0
          });
          newEntries.push({
            id: 'ep_e',
            name: 'Въезд Восток',
            x: cuts[cuts.length - 1][0],
            y: cuts[cuts.length - 1][1],
            category: state.road_category || 'district',
            width: state.road_width || 15.0,
            setback: state.road_setback || 4.0
          });
        }
      }
    } else if (preset === 'cross_2x2') {
      state.activePresetTemplate = 'cross_2x2';
      const cutsH = getBoundaryCutPoints([minx - pad, cy], [maxx + pad, cy], bCoords);
      cutsH.sort((a, b) => a[0] - b[0]);
      const cutsV = getBoundaryCutPoints([cx, miny - pad], [cx, maxy + pad], bCoords);
      cutsV.sort((a, b) => a[1] - b[1]);

      if (cutsH.length >= 2) {
        newEntries.push({
          id: 'ep_w',
          name: 'Въезд Запад',
          x: cutsH[0][0],
          y: cutsH[0][1],
          category: state.road_category || 'district',
          width: state.road_width || 15.0,
          setback: state.road_setback || 4.0
        });
        newEntries.push({
          id: 'ep_e',
          name: 'Въезд Восток',
          x: cutsH[cutsH.length - 1][0],
          y: cutsH[cutsH.length - 1][1],
          category: state.road_category || 'district',
          width: state.road_width || 15.0,
          setback: state.road_setback || 4.0
        });
      }
      if (cutsV.length >= 2) {
        newEntries.push({
          id: 'ep_s',
          name: 'Въезд Юг',
          x: cutsV[0][0],
          y: cutsV[0][1],
          category: state.road_category || 'district',
          width: state.road_width || 15.0,
          setback: state.road_setback || 4.0
        });
        newEntries.push({
          id: 'ep_n',
          name: 'Въезд Север',
          x: cutsV[cutsV.length - 1][0],
          y: cutsV[cutsV.length - 1][1],
          category: state.road_category || 'district',
          width: state.road_width || 15.0,
          setback: state.road_setback || 4.0
        });
      }
    }

    if (newEntries.length > 0) {
      state.entry_points = newEntries;
      state.uds_mode = 'entries';
      if (el.btnTabEntryPoints) {
        el.btnTabEntryPoints.classList.add('active');
        if (el.btnTabFreeDraw) el.btnTabFreeDraw.classList.remove('active');
        if (el.subviewEntryPoints) el.subviewEntryPoints.style.display = 'block';
        if (el.subviewFreeDraw) el.subviewFreeDraw.style.display = 'none';
      }
      updateEntryPointsUI();
      renderEntryPointsOnSvg();
      rebuildRoadsFromEntryPoints();
    }
  }

  // Subtab switching (Въезды vs Свободное черчение)
  if (el.btnTabEntryPoints) {
    el.btnTabEntryPoints.addEventListener('click', () => {
      state.uds_mode = 'entries';
      if (el.btnTabEntryPoints) el.btnTabEntryPoints.classList.add('active');
      if (el.btnTabFreeDraw) el.btnTabFreeDraw.classList.remove('active');
      if (el.subviewEntryPoints) el.subviewEntryPoints.style.display = 'block';
      if (el.subviewFreeDraw) el.subviewFreeDraw.style.display = 'none';
      toggleDrawingMode(false);
      renderCustomRoadHandles();
      renderEntryPointsOnSvg();
    });
  }
  if (el.btnTabFreeDraw) {
    el.btnTabFreeDraw.addEventListener('click', () => {
      state.uds_mode = 'free_draw';
      if (el.btnTabEntryPoints) el.btnTabEntryPoints.classList.remove('active');
      if (el.btnTabFreeDraw) el.btnTabFreeDraw.classList.add('active');
      if (el.subviewEntryPoints) el.subviewEntryPoints.style.display = 'none';
      if (el.subviewFreeDraw) el.subviewFreeDraw.style.display = 'block';
      toggleAddEntryPointMode(false);
      renderCustomRoadHandles();
      renderEntryPointsOnSvg();
    });
  }

  function toggleAddEntryPointMode(forceState = null) {
    state.isAddingEntryPoint = forceState !== null ? forceState : !state.isAddingEntryPoint;
    if (state.isAddingEntryPoint) {
      toggleDrawingMode(false);
    }
    if (el.btnAddEntryPoint) {
      el.btnAddEntryPoint.classList.toggle('active', state.isAddingEntryPoint);
      if (state.isAddingEntryPoint) {
        if (el.btnEntryIcon) el.btnEntryIcon.textContent = '❌';
        if (el.btnEntryText) el.btnEntryText.textContent = 'Отменить установку';
        if (el.entryRoadHint) {
          el.entryRoadHint.innerHTML = '<b>Режим активен:</b> Кликните по красной/синей линии границы ЗУ, чтобы добавить точку въезда.';
          el.entryRoadHint.style.borderColor = 'var(--accent)';
          el.entryRoadHint.style.color = 'var(--accent)';
        }
      } else {
        if (el.btnEntryIcon) el.btnEntryIcon.textContent = '📍';
        if (el.btnEntryText) el.btnEntryText.textContent = 'Поставить въезд на границе';
        if (el.entryRoadHint) {
          el.entryRoadHint.innerHTML = state.entry_points.length === 0
            ? 'Кликните <b>«Поставить въезд»</b>, затем укажите 2–4 точки на границе участка. Алгоритм увяжет их в связную сеть улиц и нарежет кварталы.'
            : `Установлено въездов: <b>${state.entry_points.length}</b>. Перетаскивайте маркеры по границе ЗУ для тонкой настройки трассировки.`;
          el.entryRoadHint.style.borderColor = 'var(--accent-border)';
          el.entryRoadHint.style.color = 'var(--text-secondary)';
        }
      }
    }
    if (el.svgCanvas) {
      el.svgCanvas.classList.toggle('drawing-mode', state.isAddingEntryPoint);
    }
  }

  if (el.btnAddEntryPoint) {
    el.btnAddEntryPoint.addEventListener('click', () => {
      toggleAddEntryPointMode();
    });
  }

  if (el.btnClearEntries) {
    el.btnClearEntries.addEventListener('click', () => {
      state.entry_points = [];
      state.custom_roads = [];
      updateEntryPointsUI();
      renderEntryPointsOnSvg();
      if (state.road_preset === 'custom') {
        state.road_preset = 'none';
        el.presetBtns.forEach(b => b.classList.toggle('active', b.dataset.preset === 'none'));
        if (el.valPresetBadge) el.valPresetBadge.textContent = 'Без дорог';
      }
      apiPreviewSite(true);
    });
  }

  function getEntryCatLabel(cat) {
    if (cat === 'arterial') return 'Магистральная';
    if (cat === 'local') return 'Местная';
    return 'Районная';
  }

  function updateEntryPointsUI() {
    if (!el.entryPointsList) return;
    if (state.entry_points.length === 0) {
      el.entryPointsList.innerHTML = '';
      if (el.entryRoadHint && !state.isAddingEntryPoint) {
        el.entryRoadHint.innerHTML = 'Кликните <b>«Поставить въезд»</b>, затем укажите 2–4 точки на границе участка. Алгоритм увяжет их в связную сеть улиц и нарежет кварталы.';
        el.entryRoadHint.style.borderColor = 'var(--accent-border)';
        el.entryRoadHint.style.color = 'var(--text-secondary)';
      }
      return;
    }

    let html = '';
    state.entry_points.forEach((ep, idx) => {
      const w = ep.width || 15.0;
      const isLocal = ep.category === 'local' || w <= 10.0;
      const isArterial = ep.category === 'arterial' || w >= 20.0;
      const isDistrict = !isLocal && !isArterial;

      html += `
        <div class="entry-point-card" data-entry-idx="${idx}">
          <div class="entry-point-header">
            <div class="entry-point-title">
              <span class="entry-num-badge">${idx + 1}</span>
              <span class="entry-point-name">${ep.name || ('Въезд ' + (idx + 1))}</span>
              <span class="entry-point-coords">(${Math.round(ep.x)}м, ${Math.round(ep.y)}м)</span>
            </div>
            <button class="entry-del-btn" data-entry-del-idx="${idx}" title="Удалить въезд">×</button>
          </div>

          <div class="entry-cat-pills">
            <button type="button" class="entry-cat-pill ${isLocal ? 'active' : ''}" data-cat="local" data-entry-idx="${idx}" title="Местная улица (8м)">
              🚙 Местная
            </button>
            <button type="button" class="entry-cat-pill ${isDistrict ? 'active' : ''}" data-cat="district" data-entry-idx="${idx}" title="Районная улица (15м)">
              🛣️ Районная
            </button>
            <button type="button" class="entry-cat-pill ${isArterial ? 'active' : ''}" data-cat="arterial" data-entry-idx="${idx}" title="Магистральная улица (22м)">
              🚚 Магистраль
            </button>
          </div>

          <div class="entry-width-row">
            <span class="entry-width-label">Ширина улицы:</span>
            <div class="entry-stepper">
              <button type="button" class="entry-step-btn" data-entry-step-idx="${idx}" data-delta="-1" title="Уменьшить ширину на 1м">−</button>
              <div class="entry-stepper-val">
                <input type="number" class="entry-width-input" data-entry-input-idx="${idx}" min="6" max="40" step="0.5" value="${w}" />
                <span class="entry-step-unit">м</span>
              </div>
              <button type="button" class="entry-step-btn" data-entry-step-idx="${idx}" data-delta="1" title="Увеличить ширину на 1м">+</button>
            </div>
          </div>
        </div>
      `;
    });
    el.entryPointsList.innerHTML = html;

    // Category pills click handlers
    el.entryPointsList.querySelectorAll('.entry-cat-pill').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const pIdx = parseInt(btn.dataset.entryIdx, 10);
        const cat = btn.dataset.cat;
        const ep = state.entry_points[pIdx];
        if (!ep) return;

        if (cat === 'local') {
          ep.category = 'local';
          ep.width = 8.0;
          ep.setback = 3.0;
        } else if (cat === 'arterial') {
          ep.category = 'arterial';
          ep.width = 22.0;
          ep.setback = 6.0;
        } else {
          ep.category = 'district';
          ep.width = 15.0;
          ep.setback = 4.0;
        }

        // If 2 points, sync both so through-street stays coherent
        if (state.entry_points.length === 2) {
          const otherEp = state.entry_points[1 - pIdx];
          if (otherEp) {
            otherEp.category = ep.category;
            otherEp.width = ep.width;
            otherEp.setback = ep.setback;
          }
        }

        updateEntryPointsUI();
        renderEntryPointsOnSvg();
        rebuildRoadsFromEntryPoints();
      });
    });

    // Stepper minus/plus handlers
    el.entryPointsList.querySelectorAll('.entry-step-btn').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const sIdx = parseInt(btn.dataset.entryStepIdx, 10);
        const delta = parseFloat(btn.dataset.delta) || 0;
        const ep = state.entry_points[sIdx];
        if (!ep) return;

        const curW = ep.width || 15.0;
        const newW = Math.max(6.0, Math.min(40.0, round1(curW + delta)));
        ep.width = newW;
        if (newW <= 10.0) ep.category = 'local';
        else if (newW <= 18.0) ep.category = 'district';
        else ep.category = 'arterial';

        if (state.entry_points.length === 2) {
          const otherEp = state.entry_points[1 - sIdx];
          if (otherEp) {
            otherEp.width = newW;
            otherEp.category = ep.category;
          }
        }

        updateEntryPointsUI();
        renderEntryPointsOnSvg();
        rebuildRoadsFromEntryPoints();
      });
    });

    // Direct numeric input handlers
    el.entryPointsList.querySelectorAll('.entry-width-input').forEach(input => {
      const applyVal = () => {
        const iIdx = parseInt(input.dataset.entryInputIdx, 10);
        const val = parseFloat(input.value);
        const ep = state.entry_points[iIdx];
        if (!ep || isNaN(val)) return;

        const clamped = Math.max(6.0, Math.min(40.0, round1(val)));
        ep.width = clamped;
        if (clamped <= 10.0) ep.category = 'local';
        else if (clamped <= 18.0) ep.category = 'district';
        else ep.category = 'arterial';

        if (state.entry_points.length === 2) {
          const otherEp = state.entry_points[1 - iIdx];
          if (otherEp) {
            otherEp.width = clamped;
            otherEp.category = ep.category;
          }
        }

        renderEntryPointsOnSvg();
        rebuildRoadsFromEntryPoints();
      };
      input.addEventListener('change', applyVal);
      input.addEventListener('keydown', e => {
        if (e.key === 'Enter') {
          e.preventDefault();
          input.blur();
        }
      });
    });

    // Delete buttons
    el.entryPointsList.querySelectorAll('[data-entry-del-idx]').forEach(btn => {
      btn.addEventListener('click', e => {
        e.stopPropagation();
        const dIdx = parseInt(btn.dataset.entryDelIdx, 10);
        state.entry_points.splice(dIdx, 1);
        updateEntryPointsUI();
        renderEntryPointsOnSvg();
        rebuildRoadsFromEntryPoints();
      });
    });

    // Hover highlighting between card and canvas marker
    el.entryPointsList.querySelectorAll('.entry-point-card').forEach(card => {
      const idx = parseInt(card.dataset.entryIdx, 10);
      card.addEventListener('mouseenter', () => {
        card.classList.add('highlighted');
        if (el.svgEntryPointsLayer) {
          const m = el.svgEntryPointsLayer.querySelector(`.entry-marker[data-entry-idx="${idx}"]`);
          if (m) m.classList.add('highlighted');
          const line = el.svgEntryPointsLayer.querySelector(`.entry-ray-line[data-entry-idx="${idx}"]`);
          if (line) {
            line.setAttribute('stroke', '#38bdf8');
            line.setAttribute('stroke-width', '4.5');
          }
        }
      });
      card.addEventListener('mouseleave', () => {
        card.classList.remove('highlighted');
        if (el.svgEntryPointsLayer) {
          const m = el.svgEntryPointsLayer.querySelector(`.entry-marker[data-entry-idx="${idx}"]`);
          if (m) m.classList.remove('highlighted');
          const line = el.svgEntryPointsLayer.querySelector(`.entry-ray-line[data-entry-idx="${idx}"]`);
          const ep = state.entry_points[idx];
          if (line && ep) {
            line.setAttribute('stroke', '#0284c7');
            line.setAttribute('stroke-width', String(Math.max(2, Math.min(6, (ep.width || 15) / 4))));
          }
        }
      });
    });

    // Update hints according to points count
    if (el.entryRoadHint && !state.isAddingEntryPoint) {
      if (state.entry_points.length === 1) {
        el.entryRoadHint.innerHTML = '📍 <b>Въезд 1 установлен.</b> Добавьте еще хотя бы 1 точку въезда на границе для формирования улицы.';
        el.entryRoadHint.style.borderColor = 'var(--accent-border)';
      } else if (state.entry_points.length === 2) {
        el.entryRoadHint.innerHTML = '🚗 <b>Сквозной проезд сформирован (2 въезда).</b> Перетаскивайте маркеры по границе ЗУ или добавьте 3-й въезд для T-перекрестка.';
        el.entryRoadHint.style.borderColor = 'var(--success)';
      } else if (state.entry_points.length === 3) {
        el.entryRoadHint.innerHTML = '✨ <b>3-лучевой T-перекресток.</b> Участок разделен на 3 суб-квартала. Настройте ширину каждого въезда индивидуально.';
        el.entryRoadHint.style.borderColor = 'var(--accent)';
      } else {
        el.entryRoadHint.innerHTML = `✨ <b>${state.entry_points.length}-лучевой перекресток.</b> Участок разделен на ${state.entry_points.length} суб-квартала. Толщина каждой улицы настраивается отдельно.`;
        el.entryRoadHint.style.borderColor = 'var(--accent)';
      }
    }
  }

  function rebuildRoadsFromEntryPoints() {
    state.currentScenario = null; // Invalidate Step 3 scenario cache so it regenerates on clean sub-blocks
    if (state.entry_points.length === 0) {
      state.custom_roads = [];
      state.activePresetTemplate = null;
      updateCustomRoadsUI();
      if (state.road_preset === 'custom') {
        state.road_preset = 'none';
        el.presetBtns.forEach(b => b.classList.toggle('active', b.dataset.preset === 'none'));
        if (el.valPresetBadge) el.valPresetBadge.textContent = 'Без дорог';
      }
      apiPreviewSite(true);
      return;
    }

    if (state.entry_points.length === 1) {
      state.custom_roads = [];
      updateCustomRoadsUI();
      apiPreviewSite(true); // Clear old road corridors from canvas so there are no orphan roads
      return;
    }

    if (state.entry_points.length === 2) {
      const ep1 = state.entry_points[0];
      const ep2 = state.entry_points[1];
      const width = ep1.width || ep2.width || 15.0;
      const category = ep1.category || ep2.category || 'district';
      ep1.width = width;
      ep2.width = width;
      ep1.category = category;
      ep2.category = category;

      state.custom_roads = [
        {
          name: `Сквозной проезд (${width}м)`,
          category: category,
          width: width,
          setback: ep1.setback || 4.0,
          points: [
            [ep1.x, ep1.y],
            [ep2.x, ep2.y]
          ]
        }
      ];
    } else if (state.entry_points.length === 4) {
      const p = state.entry_points;
      let hub = null;
      const cross1 = findSegmentIntersection([p[0].x, p[0].y], [p[1].x, p[1].y], [p[2].x, p[2].y], [p[3].x, p[3].y]);
      const cross2 = findSegmentIntersection([p[0].x, p[0].y], [p[2].x, p[2].y], [p[1].x, p[1].y], [p[3].x, p[3].y]);
      const cross3 = findSegmentIntersection([p[0].x, p[0].y], [p[3].x, p[3].y], [p[1].x, p[1].y], [p[2].x, p[2].y]);
      if (cross1) hub = cross1;
      else if (cross2) hub = cross2;
      else if (cross3) hub = cross3;
      else {
        const sumX = p.reduce((acc, ep) => acc + ep.x, 0);
        const sumY = p.reduce((acc, ep) => acc + ep.y, 0);
        hub = [sumX / 4, sumY / 4];
      }
      const hubX = round2(hub[0]);
      const hubY = round2(hub[1]);

      state.custom_roads = p.map((ep, idx) => ({
        name: `Въезд ${idx + 1} (${ep.width || 15.0}м)`,
        category: ep.category || 'district',
        width: ep.width || 15.0,
        setback: ep.setback || 4.0,
        points: [[ep.x, ep.y], [hubX, hubY]]
      }));
    } else {
      const count = state.entry_points.length;
      const sumX = state.entry_points.reduce((acc, ep) => acc + ep.x, 0);
      const sumY = state.entry_points.reduce((acc, ep) => acc + ep.y, 0);
      const hubX = round2(sumX / count);
      const hubY = round2(sumY / count);

      state.custom_roads = state.entry_points.map((ep, idx) => ({
        name: `Въезд ${idx + 1} (${ep.width || 15.0}м)`,
        category: ep.category || 'district',
        width: ep.width || 15.0,
        setback: ep.setback || 4.0,
        points: [
          [ep.x, ep.y],
          [hubX, hubY]
        ]
      }));
    }

    state.road_preset = 'custom';
    const activeKey = state.activePresetTemplate || 'custom';
    el.presetBtns.forEach(b => b.classList.toggle('active', b.dataset.preset === activeKey));
    if (el.valPresetBadge) {
      const pLabels = { longitudinal: 'Продольная', transverse: 'Поперечная', cross_2x2: 'Сетка 2×2', custom: 'Въезды на границе' };
      el.valPresetBadge.textContent = pLabels[state.activePresetTemplate] || 'Въезды на границе';
    }

    updateCustomRoadsUI();
    apiPreviewSite(true);
  }

  function renderEntryPointsOnSvg() {
    if (!el.svgEntryPointsLayer) return;
    if (state.uds_mode !== 'entries' || state.entry_points.length === 0) {
      el.svgEntryPointsLayer.innerHTML = '';
      return;
    }

    const helpers = getCoordHelpers();
    let markup = '';

    // If 2 points, draw connecting axis guideline
    if (state.entry_points.length === 2) {
      const p1 = helpers.siteToSvg(state.entry_points[0].x, state.entry_points[0].y);
      const p2 = helpers.siteToSvg(state.entry_points[1].x, state.entry_points[1].y);
      markup += `
        <line x1="${p1[0]}" y1="${p1[1]}" x2="${p2[0]}" y2="${p2[1]}"
              stroke="#0284c7" stroke-width="2.5" stroke-dasharray="6,4" opacity="0.85" style="pointer-events:none;" />
      `;
    } else if (state.entry_points.length === 4) {
      const p = state.entry_points;
      let hub = null;
      const cross1 = findSegmentIntersection([p[0].x, p[0].y], [p[1].x, p[1].y], [p[2].x, p[2].y], [p[3].x, p[3].y]);
      const cross2 = findSegmentIntersection([p[0].x, p[0].y], [p[2].x, p[2].y], [p[1].x, p[1].y], [p[3].x, p[3].y]);
      const cross3 = findSegmentIntersection([p[0].x, p[0].y], [p[3].x, p[3].y], [p[1].x, p[1].y], [p[2].x, p[2].y]);
      if (cross1) hub = cross1;
      else if (cross2) hub = cross2;
      else if (cross3) hub = cross3;
      else {
        const sumX = p.reduce((acc, ep) => acc + ep.x, 0);
        const sumY = p.reduce((acc, ep) => acc + ep.y, 0);
        hub = [sumX / 4, sumY / 4];
      }
      const sCross = helpers.siteToSvg(hub[0], hub[1]);

      p.forEach((ep, idx) => {
        const sPt = helpers.siteToSvg(ep.x, ep.y);
        const rayW = Math.max(2, Math.min(6, (ep.width || 15) / 4));
        markup += `
          <line class="entry-ray-line" data-entry-idx="${idx}" x1="${sPt[0]}" y1="${sPt[1]}" x2="${sCross[0]}" y2="${sCross[1]}"
                stroke="#0284c7" stroke-width="${rayW}" stroke-dasharray="6,4" opacity="0.85" style="pointer-events:none;" />
        `;
      });
      markup += `
        <g class="entry-hub" style="pointer-events:none;">
          <circle cx="${sCross[0]}" cy="${sCross[1]}" r="8" fill="#0284c7" fill-opacity="0.3" stroke="#0284c7" stroke-width="2" />
          <circle cx="${sCross[0]}" cy="${sCross[1]}" r="3" fill="#ffffff" />
        </g>
      `;
    } else if (state.entry_points.length === 3) {
      const sumX = state.entry_points.reduce((acc, ep) => acc + ep.x, 0);
      const sumY = state.entry_points.reduce((acc, ep) => acc + ep.y, 0);
      const cSite = [sumX / 3, sumY / 3];
      const cSvg = helpers.siteToSvg(cSite[0], cSite[1]);

      state.entry_points.forEach((ep, idx) => {
        const sPt = helpers.siteToSvg(ep.x, ep.y);
        const rayW = Math.max(2, Math.min(6, (ep.width || 15) / 4));
        markup += `
          <line class="entry-ray-line" data-entry-idx="${idx}" x1="${sPt[0]}" y1="${sPt[1]}" x2="${cSvg[0]}" y2="${cSvg[1]}"
                stroke="#0284c7" stroke-width="${rayW}" stroke-dasharray="6,4" opacity="0.85" style="pointer-events:none;" />
        `;
      });

      markup += `
        <g class="entry-hub" style="pointer-events:none;">
          <circle cx="${cSvg[0]}" cy="${cSvg[1]}" r="8" fill="#0284c7" fill-opacity="0.3" stroke="#0284c7" stroke-width="2" />
          <circle cx="${cSvg[0]}" cy="${cSvg[1]}" r="3" fill="#ffffff" />
        </g>
      `;
    }

    // Draggable entry markers + Width text badges
    state.entry_points.forEach((ep, idx) => {
      const sPt = helpers.siteToSvg(ep.x, ep.y);
      const label = `${idx + 1}`;
      const badgeText = `${ep.width || 15}м`;
      const badgeW = badgeText.length * 7 + 10;
      markup += `
        <g class="entry-marker" data-entry-idx="${idx}" transform="translate(${sPt[0]}, ${sPt[1]})">
          <circle cx="0" cy="0" r="14" fill="#0284c7" stroke="#ffffff" stroke-width="2.5" filter="drop-shadow(0 2px 5px rgba(0,0,0,0.35))" />
          <text x="0" y="4" text-anchor="middle" font-size="11" font-weight="700" fill="#ffffff" style="pointer-events:none; font-family:var(--font-mono, sans-serif);">${label}</text>
          <!-- Width badge pill -->
          <g class="entry-canvas-badge" transform="translate(18, -9)">
            <rect x="0" y="0" width="${badgeW}" height="18" rx="4" fill="#0f172a" fill-opacity="0.92" stroke="#0284c7" stroke-width="1.2" />
            <text x="${badgeW / 2}" y="13" text-anchor="middle" fill="#38bdf8" font-size="10.5" font-weight="bold">${badgeText}</text>
          </g>
        </g>
      `;
    });

    el.svgEntryPointsLayer.innerHTML = markup;
    bindEntryMarkerDragEvents();
  }

  function bindEntryMarkerDragEvents() {
    if (!el.svgEntryPointsLayer) return;
    const markers = el.svgEntryPointsLayer.querySelectorAll('.entry-marker');
    markers.forEach(m => {
      const idx = parseInt(m.dataset.entryIdx, 10);
      m.addEventListener('mousedown', e => {
        e.stopPropagation();
        state.activeEntryDrag = { idx };
      });
      m.addEventListener('mouseenter', () => {
        m.classList.add('highlighted');
        if (el.entryPointsList) {
          const c = el.entryPointsList.querySelector(`.entry-point-card[data-entry-idx="${idx}"]`);
          if (c) c.classList.add('highlighted');
        }
      });
      m.addEventListener('mouseleave', () => {
        m.classList.remove('highlighted');
        if (el.entryPointsList) {
          const c = el.entryPointsList.querySelector(`.entry-point-card[data-entry-idx="${idx}"]`);
          if (c) c.classList.remove('highlighted');
        }
      });
    });
  }

  function toggleDrawingMode(active) {
    state.isDrawingRoad = active;
    state.drawingRoadStart = null;
    if (el.svgRoadDrawingLayer) el.svgRoadDrawingLayer.innerHTML = '';

    if (el.btnDrawRoad) el.btnDrawRoad.classList.toggle('active', active);
    if (el.btnDrawText) el.btnDrawText.textContent = active ? '⏹ Завершить черчение' : 'Начертить улицу на плане';
    if (el.btnDrawIcon) el.btnDrawIcon.textContent = active ? '✕' : '✏️';
    if (el.svgCanvas) el.svgCanvas.classList.toggle('drawing-mode', active);

    if (el.drawRoadHint) {
      if (active) {
        el.drawRoadHint.innerHTML = '<b>Режим черчения:</b> Кликните 1-ю точку входа на границе, затем 2-ю точку выхода.';
        el.drawRoadHint.style.borderColor = 'var(--success)';
        el.drawRoadHint.style.color = 'var(--text-primary)';
      } else {
        el.drawRoadHint.innerHTML = 'Кликните <b>«Начертить улицу»</b>, затем укажите начальную и конечную точку на 2D CAD чертеже.';
        el.drawRoadHint.style.borderColor = 'var(--accent-border)';
        el.drawRoadHint.style.color = 'var(--text-secondary)';
      }
    }
  }

  // Clear Custom Roads
  if (el.btnClearRoads) {
    el.btnClearRoads.addEventListener('click', () => {
      state.custom_roads = [];
      updateCustomRoadsUI();
      if (state.road_preset === 'custom') {
        state.road_preset = 'none';
        el.presetBtns.forEach(b => b.classList.toggle('active', b.dataset.preset === 'none'));
        if (el.valPresetBadge) el.valPresetBadge.textContent = 'Без дорог';
      }
      apiPreviewSite(true);
    });
  }

  function updateCustomRoadsUI() {
    if (el.valCustomCount) el.valCustomCount.textContent = `${state.custom_roads.length} улиц`;

    if (el.customRoadsList) {
      if (state.custom_roads.length === 0) {
        el.customRoadsList.innerHTML = '';
        return;
      }
      let html = '';
      state.custom_roads.forEach((r, idx) => {
        const lenM = Math.round(calcRoadLength(r.points));
        html += `
          <div class="custom-road-item" data-road-idx="${idx}">
            <div class="custom-road-left">
              <span class="custom-road-name">${r.name || `Улица ${idx + 1}`}</span>
              <span class="custom-road-meta">${r.width} м • ${lenM} м</span>
            </div>
            <button class="custom-road-del" data-road-del-idx="${idx}" title="Удалить улицу">×</button>
          </div>
        `;
      });
      el.customRoadsList.innerHTML = html;

      // Delete buttons
      el.customRoadsList.querySelectorAll('[data-road-del-idx]').forEach(b => {
        b.addEventListener('click', e => {
          e.stopPropagation();
          const dIdx = parseInt(b.dataset.roadDelIdx, 10);
          state.custom_roads.splice(dIdx, 1);
          updateCustomRoadsUI();
          apiPreviewSite(true);
        });
      });
    }
  }

  function calcRoadLength(pts) {
    if (!pts || pts.length < 2) return 0;
    const dx = pts[1][0] - pts[0][0];
    const dy = pts[1][1] - pts[0][1];
    return Math.sqrt(dx * dx + dy * dy);
  }

  // --- RENDER CUSTOM ROAD HANDLES (DRAGGABLE ENDPOINTS & MIDPOINTS) ---
  function renderCustomRoadHandles() {
    if (!el.svgRoadHandlesLayer) return;
    if (state.uds_mode !== 'free_draw' || state.custom_roads.length === 0) {
      el.svgRoadHandlesLayer.innerHTML = '';
      return;
    }

    const helpers = getCoordHelpers();
    let markup = '';

    state.custom_roads.forEach((road, rIdx) => {
      const p1 = road.points[0];
      const p2 = road.points[1];
      const s1 = helpers.siteToSvg(p1[0], p1[1]);
      const s2 = helpers.siteToSvg(p2[0], p2[1]);
      const sMid = [(s1[0] + s2[0]) / 2, (s1[1] + s2[1]) / 2];

      markup += `
        <!-- Road ${rIdx + 1} Handles -->
        <circle class="road-handle" data-road-idx="${rIdx}" data-handle="pt1" cx="${s1[0]}" cy="${s1[1]}" r="7" fill="#38bdf8" stroke="#ffffff" stroke-width="2" />
        <circle class="road-handle" data-road-idx="${rIdx}" data-handle="pt2" cx="${s2[0]}" cy="${s2[1]}" r="7" fill="#38bdf8" stroke="#ffffff" stroke-width="2" />
        <rect class="road-handle-mid" data-road-idx="${rIdx}" data-handle="mid" x="${sMid[0] - 6}" y="${sMid[1] - 6}" width="12" height="12" rx="2" fill="#f59e0b" stroke="#ffffff" stroke-width="2" />
      `;
    });

    el.svgRoadHandlesLayer.innerHTML = markup;
    bindHandleDragEvents();
  }

  function bindHandleDragEvents() {
    if (!el.svgRoadHandlesLayer) return;
    const handles = el.svgRoadHandlesLayer.querySelectorAll('.road-handle, .road-handle-mid');
    handles.forEach(h => {
      h.addEventListener('mousedown', e => {
        e.stopPropagation();
        const rIdx = parseInt(h.dataset.roadIdx, 10);
        const handleType = h.dataset.handle;
        state.activeHandleDrag = {
          roadIdx: rIdx,
          handleType: handleType,
          initialMouseX: e.clientX,
          initialMouseY: e.clientY
        };
      });
    });
  }

  // --- CANVAS CLICK & MOUSEMOVE HANDLERS (DRAWING & DRAGGING) ---
  el.svgCanvas.addEventListener('click', e => {
    // 1. Add Entry Point on Boundary Mode
    if (state.isAddingEntryPoint) {
      if (!state.currentData || !state.currentData.boundary_coords || state.currentData.boundary_coords.length < 3) {
        showToast('Сначала загрузите или выберите участок', 'warning');
        return;
      }

      const rect = el.svgCanvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      const svgX = (mouseX - panZoom.tx) / panZoom.scale;
      const svgY = (mouseY - panZoom.ty) / panZoom.scale;

      const helpers = getCoordHelpers();
      const [siteX, siteY] = helpers.svgToSite(svgX, svgY);
      const boundaryCoords = state.currentData.boundary_coords;
      const proj = projectPointToBoundary(siteX, siteY, boundaryCoords);

      const newIdx = state.entry_points.length + 1;
      state.entry_points.push({
        id: 'ep_' + Date.now() + '_' + Math.random().toString(36).substr(2, 4),
        name: `Въезд ${newIdx}`,
        x: round2(proj[0]),
        y: round2(proj[1]),
        category: state.road_category || 'district',
        width: state.road_width || 15.0,
        setback: state.road_setback || 4.0
      });

      updateEntryPointsUI();
      renderEntryPointsOnSvg();
      rebuildRoadsFromEntryPoints();

      if (state.entry_points.length >= 4) {
        toggleAddEntryPointMode(false);
      }
      return;
    }

    // 2. Free Draw Road Mode
    if (!state.isDrawingRoad) return;

    const rect = el.svgCanvas.getBoundingClientRect();
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;

    const svgX = (mouseX - panZoom.tx) / panZoom.scale;
    const svgY = (mouseY - panZoom.ty) / panZoom.scale;

    const helpers = getCoordHelpers();
    const [siteX, siteY] = helpers.svgToSite(svgX, svgY);

    if (!state.drawingRoadStart) {
      // Point 1
      state.drawingRoadStart = { siteX, siteY, svgX, svgY };
      if (el.svgRoadDrawingLayer) {
        el.svgRoadDrawingLayer.innerHTML = `
          <circle cx="${svgX}" cy="${svgY}" r="6" fill="#34d399" stroke="#ffffff" stroke-width="2" />
        `;
      }
      if (el.drawRoadHint) {
        el.drawRoadHint.innerHTML = '<b>Точка 1 задана!</b> Теперь кликните 2-ю точку для завершения коридора улицы.';
      }
    } else {
      // Point 2 -> Create Road
      const p1 = [state.drawingRoadStart.siteX, state.drawingRoadStart.siteY];
      const p2 = [siteX, siteY];

      const newRoad = {
        name: `Улица ${state.custom_roads.length + 1}`,
        category: state.road_category,
        width: state.road_width,
        setback: state.road_setback,
        points: [p1, p2]
      };

      state.custom_roads.push(newRoad);
      state.road_preset = 'custom';
      el.presetBtns.forEach(b => b.classList.toggle('active', b.dataset.preset === 'custom'));
      if (el.valPresetBadge) el.valPresetBadge.textContent = 'На чертеже';

      state.drawingRoadStart = null;
      if (el.svgRoadDrawingLayer) el.svgRoadDrawingLayer.innerHTML = '';

      updateCustomRoadsUI();
      toggleDrawingMode(false);
      apiPreviewSite(true);
    }
  });

  el.svgCanvas.addEventListener('mousemove', e => {
    // 1. Drawing rubberband line
    if (state.isDrawingRoad && state.drawingRoadStart) {
      const rect = el.svgCanvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      const curSvgX = (mouseX - panZoom.tx) / panZoom.scale;
      const curSvgY = (mouseY - panZoom.ty) / panZoom.scale;

      const p1 = state.drawingRoadStart;
      if (el.svgRoadDrawingLayer) {
        el.svgRoadDrawingLayer.innerHTML = `
          <line x1="${p1.svgX}" y1="${p1.svgY}" x2="${curSvgX}" y2="${curSvgY}" stroke="#34d399" stroke-width="3" stroke-dasharray="6,4" />
          <circle cx="${p1.svgX}" cy="${p1.svgY}" r="6" fill="#34d399" stroke="#ffffff" stroke-width="2" />
          <circle cx="${curSvgX}" cy="${curSvgY}" r="5" fill="#38bdf8" stroke="#ffffff" stroke-width="1.5" />
        `;
      }
    }

    // 0. Dragging entry marker along boundary
    if (state.activeEntryDrag) {
      const drag = state.activeEntryDrag;
      const ep = state.entry_points[drag.idx];
      if (!ep) return;

      const rect = el.svgCanvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;
      const svgX = (mouseX - panZoom.tx) / panZoom.scale;
      const svgY = (mouseY - panZoom.ty) / panZoom.scale;

      const helpers = getCoordHelpers();
      const [siteX, siteY] = helpers.svgToSite(svgX, svgY);
      const boundaryCoords = (state.currentData && state.currentData.boundary_coords) || [];
      const proj = projectPointToBoundary(siteX, siteY, boundaryCoords);

      ep.x = round2(proj[0]);
      ep.y = round2(proj[1]);
      renderEntryPointsOnSvg();
      return;
    }

    // 2. Dragging road handle
    if (state.activeHandleDrag) {
      const drag = state.activeHandleDrag;
      const road = state.custom_roads[drag.roadIdx];
      if (!road) return;

      const rect = el.svgCanvas.getBoundingClientRect();
      const mouseX = e.clientX - rect.left;
      const mouseY = e.clientY - rect.top;

      const svgX = (mouseX - panZoom.tx) / panZoom.scale;
      const svgY = (mouseY - panZoom.ty) / panZoom.scale;

      const helpers = getCoordHelpers();
      const [siteX, siteY] = helpers.svgToSite(svgX, svgY);

      if (drag.handleType === 'pt1') {
        road.points[0] = [siteX, siteY];
      } else if (drag.handleType === 'pt2') {
        road.points[1] = [siteX, siteY];
      } else if (drag.handleType === 'mid') {
        const midSite = [
          (road.points[0][0] + road.points[1][0]) / 2,
          (road.points[0][1] + road.points[1][1]) / 2
        ];
        const dX = siteX - midSite[0];
        const dY = siteY - midSite[1];
        road.points[0] = [round2(road.points[0][0] + dX), round2(road.points[0][1] + dY)];
        road.points[1] = [round2(road.points[1][0] + dX), round2(road.points[1][1] + dY)];
      }

      renderCustomRoadHandles();
    }
  });

  window.addEventListener('mouseup', () => {
    if (state.activeEntryDrag) {
      state.activeEntryDrag = null;
      state.activePresetTemplate = null; // User fine-tuned positions manually on canvas -> custom
      updateEntryPointsUI();
      rebuildRoadsFromEntryPoints();
    }
    if (state.activeHandleDrag) {
      state.activeHandleDrag = null;
      updateCustomRoadsUI();
      apiPreviewSite(true);
    }
  });

  // Cancel drawing on Escape
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape') {
      if (state.isDrawingRoad) toggleDrawingMode(false);
      if (state.isAddingEntryPoint) toggleAddEntryPointMode(false);
    }
  });

  // --- STEP 1 & 2 PIPELINE TRANSITION BUTTONS ---
  // Step 1: Proceed to Step 2
  if (el.btnLockSite) {
    el.btnLockSite.addEventListener('click', () => {
      if (!state.currentData) {
        alert('Пожалуйста, сначала посадите участок (введите кадастровый номер или загрузите DXF).');
        return;
      }
      state.isLocked = true;
      setStep(2);
    });
  }

  // Step 2: Back to Step 1
  if (el.btnStep2Back) {
    el.btnStep2Back.addEventListener('click', () => {
      setStep(1);
    });
  }

  // Step 2: Proceed to Step 3 -> Opens Regulations Popup Modal
  if (el.btnStep2Proceed) {
    el.btnStep2Proceed.addEventListener('click', () => {
      openStep3RegulationsModal();
    });
  }

  // Stepper Header click navigation
  if (el.stepperStep1) {
    el.stepperStep1.addEventListener('click', () => setStep(1));
  }
  if (el.stepperStep2) {
    el.stepperStep2.addEventListener('click', () => {
      if (state.currentData) setStep(2);
    });
  }
  if (el.stepperStep3) {
    el.stepperStep3.addEventListener('click', () => {
      if (state.currentData) {
        if (state.currentStep < 3) {
          openStep3RegulationsModal();
        } else {
          setStep(3);
        }
      }
    });
  }

  // --- BI-DIRECTIONAL POSTMESSAGE LISTENER (LEAFLET IFRAME <-> STUDIO) ---
  window.addEventListener('message', function (e) {
    if (!e.data) return;

    // 1. Transform on map (drag or rotation)
    if (e.data.isMapTransform) {
      const t = e.data.transform;
      if (!t) return;

      if (t.map_rot !== undefined && !isNaN(t.map_rot)) {
        state.site_rotation = t.map_rot;
        if (el.sliderRotation) el.sliderRotation.value = t.map_rot;
        if (el.valRotation) el.valRotation.textContent = `${t.map_rot > 0 ? '+' : ''}${t.map_rot.toFixed(1)}°`;
        if (el.compassSvg) el.compassSvg.style.transform = `rotate(${-t.map_rot}deg)`;
      }

      if (t.map_lat && t.map_lon && t.dist_m > 0.1) {
        state.userHasMovedSite = true;
        state.override_lat = t.map_lat;
        state.override_lon = t.map_lon;
        if (el.inputManualLat) el.inputManualLat.value = t.map_lat.toFixed(5);
        if (el.inputManualLon) el.inputManualLon.value = t.map_lon.toFixed(5);
        if (el.labelCoords) el.labelCoords.textContent = `WGS-84: [${t.map_lat.toFixed(5)}, ${t.map_lon.toFixed(5)}]`;
      }

      if (t.lock) {
        state.isLocked = true;
        setStep(2);
      }
      return;
    }

    // 2. Digitize contour clicks (Mode 3: Points)
    if (e.data.type === 'contourDigitized' && e.data.points && e.data.points.length >= 3) {
      const pts = e.data.points;
      const txt = pts.map((p, idx) => `${idx + 1}\t${p[0].toFixed(6)}\t${p[1].toFixed(6)}`).join('\n');
      state.gpzu_coordinates = txt;
      if (el.textareaCoords) el.textareaCoords.value = txt;
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

    // 3. Pick point on map
    if (e.data.type === 'mapPointPicked') {
      const pLat = Number(e.data.lat);
      const pLon = Number(e.data.lon);
      state.userHasMovedSite = true;
      state.userHasEnteredManualCoords = true;
      state.override_lat = pLat;
      state.override_lon = pLon;
      if (el.inputManualLat) el.inputManualLat.value = pLat.toFixed(5);
      if (el.inputManualLon) el.inputManualLon.value = pLon.toFixed(5);
      if (el.labelCoords) el.labelCoords.textContent = `WGS-84: [${pLat.toFixed(5)}, ${pLon.toFixed(5)}]`;
      apiPreviewSite(true);
      return;
    }
  });

  // --- STEP 1: CADASTRE & DXF HANDLERS ---
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

  if (el.btnLoadCadastre) el.btnLoadCadastre.addEventListener('click', loadCadastreSite);
  if (el.inputCadNum) {
    el.inputCadNum.addEventListener('keydown', e => {
      if (e.key === 'Enter') {
        e.preventDefault();
        loadCadastreSite();
      }
    });
  }

  // --- UNIFIED GPZU UPLOAD & PROCESSING ---
  async function handleGpzuUpload(file, isCadTab = true) {
    if (!file) return;
    const dropzoneText = isCadTab ? el.cadGpzuDropzoneText : el.gpzuDropzoneText;
    const statusBadge = isCadTab ? el.cadGpzuStatusBadge : el.digitizeStatusBadge;
    const defaultText = isCadTab
      ? 'Загрузить выписку ГПЗУ (.PDF / .XLSX / .TXT)'
      : 'Перетащите PDF, Excel или текст ГПЗУ';

    const isPdf = file.name.toLowerCase().endsWith('.pdf');
    if (dropzoneText) dropzoneText.textContent = isPdf ? '⏳ Анализ ГПЗУ (для сканов выполняется OCR)...' : '⏳ Чтение выписки ГПЗУ...';

    const reader = new FileReader();
    reader.onload = async () => {
      const b64 = reader.result.split(',')[1];
      try {
        // Send msk_zone: null to allow auto-detection from document text & cad number!
        const res = await fetch('/api/upload-gpzu', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_base64: b64, filename: file.name, msk_zone: null })
        });
        const d = await res.json();
        if (d.success && (d.coordinates_text || (d.coordinates && d.coordinates.length))) {
          state.currentGpzuParsedData = d;
          const coordsTxt = d.coordinates_text || d.coordinates.map((p, idx) => `${idx + 1}\t${p.x || p[0]}\t${p.y || p[1]}`).join('\n');
          state.gpzu_coordinates = coordsTxt;
          if (el.textareaCoords) el.textareaCoords.value = coordsTxt;

          if (d.cadastral_number) {
            state.cad_query = d.cadastral_number;
            if (el.inputCadNum) el.inputCadNum.value = d.cadastral_number;
          }
          if (d.coordinate_system) {
            ensureMskOption(d.coordinate_system);
            state.msk_zone = d.coordinate_system;
          }

          // Reset manual shifts so site lands accurately at document coordinates
          state.userHasMovedSite = false;
          state.override_lat = 0.0;
          state.override_lon = 0.0;

          const isOcr = d.source === 'ocr_scanned_pdf';
          if (dropzoneText) dropzoneText.textContent = `✓ Загружен: ${file.name}${isOcr ? ' (распознан скан)' : ''}`;
          if (statusBadge) {
            statusBadge.style.display = 'block';
            statusBadge.textContent = `✓ Извлечено ${d.points_count || 'контур'} точек${d.cadastral_number ? ' • КН ' + d.cadastral_number : ''}${isOcr ? ' [OCR]' : ''}`;
          }

          if (el.btnOpenGpzuModalCad) el.btnOpenGpzuModalCad.style.display = 'flex';
          if (el.btnOpenGpzuModalPoints) el.btnOpenGpzuModalPoints.style.display = 'flex';

          openGpzuModalWithData(d);
        } else {
          if (dropzoneText) dropzoneText.textContent = defaultText;
          alert(d.error || 'Не удалось извлечь поворотные точки из файла ГПЗУ');
        }
      } catch (err) {
        console.error('Upload GPZU error:', err);
        if (dropzoneText) dropzoneText.textContent = defaultText;
        alert('Ошибка загрузки файла ГПЗУ');
      }
    };
    reader.readAsDataURL(file);
  }

  // GPZU Upload on Step 1 Cadastre Tab
  if (el.cadGpzuDropzone && el.cadGpzuFileInput) {
    el.cadGpzuDropzone.addEventListener('click', () => el.cadGpzuFileInput.click());
    el.cadGpzuDropzone.addEventListener('dragover', e => {
      e.preventDefault();
      el.cadGpzuDropzone.style.borderColor = 'var(--accent)';
    });
    el.cadGpzuDropzone.addEventListener('dragleave', () => {
      el.cadGpzuDropzone.style.borderColor = '';
    });
    el.cadGpzuDropzone.addEventListener('drop', e => {
      e.preventDefault();
      el.cadGpzuDropzone.style.borderColor = '';
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleGpzuUpload(e.dataTransfer.files[0], true);
      }
    });
    el.cadGpzuFileInput.addEventListener('change', e => {
      if (e.target.files && e.target.files[0]) {
        handleGpzuUpload(e.target.files[0], true);
      }
    });
  }

  // Mode Switcher (1. Кадастр | 2. CAD | 3. Точки)
  el.modeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.mode;
      state.mode = mode;

      el.modeBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      Object.keys(el.panes).forEach(paneKey => {
        if (el.panes[paneKey]) el.panes[paneKey].classList.toggle('active', paneKey === mode);
      });

      apiPreviewSite();
    });
  });

  // Custom Area
  if (el.inputCustomArea) {
    el.inputCustomArea.addEventListener('change', () => {
      state.custom_area = parseFloat(el.inputCustomArea.value) || 42500;
      if (state.currentData) apiPreviewSite();
    });
  }

  // Fetch PKK
  if (el.btnFetchPkk) {
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
          if (el.pkkBadge) {
            el.pkkBadge.style.display = 'block';
            el.pkkBadge.textContent = '✓ Границы подтверждены ПКК Росреестра';
          }
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
  }

  // Manual Coordinates
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

  // Pick Point on Map
  if (el.btnPickPointCadastre) {
    el.btnPickPointCadastre.addEventListener('click', () => {
      setCanvasView('osm');
      if (el.iframeOsm && el.iframeOsm.contentWindow) {
        el.iframeOsm.contentWindow.postMessage({ type: 'startPickPoint' }, '*');
      }
    });
  }

  // Mode 2: DXF Upload
  if (el.dxfDropzone && el.dxfFileInput) {
    el.dxfDropzone.addEventListener('click', () => el.dxfFileInput.click());
    el.dxfFileInput.addEventListener('change', e => {
      const file = e.target.files[0];
      if (!file) return;
      const reader = new FileReader();
      reader.onload = async () => {
        const b64 = reader.result.split(',')[1];
        state.mode = 'cad';
        state.userHasMovedSite = false;
        state.override_lat = 0.0;
        state.override_lon = 0.0;
        state.msk_zone = '';
        if (el.selectMskZone) el.selectMskZone.value = '';
        if (el.mskDetectedBadge) el.mskDetectedBadge.style.display = 'none';
        state.cad_file_base64 = b64;
        state.cad_filename = file.name;
        if (el.dxfDropzoneText) el.dxfDropzoneText.textContent = `✓ Загружен: ${file.name}`;

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
  }

  if (el.selectCadLayer) {
    el.selectCadLayer.addEventListener('change', () => {
      state.boundary_layer = el.selectCadLayer.value || null;
      apiPreviewSite(true);
    });
  }

  if (el.selectCadRedline) {
    el.selectCadRedline.addEventListener('change', () => {
      state.red_lines_layer = el.selectCadRedline.value || null;
      apiPreviewSite(true);
    });
  }

  if (el.selectMskZone) {
    el.selectMskZone.addEventListener('change', () => {
      state.msk_zone = el.selectMskZone.value;
      state.userHasMovedSite = false;
      state.override_lat = 0.0;
      state.override_lon = 0.0;
      if (state.currentData || state.cad_file_base64) apiPreviewSite(true);
    });
  }

  if (el.inputCadAssigned) {
    el.inputCadAssigned.addEventListener('change', () => {
      state.assigned_cad_query = el.inputCadAssigned.value.trim();
      state.userHasMovedSite = false;
      state.override_lat = 0.0;
      state.override_lon = 0.0;
      if (state.currentData || state.cad_file_base64) apiPreviewSite(true);
    });
  }

  if (el.chkCadSwapXy) {
    el.chkCadSwapXy.addEventListener('change', () => {
      state.userHasMovedSite = false;
      if (state.currentData || state.dxf_filename) apiPreviewSite(true);
    });
  }

  // Mode 3: Digitize on Satellite Map
  if (el.btnDigitizeMap) {
    el.btnDigitizeMap.addEventListener('click', () => {
      setCanvasView('osm');
      if (!state.currentData) {
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
  }

  // Mode 3: Apply Coordinates from textarea
  if (el.btnApplyCoords) {
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
  }

  // Mode 3: GPZU upload (.pdf / .xlsx / .txt)
  if (el.gpzuDropzone && el.gpzuFileInput) {
    el.gpzuDropzone.addEventListener('click', () => el.gpzuFileInput.click());
    el.gpzuDropzone.addEventListener('dragover', e => {
      e.preventDefault();
      el.gpzuDropzone.style.borderColor = 'var(--accent)';
    });
    el.gpzuDropzone.addEventListener('dragleave', () => {
      el.gpzuDropzone.style.borderColor = '';
    });
    el.gpzuDropzone.addEventListener('drop', e => {
      e.preventDefault();
      el.gpzuDropzone.style.borderColor = '';
      if (e.dataTransfer.files && e.dataTransfer.files[0]) {
        handleGpzuUpload(e.dataTransfer.files[0], false);
      }
    });
    el.gpzuFileInput.addEventListener('change', e => {
      if (e.target.files && e.target.files[0]) {
        handleGpzuUpload(e.target.files[0], false);
      }
    });
  }

  // =========================================================================
  // GPZU MODAL INSPECTOR & RESTRICTIONS ENGINE
  // =========================================================================

  function closeGpzuModal() {
    if (el.gpzuModal) el.gpzuModal.style.display = 'none';
  }

  function flushGpzuModalTextareas() {
    if (!el.modalGpzuZonesList || !state.currentGpzuParsedData || !state.currentGpzuParsedData.zones) return;
    el.modalGpzuZonesList.querySelectorAll('.gpzu-zone-card').forEach((card, cIdx) => {
      const ta = card.querySelector('.zone-coords-textarea');
      if (ta && state.currentGpzuParsedData.zones[cIdx]) {
        const val = ta.value.trim();
        if (val) {
          state.currentGpzuParsedData.zones[cIdx].coordinates_text = val;
          const pts = parseCoordinateTextClient(val);
          state.currentGpzuParsedData.zones[cIdx].coordinates = pts;
          state.currentGpzuParsedData.zones[cIdx].points_count = pts.length;
          state.currentGpzuParsedData.zones[cIdx].area_sqm = calculatePolygonAreaClient(pts);
          state.currentGpzuParsedData.zones[cIdx].area_ha = state.currentGpzuParsedData.zones[cIdx].area_sqm / 10000;
        }
      }
    });
  }

  function renderGpzuZonesModalList(zones) {
    if (!el.modalGpzuZonesList) return;
    el.modalGpzuZonesList.innerHTML = '';
    if (el.modalGpzuZonesCount) el.modalGpzuZonesCount.textContent = zones ? zones.length : 0;

    if (!zones || zones.length === 0) {
      el.modalGpzuZonesList.innerHTML = `
        <div style="font-size:11.5px; color:var(--text-secondary); padding:8px; text-align:center;">
          Каталоги координат в документе не обнаружены.
        </div>`;
      return;
    }

    zones.forEach((z, idx) => {
      const isBoundary = (z.role === 'boundary');
      const card = document.createElement('div');
      card.className = 'gpzu-zone-card';
      card.style.cssText = isBoundary
        ? 'background:rgba(56, 189, 248, 0.05); border:1.5px solid var(--accent); border-radius:var(--radius-sm); padding:12px; display:flex; flex-direction:column; gap:8px;'
        : 'background:var(--bg-panel); border:1px solid var(--border-subtle); border-radius:var(--radius-sm); padding:10px 12px; display:flex; flex-direction:column; gap:6px;';

      let typeBadge = 'badge-neutral';
      if (z.role === 'boundary') typeBadge = 'badge-ok';
      else if (z.role === 'buildable_envelope') typeBadge = 'badge-accent';
      else if (z.role === 'zouit_exclusion') typeBadge = 'badge-warn';

      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap;">
          <div style="display:flex; align-items:center; gap:8px; flex:1; min-width:240px;">
            <input type="checkbox" class="gpzu-zone-chk-apply" data-index="${idx}" ${z.default_apply !== false ? 'checked' : ''} />
            <span style="font-weight:600; font-size:12.5px; color:var(--text-primary);">${escapeHtml(z.name || `Зона ${idx+1}`)}</span>
            <span class="badge-status ${typeBadge} zone-badge-pts-${idx}" style="font-size:10.5px;">${z.points_count || 0} точек</span>
            <span class="badge-status badge-neutral zone-badge-area-${idx}" style="font-size:10.5px;">${Math.round(z.area_sqm || 0).toLocaleString('ru-RU')} м²</span>
          </div>
          <div style="display:flex; align-items:center; gap:6px;">
            <label style="font-size:11px; color:var(--text-secondary);">Роль:</label>
            <select class="input-text gpzu-zone-role-select" data-index="${idx}" style="font-size:11px; padding:3px 6px;">
              <option value="boundary" ${z.role === 'boundary' ? 'selected' : ''}>📐 Основной контур ЗУ</option>
              <option value="buildable_envelope" ${z.role === 'buildable_envelope' ? 'selected' : ''}>🏗️ Пятно застройки</option>
              <option value="zouit_exclusion" ${z.role === 'zouit_exclusion' ? 'selected' : ''}>🛡️ ЗОУИТ (Вычесть)</option>
              <option value="easement" ${z.role === 'easement' ? 'selected' : ''}>🚶 Сервитут</option>
              <option value="ignore" ${z.role === 'ignore' ? 'selected' : ''}>❌ Игнорировать</option>
            </select>
          </div>
        </div>

        <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; color:var(--text-secondary); flex-wrap:wrap; gap:6px;">
          <span>${escapeHtml(z.description || '')}</span>
          <div style="display:flex; gap:6px;">
            <button type="button" class="btn-secondary btn-set-boundary" data-index="${idx}" style="font-size:10.5px; padding:3px 8px; ${isBoundary ? 'font-weight:600; color:var(--accent);' : ''}" title="Сделать этот контур границей участка">
              📐 ${isBoundary ? '✓ Контур ЗУ' : 'Сделать контуром ЗУ'}
            </button>
            <button type="button" class="btn-secondary btn-toggle-zone-coords" data-index="${idx}" style="font-size:10.5px; padding:3px 8px;">
              ✏️ Точки границ (<span class="btn-pts-lbl-${idx}">${z.points_count || 0}</span>)
            </button>
          </div>
        </div>

        <div class="zone-coords-editor-box" id="zone-coords-box-${idx}" style="display:none; margin-top:6px; background:var(--bg-card); border:1px solid var(--border-subtle); border-radius:var(--radius-sm); padding:8px 10px;">
          <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px; flex-wrap:wrap; gap:6px;">
            <span style="font-size:11px; font-weight:600; color:var(--text-primary); display:flex; align-items:center; gap:4px;">
              <span>📋</span> Координаты поворотных точек (формат: № X Y или X Y):
            </span>
            <div style="display:flex; gap:4px;">
              <button type="button" class="btn-secondary btn-swap-xy" data-index="${idx}" style="font-size:10px; padding:2px 6px;" title="Поменять X и Y местами">↕ X ↔ Y</button>
              <button type="button" class="btn-secondary btn-add-pt" data-index="${idx}" style="font-size:10px; padding:2px 6px;" title="Добавить строку для новой точки">+ Добавить точку</button>
              <button type="button" class="btn-secondary btn-recalc-pts" data-index="${idx}" style="font-size:10px; padding:2px 6px;" title="Пересчитать площадь">🔄 Пересчитать</button>
            </div>
          </div>
          <textarea class="zone-coords-textarea" id="zone-coords-ta-${idx}" rows="6" style="font-family:var(--font-mono); font-size:11px; width:100%; resize:vertical; background:var(--bg-panel); border:1px solid var(--border-subtle); color:var(--text-primary); padding:6px 8px; line-height:1.45;" placeholder="1  386213.46  2226426.33&#10;2  386253.41  2226490.62...">${escapeHtml(z.coordinates_text || '')}</textarea>
          <div style="display:flex; justify-content:space-between; align-items:center; margin-top:4px; font-size:10.5px; color:var(--text-secondary);">
            <span id="zone-live-stat-${idx}">✅ Точек: <b>${z.points_count || 0}</b> | Площадь: <b>${Math.round(z.area_sqm || 0).toLocaleString('ru-RU')} м²</b> (${((z.area_sqm || 0) / 10000).toFixed(2)} га)</span>
            <span style="color:var(--text-muted);">Формат: № [таб/пробел] X [таб/пробел] Y</span>
          </div>
        </div>
      `;

      const ta = card.querySelector(`#zone-coords-ta-${idx}`);
      const boxCoords = card.querySelector(`#zone-coords-box-${idx}`);
      const btnCoords = card.querySelector('.btn-toggle-zone-coords');

      if (btnCoords && boxCoords) {
        btnCoords.addEventListener('click', () => {
          boxCoords.style.display = boxCoords.style.display === 'none' ? 'block' : 'none';
        });
      }

      const updateZoneFromTextarea = () => {
        if (!ta) return;
        const text = ta.value;
        const pts = parseCoordinateTextClient(text);
        const area = calculatePolygonAreaClient(pts);
        z.coordinates_text = text;
        z.coordinates = pts;
        z.points_count = pts.length;
        z.area_sqm = Math.round(area * 10) / 10;
        z.area_ha = Math.round(area / 1000) / 10;

        const badgePts = card.querySelector(`.zone-badge-pts-${idx}`);
        if (badgePts) badgePts.textContent = `${pts.length} точек`;
        const badgeArea = card.querySelector(`.zone-badge-area-${idx}`);
        if (badgeArea) badgeArea.textContent = `${Math.round(area).toLocaleString('ru-RU')} м²`;
        const btnPtsLbl = card.querySelector(`.btn-pts-lbl-${idx}`);
        if (btnPtsLbl) btnPtsLbl.textContent = pts.length;

        const statSpan = card.querySelector(`#zone-live-stat-${idx}`);
        if (statSpan) {
          if (pts.length >= 3) {
            statSpan.innerHTML = `✅ Точек: <b>${pts.length}</b> | Площадь: <b>${Math.round(area).toLocaleString('ru-RU')} м²</b> (${(area / 10000).toFixed(2)} га)`;
          } else {
            statSpan.innerHTML = `⚠️ <span style="color:var(--danger);">Точек: <b>${pts.length}</b> (нужно минимум 3 для контура)</span>`;
          }
        }

        if (z.role === 'boundary') {
          if (el.modalGpzuPointsBadge) {
            el.modalGpzuPointsBadge.textContent = `${pts.length} точек границы (${state.currentGpzuParsedData.coordinate_system || 'МСК'})`;
          }
          if (el.modalGpzuAreaBadge) {
            el.modalGpzuAreaBadge.textContent = `${Math.round(area).toLocaleString('ru-RU')} м² (${(area / 10000).toFixed(2)} га)`;
          }
          state.currentGpzuParsedData.points_count = pts.length;
          state.currentGpzuParsedData.area_sqm = area;
          state.currentGpzuParsedData.area_ha = area / 10000;
          state.currentGpzuParsedData.coordinates_text = text;
        }
      };

      if (ta) {
        ta.addEventListener('input', updateZoneFromTextarea);
        ta.addEventListener('change', updateZoneFromTextarea);
      }

      const btnRecalc = card.querySelector('.btn-recalc-pts');
      if (btnRecalc) {
        btnRecalc.addEventListener('click', updateZoneFromTextarea);
      }

      const btnSwap = card.querySelector('.btn-swap-xy');
      if (btnSwap && ta) {
        btnSwap.addEventListener('click', () => {
          const text = ta.value;
          const lines = text.trim().split(/[\r\n]+/);
          const swapped = lines.map(l => {
            const clean = l.trim();
            if (!clean) return l;
            const parts = clean.split(/[\s	;]+/);
            if (parts.length >= 3) {
              return `${parts[0]}	${parts[2]}	${parts[1]}`;
            } else if (parts.length === 2) {
              return `${parts[1]}	${parts[0]}`;
            }
            return l;
          }).join('\n');
          ta.value = swapped;
          updateZoneFromTextarea();
        });
      }

      const btnAddPt = card.querySelector('.btn-add-pt');
      if (btnAddPt && ta) {
        btnAddPt.addEventListener('click', () => {
          const text = ta.value.trim();
          const pts = parseCoordinateTextClient(text);
          const nextIdx = pts.length + 1;
          let nextX = 0, nextY = 0;
          if (pts.length > 0) {
            nextX = (pts[pts.length - 1][0] + 10).toFixed(2);
            nextY = (pts[pts.length - 1][1] + 10).toFixed(2);
          }
          ta.value = text + (text ? '\n' : '') + `${nextIdx}	${nextX}	${nextY}`;
          updateZoneFromTextarea();
          ta.scrollTop = ta.scrollHeight;
        });
      }

      const btnSetB = card.querySelector('.btn-set-boundary');
      if (btnSetB) {
        btnSetB.addEventListener('click', () => {
          if (!state.currentGpzuParsedData || !state.currentGpzuParsedData.zones) return;
          state.currentGpzuParsedData.zones.forEach((zoneItem, sIdx) => {
            zoneItem.role = (sIdx === idx) ? 'boundary' : 'other';
          });
          renderGpzuZonesModalList(state.currentGpzuParsedData.zones);
        });
      }

      const roleSel = card.querySelector('.gpzu-zone-role-select');
      if (roleSel) {
        roleSel.addEventListener('change', () => {
          if (state.currentGpzuParsedData.zones && state.currentGpzuParsedData.zones[idx]) {
            state.currentGpzuParsedData.zones[idx].role = roleSel.value;
            if (roleSel.value === 'boundary') {
              state.currentGpzuParsedData.zones.forEach((oZ, oIdx) => {
                if (oIdx !== idx && oZ.role === 'boundary') oZ.role = 'other';
              });
              renderGpzuZonesModalList(state.currentGpzuParsedData.zones);
            }
          }
        });
      }

      const chkApply = card.querySelector('.gpzu-zone-chk-apply');
      if (chkApply) {
        chkApply.addEventListener('change', () => {
          if (state.currentGpzuParsedData.zones && state.currentGpzuParsedData.zones[idx]) {
            state.currentGpzuParsedData.zones[idx].enabled = chkApply.checked;
          }
        });
      }

      el.modalGpzuZonesList.appendChild(card);
    });
  }

  function renderZouitModalList(zouitList) {
    if (!el.modalGpzuZouitList) return;
    el.modalGpzuZouitList.innerHTML = '';

    if (!zouitList || zouitList.length === 0) {
      el.modalGpzuZouitList.innerHTML = `
        <div style="font-size:12px; color:var(--text-secondary); background:var(--bg-card); padding:14px; border-radius:var(--radius-sm); text-align:center;">
          🛡️ В документе не обнаружено записей об охранных зонах и ЗОУИТ.<br>Вы можете добавить зону вручную с помощью кнопки «➕ Добавить ЗОУИТ вручную».
        </div>`;
      return;
    }

    zouitList.forEach((z, idx) => {
      const card = document.createElement('div');
      card.className = 'zouit-item-card';
      card.style.cssText = 'background:var(--bg-panel); border:1px solid var(--border-subtle); border-radius:var(--radius); padding:12px; display:flex; flex-direction:column; gap:8px;';

      const hasCoords = Boolean(z.has_coordinates && z.coordinates && z.coordinates.length >= 3);
      const badgeClass = hasCoords ? 'badge-status badge-ok' : 'badge-status badge-warn';
      const badgeText = hasCoords
        ? `🟢 Каталог координат: ${z.points_count || z.coordinates.length} точек`
        : `⚠️ Поворотные точки в документе отсутствуют`;

      const defaultChecked = z.is_exclusion_zone !== false && hasCoords;

      card.innerHTML = `
        <div style="display:flex; justify-content:space-between; align-items:center; gap:10px; flex-wrap:wrap;">
          <label style="display:flex; align-items:center; gap:8px; cursor:pointer; flex:1; min-width:240px;">
            <input type="checkbox" class="zouit-chk-apply" data-index="${idx}" ${defaultChecked ? 'checked' : ''} />
            <input type="text" class="input-text zouit-input-name" data-index="${idx}" value="${escapeHtml(z.name || `Охранная зона ${idx + 1}`)}" style="font-weight:600; font-size:12.5px; width:100%; border:1px solid transparent; background:transparent; padding:2px 4px; color:var(--text-primary);" title="Кликните для редактирования наименования зоны" />
          </label>
          <div style="display:flex; align-items:center; gap:8px;">
            <span class="${badgeClass} zouit-badge-status" id="zouit-badge-${idx}" style="font-size:11px;">${badgeText}</span>
            <button type="button" class="btn-secondary btn-zouit-del" data-index="${idx}" title="Удалить зону из списка" style="padding:2px 6px; font-size:12px; color:var(--text-secondary); border:none; background:transparent; cursor:pointer;">✕</button>
          </div>
        </div>

        ${z.snippet ? `<div style="font-size:11px; color:var(--text-secondary); font-style:italic; line-height:1.3; background:var(--bg-card); padding:6px 10px; border-radius:var(--radius-sm); border-left:3px solid var(--warning);">«${escapeHtml(z.snippet)}»</div>` : ''}

        <details class="expander" ${!hasCoords ? 'open' : ''} style="margin-top:2px; font-size:11.5px;">
          <summary style="cursor:pointer; color:var(--accent); font-weight:600;">
            ${hasCoords ? `Посмотреть каталог точек (${z.points_count || z.coordinates.length} точ.)` : '✏️ Ввести каталог поворотных точек вручную'}
          </summary>
          <div style="display:flex; flex-direction:column; gap:6px; margin-top:6px;">
            <div style="font-size:10.5px; color:var(--text-secondary);">
              Вставьте пары координат X Y (или точка, X, Y) в метрах МСК или градусах:
            </div>
            <textarea class="zouit-manual-coords" data-index="${idx}" rows="3" style="font-family:var(--font-mono); font-size:11px; width:100%; resize:vertical; background:var(--bg-panel); border:1px solid var(--border-subtle); color:var(--text-primary); padding:4px 6px;" placeholder="1  338000.00  1475200.00&#10;2  338050.00  1475250.00&#10;3  338020.00  1475300.00">${escapeHtml(z.coordinates_text || '')}</textarea>
            <div style="display:flex; gap:12px; align-items:center;">
              <label style="display:flex; align-items:center; gap:6px; font-size:11px; color:var(--text-secondary);">
                <span>Буфер / ширина охранной зоны (м):</span>
                <input type="number" class="zouit-input-buffer" data-index="${idx}" value="${z.buffer_m || 5}" step="1" min="1" max="200" style="width:60px; padding:2px 4px; font-size:11px; text-align:right;" />
              </label>
            </div>
          </div>
        </details>
      `;

      el.modalGpzuZouitList.appendChild(card);
    });

    // Realtime listeners for manual coordinates in ZOUIT cards
    el.modalGpzuZouitList.querySelectorAll('.zouit-manual-coords').forEach(ta => {
      ta.addEventListener('input', e => {
        const idx = parseInt(e.target.dataset.index, 10);
        const text = e.target.value.trim();
        const pts = parseCoordinateTextClient(text);
        const badge = document.getElementById(`zouit-badge-${idx}`);
        const chk = el.modalGpzuZouitList.querySelector(`.zouit-chk-apply[data-index="${idx}"]`);
        if (pts.length >= 3) {
          if (badge) {
            badge.className = 'badge-status badge-ok';
            badge.textContent = `🟢 Введено вручную: ${pts.length} точек`;
          }
          if (chk) chk.checked = true;
        } else if (pts.length === 2) {
          if (badge) {
            badge.className = 'badge-status badge-ok';
            badge.textContent = `🟢 Осевая линия (2 точки + буфер)`;
          }
          if (chk) chk.checked = true;
        } else {
          if (badge) {
            badge.className = 'badge-status badge-warn';
            badge.textContent = `⚠️ Поворотные точки отсутствуют`;
          }
        }
      });
    });

    // Delete ZOUIT card
    el.modalGpzuZouitList.querySelectorAll('.btn-zouit-del').forEach(btn => {
      btn.addEventListener('click', e => {
        const idx = parseInt(e.target.dataset.index, 10);
        if (state.currentGpzuParsedData && state.currentGpzuParsedData.zouit) {
          state.currentGpzuParsedData.zouit.splice(idx, 1);
          renderZouitModalList(state.currentGpzuParsedData.zouit);
        }
      });
    });
  }

  function openGpzuModalWithData(data) {
    if (!data) return;
    state.currentGpzuParsedData = JSON.parse(JSON.stringify(data));
    if (el.gpzuModal) el.gpzuModal.style.display = 'flex';

    if (el.modalGpzuTitle) {
      el.modalGpzuTitle.textContent = `${data.cadastral_number || 'Кадастровый номер не указан'} · ${data.filename || 'Файл ГПЗУ'}`;
    }
    if (el.modalGpzuPointsBadge) {
      el.modalGpzuPointsBadge.textContent = `${data.points_count || 0} точек границы (${data.coordinate_system || 'МСК'})`;
    }
    if (el.modalGpzuAreaBadge) {
      el.modalGpzuAreaBadge.textContent = `${Math.round(data.area_sqm || 0).toLocaleString('ru-RU')} м² (${(data.area_ha || ((data.area_sqm || 0) / 10000)).toFixed(2)} га)`;
    }

    const sb = data.setbacks || {};
    const snips = data.snippets || {};

    // 1. Отступ от границ ЗУ
    if (el.modalGpzuChkSetback && el.modalGpzuValSetback && el.modalGpzuSnipSetback) {
      if (sb.boundary_setback !== undefined && sb.boundary_setback !== null) {
        el.modalGpzuChkSetback.checked = true;
        el.modalGpzuValSetback.value = sb.boundary_setback;
        el.modalGpzuSnipSetback.textContent = snips.boundary_setback ? `«${snips.boundary_setback}»` : 'Найдено в разделе 2.2 ГПЗУ';
      } else {
        el.modalGpzuChkSetback.checked = false;
        el.modalGpzuValSetback.value = state.boundary_setback || 3.0;
        el.modalGpzuSnipSetback.textContent = '(в тексте ГПЗУ не найдено, действует ПЗЗ/РНГП)';
      }
    }

    // 2. Отступ от красных линий
    if (el.modalGpzuChkRedline && el.modalGpzuValRedline && el.modalGpzuSnipRedline) {
      if (sb.red_line_setback !== undefined && sb.red_line_setback !== null) {
        el.modalGpzuChkRedline.checked = true;
        el.modalGpzuValRedline.value = sb.red_line_setback;
        el.modalGpzuSnipRedline.textContent = snips.red_line_setback ? `«${snips.red_line_setback}»` : 'Найдено в разделе 2.2 ГПЗУ';
      } else {
        el.modalGpzuChkRedline.checked = false;
        el.modalGpzuValRedline.value = state.red_line_setback || 5.0;
        el.modalGpzuSnipRedline.textContent = '(в тексте ГПЗУ не найдено, действует норматив)';
      }
    }

    // 3. Предельная этажность
    if (el.modalGpzuChkFloors && el.modalGpzuValFloors && el.modalGpzuSnipFloors) {
      if (sb.max_floors !== undefined && sb.max_floors !== null) {
        el.modalGpzuChkFloors.checked = true;
        el.modalGpzuValFloors.value = sb.max_floors;
        el.modalGpzuSnipFloors.textContent = snips.max_floors ? `«${snips.max_floors}»` : 'Найдено в регламентах ГПЗУ';
      } else {
        el.modalGpzuChkFloors.checked = false;
        el.modalGpzuValFloors.value = state.max_floors || 14;
        el.modalGpzuSnipFloors.textContent = '(в тексте ГПЗУ не найдено, действует базовая)';
      }
    }

    // 4. Предельная высота зданий
    if (el.modalGpzuChkMaxH && el.modalGpzuValMaxH && el.modalGpzuSnipMaxH) {
      if (sb.max_height_m !== undefined && sb.max_height_m !== null) {
        el.modalGpzuChkMaxH.checked = true;
        el.modalGpzuValMaxH.value = sb.max_height_m;
        el.modalGpzuSnipMaxH.textContent = snips.max_height_m ? `«${snips.max_height_m}»` : 'Найдено в регламентах ГПЗУ';
      } else {
        el.modalGpzuChkMaxH.checked = false;
        el.modalGpzuValMaxH.value = state.max_height_m || 50.0;
        el.modalGpzuSnipMaxH.textContent = '(в тексте ГПЗУ не найдено, без ограничений)';
      }
    }

    // 5. Кз (BCR)
    if (el.modalGpzuChkBcr && el.modalGpzuValBcr && el.modalGpzuSnipBcr) {
      if (sb.max_bcr !== undefined && sb.max_bcr !== null) {
        el.modalGpzuChkBcr.checked = true;
        el.modalGpzuValBcr.value = Math.round(sb.max_bcr <= 1.0 ? sb.max_bcr * 100 : sb.max_bcr);
        el.modalGpzuSnipBcr.textContent = snips.max_bcr ? `«${snips.max_bcr}»` : 'Найдено в регламентах ГПЗУ';
      } else {
        el.modalGpzuChkBcr.checked = false;
        el.modalGpzuValBcr.value = state.max_bcr || 40;
        el.modalGpzuSnipBcr.textContent = '(в тексте ГПЗУ не найдено, действует ПЗЗ 40%)';
      }
    }

    // 6. Кпз (FAR)
    if (el.modalGpzuChkFar && el.modalGpzuValFar && el.modalGpzuSnipFar) {
      if (sb.max_far !== undefined && sb.max_far !== null) {
        el.modalGpzuChkFar.checked = true;
        el.modalGpzuValFar.value = sb.max_far;
        el.modalGpzuSnipFar.textContent = snips.max_far ? `«${snips.max_far}»` : 'Найдено в регламентах ГПЗУ';
      } else {
        el.modalGpzuChkFar.checked = false;
        el.modalGpzuValFar.value = state.max_far || 2.5;
        el.modalGpzuSnipFar.textContent = '(в тексте ГПЗУ не найдено, действует ПЗЗ 2.5)';
      }
    }

    // 7. Озеленение
    if (el.modalGpzuChkGreen && el.modalGpzuValGreen && el.modalGpzuSnipGreen) {
      if (sb.min_greening_percent !== undefined && sb.min_greening_percent !== null) {
        el.modalGpzuChkGreen.checked = true;
        el.modalGpzuValGreen.value = Math.round(sb.min_greening_percent);
        el.modalGpzuSnipGreen.textContent = snips.min_greening_percent ? `«${snips.min_greening_percent}»` : 'Найдено в регламентах ГПЗУ';
      } else {
        el.modalGpzuChkGreen.checked = false;
        el.modalGpzuValGreen.value = state.green_ratio || 25;
        el.modalGpzuSnipGreen.textContent = '(в тексте ГПЗУ не найдено, норматив СП 42: 25%)';
      }
    }

    // Render lists
    renderGpzuZonesModalList(state.currentGpzuParsedData.zones || []);
    renderZouitModalList(state.currentGpzuParsedData.zouit || []);
  }

  function applyGpzuModalData(boundaryOnly = false) {
    if (!state.currentGpzuParsedData) return;
    flushGpzuModalTextareas();

    // 1. Regulatory parameters (if full apply)
    if (!boundaryOnly) {
      if (el.modalGpzuChkSetback && el.modalGpzuChkSetback.checked) {
        const val = parseFloat(el.modalGpzuValSetback.value);
        if (!isNaN(val)) {
          state.boundary_setback = val;
          if (el.sliderBoundarySetback) el.sliderBoundarySetback.value = val;
          if (el.valBoundarySetback) el.valBoundarySetback.textContent = `${val} м`;
        }
      }

      if (el.modalGpzuChkRedline && el.modalGpzuChkRedline.checked) {
        const val = parseFloat(el.modalGpzuValRedline.value);
        if (!isNaN(val)) {
          state.red_line_setback = val;
          if (el.sliderRedlineSetback) el.sliderRedlineSetback.value = val;
          if (el.valRedlineSetback) el.valRedlineSetback.textContent = `${val} м`;
        }
      }

      if (el.modalGpzuChkFloors && el.modalGpzuChkFloors.checked) {
        const val = parseInt(el.modalGpzuValFloors.value, 10);
        if (!isNaN(val)) {
          state.max_floors = val;
          if (el.inputMaxFloors) el.inputMaxFloors.value = val;
          if (el.valMaxFloors) el.valMaxFloors.textContent = `${val} эт.`;
        }
      }

      if (el.modalGpzuChkMaxH && el.modalGpzuChkMaxH.checked) {
        const val = parseFloat(el.modalGpzuValMaxH.value);
        if (!isNaN(val)) {
          state.max_height_m = val;
          if (el.inputMaxHeight) el.inputMaxHeight.value = val;
          if (el.valMaxHeight) el.valMaxHeight.textContent = `${val} м`;
        }
      }

      if (el.modalGpzuChkBcr && el.modalGpzuChkBcr.checked) {
        const val = parseFloat(el.modalGpzuValBcr.value);
        if (!isNaN(val)) {
          state.max_bcr = val;
          if (el.inputMaxBcr) el.inputMaxBcr.value = val;
          if (el.valMaxBcr) el.valMaxBcr.textContent = `${val}%`;
        }
      }

      if (el.modalGpzuChkFar && el.modalGpzuChkFar.checked) {
        const val = parseFloat(el.modalGpzuValFar.value);
        if (!isNaN(val)) {
          state.max_far = val;
          if (el.inputMaxFar) el.inputMaxFar.value = val;
          if (el.valMaxFar) el.valMaxFar.textContent = `${val.toFixed(2)}`;
        }
      }

      if (el.modalGpzuChkGreen && el.modalGpzuChkGreen.checked) {
        const val = parseFloat(el.modalGpzuValGreen.value);
        if (!isNaN(val)) state.green_ratio = val;
      }

      if (el.step3CardFloors) el.step3CardFloors.textContent = `${state.max_floors} эт. (${state.max_height_m} м)`;
      if (el.step3CardFar) el.step3CardFar.textContent = state.max_far.toFixed(2);
      if (el.step3CardBcr) el.step3CardBcr.textContent = `${state.max_bcr}%`;
      if (el.step3CardGreen) el.step3CardGreen.textContent = `≥ ${state.green_ratio}%`;
    }

    // 2. Active ZOUIT zones
    state.activeZouitZones = [];
    if (!boundaryOnly) {
      if (state.currentGpzuParsedData.zones) {
        state.currentGpzuParsedData.zones.forEach(z => {
          if (z.role === 'zouit_exclusion' && z.enabled !== false && z.coordinates && z.coordinates.length >= 3) {
            state.activeZouitZones.push({
              name: z.name,
              enabled: true,
              coordinates: z.coordinates,
              coordinates_text: z.coordinates_text,
              buffer_m: 5.0,
              snippet: z.description || '',
              type: 'zouit'
            });
          }
        });
      }

      if (el.modalGpzuZouitList && state.currentGpzuParsedData.zouit) {
        const cards = el.modalGpzuZouitList.querySelectorAll('.zouit-item-card');
        cards.forEach(card => {
          const chk = card.querySelector('.zouit-chk-apply');
          const idx = parseInt(chk.dataset.index, 10);
          const zObj = state.currentGpzuParsedData.zouit[idx];
          if (chk && chk.checked && zObj) {
            const nameInput = card.querySelector('.zouit-input-name');
            const name = nameInput ? nameInput.value.trim() : zObj.name;
            const ta = card.querySelector('.zouit-manual-coords');
            const coordsText = ta ? ta.value.trim() : (zObj.coordinates_text || '');
            const bufInput = card.querySelector('.zouit-input-buffer');
            const bufM = bufInput ? (parseFloat(bufInput.value) || 5.0) : 5.0;

            let coords = zObj.coordinates || [];
            if (coordsText) {
              const clientPts = parseCoordinateTextClient(coordsText);
              if (clientPts.length >= 2) coords = clientPts;
            }

            if (!state.activeZouitZones.some(az => az.name === name)) {
              state.activeZouitZones.push({
                name: name,
                enabled: true,
                coordinates: coords,
                coordinates_text: coordsText,
                buffer_m: bufM,
                snippet: zObj.snippet || '',
                type: zObj.type || 'easement'
              });
            }
          }
        });
      }
    }

    // 3. Boundary zone selection
    let bZone = null;
    if (state.currentGpzuParsedData.zones && state.currentGpzuParsedData.zones.length > 0) {
      bZone = state.currentGpzuParsedData.zones.find(z => z.role === 'boundary') || state.currentGpzuParsedData.zones[0];
    }
    const targetCoords = (bZone && bZone.coordinates_text) || state.currentGpzuParsedData.coordinates_text || '';
    const targetPts = parseCoordinateTextClient(targetCoords);

    if (targetPts.length < 3) {
      alert('⚠️ Ошибка: для контура границы требуется минимум 3 точки!');
      return;
    }

    state.gpzu_coordinates = targetCoords;
    if (el.textareaCoords) el.textareaCoords.value = targetCoords;

    if (state.currentGpzuParsedData.coordinate_system) {
      ensureMskOption(state.currentGpzuParsedData.coordinate_system);
      state.msk_zone = state.currentGpzuParsedData.coordinate_system;
    }
    if (state.currentGpzuParsedData.cadastral_number) {
      state.cad_query = state.currentGpzuParsedData.cadastral_number;
      if (el.inputCadNum) el.inputCadNum.value = state.currentGpzuParsedData.cadastral_number;
    }
    if (bZone && bZone.area_sqm) {
      state.custom_area = Math.round(bZone.area_sqm);
    } else if (state.currentGpzuParsedData.area_sqm) {
      state.custom_area = Math.round(state.currentGpzuParsedData.area_sqm);
    }

    state.userHasMovedSite = false;
    state.override_lat = 0.0;
    state.override_lon = 0.0;
    state.isLocked = false;

    closeGpzuModal();
    apiPreviewSite(true);
  }

  // Bind GPZU modal actions
  if (el.gpzuModalClose) el.gpzuModalClose.addEventListener('click', closeGpzuModal);
  if (el.btnModalGpzuCancel) el.btnModalGpzuCancel.addEventListener('click', closeGpzuModal);
  if (el.gpzuModal) {
    el.gpzuModal.addEventListener('click', e => {
      if (e.target === el.gpzuModal) closeGpzuModal();
    });
  }
  if (el.btnModalGpzuApply) {
    el.btnModalGpzuApply.addEventListener('click', () => applyGpzuModalData(false));
  }
  if (el.btnModalGpzuBoundaryOnly) {
    el.btnModalGpzuBoundaryOnly.addEventListener('click', () => applyGpzuModalData(true));
  }
  if (el.btnModalAddZouit) {
    el.btnModalAddZouit.addEventListener('click', () => {
      if (!state.currentGpzuParsedData) {
        state.currentGpzuParsedData = { zouit: [] };
      }
      if (!state.currentGpzuParsedData.zouit) state.currentGpzuParsedData.zouit = [];
      state.currentGpzuParsedData.zouit.push({
        name: `Пользовательская охранная зона ${state.currentGpzuParsedData.zouit.length + 1}`,
        type: 'custom',
        has_coordinates: false,
        coordinates: [],
        coordinates_text: '',
        points_count: 0,
        is_exclusion_zone: true,
        buffer_m: 5.0,
        snippet: 'Добавлено пользователем вручную'
      });
      renderZouitModalList(state.currentGpzuParsedData.zouit);
    });
  }

  if (el.btnOpenGpzuModalCad) {
    el.btnOpenGpzuModalCad.addEventListener('click', () => {
      if (state.currentGpzuParsedData) {
        openGpzuModalWithData(state.currentGpzuParsedData);
      } else {
        alert('Сначала загрузите выписку ГПЗУ');
      }
    });
  }
  if (el.btnOpenGpzuModalPoints) {
    el.btnOpenGpzuModalPoints.addEventListener('click', () => {
      if (state.currentGpzuParsedData) {
        openGpzuModalWithData(state.currentGpzuParsedData);
      } else {
        alert('Сначала загрузите выписку ГПЗУ');
      }
    });
  }
  // =========================================================================
  // STEP 3: REGULATIONS POPUP MODAL & CONTROLS
  // =========================================================================

  function openStep3RegulationsModal() {
    if (!state.currentData) {
      alert('Пожалуйста, сначала посадите участок на Шаге 1.');
      return;
    }
    if (!el.modalStep3Regs) return;

    // 1. Site and Blocks Summary
    const areaHa = state.currentData.site_area_ha ? `${fmtNum(state.currentData.site_area_ha)} га` : `${((state.currentData.site_area_sqm || 0) / 10000).toFixed(2)} га`;
    if (el.modalStep3SiteSummary) {
      el.modalStep3SiteSummary.textContent = `${areaHa} (${fmtInt(state.currentData.site_area_sqm || 0)} м²)`;
    }
    const roads = state.currentData.roads || {};
    const blCount = roads.sub_blocks_count || ((roads.sub_blocks_data && roads.sub_blocks_data.length) || 1);
    if (el.modalStep3BlocksSummary) {
      el.modalStep3BlocksSummary.textContent = `${blCount} ${pluralBlocks(blCount)}`;
    }

    // 2. Regulations Inputs
    if (el.inputStep3Floors) {
      el.inputStep3Floors.value = state.max_floors;
      if (el.valStep3Floors) el.valStep3Floors.textContent = `${state.max_floors} эт.`;
    }
    if (el.inputStep3Height) {
      el.inputStep3Height.value = state.max_height_m;
      if (el.valStep3Height) el.valStep3Height.textContent = `${state.max_height_m} м`;
    }
    if (el.inputStep3Bcr) {
      el.inputStep3Bcr.value = state.max_bcr;
      if (el.valStep3Bcr) el.valStep3Bcr.textContent = `${state.max_bcr}%`;
    }
    if (el.inputStep3Far) {
      el.inputStep3Far.value = state.max_far;
      if (el.valStep3Far) el.valStep3Far.textContent = state.max_far.toFixed(2);
    }
    if (el.inputStep3Green) {
      el.inputStep3Green.value = state.green_ratio;
      if (el.valStep3Green) el.valStep3Green.textContent = `${state.green_ratio}%`;
    }
    if (el.inputStep3SetbackBound) {
      el.inputStep3SetbackBound.value = state.boundary_setback;
    }
    if (el.inputStep3SetbackRedline) {
      el.inputStep3SetbackRedline.value = state.red_line_setback;
    }
    if (el.valStep3Setback) {
      el.valStep3Setback.textContent = `${state.boundary_setback} / ${state.red_line_setback} м`;
    }

    // 3. Snippets from GPZU if available
    const snips = (state.currentGpzuParsedData && state.currentGpzuParsedData.snippets) || {};
    if (el.snipStep3Floors) {
      el.snipStep3Floors.textContent = snips.max_floors ? `«${snips.max_floors}»` : 'Раздел 2.2 ГПЗУ / ПЗЗ';
    }
    if (el.snipStep3Height) {
      el.snipStep3Height.textContent = snips.max_height_m ? `«${snips.max_height_m}»` : 'Предельная высота от нуля до конька/парапета';
    }
    if (el.snipStep3Bcr) {
      el.snipStep3Bcr.textContent = snips.max_bcr ? `«${snips.max_bcr}»` : 'Максимальный процент застройки в границах квартала';
    }
    if (el.snipStep3Far) {
      el.snipStep3Far.textContent = snips.max_far ? `«${snips.max_far}»` : 'Коэффициент плотности застройки (КПО)';
    }

    // 4. ZOUIT status
    const zouits = state.activeZouitZones || [];
    if (el.modalStep3ZouitCount) {
      el.modalStep3ZouitCount.textContent = `${zouits.length} зон`;
    }
    if (el.modalStep3ZouitSummary) {
      if (zouits.length > 0) {
        const zouitArea = (state.currentData && state.currentData.zouit_info || []).reduce((acc, z) => acc + (z.area_sqm || 0), 0);
        el.modalStep3ZouitSummary.textContent = `Активны ограничения: ${zouits.map(z => z.name).join('; ')} (-${fmtInt(zouitArea)} м²)`;
      } else {
        el.modalStep3ZouitSummary.textContent = 'Охранные зоны ЗОУИТ не обнаружены';
      }
    }

    el.modalStep3Regs.style.display = 'flex';
  }

  function closeStep3RegulationsModal() {
    if (el.modalStep3Regs) el.modalStep3Regs.style.display = 'none';
  }

  if (el.modalStep3RegsClose) el.modalStep3RegsClose.addEventListener('click', closeStep3RegulationsModal);
  if (el.btnStep3RegsBack) el.btnStep3RegsBack.addEventListener('click', closeStep3RegulationsModal);
  if (el.modalStep3Regs) {
    el.modalStep3Regs.addEventListener('click', e => {
      if (e.target === el.modalStep3Regs) closeStep3RegulationsModal();
    });
  }

  // Real-time tag updates in Step 3 Modal
  if (el.inputStep3Floors) {
    el.inputStep3Floors.addEventListener('input', () => {
      const v = el.inputStep3Floors.value;
      if (el.valStep3Floors) el.valStep3Floors.textContent = `${v} эт.`;
    });
  }
  if (el.inputStep3Height) {
    el.inputStep3Height.addEventListener('input', () => {
      const v = el.inputStep3Height.value;
      if (el.valStep3Height) el.valStep3Height.textContent = `${v} м`;
    });
  }
  if (el.inputStep3Bcr) {
    el.inputStep3Bcr.addEventListener('input', () => {
      const v = el.inputStep3Bcr.value;
      if (el.valStep3Bcr) el.valStep3Bcr.textContent = `${v}%`;
    });
  }
  if (el.inputStep3Far) {
    el.inputStep3Far.addEventListener('input', () => {
      const v = parseFloat(el.inputStep3Far.value);
      if (el.valStep3Far) el.valStep3Far.textContent = isNaN(v) ? '2.50' : v.toFixed(2);
    });
  }
  if (el.inputStep3Green) {
    el.inputStep3Green.addEventListener('input', () => {
      const v = el.inputStep3Green.value;
      if (el.valStep3Green) el.valStep3Green.textContent = `${v}%`;
    });
  }
  const updateSetbackTag = () => {
    const b = el.inputStep3SetbackBound ? el.inputStep3SetbackBound.value : state.boundary_setback;
    const r = el.inputStep3SetbackRedline ? el.inputStep3SetbackRedline.value : state.red_line_setback;
    if (el.valStep3Setback) el.valStep3Setback.textContent = `${b} / ${r} м`;
  };
  if (el.inputStep3SetbackBound) el.inputStep3SetbackBound.addEventListener('input', updateSetbackTag);
  if (el.inputStep3SetbackRedline) el.inputStep3SetbackRedline.addEventListener('input', updateSetbackTag);

  // Confirm Step 3 Regulations & Proceed to Step 3
  if (el.btnStep3RegsConfirm) {
    el.btnStep3RegsConfirm.addEventListener('click', () => {
      if (el.inputStep3Floors) state.max_floors = parseInt(el.inputStep3Floors.value, 10) || state.max_floors;
      if (el.inputStep3Height) state.max_height_m = parseFloat(el.inputStep3Height.value) || state.max_height_m;
      if (el.inputStep3Bcr) state.max_bcr = parseFloat(el.inputStep3Bcr.value) || state.max_bcr;
      if (el.inputStep3Far) state.max_far = parseFloat(el.inputStep3Far.value) || state.max_far;
      if (el.inputStep3Green) state.green_ratio = parseFloat(el.inputStep3Green.value) || state.green_ratio;
      if (el.inputStep3SetbackBound) state.boundary_setback = parseFloat(el.inputStep3SetbackBound.value) || state.boundary_setback;
      if (el.inputStep3SetbackRedline) state.red_line_setback = parseFloat(el.inputStep3SetbackRedline.value) || state.red_line_setback;

      // Read and save fine-tuned RNGP parameters
      const playChildren = el.inputRngpChildren ? parseFloat(el.inputRngpChildren.value) : 0.70;
      const playSport = el.inputRngpSport ? parseFloat(el.inputRngpSport.value) : 2.00;
      const playRelax = el.inputRngpRelax ? parseFloat(el.inputRngpRelax.value) : 0.10;
      const playUtility = el.inputRngpUtility ? parseFloat(el.inputRngpUtility.value) : 0.38;
      const livingPerPerson = el.inputRngpLiving ? parseFloat(el.inputRngpLiving.value) : 30.0;
      const parkingRatio = el.inputRngpParkingRatio ? parseFloat(el.inputRngpParkingRatio.value) : 350.0;
      const guestShare = el.inputRngpGuestShare ? parseFloat(el.inputRngpGuestShare.value) / 100.0 : 0.25;
      const areaPerCar = el.inputRngpAreaPerCar ? parseFloat(el.inputRngpAreaPerCar.value) : 25.0;

      state.custom_regional_norm = {
        name: "Индивидуальный норматив (РНГП / ГПЗУ)",
        parking_method: "per_1000_people",
        parking_ratio: parkingRatio,
        guest_share: guestShare,
        area_per_car: areaPerCar,
        play_children: playChildren,
        play_sport: playSport,
        play_relax: playRelax,
        play_utility: playUtility * 0.8,
        play_waste: playUtility * 0.2,
        living_per_person: livingPerPerson,
        green_ratio_min: (state.green_ratio ? state.green_ratio / 100.0 : 0.25),
        max_far: state.max_far || 2.5,
        max_bcr: (state.max_bcr ? state.max_bcr / 100.0 : 0.40)
      };

      // Update Step 3 Left panel summary card
      if (el.step3CardFloors) el.step3CardFloors.textContent = `${state.max_floors} эт. (${state.max_height_m} м)`;
      if (el.step3CardFar) el.step3CardFar.textContent = state.max_far.toFixed(2);
      if (el.step3CardBcr) el.step3CardBcr.textContent = `${state.max_bcr}%`;
      if (el.step3CardGreen) el.step3CardGreen.textContent = `≥ ${state.green_ratio}%`;

      // Update Land Passport rows
      if (el.pMaxHeight) el.pMaxHeight.textContent = `${state.max_floors} эт. (${state.max_height_m} м)`;
      if (el.pMaxBcr) el.pMaxBcr.textContent = `${state.max_bcr}%`;
      if (el.pMaxFar) el.pMaxFar.textContent = `${state.max_far.toFixed(2)}`;

      closeStep3RegulationsModal();
      setStep(3);
      apiGenerateLayout();
    });
  }

  // Open Full GPZU Inspector from Step 3 Popup
  if (el.btnStep3OpenFullGpzu) {
    el.btnStep3OpenFullGpzu.addEventListener('click', () => {
      closeStep3RegulationsModal();
      if (state.currentGpzuParsedData) {
        openGpzuModalWithData(state.currentGpzuParsedData);
      } else {
        openGpzuModalWithData({
          cadastral_number: state.cad_query || '',
          filename: 'Ручные регламенты',
          coordinate_system: state.msk_zone || 'МСК',
          points_count: (state.currentData && state.currentData.boundary_coords) ? state.currentData.boundary_coords.length : 0,
          area_sqm: (state.currentData && state.currentData.site_area_sqm) || state.custom_area,
          setbacks: {
            boundary_setback: state.boundary_setback,
            red_line_setback: state.red_line_setback,
            max_floors: state.max_floors,
            max_height_m: state.max_height_m,
            max_bcr: state.max_bcr / 100.0,
            max_far: state.max_far,
            min_greening_percent: state.green_ratio
          },
          snippets: {},
          zones: [
            {
              id: 'zone_main',
              name: 'Основной контур ЗУ',
              role: 'boundary',
              points_count: (state.currentData && state.currentData.boundary_coords) ? state.currentData.boundary_coords.length : 0,
              coordinates_text: state.gpzu_coordinates || '',
              area_sqm: (state.currentData && state.currentData.site_area_sqm) || state.custom_area
            }
          ],
          zouit: state.activeZouitZones || []
        });
      }
    });
  }

  // Step 3 Left panel: Edit regulations button
  if (el.btnStep3EditRegs) {
    el.btnStep3EditRegs.addEventListener('click', () => {
      openStep3RegulationsModal();
    });
  }

  // Step 3 Left panel: Back button to Step 2
  if (el.btnStep3Back) {
    el.btnStep3Back.addEventListener('click', () => {
      setStep(2);
    });
  }

  // Step 3 Left panel: Typology selector (принципы обычного дашборда)
  el.typologyBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      el.typologyBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const typ = btn.dataset.typology;
      state.typology = typ;
      const names = {
        AUTO: 'Квартальная (AUTO)',
        U_SHAPE: 'П-образные дворы',
        TOWER: 'Башни (Towers)',
        SECTIONAL: 'Секционная'
      };
      if (el.valTypologyTag) el.valTypologyTag.textContent = names[typ] || typ;
      if (typ === 'TOWER') {
        const maxH = state.max_height_m || 50.0;
        // башня Б1: коммерческий 1-й этаж 4.2 м, типовой этаж 3.15 м
        const maxFitFloors = Math.max(1, Math.floor((maxH - 4.2) / 3.15) + 1);
        const targetTowerFloors = Math.min(16, maxFitFloors);
        state.max_floors = targetTowerFloors;
        if (el.sliderStep3Floors) el.sliderStep3Floors.value = targetTowerFloors;
        if (el.labelStep3Floors) el.labelStep3Floors.textContent = `${targetTowerFloors} эт.`;
        const estH = (4.2 + (targetTowerFloors - 1) * 3.15).toFixed(1);
        if (el.valStep3FloorsTag) el.valStep3FloorsTag.textContent = `${targetTowerFloors} эт. (${estH} м)`;
        if (el.step3CardFloors) el.step3CardFloors.textContent = `${targetTowerFloors} эт. (${estH} м)`;
      }

      // Auto-recalculate layout on Step 3: instantly update buildings inside the existing UDS sub-blocks!
      if (state.currentStep === 3 && state.currentData && !state.isGenerating) {
        apiGenerateLayout();
      }
    });
  });

  // Вспомогательный дебаунсер для живого отклика параметров и ползунков Шага 3
  let step3DebounceTimer = null;
  function triggerStep3LiveUpdate(delay = 250) {
    if (state.currentStep !== 3 || !state.currentData || state.isGenerating) return;
    clearTimeout(step3DebounceTimer);
    step3DebounceTimer = setTimeout(() => {
      apiGenerateLayout();
    }, delay);
  }

  // Step 3: Принципы застройки (СанПиН инсоляция, Двор без машин, ориентация)
  if (el.chkStep3Cascade) {
    el.chkStep3Cascade.addEventListener('change', () => {
      state.cascade_floors = el.chkStep3Cascade.checked;
      triggerStep3LiveUpdate(100);
    });
  }
  if (el.chkStep3CarFree) {
    el.chkStep3CarFree.addEventListener('change', () => {
      state.car_free_courtyard = el.chkStep3CarFree.checked;
      triggerStep3LiveUpdate(100);
    });
  }
  
    // Региональные нормативы и ЗОУИТ-парковки (Шаг 3)
    function applyRegionalNorm(normId) {
      if (!normId) normId = 'russia_sp42';
      state.regional_norm_id = normId;
      if (el.selectStep3RegionalNorm) el.selectStep3RegionalNorm.value = normId;
      const meta = REGIONAL_NORMS_DATA[normId] || REGIONAL_NORMS_DATA.russia_sp42;
      if (el.badgeStep3NormTag) el.badgeStep3NormTag.textContent = meta.badge;
      if (el.step3NormSummary) el.step3NormSummary.textContent = meta.desc;
    }

    function autoDetectRegionFromCadastre(cadQuery) {
      if (!cadQuery) return;
      const clean = cadQuery.trim();
      let matched = null;
      if (clean.startsWith('77:')) matched = 'moscow_mngp';
      else if (clean.startsWith('50:')) matched = 'moscow_oblast_rngp';
      else if (clean.startsWith('78:')) matched = 'spb_rngp';
      else if (clean.startsWith('72:')) matched = 'tyumen_mngp';
      if (matched) {
        applyRegionalNorm(matched);
      }
    }

    if (el.selectStep3RegionalNorm) {
      el.selectStep3RegionalNorm.addEventListener('change', (e) => {
        applyRegionalNorm(e.target.value);
        triggerStep3LiveUpdate(100);
      });
    }

    if (el.chkStep3AllowZouit) {
      el.chkStep3AllowZouit.checked = !!state.allow_parking_in_zouit;
      el.chkStep3AllowZouit.addEventListener('change', () => {
        state.allow_parking_in_zouit = el.chkStep3AllowZouit.checked;
        triggerStep3LiveUpdate(100);
      });
    }

    if (el.chkStep3OnlyGround) {
    el.chkStep3OnlyGround.addEventListener('change', () => {
      state.only_ground_parking = el.chkStep3OnlyGround.checked;
      if (state.currentScenario) {
        apiGenerateLayout();
      }
    });
  }
  if (el.chkStep3TowersMixed) {
    el.chkStep3TowersMixed.addEventListener('change', () => {
      state.allow_towers_in_mixed = el.chkStep3TowersMixed.checked;
      triggerStep3LiveUpdate(100);
    });
  }
  if (el.selectStep3CourtOrient) {
    el.selectStep3CourtOrient.addEventListener('change', () => {
      state.courtyard_orientation = el.selectStep3CourtOrient.value;
      triggerStep3LiveUpdate(100);
    });
  }
  // --- Чипы выбора секций и Каталог типовых секций с численными высотами ---
  function calcSectionHeight(sec, floors) {
    if (!floors || floors <= 0) return 0;
    const gh = (sec.has_commercial_ground && sec.ground_floor_height) ? sec.ground_floor_height : (sec.floor_height || 3.15);
    const fh = sec.floor_height || 3.15;
    if (sec.has_commercial_ground && floors > 1) {
      return Number((gh + (floors - 1) * fh).toFixed(2));
    }
    return Number((floors * fh).toFixed(2));
  }

  function refreshPrefSectionChips() {
    if (!el.prefSectionsContainer) return;
    el.prefSectionsContainer.innerHTML = '';
    const catOrder = { MIDDLE: 0, CORNER: 1, END: 2, TOWER: 3, UNIVERSAL: 4 };
    (state.sectionCatalog || [])
      .slice()
      .sort((a, b) => ((catOrder[a.category] ?? 9) - (catOrder[b.category] ?? 9)) || (a.width - b.width))
      .forEach(sec => {
        const chip = document.createElement('button');
        chip.type = 'button';
        chip.className = 'cat-pill';
        if (state.preferred_section_ids.includes(sec.id)) chip.classList.add('active');
        chip.setAttribute('data-id', sec.id);
        chip.textContent = (sec.code && sec.code !== sec.id) ? sec.code : sec.name;
        const minH = calcSectionHeight(sec, sec.min_floors);
        const maxH = calcSectionHeight(sec, sec.max_floors);
        chip.title = `${sec.name}: ${sec.width}×${sec.depth} м, этажи ${sec.min_floors}–${sec.max_floors} (${minH.toFixed(1)}–${maxH.toFixed(1)} м)`;
        chip.addEventListener('click', () => {
          chip.classList.toggle('active');
          const id = chip.getAttribute('data-id');
          const idx = state.preferred_section_ids.indexOf(id);
          if (idx >= 0) state.preferred_section_ids.splice(idx, 1);
          else state.preferred_section_ids.push(id);
          if (el.hintPrefSections) {
            el.hintPrefSections.textContent = state.preferred_section_ids.length
              ? `Выбрано: ${state.preferred_section_ids.length}`
              : 'Все типы';
          }
          triggerStep3LiveUpdate(150);
        });
        el.prefSectionsContainer.appendChild(chip);
      });
  }

  function renderSectionsCatalogModal() {
    if (!el.modalSectionsTbody) return;
    el.modalSectionsTbody.innerHTML = '';
    const catOrder = { TOWER: 0, MIDDLE: 1, CORNER: 2, END: 3, UNIVERSAL: 4 };
    const catBadges = {
      TOWER: '<span class="sec-badge-category badge-accent">🗼 Башня</span>',
      MIDDLE: '<span class="sec-badge-category badge-neutral">🏢 Рядовая</span>',
      CORNER: '<span class="sec-badge-category badge-neutral">↩️ Угловая</span>',
      END: '<span class="sec-badge-category badge-neutral">↔️ Торцевая</span>',
      UNIVERSAL: '<span class="sec-badge-category badge-ok">🌟 Универсал</span>',
    };

    const sorted = (state.sectionCatalog || []).slice().sort((a, b) => {
      return (catOrder[a.category] ?? 9) - (catOrder[b.category] ?? 9) || (a.width - b.width);
    });

    sorted.forEach(sec => {
      const tr = document.createElement('tr');
      tr.setAttribute('data-sec-id', sec.id);

      const minH = calcSectionHeight(sec, sec.min_floors);
      const maxH = calcSectionHeight(sec, sec.max_floors);

      tr.innerHTML = `
        <td class="sec-cell-num" style="font-weight:700; color:var(--text-primary);">
          ${sec.code || sec.id}
        </td>
        <td title="${sec.name}">
          ${catBadges[sec.category] || sec.category}
        </td>
        <td class="sec-cell-num" style="color:var(--text-secondary);">
          ${sec.width} × ${sec.depth} м
        </td>
        <td style="text-align:right;">
          <input type="number" class="sec-input-floors sec-input-min-floors" data-id="${sec.id}"
            value="${sec.min_floors}" min="1" max="75" step="1" title="Минимальная этажность">
        </td>
        <td style="text-align:right;">
          <input type="number" class="sec-input-floors sec-input-max-floors" data-id="${sec.id}"
            value="${sec.max_floors}" min="1" max="75" step="1" title="Максимальная этажность">
        </td>
        <td class="sec-cell-num sec-cell-min-h" style="text-align:right; font-weight:600; color:var(--text-primary);">
          ${minH.toFixed(1)} м
        </td>
        <td class="sec-cell-num sec-cell-max-h" style="text-align:right; font-weight:600; color:var(--text-primary);">
          ${maxH.toFixed(1)} м
        </td>
        <td class="sec-cell-num" style="color:var(--text-secondary);">
          ${sec.ground_floor_height || 4.2} / ${sec.floor_height || 3.15} м
        </td>
        <td class="sec-cell-num">
          <b>${sec.floor_area}</b> / <span style="color:var(--text-secondary);">${sec.living_area_per_floor || '—'} м²</span>
        </td>
        <td class="sec-cell-num" style="color:var(--text-secondary);">
          <b>${sec.total_apartments_per_floor || 0}</b> кв.
        </td>
      `;

      // Live updates of heights when numbers are typed
      const inpMin = tr.querySelector('.sec-input-min-floors');
      const inpMax = tr.querySelector('.sec-input-max-floors');
      const cellMinH = tr.querySelector('.sec-cell-min-h');
      const cellMaxH = tr.querySelector('.sec-cell-max-h');

      function updateRowHeights() {
        const minVal = parseInt(inpMin.value, 10);
        const maxVal = parseInt(inpMax.value, 10);
        if (!isNaN(minVal) && minVal > 0) {
          cellMinH.textContent = `${calcSectionHeight(sec, minVal).toFixed(1)} м`;
        }
        if (!isNaN(maxVal) && maxVal > 0) {
          cellMaxH.textContent = `${calcSectionHeight(sec, maxVal).toFixed(1)} м`;
        }
      }

      function sanitizeFloorsOnBlur() {
        let minF = parseInt(inpMin.value, 10);
        let maxF = parseInt(inpMax.value, 10);
        if (isNaN(minF) || minF < 1) {
          minF = 1;
          inpMin.value = minF;
        }
        if (isNaN(maxF) || maxF < 1) {
          maxF = minF;
          inpMax.value = maxF;
        }
        if (maxF < minF) {
          maxF = minF;
          inpMax.value = maxF;
        }
        updateRowHeights();
      }

      inpMin.addEventListener('input', updateRowHeights);
      inpMax.addEventListener('input', updateRowHeights);
      inpMin.addEventListener('change', sanitizeFloorsOnBlur);
      inpMax.addEventListener('change', sanitizeFloorsOnBlur);

      el.modalSectionsTbody.appendChild(tr);
    });
  }

  function openSectionsCatalogModal() {
    renderSectionsCatalogModal();
    if (el.modalSectionsTable) el.modalSectionsTable.style.display = 'flex';
  }
  function closeSectionsCatalogModal() {
    if (el.modalSectionsTable) el.modalSectionsTable.style.display = 'none';
  }

  if (el.btnHeaderSections) el.btnHeaderSections.addEventListener('click', openSectionsCatalogModal);
  if (el.btnOpenSectionsModal) el.btnOpenSectionsModal.addEventListener('click', openSectionsCatalogModal);
  if (el.modalSectionsClose) el.modalSectionsClose.addEventListener('click', closeSectionsCatalogModal);
  if (el.btnModalSectionsCancel) el.btnModalSectionsCancel.addEventListener('click', closeSectionsCatalogModal);
  if (el.modalSectionsTable) {
    el.modalSectionsTable.addEventListener('click', e => {
      if (e.target === el.modalSectionsTable) closeSectionsCatalogModal();
    });
  }

  if (el.btnModalSectionsSave) {
    el.btnModalSectionsSave.addEventListener('click', async () => {
      const updates = [];
      const rows = el.modalSectionsTbody ? el.modalSectionsTbody.querySelectorAll('tr[data-sec-id]') : [];
      rows.forEach(tr => {
        const id = tr.getAttribute('data-sec-id');
        const inpMin = tr.querySelector('.sec-input-min-floors');
        const inpMax = tr.querySelector('.sec-input-max-floors');
        if (id && inpMin && inpMax) {
          let minF = parseInt(inpMin.value, 10) || 1;
          let maxF = parseInt(inpMax.value, 10) || minF;
          if (maxF < minF) maxF = minF;
          updates.push({ id, min_floors: minF, max_floors: maxF });
        }
      });

      if (el.modalSectionsStatus) el.modalSectionsStatus.textContent = '⏳ Сохранение параметров секций...';
      try {
        const resp = await fetch('/api/library/update', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ sections: updates }),
        });
        if (resp.ok) {
          const res = await resp.json();
          if (res.catalog) state.sectionCatalog = res.catalog;
          refreshPrefSectionChips();
          showToast('✅ Параметры и высотности секций успешно сохранены!');
          closeSectionsCatalogModal();
        } else {
          showToast('❌ Ошибка сохранения параметров секций');
        }
      } catch (err) {
        showToast(`❌ Ошибка сети: ${err.message}`);
      } finally {
        if (el.modalSectionsStatus) el.modalSectionsStatus.textContent = 'Все изменения автоматически сохраняются в библиотеку и влияют на генерацию';
      }
    });
  }

  // Загрузка каталога секций при инициализации
  (async () => {
    try {
      const resp = await fetch('/api/library');
      if (resp.ok) {
        const data = await resp.json();
        state.sectionCatalog = data.catalog || [];
        refreshPrefSectionChips();
      }
    } catch (_) {}
  })();
  if (el.sliderStep3Floors) {
    el.sliderStep3Floors.addEventListener('input', () => {
      state.max_floors = parseInt(el.sliderStep3Floors.value, 10);
      if (el.labelStep3Floors) el.labelStep3Floors.textContent = `${state.max_floors} эт.`;
      if (el.valStep3FloorsTag) el.valStep3FloorsTag.textContent = `${state.max_floors} эт. (${state.max_floors * 3} м)`;
      if (el.step3CardFloors) el.step3CardFloors.textContent = `${state.max_floors} эт. (${state.max_floors * 3} м)`;
      triggerStep3LiveUpdate(350);
    });
    el.sliderStep3Floors.addEventListener('change', () => {
      triggerStep3LiveUpdate(0);
    });
  }
  if (el.sliderStep3Setback) {
    el.sliderStep3Setback.addEventListener('input', () => {
      state.boundary_setback = parseFloat(el.sliderStep3Setback.value);
      if (el.labelStep3Setback) el.labelStep3Setback.textContent = `${state.boundary_setback.toFixed(1)} м`;
      triggerStep3LiveUpdate(350);
    });
    el.sliderStep3Setback.addEventListener('change', () => {
      triggerStep3LiveUpdate(0);
    });
  }

  if (el.sliderStep3MaxSections) {
    el.sliderStep3MaxSections.addEventListener('input', () => {
      const val = parseInt(el.sliderStep3MaxSections.value, 10);
      state.max_sections = val;
      if (el.labelStep3MaxSections) el.labelStep3MaxSections.textContent = `${val} секций`;
      triggerStep3LiveUpdate(350);
    });
    el.sliderStep3MaxSections.addEventListener('change', () => {
      triggerStep3LiveUpdate(0);
    });
  }

  // Step 3 Left panel: Generate Layout button
  if (el.btnGenerateLayout) {
    el.btnGenerateLayout.addEventListener('click', () => {
      apiGenerateLayout();
    });
  }

  if (el.btnRunMaximize) {
    el.btnRunMaximize.addEventListener('click', () => {
      apiGenerateLayout({ gen_mode: 'maximize' });
    });
  }

  if (el.btnCalcVariants) {
    el.btnCalcVariants.addEventListener('click', () => {
      apiCalcVariants();
    });
  }

  if (el.svgCanvas) {
    el.svgCanvas.addEventListener('click', (e) => {
      if (!e.target.closest('.cad-section-poly')) {
        renderSectionInspector(null);
      }
    });
  }

  // --- STEP 3: BUILD GENERATE PAYLOAD HELPER ---
  function buildGeneratePayload(overrides = {}) {
    const payload = {
      site_mode: state.mode === 'cad' ? 'cad' : 'cadastre',
      cad_swap_xy: el.chkCadSwapXy ? !!el.chkCadSwapXy.checked : false,
      cad_query: (state.cad_query || '').trim(),
      custom_area: state.custom_area || 32000,
      override_lat: state.override_lat || 0.0,
      override_lon: state.override_lon || 0.0,
      user_has_moved_site: !!state.userHasMovedSite,
      user_has_entered_manual_coords: !!state.userHasEnteredManualCoords,
      site_rotation: state.site_rotation || 0.0,
      boundary_setback: state.boundary_setback != null ? state.boundary_setback : 6.0,
      red_line_setback: state.red_line_setback != null ? state.red_line_setback : 5.0,
      target_floors: state.max_floors || 14,
      max_building_height_m: state.max_height_m || null,
      floor_height: 3.0,
      cascade_floors: state.cascade_floors !== false,
      asymmetric_wings: state.asymmetric_wings !== false,
      car_free_courtyard: state.car_free_courtyard !== false,
      only_ground_parking: !!state.only_ground_parking,
      typology: state.typology === 'SECTIONAL' ? 'LINEAR' : (state.typology || 'AUTO'),
      courtyard_orientation: state.courtyard_orientation || 'SOUTH',
      preferred_section_ids: (state.preferred_section_ids && state.preferred_section_ids.length)
        ? state.preferred_section_ids.slice()
        : null,
      section_overrides: (() => {
        const ovr = {};
        (state.sectionCatalog || []).forEach(s => {
          ovr[s.id] = { min_floors: s.min_floors, max_floors: s.max_floors };
        });
        return ovr;
      })(),
      max_far: state.max_far || 2.5,
      max_bcr: (state.max_bcr ? state.max_bcr / 100.0 : 0.4),
      enable_red_line: state.enable_red_line || false,
      road_preset: state.road_preset || 'none',
      road_width: state.road_width || 16.0,
      road_setback: state.road_setback || 4.0,
      road_pos: state.road_pos != null ? state.road_pos : 0.5,
      road_pos_x: state.road_pos_x != null ? state.road_pos_x : 0.5,
      road_pos_y: state.road_pos_y != null ? state.road_pos_y : 0.5,
      custom_roads: state.custom_roads || [],
      max_sections: state.max_sections || 8,
      stage: 2,
      site_locked: true,
      allow_parking_in_zouit: !!state.allow_parking_in_zouit,
      allow_towers_in_mixed: state.allow_towers_in_mixed !== false,
      regional_norm_id: state.regional_norm_id || 'russia_sp42',
      surrounding_height_overrides: state.surrounding_height_overrides || {},
      insolation: {
        enabled: document.getElementById('chk-insolation-enable') ? document.getElementById('chk-insolation-enable').checked : true,
        norm_hours: parseFloat(document.getElementById('select-insolation-zone')?.value || 2.0),
        allow_intermittent: document.getElementById('chk-insolation-allow-intermittent') ? document.getElementById('chk-insolation-allow-intermittent').checked : true,
        include_surroundings: document.getElementById('chk-insolation-include-surroundings') ? document.getElementById('chk-insolation-include-surroundings').checked : true,
        default_surrounding_height: parseFloat(document.getElementById('input-insolation-surr-height')?.value || 15.0),
        grid_step_m: parseFloat(document.getElementById('select-insolation-grid-step')?.value || 3.0),
        auto_cascade_reduction: document.getElementById('chk-insolation-auto-cascade') ? document.getElementById('chk-insolation-auto-cascade').checked : true,
      },
      respect_norms: true,
      explore_angles: (overrides.gen_mode === 'maximize'),
      explore_all_typologies: false,
      gen_mode: overrides.gen_mode || 'fixed',
      ...overrides
    };

    if (state.custom_regional_norm) {
      payload.custom_regional_norm = state.custom_regional_norm;
    }

    if (state.msk_zone) payload.msk_zone = state.msk_zone;
    if (state.activeZouitZones && state.activeZouitZones.length > 0) payload.zouit_zones = state.activeZouitZones;

    if (state.mode === 'cadastre') {
      if (state.gpzu_coordinates) payload.gpzu_coordinates = state.gpzu_coordinates;
      if (state.cad_file_base64) {
        payload.cad_file_base64 = state.cad_file_base64;
        payload.cad_filename = state.cad_filename;
      }
    } else if (state.mode === 'cad') {
      payload.assigned_cad_query = (state.assigned_cad_query || state.cad_query || '').trim();
      payload.boundary_layer = state.boundary_layer || null;
      payload.red_lines_layer = state.red_lines_layer || null;
      if (state.cad_file_base64) {
        payload.cad_file_base64 = state.cad_file_base64;
        payload.cad_filename = state.cad_filename;
      }
    } else if (state.mode === 'points') {
      payload.gpzu_coordinates = state.gpzu_coordinates || '';
    }

    return Object.assign(payload, overrides);
  }

  // --- TOP-1 OPTIMIZATION PROGRESS INDICATOR ---
  let optFinishTimeout = null;

  function startOptimizationIndicator() {
    if (!el.optProgressPanel) return;
    if (optFinishTimeout) clearTimeout(optFinishTimeout);
    el.optProgressPanel.style.display = 'flex';
    el.optProgressPanel.style.opacity = '1';
    el.optProgressPanel.style.transform = 'translateY(0)';
    if (el.optBadgePct) el.optBadgePct.textContent = '0%';
    if (el.optBarFill) el.optBarFill.style.width = '4%';
    if (el.optStatusMsg) el.optStatusMsg.textContent = 'Запуск поиска: оценка сетки этажей и углов...';
    if (el.optValCount) el.optValCount.textContent = '0 / 0';
    if (el.optValGfa) el.optValGfa.textContent = '—';
    if (el.optValFloors) el.optValFloors.textContent = '—';
  }

  function updateOptimizationIndicator(data) {
    if (!data || !el.optProgressPanel) return;
    const pct = Math.max(4, Math.min(100, data.percent || 0));
    if (el.optBadgePct) el.optBadgePct.textContent = `${pct}%`;
    if (el.optBarFill) el.optBarFill.style.width = `${pct}%`;
    if (el.optStatusMsg && data.message) el.optStatusMsg.textContent = data.message;
    if (el.optValCount) el.optValCount.textContent = `${data.tested_count || data.step || 0} / ${data.total || 0}`;
    if (el.optValGfa && data.best_gfa) el.optValGfa.textContent = `${fmtNum(data.best_gfa)} м²`;
    if (el.optValFloors && data.best_floors) el.optValFloors.textContent = `${data.best_floors} эт.`;
  }

  function finishOptimizationIndicator(bestGfa, bestFloors) {
    if (!el.optProgressPanel) return;
    if (el.optBadgePct) el.optBadgePct.textContent = '100%';
    if (el.optBarFill) el.optBarFill.style.width = '100%';
    if (bestGfa && el.optValGfa) el.optValGfa.textContent = `${fmtNum(bestGfa)} м²`;
    if (bestFloors && el.optValFloors) el.optValFloors.textContent = `${bestFloors} эт.`;
    if (el.optStatusMsg) el.optStatusMsg.textContent = '✓ Оптимум по закону найден! Генплан обновлён.';
    optFinishTimeout = setTimeout(() => {
      el.optProgressPanel.style.opacity = '0';
      el.optProgressPanel.style.transform = 'translateY(-6px)';
      setTimeout(() => {
        el.optProgressPanel.style.display = 'none';
      }, 350);
    }, 2200);
  }

  // --- STEP 3: MASTERPLAN CALCULATION PROGRESS INDICATOR ---
  // ponytail: многостадийный понятный индикатор расчета без тяжелых библиотек — upgrade path: стриминг SSE шагов бэкенда
  let calcProgressInterval = null;
  let calcProgressTimeout = null;

  function setCalcProgressStage(pct, activeStep, title, subtitle) {
    const bar = document.getElementById('calc-progress-bar-fill');
    const badge = document.getElementById('calc-progress-pct-badge');
    const txtTitle = document.getElementById('canvas-loading-text');
    const txtSub = document.getElementById('canvas-loading-subtext');

    if (bar) bar.style.width = `${pct}%`;
    if (badge) badge.textContent = `${pct}%`;
    if (txtTitle && title) txtTitle.textContent = title;
    if (txtSub && subtitle) txtSub.textContent = subtitle;

    for (let i = 1; i <= 5; i++) {
      const row = document.getElementById(`calc-step-${i}`);
      if (!row) continue;
      const icon = row.querySelector('.calc-step-icon');
      row.classList.remove('done', 'active', 'pending');
      if (i < activeStep) {
        row.classList.add('done');
        if (icon) icon.textContent = '✓';
      } else if (i === activeStep) {
        row.classList.add('active');
        if (icon) icon.textContent = '⏳';
      } else {
        row.classList.add('pending');
        if (icon) icon.textContent = '○';
      }
    }
  }

  function startCalcProgressIndicator(isMaximize) {
    if (calcProgressInterval) clearInterval(calcProgressInterval);
    if (calcProgressTimeout) clearTimeout(calcProgressTimeout);

    if (el.canvasLoadingOverlay) {
      el.canvasLoadingOverlay.style.display = 'flex';
      el.canvasLoadingOverlay.style.opacity = '1';
    }

    if (isMaximize) {
      setCalcProgressStage(10, 1, 'Поиск оптимального решения...', 'Перебор этажности и конфигураций');
    } else {
      setCalcProgressStage(15, 1, 'Размещение корпусов...', 'Трассировка осей и противопожарные разрывы');
    }

    const startTime = Date.now();
    calcProgressInterval = setInterval(() => {
      const elapsed = Date.now() - startTime;
      if (elapsed < 800) {
        setCalcProgressStage(22, 1, 'Размещение корпусов...', 'Трассировка осей и противопожарные разрывы');
      } else if (elapsed < 3500) {
        const p = Math.min(65, 30 + Math.round(((elapsed - 800) / 2700) * 35));
        setCalcProgressStage(p, 2, 'Расчет инсоляции СанПиН 1.2.3685-21...', 'Трассировка солнечных лучей и калибровка этажей');
      } else if (elapsed < 6500) {
        const p = Math.min(82, 65 + Math.round(((elapsed - 3500) / 3000) * 17));
        setCalcProgressStage(p, 3, 'Влияние на окружающую застройку...', 'Анализ затенения окон и фасадов соседей');
      } else {
        const p = Math.min(89, 82 + Math.round(((elapsed - 6500) / 4000) * 7));
        setCalcProgressStage(p, 4, 'Баланс территории и парковок...', 'Расчет машиномест, озеленения и ТЭП');
      }
    }, 150);
  }

  function stopCalcProgressIndicator(success = true) {
    if (calcProgressInterval) {
      clearInterval(calcProgressInterval);
      calcProgressInterval = null;
    }
    if (success) {
      setCalcProgressStage(100, 6, '✓ Расчет завершен', 'Мастер-план и ТЭП готовы');
      calcProgressTimeout = setTimeout(() => {
        if (el.canvasLoadingOverlay) {
          el.canvasLoadingOverlay.style.opacity = '0';
          setTimeout(() => {
            el.canvasLoadingOverlay.style.display = 'none';
            el.canvasLoadingOverlay.style.opacity = '1';
          }, 200);
        }
      }, 350);
    } else {
      if (el.canvasLoadingOverlay) {
        el.canvasLoadingOverlay.style.display = 'none';
      }
    }
  }

  // --- STEP 3: API CALL TO GENERATE LAYOUT ---
  let optProgressInterval = null;

  async function apiGenerateLayout(options = {}) {
    const isMaximize = options.gen_mode === 'maximize';
    state.isGenerating = true;
    try {
      startCalcProgressIndicator(isMaximize);

      if (el.btnGenerateLayout) {
        el.btnGenerateLayout.disabled = true;
        el.btnGenerateLayout.innerHTML = '<span class="loading-spinner" style="width:13px; height:13px; border-width:2px; display:inline-block; vertical-align:middle; margin-right:6px;"></span> Идет расчет застройки...';
      }
      if (el.btnRunMaximize) {
        el.btnRunMaximize.disabled = true;
        el.btnRunMaximize.textContent = '⏳ Оптимизация по закону...';
      }

      if (isMaximize) {
        startOptimizationIndicator();
        optProgressInterval = setInterval(async () => {
          try {
            const pResp = await fetch('/api/progress');
            if (pResp.ok) {
              const pData = await pResp.json();
              updateOptimizationIndicator(pData);
            }
          } catch (_) {}
        }, 160);
      }

      const payload = buildGeneratePayload(options);

      const res = await fetch('/api/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });

      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP ${res.status}`);
      }

      const data = await res.json();

      if (optProgressInterval) clearInterval(optProgressInterval);
      if (calcProgressInterval) {
        clearInterval(calcProgressInterval);
        calcProgressInterval = null;
      }

      // Переключаем на шаг 5 только после реального получения данных от сервера
      setCalcProgressStage(95, 5, 'Сборка 3D-модели...', 'Генерация фасадов и визуализация');

      renderGeneratedLayout(data);
      setCanvasView('3d');

      if (isMaximize) {
        const bestGfa = (data && data.tep) ? data.tep.gfa : null;
        const bestFloors = (data && data.buildings && data.buildings.length)
          ? Math.max(...data.buildings.map(b => b.floors || 0))
          : null;
        finishOptimizationIndicator(bestGfa, bestFloors);
      }

      setTimeout(() => {
        stopCalcProgressIndicator(true);
      }, 250);
    } catch (err) {
      if (optProgressInterval) clearInterval(optProgressInterval);
      if (el.optProgressPanel) el.optProgressPanel.style.display = 'none';
      stopCalcProgressIndicator(false);
      console.error('Error generating layout:', err);
      alert('Ошибка при расчете застройки: ' + err.message);
    } finally {
      state.isGenerating = false;
      if (el.btnGenerateLayout) {
        el.btnGenerateLayout.disabled = false;
        el.btnGenerateLayout.innerHTML = '⚡ Пересчитать застройку';
      }
      if (el.btnRunMaximize) {
        el.btnRunMaximize.disabled = false;
        el.btnRunMaximize.textContent = '⚡ Выжать максимум по закону (Top-1)';
      }
    }
  }

  // --- STEP 3: API CALL TO COMPUTE VARIANTS MATRIX ---
  async function apiCalcVariants() {
    try {
      if (el.btnCalcVariants) {
        el.btnCalcVariants.disabled = true;
        el.btnCalcVariants.innerHTML = '<span class="loading-spinner" style="width:11px; height:11px; border-width:2px; display:inline-block; vertical-align:middle; margin-right:4px;"></span> Расчет...';
      }
      const payload = buildGeneratePayload();
      const res = await fetch('/api/variants', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (!res.ok) {
        const errData = await res.json().catch(() => ({}));
        throw new Error(errData.error || `HTTP ${res.status}`);
      }
      const data = await res.json();
      if (data.variants && data.variants.length > 0) {
        state.lastVariantsMatrix = data.variants;
        renderVariantsMatrix(data.variants);
      }
    } catch (err) {
      console.error('Error computing variants:', err);
      alert('Ошибка расчета матрицы вариантов: ' + err.message);
    } finally {
      if (el.btnCalcVariants) {
        el.btnCalcVariants.disabled = false;
        el.btnCalcVariants.innerHTML = '⚡ Рассчитать';
      }
    }
  }

  // --- STEP 3: RENDER VARIANTS MATRIX ---
  function renderVariantsMatrix(variants) {
    if (!el.tbodyVariantsMatrix) return;
    if (!variants || !variants.length) {
      el.tbodyVariantsMatrix.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 12px;">Нажмите «⚡ Рассчитать» для анализа этажей</td></tr>';
      return;
    }
    const currentFloors = (state.currentScenario && state.currentScenario.floors) || state.max_floors || 14;
    el.tbodyVariantsMatrix.innerHTML = variants.map(v => {
      const isActive = (v.floors === currentFloors);
      const okBadge = v.normative_ok 
        ? '<span style="color:#10b981; font-weight:600;">✅ В норме</span>' 
        : '<span style="color:#ef4444; font-weight:600;">⚠️ Превыш.</span>';
      const actionHtml = isActive
        ? '<span style="background:#10b981; color:#fff; font-size:10px; font-weight:700; padding:2px 6px; border-radius:3px;">Выбран</span>'
        : `<button type="button" class="angle-btn btn-pick-variant" data-floors="${v.floors}" style="font-size:10px; padding:2px 6px;">Выбрать</button>`;

      return `
        <tr class="clickable-row ${isActive ? 'active-scenario-row' : ''}" data-floors="${v.floors}" style="border-bottom:1px solid var(--border-default);">
          <td style="padding:5px 6px; font-weight:700; color:${isActive ? 'var(--accent)' : 'inherit'};">${v.floors} эт.</td>
          <td style="padding:5px 6px; text-align:right; font-variant-numeric:tabular-nums;">${fmtNum(v.gfa)}</td>
          <td style="padding:5px 6px; text-align:right; font-variant-numeric:tabular-nums;">${v.far != null ? v.far : '—'}</td>
          <td style="padding:5px 6px; text-align:right; font-variant-numeric:tabular-nums;">${v.bcr != null ? v.bcr + '%' : '—'}</td>
          <td style="padding:5px 6px; text-align:center;">${okBadge}</td>
          <td style="padding:5px 6px; text-align:right;">${actionHtml}</td>
        </tr>
      `;
    }).join('');

    el.tbodyVariantsMatrix.querySelectorAll('tr[data-floors]').forEach(tr => {
      tr.addEventListener('click', () => {
        const fl = parseInt(tr.dataset.floors, 10);
        if (!fl || fl === state.max_floors) return;
        state.max_floors = fl;
        if (el.sliderStep3Floors) el.sliderStep3Floors.value = fl;
        if (el.labelStep3Floors) el.labelStep3Floors.textContent = `${fl} эт.`;
        if (el.valStep3FloorsTag) el.valStep3FloorsTag.textContent = `${fl} эт.`;
        apiGenerateLayout();
      });
    });
  }

  // --- 3D SCENARIO VARIANTS DOCK ---
  // ponytail: компактный переключатель сценариев в 3D без громоздких оберток — upgrade path: поддержка анимации камеры при смене сценария
  function render3dScenariosDock(scenarios, activeIdx = 0) {
    if (!el.dock3dScenarios || !el.dockScenarioButtons) return;
    if (!scenarios || scenarios.length <= 1) {
      el.dock3dScenarios.style.display = 'none';
      return;
    }
    el.dock3dScenarios.style.display = 'flex';
    el.dockScenarioButtons.innerHTML = scenarios.map((v, i) => {
      const isActive = (i === activeIdx);
      const fl = v.floors || (v.tep && v.tep.max_floors) || state.max_floors || 14;
      const gfa = v.tep ? (v.tep.gfa || v.tep.total_gfa) : (v.gfa || 0);
      const isNormOk = v.normative_ok !== false && (!v.norm_checks || Object.values(v.norm_checks).every(c => c.ok !== false));
      const statusText = isNormOk ? 'В норме' : 'Превышение норматива';
      const titleAttr = `Вариант ${i + 1}: GFA ${fmtNum(gfa)} м² (${statusText})`;
      return `<button type="button" class="dock-variant-btn ${isActive ? 'active' : ''}" data-idx="${i}" title="${escapeHtml(titleAttr)}">Вариант ${i + 1}</button>`;
    }).join('');

    el.dockScenarioButtons.querySelectorAll('.dock-variant-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        const idx = parseInt(btn.dataset.idx, 10);
        switchScenarioVariant(idx);
      });
    });
  }

  function update3dScenariosDockActive(activeIdx) {
    if (!el.dockScenarioButtons) return;
    el.dockScenarioButtons.querySelectorAll('.dock-variant-btn').forEach(btn => {
      const idx = parseInt(btn.dataset.idx, 10);
      btn.classList.toggle('active', idx === activeIdx);
    });
  }

  function switchScenarioVariant(idx) {
    if (!state.currentScenarios || !state.currentScenarios[idx]) return;
    state.activeVariantIndex = idx;
    const targetScenario = state.currentScenarios[idx];

    // Рендерим выбранный сценарий (флаг true предотвращает перезапись state.currentScenarios)
    renderGeneratedLayout(targetScenario, true);

    // Обновляем визуальный активный статус кнопок в доке
    update3dScenariosDockActive(idx);

    // Синхронизируем строку матрицы этажности справа, если матрица была рассчитана
    if (state.lastVariantsMatrix) {
      renderVariantsMatrix(state.lastVariantsMatrix);
    }

    // Сохраняем активный вариант на сервере для экспортов (DXF, 3D, отчет)
    fetch('/api/activate-variant', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ index: idx })
    }).catch(err => console.warn('Не удалось активировать сценарий на сервере:', err));
  }

  // --- STEP 3: RENDER APARTMENTS BREAKDOWN ---
  function renderApartmentsBreakdown(buildings) {
    if (!el.tbodyApartmentsBreakdown) return;
    if (!buildings || !buildings.length) {
      el.tbodyApartmentsBreakdown.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 12px;">—</td></tr>';
      return;
    }
    el.tbodyApartmentsBreakdown.innerHTML = buildings.map(b => {
      const ap = b.apartments || {};
      return `
        <tr style="border-bottom: 1px solid var(--border-default);">
          <td style="padding: 5px 6px; font-weight: 600; color: var(--text-primary);">${escapeHtml(b.name || b.id)}</td>
          <td style="padding: 5px 6px; text-align: center; font-variant-numeric: tabular-nums;">${ap.studio || 0}</td>
          <td style="padding: 5px 6px; text-align: center; font-variant-numeric: tabular-nums;">${ap['1k'] || 0}</td>
          <td style="padding: 5px 6px; text-align: center; font-variant-numeric: tabular-nums;">${ap['2k'] || 0}</td>
          <td style="padding: 5px 6px; text-align: center; font-variant-numeric: tabular-nums;">${ap['3k'] || 0}</td>
          <td style="padding: 5px 6px; text-align: right; font-variant-numeric: tabular-nums; font-weight: 700; color: var(--accent);">${fmtNum(b.apartments_total || 0)}</td>
        </tr>
      `;
    }).join('');
  }

  // --- STEP 3: RENDER SANITARY & TKO ---
  function renderSanitaryAndTko(sanitary) {
    if (!sanitary) return;
    const ws = sanitary.waste_sites || [];
    const tCount = ws.length;
    const cCount = sanitary.total_containers || ws.reduce((acc, s) => acc + (s.containers || 0), 0);

    if (el.tepSanTko) {
      el.tepSanTko.textContent = tCount > 0 ? `${tCount} площ. (${cCount} баков)` : '— площ.';
    }
    if (el.badgeSanStatus) {
      const ok = sanitary.waste_is_compliant !== false && sanitary.parking_is_compliant !== false;
      el.badgeSanStatus.className = ok ? 'badge-status badge-ok' : 'badge-status badge-warn';
      el.badgeSanStatus.textContent = ok ? 'В норме' : 'Отклонение';
    }
    if (el.tepSanBuffer) {
      const dist = sanitary.min_parking_distance_to_windows_m;
      el.tepSanBuffer.textContent = (dist != null && dist > 0) ? `${dist.toFixed(1)} м (норма ≥10м)` : '10–15 м';
    }

    if (el.svgParkingSanLayer) {
      const pPath = sanitary.parking_buffer_10m_path || sanitary.parking_buffer_15m_path;
      if (pPath) {
        el.svgParkingSanLayer.innerHTML = `<path d="${pPath}" class="svg-parking-san-buffer"><title>Санитарный разрыв от стоянок до окон (СанПиН 2.1.3684)</title></path>`;
      } else {
        el.svgParkingSanLayer.innerHTML = '';
      }
    }

    if (el.svgTkoLayer) {
      let tkoMarkup = '';
      (sanitary.waste_radius_paths || []).forEach(rPath => {
        tkoMarkup += `<path d="${rPath}" class="svg-tko-radius" />`;
      });
      ws.forEach(s => {
        if (s.path) {
          tkoMarkup += `<path d="${s.path}" class="svg-tko-site"><title>Площадка ТКО: ${s.containers || 4} конт. (от окон ${s.distance_to_windows ? s.distance_to_windows.toFixed(1) + 'м' : '≥20м'}, радиус 100м)</title></path>`;
        }
      });
      el.svgTkoLayer.innerHTML = tkoMarkup;
    }
  }

  // --- STEP 3: RENDER INSOLATION RESULTS (САНПИН 1.2.3685-21) ---
  function renderInsolationResults(insol) {
    const rateEl = document.getElementById('insolation-stat-rate');
    const tepRateEl = document.getElementById('tep-insol-pct');
    const ptsEl = document.getElementById('insolation-stat-pts');
    const badgeCalc = document.getElementById('badge-insolation-calc-status');
    const badgeRight = document.getElementById('badge-insol-status');
    const descEl = document.getElementById('insolation-stat-desc');
    const normEl = document.getElementById('tep-insol-norm');
    const dateEl = document.getElementById('tep-insol-date');
    const surrEl = document.getElementById('tep-insol-surr');
    const contEl = document.getElementById('insolation-stat-cont');
    const intermEl = document.getElementById('insolation-stat-interm');
    const tepIntermEl = document.getElementById('tep-insol-interm');
    const tepSurrImpactEl = document.getElementById('tep-insol-surr-impact');

    const badgeSurrImpact = document.getElementById('badge-surr-impact-status');
    const descSurrImpact = document.getElementById('surr-impact-desc');
    const wrapSurrImpact = document.getElementById('surr-impact-table-wrap');
    const tbodySurrImpact = document.getElementById('surr-impact-tbody');

    if (!insol || insol.compliance_rate_percent == null) {
      if (rateEl) rateEl.textContent = '— %';
      if (tepRateEl) tepRateEl.textContent = '— %';
      if (ptsEl) ptsEl.textContent = '—';
      if (contEl) contEl.textContent = 'Непрерывно (≥2ч): —';
      if (intermEl) intermEl.textContent = 'Прерывисто: —';
      if (tepIntermEl) tepIntermEl.textContent = '—';
      if (tepSurrImpactEl) tepSurrImpactEl.textContent = '—';
      if (badgeCalc) {
        badgeCalc.textContent = 'Не рассчитано';
        badgeCalc.className = 'badge-status';
      }
      if (badgeRight) {
        badgeRight.textContent = '—';
        badgeRight.className = 'badge-status';
      }
      if (wrapSurrImpact) wrapSurrImpact.style.display = 'none';
      return;
    }

    const rate = insol.compliance_rate_percent;
    const isOk = !!insol.sanpin_compliant;
    const reqH = insol.required_hours || 2.0;
    const contPts = insol.continuous_compliant_points || 0;
    const intermPts = insol.intermittent_compliant_points || 0;
    const totalPts = insol.total_facade_points || 0;

    if (rateEl) {
      rateEl.textContent = `${rate}%`;
      rateEl.style.color = isOk ? 'var(--success)' : 'var(--danger)';
    }
    if (tepRateEl) {
      tepRateEl.textContent = `${rate}%`;
      tepRateEl.style.color = isOk ? 'var(--success)' : 'var(--danger)';
    }
    if (ptsEl) {
      ptsEl.textContent = `${insol.compliant_points || 0} / ${totalPts}`;
    }
    if (contEl) {
      contEl.textContent = `Непрерывно (≥${reqH}ч): ${contPts} яч.`;
    }
    if (intermEl) {
      intermEl.textContent = `Прерывисто: ${intermPts} яч.`;
    }
    if (tepIntermEl) {
      const pct = totalPts > 0 ? ((intermPts / totalPts) * 100).toFixed(0) : '0';
      tepIntermEl.textContent = `${intermPts} яч. (${pct}%)`;
    }

    if (badgeCalc) {
      badgeCalc.textContent = isOk ? 'Норма выполнена' : 'Есть дефицит';
      badgeCalc.className = isOk ? 'badge-status badge-ok' : 'badge-status badge-warn';
    }
    if (badgeRight) {
      badgeRight.textContent = isOk ? 'В норме' : 'Внимание';
      badgeRight.className = isOk ? 'badge-status badge-ok' : 'badge-status badge-warn';
    }
    if (normEl) {
      normEl.textContent = `≥ ${reqH.toFixed(1)} ч (или прерыв. ≥ 2.5 ч)`;
    }
    if (dateEl && insol.calculation_date) {
      dateEl.textContent = insol.calculation_date;
    }
    if (surrEl) {
      surrEl.textContent = 'Учтено (OSM)';
    }
    if (descEl) {
      if (isOk) {
        descEl.innerHTML = `<span style="color:var(--success); font-weight:600;">✓ Требования СанПиН 1.2.3685-21 выполнены.</span> Непрерывная или прерывистая норма обеспечена на ${rate}% фасадов (${contPts} непрер. + ${intermPts} прерыв.).`;
      } else {
        descEl.innerHTML = `<span style="color:var(--danger); font-weight:600;">⚠ Теневой дефицит:</span> ${Number(100 - rate).toFixed(1)}% фасадов затенены. Применено каскадное понижение южных крыльев.`;
      }
    }

    // Влияние на окружающую застройку (затенение соседних домов)
    const surrImpact = insol.surrounding_impact;
    if (surrImpact) {
      const isSurrOk = surrImpact.sanpin_surroundings_compliant !== false && (surrImpact.critical_violations_count || 0) === 0;
      if (tepSurrImpactEl) {
        tepSurrImpactEl.textContent = isSurrOk ? 'Норма соблюдена' : `Дефицит (${surrImpact.critical_violations_count} тчк)`;
        tepSurrImpactEl.style.color = isSurrOk ? 'var(--success)' : 'var(--danger)';
      }
      if (badgeSurrImpact) {
        badgeSurrImpact.textContent = isSurrOk ? 'Норма соблюдена' : 'Есть дефицит';
        badgeSurrImpact.className = isSurrOk ? 'badge-status badge-ok' : 'badge-status badge-warn';
      }
      if (descSurrImpact && surrImpact.summary_text) {
        descSurrImpact.textContent = surrImpact.summary_text;
      }
      if (tbodySurrImpact && surrImpact.buildings && surrImpact.buildings.length > 0) {
        tbodySurrImpact.innerHTML = surrImpact.buildings.map(b => {
          const isCrit = b.sanpin_status === 'CRITICAL_DEFICIT';
          const isShaded = b.is_shaded_by_project;
          const statBadge = isCrit
            ? '<span style="color:#ef4444;font-weight:700;">Дефицит</span>'
            : isShaded
              ? '<span style="color:#f59e0b;font-weight:600;">Тень</span>'
              : '<span style="color:#10b981;">Норма</span>';
          const ovrMark = b.is_overridden ? ' <span title="Высота изменена вручную">✏️</span>' : '';
          return `
            <tr>
              <td style="padding:4px 6px;max-width:110px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${b.name || b.id}">${b.name || b.id}${ovrMark}</td>
              <td style="padding:4px 6px;text-align:right;">${b.height_m}м (${b.levels}эт)</td>
              <td style="padding:4px 6px;text-align:right;color:${b.delta_hours < -0.1 ? '#ef4444' : 'inherit'};font-family:var(--font-mono);">${b.delta_hours > 0 ? '+' : ''}${b.delta_hours}ч</td>
              <td style="padding:4px 6px;text-align:center;">${statBadge}</td>
            </tr>
          `;
        }).join('');
        if (wrapSurrImpact) wrapSurrImpact.style.display = 'block';
      } else if (wrapSurrImpact) {
        wrapSurrImpact.style.display = 'none';
      }
    } else {
      if (tepSurrImpactEl) {
        tepSurrImpactEl.textContent = 'Норма соблюдена';
        tepSurrImpactEl.style.color = 'var(--success)';
      }
      if (wrapSurrImpact) wrapSurrImpact.style.display = 'none';
    }
  }

  // --- STEP 3: SECTION INSPECTOR ---
  function renderSectionInspector(secId) {
    if (!el.sectionInspectorCard) return;

    if (!secId || state.selectedSectionId === secId) {
      state.selectedSectionId = null;
      el.sectionInspectorCard.style.display = 'none';
      if (el.svgSectionsLayer) {
        el.svgSectionsLayer.querySelectorAll('.cad-section-poly').forEach(p => p.classList.remove('selected-section'));
      }
      return;
    }

    state.selectedSectionId = secId;
    const current = state.currentScenario || state.currentData;
    const sec = (current && current.sections) ? current.sections.find(s => s.id === secId || s.type_id === secId) : null;

    if (!sec) {
      el.sectionInspectorCard.style.display = 'none';
      return;
    }

    if (el.inspSecTitle) el.inspSecTitle.textContent = `${sec.building_name || 'Корпус'} · ${sec.label || 'Секция'}`;
    if (el.inspSecCategory) el.inspSecCategory.textContent = sec.category_label || sec.category || 'Секция';
    if (el.inspSecBuilding) el.inspSecBuilding.textContent = sec.building_name || '—';
    if (el.inspSecType) el.inspSecType.textContent = `${sec.type_name || ''} (${sec.type_id || ''})`;
    const catSec = (state.sectionCatalog || []).find(c => c.id === (sec.type_id || sec.id) || c.code === (sec.type_name || ''));
    const rangeText = catSec ? ` [лимит: ${catSec.min_floors}–${catSec.max_floors} эт.]` : '';
    if (el.inspSecFloors) el.inspSecFloors.textContent = `${sec.floors} эт. (${sec.height_m || (sec.floors * 3.0).toFixed(1)} м)${rangeText}`;
    if (el.inspSecGfa) {
      const liv = sec.residential_area || Math.round((sec.gfa || 0) * 0.7);
      el.inspSecGfa.textContent = `${fmtNum(sec.gfa || 0)} м² (жил. ~${fmtNum(liv)} м²)`;
    }
    if (el.inspSecApts) el.inspSecApts.textContent = `${sec.apartments_total || 0} квартир`;
    if (el.inspSecBreakdown) {
      const ap = sec.apartments || {};
      el.inspSecBreakdown.textContent = `Ст: ${ap.studio || 0} · 1к: ${ap['1k'] || 0} · 2к: ${ap['2k'] || 0} · 3к: ${ap['3k'] || 0}`;
    }
    if (el.inspSecGround) {
      el.inspSecGround.textContent = sec.commercial_ground ? 'Коммерция / стрит-ритейл' : 'Жилой этаж';
    }

    el.sectionInspectorCard.style.display = 'block';

    if (el.svgSectionsLayer) {
      el.svgSectionsLayer.querySelectorAll('.cad-section-poly').forEach(p => {
        p.classList.toggle('selected-section', p.dataset.secId === secId);
      });
    }
  }

  // --- STEP 3: RENDER GENERATED 2D/3D LAYOUT & TEP ---
  function renderGeneratedLayout(data, isVariantSwitch = false) {
    if (!data) return;
    state.currentScenario = data;

    if (!isVariantSwitch) {
      state.currentScenarios = (data.variants && data.variants.length > 0) ? data.variants : [data];
      state.activeVariantIndex = data.active_variant_index || 0;
      render3dScenariosDock(state.currentScenarios, state.activeVariantIndex);
      if (!state.lastVariantsMatrix && el.tbodyVariantsMatrix) {
        el.tbodyVariantsMatrix.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 12px;">Нажмите «⚡ Рассчитать» для анализа этажей</td></tr>';
      }
    } else {
      update3dScenariosDockActive(state.activeVariantIndex);
    }

    // 1. Update verification card
    const bCount = (data.buildings || []).length;
    const sCount = (data.sections || []).length;
    if (el.verifBuildingsCount) el.verifBuildingsCount.textContent = bCount;
    if (el.verifSectionsCount) el.verifSectionsCount.textContent = sCount;
    if (el.valBuildingsCountBadge) el.valBuildingsCountBadge.textContent = `${bCount} корпусов`;

    // 2. Typology Badge
    const typNames = { SECTIONAL: 'Секционная', TOWERS: 'Башенная', PERIMETER: 'Периметральная', MIXED: 'Смешанная' };
    if (el.valTepTypologyBadge) el.valTepTypologyBadge.textContent = typNames[data.typology] || data.typology || 'Секционная';

    // 3. TEP Passport Table
    const tep = data.tep || {};
    if (el.tepGfa) el.tepGfa.textContent = tep.gfa ? `${fmtNum(tep.gfa)} м²` : '—';
    if (el.tepLiving) el.tepLiving.textContent = tep.residential_area ? `${fmtNum(tep.residential_area)} м²` : '—';
    if (el.tepComm) el.tepComm.textContent = tep.commercial_area ? `${fmtNum(tep.commercial_area)} м²` : '—';
    if (el.tepFar) el.tepFar.textContent = tep.far != null ? tep.far.toFixed(2) : '—';
    if (el.tepBcr) el.tepBcr.textContent = tep.bcr != null ? `${(tep.bcr * 100).toFixed(1)}%` : '—';
    if (el.tepFootprint) el.tepFootprint.textContent = tep.building_area ? `${fmtNum(tep.building_area)} м²` : '—';

    // 4. Social & Inhabitants
    if (el.tepPop) el.tepPop.textContent = tep.population ? `${fmtNum(Math.round(tep.population))} чел.` : '—';
    if (el.tepApts) el.tepApts.textContent = tep.apartments_total ? `${fmtNum(tep.apartments_total)} шт.` : '—';

    // 5. Parking & Infrastructure
    if (el.tepParkingReq) el.tepParkingReq.textContent = tep.parking_required ? `${fmtNum(tep.parking_required)} м/м` : '—';
    if (el.tepParkingGround) el.tepParkingGround.textContent = tep.parking_ground ? `${fmtNum(tep.parking_ground)} м/м` : '—';
    if (el.tepParkingUnderground) {
      if (tep.only_ground_parking || state.only_ground_parking) {
        el.tepParkingUnderground.innerHTML = '<span style="color:var(--text-muted); font-size:11px;">0 м/м (исключен)</span>';
      } else {
        el.tepParkingUnderground.textContent = tep.parking_underground ? `${fmtNum(tep.parking_underground)} м/м` : '0 м/м';
      }
    }
    if (el.tepParkingTotal) el.tepParkingTotal.textContent = (tep.parking_ground || 0) + (tep.parking_underground || 0) ? `${fmtNum((tep.parking_ground || 0) + (tep.parking_underground || 0))} м/м` : '—';

    if (el.tepGreenFact) el.tepGreenFact.textContent = tep.green_area ? `${fmtNum(tep.green_area)} м²` : '—';
    if (el.tepPlayChildren) el.tepPlayChildren.textContent = tep.playgrounds_children ? `${fmtNum(tep.playgrounds_children)} м²` : '—';
    if (el.tepPlaySport) el.tepPlaySport.textContent = tep.playgrounds_sport ? `${fmtNum(tep.playgrounds_sport)} м²` : '—';
    if (el.tepPlayRelax) el.tepPlayRelax.textContent = tep.playgrounds_relax ? `${fmtNum(tep.playgrounds_relax)} м²` : '—';

    // 6. Buildings Explication Table
    if (el.tbodyBuildingsExplication) {
      if (data.buildings && data.buildings.length > 0) {
        el.tbodyBuildingsExplication.innerHTML = data.buildings.map(b => `
          <tr style="border-bottom: 1px solid var(--border-default); transition: background 0.15s;" onmouseover="this.style.background='var(--bg-surface-hover)'" onmouseout="this.style.background='transparent'">
            <td style="padding: 6px 8px; font-weight: 600; color: var(--text-primary); display: flex; align-items: center; gap: 6px;">
              <span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:#38bdf8;"></span>
              ${escapeHtml(b.name || b.id)}
            </td>
            <td style="padding: 6px 8px; text-align: center; color: var(--accent); font-weight: 600;">${b.floors} эт.</td>
            <td style="padding: 6px 8px; text-align: right; font-variant-numeric: tabular-nums;">${fmtNum(b.total_gfa || 0)}</td>
            <td style="padding: 6px 8px; text-align: right; font-variant-numeric: tabular-nums; font-weight: 600;">${fmtNum(b.apartments_total || 0)}</td>
          </tr>
        `).join('');
      } else {
        el.tbodyBuildingsExplication.innerHTML = '<tr><td colspan="4" style="text-align: center; color: var(--text-muted); padding: 12px;">Застройка не сгенерирована</td></tr>';
      }
    }

    // 6.5 Render Road Network & Sub-blocks from generation result
    const roads = data.roads;
    if (el.svgRoadCorridorLayer) {
      let cMarkup = '';
      if (roads && roads.corridor_path) {
        cMarkup = `<path id="cad-roads-corridor" d="${roads.corridor_path}" fill="rgba(30, 41, 59, 0.75)" stroke="#475569" stroke-width="1.5" />`;
      }
      el.svgRoadCorridorLayer.innerHTML = cMarkup;
    }

    if (el.svgRoadBufferLayer) {
      let bufMarkup = '';
      if (roads && roads.buffer_path) {
        bufMarkup = `<path id="cad-roads-buffer" d="${roads.buffer_path}" fill="rgba(245, 158, 11, 0.06)" stroke="#f59e0b" stroke-width="1.2" stroke-dasharray="6,4" />`;
      }
      el.svgRoadBufferLayer.innerHTML = bufMarkup;
    }

    if (el.svgRoadCenterlinesLayer) {
      let clMarkup = '';
      if (roads && roads.centerlines_paths) {
        roads.centerlines_paths.forEach(p => {
          clMarkup += `<path class="cad-centerline" d="${p}" fill="none" stroke="#f8fafc" stroke-width="2" stroke-dasharray="8,5" />`;
        });
      }
      el.svgRoadCenterlinesLayer.innerHTML = clMarkup;
    }

    if (el.svgSubBlocksLayer) {
      let sbMarkup = '';
      if (roads && roads.sub_blocks_data && roads.sub_blocks_data.length > 0) {
        roads.sub_blocks_data.forEach(b => {
          sbMarkup += `<path class="sub-block-poly" data-block-idx="${b.index}" d="${b.path}" fill="rgba(16, 185, 129, 0.12)" stroke="#10b981" stroke-width="2" />`;
          if (b.centroid_svg && b.centroid_svg.length >= 2) {
            sbMarkup += `
              <g class="sub-block-badge" data-block-idx="${b.index}" transform="translate(${b.centroid_svg[0]}, ${b.centroid_svg[1]})" style="pointer-events: none;">
                <circle r="14" fill="#0f172a" stroke="#10b981" stroke-width="1.8" />
                <text text-anchor="middle" dy="4" fill="#10b981" font-size="11" font-weight="bold">${b.index}</text>
                <rect x="-32" y="18" width="64" height="18" rx="4" fill="#0f172a" stroke="rgba(255,255,255,0.18)" stroke-width="1" />
                <text text-anchor="middle" dy="31" fill="#f8fafc" font-size="10" font-family="monospace">${fmtNum2(b.area_ha)} га</text>
              </g>
            `;
          }
        });
      } else if (data.buildable_path) {
        sbMarkup = `<path id="cad-setback-bound" d="${data.buildable_path}" fill="rgba(16, 185, 129, 0.08)" stroke="#10b981" stroke-width="1.8" stroke-dasharray="6,4" />`;
      }
      el.svgSubBlocksLayer.innerHTML = sbMarkup;
      bindSubBlockPolyEvents();
    }

    if (el.svgRoadHandlesLayer) {
      el.svgRoadHandlesLayer.innerHTML = '';
    }
    renderEntryPointsOnSvg();

    // 7. Render 2D SVG Layers
    if (el.svgParkingLayer) {
      let pMarkup = '';
      if (data.parking_layout && data.parking_layout.bays_path) {
        pMarkup += `<path d="${data.parking_layout.bays_path}" class="cad-parking-bay" />`;
      }
      if (data.parking_layout && data.parking_layout.slots_paths) {
        data.parking_layout.slots_paths.forEach(sp => {
          pMarkup += `<path d="${sp}" stroke="rgba(255,255,255,0.4)" stroke-width="0.8" fill="none" />`;
        });
      }
      el.svgParkingLayer.innerHTML = pMarkup;
    }

    if (el.svgFireSafetyLayer) {
      let fsMarkup = '';
      if (data.fire_safety && data.fire_safety.fire_roads_path) {
        fsMarkup += `<path d="${data.fire_safety.fire_roads_path}" class="cad-fire-road" />`;
      }
      if (data.fire_safety && data.fire_safety.fire_turnarounds_path) {
        fsMarkup += `<path d="${data.fire_safety.fire_turnarounds_path}" class="cad-fire-turnaround" />`;
      }
      el.svgFireSafetyLayer.innerHTML = fsMarkup;
    }

    if (el.svgBuildingsLayer) {
      let bMarkup = '';
      if (data.buildings) {
        data.buildings.forEach(b => {
          if (b.path) {
            bMarkup += `<path class="cad-building-poly" d="${b.path}" fill="rgba(15, 23, 42, 0.85)" stroke="#0284c7" stroke-width="2.5"><title>${escapeHtml(b.name || b.id)}: ${b.floors} эт., GFA ${fmtNum(b.total_gfa || 0)} м²</title></path>`;
          }
        });
      }
      el.svgBuildingsLayer.innerHTML = bMarkup;
    }

    if (el.svgSectionsLayer) {
      let sMarkup = '';
      if (data.sections) {
        data.sections.forEach(sec => {
          if (sec.path) {
            const color = sec.category_color || '#0ea5e9';
            sMarkup += `<path class="cad-section-poly" data-sec-id="${sec.id}" d="${sec.path}" fill="${color}" fill-opacity="0.8" stroke="#ffffff" stroke-width="1.2"><title>${escapeHtml(sec.label || sec.id)}: ${sec.floors} эт., GFA ${fmtNum(sec.gfa || 0)} м², квартир ${sec.apartments_total || 0}</title></path>`;
            if (sec.cx != null && sec.cy != null) {
              sMarkup += `<text x="${sec.cx}" y="${sec.cy + 3}" text-anchor="middle" font-size="9" font-weight="700" fill="#ffffff" style="pointer-events:none; text-shadow: 0 1px 2px rgba(0,0,0,0.85);">${escapeHtml(sec.label || '')}</text>`;
            }
          }
        });
      }
      el.svgSectionsLayer.innerHTML = sMarkup;

      el.svgSectionsLayer.querySelectorAll('.cad-section-poly').forEach(p => {
        p.addEventListener('click', (e) => {
          e.stopPropagation();
          renderSectionInspector(p.dataset.secId);
        });
      });
    }

    // 8. Sanitary and TKO
    renderSanitaryAndTko(data.sanitary || {});

    // 8.5. Insolation (СанПиН 1.2.3685-21)
    renderInsolationResults(data.insolation || {});

    // 9. Apartments Breakdown & Variants Matrix Sync
    renderApartmentsBreakdown(data.buildings || []);
    if (state.lastVariantsMatrix) {
      renderVariantsMatrix(state.lastVariantsMatrix);
    }

    // 10. Update 3D Viewer iframe
    if (data.viewer_3d_data) {
      sync3dViewer(data.viewer_3d_data);
      setTimeout(() => sync3dViewer(data.viewer_3d_data), 150);
    }

    // 11. Update Leaflet Map if present
    if (data.leaflet_html && el.iframeOsm) {
      el.iframeOsm.srcdoc = data.leaflet_html;
    }

    // 12. Fit SVG viewport
    if (data.svg_viewbox) {
      fitSvgToViewport(data.svg_viewbox);
    }

    // 13. Re-apply engineering layers visibility
    applyLayerVisibility();
  }

  // --- EXPORT DOCUMENTATION HOOKS ---
  function setupExportButtons() {
    function triggerDownload(url, filename) {
      const a = document.createElement('a');
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }

    if (el.btnExportDxf) {
      el.btnExportDxf.addEventListener('click', () => {
        triggerDownload('/api/export/dxf', 'plan_cad.dxf');
      });
    }

    if (el.btnExport3d) {
      el.btnExport3d.addEventListener('click', () => {
        triggerDownload('/api/export/3d-html', 'plan_3d.html');
      });
    }

    if (el.btnExportGeojson) {
      el.btnExportGeojson.addEventListener('click', () => {
        triggerDownload('/api/export/geojson', 'plan.geojson');
      });
    }

    if (el.btnExportReport) {
      el.btnExportReport.addEventListener('click', () => {
        triggerDownload('/api/export/report', 'tep_report.txt');
      });
    }
  }

  // --- 3D VIEWER SYNCHRONIZATION ---
  function sync3dViewer(specificData = null) {
    if (!el.iframe3d) return;
    const v3dData = specificData ||
      (state.currentScenario && state.currentScenario.viewer_3d_data) ||
      (state.currentData && state.currentData.viewer_3d_data);
    if (!v3dData) return;

    try {
      if (el.iframe3d.contentWindow) {
        el.iframe3d.contentWindow.postMessage({ type: 'activate' }, '*');
        el.iframe3d.contentWindow.postMessage({ type: 'loadData', data: v3dData, basemap: 'osm' }, '*');
      }
    } catch (_) {}
  }

  // 3D Viewer Message Handler (Ready & Section Clicks & Generate Trigger & Surrounding Overrides)
  window.addEventListener('message', (e) => {
    if (!e.data) return;
    if (e.data.type === 'viewer3dReady') {
      sync3dViewer();
    } else if (e.data.type === 'requestGenerate') {
      setStep(3);
      apiGenerateLayout();
    } else if (e.data.type === 'section_click' && e.data.section_id) {
      renderSectionInspector(e.data.section_id);
    } else if (e.data.type === 'surrounding_height_override') {
      const bId = e.data.id;
      const newH = parseFloat(e.data.height);
      state.surrounding_height_overrides = state.surrounding_height_overrides || {};
      state.surrounding_height_overrides[bId] = newH;
      updateSurroundingOverridesBadge();
      if (e.data.recalculate) {
        setStep(3);
        apiGenerateLayout();
      }
    }
  });

  function updateSurroundingOverridesBadge() {
    const badgeText = document.getElementById('surr-overrides-count-text');
    const resetBtn = document.getElementById('btn-reset-surr-overrides');
    const count = Object.keys(state.surrounding_height_overrides || {}).length;
    if (badgeText) {
      badgeText.textContent = `Ручных правок высоты: ${count}`;
    }
    if (resetBtn) {
      resetBtn.style.display = count > 0 ? 'inline-block' : 'none';
    }
  }

  const btnResetSurr = document.getElementById('btn-reset-surr-overrides');
  if (btnResetSurr) {
    btnResetSurr.addEventListener('click', () => {
      state.surrounding_height_overrides = {};
      updateSurroundingOverridesBadge();
      apiGenerateLayout();
    });
  }

    // Orientation & Setbacks (Step 1)
  if (el.sliderRotation) {
    el.sliderRotation.addEventListener('input', () => {
      const val = parseFloat(el.sliderRotation.value);
      state.site_rotation = val;
      if (el.valRotation) el.valRotation.textContent = `${val > 0 ? '+' : ''}${val.toFixed(1)}°`;
      if (el.compassSvg) el.compassSvg.style.transform = `rotate(${-val}deg)`;
    });
    el.sliderRotation.addEventListener('change', () => {
      if (state.currentData) apiPreviewSite(true);
    });
  }

  el.angleBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const rot = parseFloat(btn.dataset.rot);
      state.site_rotation = rot;
      if (el.sliderRotation) el.sliderRotation.value = rot;
      if (el.valRotation) el.valRotation.textContent = `${rot > 0 ? '+' : ''}${rot.toFixed(1)}°`;
      if (el.compassSvg) el.compassSvg.style.transform = `rotate(${-rot}deg)`;
      if (state.currentData) apiPreviewSite(true);
    });
  });

  if (el.btnResetLanding) {
    el.btnResetLanding.addEventListener('click', () => {
      state.site_rotation = 0.0;
      state.override_lat = 0.0;
      state.override_lon = 0.0;
      state.userHasMovedSite = false;
      state.userHasEnteredManualCoords = false;

      if (el.sliderRotation) el.sliderRotation.value = 0;
      if (el.valRotation) el.valRotation.textContent = '0.0°';
      if (el.compassSvg) el.compassSvg.style.transform = 'rotate(0deg)';
      if (el.inputManualLat) el.inputManualLat.value = '';
      if (el.inputManualLon) el.inputManualLon.value = '';

      if (state.currentData) apiPreviewSite(true);
    });
  }

  if (el.sliderBoundarySetback) {
    el.sliderBoundarySetback.addEventListener('input', () => {
      const val = parseInt(el.sliderBoundarySetback.value, 10);
      state.boundary_setback = val;
      if (el.valBoundarySetback) el.valBoundarySetback.textContent = `${val} м`;
    });
    el.sliderBoundarySetback.addEventListener('change', () => {
      if (state.currentData) apiPreviewSite(true);
    });
  }

  if (el.sliderRedlineSetback) {
    el.sliderRedlineSetback.addEventListener('input', () => {
      const val = parseInt(el.sliderRedlineSetback.value, 10);
      state.red_line_setback = val;
      if (el.valRedlineSetback) el.valRedlineSetback.textContent = `${val} м`;
    });
    el.sliderRedlineSetback.addEventListener('change', () => {
      if (state.currentData) apiPreviewSite(true);
    });
  }

  if (el.chkRedlines) {
    el.chkRedlines.addEventListener('change', () => {
      state.enable_red_line = el.chkRedlines.checked;
      if (state.currentData) apiPreviewSite(true);
    });
  }

  if (el.chkZouit) {
    el.chkZouit.addEventListener('change', () => {
      state.zouit_active = el.chkZouit.checked;
      if (state.currentData) apiPreviewSite(true);
    });
  }

  // --- CENTER CANVAS VIEWPORT SWITCHER ---
  function setCanvasView(viewKey) {
    state.activeView = viewKey;

    if (el.tabCanvasOsm) el.tabCanvasOsm.classList.toggle('active', viewKey === 'osm');
    if (viewKey === 'osm' && el.iframeOsm && state.lastLeafletHtml && el.iframeOsm.srcdoc !== state.lastLeafletHtml) {
      el.iframeOsm.srcdoc = state.lastLeafletHtml;
    }
    if (el.tabCanvasSvg) el.tabCanvasSvg.classList.toggle('active', viewKey === 'svg');
    if (el.tabCanvas3d) el.tabCanvas3d.classList.toggle('active', viewKey === '3d');

    if (el.canvasPanes && el.canvasPanes.osm) el.canvasPanes.osm.classList.toggle('active', viewKey === 'osm');
    if (el.canvasPanes && el.canvasPanes.svg) el.canvasPanes.svg.classList.toggle('active', viewKey === 'svg');
    if (el.canvasPanes && el.canvasPanes.view3d) el.canvasPanes.view3d.classList.toggle('active', viewKey === '3d');

    if (el.cadZoomControls) {
      el.cadZoomControls.style.display = viewKey === 'svg' ? 'flex' : 'none';
    }
    if (el.canvasBasemapBar) {
      el.canvasBasemapBar.style.display = viewKey === 'svg' ? 'flex' : 'none';
    }

    if (viewKey === 'svg') {
      updateSvgBasemap();
      if (state.currentScenario || state.currentData) {
        const vb = (state.currentScenario && state.currentScenario.svg_viewbox) || (state.currentData && state.currentData.svg_viewbox) || '0 0 1000 700';
        fitSvgToViewport(vb);
      }
    }

    if (viewKey === '3d') {
      sync3dViewer();
      setTimeout(() => sync3dViewer(), 120);
      setTimeout(() => {
        try {
          if (el.iframe3d && el.iframe3d.contentWindow) {
            el.iframe3d.contentWindow.dispatchEvent(new Event("resize"));
          }
        } catch (_) {}
      }, 350);
    }
  }

  if (el.tabCanvasOsm) el.tabCanvasOsm.addEventListener('click', () => setCanvasView('osm'));
  if (el.tabCanvasSvg) el.tabCanvasSvg.addEventListener('click', () => setCanvasView('svg'));
  if (el.tabCanvas3d) el.tabCanvas3d.addEventListener('click', () => setCanvasView('3d'));

  // Canvas Basemap Switcher Handlers
  const basemapBtns = [el.btnBmOsm, el.btnBmSatellite, el.btnBmLight, el.btnBmNone].filter(Boolean);
  basemapBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      const bm = btn.dataset.basemap;
      state.activeBasemap = bm;
      basemapBtns.forEach(b => b.classList.toggle('active', b === btn));
      updateSvgBasemap();
    });
  });

  if (el.sliderBasemapOpacity) {
    el.sliderBasemapOpacity.addEventListener('input', e => {
      const val = parseInt(e.target.value, 10);
      state.basemapOpacity = val / 100.0;
      if (el.labelBasemapOpacity) el.labelBasemapOpacity.textContent = `${val}%`;
      if (el.svgBasemapLayer) {
        const tiles = el.svgBasemapLayer.querySelectorAll('.svg-basemap-tile');
        tiles.forEach(t => t.setAttribute('opacity', String(state.basemapOpacity)));
      }
    });
  }

  // SVG Pan & Zoom Handlers
  if (el.svgCanvas) {
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
      if (e.button !== 0 || state.isDrawingRoad || state.activeHandleDrag || state.isAddingEntryPoint || state.activeEntryDrag) return;
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
  }

  if (el.btnZoomIn) {
    el.btnZoomIn.addEventListener('click', () => {
      panZoom.scale *= 1.25;
      applySvgTransform();
    });
  }

  if (el.btnZoomOut) {
    el.btnZoomOut.addEventListener('click', () => {
      panZoom.scale *= 0.8;
      applySvgTransform();
    });
  }

  if (el.btnZoomReset) {
    el.btnZoomReset.addEventListener('click', () => {
      if (state.currentData) {
        fitSvgToViewport(state.currentData.svg_viewbox || '0 0 1000 700');
      }
    });
  }

  // --- THEME SWITCHER (DARK CAD / LIGHT SHADCN) ---
  const THEME_STORAGE_KEY = 'urban_tep_studio_theme';

  function applyTheme(theme) {
    const root = document.documentElement;
    const body = document.body;
    if (body) {
      if (theme === 'light') {
        body.classList.remove('dark-theme', 'dark');
        body.classList.add('radix-themes', 'light-theme', 'light');
        body.setAttribute('data-accent-color', 'slate');
      } else {
        body.classList.remove('light-theme', 'light');
        body.classList.add('radix-themes', 'dark-theme', 'dark');
        body.setAttribute('data-accent-color', 'cyan');
      }
    }
    if (theme === 'light') {
      root.setAttribute('data-theme', 'light');
      if (el.themeIcon) el.themeIcon.textContent = '🌙';
      if (el.themeLabel) el.themeLabel.textContent = 'Тёмная';
    } else {
      root.removeAttribute('data-theme');
      if (el.themeIcon) el.themeIcon.textContent = '☀️';
      if (el.themeLabel) el.themeLabel.textContent = 'Светлая';
    }
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme);
    } catch (_) {}
  }

  function initTheme() {
    let saved = 'light';
    try {
      saved = localStorage.getItem(THEME_STORAGE_KEY) || 'light';
    } catch (_) {}
    applyTheme(saved);

    if (el.btnThemeToggle) {
      el.btnThemeToggle.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
        applyTheme(current === 'light' ? 'dark' : 'light');
      });
    }
  }

  // --- STEP 3: INSOLATION UI CONTROLS & SUB-TABS ---
  function setupInsolationControls() {
    const subtabParamsBtn = document.getElementById('subtab-btn-step3-params');
    const subtabInsolBtn = document.getElementById('subtab-btn-step3-insolation');
    const subtabParamsView = document.getElementById('subtab-view-step3-params');
    const subtabInsolView = document.getElementById('subtab-view-step3-insolation');

    if (subtabParamsBtn && subtabInsolBtn) {
      subtabParamsBtn.addEventListener('click', () => {
        subtabParamsBtn.classList.add('active');
        subtabInsolBtn.classList.remove('active');
        if (subtabParamsView) subtabParamsView.style.display = 'block';
        if (subtabInsolView) subtabInsolView.style.display = 'none';
      });
      subtabInsolBtn.addEventListener('click', () => {
        subtabInsolBtn.classList.add('active');
        subtabParamsBtn.classList.remove('active');
        if (subtabParamsView) subtabParamsView.style.display = 'none';
        if (subtabInsolView) subtabInsolView.style.display = 'block';
      });
    }

    const selInsolZone = document.getElementById('select-insolation-zone');
    const badgeInsolZone = document.getElementById('badge-insolation-zone-tag');
    if (selInsolZone && badgeInsolZone) {
      selInsolZone.addEventListener('change', () => {
        const v = selInsolZone.value;
        if (v === '1.5') badgeInsolZone.textContent = '1.5 ч (Юг)';
        else if (v === '2.5') badgeInsolZone.textContent = '2.5 ч (Север)';
        else badgeInsolZone.textContent = '2.0 ч (Центр)';
      });
    }

    let isProjectInsolActive = false;
    let isSurrInsolActive = false;

    const btnOpen3dInsol = document.getElementById('btn-insolation-open-3d');
    const btnRightOpen3dInsol = document.getElementById('btn-right-show-insolation-3d');
    const btnShowSurrHeatmap = document.getElementById('btn-show-surr-heatmap-3d');

    const updateInsolButtonsUI = () => {
      if (btnOpen3dInsol) {
        if (isProjectInsolActive) {
          btnOpen3dInsol.innerHTML = '☀️ Скрыть тепловую карту проекта';
          btnOpen3dInsol.classList.add('active');
          btnOpen3dInsol.style.background = 'rgba(2, 132, 199, 0.22)';
          btnOpen3dInsol.style.borderColor = 'var(--accent)';
          btnOpen3dInsol.style.color = '#38bdf8';
        } else {
          btnOpen3dInsol.innerHTML = '☀️ Включить тепловую карту в 3D';
          btnOpen3dInsol.classList.remove('active');
          btnOpen3dInsol.style.background = '';
          btnOpen3dInsol.style.borderColor = '';
          btnOpen3dInsol.style.color = 'var(--accent)';
        }
      }
      if (btnRightOpen3dInsol) {
        if (isProjectInsolActive) {
          btnRightOpen3dInsol.innerHTML = '☀️ Скрыть тепловую карту проекта';
          btnRightOpen3dInsol.classList.add('active');
          btnRightOpen3dInsol.style.background = 'rgba(2, 132, 199, 0.22)';
          btnRightOpen3dInsol.style.borderColor = 'var(--accent)';
          btnRightOpen3dInsol.style.color = '#38bdf8';
        } else {
          btnRightOpen3dInsol.innerHTML = '☀️ Показать тепловую карту в 3D';
          btnRightOpen3dInsol.classList.remove('active');
          btnRightOpen3dInsol.style.background = '';
          btnRightOpen3dInsol.style.borderColor = '';
          btnRightOpen3dInsol.style.color = 'var(--accent)';
        }
      }
      if (btnShowSurrHeatmap) {
        if (isSurrInsolActive) {
          btnShowSurrHeatmap.innerHTML = '🏘️ Скрыть тепловую карту окружения';
          btnShowSurrHeatmap.classList.add('active');
          btnShowSurrHeatmap.style.background = 'rgba(245, 158, 11, 0.25)';
          btnShowSurrHeatmap.style.borderColor = '#f59e0b';
          btnShowSurrHeatmap.style.color = '#b45309';
          btnShowSurrHeatmap.style.fontWeight = '700';
        } else {
          btnShowSurrHeatmap.innerHTML = '☀️ Показать тепловую карту окружения в 3D';
          btnShowSurrHeatmap.classList.remove('active');
          btnShowSurrHeatmap.style.background = 'rgba(245, 158, 11, 0.08)';
          btnShowSurrHeatmap.style.borderColor = '#f59e0b';
          btnShowSurrHeatmap.style.color = '#d97706';
          btnShowSurrHeatmap.style.fontWeight = '600';
        }
      }
    };

    const syncTo3dViewer = () => {
      const tab3d = document.getElementById('tab-canvas-3d');
      if (tab3d && !tab3d.classList.contains('active')) {
        tab3d.click();
      }
      setTimeout(() => {
        if (el.iframe3d && el.iframe3d.contentWindow) {
          el.iframe3d.contentWindow.postMessage({
            type: 'toggleInsolation',
            showProject: isProjectInsolActive,
            showSurroundings: isSurrInsolActive
          }, '*');
        }
      }, 100);
    };

    const toggleProjectInsol = (e) => {
      if (e) e.preventDefault();
      isProjectInsolActive = !isProjectInsolActive;
      updateInsolButtonsUI();
      syncTo3dViewer();
    };

    const toggleSurrInsol = (e) => {
      if (e) e.preventDefault();
      isSurrInsolActive = !isSurrInsolActive;
      updateInsolButtonsUI();
      syncTo3dViewer();
    };

    if (btnOpen3dInsol) btnOpen3dInsol.addEventListener('click', toggleProjectInsol);
    if (btnRightOpen3dInsol) btnRightOpen3dInsol.addEventListener('click', toggleProjectInsol);
    if (btnShowSurrHeatmap) btnShowSurrHeatmap.addEventListener('click', toggleSurrInsol);
  }

  // --- INITIALIZATION ---
  initTheme();
  initEmptyState();
  setupExportButtons();
  setupLayerToggleButtons();
  setupInsolationControls();
})();
