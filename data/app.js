/**
 * God Slayer: Abyss - 부동산 실거래가 시각화 (Unit Toggle & Search Clean Version)
 * 역할: 면적 단위 전환(평/㎡) 및 검색 결과 최적화
 */

const state = {
    map: null,
    geocoder: null,
    levelData: {}, 
    detailShards: {}, 
    overlays: [],
    tooltip: null,
    currentLevel: 0,
    selectedMonths: [],
    selectedType: 'apt',
    activeGungus: null, 
    filters: { '매매': true, '전세': true, '월세': true },
    localFilters: { '매매': true, '전세': true, '월세': true },
    globalArea: { min: 0, max: 80 },
    displayUnit: 'pyeong', // 'pyeong' | 'm2'
    hoveredItem: null,
    selectedComplex: null,
    selectedArea: null,
    searchIndex: [],
    allLoadedData: [],
    // 정비사업 레이어
    showRedev: false,
    redevZones: null,
    redevOverlays: [],
    // 겹침 마커 선택 리스트 / 반경 / 지적도
    clusterPicker: null,
    radiusOn: false,
    radiusOverlays: [],
    cadastralOn: false,
    // 주소 검색
    lastAddrQuery: null,
    lastAddrResults: [],
    searchPin: null,
    // 거리/면적 측정
    measureMode: null,           // null | 'dist' | 'area'
    curPts: [], curLine: null, curPoly: null, curOverlays: [], curAreaLabel: null,
    doneShapes: { dist: [], area: [] },
    // 현위치 / 로드뷰
    geolocOverlay: null,
    roadviewOn: false,
    rv: null, rvClient: null,
    // 지적도 모드 클릭 주소 표시 + VWorld 필지 폴리곤
    clickAddrOverlay: null,
    clickParcelPoly: null,
    // 길찾기 (출발→도착)
    routeMode: false,
    routePts: [],
    routeOverlays: [],
    // 로드뷰 위치 핀 / 조그 패드
    rvMapPin: null,
    rvPinBound: false,
    jogTimer: null,
    // 토지이용계획(용도지역) 오버레이
    landuseOn: false,
    landuseReady: false,
    // 건물연령 레이어 (VWorld 건물통합정보 폴리곤)
    bldgAgeOn: false,
    bldgAgeOverlays: [],
    bldgAgeToken: 0
};

const CONFIG = {
    ZOOM_LEVELS: { 1: 9, 2: 7, 3: 5, 4: 0 },
    TYPE_COLORS: {
        'apt': '#2563eb', 'rh': '#16a34a', 'sh': '#ef4444', 'off': '#06b6d4',
        'nrg': '#f59e0b', 'land': '#65a30d', 'silv': '#8b5cf6', 'indu': '#64748b'
    },
    // 전월세(전세/월세) 실거래가 제공되는 유형. 나머지는 국토부가 매매만 공개함.
    RENT_SUPPORTED: new Set(['apt', 'rh', 'sh', 'off']),
    // 정비사업 추진단계별 색 — 무지개색 순서 (초기 빨강 → 착공 보라)
    REDEV_STAGES: ['구역지정', '추진위', '조합설립', '건축심의', '사업시행', '관리처분', '착공'],
    REDEV_COLORS: {
        '구역지정': '#ef4444',  // 빨
        '추진위': '#f97316',    // 주
        '조합설립': '#eab308',  // 노
        '건축심의': '#22c55e',  // 초
        '사업시행': '#3b82f6',  // 파
        '관리처분': '#4338ca',  // 남
        '착공': '#a855f7'       // 보
    },
    // 노후도(경과년수) 구간별 색
    AGING_BANDS: [
        { min: 30, color: '#dc2626', label: '30년 이상' },
        { min: 20, color: '#f97316', label: '20~29년' },
        { min: 10, color: '#eab308', label: '10~19년' },
        { min: 0,  color: '#22c55e', label: '10년 미만' }
    ],
    AGING_UNKNOWN: '#9ca3af'
};

const isMobile = () => window.innerWidth <= 768;

// VWorld domain 파라미터는 '키에 등록된 도메인'과 일치해야 함 (접속 호스트와 무관 — 실측 확인).
// config.pages.js(공개 키)가 자체 도메인을 지정했으면 그대로, 아니면 로컬 키 기준 localhost.
window.VWORLD_DOMAIN = window.VWORLD_DOMAIN || 'localhost';

// 오버레이(마커·픽커·핀 등) 클릭 표시 — 지도 클릭 핸들러(로드뷰 점프 등)로 전파되지 않게
function markOverlayClick(ev) {
    if (ev && ev.stopPropagation) ev.stopPropagation();
    state.overlayClickAt = Date.now();
}

// 터치 기기: hover 범례가 없으므로, 버튼을 켤 때 범례를 잠깐(4초) 보여줌
function flashLegend(btn) {
    if (window.matchMedia('(hover: hover) and (pointer: fine)').matches) return; // 마우스 환경은 hover로 충분
    const dd = btn.parentElement ? btn.parentElement.querySelector('.map-dropdown') : null;
    if (!dd) return;
    dd.classList.add('show');
    clearTimeout(dd._flashTimer);
    dd._flashTimer = setTimeout(() => dd.classList.remove('show'), 4000);
}

// 결과 영역(data-section)은 필터 패널에서 분리된 독립 패널:
// - 모바일: 하단 시트 (30% ↔ 전체화면)
// - 데스크톱: 필터 패널 우측 플로팅 패널 (세로 공간 확보)
function placeDataSection() {
    const ds = document.getElementById('data-section');
    if (!ds) return;
    if (ds.parentElement !== document.body) document.body.appendChild(ds);
    if (isMobile()) {
        ds.classList.add('mobile-sheet');
        ds.classList.remove('desktop-float');
    } else {
        ds.classList.add('desktop-float');
        ds.classList.remove('mobile-sheet', 'expanded');
    }
}

window.onload = () => {
    if (typeof kakao !== 'undefined' && kakao.maps) {
        kakao.maps.load(() => init());
    } else {
        // SDK 로드 실패가 조용히 묻히면 "마커 안 나옴/전환 안 됨"으로만 보임 → 원인을 화면에 표시
        const banner = document.createElement('div');
        banner.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#dc2626;color:#fff;padding:12px 16px;font-size:14px;font-weight:600;text-align:center;';
        banner.textContent = '카카오맵 SDK 로드 실패: 인터넷 연결 또는 카카오 개발자 콘솔의 JavaScript 키/플랫폼 도메인(localhost:8080) 등록을 확인하세요. (F12 콘솔에서 상세 오류 확인 가능)';
        document.body.appendChild(banner);
        const statusEl = document.getElementById('status-bar');
        if (statusEl) statusEl.textContent = '오류: 지도 SDK 로드 실패';
    }
};

// VWorld 용도지역 WMS를 카카오 커스텀 타일셋으로 등록
// 카카오 타일 그리드: EPSG:5181, 원점(-30000,-60000), 해상도 2^(레벨-3) m/px (수치 검증 완료)
function initLanduseTileset() {
    if (!window.VWORLD_KEY || !kakao.maps.Tileset) return false;
    const urlFunc = (x, y, z) => {
        const span = 256 * Math.pow(2, z - 3);
        const minx = x * span - 30000;
        const miny = y * span - 60000;
        return 'https://api.vworld.kr/req/wms?SERVICE=WMS&REQUEST=GetMap&VERSION=1.3.0'
            + '&LAYERS=lt_c_uq111&STYLES=lt_c_uq111&CRS=EPSG:5181'
            + `&BBOX=${minx},${miny},${minx + span},${miny + span}`
            + '&WIDTH=256&HEIGHT=256&FORMAT=image/png&TRANSPARENT=true'
            + `&KEY=${window.VWORLD_KEY}&DOMAIN=${window.VWORLD_DOMAIN || 'localhost'}`;
    };
    kakao.maps.Tileset.add('LANDUSE', new kakao.maps.Tileset({ width: 256, height: 256, urlFunc }));
    return true;
}

async function init() {
    state.geocoder = new kakao.maps.services.Geocoder();
    const mapContainer = document.getElementById('map');
    state.map = new kakao.maps.Map(mapContainer, { center: new kakao.maps.LatLng(37.5665, 126.9780), level: 5 });
    state.landuseReady = initLanduseTileset();
    
    const zoomControl = new kakao.maps.ZoomControl();
    state.map.addControl(zoomControl, kakao.maps.ControlPosition.RIGHT);
    
    state.tooltip = new kakao.maps.CustomOverlay({ zIndex: 1000, clickable: false, xAnchor: 0.5, yAnchor: 1.5 });

    setupEventListeners();
    applyTxAvailability();
    placeDataSection();
    window.addEventListener('resize', placeDataSection);
    await renderMonthSelect();
    await loadGlobalSearchIndex();
    
    const baseSelect = document.getElementById('base-month-select');
    if (baseSelect && baseSelect.value) {
        state.selectedMonths = [baseSelect.value];
        updateMap(true);
    }
}

