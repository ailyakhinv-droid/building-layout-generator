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
    cascade_floors: true, // Каскадная форма с пониженными крыльями по СанПиН
    asymmetric_wings: true,
    variable_insolation: true,
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

    // Step 2: Custom Roads Drawing
    valCustomCount: document.getElementById('val-custom-count'),
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

    // 7. Render Custom Road Handles
    if (!isStep1) {
      renderCustomRoadHandles();
    } else {
      if (el.svgRoadHandlesLayer) el.svgRoadHandlesLayer.innerHTML = '';
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
      state.road_preset = preset;

      el.presetBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const presetLabels = {
        none: 'Без дорог',
        longitudinal: 'Продольная',
        transverse: 'Поперечная',
        cross_2x2: 'Сетка 2×2',
        custom: 'На чертеже'
      };
      if (el.valPresetBadge) el.valPresetBadge.textContent = presetLabels[preset] || preset;

      // Show/hide grid sliders vs single pos slider
      if (el.groupRoadPos && el.groupRoadPosGrid) {
        if (preset === 'cross_2x2') {
          el.groupRoadPos.style.display = 'none';
          el.groupRoadPosGrid.style.display = 'block';
        } else if (preset === 'longitudinal' || preset === 'transverse') {
          el.groupRoadPos.style.display = 'block';
          el.groupRoadPosGrid.style.display = 'none';
        } else {
          el.groupRoadPos.style.display = 'none';
          el.groupRoadPosGrid.style.display = 'none';
        }
      }

      apiPreviewSite(true);
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
      apiPreviewSite();
    });
    el.sliderRoadPos.addEventListener('change', () => {
      apiPreviewSite(true);
    });
  }

  // Dual Pos Grid Sliders (X & Y)
  function onGridPosChange() {
    const px = parseInt(el.sliderRoadPosX ? el.sliderRoadPosX.value : '50', 10);
    const py = parseInt(el.sliderRoadPosY ? el.sliderRoadPosY.value : '50', 10);
    state.road_pos_x = px / 100.0;
    state.road_pos_y = py / 100.0;
    if (el.valRoadPosXY) el.valRoadPosXY.textContent = `${px}% / ${py}%`;
    apiPreviewSite(true);
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
    if (state.custom_roads.length === 0) {
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
    if (state.activeHandleDrag) {
      state.activeHandleDrag = null;
      updateCustomRoadsUI();
      apiPreviewSite(true);
    }
  });

  // Cancel drawing on Escape
  window.addEventListener('keydown', e => {
    if (e.key === 'Escape' && state.isDrawingRoad) {
      toggleDrawingMode(false);
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
        AUTO: 'Квартальная / Смешанная (AUTO)',
        PERIMETER: 'Периметр (R2-Style)',
        TOWER: 'Башни (Towers)',
        U_SHAPE: 'П-образные дворы',
        SECTIONAL: 'Секционная'
      };
      if (el.valTypologyTag) el.valTypologyTag.textContent = names[typ] || typ;
    });
  });

  // Step 3: Принципы застройки (СанПиН инсоляция, Двор без машин, ориентация)
  if (el.chkStep3Cascade) {
    el.chkStep3Cascade.addEventListener('change', () => {
      state.cascade_floors = el.chkStep3Cascade.checked;
    });
  }
  if (el.chkStep3CarFree) {
    el.chkStep3CarFree.addEventListener('change', () => {
      state.car_free_courtyard = el.chkStep3CarFree.checked;
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
      });
    }

    if (el.chkStep3AllowZouit) {
      el.chkStep3AllowZouit.checked = !!state.allow_parking_in_zouit;
      el.chkStep3AllowZouit.addEventListener('change', () => {
        state.allow_parking_in_zouit = el.chkStep3AllowZouit.checked;
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
    });
  }
  if (el.selectStep3CourtOrient) {
    el.selectStep3CourtOrient.addEventListener('change', () => {
      state.courtyard_orientation = el.selectStep3CourtOrient.value;
    });
  }
  // --- Чипы выбора секций (preferred_section_ids: whitelist для генерации) ---
  if (el.prefSectionsContainer) {
    (async () => {
      let catalog = [];
      try {
        const resp = await fetch('/api/library');
        if (resp.ok) {
          const data = await resp.json();
          catalog = data.catalog || [];
        }
      } catch (_) {}
      const catOrder = { MIDDLE: 0, CORNER: 1, END: 2, TOWER: 3 };
      catalog
        .slice()
        .sort((a, b) => ((catOrder[a.category] ?? 9) - (catOrder[b.category] ?? 9)) || (a.width - b.width))
        .forEach(sec => {
          const chip = document.createElement('button');
          chip.type = 'button';
          chip.className = 'cat-pill';
          chip.setAttribute('data-id', sec.id);
          chip.textContent = (sec.code && sec.code !== sec.id) ? sec.code : sec.name;
          chip.title = `${sec.name}: ${sec.width}×${sec.depth} м, этажи ${sec.min_floors}–${sec.max_floors}`;
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
          });
          el.prefSectionsContainer.appendChild(chip);
        });
    })();
  }
  if (el.sliderStep3Floors) {
    el.sliderStep3Floors.addEventListener('input', () => {
      state.max_floors = parseInt(el.sliderStep3Floors.value, 10);
      if (el.labelStep3Floors) el.labelStep3Floors.textContent = `${state.max_floors} эт.`;
      if (el.valStep3FloorsTag) el.valStep3FloorsTag.textContent = `${state.max_floors} эт. (${state.max_floors * 3} м)`;
      if (el.step3CardFloors) el.step3CardFloors.textContent = `${state.max_floors} эт. (${state.max_floors * 3} м)`;
    });
  }
  if (el.sliderStep3Setback) {
    el.sliderStep3Setback.addEventListener('input', () => {
      state.boundary_setback = parseFloat(el.sliderStep3Setback.value);
      if (el.labelStep3Setback) el.labelStep3Setback.textContent = `${state.boundary_setback.toFixed(1)} м`;
    });
  }

  if (el.sliderStep3MaxSections) {
    el.sliderStep3MaxSections.addEventListener('input', () => {
      const val = parseInt(el.sliderStep3MaxSections.value, 10);
      state.max_sections = val;
      if (el.labelStep3MaxSections) el.labelStep3MaxSections.textContent = `${val} секций`;
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
      floor_height: 3.0,
      cascade_floors: state.cascade_floors !== false,
      asymmetric_wings: state.asymmetric_wings !== false,
      car_free_courtyard: state.car_free_courtyard !== false,
      only_ground_parking: !!state.only_ground_parking,
      typology: state.typology || 'AUTO',
      courtyard_orientation: state.courtyard_orientation || 'SOUTH',
      preferred_section_ids: (state.preferred_section_ids && state.preferred_section_ids.length)
        ? state.preferred_section_ids.slice()
        : null,
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

  // --- STEP 3: API CALL TO GENERATE LAYOUT ---
  let optProgressInterval = null;

  async function apiGenerateLayout(options = {}) {
    const isMaximize = options.gen_mode === 'maximize';
    state.isGenerating = true;
    try {
      if (el.canvasLoadingOverlay) {
        el.canvasLoadingOverlay.style.display = 'flex';
        if (el.canvasLoadingText) {
          el.canvasLoadingText.textContent = isMaximize 
            ? '⚡ Оптимизация Top-1: подбор лучшей сетки углов и этажей по СП 42...' 
            : 'Расчет застройки, инсоляции и ТЭП...';
        }
      }
      if (el.btnGenerateLayout) el.btnGenerateLayout.disabled = true;
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
      if (isMaximize) {
        const bestGfa = (data && data.tep) ? data.tep.gfa : null;
        const bestFloors = (data && data.buildings && data.buildings.length)
          ? Math.max(...data.buildings.map(b => b.floors || 0))
          : null;
        finishOptimizationIndicator(bestGfa, bestFloors);
      }

      renderGeneratedLayout(data);
      setCanvasView('3d');
    } catch (err) {
      if (optProgressInterval) clearInterval(optProgressInterval);
      if (el.optProgressPanel) el.optProgressPanel.style.display = 'none';
      console.error('Error generating layout:', err);
      alert('Ошибка при расчете застройки: ' + err.message);
    } finally {
      state.isGenerating = false;
      if (el.canvasLoadingOverlay) el.canvasLoadingOverlay.style.display = 'none';
      if (el.btnGenerateLayout) {
        el.btnGenerateLayout.disabled = false;
        el.btnGenerateLayout.textContent = '⚡ Пересчитать застройку';
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
        el.btnCalcVariants.textContent = '⏳ Расчет...';
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
        renderVariantsMatrix(data.variants);
      }
    } catch (err) {
      console.error('Error computing variants:', err);
      alert('Ошибка расчета матрицы вариантов: ' + err.message);
    } finally {
      if (el.btnCalcVariants) {
        el.btnCalcVariants.disabled = false;
        el.btnCalcVariants.textContent = '⚡ Рассчитать';
      }
    }
  }

  // --- STEP 3: RENDER VARIANTS MATRIX ---
  function renderVariantsMatrix(variants) {
    if (!el.tbodyVariantsMatrix) return;
    if (!variants || !variants.length) {
      el.tbodyVariantsMatrix.innerHTML = '<tr><td colspan="6" style="text-align: center; color: var(--text-muted); padding: 12px;">Нажмите «Рассчитать» для матрицы сценариев</td></tr>';
      return;
    }
    const currentFloors = state.max_floors || 14;
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
    if (el.inspSecFloors) el.inspSecFloors.textContent = `${sec.floors} эт. (${sec.height_m || (sec.floors * 3.0).toFixed(1)} м)`;
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
  function renderGeneratedLayout(data) {
    if (!data) return;
    state.currentScenario = data;

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

    // 9. Variants Matrix & Apartments Breakdown
    renderVariantsMatrix(data.variants || []);
    renderApartmentsBreakdown(data.buildings || []);

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

  // 3D Viewer Message Handler (Ready & Section Clicks & Generate Trigger)
  window.addEventListener('message', (e) => {
    if (!e.data) return;
    if (e.data.type === 'viewer3dReady') {
      sync3dViewer();
    } else if (e.data.type === 'requestGenerate') {
      setStep(3);
      apiGenerateLayout();
    } else if (e.data.type === 'section_click' && e.data.section_id) {
      renderSectionInspector(e.data.section_id);
    }
  });

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

    if (viewKey === 'svg' && (state.currentScenario || state.currentData)) {
      const vb = (state.currentScenario && state.currentScenario.svg_viewbox) || (state.currentData && state.currentData.svg_viewbox) || '0 0 1000 700';
      fitSvgToViewport(vb);
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
      if (e.button !== 0 || state.isDrawingRoad || state.activeHandleDrag) return;
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
    let saved = 'dark';
    try {
      saved = localStorage.getItem(THEME_STORAGE_KEY) || 'dark';
    } catch (_) {}
    applyTheme(saved);

    if (el.btnThemeToggle) {
      el.btnThemeToggle.addEventListener('click', () => {
        const current = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
        applyTheme(current === 'light' ? 'dark' : 'light');
      });
    }
  }

  // --- INITIALIZATION ---
  initTheme();
  initEmptyState();
  setupExportButtons();
  setupLayerToggleButtons();
})();
