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
    cadastralOn: false
};

const CONFIG = {
    ZOOM_LEVELS: { 1: 9, 2: 7, 3: 5, 4: 0 },
    TYPE_COLORS: {
        'apt': '#2563eb', 'rh': '#16a34a', 'sh': '#ef4444', 'off': '#06b6d4',
        'nrg': '#f59e0b', 'land': '#65a30d', 'silv': '#8b5cf6', 'indu': '#64748b'
    },
    // 전월세(전세/월세) 실거래가 제공되는 유형. 나머지는 국토부가 매매만 공개함.
    RENT_SUPPORTED: new Set(['apt', 'rh', 'sh', 'off']),
    // 정비사업 추진단계별 색 (초기 → 착공 순)
    REDEV_STAGES: ['구역지정', '추진위', '조합설립', '건축심의', '사업시행', '관리처분', '착공'],
    REDEV_COLORS: {
        '구역지정': '#9ca3af', '추진위': '#f59e0b', '조합설립': '#f97316',
        '건축심의': '#06b6d4', '사업시행': '#3b82f6', '관리처분': '#8b5cf6', '착공': '#ef4444'
    }
};

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

async function init() {
    state.geocoder = new kakao.maps.services.Geocoder();
    const mapContainer = document.getElementById('map');
    state.map = new kakao.maps.Map(mapContainer, { center: new kakao.maps.LatLng(37.5665, 126.9780), level: 5 });
    
    const zoomControl = new kakao.maps.ZoomControl();
    state.map.addControl(zoomControl, kakao.maps.ControlPosition.RIGHT);
    
    state.tooltip = new kakao.maps.CustomOverlay({ zIndex: 1000, clickable: false, xAnchor: 0.5, yAnchor: 1.5 });

    setupEventListeners();
    applyTxAvailability();
    await renderMonthSelect();
    await loadGlobalSearchIndex();
    
    const baseSelect = document.getElementById('base-month-select');
    if (baseSelect && baseSelect.value) {
        state.selectedMonths = [baseSelect.value];
        updateMap(true);
    }
}

