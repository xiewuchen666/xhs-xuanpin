const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

const params = new URLSearchParams(window.location.search);
const requestedView = params.get('view');
const view = ['single', 'shops', 'selection'].includes(requestedView) ? requestedView : 'single';

const pageHead = document.querySelector('#pageHead');
const toolbar = document.querySelector('#toolbar');
const notice = document.querySelector('#notice');
const content = document.querySelector('#content');

const actionOverlay = document.querySelector('#actionOverlay');
const actionProductTitle = document.querySelector('#actionProductTitle');
const actionClose = document.querySelector('#actionClose');
const actionCollect = document.querySelector('#actionCollect');
const actionPause = document.querySelector('#actionPause');
const actionSelection = document.querySelector('#actionSelection');
const actionShop = document.querySelector('#actionShop');
const actionRemove = document.querySelector('#actionRemove');

const trendOverlay = document.querySelector('#trendOverlay');
const trendProductTitle = document.querySelector('#trendProductTitle');
const trendClose = document.querySelector('#trendClose');
const trendChart = document.querySelector('#trendChart');
const trendSummary = document.querySelector('#trendSummary');
const trendNote = document.querySelector('#trendNote');
const trendTabs = [...document.querySelectorAll('[data-trend-mode]')];

const shopImportOverlay = document.querySelector('#shopImportOverlay');
const shopImportClose = document.querySelector('#shopImportClose');
const shopImportCancel = document.querySelector('#shopImportCancel');
const shopImportSubmit = document.querySelector('#shopImportSubmit');
const shopImportText = document.querySelector('#shopImportText');
const shopImportTitle = document.querySelector('#shopImportTitle');
const shopImportHint = document.querySelector('#shopImportHint');

const exportOverlay = document.querySelector('#exportOverlay');
const exportClose = document.querySelector('#exportClose');
const exportCancel = document.querySelector('#exportCancel');
const exportCsv = document.querySelector('#exportCsv');
const exportXlsx = document.querySelector('#exportXlsx');
const exportSummary = document.querySelector('#exportSummary');

const settingsOverlay = document.querySelector('#settingsOverlay');
const settingsClose = document.querySelector('#settingsClose');
const settingsCancel = document.querySelector('#settingsCancel');
const settingsSave = document.querySelector('#settingsSave');
const autoEnabledInput = document.querySelector('#autoEnabledInput');
const autoIntervalInput = document.querySelector('#autoIntervalInput');
const midnightEnabledInput = document.querySelector('#midnightEnabledInput');
const settingsRuntime = document.querySelector('#settingsRuntime');
const dockCard = document.querySelector('#dockCard');

let selectedProductId = null;
let dockTrendMode = 'daily';
let dockTrendRange = 7;
let cachedTrends = {};
let activeActionProductId = null;
let activeActionContext = 'single';
let activeTrendData = null;
let activeTrendMode = 'daily';
let allProducts = [];
let allShops = [];
let expandedShopKeys = new Set();
let productPage = 1;
let productPageSize = 30;
let shopPage = 1;
let shopPageSize = 30;
let importScope = 'shop';
let refreshInFlight = false;
const watchedImportJobs = new Set();

function showNotice(message, type = '') {
  notice.textContent = message;
  notice.className = 'notice' + (type ? ' ' + type : '');
  notice.hidden = false;
}

function hideNotice() {
  notice.hidden = true;
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: {'Content-Type': 'application/json', ...(options.headers || {})},
    ...options
  });
  let body = null;
  try { body = await response.json(); } catch (_) {}
  if (!response.ok || body?.ok === false) {
    throw new Error(body?.error || '请求失败（HTTP ' + response.status + '）');
  }
  return body;
}

function formatPrice(value) {
  return value == null ? '—' : '¥' + Number(value).toFixed(2);
}

function formatSales(value) {
  return value == null ? '—' : Number(value).toLocaleString('zh-CN');
}

function formatDelta(value) {
  if (value == null) return '—';
  const n = Number(value);
  return (n > 0 ? '+' : '') + formatSales(n);
}

function metricValue(metric) {
  return metric?.value == null ? null : Number(metric.value);
}

function metricCell(metric, positiveAccent = false) {
  if (!metric || metric.value == null) {
    const rawReason = metric?.reason || '缺少有效采样';
    const reason = esc(rawReason);
    let hint = metric?.quality === 'anomaly' ? '计数异常' : '待有效采样';
    if (rawReason.includes('回落待确认')) hint = '回落待确认';
    else if (rawReason.includes('基线已重置') || rawReason.includes('基线重置')) hint = '基线已重置';
    return '<span class="metric-value" title="' + reason + '">—</span><small class="metric-hint" title="' + reason + '">' + hint + '</small>';
  }
  const reason = esc(metric.reason || '');
  const value = Number(metric.value);
  const display = value > 0 ? '+' + formatSales(value) : formatSales(value);
  const valueClass = positiveAccent && value > 0 ? 'metric-value positive' : 'metric-value';
  return '<span class="' + valueClass + '" title="' + reason + '">' + display + '</span>';
}

function monitoredDuration(metric) {
  const hours = Number(metric?.hours);
  return !Number.isFinite(hours) || hours < 1
    ? '不足1小时'
    : (Math.round(hours * 10) / 10).toLocaleString('zh-CN') + '小时';
}

function monitoredMetricCell(metric, positiveAccent = false) {
  const base = metricCell(metric, positiveAccent);
  if (!metric?.partial || metric.value == null) return base;
  const hours = Number(metric.hours);
  // 加入后已监控24小时（或四舍五入已达24小时），就不用再标注了
  if (!Number.isFinite(hours) || hours >= 23.9 || Math.round(hours) >= 24) return base;
  const durationStr = hours < 1 ? '<1h' : (Math.round(hours * 10) / 10) + 'h';
  return base + '<small class="metric-hint" title="加入后已监控 ' + esc(monitoredDuration(metric)) + '">已监控 ' + esc(durationStr) + '</small>';
}

function rolling24Basis(metric) {
  if (metric?.value == null) return '';
  return metric.partial ? '加入后 · 已监控' + monitoredDuration(metric) : '完整24小时';
}

function totalSalesCell(product) {
  if (product.total_sales == null) {
    return '<span class="metric-value">—</span><small class="metric-hint">待有效采样</small>';
  }
  return '<span class="metric-value" title="' + esc(product.precision_label || '') + '">' +
    formatSales(product.total_sales) + '</span>';
}

function intervalHint(hours) {
  const value = Number(hours);
  if (!Number.isFinite(value) || value < 0) return '';
  const rounded = Math.round(value * 10) / 10;
  return (Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)) + 'h 区间';
}

function incrementCell(metric) {
  if (!metric || metric.value == null) return metricCell(metric);
  const base = metricCell(metric);
  const hint = intervalHint(metric.hours);
  return base + (hint ? '<small class="metric-hint" title="' + esc(hint) + '">' + esc(hint) + '</small>' : '');
}

function summaryMetric(products, key) {
  const values = products
    .filter(p => key !== 'rolling24' || !p[key]?.partial)
    .map(p => metricValue(p[key]))
    .filter(v => v != null);
  if (!values.length) return '—';
  return formatSales(values.reduce((sum, value) => sum + value, 0));
}

function formatPriceNum(val) {
  return val == null ? '—' : Number(val).toFixed(0);
}

function formatDateTime(dtStr) {
  if (!dtStr) return '—';
  const s = String(dtStr).replace('T', ' ');
  if (s.length >= 16) {
    const d = s.substring(0, 10);
    const t = s.substring(11, 16);
    return '<div style="line-height:1.35;"><div style="color:var(--ink2);font-size:12px;">' + d + '</div><div style="color:var(--ink3);font-size:11px;">' + t + '</div></div>';
  }
  return '<span style="color:var(--ink3);font-size:11px;">' + esc(s) + '</span>';
}

function formatFans(count) {
  const num = Number(count);
  if (!Number.isFinite(num) || num <= 0) return '';
  if (num >= 10000) {
    return (num / 10000).toFixed(1) + '万粉丝';
  }
  return num.toLocaleString('zh-CN') + '粉丝';
}

function getShopInfo(product) {
  const name = product.shop_name || '店铺未识别';
  const shop = (allShops || []).find(s =>
    (s.shop_id && product.shop_id && s.shop_id === product.shop_id) ||
    (s.shop_name && product.shop_name && s.shop_name === product.shop_name)
  );
  const rawRating = (shop && shop.rating != null && String(shop.rating).trim() !== '')
    ? String(shop.rating).trim()
    : (product.shop_rating != null && String(product.shop_rating).trim() !== '' ? String(product.shop_rating).trim() : null);
  const rating = (rawRating && rawRating !== '0' && rawRating !== '0.0') ? rawRating : null;
  const rawFans = (shop && shop.brand_fans_count != null) ? shop.brand_fans_count : product.brand_fans_count;
  let fans = null;
  if (rawFans != null && Number(rawFans) > 0) {
    fans = formatFans(rawFans);
  }
  return { name, rating, fans };
}

function pageHeader(title, countText, subtitle, cards) {
  pageHead.innerHTML =
    '<div class="page-title-row">' +
      '<div class="page-title-left">' +
        '<h1>' + esc(title) + '</h1>' +
        '<div class="subtitle">' + esc(subtitle) + '</div>' +
      '</div>' +
      '<div class="page-title-actions">' +
        '<button class="btn-export-primary" id="pageExportBtn" type="button">' +
          '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
          '导出数据' +
        '</button>' +
        '<button class="btn-collect-secondary" id="pageCollectBtn" type="button">' +
          '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>' +
          '立即采集' +
        '</button>' +
      '</div>' +
    '</div>' +
    '<div class="metrics-grid">' +
      cards.map(c =>
        '<div class="metric-card' + (c.filterKey !== undefined ? ' clickable-card' : '') + '"' +
          (c.filterKey !== undefined ? ' data-status-filter="' + esc(c.filterKey) + '" title="点击按状态筛选"' : '') + '>' +
          (c.iconSvg ? '<div class="metric-icon-box ' + (c.iconBoxClass || 'icon-box-red') + '">' + c.iconSvg + '</div>' : '') +
          '<div class="metric-content">' +
            '<div class="label">' + esc(c.label) + '</div>' +
            '<div class="val">' + esc(c.value) + '</div>' +
            (c.deltaHtml ? '<div class="delta">' + c.deltaHtml + '</div>' : '') +
          '</div>' +
        '</div>'
      ).join('') +
    '</div>';

  document.querySelectorAll('.metric-card[data-status-filter]').forEach(card => {
    card.addEventListener('click', () => {
      const sf = document.querySelector('#statusFilter');
      if (sf) {
        const targetVal = card.getAttribute('data-status-filter') || '';
        sf.value = (sf.value === targetVal && targetVal !== '') ? '' : targetVal;
        productPage = 1;
        renderCurrentProductList();
      }
    });
  });

  document.querySelector('#pageExportBtn')?.addEventListener('click', openExportDialog);
  document.querySelector('#pageCollectBtn')?.addEventListener('click', event => {
    if (view === 'shops') collectVisibleShopProducts(event);
    else collectVisibleProducts(event);
  });
}

