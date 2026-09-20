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

const shopImportOverlay = document.querySelector('#shopImportOverlay');
const shopImportClose = document.querySelector('#shopImportClose');
const shopImportCancel = document.querySelector('#shopImportCancel');
const shopImportSubmit = document.querySelector('#shopImportSubmit');
const shopImportText = document.querySelector('#shopImportText');

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

let activeActionProductId = null;
let activeActionContext = 'single';
let allProducts = [];
let allShops = [];
let expandedShopKeys = new Set();
let productPage = 1;
let productPageSize = 30;
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
  return base + '<small class="metric-hint">加入后 · 已监控' + esc(monitoredDuration(metric)) + '</small>';
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
  return (Number.isInteger(rounded) ? rounded.toFixed(0) : rounded.toFixed(1)) + ' 小时区间';
}

function incrementCell(metric) {
  if (!metric || metric.value == null) return metricCell(metric);
  const base = metricCell(metric);
  const hint = intervalHint(metric.hours);
  return base + (hint ? '<small class="metric-hint">' + esc(hint) + '</small>' : '');
}

function summaryMetric(products, key) {
  const values = products
    .filter(p => key !== 'rolling24' || !p[key]?.partial)
    .map(p => metricValue(p[key]))
    .filter(v => v != null);
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
    '<button class="btn" id="exportButton" type="button">⇩ 导出</button>' +
    '<button class="btn primary" id="collectPageButton" type="button">立即采集本页</button>' +
    '<button class="btn" id="settingsButton" type="button">设置</button>';

  document.querySelector('#toolbarSearch').addEventListener('input', () => { productPage = 1; renderCurrentProductList(); });
  document.querySelector('#shopFilter').addEventListener('change', () => { productPage = 1; renderCurrentProductList(); });
  document.querySelector('#sortSelect').addEventListener('change', () => { productPage = 1; renderCurrentProductList(); });
  document.querySelector('#exportButton').addEventListener('click', openExportDialog);
  document.querySelector('#collectPageButton').addEventListener('click', collectVisibleProducts);
  document.querySelector('#settingsButton').addEventListener('click', openSettings);
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
  if (sortKey === 'rolling24_desc') result.sort((a,b) => {
    const rank = product => product.rolling24?.value == null ? 2 : (product.rolling24?.partial ? 1 : 0);
    return rank(a) - rank(b) || metricNumber(b,'rolling24') - metricNumber(a,'rolling24');
  });
  else if (sortKey === 'today_desc') result.sort((a,b) => metricNumber(b,'today') - metricNumber(a,'today'));
  else if (sortKey === 'sales_desc') result.sort((a,b) => metricNumber(b,'sales') - metricNumber(a,'sales'));
  else result.sort((a,b) => metricNumber(b,'updated') - metricNumber(a,'updated'));
  return result;
}

function productRow(product, context) {
  const paused = product.monitor_state === 'paused';
  const selected = Number(product.in_selection_pool) === 1;
  const inShop = Number(product.in_shop_monitor) === 1;
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
      '<td class="num">' + totalSalesCell(product) + '</td>' +
      '<td class="num">' + monitoredMetricCell(product.today, true) + '</td>' +
      '<td class="num">' + monitoredMetricCell(product.rolling24, true) + '</td>' +
      '<td class="num">' + incrementCell(product.increment) + '</td>' +
      '<td><span>' + esc(product.last_collected_at || '—') + '</span></td>' +
      '<td><span class="status ' + (paused ? 'paused' : (product.health || 'active')) + '">' +
        esc(paused ? '● 已暂停' : ('● ' + (product.health_label || '正常'))) + '</span></td>' +
      '<td><div class="actions"><button class="more-btn" type="button" aria-label="打开商品操作" title="商品操作" ' +
      'data-more-product-id="' + product.id + '" data-more-title="' + esc(product.title) + '" ' +
      'data-more-paused="' + (paused ? '1' : '0') + '" data-more-selected="' + (selected ? '1' : '0') + '" ' +
      'data-more-shop="' + (inShop ? '1' : '0') + '" data-more-context="' + esc(context) + '">···</button></div></td></tr>';
}

