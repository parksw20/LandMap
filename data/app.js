/**
 * God Slayer: Abyss - 부동산 실거래가 시각화 (Fixed Rendering Version)
 * 역할: 데이터 구조 변경에 따른 필터링 및 렌더링 로직 최종 보정
 */

const state = {
    map: null,
    geocoder: null,
    levelData: {}, 
    detailShards: {}, 
    overlays: [],
    tooltip: null,
    currentLevel: 0,
    selectedMonths: [], // 초기값 비움
    selectedType: 'apt',
    activeGungus: null, 
    filters: { '매매': true, '전세': true, '월세': true },
    hoveredItem: null,
    selectedComplex: null,
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
    await renderMonthFilters(); // 여기서 state.selectedMonths가 설정됨
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
        r.onchange = (e) => { 
            state.selectedType = e.target.value; 
            state.selectedComplex = null; 
            document.getElementById('data-section').style.display = 'none'; 
            updateMap(true); 
        };
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
}

async function renderMonthFilters() {
    try {
        const res = await fetch('./manifest.json?v=' + Date.now());
        if (!res.ok) throw new Error();
        const ymList = await res.json();
        const listEl = document.getElementById('dataset-list');
        listEl.innerHTML = '';
        
        if (ymList.length > 0 && state.selectedMonths.length === 0) {
            state.selectedMonths = [ymList[0]];
        }

        ymList.forEach(ym => {
            const label = `${ym.substring(0,4)}.${ym.substring(4,6)}`;
            const wrapper = document.createElement('label');
            wrapper.className = 'filter-chip';
            wrapper.innerHTML = `<input type="checkbox" name="datasetMonth" value="${ym}" ${state.selectedMonths.includes(ym) ? 'checked' : ''}> <span class="chip-label">${label}</span>`;
            wrapper.querySelector('input').onchange = (e) => {
                const checked = document.querySelectorAll('input[name="datasetMonth"]:checked');
                if (checked.length > 3) { alert('최대 3개월까지만 선택 가능합니다.'); e.target.checked = false; return; }
                state.selectedMonths = Array.from(checked).map(el => el.value);
                updateMap(true);
            };
            listEl.appendChild(wrapper);
        });
    } catch (e) {
        document.getElementById('dataset-list').innerHTML = '<div class="loading-text">데이터 준비 중...</div>';
        setTimeout(renderMonthFilters, 3000);
    }
}

async function updateMap(force = false) {
    const zoom = state.map.getLevel();
    let newLevel = 1;
    if (zoom >= CONFIG.ZOOM_LEVELS[1]) newLevel = 1;
    else if (zoom >= CONFIG.ZOOM_LEVELS[2]) newLevel = 2;
    else if (zoom >= CONFIG.ZOOM_LEVELS[3]) newLevel = 3;
    else newLevel = 4;

    if (newLevel === 4) {
        const bounds = state.map.getBounds();
        const gungusInView = new Set();
        for (const ym of state.selectedMonths) {
            const gunguSummary = await loadSummaryData(ym, 2);
            gunguSummary.forEach(g => {
                const pos = new kakao.maps.LatLng(g.coords[1], g.coords[0]);
                if (bounds.contain(pos)) {
                    const gunguKey = `${g.sido}_${g.name.split(' ')[1] || g.name}`.replace(/ /g, '_');
                    gungusInView.add(gunguKey);
                }
            });
        }

        const center = state.map.getCenter();
        state.geocoder.coord2RegionCode(center.getLng(), center.getLat(), async (result, status) => {
            if (status === kakao.maps.services.Status.OK) {
                const reg = result.find(r => r.region_type === 'H' || r.region_type === 'B');
                const centerGungu = `${reg.region_1depth_name}_${reg.region_2depth_name}`.replace(/ /g, '_');
                gungusInView.add(centerGungu);

                const gunguList = Array.from(gungusInView);
                const gunguKeyStr = gunguList.sort().join('|');

                if (state.activeGungus !== gunguKeyStr || state.currentLevel !== 4 || force) {
                    state.activeGungus = gunguKeyStr;
                    state.currentLevel = 4;
                    const mergedData = await fetchAndMergeData(4, gunguList);
                    renderMarkers(mergedData, 4);
                }
            }
        });
    } else {
        if (state.currentLevel === newLevel && !force) return;
        state.currentLevel = newLevel; state.activeGungus = null;
        const mergedData = await fetchAndMergeData(newLevel);
        renderMarkers(mergedData, newLevel);
    }
}