function setupEventListeners() {
    kakao.maps.event.addListener(state.map, 'zoom_changed', () => { state.tooltip.setMap(null); updateMap(); if (state.radiusOn) drawRadius(); if (state.bldgAgeOn) refreshBldgAge(); });
    kakao.maps.event.addListener(state.map, 'dragend', () => { if (state.currentLevel === 4) updateMap(true); if (state.radiusOn) drawRadius(); if (state.bldgAgeOn) refreshBldgAge(); });

    // 지도 클릭: 로드뷰 > 측정 > 길찾기 > 지적도(주소 표시) 순으로 처리
    // 단, 마커 등 오버레이 UI를 클릭한 직후에는 지도 클릭으로 처리하지 않음
    kakao.maps.event.addListener(state.map, 'click', (e) => {
        if (Date.now() - (state.overlayClickAt || 0) < 400) return;
        if (state.roadviewOn) { openRoadview(e.latLng); return; }
        if (state.measureMode) { onMeasureClick(e.latLng); return; }
        if (state.routeMode) { onRouteClick(e.latLng); return; }
        if (state.cadastralOn) showClickAddress(e.latLng);
    });
    kakao.maps.event.addListener(state.map, 'rightclick', () => finishMeasure());
    kakao.maps.event.addListener(state.map, 'dblclick', () => finishMeasure());
    document.addEventListener('keydown', (e) => { if (e.key === 'Escape') finishMeasure(); });
    
    const baseSelect = document.getElementById('base-month-select');
    const rangeSelect = document.getElementById('range-select');
    const updatePeriod = async () => {
        const baseIdx = baseSelect.selectedIndex;
        const range = parseInt(rangeSelect.value);
        if (baseIdx === -1) return;
        
        state.selectedMonths = [];
        for (let i = 0; i < range; i++) {
            const opt = baseSelect.options[baseIdx + i];
            if (opt && opt.value) state.selectedMonths.push(opt.value);
        }
        
        await updateMap(true); 
        
        if (state.selectedComplex) {
            const currentComplex = state.allLoadedData.find(i => 
                i.name === state.selectedComplex.name && i.address === state.selectedComplex.address
            );
            if (currentComplex) {
                state.selectedComplex = currentComplex;
                renderComplexDetail();
            } else {
                document.getElementById('data-list').innerHTML = '<div class="empty-state">선택한 기간에는 거래 내역이 없습니다.</div>';
            }
        }
    };
    if (baseSelect) baseSelect.onchange = updatePeriod;
    if (rangeSelect) rangeSelect.onchange = updatePeriod;

    document.getElementById('skyview-btn').onclick = () => {
        const type = state.map.getMapTypeId();
        state.map.setMapTypeId(type === kakao.maps.MapTypeId.ROADMAP ? kakao.maps.MapTypeId.HYBRID : kakao.maps.MapTypeId.ROADMAP);
    };

    const radiusBtn = document.getElementById('radius-btn');
    if (radiusBtn) radiusBtn.onclick = () => {
        state.radiusOn = !state.radiusOn;
        radiusBtn.classList.toggle('active', state.radiusOn);
        drawRadius();
    };

    // 오버레이 타일은 나중에 추가된 것이 위에 깔림 → 로드뷰 도로선(파란선)을 항상 맨 위로 유지
    const reassertRoadviewOverlay = () => {
        if (!state.roadviewOn) return;
        state.map.removeOverlayMapTypeId(kakao.maps.MapTypeId.ROADVIEW);
        state.map.addOverlayMapTypeId(kakao.maps.MapTypeId.ROADVIEW);
    };

    const cadastralBtn = document.getElementById('cadastral-btn');
    if (cadastralBtn) cadastralBtn.onclick = () => {
        state.cadastralOn = !state.cadastralOn;
        cadastralBtn.classList.toggle('active', state.cadastralOn);
        if (state.cadastralOn) { state.map.addOverlayMapTypeId(kakao.maps.MapTypeId.USE_DISTRICT); reassertRoadviewOverlay(); }
        else state.map.removeOverlayMapTypeId(kakao.maps.MapTypeId.USE_DISTRICT);
    };

    const distBtn = document.getElementById('dist-btn');
    if (distBtn) distBtn.onclick = () => setMeasureMode('dist');
    const areaBtn = document.getElementById('area-btn');
    if (areaBtn) areaBtn.onclick = () => setMeasureMode('area');

    const geolocBtn = document.getElementById('geoloc-btn');
    if (geolocBtn) geolocBtn.onclick = moveToCurrentLocation;

    // 길찾기 모드
    const routeBtn = document.getElementById('route-btn');
    if (routeBtn) routeBtn.onclick = () => {
        state.routeMode = !state.routeMode;
        routeBtn.classList.toggle('active', state.routeMode);
        if (!state.routeMode) clearRoute();
        else document.getElementById('status-bar').textContent = '길찾기: 출발지를 클릭하세요';
    };

    // 조그(다이얼) 패드 — 로드뷰 시점(pan/tilt) 조작 전용, 로드뷰 열리면 항상 표시
    const jogPad = document.getElementById('jog-pad');
    if (jogPad) {
        const jogStop = () => { if (state.jogTimer) { clearInterval(state.jogTimer); state.jogTimer = null; } };
        // 로드뷰 '이동': 현재 바라보는 방향 기준으로 한 걸음(약 14m) 옮겨 인접 파노라마로 점프
        // ▲=전진, ▼=후진, ◀▶=옆걸음 (대각선 조합 가능)
        const applyJog = (dx, dy) => {
            if (!state.rv || !state.rv.getPosition || !state.rvClient) return;
            const pos = state.rv.getPosition();
            if (!pos) return;
            const heading = state.rv.getViewpoint ? (state.rv.getViewpoint().pan || 0) : 0;
            const ang = (heading + Math.atan2(dx, -dy) * 180 / Math.PI) * Math.PI / 180;
            const dist = 14; // m/걸음
            const lat = pos.getLat(), lng = pos.getLng();
            const nLat = lat + (dist * Math.cos(ang)) / 111320;
            const nLng = lng + (dist * Math.sin(ang)) / (111320 * Math.cos(lat * Math.PI / 180));
            const np = new kakao.maps.LatLng(nLat, nLng);
            state.rvClient.getNearestPanoId(np, 12, (panoId) => {
                if (panoId !== null) state.rv.setPanoId(panoId, np);
            });
        };
        // 8방향 버튼: 누르는 동안 걸음 반복
        jogPad.querySelectorAll('.jog-arrow').forEach(btn => {
            const dx = parseInt(btn.dataset.dx), dy = parseInt(btn.dataset.dy);
            btn.addEventListener('pointerdown', (ev) => {
                ev.preventDefault();
                jogStop();
                applyJog(dx, dy);
                state.jogTimer = setInterval(() => applyJog(dx, dy), 650);
            });
            ['pointerup', 'pointerleave', 'pointercancel'].forEach(evt => btn.addEventListener(evt, jogStop));
        });
        // 가운데 노브 드래그 = 조이스틱 (끄는 방향으로 걸음 반복)
        const knob = document.getElementById('jog-knob');
        if (knob) {
            let vec = { x: 0, y: 0 };
            knob.addEventListener('pointerdown', (ev) => {
                ev.preventDefault();
                knob.setPointerCapture(ev.pointerId);
                const padRect = jogPad.getBoundingClientRect();
                const cx = padRect.left + padRect.width / 2, cy = padRect.top + padRect.height / 2;
                const track = (e) => {
                    const R = padRect.width / 2;
                    vec = { x: Math.max(-1, Math.min(1, (e.clientX - cx) / R)), y: Math.max(-1, Math.min(1, (e.clientY - cy) / R)) };
                    knob.style.transform = `translate(calc(-50% + ${vec.x * 26}px), calc(-50% + ${vec.y * 26}px))`;
                };
                track(ev);
                jogStop();
                applyJog(vec.x, vec.y);
                state.jogTimer = setInterval(() => applyJog(vec.x, vec.y), 650);
                const up = () => {
                    jogStop();
                    knob.style.transform = 'translate(-50%, -50%)';
                    knob.removeEventListener('pointermove', track);
                    knob.removeEventListener('pointerup', up);
                    knob.removeEventListener('pointercancel', up);
                };
                knob.addEventListener('pointermove', track);
                knob.addEventListener('pointerup', up);
                knob.addEventListener('pointercancel', up);
            });
        }
    }

    const roadviewBtn = document.getElementById('roadview-btn');
    if (roadviewBtn) roadviewBtn.onclick = () => {
        state.roadviewOn = !state.roadviewOn;
        roadviewBtn.classList.toggle('active', state.roadviewOn);
        if (state.roadviewOn) state.map.addOverlayMapTypeId(kakao.maps.MapTypeId.ROADVIEW);
        else { state.map.removeOverlayMapTypeId(kakao.maps.MapTypeId.ROADVIEW); document.getElementById('roadview-panel').style.display = 'none'; hideRvMapPin(); }
    };
    const rvCloseBtn = document.getElementById('rv-close-btn');
    if (rvCloseBtn) rvCloseBtn.onclick = () => { document.getElementById('roadview-panel').style.display = 'none'; hideRvMapPin(); };

    document.querySelectorAll('input[name="housingType"]').forEach(r => {
        r.onchange = (e) => { state.selectedType = e.target.value; state.selectedComplex = null; document.getElementById('data-section').style.display = 'none'; applyTxAvailability(); updateMap(true); };
    });

    document.querySelectorAll('input[name="transactionType"]').forEach(c => {
        c.onchange = () => {
            const chks = document.querySelectorAll('input[name="transactionType"]:checked');
            state.filters = { '매매': false, '전세': false, '월세': false };
            chks.forEach(chk => state.filters[chk.value] = true);
            if (state.selectedComplex) renderComplexDetail();
            updateMap(true);
        };
    });

    const searchInput = document.getElementById('search-input');
    if (searchInput) searchInput.oninput = (e) => handleSearch(e.target.value);

    const redevBtn = document.getElementById('redev-btn');
    if (redevBtn) redevBtn.onclick = () => {
        toggleRedev(!state.showRedev);
        redevBtn.classList.toggle('active', state.showRedev);
        if (state.showRedev) flashLegend(redevBtn);
    };
    // 호버 드롭다운용 세로 범례 채우기
    const redevDropdown = document.getElementById('redev-dropdown');
    if (redevDropdown) {
        redevDropdown.innerHTML = '<div class="dropdown-title">추진단계</div>' +
            CONFIG.REDEV_STAGES.map(s =>
                `<div class="legend-v-item"><span class="legend-dot" style="background:${CONFIG.REDEV_COLORS[s]}"></span>${s}</div>`
            ).join('');
    }

    // 토지이용계획(용도지역) 오버레이 토글
    const landuseBtn = document.getElementById('landuse-btn');
    if (landuseBtn) landuseBtn.onclick = () => {
        if (!state.landuseReady) {
            document.getElementById('status-bar').textContent = 'VWorld 키가 없어 이용계획을 표시할 수 없습니다 (make_config.py 실행 필요)';
            return;
        }
        state.landuseOn = !state.landuseOn;
        landuseBtn.classList.toggle('active', state.landuseOn);
        if (state.landuseOn) { state.map.addOverlayMapTypeId(kakao.maps.MapTypeId.LANDUSE); reassertRoadviewOverlay(); flashLegend(landuseBtn); }
        else state.map.removeOverlayMapTypeId(kakao.maps.MapTypeId.LANDUSE);
    };

    const agingLegendHtml = (note) => '<div class="dropdown-title">건축 경과년수</div>' +
        CONFIG.AGING_BANDS.map(b =>
            `<div class="legend-v-item"><span class="legend-dot" style="background:${b.color}"></span>${b.label}</div>`
        ).join('') +
        `<div class="legend-v-item"><span class="legend-dot" style="background:${CONFIG.AGING_UNKNOWN}"></span>정보 없음</div>` +
        `<div class="dropdown-note" style="margin:6px 0 0;">${note}</div>`;

    // 건물연령 (통합): 건물 폴리곤(동 축척~최대 확대) + 상세 매물 마커를 경과년수 색으로
    const bldgAgeBtn = document.getElementById('bldgage-btn');
    if (bldgAgeBtn) bldgAgeBtn.onclick = () => {
        if (!window.VWORLD_KEY) {
            document.getElementById('status-bar').textContent = 'VWorld 키가 없어 건물연령을 표시할 수 없습니다';
            return;
        }
        state.bldgAgeOn = !state.bldgAgeOn;
        refreshBldgAge();
        updateMap(true); // 매물 마커 색도 함께 갱신
        if (state.bldgAgeOn) flashLegend(bldgAgeBtn);
    };
    const bldgAgeDropdown = document.getElementById('bldgage-dropdown');
    if (bldgAgeDropdown) bldgAgeDropdown.innerHTML = agingLegendHtml('최대 확대 구간(레벨 1~2)에서 건물·매물에 적용');


    // 모바일 좌측 상단 필터 토글
    const filterFab = document.getElementById('filter-fab');
    if (filterFab) filterFab.onclick = () => {
        document.getElementById('control-panel').classList.toggle('collapsed');
    };

    const btnP = document.getElementById('unit-pyeong');
    const btnM = document.getElementById('unit-m2');
    if (btnP && btnM) {
        btnP.onclick = () => { state.displayUnit = 'pyeong'; btnP.classList.add('active'); btnM.classList.remove('active'); updateMap(true); if (state.selectedComplex) renderComplexDetail(); };
        btnM.onclick = () => { state.displayUnit = 'm2'; btnM.classList.add('active'); btnP.classList.remove('active'); updateMap(true); if (state.selectedComplex) renderComplexDetail(); };
    }

    const minRange = document.getElementById('area-min'), maxRange = document.getElementById('area-max'), rangeText = document.getElementById('area-range-text');
    if (minRange && maxRange) {
        const updateSlider = () => {
            let min = parseInt(minRange.value), max = parseInt(maxRange.value);
            if (min > max) [min, max] = [max, min];
            state.globalArea = { min, max };
            rangeText.textContent = `${min}평 ~ ${max >= 80 ? '80평+' : max + '평'}`;
            const track = document.querySelector('.slider-track');
            const p1 = (min / 80) * 100, p2 = (max / 80) * 100;
            track.style.background = `linear-gradient(to right, #e5e7eb ${p1}%, var(--primary-color) ${p1}%, var(--primary-color) ${p2}%, #e5e7eb ${p2}%)`;
            updateMap(true);
        };
        minRange.oninput = updateSlider; maxRange.oninput = updateSlider; updateSlider(); 
    }

    // 리스트 내 필터 (Checkbox)
    document.querySelectorAll('input[name="localTransactionType"]').forEach(c => {
        c.onchange = () => {
            const chks = document.querySelectorAll('input[name="localTransactionType"]:checked');
            state.localFilters = { '매매': false, '전세': false, '월세': false };
            chks.forEach(chk => state.localFilters[chk.value] = true);
            if (state.selectedComplex) renderComplexDetail();
        };
    });

    const closeDataBtn = document.getElementById('close-data-btn');
    if (closeDataBtn) {
        closeDataBtn.onclick = () => {
            const ds = document.getElementById('data-section');
            ds.style.display = 'none';
            ds.classList.remove('expanded');
            document.getElementById('control-panel').classList.remove('full-screen');
            state.selectedComplex = null;
            updateMap(true);
        };
    }

    // 모바일 결과 시트: 30% ↔ 전체화면 토글
    const expandBtn = document.getElementById('expand-data-btn');
    if (expandBtn) {
        expandBtn.onclick = () => {
            const ds = document.getElementById('data-section');
            const expanded = ds.classList.toggle('expanded');
            expandBtn.textContent = expanded ? '⇲' : '⛶';
            expandBtn.title = expanded ? '이전 크기로' : '전체화면 전환';
        };
    }

    const toggleBtn = document.getElementById('panel-toggle-btn');
    if (toggleBtn) {
        toggleBtn.onclick = () => {
            const panel = document.getElementById('control-panel');
            panel.classList.toggle('collapsed');
            if (window.innerWidth <= 768 && !panel.classList.contains('collapsed')) {
                panel.classList.add('full-screen');
            } else if (panel.classList.contains('collapsed')) {
                panel.classList.remove('full-screen');
            }
        };
    }
}

