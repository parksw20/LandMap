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
    globalArea: { min: 0, max: 80 },
    displayUnit: 'pyeong', // 'pyeong' | 'm2'
    hoveredItem: null,
    selectedComplex: null,
    selectedArea: null,
    searchIndex: [], 
    allLoadedData: []
};

const CONFIG = {
    ZOOM_LEVELS: { 1: 9, 2: 7, 3: 5, 4: 0 },
    TYPE_COLORS: {
        'apt': '#2563eb', 'rh': '#16a34a', 'sh': '#ef4444', 'off': '#06b6d4'
    }
};

window.onload = () => { if (typeof kakao !== 'undefined' && kakao.maps) kakao.maps.load(() => init()); };

async function init() {
    state.geocoder = new kakao.maps.services.Geocoder();
    const mapContainer = document.getElementById('map');
    state.map = new kakao.maps.Map(mapContainer, { center: new kakao.maps.LatLng(37.5665, 126.9780), level: 10 });
    state.map.addControl(new kakao.maps.ZoomControl(), kakao.maps.ControlPosition.RIGHT);
    state.tooltip = new kakao.maps.CustomOverlay({ zIndex: 1000, clickable: false, xAnchor: 0.5, yAnchor: 1.5 });

    setupEventListeners();
    await renderMonthFilters(); 
    updateMap();
}

function setupEventListeners() {
    kakao.maps.event.addListener(state.map, 'zoom_changed', () => { state.tooltip.setMap(null); updateMap(); });
    kakao.maps.event.addListener(state.map, 'dragend', () => { if (state.currentLevel === 4) updateMap(true); });
    
    document.getElementById('skyview-btn').onclick = () => {
        const type = state.map.getMapTypeId();
        state.map.setMapTypeId(type === kakao.maps.MapTypeId.ROADMAP ? kakao.maps.MapTypeId.HYBRID : kakao.maps.MapTypeId.ROADMAP);
    };

    document.querySelectorAll('input[name="housingType"]').forEach(r => {
        r.onchange = (e) => { state.selectedType = e.target.value; state.selectedComplex = null; document.getElementById('data-section').style.display = 'none'; updateMap(true); };
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

    // 단위 전환 이벤트
    const btnP = document.getElementById('unit-pyeong');
    const btnM = document.getElementById('unit-m2');
    if (btnP && btnM) {
        btnP.onclick = () => { state.displayUnit = 'pyeong'; btnP.classList.add('active'); btnM.classList.remove('active'); updateMap(true); if (state.selectedComplex) renderComplexDetail(); };
        btnM.onclick = () => { state.displayUnit = 'm2'; btnM.classList.add('active'); btnP.classList.remove('active'); updateMap(true); if (state.selectedComplex) renderComplexDetail(); };
    }

    // 전역 면적 슬라이더
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
}

async function renderMonthFilters() {
    try {
        const res = await fetch('./manifest.json?v=' + Date.now());
        const ymList = await res.json();
        const listEl = document.getElementById('dataset-list'); listEl.innerHTML = '';
        if (ymList.length > 0 && state.selectedMonths.length === 0) state.selectedMonths = [ymList[0]];
        ymList.forEach(ym => {
            const wrapper = document.createElement('label'); wrapper.className = 'filter-chip';
            wrapper.innerHTML = `<input type="checkbox" name="datasetMonth" value="${ym}" ${state.selectedMonths.includes(ym) ? 'checked' : ''}> <span class="chip-label">${ym.substring(0,4)}.${ym.substring(4,6)}</span>`;
            wrapper.querySelector('input').onchange = (e) => {
                const checked = document.querySelectorAll('input[name="datasetMonth"]:checked');
                if (checked.length > 3) { alert('최대 3개월까지만 선택 가능합니다.'); e.target.checked = false; return; }
                state.selectedMonths = Array.from(checked).map(el => el.value); updateMap(true);
            };
            listEl.appendChild(wrapper);
        });
    } catch (e) { setTimeout(renderMonthFilters, 3000); }
}

async function updateMap(force = false) {
    const zoom = state.map.getLevel();
    let newLevel = zoom >= CONFIG.ZOOM_LEVELS[1] ? 1 : (zoom >= CONFIG.ZOOM_LEVELS[2] ? 2 : (zoom >= CONFIG.ZOOM_LEVELS[3] ? 3 : 4));
    loadSearchIndex();
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
        });
    } else {
        if (state.currentLevel === newLevel && !force) return;
        state.currentLevel = newLevel; state.activeGungus = null;
        renderMarkers(await fetchAndMergeData(newLevel), newLevel);
    }
}

