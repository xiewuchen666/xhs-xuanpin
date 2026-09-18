const esc = value => String(value ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

async function loadProducts() {
  const products = await fetch('/api/products').then(response => response.json());
  document.querySelector('#count').textContent = products.length;
  if (!products.length) return;
  document.querySelector('#notice').hidden = true;
  document.querySelector('#content').innerHTML = `<table><thead><tr><th style="width:42%">商品 / 店铺</th><th>当前价</th><th>累计销量</th><th>最近更新</th><th>状态</th></tr></thead><tbody>${products.map(product => `
    <tr><td><div class="product"><img src="${esc(product.image_url)}" alt=""><div class="copy"><b>${esc(product.title)}</b><span>${esc(product.shop_name || '店铺未识别')}</span></div></div></td>
    <td class="num">${product.price == null ? '—' : `¥${Number(product.price).toFixed(2)}`}</td><td class="num">${product.total_sales == null ? '—' : Number(product.total_sales).toLocaleString('zh-CN')}</td><td>${esc(product.last_collected_at)}</td><td><span class="status">● 正常</span></td></tr>`).join('')}</tbody></table>`;
}

window.addEventListener('xhs-product-collected', loadProducts);
loadProducts().catch(() => document.querySelector('#notice').textContent = '本地服务暂不可用，请查看启动状态。');