// 선택한 부동산 유형이 전월세를 제공하지 않으면 전세/월세 체크박스를 비활성화(회색+취소선)하고
// 안내 문구를 노출한다. 매매만 강제로 켠다. (상위 필터 + 리스트 내 필터 모두 적용)
function applyTxAvailability() {
    const rentOk = CONFIG.RENT_SUPPORTED.has(state.selectedType);

    ['전세', '월세'].forEach(v => {
        document.querySelectorAll(
            `input[name="transactionType"][value="${v}"], input[name="localTransactionType"][value="${v}"]`
        ).forEach(cb => {
            cb.disabled = !rentOk;
            cb.checked = rentOk;
            const chip = cb.closest('.filter-chip');
            if (chip) chip.classList.toggle('disabled', !rentOk);
        });
    });

    // 매매는 항상 제공 → 켜둔 상태 유지
    document.querySelectorAll(
        'input[name="transactionType"][value="매매"], input[name="localTransactionType"][value="매매"]'
    ).forEach(cb => { cb.checked = true; });

    state.filters = { '매매': true, '전세': rentOk, '월세': rentOk };
    state.localFilters = { '매매': true, '전세': rentOk, '월세': rentOk };

    const note = document.getElementById('tx-availability-note');
    if (note) note.style.display = rentOk ? 'none' : 'block';
}

// ==========================
// 정비사업(재개발/재건축) 레이어
// ==========================
async function toggleRedev(on) {
    state.showRedev = on;
    const legend = document.getElementById('redev-legend');
    if (!on) {
        clearRedevOverlays();
        if (legend) legend.style.display = 'none';
        return;
    }
    if (!state.redevZones) {
        try {
            const [zr, pr] = await Promise.all([
                fetch(`./redev_zones.json?v=${DATA_VER}`),
                fetch(`./redev_polygons.json?v=${DATA_VER}`)
            ]);
            state.redevZones = await zr.json();
            state.redevPolys = pr.ok ? await pr.json() : {};
        } catch (e) {
            console.error('정비구역 데이터 로드 실패:', e);
            state.redevZones = state.redevZones || [];
            state.redevPolys = state.redevPolys || {};
        }
    }
    if (legend) {
        legend.innerHTML = CONFIG.REDEV_STAGES.map(s =>
            `<span class="legend-item"><span class="legend-dot" style="background:${CONFIG.REDEV_COLORS[s]}"></span>${s}</span>`
        ).join('');
        legend.style.display = 'flex';
    }
    renderRedevMarkers();
}

function clearRedevOverlays() {
    state.redevOverlays.forEach(o => o.setMap(null));
    state.redevOverlays = [];
}

function renderRedevMarkers() {
    clearRedevOverlays();
    if (!state.showRedev || !state.redevZones) return;
    state.redevZones.forEach(z => {
        const pos = new kakao.maps.LatLng(z.coords[1], z.coords[0]);
        const color = CONFIG.REDEV_COLORS[z.stage] || '#6b7280';

        // 구역 경계 폴리곤 (SHP 매칭된 318개 구역) — 단계색으로 영역 표시
        const rings = state.redevPolys ? state.redevPolys[`${z.district}|${z.name}`] : null;
        if (rings) {
            rings.forEach(ring => {
                const path = ring.map(p => new kakao.maps.LatLng(p[1], p[0]));
                const poly = new kakao.maps.Polygon({
                    path, strokeWeight: 2, strokeColor: color, strokeOpacity: 0.9,
                    fillColor: color, fillOpacity: 0.18, zIndex: 40
                });
                poly.setMap(state.map);
                state.redevOverlays.push(poly);
                kakao.maps.event.addListener(poly, 'click', () => showRedevDetail(z, color));
                kakao.maps.event.addListener(poly, 'mouseover', () => {
                    state.tooltip.setContent(
                        `<div class="custom-tooltip"><div class="tooltip-header">${z.name} <span style="color:${color}">● ${z.stage}</span></div></div>`
                    );
                    state.tooltip.setPosition(pos);
                    state.tooltip.setMap(state.map);
                });
                kakao.maps.event.addListener(poly, 'mouseout', () => state.tooltip.setMap(null));
            });
        }

        const div = document.createElement('div');
        div.className = 'redev-marker';
        div.innerHTML = `<div class="redev-dot" style="background:${color}"></div>`;
        const overlay = new kakao.maps.CustomOverlay({ position: pos, content: div, yAnchor: 0.5, zIndex: 50 });
        overlay.setMap(state.map);
        state.redevOverlays.push(overlay);

        div.onmouseenter = () => {
            state.tooltip.setContent(
                `<div class="custom-tooltip"><div class="tooltip-header">${z.name} <span style="color:${color}">● ${z.stage}</span></div>` +
                `<div class="tooltip-body"><div class="tooltip-row"><span>${z.type}</span></div>` +
                `<div class="tooltip-row"><span>${z.district} ${z.addr}</span></div></div></div>`
            );
            state.tooltip.setPosition(pos);
            state.tooltip.setMap(state.map);
        };
        div.onmouseleave = () => state.tooltip.setMap(null);
        div.onpointerdown = (ev) => markOverlayClick(ev);
        div.onclick = (ev) => { markOverlayClick(ev); showRedevDetail(z, color); };
    });
}

function showRedevDetail(z, color) {
    const sidePanel = document.getElementById('data-section');
    const dataList = document.getElementById('data-list');
    const areaFilter = document.getElementById('area-filter');
    state.selectedComplex = null;
    document.getElementById('data-title').textContent = `${z.name} (${z.stage})`;
    areaFilter.style.display = 'none';

    const controlPanel = document.getElementById('control-panel');
    if (isMobile()) {
        controlPanel.classList.add('collapsed');
    } else {
        controlPanel.classList.remove('collapsed');
    }
    sidePanel.style.display = 'block';
    sidePanel.scrollTop = 0;

    const dates = [
        ['구역지정', z.d_zone], ['추진위 승인', z.d_committee], ['조합설립', z.d_assoc],
        ['사업시행인가', z.d_impl], ['관리처분인가', z.d_mgmt], ['착공', z.d_constr]
    ].filter(([, v]) => v);
    const hh = [];
    if (z.hh_exist) hh.push(`기존 ${z.hh_exist}세대`);
    if (z.hh_total) hh.push(`신축 ${z.hh_total}세대 (분양 ${z.hh_sale || '-'} / 임대 ${z.hh_rent || '-'})`);

    dataList.innerHTML =
        `<div class="data-card" style="border-left:4px solid ${color}">` +
        `<div class="card-title-row"><span class="card-badge" style="background:${color}">${z.stage}</span><span class="card-date">${z.type}</span></div>` +
        `<div class="card-row-main">${z.district} ${z.addr}</div>` +
        (hh.length ? `<div class="card-row-highlight">${hh.join(' → ')}</div>` : '') +
        dates.map(([k, v]) => `<div class="card-row-sub">${k}: ${v}</div>`).join('') +
        `</div>`;
}

async function renderMonthSelect() {
    try {
        const res = await fetch('./manifest.json?v=' + Date.now());
        const ymList = await res.json();
        const selectEl = document.getElementById('base-month-select');
        selectEl.innerHTML = ymList.map(ym => `<option value="${ym}">${ym.substring(0,4)}.${ym.substring(4,6)}</option>`).join('');
        
        if (ymList.length > 0) {
            state.selectedMonths = [ymList[0]];
            selectEl.selectedIndex = 0;
        }
    } catch (e) { console.error("데이터 목록 로드 실패:", e); }
}

async function updateMap(force = false) {
    return new Promise(async (resolve) => {
        const zoom = state.map.getLevel();
        let newLevel = zoom >= CONFIG.ZOOM_LEVELS[1] ? 1 : (zoom >= CONFIG.ZOOM_LEVELS[2] ? 2 : (zoom >= CONFIG.ZOOM_LEVELS[3] ? 3 : 4));
        
        if (newLevel === 4) {
            // 구 데이터 로딩: 구 '중심점'이 화면 밖이어도 가장자리 매물이 빠지지 않도록
            // 뷰포트의 절반만큼 사방으로 여유를 두고 판정
            const bounds = state.map.getBounds(), gungusInView = new Set();
            const sw = bounds.getSouthWest(), ne = bounds.getNorthEast();
            const mLng = (ne.getLng() - sw.getLng()) * 0.5, mLat = (ne.getLat() - sw.getLat()) * 0.5;
            const inExpanded = (c) => c[0] >= sw.getLng() - mLng && c[0] <= ne.getLng() + mLng && c[1] >= sw.getLat() - mLat && c[1] <= ne.getLat() + mLat;
            for (const ym of state.selectedMonths) {
                (await loadSummaryData(ym, 2)).forEach(g => { if (inExpanded(g.coords)) gungusInView.add(`${g.sido}_${g.name.split(' ')[1] || g.name}`.replace(/ /g, '_')); });
            }
            state.geocoder.coord2RegionCode(state.map.getCenter().getLng(), state.map.getCenter().getLat(), async (result, status) => {
                if (status === kakao.maps.services.Status.OK) {
                    const reg = result.find(r => r.region_type === 'H' || r.region_type === 'B');
                    gungusInView.add(`${reg.region_1depth_name}_${reg.region_2depth_name}`.replace(/ /g, '_'));
                    const gunguKeyStr = Array.from(gungusInView).sort().join('|');
                    if (state.activeGungus !== gunguKeyStr || state.currentLevel !== 4 || force) {
                        state.activeGungus = gunguKeyStr; state.currentLevel = 4;
                        renderMarkers(await fetchAndMergeData(4, Array.from(gungusInView)), 4);
                    }
                }
                resolve();
            });
        } else {
            if (state.currentLevel === newLevel && !force) { resolve(); return; }
            state.currentLevel = newLevel; state.activeGungus = null;
            renderMarkers(await fetchAndMergeData(newLevel), newLevel);
            resolve();
        }
    });
}

async function loadGlobalSearchIndex() {
    try {
        const res = await fetch('./global_search_index.json?v=' + Date.now());
        if (res.ok) {
            state.searchIndex = await res.json();
        }
    } catch (e) { console.error("검색 인덱스 로드 실패:", e); }
}

async function fetchAndMergeData(level, gunguList = []) {
    const allResults = []; if (state.selectedMonths.length === 0) return [];
    for (const ym of state.selectedMonths) {
        if (level === 4) { for (const gunguKey of gunguList) allResults.push(...(await loadDetailShard(ym, gunguKey))); }
        else allResults.push(...(await loadSummaryData(ym, level)));
    }
    const mergedMap = new Map();
    allResults.forEach(item => {
        const key = level === 4 ? (item.address + item.name) : item.name;
        if (!mergedMap.has(key)) mergedMap.set(key, JSON.parse(JSON.stringify(item)));
        else {
            const ex = mergedMap.get(key); ex.stats.total += item.stats.total;
            ['sale', 'jeonse', 'monthly'].forEach(t => {
                if (!item.stats[t]) return; 
                if (!ex.stats[t]) { ex.stats[t] = JSON.parse(JSON.stringify(item.stats[t])); return; }
                ex.stats[t].count += item.stats[t].count;
                ex.stats[t].range = [Math.min(ex.stats[t].range[0], item.stats[t].range[0]), Math.max(ex.stats[t].range[1], item.stats[t].range[1])];
                if (item.stats[t].count > ex.stats[t].count / 2) { 
                    ex.stats[t].rep_area = item.stats[t].rep_area; 
                    ex.stats[t].rep_avg_price = item.stats[t].rep_avg_price; 
                }
            });
            if (level === 4 && item.deals) ex.deals.push(...item.deals);
        }
    });
    return (state.allLoadedData = Array.from(mergedMap.values()));
}

// 페이지 로드 시각 기반 버전 토큰: 새로고침하면 항상 최신 데이터(JSON)를 받는다
// (데이터 재생성 후 브라우저가 옛 hierarchy 캐시를 계속 쓰는 문제 방지)
const DATA_VER = Date.now();

async function loadSummaryData(ym, level) {
    const cacheKey = `${ym}_${state.selectedType}_${level}`; if (state.levelData[cacheKey]) return state.levelData[cacheKey];
    const fileMap = { 1: 'summary_sido.json', 2: 'summary_gungu.json', 3: 'summary_dong.json' };
    try { const res = await fetch(`./hierarchy/${ym}/${state.selectedType}/${fileMap[level]}?v=${DATA_VER}`); const data = await res.json(); return (state.levelData[cacheKey] = data); } catch (e) { return []; }
}

async function loadDetailShard(ym, gunguKey) {
    const cacheKey = `${ym}_${state.selectedType}_${gunguKey}`; if (state.detailShards[cacheKey]) return state.detailShards[cacheKey];
    try { const res = await fetch(`./hierarchy/${ym}/${state.selectedType}/details/${gunguKey}.json?v=${DATA_VER}`); const data = await res.json(); return (state.detailShards[cacheKey] = data); } catch (e) { return []; }
}