async function loadSearchIndex() {
    const allSearchItems = [], dongSet = new Set();
    for (const ym of state.selectedMonths) {
        (await loadSummaryData(ym, 3)).forEach(d => { if (!dongSet.has(d.name)) { allSearchItems.push({ type: 'dong', name: d.name, coords: d.coords }); dongSet.add(d.name); } });
        try {
            const res = await fetch(`./hierarchy/${ym}/${state.selectedType}/search_index.json`);
            if (res.ok) (await res.json()).forEach(i => allSearchItems.push({ type: 'complex', name: i.n, addr: i.a, coords: i.c }));
        } catch (e) {}
    }
    state.searchIndex = allSearchItems;
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
                if (!item.stats[t]) return; if (!ex.stats[t]) { ex.stats[t] = JSON.parse(JSON.stringify(item.stats[t])); return; }
                ex.stats[t].count += item.stats[t].count;
                ex.stats[t].range = [Math.min(ex.stats[t].range[0], item.stats[t].range[0]), Math.max(ex.stats[t].range[1], item.stats[t].range[1])];
                if (item.stats[t].count > ex.stats[t].count / 2) { ex.stats[t].rep_area = item.stats[t].rep_area; ex.stats[t].rep_avg_price = item.stats[t].rep_avg_price; }
            });
            if (level === 4 && item.deals) ex.deals.push(...item.deals);
        }
    });
    return (state.allLoadedData = Array.from(mergedMap.values()));
}

async function loadSummaryData(ym, level) {
    const cacheKey = `${ym}_${state.selectedType}_${level}`; if (state.levelData[cacheKey]) return state.levelData[cacheKey];
    const fileMap = { 1: 'summary_sido.json', 2: 'summary_gungu.json', 3: 'summary_dong.json' };
    try { const res = await fetch(`./hierarchy/${ym}/${state.selectedType}/${fileMap[level]}`); const data = await res.json(); return (state.levelData[cacheKey] = data); } catch (e) { return []; }
}

async function loadDetailShard(ym, gunguKey) {
    const cacheKey = `${ym}_${state.selectedType}_${gunguKey}`; if (state.detailShards[cacheKey]) return state.detailShards[cacheKey];
    try { const res = await fetch(`./hierarchy/${ym}/${state.selectedType}/details/${gunguKey}.json`); const data = await res.json(); return (state.detailShards[cacheKey] = data); } catch (e) { return []; }
}

function renderMarkers(data, level) {
    clearOverlays(); const bounds = state.map.getBounds();
    const filtered = data.filter(item => {
        const s = item.stats; let maxRepArea = 0;
        ['sale', 'jeonse', 'monthly'].forEach(t => { if (state.filters[t === 'sale' ? '매매' : (t === 'jeonse' ? '전세' : '월세')] && s[t]) maxRepArea = Math.max(maxRepArea, s[t].rep_area); });
        if (maxRepArea > 0) { const p = Math.round(maxRepArea * 0.3025); if (!(p >= state.globalArea.min && (state.globalArea.max >= 80 || p <= state.globalArea.max))) return false; }
        return (state.filters['매매'] && s.sale) || (state.filters['전세'] && s.jeonse) || (state.filters['월세'] && s.monthly);
    });
    filtered.forEach(item => {
        const pos = new kakao.maps.LatLng(item.coords[1], item.coords[0]); if (level === 4 && !bounds.contain(pos)) return;
        const content = createOverlayContent(item, level), overlay = new kakao.maps.CustomOverlay({ position: pos, content: content, yAnchor: 1.0 });
        overlay.setMap(state.map); state.overlays.push(overlay);
        content.onclick = () => { if (level === 4) { state.selectedComplex = item; state.selectedArea = null; renderComplexDetail(); } else handleLevelMove(item, level); };
        content.onmouseenter = () => { const key = `${level}_${item.name}`; if (state.hoveredItem === key) return; state.hoveredItem = key; showTooltip(item, level, pos); };
        content.onmouseleave = () => { state.hoveredItem = null; state.tooltip.setMap(null); };
    });
    document.getElementById('status-bar').textContent = `${level}단계: ${filtered.length}건 표시 중`;
}

