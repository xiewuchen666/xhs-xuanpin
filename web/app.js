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
const actionRemove = document.querySelector('#actionRemove');

let activeActionProductId = null;
let activeActionContext = 'single';
let allProducts = [];
let allShops = [];
let expandedShopKeys = new Set();
let shopPage = 1;
let shopPageSize = 30;

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
    const reason = esc(metric?.reason || '缺少有效采样');
    return '<span class="metric-value" title="' + reason + '">—</span><small class="metric-hint" title="' + reason + '">' +
      (metric?.quality === 'anomaly' ? '计数异常' : '待有效采样') + '</small>';
  }
  const reason = esc(metric.reason || '');
  const value = Number(metric.value);
  const display = value > 0 ? '+' + formatSales(value) : formatSales(value);
  const valueClass = positiveAccent && value > 0 ? 'metric-value positive' : 'metric-value';
  const suffix = metric.quality === 'approximate' ? '<small class="metric-hint">近似边界</small>' : '';
  return '<span class="' + valueClass + '" title="' + reason + '">' + display + '</span>' + suffix;
}

function summaryMetric(products, key) {
  const values = products.map(p => metricValue(p[key])).filter(v => v != null);
  if (!values.length) return '—';
  return formatSales(values.reduce((sum, value) => sum + value, 0));
}

function pageHeader(title, countText, subtitle, cards) {
  pageHead.innerHTML =
    '<div class="titleline"><h1>' + esc(title) + '</h1><span class="count">' + esc(countText) + '</span></div>' +
    '<div class="subtitle">' + esc(subtitle) + '</div>' +
    '<div class="metrics">' +
    cards.map(card =>
      '<div class="metric"><span>' + esc(card.label) + '</span><b>' + esc(card.value) + '</b></div>'
    ).join('') +
    '</div>';
}

function productHeader(products, selectionMode = false) {
  const todayValues = products.map(p => metricValue(p.today)).filter(v => v != null);
  pageHeader(
    selectionMode ? '选品中心' : '单品监控',
    products.length + ' 个商品',
    selectionMode
      ? '展示已人工确认进入选品范围的商品；持续监控和指标口径与单品监控一致。'
      : '只展示你主动加入单品监控的商品；指标口径沿用已确认采集规则。',
    [
      {label: selectionMode ? '选品商品' : '监控中', value: selectionMode ? String(products.length) : String(products.filter(p => p.monitor_state === 'active').length)},
      {label: '今日有新增', value: todayValues.length ? String(products.filter(p => Number(p.today?.value) > 0).length) : '—'},
      {label: '近24h新增合计', value: summaryMetric(products, 'rolling24')},
      {label: '需关注', value: String(products.filter(p => p.monitor_state !== 'paused' && ['warning','danger'].includes(p.health)).length)}
    ]
  );
}

function productExternalHref(product) {
  return String(product.url || '#');
}

function productToolbar(products) {
  const shops = [...new Set(products.map(p => (p.shop_name || '').trim()).filter(Boolean))]
    .sort((a,b) => a.localeCompare(b, 'zh-CN'));
  toolbar.innerHTML =
    '<label class="searchbox" aria-label="搜索商品或店铺"><span>⌕</span><input id="toolbarSearch" type="search" placeholder="搜索商品或店铺"></label>' +
    '<select class="selectbox" id="shopFilter" aria-label="店铺筛选"><option value="">全部店铺</option>' +
      shops.map(shop => '<option value="' + esc(shop) + '">' + esc(shop) + '</option>').join('') +
    '</select>' +
    '<select class="selectbox" id="sortSelect" aria-label="排序方式">' +
      '<option value="rolling24_desc">近24h新增 ↓</option><option value="today_desc">今日新增 ↓</option>' +
      '<option value="sales_desc">累计销量 ↓</option><option value="updated_desc">最近更新 ↓</option>' +
    '</select><div class="grow"></div>' +
    '<button class="btn" type="button" disabled title="导出将在后续阶段实现">⇩ 导出</button>' +
    '<button class="btn primary" id="collectPageButton" type="button">立即采集本页</button>' +
    '<button class="btn" id="settingsButton" type="button">设置</button>';

  document.querySelector('#toolbarSearch').addEventListener('input', renderCurrentProductList);
  document.querySelector('#shopFilter').addEventListener('change', renderCurrentProductList);
  document.querySelector('#sortSelect').addEventListener('change', renderCurrentProductList);
  document.querySelector('#collectPageButton').addEventListener('click', collectVisibleProducts);
  document.querySelector('#settingsButton').addEventListener('click', () => {
    showNotice('自动采集设置将在下一阶段启用；当前规划的全局采集间隔为 60 分钟。');
  });
}