function renderMarkers(data, level) {
    clearOverlays(); const bounds = state.map.getBounds();
    const filtered = data.filter(item => {
        const s = item.stats; let maxRepArea = 0;
        ['sale', 'jeonse', 'monthly'].forEach(t => { if (state.filters[t === 'sale' ? '매매' : (t === 'jeonse' ? '전세' : '월세')] && s[t]) maxRepArea = Math.max(maxRepArea, s[t].rep_area); });
        if (maxRepArea > 0) { const p = Math.round(maxRepArea * 0.3025); if (!(p >= state.globalArea.min && (state.globalArea.max >= 80 || p <= state.globalArea.max))) return false; }
        return (state.filters['매매'] && s.sale) || (state.filters['전세'] && s.jeonse) || (state.filters['월세'] && s.monthly);
    });
    // 레벨4: 동일 좌표에 여러 그룹이 겹치면 하나의 마커 + 개수 배지로 묶는다
    let renderList; // [ [대표item, 그룹배열] ]
    if (level === 4) {
        const byPos = new Map();
        filtered.forEach(item => {
            const k = `${item.coords[0]},${item.coords[1]}`;
            if (!byPos.has(k)) byPos.set(k, []);
            byPos.get(k).push(item);
        });
        renderList = Array.from(byPos.values()).map(g => [g[0], g]);
    } else {
        renderList = filtered.map(item => [item, [item]]);
    }

    renderList.forEach(([item, group]) => {
        const pos = new kakao.maps.LatLng(item.coords[1], item.coords[0]); if (level === 4 && !bounds.contain(pos)) return;
        const content = createOverlayContent(item, level, group.length), overlay = new kakao.maps.CustomOverlay({ position: pos, content: content, yAnchor: 1.0 });
        overlay.setMap(state.map); state.overlays.push(overlay);
        // pointerdown 시점에 가드 — 카카오 지도 클릭 처리(필지조회·로드뷰 등)보다 항상 먼저 걸리게
        content.onpointerdown = (ev) => markOverlayClick(ev);
        content.onclick = (ev) => {
            markOverlayClick(ev);
            if (level !== 4) { handleLevelMove(item, level); return; }
            closeClusterPicker();
            if (group.length === 1) {
                state.selectedComplex = item; state.selectedArea = null; renderComplexDetail(); updateMap(true);
            } else {
                showClusterPicker(group, pos);
            }
        };
        content.onmouseenter = () => { const key = `${level}_${item.name}`; if (state.hoveredItem === key) return; state.hoveredItem = key; showTooltip(item, level, pos); };
        content.onmouseleave = () => { state.hoveredItem = null; state.tooltip.setMap(null); };
    });
    
    // 상태바 갱신: 선택된 단지가 있으면 단지 정보, 없으면 단계별 건수
    const statusEl = document.getElementById('status-bar');
    if (state.selectedComplex && level === 4) {
        statusEl.textContent = `${state.selectedComplex.name}: 총 ${state.selectedComplex.deals.length}건`;
    } else {
        statusEl.textContent = `${level}단계: ${filtered.length}건 표시 중`;
    }
}

// 위치 미확정 묶음 판별: 이름이 '시도 구 동' 형태로 끝나면 동 단위 그룹(동 중심 표시)
// (마스킹 매매 미매칭 + 지번이 제공되지 않는 전월세가 여기에 묶인다)
// 아파트 단지명(숫자 없는 이름) 오탐 방지: 3토큰 이상 + 끝이 행정구역 접미사일 때만
function isApproxGroup(item) {
    const parts = (item.name || '').trim().split(' ');
    if (parts.length < 3) return false;
    const last = parts[parts.length - 1];
    return !/\d/.test(last) && /(동|리|가|읍|면)$/.test(last);
}

// 매물 그룹의 대표 건축년도 (거래들 중 유효값의 최빈)
function repBuildYear(item) {
    if (!item.deals) return 0;
    const counts = {};
    item.deals.forEach(d => { if (d.by && d.by > 1900) counts[d.by] = (counts[d.by] || 0) + 1; });
    let best = 0, n = 0;
    for (const y in counts) if (counts[y] > n) { n = counts[y]; best = +y; }
    return best;
}

function agingColor(buildYear) {
    if (!buildYear || buildYear <= 1900) return CONFIG.AGING_UNKNOWN;
    const age = new Date().getFullYear() - buildYear;
    for (const b of CONFIG.AGING_BANDS) if (age >= b.min) return b.color;
    return CONFIG.AGING_UNKNOWN;
}

function createOverlayContent(item, level, groupCount = 1) {
    const isSelected = state.selectedComplex && state.selectedComplex.name === item.name && state.selectedComplex.address === item.address;
    const div = document.createElement('div');
    div.className = `level-marker level-${level} ${isSelected ? 'selected' : ''}`;
    let themeColor = CONFIG.TYPE_COLORS[state.selectedType] || '#2563eb';
    // 건물연령 모드: 상세 레벨 매물 마커도 건축 경과년수 색으로
    if (state.bldgAgeOn && level === 4) themeColor = agingColor(repBuildYear(item));
    let targetType = state.filters['매매'] && item.stats.sale ? "sale" : (state.filters['전세'] && item.stats.jeonse ? "jeonse" : (state.filters['월세'] && item.stats.monthly ? "monthly" : ""));
    const stats = item.stats[targetType]; let label = "", subLabel = "";
    if (level === 4) { 
        if (stats) { label = state.displayUnit === 'pyeong' ? `${Math.round(stats.rep_area * 0.3025)}평` : `${Math.round(stats.rep_area)}㎡`; subLabel = formatPrice(stats.rep_avg_price); } 
        else { label = "내역없음"; subLabel = "-"; } 
    } else { label = (level === 2) ? (item.name.split(' ')[1] || item.name) : item.name; subLabel = stats ? `${state.displayUnit === 'pyeong' ? Math.round(stats.rep_area * 0.3025)+'평' : Math.round(stats.rep_area)+'㎡'} ${formatPrice(stats.rep_avg_price)}` : "내역없음"; }
    
    let markerBg = isSelected ? 'linear-gradient(135deg, #1e3a8a, #3b82f6)' : themeColor;
    let arrowColor = isSelected ? '#1e3a8a' : themeColor;
    // 위치 미확정 묶음(동 중심): 회색 빗금 + 점선 테두리로 실위치 마커와 구분
    if (level === 4 && isApproxGroup(item)) {
        div.classList.add('approx-group');
        if (!isSelected) { markerBg = 'repeating-linear-gradient(135deg, #94a3b8 0 5px, #64748b 5px 10px)'; arrowColor = '#64748b'; }
        label = (item.name.split(' ').pop() || '') + ' 일대';
        subLabel = `위치미상 ${item.stats.total}건`;
    }
    const badge = groupCount > 1 ? `<div class="marker-badge">${groupCount}</div>` : '';
    div.innerHTML = `${badge}<div class="marker-body" style="background:${markerBg}"><span class="marker-label">${label}</span><span class="marker-count" style="font-size:10px">${subLabel}</span></div><div class="marker-arrow" style="border-top-color:${arrowColor}"></div>`;
    return div;
}

// ==========================
// 겹침 마커 선택 리스트 (같은 좌표에 여러 매물 그룹)
// ==========================
function closeClusterPicker() {
    if (state.clusterPicker) { state.clusterPicker.setMap(null); state.clusterPicker = null; }
}

function showClusterPicker(group, pos) {
    closeClusterPicker();
    const div = document.createElement('div');
    div.className = 'cluster-picker';
    const header = document.createElement('div');
    header.className = 'picker-header';
    header.innerHTML = `<span>이 위치 매물 ${group.length}개</span><button class="picker-close">&times;</button>`;
    header.querySelector('.picker-close').onclick = (e) => { markOverlayClick(e); closeClusterPicker(); };
    div.appendChild(header);

    const list = document.createElement('div');
    list.className = 'picker-list';
    group.forEach(it => {
        const row = document.createElement('div');
        row.className = 'picker-item';
        row.innerHTML = `<div class="picker-name">${it.name}</div>` +
            `<div class="picker-addr">${it.address || ''}</div>` +
            `<div class="picker-meta">거래 ${it.deals ? it.deals.length : it.stats.total}건</div>`;
        row.onclick = (e) => {
            markOverlayClick(e);
            state.selectedComplex = it; state.selectedArea = null;
            closeClusterPicker();
            renderComplexDetail();
            updateMap(true);
        };
        list.appendChild(row);
    });
    div.appendChild(list);

    state.clusterPicker = new kakao.maps.CustomOverlay({ position: pos, content: div, yAnchor: 1.15, zIndex: 2000 });
    state.clusterPicker.setMap(state.map);
}

// ==========================
// 반경 동심원 (화면 중앙 기준 100m 간격, 지도 이동/줌 시 갱신)
// ==========================
function drawRadius() {
    state.radiusOverlays.forEach(o => o.setMap(null));
    state.radiusOverlays = [];
    if (!state.radiusOn) return;
    const c = state.map.getCenter();
    for (let i = 1; i <= 5; i++) {
        const circle = new kakao.maps.Circle({
            center: c, radius: i * 100,
            strokeWeight: 1.5, strokeColor: '#2563eb', strokeOpacity: 0.75, strokeStyle: 'shortdash',
            fillOpacity: 0
        });
        circle.setMap(state.map);
        state.radiusOverlays.push(circle);
        // 각 원 북쪽 끝에 거리 라벨
        const labelPos = new kakao.maps.LatLng(c.getLat() + (i * 100) / 111000, c.getLng());
        const label = new kakao.maps.CustomOverlay({
            position: labelPos,
            content: `<div class="radius-label">${i * 100}m</div>`,
            yAnchor: 0.5, zIndex: 60
        });
        label.setMap(state.map);
        state.radiusOverlays.push(label);
    }
}

function handleLevelMove(item, level) { state.map.setCenter(new kakao.maps.LatLng(item.coords[1], item.coords[0])); state.map.setLevel((level === 1) ? 8 : (level === 2 ? 6 : 4), { animate: true }); }
function showTooltip(item, level, pos) {
    const stats = item.stats; const fmtR = (s) => (!s) ? "" : (s.range[0] === s.range[1] ? formatPrice(s.range[0]) : `${formatPrice(s.range[0])}~${formatPrice(s.range[1])}`);
    const row = (type, key, cls) => (state.filters[type] && stats[key]) ? `<div class="tooltip-row ${cls}"><span>${type}</span><span>${stats[key].count}건</span><b>${fmtR(stats[key])}</b></div>` : "";
    const approxNote = (level === 4 && isApproxGroup(item)) ? `<div class="tooltip-note">※ 위치 미확정 매물 묶음 — 동 중심에 표시됨</div>` : '';
    state.tooltip.setContent(`<div class="custom-tooltip"><div class="tooltip-header">${item.name}</div><div class="tooltip-body">${row('매매', 'sale', 'sale')}${row('전세', 'jeonse', 'jeonse')}${row('월세', 'monthly', 'monthly')}${approxNote}</div></div>`);
    state.tooltip.setPosition(pos); state.tooltip.setMap(state.map);
}

function formatPrice(val) { if (val >= 10000) return `${Math.round(val / 1000) / 10}억`; return val.toLocaleString() + '만'; }

// 아파트 시세 월별 추이 차트 — 매매/전세/월세 3계열, 리스트 내 거래유형·평형 필터 연동
// 전체 선택 시: 평당가(만원/평, 면적이 달라도 비교 가능) / 특정 평형 선택 시: 실거래가(억)
// 월세는 환산가(보증금 + 월세×100)로 같은 축에 표시
const CHART_SERIES = [
    { key: '매매', color: '#dc2626', raw: d => d.price },
    { key: '전세', color: '#2563eb', raw: d => d.price },
    { key: '월세', color: '#16a34a', raw: d => d.price + (d.rent || 0) * 100 }
];

