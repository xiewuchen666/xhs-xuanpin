const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

const notice = document.querySelector('#notice');
const content = document.querySelector('#content');
const productCount = document.querySelector('#productCount');
const monitoringCount = document.querySelector('#monitoringCount');
const todayGrowthCount = document.querySelector('#todayGrowthCount');
const rolling24Total = document.querySelector('#rolling24Total');
const attentionCount = document.querySelector('#attentionCount');

const toolbarSearch = document.querySelector('#toolbarSearch');
const shopFilter = document.querySelector('#shopFilter');
const sortSelect = document.querySelector('#sortSelect');
const collectPageButton = document.querySelector('#collectPageButton');
const settingsButton = document.querySelector('#settingsButton');

const actionOverlay = document.querySelector('#actionOverlay');
const actionProductTitle = document.querySelector('#actionProductTitle');
const actionClose = document.querySelector('#actionClose');
const actionCollect = document.querySelector('#actionCollect');
const actionPause = document.querySelector('#actionPause');
const actionSelection = document.querySelector('#actionSelection');
const actionRemove = document.querySelector('#actionRemove');

let activeActionProductId = null;
let allProducts = [];

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

function productRow(product) {
  const paused = product.monitor_state === 'paused';
  const selected = Number(product.in_selection_pool) === 1;
  const image = product.image_url
    ? '<img src="' + esc(product.image_url) + '" alt="" referrerpolicy="no-referrer">'
    : '<img alt="">';
  return '<tr data-product-id="' + product.id + '">' +
      '<td><div class="product">' + image + '<div class="copy">' +
      '<b title="' + esc(product.title) + '">' + esc(product.title) + '</b>' +
      '<span title="' + esc(product.shop_name || '店铺未识别') + '">' + esc(product.shop_name || '店铺未识别') + '</span>' +
      (selected ? '<em class="selected">★ 已在选品中心</em>' : '') +
      '</div></div></td>' +
      '<td class="num">' + formatPrice(product.price) + '</td>' +
      '<td class="num"><span class="metric-value">' + formatSales(product.total_sales) + '</span><small class="metric-hint">' + esc(product.precision_label || '') + '</small></td>' +
      '<td class="num">' + metricCell(product.today, true) + '</td>' +
      '<td class="num">' + metricCell(product.rolling24, true) + '</td>' +
      '<td class="num">' + metricCell(product.increment) + '</td>' +
      '<td><span>' + esc(product.last_collected_at || '—') + '</span></td>' +
      '<td><span class="status ' + (paused ? 'paused' : (product.health || 'active')) + '">' + esc(paused ? '● 已暂停' : ('● ' + (product.health_label || '正常'))) + '</span></td>' +
      '<td><div class="actions">' +
      '<button class="more-btn" type="button" aria-label="打开商品操作" title="商品操作" ' +
      'data-more-product-id="' + product.id + '" ' +
      'data-more-title="' + esc(product.title) + '" ' +
      'data-more-paused="' + (paused ? '1' : '0') + '" ' +
      'data-more-selected="' + (selected ? '1' : '0') + '">···</button>' +
      '</div></td></tr>';
}

function updateSummary(products) {
  productCount.textContent = products.length + ' 个商品';
  monitoringCount.textContent = products.filter(p => p.monitor_state === 'active').length;

  const todayValues = products
    .map(p => p.today?.value)
    .filter(value => value != null)
    .map(Number);
  const rollingValues = products
    .map(p => p.rolling24?.value)
    .filter(value => value != null)
    .map(Number);

  todayGrowthCount.textContent = todayValues.length
    ? products.filter(p => Number(p.today?.value) > 0).length
    : '—';
  rolling24Total.textContent = rollingValues.length
    ? rollingValues.reduce((sum, value) => sum + value, 0).toLocaleString('zh-CN')
    : '—';
  attentionCount.textContent = products.filter(
    p => p.monitor_state !== 'paused' && ['warning', 'danger'].includes(p.health)
  ).length;
}