function metricNumber(product, key) {
  if (key === 'sales') return product.total_sales == null ? Number.NEGATIVE_INFINITY : Number(product.total_sales);
  if (key === 'updated') return Date.parse(String(product.last_collected_at || '').replace(' ', 'T')) || 0;
  const value = product[key]?.value;
  return value == null ? Number.NEGATIVE_INFINITY : Number(value);
}

function filterAndSortProducts(products) {
  const search = document.querySelector('#toolbarSearch');
  const shop = document.querySelector('#shopFilter');
  const sort = document.querySelector('#sortSelect');
  const term = (search?.value || '').trim().toLowerCase();
  const shopName = shop?.value || '';
  const result = products.filter(product => {
    const haystack = ((product.title || '') + ' ' + (product.shop_name || '')).toLowerCase();
    return (!term || haystack.includes(term)) && (!shopName || product.shop_name === shopName);
  });

  const sortKey = sort?.value || 'rolling24_desc';
  if (sortKey === 'rolling24_desc') result.sort((a,b) => metricNumber(b,'rolling24') - metricNumber(a,'rolling24'));
  else if (sortKey === 'today_desc') result.sort((a,b) => metricNumber(b,'today') - metricNumber(a,'today'));
  else if (sortKey === 'sales_desc') result.sort((a,b) => metricNumber(b,'sales') - metricNumber(a,'sales'));
  else result.sort((a,b) => metricNumber(b,'updated') - metricNumber(a,'updated'));
  return result;
}

function productRow(product, context) {
  const paused = product.monitor_state === 'paused';
  const selected = Number(product.in_selection_pool) === 1;
  const image = product.image_url
    ? '<img src="' + esc(product.image_url) + '" alt="" referrerpolicy="no-referrer">'
    : '<img alt="">';
  return '<tr data-product-id="' + product.id + '">' +
      '<td><div class="product">' + image + '<div class="copy">' +
      '<a class="product-title-link" href="' + esc(productExternalHref(product)) + '" target="_blank" rel="noopener noreferrer" title="' + esc(product.title) + '">' + esc(product.title) + '</a>' +
      '<span title="' + esc(product.shop_name || '店铺未识别') + '">' + esc(product.shop_name || '店铺未识别') + '</span>' +
      (selected && context !== 'selection' ? '<em class="selected">★ 已在选品中心</em>' : '') +
      '</div></div></td>' +
      '<td class="num">' + formatPrice(product.price) + '</td>' +
      '<td class="num"><span class="metric-value">' + formatSales(product.total_sales) + '</span><small class="metric-hint">' + esc(product.precision_label || '') + '</small></td>' +
      '<td class="num">' + metricCell(product.today, true) + '</td>' +
      '<td class="num">' + metricCell(product.rolling24, true) + '</td>' +
      '<td class="num">' + metricCell(product.increment) + '</td>' +
      '<td><span>' + esc(product.last_collected_at || '—') + '</span></td>' +
      '<td><span class="status ' + (paused ? 'paused' : (product.health || 'active')) + '">' +
        esc(paused ? '● 已暂停' : ('● ' + (product.health_label || '正常'))) + '</span></td>' +
      '<td><div class="actions"><button class="more-btn" type="button" aria-label="打开商品操作" title="商品操作" ' +
      'data-more-product-id="' + product.id + '" data-more-title="' + esc(product.title) + '" ' +
      'data-more-paused="' + (paused ? '1' : '0') + '" data-more-selected="' + (selected ? '1' : '0') + '" ' +
      'data-more-context="' + esc(context) + '">···</button></div></td></tr>';
}