async function fetchAndMergeData(level, gunguList = []) {
    const allResults = [];
    if (state.selectedMonths.length === 0) return [];

    for (const ym of state.selectedMonths) {
        if (level === 4) {
            for (const gunguKey of gunguList) {
                const data = await loadDetailShard(ym, gunguKey);
                allResults.push(...data);
            }
        } else {
            const data = await loadSummaryData(ym, level);
            allResults.push(...data);
        }
    }

    const mergedMap = new Map();
    allResults.forEach(item => {
        const key = level === 4 ? (item.address + item.name) : item.name;
        if (!mergedMap.has(key)) {
            mergedMap.set(key, JSON.parse(JSON.stringify(item)));
        } else {
            const ex = mergedMap.get(key);
            ex.stats.total += item.stats.total;
            ['sale', 'jeonse', 'monthly'].forEach(t => {
                if (!item.stats[t]) return;
                if (!ex.stats[t]) { ex.stats[t] = JSON.parse(JSON.stringify(item.stats[t])); return; }
                ex.stats[t].count += item.stats[t].count;
                const r1 = ex.stats[t].range, r2 = item.stats[t].range;
                ex.stats[t].range = [Math.min(r1[0], r2[0]), Math.max(r1[1], r2[1])];
                // 대표값은 더 많은 쪽을 따름 (단순 평균 대신)
                if (item.stats[t].count > ex.stats[t].count / 2) {
                    ex.stats[t].rep_area = item.stats[t].rep_area;
                    ex.stats[t].rep_avg_price = item.stats[t].rep_avg_price;
                }
            });
            if (level === 4 && item.deals) ex.deals.push(...item.deals);
        }
    });
    state.allLoadedData = Array.from(mergedMap.values());
    return state.allLoadedData;
}

async function loadSummaryData(ym, level) {
    const cacheKey = `${ym}_${state.selectedType}_${level}`;
    if (state.levelData[cacheKey]) return state.levelData[cacheKey];
    const fileMap = { 1: 'summary_sido.json', 2: 'summary_gungu.json', 3: 'summary_dong.json' };
    const path = `./hierarchy/${ym}/${state.selectedType}/${fileMap[level]}`;
    try {
        const res = await fetch(path);
        if (!res.ok) return [];
        const data = await res.json();
        state.levelData[cacheKey] = data;
        return data;
    } catch (e) { return []; }
}

async function loadDetailShard(ym, gunguKey) {
    const cacheKey = `${ym}_${state.selectedType}_${gunguKey}`;
    if (state.detailShards[cacheKey]) return state.detailShards[cacheKey];
    const path = `./hierarchy/${ym}/${state.selectedType}/details/${gunguKey}.json`;
    try {
        const res = await fetch(path);
        if (!res.ok) return [];
        const data = await res.json();
        state.detailShards[cacheKey] = data;
        return data;
    } catch (e) { return []; }
}

function renderMarkers(data, level) {
    clearOverlays();
    const bounds = state.map.getBounds();
    
    // 필터링 로직 보강
    const filtered = data.filter(item => {
        const s = item.stats;
        const hasSale = state.filters['매매'] && s.sale && s.sale.count > 0;
        const hasJeonse = state.filters['전세'] && s.jeonse && s.jeonse.count > 0;
        const hasMonthly = state.filters['월세'] && s.monthly && s.monthly.count > 0;
        return hasSale || hasJeonse || hasMonthly;
    });

    filtered.forEach(item => {
        const pos = new kakao.maps.LatLng(item.coords[1], item.coords[0]);
        if (level === 4 && !bounds.contain(pos)) return;
        
        const content = createOverlayContent(item, level);
        const overlay = new kakao.maps.CustomOverlay({ position: pos, content: content, yAnchor: 1.0 });
        overlay.setMap(state.map);
        state.overlays.push(overlay);

        content.onclick = () => {
            if (level === 4) { state.selectedComplex = item; renderComplexDetail(); }
            else { handleLevelMove(item, level); }
        };
        content.onmouseenter = () => {
            const key = `${level}_${item.name}`;
            if (state.hoveredItem === key) return;
            state.hoveredItem = key;
            showTooltip(item, level, pos);
        };
        content.onmouseleave = () => { state.hoveredItem = null; state.tooltip.setMap(null); };
    });
    document.getElementById('status-bar').textContent = `${level}단계: ${filtered.length}건 표시 중`;
}

function createOverlayContent(item, level) {
    const div = document.createElement('div');
    div.className = `level-marker level-${level}`;
    const themeColor = CONFIG.TYPE_COLORS[state.selectedType] || '#2563eb';
    
    let targetType = "";
    if (state.filters['매매'] && item.stats.sale) targetType = "sale";
    else if (state.filters['전세'] && item.stats.jeonse) targetType = "jeonse";
    else if (state.filters['월세'] && item.stats.monthly) targetType = "monthly";

    const typeLabel = { "sale": "매매", "jeonse": "전세", "monthly": "월세" }[targetType] || "";
    const stats = item.stats[targetType];
    
    let label = "", subLabel = "";
    if (level === 4) {
        if (stats) {
            label = `${Math.round(stats.rep_area * 0.3025)}평`;
            subLabel = formatPrice(stats.rep_avg_price);
        } else {
            label = "내역없음"; subLabel = "-";
        }
    } else {
        label = (level === 2) ? (item.name.split(' ')[1] || item.name) : item.name;
        if (stats) {
            subLabel = `[${typeLabel}] ${Math.round(stats.rep_area * 0.3025)}평 ${formatPrice(stats.rep_avg_price)}`;
        } else {
            subLabel = "내역없음";
        }
    }

    div.innerHTML = `
        <div class="marker-body" style="background:${themeColor}">
            <span class="marker-label">${label}</span>
            <span class="marker-count" style="font-size:10px">${subLabel}</span>
        </div>
        <div class="marker-arrow" style="border-top-color:${themeColor}"></div>
    `;
    return div;
}