function productHeader(products, selectionMode = false) {
  const todayValues = products.map(p => metricValue(p.today)).filter(v => v != null);
  const activeCount = selectionMode ? products.length : products.filter(p => p.monitor_state === 'active').length;
  const todayCount = todayValues.length ? products.filter(p => Number(p.today?.value) > 0).length : 0;
  const rollingTotal = summaryMetric(products, 'rolling24');
  const abnormalCount = products.filter(p => p.monitor_state !== 'paused' && (['warning','danger'].includes(p.health) || Boolean(p.anomaly))).length;

  const bagSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>';
  const barSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>';
  const clockSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';
  const alertSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';

  pageHeader(
    selectionMode ? '选品中心' : '单品监控',
    products.length + ' 个商品',
    selectionMode
      ? '展示已人工确认进入选品范围的商品；持续监控和指标口径与单品监控一致。'
      : '只展示你主动加入单品监控的商品；指标口径沿用已确认采集规则。',
    [
      { label: selectionMode ? '选品商品' : '监控中', value: String(activeCount), iconBoxClass: 'icon-box-red', iconSvg: bagSvg, filterKey: '' },
      { label: '今日有新增', value: todayValues.length ? String(todayCount) : '—', iconBoxClass: 'icon-box-blue', iconSvg: barSvg },
      { label: '近24h新增合计', value: rollingTotal, iconBoxClass: 'icon-box-blue', iconSvg: clockSvg },
      { label: '异常商品', value: String(abnormalCount), iconBoxClass: 'icon-box-red', iconSvg: alertSvg, filterKey: 'warning' }
    ]
  );
}

function productExternalHref(product) {
  return String(product.url || '#');
}

function productToolbar(products) {
  toolbar.innerHTML =
    '<label class="searchbox" aria-label="搜索商品或店铺">' +
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>' +
      '<input id="toolbarSearch" type="search" placeholder="搜索商品标题 / 店铺名称 / 商品链接">' +
    '</label>' +
    '<select class="selectbox" id="sortSelect" aria-label="排序方式">' +
      '<option value="today_desc">排序: 今日新增 ↓</option>' +
      '<option value="rolling24_desc">排序: 近24h新增 ↓</option>' +
      '<option value="sales_desc">排序: 累计销量 ↓</option>' +
      '<option value="updated_desc">最近更新 ↓</option>' +
    '</select>' +
    '<select class="selectbox" id="statusFilter" aria-label="状态筛选">' +
      '<option value="">状态: 全部</option>' +
      '<option value="active">状态: 正常</option>' +
      '<option value="paused">状态: 已暂停</option>' +
      '<option value="warning">状态: 异常</option>' +
    '</select>' +
    '<select class="selectbox" id="productPageSize" aria-label="每页条数">' +
      '<option value="50"' + (productPageSize === 50 ? ' selected' : '') + '>每页: 50</option>' +
      '<option value="30"' + (productPageSize === 30 ? ' selected' : '') + '>每页: 30</option>' +
      '<option value="100"' + (productPageSize === 100 ? ' selected' : '') + '>每页: 100</option>' +
    '</select>' +
    '<div class="grow"></div>' +
    '<button class="btn-tool" id="batchExportBtn" type="button">' +
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>' +
      '批量导出' +
    '</button>' +
    (view === 'single' ? '<button class="btn-tool" id="addSingleProductButton" type="button" style="color:var(--ink);font-weight:500;">＋ 添加商品</button>' : '') +
    '<button class="btn-tool" id="toolbarSettingsBtn" type="button">' +
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>' +
      '设置' +
    '</button>' +
    '<button class="btn-tool" id="refreshBtn" type="button">' +
      '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>' +
      '刷新' +
    '</button>';

  document.querySelector('#toolbarSearch').addEventListener('input', () => { productPage = 1; renderCurrentProductList(); });
  document.querySelector('#sortSelect').addEventListener('change', () => { productPage = 1; renderCurrentProductList(); });
  document.querySelector('#statusFilter').addEventListener('change', () => { productPage = 1; renderCurrentProductList(); });
  document.querySelector('#productPageSize').addEventListener('change', e => {
    productPageSize = Number(e.target.value) || 50;
    productPage = 1;
    renderCurrentProductList();
  });
  document.querySelector('#batchExportBtn').addEventListener('click', openExportDialog);
  document.querySelector('#addSingleProductButton')?.addEventListener('click', () => openProductImport('single'));
  document.querySelector('#toolbarSettingsBtn')?.addEventListener('click', openSettings);
  document.querySelector('#refreshBtn').addEventListener('click', refreshCurrentViewData);
}

function metricNumber(product, key) {
  if (key === 'sales') return product.total_sales == null ? Number.NEGATIVE_INFINITY : Number(product.total_sales);
  if (key === 'updated') return Date.parse(String(productUpdateTime(product)).replace(' ', 'T')) || 0;
  const value = product[key]?.value;
  return value == null ? Number.NEGATIVE_INFINITY : Number(value);
}

function productUpdateTime(product) {
  return product.last_attempt_status === 'failed'
    ? (product.last_attempt_at || product.last_collected_at || '')
    : (product.last_collected_at || '');
}

function filterAndSortProducts(products) {
  const search = document.querySelector('#toolbarSearch');
  const sort = document.querySelector('#sortSelect');
  const status = document.querySelector('#statusFilter');
  const term = (search?.value || '').trim().toLowerCase();
  const statusVal = status?.value || '';

  const result = products.filter(product => {
    const haystack = ((product.title || '') + ' ' + (product.shop_name || '') + ' ' + (product.url || '')).toLowerCase();
    const matchesTerm = !term || haystack.includes(term);
    const isAbnormal = ['warning', 'danger'].includes(product.health) || Boolean(product.anomaly);
    const matchesStatus = !statusVal || (
      statusVal === 'paused'
        ? product.monitor_state === 'paused'
        : (statusVal === 'warning'
            ? isAbnormal
            : (product.monitor_state === 'active' && !isAbnormal))
    );
    return matchesTerm && matchesStatus;
  });

  const sortKey = sort?.value || 'today_desc';
  if (sortKey === 'today_desc') result.sort((a,b) => (metricNumber(b,'today') || 0) - (metricNumber(a,'today') || 0));
  else if (sortKey === 'rolling24_desc') result.sort((a,b) => (metricNumber(b,'rolling24') || 0) - (metricNumber(a,'rolling24') || 0));
  else if (sortKey === 'sales_desc') result.sort((a,b) => (metricNumber(b,'sales') || 0) - (metricNumber(a,'sales') || 0));
  else result.sort((a,b) => metricNumber(b,'updated') - metricNumber(a,'updated'));
  return result;
}

function productRow(product, context) {
  const paused = product.monitor_state === 'paused';
  const selected = Number(product.in_selection_pool) === 1;
  const inShop = Number(product.in_shop_monitor) === 1;
  const isRowSelected = product.id === selectedProductId;
  const shopInfo = getShopInfo(product);

  const imgUrl = product.image_url || '';
  const imgHtml = imgUrl
    ? '<img src="' + esc(imgUrl) + '" alt="" referrerpolicy="no-referrer">'
    : '<img alt="" style="background:#F2F3F5;">';

  let shopSubParts = [];
  if (shopInfo.rating) shopSubParts.push('<span class="star-rating">★ ' + esc(shopInfo.rating) + '</span>');
  if (shopInfo.fans) shopSubParts.push('<span>' + esc(shopInfo.fans) + '</span>');
  const shopSubHtml = shopSubParts.length > 0
    ? '<div class="shop-sub">' + shopSubParts.join('<span style="color:var(--line);margin:0 2px;">|</span>') + '</div>'
    : '';

  return '<tr class="product-row ' + (isRowSelected ? 'selected-row' : '') + '" data-product-id="' + product.id + '">' +
    '<td style="width:36px;"><input type="checkbox" class="row-checkbox" ' + (isRowSelected ? 'checked' : '') + ' onclick="event.stopPropagation()"></td>' +
    '<td>' +
      '<div class="product">' +
        imgHtml +
        '<div class="copy">' +
          '<a class="product-title-link" href="' + esc(productExternalHref(product)) + '" target="_blank" rel="noopener noreferrer" title="' + esc(product.title) + '" onclick="event.stopPropagation()">' + esc(product.title) + '</a>' +
          (selected && context !== 'selection' ? '<em class="selected">已在选品中心</em>' : '') +
        '</div>' +
      '</div>' +
    '</td>' +
    '<td>' +
      '<div class="shop-cell">' +
        '<span class="shop-name" title="' + esc(shopInfo.name) + '">' + esc(shopInfo.name) + '</span>' +
        shopSubHtml +
      '</div>' +
    '</td>' +
    '<td class="num">' + formatPrice(product.price) + '</td>' +
    '<td class="num">' + totalSalesCell(product) + '</td>' +
    '<td class="num">' + metricCell(product.today, true) + '</td>' +
    '<td class="num">' + monitoredMetricCell(product.rolling24, true) + '</td>' +
    '<td class="num">' + incrementCell(product.increment) + '</td>' +
    '<td>' + formatDateTime(productUpdateTime(product)) + '</td>' +
    '<td>' +
      '<span class="status ' + (paused ? 'paused' : (product.health || 'active')) + '" title="' +
        esc(product.last_attempt_error || product.today?.reason || product.health_label || '正常') + '">' +
        esc(paused ? '● 已暂停' : ('● ' + (product.health_label || '正常'))) +
      '</span>' +
    '</td>' +
    '<td style="text-align:center;">' +
      '<div class="actions" style="justify-content:center;">' +
        '<button class="more-btn" type="button" aria-label="商品操作" title="商品操作" ' +
          'data-more-product-id="' + product.id + '" data-more-title="' + esc(product.title) + '" ' +
          'data-more-paused="' + (paused ? '1' : '0') + '" data-more-selected="' + (selected ? '1' : '0') + '" ' +
          'data-more-shop="' + (inShop ? '1' : '0') + '" data-more-context="' + esc(context) + '" onclick="event.stopPropagation()">···</button>' +
      '</div>' +
    '</td>' +
  '</tr>';
}