function buildPriceChart(item) {
    const areaSel = state.selectedArea;          // null = 전체
    const perPyeong = areaSel === null;          // 전체 → 평당가 모드
    const dealArea = d => state.displayUnit === 'pyeong' ? Math.round(d.area * 0.3025) : Math.round(d.area);

    // 계열별 월평균 집계 (거래유형 + 평형 필터 연동)
    const series = [];
    CHART_SERIES.forEach(s => {
        if (!state.localFilters[s.key]) return;
        const deals = (item.deals || []).filter(d =>
            d.type === s.key && d.price > 0 && d.area > 0 && d.date && d.date.length >= 7 &&
            (perPyeong || dealArea(d) === areaSel));
        if (!deals.length) return;
        const byMonth = {};
        deals.forEach(d => {
            const k = d.date.slice(0, 7);
            const v = perPyeong ? s.raw(d) / (d.area * 0.3025) : s.raw(d);
            (byMonth[k] = byMonth[k] || []).push(v);
        });
        const months = Object.keys(byMonth).sort();
        series.push({
            ...s, n: deals.length, months,
            avgs: months.map(k => byMonth[k].reduce((a, b) => a + b, 0) / byMonth[k].length),
            counts: months.map(k => byMonth[k].length)
        });
    });
    if (!series.length) return null;
    const allMonths = [...new Set(series.flatMap(s => s.months))].sort();
    if (allMonths.length < 2) return null; // 추이라 할 게 없으면 생략

    const W = 320, H = 140, PL = 42, PR = 12, PT = 12, PB = 24;
    const allVals = series.flatMap(s => s.avgs);
    const min = Math.min(...allVals), max = Math.max(...allVals);
    const span = (max - min) || max * 0.1 || 1;
    const x = m => PL + (W - PL - PR) * (allMonths.indexOf(m) / (allMonths.length - 1));
    const y = v => PT + (H - PT - PB) * (1 - (v - min) / span);
    // 축·툴팁 값 표기: 평당가 = 만원/평, 실거래가 = 억 단위
    const fmtVal = v => perPyeong ? `${Math.round(v).toLocaleString()}` : formatPrice(v);
    const tipUnit = perPyeong ? '만/평' : '';
    const mLabel = m => m.slice(2).replace('-', '.');

    let lines = '', dots = '';
    series.forEach(s => {
        const pts = s.months.map((m, i) => `${x(m).toFixed(1)},${y(s.avgs[i]).toFixed(1)}`).join(' ');
        if (s.months.length > 1) lines += `<polyline points="${pts}" fill="none" stroke="${s.color}" stroke-width="2"/>`;
        s.months.forEach((m, i) => {
            dots += `<circle class="chart-dot" cx="${x(m).toFixed(1)}" cy="${y(s.avgs[i]).toFixed(1)}" r="3.5" fill="${s.color}"` +
                ` data-tip="${m.slice(2).replace('-', '.')} ${s.key}: ${fmtVal(s.avgs[i])}${tipUnit} · ${s.counts[i]}건"/>`;
        });
    });
    const legend = series.map(s =>
        `<span class="chart-leg"><span class="legend-dot" style="background:${s.color}"></span>${s.key}${s.key === '월세' ? '(환산)' : ''} ${s.n}건</span>`
    ).join('');

    const unitLabel = state.displayUnit === 'pyeong' ? '평' : '㎡';
    const titleHtml = perPyeong
        ? `<span class="chart-badge py">평당가</span> 추이 <span>(만원/평 · 면적 혼합이라 평당 환산${series.some(s => s.key === '월세') ? ' · 월세=보증금+월세×100' : ''})</span>`
        : `<span class="chart-badge raw">실거래가</span> ${areaSel}${unitLabel} 추이 <span>(${series.some(s => s.key === '월세') ? '월세=보증금+월세×100 환산' : '실제 거래금액'})</span>`;

    const div = document.createElement('div');
    div.className = 'price-chart' + (perPyeong ? ' per-pyeong' : '');
    div.innerHTML =
        `<div class="chart-title">${titleHtml}</div>` +
        `<div class="chart-legend">${legend}</div>` +
        `<svg viewBox="0 0 ${W} ${H}" width="100%">` +
        `<line x1="${PL}" y1="${y(max)}" x2="${W - PR}" y2="${y(max)}" class="chart-grid"/>` +
        `<line x1="${PL}" y1="${y(min)}" x2="${W - PR}" y2="${y(min)}" class="chart-grid"/>` +
        `<text x="${PL - 5}" y="${y(max) + 4}" text-anchor="end" class="chart-axis">${fmtVal(max)}</text>` +
        `<text x="${PL - 5}" y="${y(min) + 4}" text-anchor="end" class="chart-axis">${fmtVal(min)}</text>` +
        lines + dots +
        `<text x="${x(allMonths[0])}" y="${H - 7}" text-anchor="start" class="chart-axis">${mLabel(allMonths[0])}</text>` +
        `<text x="${x(allMonths[allMonths.length - 1])}" y="${H - 7}" text-anchor="end" class="chart-axis">${mLabel(allMonths[allMonths.length - 1])}</text>` +
        `</svg><div class="chart-tip" style="display:none;"></div>`;

    // 점 호버 툴팁
    const tip = div.querySelector('.chart-tip');
    div.querySelectorAll('.chart-dot').forEach(c => {
        c.addEventListener('mouseenter', () => {
            tip.textContent = c.dataset.tip;
            const cr = c.getBoundingClientRect(), dr = div.getBoundingClientRect();
            tip.style.display = 'block';
            tip.style.left = Math.max(4, Math.min(cr.left - dr.left - 60, dr.width - 130)) + 'px';
            tip.style.top = (cr.top - dr.top - 30) + 'px';
        });
        c.addEventListener('mouseleave', () => { tip.style.display = 'none'; });
    });
    return div;
}

function renderComplexDetail() {
    const item = state.selectedComplex; if (!item || !item.deals) return;
    const sidePanel = document.getElementById('data-section'), dataList = document.getElementById('data-list'), areaFilter = document.getElementById('area-filter');
    sidePanel.scrollTop = 0; document.getElementById('data-title').textContent = item.name;
    // 주소 표시 (건물명과 주소가 같으면 중복 생략)
    const addrEl = document.getElementById('data-address');
    if (addrEl) {
        addrEl.textContent = (item.address && item.address !== item.name) ? item.address : '';
        if (isApproxGroup(item)) addrEl.innerHTML = `<span class="approx-badge">위치미상</span> 지번이 공개되지 않아 동 중심에 묶어 표시한 매물입니다` + (addrEl.textContent ? ` · ${addrEl.textContent}` : '');
    }
    
    // 모바일: 필터 패널은 접고(FAB로 열기) 결과는 독립 하단 시트(30%)로
    const controlPanel = document.getElementById('control-panel');
    if (isMobile()) {
        controlPanel.classList.add('collapsed');
    } else {
        controlPanel.classList.remove('collapsed');
    }
    sidePanel.style.display = 'block';

    const validInGlobal = item.deals.filter(d => { const p = Math.round(d.area * 0.3025); return p >= state.globalArea.min && (state.globalArea.max >= 80 || p <= state.globalArea.max); });
    const uniqueAreas = [...new Set(validInGlobal.map(d => state.displayUnit === 'pyeong' ? Math.round(d.area * 0.3025) : Math.round(d.area)))].sort((a, b) => a - b);
    areaFilter.innerHTML = '';
    if (uniqueAreas.length > 0) {
        const allChip = document.createElement('div'); allChip.className = `area-chip ${state.selectedArea === null ? 'active' : ''}`; allChip.textContent = '전체'; allChip.onclick = () => { state.selectedArea = null; renderComplexDetail(); }; areaFilter.appendChild(allChip);
        uniqueAreas.forEach(area => { const chip = document.createElement('div'); chip.className = `area-chip ${state.selectedArea === area ? 'active' : ''}`; chip.textContent = state.displayUnit === 'pyeong' ? `${area}평` : `${area}㎡`; chip.onclick = () => { state.selectedArea = area; renderComplexDetail(); }; areaFilter.appendChild(chip); });
        areaFilter.style.display = 'flex';
    } else areaFilter.style.display = 'none';
    dataList.innerHTML = '';
    // 아파트 한정: 매매 평당가 추이 차트
    if (state.selectedType === 'apt') {
        const chart = buildPriceChart(item);
        if (chart) dataList.appendChild(chart);
    }
    const priority = { '매매': 1, '전세': 2, '월세': 3 };
    
    // localFilters 적용
    let filtered = validInGlobal.filter(d => state.localFilters[d.type]);
    if (state.selectedArea !== null) filtered = filtered.filter(d => (state.displayUnit === 'pyeong' ? Math.round(d.area * 0.3025) : Math.round(d.area)) === state.selectedArea);
    filtered.sort((a, b) => (priority[a.type] || 99) - (priority[b.type] || 99) || b.date.localeCompare(a.date));
    filtered.forEach(deal => {
        const card = document.createElement('div'); card.className = `data-card card-${deal.type === '전세' ? 'jeonse' : (deal.type === '월세' ? 'monthly' : 'sale')}`;
        const pArea = Math.round(deal.area * 0.3025);
        const pLand = deal.land ? Math.round(deal.land * 0.3025) : 0;
        let info = `전용: ${pArea}평 (${deal.area}㎡)`;
        if (pLand > 0) info += `, 대지: ${pLand}평 (${deal.land}㎡)`;
        if (deal.floor && deal.floor !== "nan" && deal.floor !== "0") info += ` | ${deal.floor}층`;
        const dongInfo = (deal.dong && deal.dong !== "nan" && deal.dong !== "") ? `<div class="card-row-highlight">${deal.dong}동</div>` : "";
        // 지번 표시: 마스킹('2*')이면 그대로 표기, 없으면 그룹 주소로 대체
        const jibunTxt = (deal.jibun && deal.jibun !== "nan") ? deal.jibun : (item.address || "");
        const addrInfo = jibunTxt ? `<div class="card-row-sub card-addr">주소: ${jibunTxt}</div>` : "";
        const byInfo = (deal.by && deal.by > 1900) ? `<div class="card-row-sub">건축년도: ${deal.by}년 (${new Date().getFullYear() - deal.by}년차)</div>` : "";
        card.innerHTML = `<div class="card-title-row"><span class="card-badge">${deal.type}</span><span class="card-date">${deal.date || ''}</span></div><div class="card-price-row"><span class="card-price">${formatPrice(deal.price || 0)}${deal.rent > 0 ? ' / ' + deal.rent : ''}</span></div><div class="card-row-main">${info}</div>${addrInfo}${byInfo}${dongInfo}${(deal.period && deal.period !== "nan") ? `<div class="card-row-sub">임차기간: ${deal.period}</div>` : ''}${(deal.renew && deal.renew !== "nan") ? `<div class="card-row-sub">갱신여부: ${deal.renew}</div>` : ''}${(deal.p_dep && deal.p_dep > 0) ? `<div class="card-row-sub">종전: ${formatPrice(deal.p_dep)}${deal.p_rent > 0 ? ' / ' + deal.p_rent : ''}</div>` : ''}`;
        dataList.appendChild(card);
    });
    if (filtered.length === 0) dataList.innerHTML = '<div class="empty-state">해당 필터에 맞는 거래 내역이 없습니다.</div>';
}

// ==========================
// 거리/면적 측정 도구
// ==========================
function fmtDist(m) { return m < 1000 ? `${Math.round(m)}m` : `${(m / 1000).toFixed(2)}km`; }
function fmtArea(a) { return `${Math.round(a).toLocaleString()}㎡ (${Math.round(a * 0.3025).toLocaleString()}평)`; }
// 도보 소요시간 (보행속도 약 4km/h = 67m/분)
function fmtWalk(m) { const min = Math.max(1, Math.round(m / 67)); return min < 60 ? `${min}분` : `${Math.floor(min / 60)}시간 ${min % 60}분`; }

// 버튼 클릭: 모드 ON (다른 측정 모드는 종료). 재클릭: 모드 OFF + 해당 유형 도형 전부 삭제
function setMeasureMode(mode) {
    finishMeasure();
    const turnOff = state.measureMode === mode;
    state.measureMode = turnOff ? null : mode;
    if (turnOff) clearMeasure(mode);
    document.getElementById('dist-btn').classList.toggle('active', state.measureMode === 'dist');
    document.getElementById('area-btn').classList.toggle('active', state.measureMode === 'area');
    const statusEl = document.getElementById('status-bar');
    if (state.measureMode === 'dist') statusEl.textContent = '거리 측정: 지도를 클릭하세요 (더블클릭/우클릭/ESC로 종료)';
    else if (state.measureMode === 'area') statusEl.textContent = '면적 측정: 꼭짓점을 클릭하세요 (더블클릭/우클릭/ESC로 종료)';
}

function addMeasureOverlay(latlng, html, yAnchor = 0.5) {
    const div = document.createElement('div');
    div.innerHTML = html;
    const ov = new kakao.maps.CustomOverlay({ position: latlng, content: div.firstChild, yAnchor, zIndex: 1700 });
    ov.setMap(state.map);
    state.curOverlays.push(ov);
    return ov;
}

