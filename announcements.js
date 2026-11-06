/* Shared public-announcement panel for provincial and headquarters feeds. */
(function () {
  'use strict';
  const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function safeURL(value) {
    try { const url = new URL(value, location.href); return ['https:', 'http:'].includes(url.protocol) ? url.href : '#'; }
    catch (_) { return '#'; }
  }
  function mount(config) {
    const box = document.getElementById('announceBox'), sub = document.getElementById('announceSub');
    const select = document.getElementById('announceScope'), title = document.getElementById('announceTitle');
    const source = document.getElementById('announceSource'), retry = document.getElementById('announceRetry');
    if (!box || box.dataset.mounted) return;
    box.dataset.mounted = 'true';
    const cache = new Map(); let revision = 0;
    const preferred = config.feeds.find(feed => feed.hash === location.hash);
    select.value = preferred ? preferred.scope : config.feeds[0].scope;
    async function render(force) {
      const feed = config.feeds.find(feed => feed.scope === select.value) || config.feeds[0];
      const request = ++revision;
      title.textContent = feed.title; source.textContent = feed.source;
      sub.textContent = '每天 00:00、12:00 自动检查 · 按发布日期展示最新 15 条';
      box.innerHTML = '<div class="loading">加载公告…</div>';
      retry.disabled = true;
      try {
        let data = force ? null : cache.get(feed.path);
        if (!data) {
          const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 25000);
          try {
            const response = await fetch(feed.path, {cache:'no-store', signal:controller.signal});
            if (!response.ok) throw Error('HTTP ' + response.status);
            data = await response.json();
          } finally { clearTimeout(timer); }
          if (!data || data.operator !== config.operator || data.province !== feed.scope || !Array.isArray(data.items)) throw Error('公告范围不匹配');
          cache.set(feed.path, data);
        }
        if (request !== revision) return;
        sub.textContent = '数据更新时间：' + (data.updated || '未提供') + ' · ' + data.items.length + ' 条公告' + (data.status === 'failed' ? ' · 本轮获取失败，显示上次成功数据' : ' · 每天 00:00、12:00 自动检查');
        if (!data.items.length) {
          if (data.status === 'failed') throw Error('公告采集暂不可用');
          box.innerHTML = '<div class="empty">暂无公告数据</div>'; return;
        }
        box.innerHTML = data.items.map((item, i) => {
          const attachments = (item.attachments || []).map(a => '<a class="ann-att-btn" href="' + escape(safeURL(a.url)) + '" target="_blank" rel="noopener noreferrer">附件 · ' + escape(a.name || '下载') + '</a>').join('');
          return '<article class="ann-item"><button class="ann-head" type="button" aria-expanded="false" aria-controls="announcement-body-' + i + '"><span class="ann-date">' + escape(item.date || '') + '</span><span class="ann-title">' + escape(item.title || '') + '</span><span class="ann-arrow" aria-hidden="true">⌄</span></button>' +
            (item.summary ? '<p class="ann-summary">' + escape(item.summary) + '</p>' : '') +
            '<div class="ann-body" id="announcement-body-' + i + '">' + (item.content ? '<div class="ann-content">' + item.content + '</div>' : '<p>正文暂未取得，请查看官网原文。</p>') +
            (attachments ? '<div class="ann-att">' + attachments + '</div>' : '') + '<p class="ann-more"><a href="' + escape(safeURL(item.page_url)) + '" target="_blank" rel="noopener noreferrer">查看官网原文 ↗</a></p></div></article>';
        }).join('');
        box.querySelectorAll('.ann-head').forEach(button => button.addEventListener('click', () => {
          const open = button.closest('.ann-item').classList.toggle('open'); button.setAttribute('aria-expanded', String(open));
        }));
      } catch (_) {
        if (request !== revision) return;
        sub.textContent = '公告暂时无法读取，请重试或访问官方公告栏目。';
        box.innerHTML = '<div class="empty">' + escape(feed.title) + '加载失败。<a href="' + escape(safeURL(feed.official)) + '" target="_blank" rel="noopener noreferrer">查看官方公告 ↗</a></div>';
      } finally { if (request === revision) retry.disabled = false; }
    }
    select.addEventListener('change', () => {
      const feed = config.feeds.find(feed => feed.scope === select.value);
      if (feed) { try { history.replaceState(null, '', feed.hash); } catch (_) {} }
      render(false);
    });
    retry.addEventListener('click', () => render(true));
    window.addEventListener('hashchange', () => {
      const feed = config.feeds.find(feed => feed.hash === location.hash);
      if (feed && select.value !== feed.scope) { select.value = feed.scope; render(false); }
    });
    render(false);
  }
  window.AnnouncementPanel = {mount};
})();