function renderProductTable(products, context, total) {
  const scrollWrap = document.querySelector('.tablewrap');
  const mainWrap = document.querySelector('main');
  const savedScrollTop = scrollWrap ? scrollWrap.scrollTop : null;
  const savedScrollLeft = scrollWrap ? scrollWrap.scrollLeft : null;
  const savedMainScrollTop = mainWrap ? mainWrap.scrollTop : null;

  if (!products.some(product => product.id === selectedProductId)) {
    selectedProductId = products[0]?.id ?? null;
  }
  const pager = renderProductPager(total);
  if (!products.length) {
    content.innerHTML = '<div class="empty" style="padding:40px 0;text-align:center;color:var(--ink3);">' +
      (context === 'selection' ? '选品中心还没有符合当前条件的商品。' : '没有符合当前条件的商品。') +
      '</div>' + pager;
    if (dockCard) dockCard.hidden = true;
    bindProductPager();
    return;
  }

  content.innerHTML =
    '<div class="tablewrap"><table class="product-data-table"><thead><tr>' +
    '<th style="width:36px;"></th>' +
    '<th style="min-width:200px;">商品</th>' +
    '<th style="width:130px;">店铺</th>' +
    '<th style="width:80px;">当前价格</th>' +
    '<th style="width:85px;">累计销量</th>' +
    '<th style="width:85px;">今日新增</th>' +
    '<th style="width:105px;">近24小时新增</th>' +
    '<th style="width:100px;">最近区间新增</th>' +
    '<th style="width:125px;">最近更新时间</th>' +
    '<th style="width:78px;">状态</th>' +
    '<th style="width:50px;text-align:center;">操作</th>' +
    '</tr></thead><tbody>' +
    products.map(product => productRow(product, context)).join('') +
    '</tbody></table></div>' +
    pager;

  bindProductPager();
  bindTableEvents();

  if (savedScrollTop !== null) {
    const newScrollWrap = document.querySelector('.tablewrap');
    if (newScrollWrap) {
      newScrollWrap.scrollTop = savedScrollTop;
      newScrollWrap.scrollLeft = savedScrollLeft;
    }
  }
  if (savedMainScrollTop !== null) {
    const newMainWrap = document.querySelector('main');
    if (newMainWrap) newMainWrap.scrollTop = savedMainScrollTop;
  }

  const selectedProduct = products.find(p => p.id === selectedProductId) || products[0];
  if (selectedProduct) {
    renderDockPanel(selectedProduct);
  } else if (dockCard) {
    dockCard.hidden = true;
  }
}

function renderProductPager(total) {
  const pages = Math.max(1, Math.ceil(total / productPageSize));
  productPage = Math.min(productPage, pages);

  let pageBtnsHtml = '';
  if (pages <= 7) {
    for (let p = 1; p <= pages; p++) {
      pageBtnsHtml += '<button class="page-btn ' + (p === productPage ? 'active' : '') + '" data-page="' + p + '">' + p + '</button>';
    }
  } else {
    const start = Math.max(1, Math.min(productPage - 2, pages - 4));
    const end = Math.min(pages, start + 4);
    if (start > 1) {
      pageBtnsHtml += '<button class="page-btn ' + (1 === productPage ? 'active' : '') + '" data-page="1">1</button>';
      if (start > 2) pageBtnsHtml += '<span class="pager-ellipsis">...</span>';
    }
    for (let p = start; p <= end; p++) {
      pageBtnsHtml += '<button class="page-btn ' + (p === productPage ? 'active' : '') + '" data-page="' + p + '">' + p + '</button>';
    }
    if (end < pages) {
      if (end < pages - 1) pageBtnsHtml += '<span class="pager-ellipsis">...</span>';
      pageBtnsHtml += '<button class="page-btn ' + (pages === productPage ? 'active' : '') + '" data-page="' + pages + '">' + pages + '</button>';
    }
  }

  return '<div class="pager">' +
    '<div class="pager-left">共 ' + total + ' 条数据，已选择 1 条</div>' +
    '<div class="pager-right">' +
      '<button class="page-btn" id="productPrev"' + (productPage <= 1 ? ' disabled' : '') + '>‹</button>' +
      pageBtnsHtml +
      '<button class="page-btn" id="productNext"' + (productPage >= pages ? ' disabled' : '') + '>›</button>' +
      '<div class="pager-goto">前往 <input type="text" class="pager-goto-input" id="pagerGotoInput" value="' + productPage + '"> 页</div>' +
    '</div>' +
  '</div>';
}

function bindTableEvents() {
  document.querySelectorAll('.product-row').forEach(row => {
    row.addEventListener('click', () => {
      const id = Number(row.dataset.productId);
      if (!id) return;
      selectedProductId = id;
      document.querySelectorAll('.product-row').forEach(r => {
        const isTarget = Number(r.dataset.productId) === id;
        r.classList.toggle('selected-row', isTarget);
        const cb = r.querySelector('.row-checkbox');
        if (cb) cb.checked = isTarget;
      });
      const prod = allProducts.find(p => p.id === id);
      if (prod) renderDockPanel(prod);
    });
  });

  document.querySelectorAll('.row-checkbox').forEach(checkbox => {
    checkbox.addEventListener('click', event => {
      event.preventDefault();
      event.stopPropagation();
      checkbox.closest('.product-row')?.click();
    });
  });

  document.querySelectorAll('.more-btn').forEach(btn => {
    btn.addEventListener('click', () => openActionPanel(btn));
  });
}

function renderDockPanel(product) {
  if (!dockCard || !product) return;
  dockCard.hidden = false;
  const shopInfo = getShopInfo(product);
  const imgUrl = product.image_url || '';
  const imgHtml = imgUrl
    ? '<img src="' + esc(imgUrl) + '" alt="" referrerpolicy="no-referrer" class="dock-thumb">'
    : '<div class="dock-thumb" style="display:grid;place-items:center;color:#aaa;">图</div>';

  const todayVal = product.today?.value;
  const rolling24Val = product.rolling24?.value;
  const priceDisplay = formatPrice(product.price);
  const totalDisplay = product.total_sales != null ? formatSales(product.total_sales) : '—';
  const todayDisplay = todayVal != null ? (Number(todayVal) > 0 ? '+' : '') + formatSales(todayVal) : '—';
  const rolling24Display = rolling24Val != null ? (Number(rolling24Val) > 0 ? '+' : '') + formatSales(rolling24Val) : '—';

  let dockShopSubs = [];
  if (shopInfo.rating) dockShopSubs.push('<span class="star-rating">★ ' + esc(shopInfo.rating) + '</span>');
  if (shopInfo.fans) dockShopSubs.push('<span>' + esc(shopInfo.fans) + '</span>');
  const dockSubHtml = dockShopSubs.length > 0
    ? dockShopSubs.join('<span style="color:var(--line);margin:0 4px;">|</span>') + '<span style="color:var(--line);margin:0 4px;">|</span>'
    : '';

  dockCard.innerHTML =
    '<div class="dock-detail">' +
      '<div>' +
        '<div class="dock-title-line">商品详情 (已选择 1 个商品)</div>' +
        '<div class="dock-detail-body">' +
          imgHtml +
          '<div class="dock-info">' +
            '<div>' +
              '<div class="dock-product-title" title="' + esc(product.title) + '">' + esc(product.title) + '</div>' +
              '<div class="dock-shop-row">' +
                '<span style="font-weight:500;color:var(--ink);">' + esc(shopInfo.name) + '</span>' +
                dockSubHtml +
              '</div>' +
            '</div>' +
            '<div class="dock-metrics-grid">' +
              '<div class="dock-metric-box"><small>当前价格</small><b class="red">' + priceDisplay + '</b></div>' +
              '<div class="dock-metric-box"><small>累计销量</small><b>' + totalDisplay + '</b></div>' +
              '<div class="dock-metric-box"><small>今日新增</small><b class="red">' + todayDisplay + '</b></div>' +
              '<div class="dock-metric-box"><small>近24小时新增</small><b class="red">' + rolling24Display + '</b></div>' +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="dock-links-row">' +
        '<a href="' + esc(productExternalHref(product)) + '" target="_blank" rel="noopener noreferrer" class="dock-link-btn">' +
          '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>' +
          '查看详情' +
        '</a>' +
        '<button id="dockCopyLinkBtn" type="button" class="dock-link-btn">' +
          '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/></svg>' +
          '复制链接' +
        '</button>' +
      '</div>' +
    '</div>' +
    '<div class="dock-trend">' +
      '<div class="trend-head">' +
        '<div class="trend-head-left">' +
          '<span class="trend-title">成交趋势</span>' +
          '<div class="trend-mode-switch">' +
            '<button class="trend-mode-btn ' + (dockTrendMode === 'daily' ? 'active' : '') + '" type="button" data-dock-mode="daily">日销量</button>' +
            '<button class="trend-mode-btn ' + (dockTrendMode === 'hourly' ? 'active' : '') + '" type="button" data-dock-mode="hourly">小时销量</button>' +
          '</div>' +
        '</div>' +
        '<div class="trend-head-right">' +
          (dockTrendMode === 'daily' ? '<div class="trend-range-switch">' + [7, 30, 0].map(days =>
            '<button class="trend-range-btn ' + (dockTrendRange === days ? 'active' : '') + '" type="button" data-dock-range="' + days + '">' +
              (days ? '近' + days + '天' : '全部') +
            '</button>'
          ).join('') + '</div>' : '') +
          '<div class="trend-summary-text" id="dockTrendSummary"></div>' +
        '</div>' +
      '</div>' +
      '<div class="trend-svg-container" id="dockTrendSvgWrap">' +
        '<div style="height:100%;display:grid;place-items:center;color:var(--ink3);font-size:12px;">正在加载走势图…</div>' +
      '</div>' +
      '<div class="trend-note" id="dockTrendNote"></div>' +
    '</div>';

  document.querySelector('#dockCopyLinkBtn')?.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(product.url || '');
      showNotice('商品链接已复制到剪贴板', 'success');
    } catch (_) {
      showNotice('复制失败，请手动复制', 'error');
    }
  });

  document.querySelectorAll('[data-dock-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      dockTrendMode = btn.dataset.dockMode;
      renderDockPanel(product);
    });
  });
  document.querySelectorAll('[data-dock-range]').forEach(btn => {
    btn.addEventListener('click', () => {
      dockTrendRange = Number(btn.dataset.dockRange);
      renderDockPanel(product);
    });
  });

  loadAndRenderDockTrend(product);
}