function onMeasureClick(latlng) {
    state.curPts.push(latlng);
    addMeasureOverlay(latlng, '<div class="measure-dot"></div>');
    if (state.measureMode === 'dist') {
        if (!state.curLine) {
            state.curLine = new kakao.maps.Polyline({ path: state.curPts, strokeWeight: 3, strokeColor: '#dc2626', strokeOpacity: 0.9 });
            state.curLine.setMap(state.map);
        } else {
            state.curLine.setPath(state.curPts);
        }
        if (state.curPts.length >= 2) {
            const len = state.curLine.getLength();
            addMeasureOverlay(latlng, `<div class="measure-label total">${fmtDist(len)} · 도보 ${fmtWalk(len)}</div>`, 1.6);
        }
    } else if (state.measureMode === 'area') {
        if (!state.curPoly) {
            state.curPoly = new kakao.maps.Polygon({ path: state.curPts, strokeWeight: 2, strokeColor: '#059669', strokeOpacity: 0.9, fillColor: '#059669', fillOpacity: 0.2 });
            state.curPoly.setMap(state.map);
        } else {
            state.curPoly.setPath(state.curPts);
        }
        if (state.curPts.length >= 3) {
            if (state.curAreaLabel) { state.curAreaLabel.setMap(null); state.curOverlays = state.curOverlays.filter(o => o !== state.curAreaLabel); }
            state.curAreaLabel = addMeasureOverlay(latlng, `<div class="measure-label area-total">${fmtArea(state.curPoly.getArea())}</div>`, 1.6);
        }
    }
}

// 현재 그리던 도형을 확정(고정)하고 새로 그릴 수 있게 초기화 (모드는 유지)
// 확정된 도형의 마지막 값 라벨에 × 버튼이 붙어 개별 삭제 가능
function finishMeasure() {
    if (!state.measureMode) return;
    if (!state.curPts.length) return;
    const mode = state.measureMode;
    const complete = (mode === 'dist' && state.curPts.length >= 2) || (mode === 'area' && state.curPts.length >= 3);

    const group = [];
    if (state.curLine) group.push(state.curLine);
    if (state.curPoly) group.push(state.curPoly);
    group.push(...state.curOverlays);

    if (!complete) {
        // 점이 모자란 미완성 도형은 그냥 제거
        group.forEach(o => o.setMap(null));
    } else {
        // 마지막 값 라벨에 삭제(×) 버튼 부착
        const labelOv = [...state.curOverlays].reverse().find(o =>
            o.opts && o.opts.content && o.opts.content.classList &&
            (o.opts.content.classList.contains('total') || o.opts.content.classList.contains('area-total')));
        if (labelOv) {
            const el = labelOv.opts.content;
            el.classList.add('closable');
            const x = document.createElement('span');
            x.className = 'measure-close';
            x.textContent = '×';
            x.title = '이 측정 삭제';
            x.onclick = (e) => {
                e.stopPropagation();
                group.forEach(o => o.setMap(null));
                state.doneShapes[mode] = state.doneShapes[mode].filter(g => g !== group);
            };
            el.appendChild(x);
        }
        state.doneShapes[mode].push(group);
        // 면적 확정 시: 영역 내 건물 노후도 자동 분석
        if (mode === 'area' && window.VWORLD_KEY) {
            const ring = state.curPts.map(p => [p.getLng(), p.getLat()]);
            const drawnArea = state.curPoly ? state.curPoly.getArea() : 0;
            analyzeAreaBuildings(ring, drawnArea);
        }
    }
    state.curPts = []; state.curLine = null; state.curPoly = null; state.curOverlays = []; state.curAreaLabel = null;
}

function clearMeasure(mode) {
    state.doneShapes[mode].forEach(group => group.forEach(o => o.setMap(null)));
    state.doneShapes[mode] = [];
}

// ==========================
// 면적 영역 노후도 분석 — 영역에 절반 이상 걸친 건물 대상
// ==========================
function pointInRing(x, y, ring) {
    let inside = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
        const xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
        if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
}

// 건물 도형이 그린 영역에 얼마나 걸치는지 (건물 bbox 7×7 격자 샘플링)
function overlapFraction(bRing, clipRing) {
    const xs = bRing.map(p => p[0]), ys = bRing.map(p => p[1]);
    const minx = Math.min(...xs), maxx = Math.max(...xs);
    const miny = Math.min(...ys), maxy = Math.max(...ys);
    let inB = 0, inBoth = 0;
    const N = 7;
    for (let i = 0; i < N; i++) {
        for (let j = 0; j < N; j++) {
            const x = minx + (maxx - minx) * (i + 0.5) / N;
            const y = miny + (maxy - miny) * (j + 0.5) / N;
            if (pointInRing(x, y, bRing)) {
                inB++;
                if (pointInRing(x, y, clipRing)) inBoth++;
            }
        }
    }
    if (!inB) {
        const cx = xs.reduce((a, b) => a + b, 0) / xs.length, cy = ys.reduce((a, b) => a + b, 0) / ys.length;
        return pointInRing(cx, cy, clipRing) ? 1 : 0;
    }
    return inBoth / inB;
}

function analyzeAreaBuildings(ring, drawnArea) {
    const statusEl = document.getElementById('status-bar');
    statusEl.textContent = '영역 노후도 분석 중...';
    const lngs = ring.map(p => p[0]), lats = ring.map(p => p[1]);
    const box = `BOX(${Math.min(...lngs)},${Math.min(...lats)},${Math.max(...lngs)},${Math.max(...lats)})`;
    const feats = [];
    const fetchPage = (page) => vworldBuildings(box, page, (resp) => {
        const ok = resp && resp.response && resp.response.status === 'OK';
        const batch = ok ? (resp.response.result.featureCollection.features || []) : [];
        feats.push(...batch);
        const total = ok && resp.response.record ? parseInt(resp.response.record.total) : 0;
        if (ok && feats.length < total && page < 3) fetchPage(page + 1);
        else renderAreaAnalysis(ring, drawnArea, feats);
    });
    fetchPage(1);
}

function renderAreaAnalysis(ring, drawnArea, feats) {
    const nowYear = new Date().getFullYear();
    const included = [];
    feats.forEach(f => {
        const bRing = f.geometry.type === 'MultiPolygon' ? f.geometry.coordinates[0][0] : f.geometry.coordinates[0];
        if (overlapFraction(bRing, ring) < 0.5) return; // 절반 이상 걸친 건물만
        const p = f.properties;
        const ym = ((p.useapr_day || '').match(/^(\d{4})/) || [])[1];
        included.push({
            year: ym ? parseInt(ym) : 0,
            tot: parseFloat(p.totalarea || 0) || 0,
            flr: parseInt(p.grnd_flr || 0) || 0
        });
    });

    const panel = document.getElementById('parcel-panel');
    const statusEl = document.getElementById('status-bar');
    if (!panel) return;
    if (!included.length) {
        statusEl.textContent = '영역 내 건물 정보 없음';
        return;
    }

    // 밴드 집계 (경과년수)
    const bands = CONFIG.AGING_BANDS.map(b => ({ ...b, n: 0 }));
    let unknown = 0, ageSum = 0, aged = 0, over30 = 0;
    let oldest = 0, newest = 0;
    included.forEach(b => {
        if (!b.year || b.year < 1800) { unknown++; return; }
        const age = nowYear - b.year;
        ageSum += age; aged++;
        if (age >= 30) over30++;
        for (const band of bands) if (age >= band.min) { band.n++; break; }
        if (!oldest || b.year < oldest) oldest = b.year;
        if (b.year > newest) newest = b.year;
    });
    const total = included.length;
    const avgAge = aged ? Math.round(ageSum / aged) : 0;
    // 비율은 '전체 동수' 기준 (정비 노후도 산정 실무와 동일 — 정보 없는 건물도 분모 포함)
    const over30pctAll = Math.round(over30 * 100 / total);
    const over30pctKnown = aged ? Math.round(over30 * 100 / aged) : 0;
    const totSum = included.reduce((a, b) => a + b.tot, 0);
    const flrs = included.filter(b => b.flr > 0);
    const avgFlr = flrs.length ? (flrs.reduce((a, b) => a + b.flr, 0) / flrs.length).toFixed(1) : '-';

    const bandRows = bands.map(b =>
        `<div class="landuse-item"><span class="legend-dot" style="background:${b.color}"></span> ${b.label}: <b>${b.n}동</b> (${Math.round(b.n * 100 / total)}%)</div>`
    ).join('') +
        (unknown ? `<div class="landuse-item"><span class="legend-dot" style="background:${CONFIG.AGING_UNKNOWN}"></span> 정보 없음: <b>${unknown}동</b> (${Math.round(unknown * 100 / total)}%)</div>` : '');

    // 재개발 노후도 참고 (통상 30년 이상 2/3 = 67%, 전체 동수 기준 — 보수적 판정)
    const redevOk = over30pctAll >= 67;

    panel.innerHTML =
        `<span class="click-addr-close" title="닫기">×</span>` +
        `<div class="click-addr-jibun">영역 노후도 분석</div>` +
        `<div class="click-addr-road">영역 ${fmtArea(drawnArea)} · 절반 이상 걸친 건물 ${total}동</div>` +
        `<div class="click-addr-parcel">` +
        `평균 경과년수 <b>${avgAge}년</b> (확인 ${aged}동 기준)<br>` +
        `30년 이상 <b>${over30pctAll}%</b> (${over30}/${total}동${unknown ? ` · 연식 확인분 기준 ${over30pctKnown}%` : ''})<br>` +
        `<span class="redev-badge ${redevOk ? 'ok' : 'no'}">정비 노후도 요건(67%) ${redevOk ? '충족' : '미달'}</span></div>` +
        `<div class="click-addr-landuse"><div class="landuse-title">경과년수 분포</div>${bandRows}</div>` +
        `<div class="click-addr-parcel">총 연면적 ${Math.round(totSum).toLocaleString()}㎡ · 평균 지상 ${avgFlr}층` +
        (oldest ? `<br>최고령 ${oldest}년 · 최신 ${newest}년` : '') + `</div>`;
    panel.querySelector('.click-addr-close').onclick = () => { panel.style.display = 'none'; };
    panel.style.display = 'block';
    statusEl.textContent = `영역 노후도 분석 완료: ${included.length}동`;
}

// ==========================
// 길찾기 — 출발/도착 클릭 → 직선거리·도보시간 + 카카오맵 길찾기 열기
// ==========================
function clearRoute() {
    state.routeOverlays.forEach(o => o.setMap(null));
    state.routeOverlays = [];
    state.routePts = [];
}

function kakaoRouteUrl(s, e) {
    return `https://map.kakao.com/link/from/출발,${s.getLat()},${s.getLng()}/to/도착,${e.getLat()},${e.getLng()}`;
}

function onRouteClick(latlng) {
    if (state.routePts.length >= 2) clearRoute();
    state.routePts.push(latlng);
    const isStart = state.routePts.length === 1;
    const pin = document.createElement('div');
    pin.className = 'route-pin ' + (isStart ? 'start' : 'end');
    pin.textContent = isStart ? '출발' : '도착';
    const ov = new kakao.maps.CustomOverlay({ position: latlng, content: pin, yAnchor: 1.3, zIndex: 1850 });
    ov.setMap(state.map);
    state.routeOverlays.push(ov);

    const statusEl = document.getElementById('status-bar');
    if (isStart) { statusEl.textContent = '길찾기: 도착지를 클릭하세요'; return; }

    const [s, e] = state.routePts;
    const line = new kakao.maps.Polyline({ path: [s, e], strokeWeight: 3, strokeColor: '#7c3aed', strokeOpacity: 0.85, strokeStyle: 'shortdash' });
    line.setMap(state.map);
    state.routeOverlays.push(line);
    const len = line.getLength();
    const mid = new kakao.maps.LatLng((s.getLat() + e.getLat()) / 2, (s.getLng() + e.getLng()) / 2);
    const lbl = document.createElement('div');
    lbl.className = 'measure-label total closable route-label';
    lbl.innerHTML = `직선 ${fmtDist(len)} · 도보 ${fmtWalk(len)} <span class="route-open">카카오맵 경로 ↗</span><span class="measure-close">×</span>`;
    lbl.querySelector('.route-open').onclick = (ev) => { ev.stopPropagation(); window.open(kakaoRouteUrl(s, e), '_blank'); };
    lbl.querySelector('.measure-close').onclick = (ev) => { ev.stopPropagation(); clearRoute(); };
    const lov = new kakao.maps.CustomOverlay({ position: mid, content: lbl, yAnchor: 1.4, zIndex: 1850 });
    lov.setMap(state.map);
    state.routeOverlays.push(lov);
    statusEl.textContent = `길찾기: 직선 ${fmtDist(len)}, 도보 약 ${fmtWalk(len)} — 카카오맵에서 상세 경로 확인`;
    // 카카오맵 길찾기 새 창 (도보/대중교통/자동차 선택 가능)
    window.open(kakaoRouteUrl(s, e), '_blank');
}