function renderProductTable(products, context, total) {
  const pager = renderProductPager(total);
  if (!products.length) {
    content.innerHTML = '<div class="empty">' +
      (context === 'selection' ? '选品中心还没有符合当前条件的商品。' : '没有符合当前条件的商品。') +
      '</div>' + pager;
    bindProductPager();
    return;
  }
  content.innerHTML =
    '<div class="tablewrap"><table><thead><tr>' +
    '<th style="width:24%">商品 / 店铺</th><th style="width:7%">当前价</th><th style="width:9%">累计销量</th>' +
    '<th style="width:9%">今日新增</th><th style="width:9%">近24小时新增</th><th style="width:10%">最近区间新增</th>' +
    '<th style="width:12%">最近更新</th><th style="width:8%">状态</th><th style="width:6%">操作</th>' +
    '</tr></thead><tbody>' + products.map(product => productRow(product, context)).join('') + '</tbody></table></div>' +
    pager;
  bindProductPager();
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

function renderProductPager(total) {
  const pages = Math.max(1, Math.ceil(total / productPageSize));
  productPage = Math.min(productPage, pages);
  const start = total ? (productPage - 1) * productPageSize + 1 : 0;
  const end = Math.min(total, productPage * productPageSize);
  return '<div class="pager">' +
    '<span>每页</span><select class="selectbox pager-size" id="productPageSize">' +
      [30,50,100].map(size => '<option value="' + size + '"' + (productPageSize === size ? ' selected' : '') + '>' + size + '</option>').join('') +
    '</select><span>共 ' + total + ' 个 · ' + start + '-' + end + '</span><div class="grow"></div>' +
    '<button class="btn" id="productPrev" type="button"' + (productPage <= 1 ? ' disabled' : '') + '>‹</button>' +
    '<span class="page-current">' + productPage + ' / ' + pages + '</span>' +
    '<button class="btn" id="productNext" type="button"' + (productPage >= pages ? ' disabled' : '') + '>›</button></div>';
}

function currentProductPageItems() {
  const products = currentFilteredProducts();
  const pages = Math.max(1, Math.ceil(products.length / productPageSize));
  if (productPage > pages) productPage = pages;
  const start = (productPage - 1) * productPageSize;
  return products.slice(start, start + productPageSize);
}

function bindProductPager() {
  document.querySelector('#productPageSize')?.addEventListener('change', event => {
    productPageSize = Number(event.target.value) || 30;
    productPage = 1;
    renderCurrentProductList();
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
    '<button class="btn" id="exportButton" type="button">⇩ 导出</button>' +
    '<button class="btn" id="addShopProductButton" type="button">＋ 添加商品</button>' +
    '<button class="btn primary" id="collectShopPageButton" type="button">立即采集本页</button>' +
    '<button class="btn" id="settingsButton" type="button">设置</button>';

  document.querySelector('#toolbarSearch').addEventListener('input', () => { shopPage = 1; renderShopList(); });
  document.querySelector('#shopSort').addEventListener('change', () => { shopPage = 1; renderShopList(); });
  document.querySelector('#exportButton').addEventListener('click', openExportDialog);
  document.querySelector('#addShopProductButton').addEventListener('click', openShopImport);
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
    '<td>' + esc(product.last_collected_at || '—') + '</td>' +
    '<td><button class="more-btn" type="button" aria-label="打开商品操作" title="商品操作" ' +
      'data-more-product-id="' + product.id + '" data-more-title="' + esc(product.title) + '" ' +
      'data-more-paused="' + (paused ? '1' : '0') + '" data-more-selected="' + (selected ? '1' : '0') + '" ' +
      'data-more-shop="1" data-more-context="shop">···</button></td>' +
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

async function collectVisibleProducts() {
  const button = document.querySelector('#collectPageButton');
  await collectProducts(
    currentProductPageItems(),
    button,
    view === 'selection' ? 'selection' : 'single'
  );
}

async function collectVisibleShopProducts() {
  const button = document.querySelector('#collectShopPageButton');
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
    updated_at: product.last_collected_at || '',
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
        updated_at: product.last_collected_at || '',
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

function openShopImport() {
  shopImportOverlay.hidden = false;
  shopImportText.value = '';
  shopImportSubmit.disabled = false;
  shopImportText.focus();
}

async function submitShopImport() {
  const text = shopImportText.value.trim();
  if (!text) {
    showNotice('请先粘贴商品分享链接或分享口令。', 'error');
    return;
  }
  shopImportSubmit.disabled = true;
  shopImportSubmit.textContent = '提交中…';
  try {
    const result = await api('/api/shops/import', {
      method:'POST',
      body:JSON.stringify({text})
    });
    closeShopImport();
    showNotice(
      '店铺监控添加任务 #' + result.job_id + ' 已提交，共识别 ' + result.count + ' 个商品；采集后会自动按所属店铺归类。',
      'success'
    );
  } catch (error) {
    showNotice(error.message || '添加店铺监控商品失败', 'error');
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
  if (!actionOverlay.hidden || !settingsOverlay.hidden || !shopImportOverlay.hidden || !exportOverlay.hidden) return;
  if (view === 'single') {
    allProducts = await api('/api/products');
    productHeader(allProducts, false);
    renderCurrentProductList();
    return;
  }
  if (view === 'selection') {
    allProducts = await api('/api/selection');
    productHeader(allProducts, true);
    renderCurrentProductList();
    return;
  }
  allShops = await api('/api/shops');
  shopsHeader();
  renderShopList();
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

shopImportOverlay.addEventListener('click', event => {
  if (event.target === shopImportOverlay) closeShopImport();
});
shopImportClose.addEventListener('click', closeShopImport);
shopImportCancel.addEventListener('click', closeShopImport);
shopImportSubmit.addEventListener('click', submitShopImport);

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
  else if (!actionOverlay.hidden) closeActionPanel();
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

setInterval(() => {
  refreshCurrentViewData().catch(() => {});
}, 15000);