async function loadAndRenderDockTrend(product, forceRefresh = false) {
  let trend = cachedTrends[product.id];
  if (!trend || forceRefresh) {
    try {
      trend = await api('/api/products/' + product.id + '/trend');
      cachedTrends[product.id] = trend;
    } catch (_) {}
  }
  if (Number(selectedProductId) !== Number(product.id)) return;

  const container = document.querySelector('#dockTrendSvgWrap');
  const summaryEl = document.querySelector('#dockTrendSummary');
  const noteEl = document.querySelector('#dockTrendNote');
  if (!container) return;

  const sourcePoints = (dockTrendMode === 'daily' ? trend?.daily : trend?.hourly) || [];
  const points = dockTrendMode === 'daily' && dockTrendRange
    ? sourcePoints.slice(-dockTrendRange)
    : sourcePoints;
  const valid = points.filter(point => point.value != null && Number.isFinite(Number(point.value)));
  const gapPoints = dockTrendMode === 'hourly'
    ? points.filter(point => point.gap && Number.isFinite(Number(point.average_hourly)))
    : [];
  const statusPoints = dockTrendMode === 'hourly'
    ? points.filter(point => point.gap_kind)
    : [];

  if (noteEl) {
    noteEl.textContent = dockTrendMode === 'daily'
      ? '日销量按每日午夜基线计算；缺失基线时从 02:00 起显示估算值。'
      : '小时销量不展示午夜基线；真实缺采用灰色虚线，异常读数排除用橙色虚线。';
  }

  if (!valid.length && !gapPoints.length && !statusPoints.length) {
    if (summaryEl) summaryEl.textContent = '暂无可计算的趋势点';
    container.innerHTML = '<div class="trend-empty" style="height:100%;display:grid;place-items:center;color:var(--ink3);font-size:12px;">采集历史不足，或当前区间存在待确认数据。</div>';
    return;
  }

  const width = 560, height = 135, left = 48, right = 16, top = 14, bottom = 24;
  const innerWidth = width - left - right, innerHeight = height - top - bottom;
  const chartValues = valid.map(point => Number(point.value)).concat(gapPoints.map(point => Number(point.average_hourly)));
  const maximum = Math.max(...chartValues, 1);
  const xAt = index => dockTrendMode === 'hourly'
    ? left + innerWidth * (index + 0.5) / points.length
    : (points.length === 1 ? left + innerWidth / 2 : left + innerWidth * index / (points.length - 1));
  const yAt = value => top + innerHeight - innerHeight * Number(value) / maximum;
  const coordinates = points.map((point, index) => point.value == null ? null : {point, x:xAt(index), y:yAt(point.value)});
  const segments = [];
  let segment = [];
  coordinates.forEach(coordinate => {
    if (coordinate) segment.push(coordinate);
    else if (segment.length) { segments.push(segment); segment = []; }
  });
  if (segment.length) segments.push(segment);

  const grid = Array.from({length:4}, (_, index) => {
    const value = maximum * (3 - index) / 3;
    const y = top + innerHeight * index / 3;
    return '<line x1="' + left + '" y1="' + y + '" x2="' + (width - right) + '" y2="' + y + '" class="trend-grid"/>' +
      '<text x="' + (left - 8) + '" y="' + (y + 3) + '" text-anchor="end" class="trend-axis">' + esc(Math.round(value).toLocaleString('zh-CN')) + '</text>';
  }).join('');

  const labelIndexes = [...new Set([0, Math.round((points.length - 1) / 3), Math.round((points.length - 1) * 2 / 3), points.length - 1])];
  const labels = labelIndexes.map(index =>
    '<text x="' + xAt(index) + '" y="' + (height - 6) + '" text-anchor="middle" class="trend-axis">' + esc(points[index]?.label || '') + '</text>'
  ).join('');

  const lines = dockTrendMode === 'daily' ? segments.map(items =>
    '<polyline points="' + items.map(item => item.x + ',' + item.y).join(' ') + '" class="trend-line"/>'
  ).join('') : '';

  const areas = dockTrendMode === 'daily' ? segments.filter(items => items.length > 1).map(items =>
    '<polygon points="' + items[0].x + ',' + (top + innerHeight) + ' ' +
      items.map(item => item.x + ',' + item.y).join(' ') + ' ' +
      items[items.length - 1].x + ',' + (top + innerHeight) + '" class="trend-area"/>'
  ).join('') : '';

  const circles = dockTrendMode === 'daily' ? coordinates.filter(Boolean).map(item => {
    const point = item.point;
    const period = point.date + (point.partial ? '（未完整）' : '');
    return '<circle cx="' + item.x + '" cy="' + item.y + '" r="3.5" class="trend-point"><title>' +
      esc(period + '：+' + formatSales(point.value) + (point.reason ? '，' + point.reason : '')) + '</title></circle>';
  }).join('') : '';

  const barWidth = Math.max(6, Math.min(20, innerWidth / Math.max(points.length, 1) * 0.65));
  const bars = dockTrendMode === 'hourly' ? points.map((point, index) => {
    const gap = point.gap && Number.isFinite(Number(point.average_hourly));
    const marker = point.gap_kind && !gap && (point.value == null || !Number.isFinite(Number(point.value)));
    if (!gap && !marker && (point.value == null || !Number.isFinite(Number(point.value)))) return '';
    const value = gap ? Number(point.average_hourly) : Number(point.value);
    const barHeight = marker ? 12 : Math.max(2, innerHeight * value / maximum);
    const detail = gap
      ? (point.from_time || '—') + ' 至 ' + point.time + '：区间共新增 +' + formatSales(point.gap_total) +
        '，平均每小时 ' + value.toLocaleString('zh-CN') + '（仅区间平均）'
      : marker ? point.time + '：' + (point.reason || '异常读数已排除')
      : (point.from_time || '—') + ' 至 ' + point.time + '：+' + formatSales(point.value) + (point.reason ? '，' + point.reason : '');
    const gapClass = point.gap_kind ? ' trend-bar-gap trend-bar-gap-' + point.gap_kind : '';
    return '<rect x="' + (xAt(index) - barWidth / 2) + '" y="' + (top + innerHeight - barHeight) +
      '" width="' + barWidth + '" height="' + barHeight + '" rx="2" class="trend-bar' + gapClass + '"><title>' +
      esc(detail) + '</title></rect>';
  }).join('') : '';

  const latest = valid[valid.length - 1];
  const regularMaximum = valid.length ? Math.max(...valid.map(point => Number(point.value))) : null;
  if (summaryEl) {
    const missingCount = statusPoints.filter(point => point.gap_kind === 'missing').length;
    const anomalyCount = statusPoints.filter(point => point.gap_kind === 'anomaly').length;
    const mixedCount = statusPoints.filter(point => point.gap_kind === 'mixed').length;
    summaryEl.textContent = '有效点 ' + valid.length + ' 个' +
      (latest ? ' · 最近 +' + formatSales(latest.value) : '') +
      (regularMaximum != null ? ' · 最高 +' + formatSales(regularMaximum) : '') +
      (missingCount ? ' · 缺采 ' + missingCount + ' 个' : '') +
      (anomalyCount ? ' · 异常排除 ' + anomalyCount + ' 个' : '') +
      (mixedCount ? ' · 混合 ' + mixedCount + ' 个' : '');
  }

  const chartLabel = dockTrendMode === 'daily' ? '商品日销量折线图' : '商品小时销量柱状图';
  container.innerHTML = '<svg viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="' + chartLabel + '">' +
    grid + labels + areas + lines + circles + bars + '</svg>';
}


function currentProductSource() {
  return allProducts;
}

function currentProductContext() {
  return view === 'selection' ? 'selection' : 'single';
}

function currentFilteredProducts() {
  return filterAndSortProducts(currentProductSource());
}

function currentProductPageItems() {
  const products = currentFilteredProducts();
  const pages = Math.max(1, Math.ceil(products.length / productPageSize));
  if (productPage > pages) productPage = pages;
  const start = (productPage - 1) * productPageSize;
  return products.slice(start, start + productPageSize);
}

function bindProductPager() {
  document.querySelectorAll('.page-btn[data-page]').forEach(btn => {
    btn.addEventListener('click', () => {
      productPage = Number(btn.dataset.page);
      renderCurrentProductList();
    });
  });
  document.querySelector('#productPrev')?.addEventListener('click', () => {
    if (productPage > 1) {
      productPage -= 1;
      renderCurrentProductList();
    }
  });
  document.querySelector('#productNext')?.addEventListener('click', () => {
    const pages = Math.max(1, Math.ceil(currentFilteredProducts().length / productPageSize));
    if (productPage < pages) {
      productPage += 1;
      renderCurrentProductList();
    }
  });
  const gotoInput = document.querySelector('#pagerGotoInput');
  if (gotoInput) {
    const handleGoto = () => {
      const val = parseInt(gotoInput.value, 10);
      const pages = Math.max(1, Math.ceil(currentFilteredProducts().length / productPageSize));
      if (!isNaN(val) && val >= 1 && val <= pages) {
        productPage = val;
        renderCurrentProductList();
      } else {
        gotoInput.value = productPage;
      }
    };
    gotoInput.addEventListener('keydown', e => { if (e.key === 'Enter') handleGoto(); });
    gotoInput.addEventListener('blur', handleGoto);
  }
}

function renderCurrentProductList() {
  const filtered = currentFilteredProducts();
  const pages = Math.max(1, Math.ceil(filtered.length / productPageSize));
  if (productPage > pages) productPage = pages;
  const start = (productPage - 1) * productPageSize;
  renderProductTable(
    filtered.slice(start, start + productPageSize),
    currentProductContext(),
    filtered.length
  );
}