function syncShopOptions(products) {
  const previous = shopFilter.value;
  const shops = [...new Set(products.map(p => (p.shop_name || '').trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, 'zh-CN'));

  shopFilter.innerHTML = '<option value="">全部店铺</option>' +
    shops.map(shop => '<option value="' + esc(shop) + '">' + esc(shop) + '</option>').join('');

  if (shops.includes(previous)) shopFilter.value = previous;
}

function metricNumber(product, key) {
  if (key === 'sales') return product.total_sales == null ? Number.NEGATIVE_INFINITY : Number(product.total_sales);
  if (key === 'updated') return Date.parse(String(product.last_collected_at || '').replace(' ', 'T')) || 0;
  const value = product[key]?.value;
  return value == null ? Number.NEGATIVE_INFINITY : Number(value);
}

function visibleProducts() {
  const term = toolbarSearch.value.trim().toLowerCase();
  const shop = shopFilter.value;
  let products = allProducts.filter(product => {
    const haystack = ((product.title || '') + ' ' + (product.shop_name || '')).toLowerCase();
    return (!term || haystack.includes(term)) && (!shop || product.shop_name === shop);
  });

  const sortKey = sortSelect.value;
  if (sortKey === 'rolling24_desc') {
    products.sort((a, b) => metricNumber(b, 'rolling24') - metricNumber(a, 'rolling24'));
  } else if (sortKey === 'today_desc') {
    products.sort((a, b) => metricNumber(b, 'today') - metricNumber(a, 'today'));
  } else if (sortKey === 'sales_desc') {
    products.sort((a, b) => metricNumber(b, 'sales') - metricNumber(a, 'sales'));
  } else if (sortKey === 'updated_desc') {
    products.sort((a, b) => metricNumber(b, 'updated') - metricNumber(a, 'updated'));
  }
  return products;
}

function renderProducts() {
  if (!allProducts.length) {
    content.innerHTML = '<div class="empty">尚无监控商品，请从左侧商品详情加入。</div>';
    return;
  }

  const products = visibleProducts();
  if (!products.length) {
    content.innerHTML = '<div class="empty">没有符合当前搜索或筛选条件的商品。</div>';
    return;
  }

  content.innerHTML =
    '<table><thead><tr>' +
    '<th style="width:24%">商品 / 店铺</th>' +
    '<th style="width:7%">当前价</th>' +
    '<th style="width:9%">累计销量</th>' +
    '<th style="width:9%">今日新增</th>' +
    '<th style="width:9%">近24小时新增</th>' +
    '<th style="width:10%">最近区间新增</th>' +
    '<th style="width:12%">最近更新</th>' +
    '<th style="width:8%">状态</th>' +
    '<th style="width:6%">操作</th>' +
    '</tr></thead><tbody>' + products.map(productRow).join('') + '</tbody></table>';
}

async function loadProducts({keepNotice = false} = {}) {
  allProducts = await fetch('/api/products').then(async response => {
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response.json();
  });

  updateSummary(allProducts);
  syncShopOptions(allProducts);
  renderProducts();

  if (!allProducts.length) {
    if (!keepNotice) showNotice('请在左侧打开商品详情，点击“加入监控”。首次采集成功后会自动出现在这里。');
    return;
  }
  if (!keepNotice) hideNotice();
}

async function collectVisibleProducts() {
  const targets = visibleProducts().filter(p => p.monitor_state === 'active');
  if (!targets.length) {
    showNotice('当前筛选结果中没有可立即采集的正常商品。');
    return;
  }

  const originalText = collectPageButton.textContent;
  collectPageButton.disabled = true;
  collectPageButton.textContent = '采集中…';
  let success = 0;
  let failed = 0;

  for (const product of targets) {
    try {
      await api('/api/products/' + product.id + '/collect', {method: 'POST', body: '{}'});
      success += 1;
    } catch (_) {
      failed += 1;
    }
  }

  collectPageButton.disabled = false;
  collectPageButton.textContent = originalText;
  await loadProducts({keepNotice: true});
  showNotice(
    failed
      ? '本页采集完成：成功 ' + success + ' 个，失败 ' + failed + ' 个。'
      : '本页 ' + success + ' 个商品已完成立即采集。',
    failed ? 'error' : 'success'
  );
}

function closeActionPanel() {
  actionOverlay.hidden = true;
  activeActionProductId = null;
}

function openActionPanel(button) {
  activeActionProductId = Number(button.dataset.moreProductId);
  const paused = button.dataset.morePaused === '1';
  const selected = button.dataset.moreSelected === '1';

  [actionCollect, actionPause, actionSelection, actionRemove].forEach(item => {
    item.disabled = false;
  });

  actionProductTitle.textContent = button.dataset.moreTitle || '当前商品';
  actionCollect.disabled = paused;
  actionPause.dataset.modalAction = paused ? 'resume' : 'pause';
  actionPause.querySelector('strong').textContent = paused ? '恢复监控' : '暂停监控';
  actionPause.querySelector('small').textContent = paused ? '恢复后重新参与后续采集' : '停止后续自动采集，可随时恢复';
  actionPause.querySelector('.action-icon').textContent = paused ? '▶' : 'Ⅱ';
  actionSelection.disabled = selected;
  actionSelection.querySelector('strong').textContent = selected ? '已加入选品中心' : '加入选品中心';
  actionSelection.querySelector('small').textContent = selected ? '该商品已经在选品工作区中' : '保留监控，同时加入选品工作区';

  actionOverlay.hidden = false;
  actionClose.focus();
}

async function runAction(action, button) {
  const productId = activeActionProductId;
  if (!productId || button.disabled) return;
  if (action === 'remove' && !confirm('确认移出单品监控？历史采集数据会保留。')) return;

  const buttons = actionOverlay.querySelectorAll('button[data-modal-action]');
  buttons.forEach(item => item.disabled = true);
  const originalStrong = button.querySelector('strong')?.textContent || '';
  if (button.querySelector('strong')) {
    button.querySelector('strong').textContent = action === 'collect' ? '采集中…' : '处理中…';
  }

  try {
    if (action === 'collect') {
      await api('/api/products/' + productId + '/collect', {method: 'POST', body: '{}'});
      showNotice('立即采集完成，最新商品数据和历史快照已保存。', 'success');
    } else if (action === 'pause' || action === 'resume') {
      const state = action === 'pause' ? 'paused' : 'active';
      await api('/api/products/' + productId + '/state', {
        method: 'POST',
        body: JSON.stringify({state})
      });
      showNotice(action === 'pause' ? '已暂停该商品。' : '已恢复该商品监控。', 'success');
    } else if (action === 'selection') {
      await api('/api/products/' + productId + '/selection', {method: 'POST', body: '{}'});
      showNotice('已加入选品中心；商品仍保留在单品监控中。', 'success');
    } else if (action === 'remove') {
      await api('/api/products/' + productId + '/monitor', {method: 'DELETE'});
      showNotice('已移出单品监控，商品主体和历史采集数据均已保留。', 'success');
    }
    closeActionPanel();
    await loadProducts({keepNotice: true});
  } catch (error) {
    showNotice(error.message || '操作失败', 'error');
    if (button.querySelector('strong')) button.querySelector('strong').textContent = originalStrong;
    closeActionPanel();
    await loadProducts({keepNotice: true}).catch(() => {});
  }
}

content.addEventListener('click', event => {
  const button = event.target.closest('button[data-more-product-id]');
  if (button) openActionPanel(button);
});

toolbarSearch.addEventListener('input', renderProducts);
shopFilter.addEventListener('change', renderProducts);
sortSelect.addEventListener('change', renderProducts);
collectPageButton.addEventListener('click', collectVisibleProducts);
settingsButton.addEventListener('click', () => {
  showNotice('自动采集设置将在下一阶段启用；当前规划的全局采集间隔为 60 分钟。');
});

actionOverlay.addEventListener('click', event => {
  if (event.target === actionOverlay) closeActionPanel();
});

actionClose.addEventListener('click', closeActionPanel);

actionOverlay.addEventListener('click', event => {
  const button = event.target.closest('button[data-modal-action]');
  if (button && !button.disabled) runAction(button.dataset.modalAction, button);
});

document.addEventListener('keydown', event => {
  if (event.key === 'Escape' && !actionOverlay.hidden) closeActionPanel();
});

window.addEventListener('xhs-product-collected', () => {
  showNotice('商品数据已写入，单品监控列表已刷新。', 'success');
  loadProducts({keepNotice: true}).catch(() => showNotice('本地服务暂不可用，请查看启动状态。', 'error'));
});

loadProducts().catch(() => showNotice('本地服务暂不可用，请查看启动状态。', 'error'));