function createOverlayContent(item, level) {
    const div = document.createElement('div'); div.className = `level-marker level-${level}`;
    const themeColor = CONFIG.TYPE_COLORS[state.selectedType] || '#2563eb';
    let targetType = state.filters['매매'] && item.stats.sale ? "sale" : (state.filters['전세'] && item.stats.jeonse ? "jeonse" : (state.filters['월세'] && item.stats.monthly ? "monthly" : ""));
    const stats = item.stats[targetType]; let label = "", subLabel = "";
    if (level === 4) { 
        if (stats) { label = state.displayUnit === 'pyeong' ? `${Math.round(stats.rep_area * 0.3025)}평` : `${Math.round(stats.rep_area)}㎡`; subLabel = formatPrice(stats.rep_avg_price); } 
        else { label = "내역없음"; subLabel = "-"; } 
    } else { label = (level === 2) ? (item.name.split(' ')[1] || item.name) : item.name; subLabel = stats ? `${state.displayUnit === 'pyeong' ? Math.round(stats.rep_area * 0.3025)+'평' : Math.round(stats.rep_area)+'㎡'} ${formatPrice(stats.rep_avg_price)}` : "내역없음"; }
    div.innerHTML = `<div class="marker-body" style="background:${themeColor}"><span class="marker-label">${label}</span><span class="marker-count" style="font-size:10px">${subLabel}</span></div><div class="marker-arrow" style="border-top-color:${themeColor}"></div>`;
    return div;
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
    sidePanel.style.display = 'block'; document.getElementById('control-panel').classList.remove('collapsed');
    const validInGlobal = item.deals.filter(d => { const p = Math.round(d.area * 0.3025); return p >= state.globalArea.min && (state.globalArea.max >= 80 || p <= state.globalArea.max); });
    const uniqueAreas = [...new Set(validInGlobal.map(d => state.displayUnit === 'pyeong' ? Math.round(d.area * 0.3025) : Math.round(d.area)))].sort((a, b) => a - b);
    areaFilter.innerHTML = '';
    if (uniqueAreas.length > 0) {
        const allChip = document.createElement('div'); allChip.className = `area-chip ${state.selectedArea === null ? 'active' : ''}`; allChip.textContent = '전체'; allChip.onclick = () => { state.selectedArea = null; renderComplexDetail(); }; areaFilter.appendChild(allChip);
        uniqueAreas.forEach(area => { const chip = document.createElement('div'); chip.className = `area-chip ${state.selectedArea === area ? 'active' : ''}`; chip.textContent = state.displayUnit === 'pyeong' ? `${area}평` : `${area}㎡`; chip.onclick = () => { state.selectedArea = area; renderComplexDetail(); }; areaFilter.appendChild(chip); });
        areaFilter.style.display = 'flex';
    } else areaFilter.style.display = 'none';
    dataList.innerHTML = ''; const priority = { '매매': 1, '전세': 2, '월세': 3 };
    let filtered = validInGlobal.filter(d => state.filters[d.type]);
    if (state.selectedArea !== null) filtered = filtered.filter(d => (state.displayUnit === 'pyeong' ? Math.round(d.area * 0.3025) : Math.round(d.area)) === state.selectedArea);
    filtered.sort((a, b) => (priority[a.type] || 99) - (priority[b.type] || 99) || b.date.localeCompare(a.date));
    filtered.forEach(deal => {
        const card = document.createElement('div'); card.className = `data-card card-${deal.type === '전세' ? 'jeonse' : (deal.type === '월세' ? 'monthly' : 'sale')}`;
        const pArea = Math.round(deal.area * 0.3025);
        // 공급면적 데이터가 없으므로 전용면적을 명확히 표기
        const info = `전용: ${pArea}평 (${deal.area}㎡)${(deal.floor && deal.floor !== "nan") ? ' | '+deal.floor+'층' : ''}`;
        const dongInfo = (deal.dong && deal.dong !== "nan" && deal.dong !== "") ? `<div class="card-row-highlight">${deal.dong}동</div>` : "";
        card.innerHTML = `<div class="card-title-row"><span class="card-badge">${deal.type}</span><span class="card-date">${deal.date || ''}</span></div><div class="card-price-row"><span class="card-price">${formatPrice(deal.price || 0)}${deal.rent > 0 ? ' / ' + deal.rent : ''}</span></div><div class="card-row-main">${info}</div>${dongInfo}${(deal.period && deal.period !== "nan") ? `<div class="card-row-sub">임차기간: ${deal.period}</div>` : ''}${(deal.renew && deal.renew !== "nan") ? `<div class="card-row-sub">갱신여부: ${deal.renew}</div>` : ''}${(deal.p_dep && deal.p_dep > 0) ? `<div class="card-row-sub">종전: ${formatPrice(deal.p_dep)}${deal.p_rent > 0 ? ' / ' + deal.p_rent : ''}</div>` : ''}`;
        dataList.appendChild(card);
    });
    if (filtered.length === 0) dataList.innerHTML = '<div class="empty-state">해당 필터에 맞는 거래 내역이 없습니다.</div>';
}

function handleSearch(q) {
    const resEl = document.getElementById('search-results'); if (!q) { resEl.classList.add('hidden'); return; }
    const results = state.searchIndex.filter(i => i.name.includes(q) || i.addr.includes(q)).slice(0, 20);
    if (results.length > 0) {
        resEl.innerHTML = results.map(r => r.type === 'dong' ? `<li class="search-item dong-result" onclick="goToDong('${r.name}', ${r.coords[1]}, ${r.coords[0]})"><span class="badge-dong">법정동</span> <span class="search-item-name">${r.name}</span></li>` : `<li class="search-item" onclick="goToLocation(${r.coords[1]}, ${r.coords[0]}, '${r.name}')"><div class="search-item-name">${r.name}</div></li>`).join('');
        resEl.classList.remove('hidden');
    } else { resEl.innerHTML = '<li class="search-item">결과 없음</li>'; resEl.classList.remove('hidden'); }
}

function goToDong(name, lat, lng) { state.map.setCenter(new kakao.maps.LatLng(lat, lng)); state.map.setLevel(6); document.getElementById('search-results').classList.add('hidden'); document.getElementById('search-input').value = name; updateMap(true); }
function goToLocation(lat, lng, name) { state.map.setCenter(new kakao.maps.LatLng(lat, lng)); state.map.setLevel(4); document.getElementById('search-results').classList.add('hidden'); document.getElementById('search-input').value = name; updateMap(true); }
function clearOverlays() { state.overlays.forEach(o => o.setMap(null)); state.overlays = []; }