async function loadSinglePage({keepNotice = false} = {}) {
  cachedTrends = {};
  allProducts = await api('/api/products');
  productHeader(allProducts, false);
  productToolbar(allProducts);
  renderCurrentProductList();
  if (!keepNotice) hideNotice();
}

async function loadSelectionPage({keepNotice = false} = {}) {
  cachedTrends = {};
  allProducts = await api('/api/selection');
  productHeader(allProducts, true);
  productToolbar(allProducts);
  renderCurrentProductList();
  if (!keepNotice) hideNotice();
}

function aggregateShopHeader(key) {
  const values = allShops.map(shop => metricValue(shop[key])).filter(v => v != null);
  if (!values.length) return '—';
  return formatSales(values.reduce((sum, value) => sum + value, 0));
}

function shopsHeader() {
  const shopSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/></svg>';
  const bagSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 2 3 6v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2V6l-3-4Z"/><path d="M3 6h18"/><path d="M16 10a4 4 0 0 1-8 0"/></svg>';
  const barSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>';
  const clockSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>';

  pageHeader(
    '店铺监控',
    allShops.length + ' 家店铺',
    '仅汇总你主动监控商品所属店铺，不自动采集整店商品。',
    [
      { label: '监控店铺', value: String(allShops.length), iconBoxClass: 'icon-box-red', iconSvg: shopSvg },
      { label: '监控商品', value: String(allShops.reduce((sum,shop) => sum + Number(shop.product_count || 0), 0)), iconBoxClass: 'icon-box-blue', iconSvg: bagSvg },
      { label: '今日新增汇总', value: aggregateShopHeader('today'), iconBoxClass: 'icon-box-blue', iconSvg: barSvg },
      { label: '近24h新增汇总', value: aggregateShopHeader('rolling24'), iconBoxClass: 'icon-box-red', iconSvg: clockSvg }
    ]
  );
}

function shopsToolbar() {
  toolbar.innerHTML =
    '<label class="searchbox" aria-label="搜索店铺"><span>⌕</span><input id="toolbarSearch" type="search" placeholder="搜索店铺"></label>' +
    '<select class="selectbox" id="shopSort" aria-label="店铺排序">' +
      '<option value="today_desc">今日新增 ↓</option><option value="rolling24_desc">近24h新增 ↓</option>' +
      '<option value="updated_desc">最近更新 ↓</option><option value="count_desc">监控商品数 ↓</option>' +
    '</select><div class="grow"></div>' +
    '<button class="btn" id="exportButton" type="button">⇩ 导出</button>' +
    '<button class="btn" id="addShopProductButton" type="button">＋ 添加商品</button>' +
    '<button class="btn primary" id="collectShopPageButton" type="button">立即采集本页</button>' +
    '<button class="btn" id="settingsButton" type="button">设置</button>';

  document.querySelector('#toolbarSearch').addEventListener('input', () => { shopPage = 1; renderShopList(); });
  document.querySelector('#shopSort').addEventListener('change', () => { shopPage = 1; renderShopList(); });
  document.querySelector('#exportButton').addEventListener('click', openExportDialog);
  document.querySelector('#addShopProductButton').addEventListener('click', () => openProductImport('shop'));
  document.querySelector('#collectShopPageButton').addEventListener('click', collectVisibleShopProducts);
  document.querySelector('#settingsButton').addEventListener('click', openSettings);
}

function shopMetric(metric) {
  if (!metric || metric.value == null) {
    return '<b>—</b><small class="metric-hint" title="' + esc(metric?.reason || '') + '">有效 0/' + Number(metric?.total || 0) + '</small>';
  }
  const value = Number(metric.value);
  const approximate = metric.approximate ? '≈' : '';
  return '<b class="' + (value > 0 ? 'positive' : '') + '">' + approximate + (value > 0 ? '+' : '') + formatSales(value) + '</b>' +
    '<small class="metric-hint" title="' + esc(metric.reason || '') + '">有效 ' + Number(metric.covered || 0) + '/' + Number(metric.total || 0) + '</small>';
}

function filteredSortedShops() {
  const term = (document.querySelector('#toolbarSearch')?.value || '').trim().toLowerCase();
  const sort = document.querySelector('#shopSort')?.value || 'today_desc';
  const shops = allShops.filter(shop => !term || String(shop.shop_name || '').toLowerCase().includes(term));

  const shopMetricNumber = (shop, key) => metricValue(shop[key]) ?? Number.NEGATIVE_INFINITY;
  if (sort === 'today_desc') shops.sort((a,b) => shopMetricNumber(b,'today') - shopMetricNumber(a,'today'));
  else if (sort === 'rolling24_desc') shops.sort((a,b) => shopMetricNumber(b,'rolling24') - shopMetricNumber(a,'rolling24'));
  else if (sort === 'count_desc') shops.sort((a,b) => Number(b.product_count || 0) - Number(a.product_count || 0));
  else shops.sort((a,b) => String(b.last_collected_at || '').localeCompare(String(a.last_collected_at || '')));
  return shops;
}

function shopProductRow(product) {
  const paused = product.monitor_state === 'paused';
  const selected = Number(product.in_selection_pool) === 1;
  const image = product.image_url
    ? '<img src="' + esc(product.image_url) + '" alt="" referrerpolicy="no-referrer">'
    : '<img alt="">';
  return '<tr data-product-id="' + product.id + '">' +
    '<td><div class="product">' + image + '<div class="copy">' +
    '<a class="product-title-link" href="' + esc(productExternalHref(product)) + '" target="_blank" rel="noopener noreferrer" title="' + esc(product.title) + '">' + esc(product.title) + '</a>' +
    '<span>' + (paused ? '已暂停监控' : '商品监控中') + '</span></div></div></td>' +
    '<td class="num">' + formatPrice(product.price) + '</td>' +
    '<td class="num">' + totalSalesCell(product) + '</td>' +
    '<td class="num">' + monitoredMetricCell(product.today, true) + '</td>' +
    '<td class="num">' + monitoredMetricCell(product.rolling24, true) + '</td>' +
    '<td class="num">' + incrementCell(product.increment) + '</td>' +
    '<td>' + esc(productUpdateTime(product) || '—') + '</td>' +
    '<td><div class="actions"><button class="more-btn" type="button" aria-label="打开商品操作" title="商品操作" ' +
      'data-more-product-id="' + product.id + '" data-more-title="' + esc(product.title) + '" ' +
      'data-more-paused="' + (paused ? '1' : '0') + '" data-more-selected="' + (selected ? '1' : '0') + '" ' +
      'data-more-shop="1" data-more-context="shop">···</button></div></td>' +
    '</tr>';
}

function shopExpandedTable(shop) {
  return '<div class="shop-expand"><table class="shop-products-table"><thead><tr>' +
    '<th style="width:24%">已监控商品</th><th style="width:7%">当前价</th><th style="width:11%">累计销量</th>' +
    '<th style="width:11%">今日新增</th><th style="width:11%">近24小时新增</th><th style="width:12%">最近区间新增</th>' +
    '<th style="width:16%">更新时间</th><th style="width:8%">操作</th>' +
    '</tr></thead><tbody>' + (shop.products || []).map(shopProductRow).join('') + '</tbody></table></div>';
}

function renderShopPager(total) {
  const pages = Math.max(1, Math.ceil(total / shopPageSize));
  shopPage = Math.min(shopPage, pages);
  const start = total ? (shopPage - 1) * shopPageSize + 1 : 0;
  const end = Math.min(total, shopPage * shopPageSize);
  return '<div class="pager">' +
    '<span>每页</span><select class="selectbox pager-size" id="shopPageSize">' +
      [30,50,100].map(size => '<option value="' + size + '"' + (shopPageSize === size ? ' selected' : '') + '>' + size + '</option>').join('') +
    '</select><span>共 ' + total + ' 家 · ' + start + '-' + end + '</span><div class="grow"></div>' +
    '<button class="btn" id="shopPrev" type="button"' + (shopPage <= 1 ? ' disabled' : '') + '>‹</button>' +
    '<span class="page-current">' + shopPage + ' / ' + pages + '</span>' +
    '<button class="btn" id="shopNext" type="button"' + (shopPage >= pages ? ' disabled' : '') + '>›</button></div>';
}

function currentShopPageItems() {
  const shops = filteredSortedShops();
  const start = (shopPage - 1) * shopPageSize;
  return shops.slice(start, start + shopPageSize);
}

function renderShopList() {
  const shops = filteredSortedShops();
  const pages = Math.max(1, Math.ceil(shops.length / shopPageSize));
  if (shopPage > pages) shopPage = pages;
  const pageItems = shops.slice((shopPage - 1) * shopPageSize, shopPage * shopPageSize);

  if (!pageItems.length) {
    content.innerHTML = '<div class="empty">店铺监控还没有商品。点击“添加商品”，粘贴商品分享链接或分享口令后会自动按所属店铺归类。</div>' + renderShopPager(shops.length);
  } else {
    content.innerHTML = '<div class="shoplist">' + pageItems.map(shop => {
      const initial = esc((shop.shop_name || '店').slice(0,1));
      const expanded = expandedShopKeys.has(shop.shop_key);
      const meta = [
        shop.rating ? '评分 ' + shop.rating : '',
        shop.brand_name ? '品牌 ' + shop.brand_name : '',
        shop.brand_fans_count != null ? '粉丝 ' + formatSales(shop.brand_fans_count) : '',
        shop.brand_notes_count != null ? '笔记 ' + formatSales(shop.brand_notes_count) : ''
      ].filter(Boolean).join(' · ');
      return '<div class="shopcard">' +
        '<div class="shoprow" data-shop-toggle="' + esc(shop.shop_key) + '" aria-expanded="' + (expanded ? 'true' : 'false') + '">' +
        '<div class="shopid"><div class="shoplogo">' + initial + '</div><div><b>' + esc(shop.shop_name) + '</b><span>' + shop.product_count + ' 个已监控商品</span>' +
        (meta ? '<small class="shop-meta-line">' + esc(meta) + '</small>' : '') + '</div></div>' +
        '<div class="shopmetric"><span>已监控</span><b>' + shop.product_count + ' 款</b></div>' +
        '<div class="shopmetric"><span>今日新增汇总</span>' + shopMetric(shop.today) + '</div>' +
        '<div class="shopmetric"><span>近24h新增汇总</span>' + shopMetric(shop.rolling24) + '</div>' +
        '<div class="shopmetric"><span>最近更新</span><b class="shop-time">' + esc(shop.last_collected_at || '—') + '</b></div>' +
        '<div><span class="status ' + esc(shop.health || 'success') + '">● ' + esc(shop.health_label || '正常') + '</span></div>' +
        '<div class="shop-toggle-label">' + (expanded ? '收起⌃' : '展开⌄') + '</div>' +
        '</div>' +
        (expanded ? shopExpandedTable(shop) : '') +
        '</div>';
    }).join('') + '</div>' + renderShopPager(shops.length);
  }

  document.querySelector('#shopPageSize')?.addEventListener('change', event => {
    shopPageSize = Number(event.target.value) || 30;
    shopPage = 1;
    renderShopList();
  });
  document.querySelector('#shopPrev')?.addEventListener('click', () => { if (shopPage > 1) { shopPage -= 1; renderShopList(); } });
  document.querySelector('#shopNext')?.addEventListener('click', () => {
    const totalPages = Math.max(1, Math.ceil(filteredSortedShops().length / shopPageSize));
    if (shopPage < totalPages) { shopPage += 1; renderShopList(); }
  });
}