// ==========================
// 건물연령 레이어 — 화면 내 건물 폴리곤을 경과년수 색으로 (VWorld 건물통합정보)
// ==========================
function clearBldgAge() {
    state.bldgAgeOverlays.forEach(o => o.setMap(null));
    state.bldgAgeOverlays = [];
}

// 건물연령 버튼 상태: 켜짐+표시중 = 파랑(active), 켜짐+축척 초과 = 회색(on-idle), 꺼짐 = 기본
function updateBldgAgeBtn() {
    const btn = document.getElementById('bldgage-btn');
    if (!btn) return;
    const usable = state.map.getLevel() <= BLDG_AGE_MAX_LEVEL;
    btn.classList.toggle('active', state.bldgAgeOn && usable);
    btn.classList.toggle('on-idle', state.bldgAgeOn && !usable);
}

const BLDG_AGE_MAX_LEVEL = 2; // 레벨 1~2 (최대 확대 구간)에서만 표시

function refreshBldgAge() {
    const token = ++state.bldgAgeToken;
    clearBldgAge();
    updateBldgAgeBtn();
    if (!state.bldgAgeOn) return;
    const statusEl = document.getElementById('status-bar');
    if (state.map.getLevel() > BLDG_AGE_MAX_LEVEL) {
        statusEl.textContent = '건물연령: 더 확대하면 표시됩니다 (버튼 회색 = 대기 상태)';
        return;
    }
    const b = state.map.getBounds();
    const sw = b.getSouthWest(), ne = b.getNorthEast();
    const box = `BOX(${sw.getLng()},${sw.getLat()},${ne.getLng()},${ne.getLat()})`;
    statusEl.textContent = '건물연령: 건물 정보 조회 중...';

    const drawPage = (page, drawn) => {
        vworldBuildings(box, page, (resp) => {
            if (token !== state.bldgAgeToken || !state.bldgAgeOn) return; // 이동/해제됨 → 폐기
            if (!resp && page === 1) {
                // JSONP 실패 = 주로 VWorld 인증키 도메인 불일치 (폰에서 IP 접속 등)
                statusEl.textContent = `건물연령: VWorld 응답 없음 — 접속 주소(${location.hostname})가 인증키 도메인에 등록됐는지 확인`;
                return;
            }
            const ok = resp && resp.response && resp.response.status === 'OK';
            let feats = ok ? (resp.response.result.featureCollection.features || []) : [];
            // 정보 없는(회색) 건물 도형은 먼저(아래층에) 옅게 — 대장 연계된 색상 건물을 가리지 않게
            const hasYear = f => /^\d{4}/.test((f.properties.useapr_day || '').trim());
            feats = [...feats.filter(f => !hasYear(f)), ...feats.filter(hasYear)];
            feats.forEach(f => {
                const ap = (f.properties.useapr_day || '').trim();
                const year = ap.length >= 4 ? parseInt(ap.slice(0, 4)) : 0;
                const known = year >= 1800;
                const color = agingColor(year);
                const rings = f.geometry.type === 'MultiPolygon'
                    ? f.geometry.coordinates.map(p => p[0]) : [f.geometry.coordinates[0]];
                const paths = rings.map(ring => ring.map(p => new kakao.maps.LatLng(p[1], p[0])));
                const poly = new kakao.maps.Polygon({
                    path: paths, strokeWeight: known ? 1 : 0.5, strokeColor: color, strokeOpacity: known ? 0.8 : 0.4,
                    fillColor: color, fillOpacity: known ? 0.45 : 0.18, zIndex: known ? 30 : 29
                });
                poly.setMap(state.map);
                state.bldgAgeOverlays.push(poly);
                kakao.maps.event.addListener(poly, 'mouseover', () => {
                    const p = f.properties;
                    const tot = parseFloat(p.totalarea || 0);
                    state.tooltip.setContent(
                        `<div class="custom-tooltip"><div class="tooltip-header">${p.bld_nm || '건물'}</div><div class="tooltip-body">` +
                        `<div class="tooltip-row"><span>${year ? `${year}년 승인 (${new Date().getFullYear() - year}년차)` : '승인일 정보 없음'}</span></div>` +
                        (tot ? `<div class="tooltip-row"><span>연면적 ${Math.round(tot).toLocaleString()}㎡</span></div>` : '') +
                        `</div></div>`);
                    state.tooltip.setPosition(paths[0][0]);
                    state.tooltip.setMap(state.map);
                });
                kakao.maps.event.addListener(poly, 'mouseout', () => state.tooltip.setMap(null));
            });
            const total = ok && resp.response.record ? parseInt(resp.response.record.total) : 0;
            const soFar = drawn + feats.length;
            if (ok && soFar < total && page < 3) {
                drawPage(page + 1, soFar); // 최대 3,000동까지
            } else {
                statusEl.textContent = `건물연령: ${soFar.toLocaleString()}동 표시` + (total > soFar ? ` (전체 ${total.toLocaleString()}동 중 일부 — 더 확대하세요)` : '');
            }
        });
    };
    drawPage(1, 0);
}

// ==========================
// 지적도 모드: 지도 클릭 → 주소 + VWorld 필지 경계/면적/공시지가
// ==========================
function clearClickParcel() {
    const panel = document.getElementById('parcel-panel');
    if (panel) { panel.style.display = 'none'; panel.innerHTML = ''; }
    if (state.clickAddrOverlay) { state.clickAddrOverlay.setMap(null); state.clickAddrOverlay = null; }
    if (state.clickParcelPoly) { state.clickParcelPoly.setMap(null); state.clickParcelPoly = null; }
}

// VWorld JSONP 공통 호출 (키는 config.local.js — git 미포함)
function vworldJsonp(url, cb) {
    if (!window.VWORLD_KEY) { cb(null); return; }
    const cbName = '__vw' + Date.now() + Math.floor(Math.random() * 10000);
    const script = document.createElement('script');
    const cleanup = () => { delete window[cbName]; script.remove(); };
    window[cbName] = (resp) => { cleanup(); cb(resp); };
    script.onerror = () => { cleanup(); cb(null); };
    script.src = url + `&key=${window.VWORLD_KEY}&domain=${window.VWORLD_DOMAIN || 'localhost'}&callback=${cbName}`;
    document.head.appendChild(script);
}

// 연속지적도: 클릭 지점의 필지 조회
function vworldParcel(latlng, cb) {
    vworldJsonp('https://api.vworld.kr/req/data?service=data&request=GetFeature&data=LP_PA_CBND_BUBUN'
        + `&format=json&crs=EPSG:4326&size=1&geomFilter=POINT(${latlng.getLng()} ${latlng.getLat()})`, cb);
}

// 토지이용계획 속성: PNU → 용도지역지구명목록 (토지이용계획확인서 항목)
function vworldLandUse(pnu, cb) {
    vworldJsonp(`https://api.vworld.kr/ned/data/getLandUseAttr?pnu=${pnu}&format=json&numOfRows=100`, cb);
}

// GIS건물통합정보: 영역 내 건물 도형+속성 (건물연령 레이어용)
function vworldBuildings(boxStr, page, cb) {
    vworldJsonp('https://api.vworld.kr/req/data?service=data&request=GetFeature&data=LT_C_BLDGINFO'
        + `&format=json&crs=EPSG:4326&size=1000&page=${page}&geomFilter=${boxStr}`, cb);
}

// 클릭 지점의 건물 1동 조회 (필지 정보 패널용)
function vworldBuildingAt(latlng, cb) {
    vworldJsonp('https://api.vworld.kr/req/data?service=data&request=GetFeature&data=LT_C_BLDGINFO'
        + `&format=json&crs=EPSG:4326&size=1&geomFilter=POINT(${latlng.getLng()} ${latlng.getLat()})`, cb);
}

// 건축물대장 주용도/구조 코드 → 명칭 (주요 코드만, 미등재는 코드 표기)
const BLDG_USE_MAP = {
    '01000': '단독주택', '02000': '공동주택', '03000': '제1종근린생활시설', '04000': '제2종근린생활시설',
    '05000': '문화및집회시설', '06000': '종교시설', '07000': '판매시설', '08000': '운수시설',
    '09000': '의료시설', '10000': '교육연구시설', '11000': '노유자시설', '12000': '수련시설',
    '13000': '운동시설', '14000': '업무시설', '15000': '숙박시설', '16000': '위락시설',
    '17000': '공장', '18000': '창고시설', '20000': '자동차관련시설', '21000': '동식물관련시설'
};
const BLDG_STRCT_MAP = {
    '11': '벽돌구조', '12': '블록구조', '13': '석구조', '14': '기타조적구조',
    '21': '철근콘크리트구조', '22': '철골철근콘크리트구조', '29': '기타콘크리트구조',
    '31': '일반철골구조', '32': '경량철골구조', '39': '기타강구조', '41': '일반목구조', '42': '통나무구조'
};

function showClickAddress(latlng) {
    if (!state.geocoder || !state.geocoder.coord2Address) return;
    state.geocoder.coord2Address(latlng.getLng(), latlng.getLat(), (result, status) => {
        if (status !== kakao.maps.services.Status.OK || !result || !result.length) return;
        const jibun = result[0].address ? result[0].address.address_name : '';
        const road = result[0].road_address ? result[0].road_address.address_name : '';
        if (!jibun && !road) return;
        clearClickParcel();

        // 정보는 하단 고정 패널에 — 지도 위 필지 영역을 가리지 않음
        const panel = document.getElementById('parcel-panel');
        if (!panel) return;
        panel.innerHTML =
            `<span class="click-addr-close" title="닫기">×</span>` +
            `<div class="click-addr-jibun">${jibun || road}</div>` +
            (road && jibun ? `<div class="click-addr-road">${road}</div>` : '') +
            (window.VWORLD_KEY ? `<div class="click-addr-parcel">필지 조회 중...</div>` : '') +
            `<div class="click-addr-bldg" style="display:none;"></div>`;
        panel.querySelector('.click-addr-close').onclick = (e) => { e.stopPropagation(); clearClickParcel(); };
        panel.style.display = 'block';

        // 클릭 지점 건물 정보 (건물통합정보 — 용도/구조/층수/면적/승인일자)
        if (window.VWORLD_KEY) {
            vworldBuildingAt(latlng, (resp) => {
                const el = panel.querySelector('.click-addr-bldg');
                if (!el) return;
                const showEmpty = () => {
                    el.innerHTML = `<div class="landuse-title">건물 정보</div><div class="bldg-empty">해당 지점 건물 정보 없음</div>`;
                    el.style.display = 'block';
                };
                const feats = resp && resp.response && resp.response.status === 'OK'
                    ? (resp.response.result.featureCollection.features || []) : [];
                if (!feats.length) { showEmpty(); return; }
                const p = feats[0].properties;
                const num = v => { const n = parseFloat(v); return isFinite(n) && n > 0 ? n : 0; };
                const ap = (p.useapr_day || '').trim();
                const apFmt = /^\d{8}$/.test(ap) ? `${ap.slice(0, 4)}-${ap.slice(4, 6)}-${ap.slice(6, 8)}` : (ap || '');
                const rows = [];
                if ((p.bld_nm || '').trim()) rows.push(['건물명칭', p.bld_nm.trim()]);
                if ((p.dong_nm || '').trim()) rows.push(['동명칭', p.dong_nm.trim()]);
                const use = (p.usability || '').trim();
                if (use) rows.push(['건물용도', BLDG_USE_MAP[use] || `코드 ${use}`]);
                const st = (p.strct_cd || '').trim();
                if (st) rows.push(['구조', BLDG_STRCT_MAP[st] || `코드 ${st}`]);
                const gf = num(p.grnd_flr), uf = num(p.ugrnd_flr);
                if (gf || uf) rows.push(['층수', `지상 ${gf}층${uf ? ` / 지하 ${uf}층` : ''}`]);
                if (num(p.totalarea)) rows.push(['연면적', `${num(p.totalarea).toLocaleString()}㎡`]);
                if (num(p.archarea)) rows.push(['건축면적', `${num(p.archarea).toLocaleString()}㎡`]);
                if (num(p.platarea)) rows.push(['대지면적', `${num(p.platarea).toLocaleString()}㎡`]);
                if (num(p.height)) rows.push(['건물높이', `${num(p.height)}m`]);
                if (num(p.vl_rat)) rows.push(['용적률', `${num(p.vl_rat)}%`]);
                if (num(p.bc_rat)) rows.push(['건폐율', `${num(p.bc_rat)}%`]);
                if (apFmt) rows.push(['사용승인일자', apFmt + (ap.length >= 4 ? ` (${new Date().getFullYear() - parseInt(ap.slice(0, 4))}년차)` : '')]);
                if (!rows.length) { showEmpty(); return; }
                el.innerHTML = `<div class="landuse-title">건물 정보</div>` +
                    rows.map(([k, v]) => `<div class="bldg-row"><span>${k}</span><b>${v}</b></div>`).join('');
                el.style.display = 'block';
            });
        }

        // VWorld 필지 경계 + 면적 + 공시지가
        vworldParcel(latlng, (resp) => {
            const el = panel.querySelector('.click-addr-parcel');
            const feats = resp && resp.response && resp.response.status === 'OK'
                ? (resp.response.result.featureCollection.features || []) : [];
            if (!feats.length) { if (el) el.textContent = '필지 정보 없음'; return; }
            const f = feats[0];
            // MultiPolygon 외곽 링들 → 카카오 폴리곤
            const rings = f.geometry.type === 'MultiPolygon'
                ? f.geometry.coordinates.map(poly => poly[0])
                : [f.geometry.coordinates[0]];
            const paths = rings.map(ring => ring.map(p => new kakao.maps.LatLng(p[1], p[0])));
            // 이용계획(노랑)·지적도(검은 선) 위에서도 잘 보이도록 굵은 로즈색 + 진한 채움
            state.clickParcelPoly = new kakao.maps.Polygon({
                path: paths, strokeWeight: 4, strokeColor: '#e11d48', strokeOpacity: 1,
                fillColor: '#e11d48', fillOpacity: 0.3, zIndex: 300
            });
            state.clickParcelPoly.setMap(state.map);
            const area = state.clickParcelPoly.getArea();
            const jiga = parseInt(f.properties.jiga || 0);
            if (el) {
                el.innerHTML = `면적: <b>${fmtArea(area)}</b>` +
                    (jiga ? `<br>공시지가: ${jiga.toLocaleString()}원/㎡` : '');
            }

            // 토지이용계획확인서 항목 (용도지역지구명목록)
            const pnu = f.properties.pnu;
            if (pnu) {
                const luDiv = document.createElement('div');
                luDiv.className = 'click-addr-landuse';
                luDiv.textContent = '토지이용계획 조회 중...';
                panel.appendChild(luDiv);
                vworldLandUse(pnu, (lu) => {
                    const items = lu && lu.landUses && lu.landUses.field ? lu.landUses.field : [];
                    if (!items.length) { luDiv.textContent = '토지이용계획 정보 없음'; return; }
                    // 중복 제거 (같은 지구가 법령별로 반복됨)
                    const seen = new Set();
                    const rows = [];
                    items.forEach(it => {
                        const nm = (it.prposAreaDstrcCodeNm || '').trim();
                        if (!nm || seen.has(nm)) return;
                        seen.add(nm);
                        const cnflc = (it.cnflcAtNm || it.cnflcAt || '').trim();
                        rows.push(`<div class="landuse-item">${nm}${cnflc === '저촉' ? ' <span class="landuse-cnflc">저촉</span>' : ''}</div>`);
                    });
                    luDiv.innerHTML = `<div class="landuse-title">용도지역·지구 (${rows.length})</div>` + rows.join('');
                });
            }
        });
    });
}