function renderProductTable(products, context) {
  if (!products.length) {
    content.innerHTML = '<div class="empty">' +
      (context === 'selection' ? '选品中心还没有商品。' : '没有符合当前条件的商品。') +
      '</div>';
    return;
  }
  content.innerHTML =
    '<div class="tablewrap"><table><thead><tr>' +
    '<th style="width:24%">商品 / 店铺</th><th style="width:7%">当前价</th><th style="width:9%">累计销量</th>' +
    '<th style="width:9%">今日新增</th><th style="width:9%">近24小时新增</th><th style="width:10%">最近区间新增</th>' +
    '<th style="width:12%">最近更新</th><th style="width:8%">状态</th><th style="width:6%">操作</th>' +
    '</tr></thead><tbody>' + products.map(product => productRow(product, context)).join('') + '</tbody></table></div>';
}

function currentProductSource() {
  return allProducts;
}

function currentProductContext() {
  return view === 'selection' ? 'selection' : 'single';
}

function renderCurrentProductList() {
  renderProductTable(filterAndSortProducts(currentProductSource()), currentProductContext());
}

async function loadSinglePage({keepNotice = false} = {}) {
  allProducts = await api('/api/products');
  productHeader(allProducts, false);
  productToolbar(allProducts);
  renderCurrentProductList();
  if (!keepNotice) hideNotice();
}