async function renderShopsPage({keepNotice = false} = {}) {
  allShops = await api('/api/shops');
  shopsHeader();
  shopsToolbar();
  renderShopList();
  if (!keepNotice) hideNotice();
}

async function collectProducts(products, button, scope = 'all') {
  const targets = products.filter(p => p.monitor_state === 'active');
  if (!targets.length) {
    showNotice('当前范围没有可立即采集的正常商品。');
    return;
  }
  const original = button.textContent;
  button.disabled = true;
  button.textContent = '提交中…';
  try {
    const result = await api('/api/jobs/collect', {
      method:'POST',
      body:JSON.stringify({scope, product_ids:targets.map(product => product.id)})
    });
    showNotice(
      '采集任务 #' + result.job_id + ' 已提交，共 ' + targets.length + ' 个商品；后台将按顺序采集。',
      'success'
    );
  } catch (error) {
    showNotice(error.message || '提交采集任务失败', 'error');
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function collectVisibleProducts(event) {
  const button = event?.currentTarget || document.querySelector('#pageCollectBtn');
  await collectProducts(
    currentProductPageItems(),
    button,
    view === 'selection' ? 'selection' : 'single'
  );
}

async function collectVisibleShopProducts(event) {
  const button = event?.currentTarget || document.querySelector('#pageCollectBtn');
  const productsById = new Map();
  currentShopPageItems().forEach(shop => (shop.products || []).forEach(product => productsById.set(product.id, product)));
  await collectProducts([...productsById.values()], button, 'shop');
}

function exportMetric(metric) {
  return metric?.value == null ? null : Number(metric.value);
}

function roundedIntervalHours(metric) {
  const hours = Number(metric?.hours);
  if (!Number.isFinite(hours) || hours < 0) return null;
  return Math.round(hours * 10) / 10;
}

function productExportRow(product) {
  return {
    title: product.title || '',
    shop_name: product.shop_name || '',
    url: product.url || '',
    price: product.price == null ? null : Number(product.price),
    total_sales: product.total_sales == null ? null : Number(product.total_sales),
    today: exportMetric(product.today),
    rolling24: exportMetric(product.rolling24),
    rolling24_basis: rolling24Basis(product.rolling24),
    increment: exportMetric(product.increment),
    interval_hours: roundedIntervalHours(product.increment),
    updated_at: productUpdateTime(product),
    status: product.monitor_state === 'paused' ? '已暂停' : (product.health_label || '正常')
  };
}

function shopExportRows(shops) {
  const rows = [];
  shops.forEach(shop => {
    const products = shop.products || [];
    const shopBase = {
      shop_name: shop.shop_name || '',
      shop_id: shop.shop_id || '',
      rating: shop.rating ?? '',
      brand_name: shop.brand_name || '',
      brand_fans_count: shop.brand_fans_count == null ? null : Number(shop.brand_fans_count),
      brand_notes_count: shop.brand_notes_count == null ? null : Number(shop.brand_notes_count),
      product_count: Number(shop.product_count || 0),
      shop_today: exportMetric(shop.today),
      shop_today_coverage: Number(shop.today?.covered || 0) + '/' + Number(shop.today?.total || 0),
      shop_rolling24: exportMetric(shop.rolling24),
      shop_rolling24_coverage: Number(shop.rolling24?.covered || 0) + '/' + Number(shop.rolling24?.total || 0)
    };
    if (!products.length) {
      rows.push(shopBase);
      return;
    }
    products.forEach(product => {
      rows.push({
        ...shopBase,
        product_title: product.title || '',
        product_url: product.url || '',
        price: product.price == null ? null : Number(product.price),
        total_sales: product.total_sales == null ? null : Number(product.total_sales),
        today: exportMetric(product.today),
        rolling24: exportMetric(product.rolling24),
        rolling24_basis: rolling24Basis(product.rolling24),
        increment: exportMetric(product.increment),
        interval_hours: roundedIntervalHours(product.increment),
        updated_at: productUpdateTime(product),
        product_status: product.monitor_state === 'paused' ? '已暂停' : (product.health_label || '正常')
      });
    });
  });
  return rows;
}

function currentExportPayload() {
  if (view === 'shops') {
    const shops = filteredSortedShops();
    const rows = shopExportRows(shops);
    return {
      module:'shops',
      rows,
      summary:shops.length + ' 家店铺 · ' + rows.length + ' 条商品明细'
    };
  }
  const products = currentFilteredProducts();
  return {
    module:view === 'selection' ? 'selection' : 'single',
    rows:products.map(productExportRow),
    summary:products.length + ' 个商品'
  };
}

function closeExportDialog() {
  exportOverlay.hidden = true;
}

function openExportDialog() {
  const payload = currentExportPayload();
  exportSummary.textContent = '当前筛选结果：' + payload.summary + '。导出将包含全部筛选结果，不受当前页限制。';
  const empty = payload.rows.length === 0;
  exportCsv.disabled = empty;
  exportXlsx.disabled = empty;
  exportOverlay.hidden = false;
  exportClose.focus();
}

function submitExport(format) {
  const payload = currentExportPayload();
  if (!payload.rows.length) {
    showNotice('当前筛选结果为空，没有可导出的数据。', 'error');
    closeExportDialog();
    return;
  }

  exportCsv.disabled = true;
  exportXlsx.disabled = true;

  if (window.chrome?.webview?.postMessage) {
    window.chrome.webview.postMessage({
      type:'export',
      module:payload.module,
      format,
      rows:payload.rows
    });
    closeExportDialog();
    showNotice('请选择保存位置，保存后会自动生成导出文件。', 'success');
    setTimeout(() => {
      exportCsv.disabled = false;
      exportXlsx.disabled = false;
    }, 500);
    return;
  }

  let frame = document.querySelector('#exportDownloadFrame');
  if (!frame) {
    frame = document.createElement('iframe');
    frame.id = 'exportDownloadFrame';
    frame.name = 'exportDownloadFrame';
    frame.hidden = true;
    document.body.appendChild(frame);
  }

  const form = document.createElement('form');
  form.method = 'POST';
  form.action = '/api/export';
  form.target = 'exportDownloadFrame';
  form.acceptCharset = 'UTF-8';
  form.hidden = true;

  const input = document.createElement('input');
  input.type = 'hidden';
  input.name = 'payload';
  input.value = JSON.stringify({module:payload.module, format, rows:payload.rows});
  form.appendChild(input);
  document.body.appendChild(form);
  form.submit();
  form.remove();

  closeExportDialog();
  showNotice('正在生成 ' + format.toUpperCase() + ' 导出文件，请选择保存位置。', 'success');
  setTimeout(() => {
    exportCsv.disabled = false;
    exportXlsx.disabled = false;
  }, 500);
}

function closeShopImport() {
  shopImportOverlay.hidden = true;
}

function openProductImport(scope) {
  importScope = scope;
  const shopMode = scope === 'shop';
  shopImportTitle.textContent = shopMode ? '添加店铺监控商品' : '添加单品监控商品';
  shopImportHint.textContent = shopMode
    ? '系统会采集商品信息，并按真实店铺 ID 自动归入对应店铺；不会自动抓取该店其他商品。'
    : '系统会在后台采集商品信息并加入单品监控；提交后可以继续操作。';
  shopImportOverlay.hidden = false;
  shopImportText.value = '';
  shopImportSubmit.disabled = false;
  shopImportText.focus();
}

async function watchImportJob(jobId) {
  jobId = Number(jobId);
  if (!jobId || watchedImportJobs.has(jobId)) return;
  watchedImportJobs.add(jobId);
  try {
    for (let attempt = 0; attempt < 120; attempt += 1) {
      await new Promise(resolve => setTimeout(resolve, 1000));
      const result = await api('/api/jobs/' + jobId);
      const job = result.job;
      if (!['success','partial','failed','blocked','cancelled','interrupted'].includes(job.status)) continue;

      await reloadCurrentView(true);
      const failed = (job.items || []).find(item => ['failed','cancelled','interrupted'].includes(item.status));
      if (job.status === 'success') {
        const label = {single:'单品监控', shop:'店铺监控', selection:'选品中心'}[job.scope] || '目标范围';
        const itemMessage = job.items?.length === 1 ? job.items[0].message : '';
        showNotice(
          itemMessage && itemMessage !== '已保存观测记录' ? itemMessage + '。' : '商品已采集并加入' + label + '。',
          'success'
        );
      } else {
        showNotice(failed?.message || job.error || '添加任务未全部完成，请查看任务状态。', 'error');
      }
      return;
    }
  } catch (error) {
    showNotice(error.message || '无法获取添加任务状态，请稍后查看列表。', 'error');
  } finally {
    watchedImportJobs.delete(jobId);
  }
}

async function submitProductImport() {
  const text = shopImportText.value.trim();
  if (!text) {
    showNotice('请先粘贴商品分享链接或分享口令。', 'error');
    return;
  }
  shopImportSubmit.disabled = true;
  shopImportSubmit.textContent = '提交中…';
  try {
    const result = await api('/api/products/import', {
      method:'POST',
      body:JSON.stringify({text, scope:importScope})
    });
    closeShopImport();
    const label = importScope === 'shop' ? '店铺监控' : '单品监控';
    showNotice(
      label + '添加任务 #' + result.job_id + ' 已提交，共识别 ' + result.count + ' 个商品；后台采集中，可以继续操作。',
      'success'
    );
    watchImportJob(result.job_id);
  } catch (error) {
    showNotice(error.message || '添加商品失败', 'error');
  } finally {
    shopImportSubmit.disabled = false;
    shopImportSubmit.textContent = '提交添加';
  }
}

function closeSettings() {
  settingsOverlay.hidden = true;
}

function formatRuntimeTime(value) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString('zh-CN', {hour12:false});
}

async function openSettings() {
  settingsOverlay.hidden = false;
  settingsRuntime.textContent = '正在读取运行状态…';
  settingsSave.disabled = true;
  try {
    const [settings, runtime] = await Promise.all([
      api('/api/settings'),
      api('/api/runtime/status')
    ]);
    autoEnabledInput.checked = settings.auto_enabled === '1';
    autoIntervalInput.value = Number(settings.auto_interval_minutes || 60);
    midnightEnabledInput.checked = settings.midnight_enabled === '1';
    const nextAuto = (runtime.scheduled || []).find(item => item.id === 'auto_collect');
    const latest = runtime.latest_job;
    const latestText = latest
      ? '最近任务 #' + latest.id + '：' + latest.status
      : '尚无后台采集任务';
    settingsRuntime.textContent =
      (runtime.worker_alive ? '采集 Worker 正常' : '采集 Worker 未运行') +
      ' · ' + (runtime.auto_enabled ? '自动采集已开启' : '自动采集已关闭') +
      ' · 下次自动采集：' + formatRuntimeTime(nextAuto?.next_run_time) +
      ' · ' + latestText;
    settingsSave.disabled = false;
    autoIntervalInput.focus();
    autoIntervalInput.select();
  } catch (error) {
    settingsRuntime.textContent = error.message || '读取设置失败';
  }
}

async function saveSettings() {
  const interval = Number(autoIntervalInput.value);
  if (!Number.isInteger(interval) || interval < 5 || interval > 1440) {
    settingsRuntime.textContent = '采集间隔必须是 5–1440 分钟之间的整数。';
    return;
  }
  settingsSave.disabled = true;
  try {
    await api('/api/settings', {
      method:'POST',
      body:JSON.stringify({
        auto_enabled:autoEnabledInput.checked,
        auto_interval_minutes:interval,
        midnight_enabled:midnightEnabledInput.checked
      })
    });
    closeSettings();
    showNotice('全局采集设置已保存。', 'success');
  } catch (error) {
    settingsRuntime.textContent = error.message || '保存设置失败';
  } finally {
    settingsSave.disabled = false;
  }
}

async function refreshCurrentViewData() {
  if (refreshInFlight || !actionOverlay.hidden || !trendOverlay.hidden || !settingsOverlay.hidden || !shopImportOverlay.hidden || !exportOverlay.hidden) return;
  refreshInFlight = true;
  try {
    if (view === 'single' || view === 'selection') {
      const nextProducts = await api(view === 'single' ? '/api/products' : '/api/selection');
      if (JSON.stringify(nextProducts) === JSON.stringify(allProducts)) return;
      allProducts = nextProducts;
      productHeader(allProducts, view === 'selection');
      renderCurrentProductList();
      const selectedProduct = allProducts.find(product => product.id === selectedProductId);
      if (selectedProduct) await loadAndRenderDockTrend(selectedProduct, true);
      return;
    }
    const nextShops = await api('/api/shops');
    if (JSON.stringify(nextShops) === JSON.stringify(allShops)) return;
    allShops = nextShops;
    shopsHeader();
    renderShopList();
  } finally {
    refreshInFlight = false;
  }
}

function closeActionPanel() {
  actionOverlay.hidden = true;
  activeActionProductId = null;
}

function openActionPanel(button) {
  activeActionProductId = Number(button.dataset.moreProductId);
  activeActionContext = button.dataset.moreContext || 'single';
  const paused = button.dataset.morePaused === '1';
  const selected = button.dataset.moreSelected === '1';
  const inShop = button.dataset.moreShop === '1';

  [actionCollect, actionPause, actionSelection, actionShop, actionRemove].forEach(item => {
    item.disabled = false;
    item.hidden = false;
  });
  actionSelection.classList.remove('danger');
  actionShop.classList.remove('danger');

  actionProductTitle.textContent = button.dataset.moreTitle || '当前商品';
  actionCollect.disabled = paused;
  actionPause.dataset.modalAction = paused ? 'resume' : 'pause';
  actionPause.querySelector('strong').textContent = paused ? '恢复监控' : '暂停监控';
  actionPause.querySelector('small').textContent = paused ? '恢复后重新参与后续采集' : '暂停后可随时恢复';
  actionPause.querySelector('.action-icon').textContent = paused ? '▶' : 'Ⅱ';

  if (activeActionContext === 'selection') {
    actionSelection.dataset.modalAction = 'leave-selection';
    actionSelection.classList.add('danger');
    actionSelection.querySelector('.action-icon').textContent = '−';
    actionSelection.querySelector('strong').textContent = '移出选品中心';
    actionSelection.querySelector('small').textContent = '仅解除选品中心归属，商品主体与历史数据保留';
    actionShop.hidden = true;
    actionRemove.hidden = true;
  } else {
    actionSelection.dataset.modalAction = 'selection';
    actionSelection.querySelector('.action-icon').textContent = '☆';
    actionSelection.disabled = selected;
    actionSelection.querySelector('strong').textContent = selected ? '已加入选品中心' : '加入选品中心';
    actionSelection.querySelector('small').textContent = selected ? '该商品已经在选品中心中' : '保留当前监控，同时加入选品中心';

    if (activeActionContext === 'shop') {
      actionShop.dataset.modalAction = 'leave-shop';
      actionShop.classList.add('danger');
      actionShop.querySelector('.action-icon').textContent = '−';
      actionShop.querySelector('strong').textContent = '移出店铺监控';
      actionShop.querySelector('small').textContent = '仅解除店铺监控归属，商品主体与历史数据保留';
      actionRemove.hidden = true;
    } else {
      actionShop.dataset.modalAction = 'shop';
      actionShop.querySelector('.action-icon').textContent = '店';
      actionShop.disabled = inShop;
      actionShop.querySelector('strong').textContent = inShop ? '已加入店铺监控' : '加入店铺监控';
      actionShop.querySelector('small').textContent = inShop ? '该商品已经在所属店铺监控中' : '按商品所属店铺自动归类并持续采集';
      actionRemove.hidden = false;
      actionRemove.disabled = false;
      actionRemove.querySelector('small').textContent = '移出单品监控列表，历史采集数据保留';
    }
  }

  actionOverlay.hidden = false;
  actionClose.focus();
}

function closeTrendPanel() {
  trendOverlay.hidden = true;
  activeTrendData = null;
}

function renderTrendChart() {
  const points = activeTrendData?.[activeTrendMode] || [];
  const valid = points.filter(point => point.value != null && Number.isFinite(Number(point.value)));
  const gapPoints = activeTrendMode === 'hourly'
    ? points.filter(point => point.gap && Number.isFinite(Number(point.average_hourly)))
    : [];
  const statusPoints = activeTrendMode === 'hourly'
    ? points.filter(point => point.gap_kind)
    : [];
  trendTabs.forEach(tab => {
    const active = tab.dataset.trendMode === activeTrendMode;
    tab.classList.toggle('active', active);
    tab.setAttribute('aria-selected', active ? 'true' : 'false');
  });
  trendNote.textContent = activeTrendMode === 'daily'
    ? '日销量按每日午夜基线计算；缺失基线时从 02:00 起显示估算值。'
    : '小时销量不展示午夜基线；真实缺采用灰色虚线，异常读数排除用橙色虚线。';
  if (!valid.length && !gapPoints.length && !statusPoints.length) {
    trendSummary.textContent = '暂无可计算的趋势点';
    trendChart.innerHTML = '<div class="trend-empty">采集历史不足，或当前区间存在待确认数据。</div>';
    return;
  }

  const width = 860, height = 320, left = 62, right = 18, top = 18, bottom = 42;
  const innerWidth = width - left - right, innerHeight = height - top - bottom;
  const chartValues = valid.map(point => Number(point.value)).concat(gapPoints.map(point => Number(point.average_hourly)));
  const maximum = Math.max(...chartValues, 1);
  const xAt = index => activeTrendMode === 'hourly'
    ? left + innerWidth * (index + 0.5) / points.length
    : (points.length === 1 ? left + innerWidth / 2 : left + innerWidth * index / (points.length - 1));
  const yAt = value => top + innerHeight - innerHeight * Number(value) / maximum;
  const coordinates = points.map((point, index) => point.value == null ? null : {point, x:xAt(index), y:yAt(point.value)});
  const segments = [];
  let segment = [];
  coordinates.forEach(coordinate => {
    if (coordinate) segment.push(coordinate);
    else if (segment.length) { segments.push(segment); segment = []; }
  });
  if (segment.length) segments.push(segment);

  const grid = Array.from({length:5}, (_, index) => {
    const value = maximum * (4 - index) / 4;
    const y = top + innerHeight * index / 4;
    return '<line x1="' + left + '" y1="' + y + '" x2="' + (width - right) + '" y2="' + y + '" class="trend-grid"/>' +
      '<text x="' + (left - 10) + '" y="' + (y + 4) + '" text-anchor="end" class="trend-axis">' + esc(Math.round(value).toLocaleString('zh-CN')) + '</text>';
  }).join('');
  const labelIndexes = [...new Set([0, Math.round((points.length - 1) / 4), Math.round((points.length - 1) / 2), Math.round((points.length - 1) * 3 / 4), points.length - 1])];
  const labels = labelIndexes.map(index =>
    '<text x="' + xAt(index) + '" y="' + (height - 13) + '" text-anchor="middle" class="trend-axis">' + esc(points[index]?.label || '') + '</text>'
  ).join('');
  const lines = activeTrendMode === 'daily' ? segments.map(items =>
    '<polyline points="' + items.map(item => item.x + ',' + item.y).join(' ') + '" class="trend-line"/>'
  ).join('') : '';
  const circles = activeTrendMode === 'daily' ? coordinates.filter(Boolean).map(item => {
    const point = item.point;
    const period = point.date + (point.partial ? '（未完整）' : '');
    return '<circle cx="' + item.x + '" cy="' + item.y + '" r="4" class="trend-point"><title>' +
      esc(period + '：+' + formatSales(point.value) + '，' + (point.reason || '')) + '</title></circle>';
  }).join('') : '';
  const barWidth = Math.max(8, Math.min(24, innerWidth / Math.max(points.length, 1) * 0.62));
  const bars = activeTrendMode === 'hourly' ? points.map((point, index) => {
    const gap = point.gap && Number.isFinite(Number(point.average_hourly));
    const marker = point.gap_kind && !gap && (point.value == null || !Number.isFinite(Number(point.value)));
    if (!gap && !marker && (point.value == null || !Number.isFinite(Number(point.value)))) return '';
    const value = gap ? Number(point.average_hourly) : Number(point.value);
    const barHeight = marker ? 16 : Math.max(2, innerHeight * value / maximum);
    const detail = gap
      ? (point.from_time || '—') + ' 至 ' + point.time + '：区间共新增 +' + formatSales(point.gap_total) +
        '，平均每小时 ' + value.toLocaleString('zh-CN') + '（仅区间平均）'
      : marker ? point.time + '：' + (point.reason || '异常读数已排除')
      : (point.from_time || '—') + ' 至 ' + point.time + '：+' + formatSales(point.value) + '，' + (point.reason || '');
    const gapClass = point.gap_kind ? ' trend-bar-gap trend-bar-gap-' + point.gap_kind : '';
    return '<rect x="' + (xAt(index) - barWidth / 2) + '" y="' + (top + innerHeight - barHeight) +
      '" width="' + barWidth + '" height="' + barHeight + '" rx="2" class="trend-bar' + gapClass + '"><title>' +
      esc(detail) + '</title></rect>';
  }).join('') : '';
  const latest = valid[valid.length - 1];
  const regularMaximum = valid.length ? Math.max(...valid.map(point => Number(point.value))) : null;
  const missingCount = statusPoints.filter(point => point.gap_kind === 'missing').length;
  const anomalyCount = statusPoints.filter(point => point.gap_kind === 'anomaly').length;
  const mixedCount = statusPoints.filter(point => point.gap_kind === 'mixed').length;
  trendSummary.textContent = '有效点 ' + valid.length + ' 个' +
    (latest ? ' · 最近 +' + formatSales(latest.value) + ' · 最高 +' + formatSales(regularMaximum) : '') +
    (missingCount ? ' · 缺采 ' + missingCount + ' 个' : '') +
    (anomalyCount ? ' · 异常排除 ' + anomalyCount + ' 个' : '') +
    (mixedCount ? ' · 混合 ' + mixedCount + ' 个' : '');
  const chartLabel = activeTrendMode === 'daily' ? '商品日销量折线图' : '商品小时销量柱状图';
  trendChart.innerHTML = '<svg viewBox="0 0 ' + width + ' ' + height + '" role="img" aria-label="' + chartLabel + '">' +
    grid + labels + lines + circles + bars + '</svg>';
}

async function openTrendPanel(button) {
  const productId = Number(button.dataset.trendProductId);
  if (!productId) return;
  activeTrendMode = 'daily';
  activeTrendData = null;
  trendProductTitle.textContent = '正在读取商品趋势…';
  trendSummary.textContent = '';
  trendNote.textContent = '';
  trendChart.innerHTML = '<div class="trend-empty">正在加载趋势数据…</div>';
  trendOverlay.hidden = false;
  trendClose.focus();
  try {
    const result = await api('/api/products/' + productId + '/trend');
    if (trendOverlay.hidden) return;
    activeTrendData = result;
    trendProductTitle.textContent = result.product?.title || '当前商品';
    renderTrendChart();
  } catch (error) {
    trendProductTitle.textContent = '成交趋势';
    trendChart.innerHTML = '<div class="trend-empty">' + esc(error.message || '趋势数据加载失败') + '</div>';
  }
}

async function runAction(action, button) {
  const productId = activeActionProductId;
  if (!productId || button.disabled) return;
  if (action === 'remove' && !confirm('确认移出单品监控？历史采集数据会保留。')) return;
  if (action === 'leave-selection' && !confirm('确认移出选品中心？商品主体和历史数据都会保留。')) return;
  if (action === 'leave-shop' && !confirm('确认移出店铺监控？商品主体和历史采集数据都会保留。')) return;

  const buttons = actionOverlay.querySelectorAll('button[data-modal-action]');
  buttons.forEach(item => item.disabled = true);
  try {
    if (action === 'collect') {
      const result = await api('/api/products/' + productId + '/collect', {method:'POST', body:'{}'});
      showNotice('采集任务 #' + result.job_id + ' 已提交，后台正在处理。', 'success');
    } else if (action === 'pause' || action === 'resume') {
      await api('/api/products/' + productId + '/state', {
        method:'POST', body:JSON.stringify({state: action === 'pause' ? 'paused' : 'active'})
      });
      showNotice(action === 'pause' ? '已暂停该商品。' : '已恢复该商品监控。', 'success');
    } else if (action === 'selection') {
      await api('/api/products/' + productId + '/selection', {method:'POST', body:'{}'});
      showNotice('已加入选品中心。', 'success');
    } else if (action === 'shop') {
      const result = await api('/api/products/' + productId + '/shop-monitor', {method:'POST', body:'{}'});
      showNotice(
        result.job_id
          ? '已加入店铺监控，并提交店铺资料刷新任务 #' + result.job_id + '。'
          : '已加入店铺监控。',
        'success'
      );
    } else if (action === 'leave-shop') {
      await api('/api/products/' + productId + '/shop-monitor', {method:'DELETE'});
      showNotice('已移出店铺监控；商品主体和历史数据均保留。', 'success');
    } else if (action === 'leave-selection') {
      await api('/api/products/' + productId + '/selection', {method:'DELETE'});
      showNotice('已移出选品中心；商品主体和历史数据均保留。', 'success');
    } else if (action === 'remove') {
      await api('/api/products/' + productId + '/monitor', {method:'DELETE'});
      showNotice('已移出单品监控，历史数据保留。', 'success');
    }
    closeActionPanel();
    await reloadCurrentView(true);
  } catch (error) {
    closeActionPanel();
    showNotice(error.message || '操作失败', 'error');
    await reloadCurrentView(true).catch(() => {});
  }
}

async function reloadCurrentView(keepNotice = false) {
  if (view === 'single') return loadSinglePage({keepNotice});
  if (view === 'selection') return loadSelectionPage({keepNotice});
  return renderShopsPage({keepNotice});
}

content.addEventListener('click', event => {
  const trend = event.target.closest('button[data-trend-product-id]');
  if (trend) {
    openTrendPanel(trend);
    return;
  }
  const more = event.target.closest('button[data-more-product-id]');
  if (more) {
    openActionPanel(more);
    return;
  }
  const toggle = event.target.closest('[data-shop-toggle]');
  if (toggle && !event.target.closest('a,button,input,select')) {
    const key = toggle.dataset.shopToggle;
    if (expandedShopKeys.has(key)) expandedShopKeys.delete(key);
    else expandedShopKeys.add(key);
    renderShopList();
  }
});

toolbar.addEventListener('click', event => {
  const more = event.target.closest('button[data-more-product-id]');
  if (more) openActionPanel(more);
});

actionOverlay.addEventListener('click', event => {
  if (event.target === actionOverlay) closeActionPanel();
  const button = event.target.closest('button[data-modal-action]');
  if (button && !button.disabled) runAction(button.dataset.modalAction, button);
});
actionClose.addEventListener('click', closeActionPanel);

trendOverlay.addEventListener('click', event => {
  if (event.target === trendOverlay) closeTrendPanel();
});
trendClose.addEventListener('click', closeTrendPanel);
trendTabs.forEach(tab => tab.addEventListener('click', () => {
  activeTrendMode = tab.dataset.trendMode;
  renderTrendChart();
}));

shopImportOverlay.addEventListener('click', event => {
  if (event.target === shopImportOverlay) closeShopImport();
});
shopImportClose.addEventListener('click', closeShopImport);
shopImportCancel.addEventListener('click', closeShopImport);
shopImportSubmit.addEventListener('click', submitProductImport);

exportOverlay.addEventListener('click', event => {
  if (event.target === exportOverlay) closeExportDialog();
});
exportClose.addEventListener('click', closeExportDialog);
exportCancel.addEventListener('click', closeExportDialog);
exportCsv.addEventListener('click', () => submitExport('csv'));
exportXlsx.addEventListener('click', () => submitExport('xlsx'));

if (window.chrome?.webview?.addEventListener) {
  window.chrome.webview.addEventListener('message', event => {
    const message = event.data;
    if (!message || message.type !== 'export-result') return;
    if (message.cancelled) {
      showNotice(message.message || '已取消导出。');
    } else {
      showNotice(
        message.message || (message.ok ? '导出完成。' : '导出失败。'),
        message.ok ? 'success' : 'error'
      );
    }
  });
}

settingsOverlay.addEventListener('click', event => {
  if (event.target === settingsOverlay) closeSettings();
});
settingsClose.addEventListener('click', closeSettings);
settingsCancel.addEventListener('click', closeSettings);
settingsSave.addEventListener('click', saveSettings);

document.addEventListener('keydown', event => {
  if (event.key !== 'Escape') return;
  if (!exportOverlay.hidden) closeExportDialog();
  else if (!shopImportOverlay.hidden) closeShopImport();
  else if (!settingsOverlay.hidden) closeSettings();
  else if (!trendOverlay.hidden) closeTrendPanel();
  else if (!actionOverlay.hidden) closeActionPanel();
});

window.addEventListener('xhs-import-queued', event => {
  const jobId = Number(event.detail?.jobId);
  showNotice('添加任务 #' + jobId + ' 已提交，后台采集中，可以继续浏览。', 'success');
  watchImportJob(jobId);
});

window.addEventListener('xhs-open-settings', () => {
  openSettings();
});

reloadCurrentView(false).catch(error => {
  showNotice(error.message || '本地服务暂不可用，请查看启动状态。', 'error');
  content.innerHTML = '<div class="empty">页面加载失败</div>';
});

setInterval(() => {
  refreshCurrentViewData().catch(() => {});
}, 30000);