// ==========================
// 현위치
// ==========================
function moveToCurrentLocation() {
    const statusEl = document.getElementById('status-bar');
    if (!navigator.geolocation) { statusEl.textContent = '이 브라우저는 위치 정보를 지원하지 않습니다'; return; }
    statusEl.textContent = '현재 위치 확인 중...';
    navigator.geolocation.getCurrentPosition(p => {
        const pos = new kakao.maps.LatLng(p.coords.latitude, p.coords.longitude);
        state.map.setCenter(pos);
        state.map.setLevel(4);
        if (state.geolocOverlay) state.geolocOverlay.setMap(null);
        const div = document.createElement('div');
        div.className = 'geoloc-dot';
        state.geolocOverlay = new kakao.maps.CustomOverlay({ position: pos, content: div, zIndex: 1900 });
        state.geolocOverlay.setMap(state.map);
        statusEl.textContent = '현재 위치로 이동했습니다';
        updateMap(true);
    }, () => { statusEl.textContent = '현재 위치를 가져올 수 없습니다 (브라우저 위치 권한 확인)'; }, { enableHighAccuracy: true, timeout: 8000 });
}

// ==========================
// 로드뷰
// ==========================
function openRoadview(latlng) {
    if (!state.rvClient) {
        state.rvClient = new kakao.maps.RoadviewClient();
        state.rv = new kakao.maps.Roadview(document.getElementById('roadview'));
    }
    state.rvClient.getNearestPanoId(latlng, 60, (panoId) => {
        if (panoId === null) {
            document.getElementById('status-bar').textContent = '이 위치 주변에는 로드뷰가 없습니다';
            return;
        }
        document.getElementById('roadview-panel').style.display = 'block';
        state.rv.setPanoId(panoId, latlng);
        setTimeout(() => { if (state.rv.relayout) state.rv.relayout(); }, 150);

        // 지도에 로드뷰 현재 위치 핀 표시 (로드뷰 안에서 이동하면 따라옴)
        if (!state.rvMapPin) {
            const d = document.createElement('div');
            d.className = 'rv-map-pin';
            state.rvMapPin = new kakao.maps.CustomOverlay({ position: latlng, content: d, zIndex: 1950 });
        }
        state.rvMapPin.setPosition(latlng);
        state.rvMapPin.setMap(state.map);
        centerMapForRoadview(latlng);
        if (!state.rvPinBound) {
            state.rvPinBound = true;
            kakao.maps.event.addListener(state.rv, 'position_changed', () => {
                const pos = state.rv.getPosition();
                if (!pos) return;
                if (state.rvMapPin) state.rvMapPin.setPosition(pos);
                // 지도는 고정 — 핀이 보이는 영역을 벗어났을 때만 재센터링
                if (!rvPosVisible(pos)) centerMapForRoadview(pos);
            });
        }
    });
}

function hideRvMapPin() {
    if (state.rvMapPin) state.rvMapPin.setMap(null);
}

// 로드뷰 패널이 화면을 가리므로, 위치 핀이 '보이는 영역'의 중앙에 오도록 지도 센터를 보정
// (데스크톱: 우측 50%가 로드뷰 → 좌측 절반 중앙 / 모바일: 하단 60%가 로드뷰 → 상단 40% 중앙)
function centerMapForRoadview(pos) {
    state.map.setCenter(pos);
    if (window.innerWidth > 768) {
        state.map.panBy(Math.round(window.innerWidth / 4), 0);
    } else {
        state.map.panBy(0, Math.round(window.innerHeight * 0.3));
    }
}

// 핀이 로드뷰에 가리지 않는 '보이는 지도 영역' 안에 있는지 (여유 5%)
function rvPosVisible(pos) {
    const b = state.map.getBounds();
    const sw = b.getSouthWest(), ne = b.getNorthEast();
    const lngSpan = ne.getLng() - sw.getLng(), latSpan = ne.getLat() - sw.getLat();
    let minLng = sw.getLng(), maxLng = ne.getLng(), minLat = sw.getLat(), maxLat = ne.getLat();
    if (window.innerWidth > 768) maxLng = sw.getLng() + lngSpan * 0.5;  // 좌측 절반만 보임
    else minLat = ne.getLat() - latSpan * 0.4;                          // 상단 40%만 보임
    const mLng = lngSpan * 0.05, mLat = latSpan * 0.05;
    return pos.getLng() >= minLng + mLng && pos.getLng() <= maxLng - mLng
        && pos.getLat() >= minLat + mLat && pos.getLat() <= maxLat - mLat;
}

let searchTimer = null;

function handleSearch(q) {
    const resEl = document.getElementById('search-results'); if (!q) { resEl.classList.add('hidden'); return; }
    const qLower = q.toLowerCase();
    const results = state.searchIndex
        .filter(i => (i.n && i.n.toLowerCase().includes(qLower)) || (i.a && i.a.toLowerCase().includes(qLower)))
        .sort((a, b) => {
            if (a.t === 'dong' && b.t !== 'dong') return -1;
            if (a.t !== 'dong' && b.t === 'dong') return 1;
            return 0;
        })
        .slice(0, 15);

    renderSearchResults(results, (state.lastAddrQuery === q) ? state.lastAddrResults : []);

    // 카카오 주소 지오코딩 병행 (디바운스) — 매물 인덱스에 없는 임의 주소도 위치 검색
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
        if (!state.geocoder) return;
        state.geocoder.addressSearch(q, (result, status) => {
            if (document.getElementById('search-input').value !== q) return; // 최신 입력만 반영
            const addrs = (status === kakao.maps.services.Status.OK && result ? result : [])
                .slice(0, 3)
                .map(r => ({
                    label: r.address_name,
                    road: r.road_address ? r.road_address.address_name : '',
                    x: parseFloat(r.x), y: parseFloat(r.y)
                }));
            state.lastAddrQuery = q;
            state.lastAddrResults = addrs;
            renderSearchResults(results, addrs);
        });
    }, 300);
}

function renderSearchResults(indexResults, addrResults) {
    const resEl = document.getElementById('search-results');
    resEl.innerHTML = '';
    // 1) 지도 위치(주소) 결과 — 매물 유무와 무관하게 해당 위치로 이동
    (addrResults || []).forEach(a => {
        const li = document.createElement('li');
        li.className = 'search-item addr-result';
        li.innerHTML = `<span class="badge-addr">주소</span> <span class="search-item-name">${a.label}</span>` +
            (a.road && a.road !== a.label ? `<div class="search-item-addr">${a.road}</div>` : '');
        li.onclick = () => goToAddress(a.y, a.x, a.label);
        resEl.appendChild(li);
    });
    // 2) 매물/법정동 인덱스 결과
    (indexResults || []).forEach(r => {
        const li = document.createElement('li');
        if (r.t === 'dong') {
            li.className = 'search-item dong-result';
            li.innerHTML = `<span class="badge-dong">법정동</span> <span class="search-item-name">${r.n}</span>`;
            li.onclick = () => goToDong(r.n, r.c[1], r.c[0]);
        } else {
            li.className = 'search-item';
            li.innerHTML = `<div class="search-item-name">${r.n}</div><div class="search-item-addr">${r.a || ''}</div>`;
            li.onclick = () => goToLocation(r.c[1], r.c[0], r.n, r.a || '');
        }
        resEl.appendChild(li);
    });
    if (!resEl.children.length) resEl.innerHTML = '<li class="search-item">결과 없음</li>';
    resEl.classList.remove('hidden');
}

// 주소 검색 결과 선택 → 지도 이동 + 위치 핀 (핀 클릭 시 제거)
function goToAddress(lat, lng, label) {
    document.getElementById('search-results').classList.add('hidden');
    document.getElementById('search-input').value = label;
    const pos = new kakao.maps.LatLng(lat, lng);
    state.map.setCenter(pos);
    state.map.setLevel(3);
    if (state.searchPin) state.searchPin.setMap(null);
    const div = document.createElement('div');
    div.className = 'search-pin';
    div.innerHTML = `<div class="search-pin-label">${label}</div><div class="search-pin-dot"></div>`;
    div.onpointerdown = (ev) => markOverlayClick(ev);
    div.onclick = (ev) => { markOverlayClick(ev); if (state.searchPin) { state.searchPin.setMap(null); state.searchPin = null; } };
    state.searchPin = new kakao.maps.CustomOverlay({ position: pos, content: div, yAnchor: 1.0, zIndex: 1800 });
    state.searchPin.setMap(state.map);
    updateMap(true);
}

function goToDong(name, lat, lng) { state.map.setCenter(new kakao.maps.LatLng(lat, lng)); state.map.setLevel(6); document.getElementById('search-results').classList.add('hidden'); document.getElementById('search-input').value = name; updateMap(true); }
function goToLocation(lat, lng, name, addr) {
    state.map.setCenter(new kakao.maps.LatLng(lat, lng));
    state.map.setLevel(4);
    document.getElementById('search-results').classList.add('hidden');
    document.getElementById('search-input').value = name;
    updateMap(true).then(() => {
        setTimeout(() => {
            // 이름+주소로 정확 매칭 (상가는 '업무' 같은 이름이 중복됨), 없으면 이름만으로
            const item = state.allLoadedData.find(i => i.name === name && (!addr || i.address === addr))
                || state.allLoadedData.find(i => i.name === name);
            if (item) {
                state.selectedComplex = item;
                state.selectedArea = null;
                renderComplexDetail();
                updateMap(true);
            }
        }, 300);
    });
}
function clearOverlays() { state.overlays.forEach(o => o.setMap(null)); state.overlays = []; closeClusterPicker(); }