function handleLevelMove(item, level) {
    const targetZoom = (level === 1) ? 8 : (level === 2 ? 6 : 4);
    state.map.setCenter(new kakao.maps.LatLng(item.coords[1], item.coords[0]));
    state.map.setLevel(targetZoom, { animate: true });
}

function showTooltip(item, level, pos) {
    const stats = item.stats;
    const fmtR = (s) => (!s) ? "" : (s.range[0] === s.range[1] ? formatPrice(s.range[0]) : `${formatPrice(s.range[0])}~${formatPrice(s.range[1])}`);
    const row = (type, key, cls) => (state.filters[type] && stats[key]) ? `<div class="tooltip-row ${cls}"><span>${type}</span><span>${stats[key].count}건</span><b>${fmtR(stats[key])}</b></div>` : "";
    
    state.tooltip.setContent(`
        <div class="custom-tooltip">
            <div class="tooltip-header">${item.name}</div>
            <div class="tooltip-body">
                ${row('매매', 'sale', 'sale')}
                ${row('전세', 'jeonse', 'jeonse')}
                ${row('월세', 'monthly', 'monthly')}
            </div>
        </div>
    `);
    state.tooltip.setPosition(pos);
    state.tooltip.setMap(state.map);
}

function formatPrice(val) {
    if (val >= 10000) { const eok = val / 10000; return `${Math.round(eok * 10) / 10}억`; }
    return val.toLocaleString() + '만';
}

function renderComplexDetail() {
    const item = state.selectedComplex; if (!item) return;
    const sidePanel = document.getElementById('data-section');
    const dataList = document.getElementById('data-list');
    document.getElementById('data-title').textContent = item.name;
    sidePanel.style.display = 'block'; document.getElementById('control-panel').classList.remove('collapsed');
    dataList.innerHTML = '';
    
    const priority = { '매매': 1, '전세': 2, '월세': 3 };
    const filteredDeals = item.deals.filter(d => state.filters[d.type]);
    
    filteredDeals.sort((a, b) => {
        if (priority[a.type] !== priority[b.type]) return priority[a.type] - priority[b.type];
        if (a.date !== b.date) return b.date.localeCompare(a.date);
        return a.price - b.price;
    });

    filteredDeals.forEach(deal => {
        const card = document.createElement('div');
        card.className = `data-card card-${deal.type === '전세' ? 'jeonse' : (deal.type === '월세' ? 'monthly' : 'sale')}`;
        let info = `전용 ${deal.area}㎡${deal.land > 0 ? ' | 대지 ' + deal.land + '㎡' : ''}${deal.floor && deal.floor !== "nan" ? ' | ' + deal.floor + '층' : ''}`;
        let dongInfo = (deal.dong && deal.dong !== "nan" && deal.dong !== "") ? `<div class="card-row-highlight">${deal.dong}동</div>` : "";

        card.innerHTML = `
            <div class="card-title-row"><span class="card-badge">${deal.type}</span><span class="card-date">${deal.date || ''}</span></div>
            <div class="card-price-row"><span class="card-price">${formatPrice(deal.price)}${deal.rent > 0 ? ' / ' + deal.rent : ''}</span></div>
            <div class="card-row-main">${info}</div>
            ${dongInfo}
            ${deal.period && deal.period !== "nan" && deal.period !== "" ? `<div class="card-row-sub">임차기간: ${deal.period}</div>` : ''}
            ${deal.renew && deal.renew !== "nan" && deal.renew !== "" ? `<div class="card-row-sub">갱신여부: ${deal.renew}</div>` : ''}
            ${deal.p_dep > 0 ? `<div class="card-row-sub">종전: ${formatPrice(deal.p_dep)}${deal.p_rent > 0 ? ' / ' + deal.p_rent : ''}</div>` : ''}
        `;
        dataList.appendChild(card);
    });
    if (dataList.innerHTML === '') dataList.innerHTML = '<div class="empty-state">해당 필터에 맞는 거래 내역이 없습니다.</div>';
}

function handleSearch(q) {
    const resEl = document.getElementById('search-results'); if (!q) { resEl.classList.add('hidden'); return; }
    const matches = state.allLoadedData.filter(i => i.name.includes(q)).slice(0, 10);
    if (matches.length > 0) {
        resEl.innerHTML = matches.map(m => `<li class="search-item" onclick="goToLocation(${m.coords[1]}, ${m.coords[0]}, '${m.name}')">${m.name}</li>`).join('');
        resEl.classList.remove('hidden');
    } else { resEl.innerHTML = '<li class="search-item">결과 없음</li>'; }
}

function goToLocation(lat, lng, name) { state.map.setCenter(new kakao.maps.LatLng(lat, lng)); state.map.setLevel(4); document.getElementById('search-results').classList.add('hidden'); document.getElementById('search-input').value = name; updateMap(true); }
function clearOverlays() { state.overlays.forEach(o => o.setMap(null)); state.overlays = []; }