function setupEventListeners() {
    kakao.maps.event.addListener(state.map, 'zoom_changed', () => { state.tooltip.setMap(null); updateMap(); });
    kakao.maps.event.addListener(state.map, 'dragend', () => { if (state.currentLevel === 4) updateMap(true); });
    
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

    const cadastralBtn = document.getElementById('cadastral-btn');
    if (cadastralBtn) cadastralBtn.onclick = () => {
        state.cadastralOn = !state.cadastralOn;
        cadastralBtn.classList.toggle('active', state.cadastralOn);
        if (state.cadastralOn) state.map.addOverlayMapTypeId(kakao.maps.MapTypeId.USE_DISTRICT);
        else state.map.removeOverlayMapTypeId(kakao.maps.MapTypeId.USE_DISTRICT);
    };

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

    const redevChk = document.getElementById('show-redev');
    if (redevChk) redevChk.onchange = (e) => toggleRedev(e.target.checked);

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
            document.getElementById('data-section').style.display = 'none';
            document.getElementById('control-panel').classList.remove('full-screen');
            state.selectedComplex = null;
            updateMap(true);
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
        div.onclick = () => showRedevDetail(z, color);
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
    controlPanel.classList.remove('collapsed');
    if (window.innerWidth <= 768) controlPanel.classList.add('full-screen');
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
            const bounds = state.map.getBounds(), gungusInView = new Set();
            for (const ym of state.selectedMonths) {
                (await loadSummaryData(ym, 2)).forEach(g => { if (bounds.contain(new kakao.maps.LatLng(g.coords[1], g.coords[0]))) gungusInView.add(`${g.sido}_${g.name.split(' ')[1] || g.name}`.replace(/ /g, '_')); });
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
        content.onclick = () => {
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

function createOverlayContent(item, level, groupCount = 1) {
    const isSelected = state.selectedComplex && state.selectedComplex.name === item.name && state.selectedComplex.address === item.address;
    const div = document.createElement('div');
    div.className = `level-marker level-${level} ${isSelected ? 'selected' : ''}`;
    const themeColor = CONFIG.TYPE_COLORS[state.selectedType] || '#2563eb';
    let targetType = state.filters['매매'] && item.stats.sale ? "sale" : (state.filters['전세'] && item.stats.jeonse ? "jeonse" : (state.filters['월세'] && item.stats.monthly ? "monthly" : ""));
    const stats = item.stats[targetType]; let label = "", subLabel = "";
    if (level === 4) { 
        if (stats) { label = state.displayUnit === 'pyeong' ? `${Math.round(stats.rep_area * 0.3025)}평` : `${Math.round(stats.rep_area)}㎡`; subLabel = formatPrice(stats.rep_avg_price); } 
        else { label = "내역없음"; subLabel = "-"; } 
    } else { label = (level === 2) ? (item.name.split(' ')[1] || item.name) : item.name; subLabel = stats ? `${state.displayUnit === 'pyeong' ? Math.round(stats.rep_area * 0.3025)+'평' : Math.round(stats.rep_area)+'㎡'} ${formatPrice(stats.rep_avg_price)}` : "내역없음"; }
    
    const markerBg = isSelected ? 'linear-gradient(135deg, #1e3a8a, #3b82f6)' : themeColor;
    const badge = groupCount > 1 ? `<div class="marker-badge">${groupCount}</div>` : '';
    div.innerHTML = `${badge}<div class="marker-body" style="background:${markerBg}"><span class="marker-label">${label}</span><span class="marker-count" style="font-size:10px">${subLabel}</span></div><div class="marker-arrow" style="border-top-color:${isSelected ? '#1e3a8a' : themeColor}"></div>`;
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
    header.querySelector('.picker-close').onclick = (e) => { e.stopPropagation(); closeClusterPicker(); };
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
            e.stopPropagation();
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
// 반경 동심원 (선택 장소 기준 100m 간격)
// ==========================
function drawRadius() {
    state.radiusOverlays.forEach(o => o.setMap(null));
    state.radiusOverlays = [];
    if (!state.radiusOn) return;
    const c = state.selectedComplex
        ? new kakao.maps.LatLng(state.selectedComplex.coords[1], state.selectedComplex.coords[0])
        : state.map.getCenter();
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
    state.tooltip.setContent(`<div class="custom-tooltip"><div class="tooltip-header">${item.name}</div><div class="tooltip-body">${row('매매', 'sale', 'sale')}${row('전세', 'jeonse', 'jeonse')}${row('월세', 'monthly', 'monthly')}</div></div>`);
    state.tooltip.setPosition(pos); state.tooltip.setMap(state.map);
}

function formatPrice(val) { if (val >= 10000) return `${Math.round(val / 1000) / 10}억`; return val.toLocaleString() + '만'; }

function renderComplexDetail() {
    const item = state.selectedComplex; if (!item || !item.deals) return;
    const sidePanel = document.getElementById('data-section'), dataList = document.getElementById('data-list'), areaFilter = document.getElementById('area-filter');
    sidePanel.scrollTop = 0; document.getElementById('data-title').textContent = item.name;
    // 주소 표시 (건물명과 주소가 같으면 중복 생략)
    const addrEl = document.getElementById('data-address');
    if (addrEl) addrEl.textContent = (item.address && item.address !== item.name) ? item.address : '';
    // 반경 표시가 켜져 있으면 새 선택 기준으로 다시 그림
    if (state.radiusOn) drawRadius();
    
    // 모바일에서만 전체 화면 활성화
    const controlPanel = document.getElementById('control-panel');
    controlPanel.classList.remove('collapsed');
    if (window.innerWidth <= 768) {
        controlPanel.classList.add('full-screen');
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
    dataList.innerHTML = ''; const priority = { '매매': 1, '전세': 2, '월세': 3 };
    
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
        card.innerHTML = `<div class="card-title-row"><span class="card-badge">${deal.type}</span><span class="card-date">${deal.date || ''}</span></div><div class="card-price-row"><span class="card-price">${formatPrice(deal.price || 0)}${deal.rent > 0 ? ' / ' + deal.rent : ''}</span></div><div class="card-row-main">${info}</div>${addrInfo}${dongInfo}${(deal.period && deal.period !== "nan") ? `<div class="card-row-sub">임차기간: ${deal.period}</div>` : ''}${(deal.renew && deal.renew !== "nan") ? `<div class="card-row-sub">갱신여부: ${deal.renew}</div>` : ''}${(deal.p_dep && deal.p_dep > 0) ? `<div class="card-row-sub">종전: ${formatPrice(deal.p_dep)}${deal.p_rent > 0 ? ' / ' + deal.p_rent : ''}</div>` : ''}`;
        dataList.appendChild(card);
    });
    if (filtered.length === 0) dataList.innerHTML = '<div class="empty-state">해당 필터에 맞는 거래 내역이 없습니다.</div>';
}

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
        .slice(0, 20);
    if (results.length > 0) {
        resEl.innerHTML = results.map(r => r.t === 'dong' ? `<li class="search-item dong-result" onclick="goToDong('${r.n}', ${r.c[1]}, ${r.c[0]})"><span class="badge-dong">법정동</span> <span class="search-item-name">${r.n}</span></li>` : `<li class="search-item" onclick="goToLocation(${r.c[1]}, ${r.c[0]}, '${r.n}', '${(r.a || '').replace(/'/g, "\\'")}')"><div class="search-item-name">${r.n}</div><div class="search-item-addr">${r.a || ''}</div></li>`).join('');
        resEl.classList.remove('hidden');
    } else { resEl.innerHTML = '<li class="search-item">결과 없음</li>'; resEl.classList.remove('hidden'); }
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