async function loadSelectionPage({keepNotice = false} = {}) {
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
  pageHeader(
    '店铺监控',
    allShops.length + ' 家店铺',
    '仅汇总你主动监控商品所属店铺，不自动采集整店商品。',
    [
      {label:'监控店铺', value:String(allShops.length)},
      {label:'监控商品', value:String(allShops.reduce((sum,shop) => sum + Number(shop.product_count || 0), 0))},
      {label:'今日新增汇总', value:aggregateShopHeader('today')},
      {label:'近24h新增汇总', value:aggregateShopHeader('rolling24')}
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
    '<button class="btn" type="button" disabled title="导出将在后续阶段实现">⇩ 导出</button>' +
    '<button class="btn primary" id="collectShopPageButton" type="button">立即采集本页</button>';

  document.querySelector('#toolbarSearch').addEventListener('input', () => { shopPage = 1; renderShopList(); });
  document.querySelector('#shopSort').addEventListener('change', () => { shopPage = 1; renderShopList(); });
  document.querySelector('#collectShopPageButton').addEventListener('click', collectVisibleShopProducts);
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
    '<td class="num"><span class="metric-value">' + formatSales(product.total_sales) + '</span><small class="metric-hint">' + esc(product.precision_label || '') + '</small></td>' +
    '<td class="num">' + metricCell(product.today, true) + '</td>' +
    '<td class="num">' + metricCell(product.rolling24, true) + '</td>' +
    '<td>' + esc(product.last_collected_at || '—') + '</td>' +
    '<td><button class="more-btn" type="button" aria-label="打开商品操作" title="商品操作" ' +
      'data-more-product-id="' + product.id + '" data-more-title="' + esc(product.title) + '" ' +
      'data-more-paused="' + (paused ? '1' : '0') + '" data-more-selected="' + (selected ? '1' : '0') + '" data-more-context="shop">···</button></td>' +
    '</tr>';
}

function shopExpandedTable(shop) {
  return '<div class="shop-expand"><table class="shop-products-table"><thead><tr>' +
    '<th style="width:30%">已监控商品</th><th style="width:9%">当前价</th><th style="width:12%">累计销量</th>' +
    '<th style="width:12%">今日新增</th><th style="width:12%">近24小时</th><th style="width:17%">更新时间</th><th style="width:8%">操作</th>' +
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
    content.innerHTML = '<div class="empty">没有符合条件的店铺。</div>' + renderShopPager(shops.length);
  } else {
    content.innerHTML = '<div class="shoplist">' + pageItems.map(shop => {
      const initial = esc((shop.shop_name || '店').slice(0,1));
      const expanded = expandedShopKeys.has(shop.shop_key);
      return '<div class="shopcard">' +
        '<div class="shoprow" data-shop-toggle="' + esc(shop.shop_key) + '" aria-expanded="' + (expanded ? 'true' : 'false') + '">' +
        '<div class="shopid"><div class="shoplogo">' + initial + '</div><div><b>' + esc(shop.shop_name) + '</b><span>' + shop.product_count + ' 个已监控商品</span></div></div>' +
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

async function collectProducts(products, button) {
  const targets = products.filter(p => p.monitor_state === 'active');
  if (!targets.length) {
    showNotice('当前范围没有可立即采集的正常商品。');
    return;
  }
  const original = button.textContent;
  button.disabled = true;
  button.textContent = '采集中…';
  let success = 0, failed = 0;
  for (const product of targets) {
    try {
      await api('/api/products/' + product.id + '/collect', {method:'POST', body:'{}'});
      success += 1;
    } catch (_) {
      failed += 1;
    }
  }
  button.disabled = false;
  button.textContent = original;
  await reloadCurrentView(true);
  showNotice(
    failed ? '采集完成：成功 ' + success + ' 个，失败 ' + failed + ' 个。' : success + ' 个商品已完成立即采集。',
    failed ? 'error' : 'success'
  );
}

async function collectVisibleProducts() {
  const button = document.querySelector('#collectPageButton');
  await collectProducts(filterAndSortProducts(allProducts), button);
}

async function collectVisibleShopProducts() {
  const button = document.querySelector('#collectShopPageButton');
  const productsById = new Map();
  currentShopPageItems().forEach(shop => (shop.products || []).forEach(product => productsById.set(product.id, product)));
  await collectProducts([...productsById.values()], button);
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

  [actionCollect, actionPause, actionSelection, actionRemove].forEach(item => {
    item.disabled = false;
    item.hidden = false;
  });

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
    actionRemove.hidden = true;
  } else {
    actionSelection.dataset.modalAction = 'selection';
    actionSelection.classList.remove('danger');
    actionSelection.querySelector('.action-icon').textContent = '☆';
    actionSelection.disabled = selected;
    actionSelection.querySelector('strong').textContent = selected ? '已加入选品中心' : '加入选品中心';
    actionSelection.querySelector('small').textContent = selected ? '该商品已经在选品中心中' : '保留当前监控，同时加入选品中心';
    actionRemove.hidden = false;
    actionRemove.disabled = false;
    actionRemove.querySelector('small').textContent = '移出单品监控列表，历史采集数据保留';
  }

  actionOverlay.hidden = false;
  actionClose.focus();
}

async function runAction(action, button) {
  const productId = activeActionProductId;
  if (!productId || button.disabled) return;
  if (action === 'remove' && !confirm('确认移出单品监控？历史采集数据会保留。')) return;
  if (action === 'leave-selection' && !confirm('确认移出选品中心？商品主体和历史数据都会保留。')) return;

  const buttons = actionOverlay.querySelectorAll('button[data-modal-action]');
  buttons.forEach(item => item.disabled = true);
  try {
    if (action === 'collect') {
      await api('/api/products/' + productId + '/collect', {method:'POST', body:'{}'});
      showNotice('立即采集完成。', 'success');
    } else if (action === 'pause' || action === 'resume') {
      await api('/api/products/' + productId + '/state', {
        method:'POST', body:JSON.stringify({state: action === 'pause' ? 'paused' : 'active'})
      });
      showNotice(action === 'pause' ? '已暂停该商品。' : '已恢复该商品监控。', 'success');
    } else if (action === 'selection') {
      await api('/api/products/' + productId + '/selection', {method:'POST', body:'{}'});
      showNotice('已加入选品中心。', 'success');
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
document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !actionOverlay.hidden) closeActionPanel();
});

window.addEventListener('xhs-product-collected', () => {
  reloadCurrentView(true)
    .then(() => showNotice('商品数据已写入，当前页面已刷新。', 'success'))
    .catch(() => showNotice('本地服务暂不可用，请查看启动状态。', 'error'));
});

reloadCurrentView(false).catch(error => {
  showNotice(error.message || '本地服务暂不可用，请查看启动状态。', 'error');
  content.innerHTML = '<div class="empty">页面加载失败</div>';
});
