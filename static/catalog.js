const root = document.querySelector('#catalog');

function readState() {
  const params = new URLSearchParams(location.search);
  const staticPage = location.pathname.match(/\/page\/(\d+)\.html$/)?.[1] || 1;
  const parsed = Number(params.get('page') || staticPage);
  return {
    query: (params.get('q') || '').trim(),
    page: Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 1,
  };
}

async function start() {
  const pageRoot = document.querySelector('#catalog-page') || root;
  const status = root.querySelector('#catalog-status');
  const table = root.querySelector('table');
  const rows = table?.tBodies[0];
  if (!status || !rows) return;
  const pageSize = Number(pageRoot.dataset.pageSize);
  const staticPagination = root.querySelector('.pagination');

  // The static page works without JavaScript. Build the search controls and
  // dynamic pager only when the index can be loaded, matching the old markup.
  const form = document.createElement('form');
  form.id = 'search-form';
  form.className = 'search-form';
  form.setAttribute('role', 'search');
  form.hidden = true;
  const label = document.createElement('label');
  label.htmlFor = 'query';
  label.textContent = '搜索物品';
  const controls = document.createElement('div');
  controls.className = 'search-controls';
  const input = document.createElement('input');
  input.id = 'query';
  input.type = 'search';
  input.name = 'q';
  input.placeholder = '输入名称或物品 ID';
  input.autocomplete = 'off';
  const submit = document.createElement('button');
  submit.type = 'submit';
  submit.textContent = '搜索';
  controls.append(input, submit);
  form.append(label, controls);
  status.before(form);

  const dynamic = document.createElement('div');
  dynamic.id = 'pagination';
  dynamic.className = 'pagination';
  dynamic.hidden = true;
  const previous = document.createElement('button');
  previous.id = 'previous';
  previous.type = 'button';
  previous.textContent = '上一页';
  const pageStatus = document.createElement('span');
  pageStatus.id = 'page-status';
  const next = document.createElement('button');
  next.id = 'next';
  next.type = 'button';
  next.textContent = '下一页';
  dynamic.append(previous, pageStatus, next);
  if (staticPagination) staticPagination.after(dynamic);
  else root.append(dynamic);

  status.textContent = '正在加载物品搜索索引…';
  try {
    const response = await fetch(pageRoot.dataset.indexUrl);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const index = await response.json();
    let state = readState();

    function render() {
      const query = state.query.toLocaleLowerCase();
      const results = index.filter(([id, name]) => !query
        || String(id).includes(query) || name.toLocaleLowerCase().includes(query));
      const pages = Math.max(1, Math.ceil(results.length / pageSize));
      state.page = Math.min(state.page, pages);
      input.value = state.query;
      const fragment = document.createDocumentFragment();
      for (const [id, name, category, iconUrl] of results.slice((state.page - 1) * pageSize, state.page * pageSize)) {
        const row = document.createElement('tr');
        const idCell = document.createElement('td');
        idCell.className = 'numeric';
        idCell.textContent = id;
        const nameCell = document.createElement('td');
        const icon = document.createElement('img');
        icon.className = 'item-icon';
        icon.src = new URL(`${pageRoot.dataset.assetRoot}${iconUrl.slice(1)}`, location.href).href;
        icon.alt = '';
        icon.width = 32;
        icon.height = 32;
        icon.loading = 'lazy';
        icon.decoding = 'async';
        const link = document.createElement('a');
        const target = new URL(`${pageRoot.dataset.detailBase}${id}.html`, location.href);
        link.href = target.href;
        link.textContent = name;
        nameCell.append(icon, document.createTextNode(' '), link);
        const categoryCell = document.createElement('td');
        categoryCell.className = 'numeric';
        categoryCell.textContent = category;
        row.append(idCell, nameCell, categoryCell);
        fragment.append(row);
      }
      rows.replaceChildren(fragment);
      status.textContent = results.length
        ? `共 ${results.length.toLocaleString('zh-CN')} 件物品${state.query ? `，搜索“${state.query}”` : ''}`
        : '没有匹配的物品，请换一个名称或 ID。';
      pageStatus.textContent = `第 ${state.page} / ${pages} 页`;
      previous.disabled = state.page === 1;
      next.disabled = state.page === pages;
    }

    function navigate(query, page) {
      state = { query: query.trim(), page };
      render();
      const url = new URL(pageRoot.dataset.catalogUrl, location.href);
      url.search = '';
      if (state.query) url.searchParams.set('q', state.query);
      if (state.page > 1) url.searchParams.set('page', state.page);
      history.pushState(null, '', url);
    }

    form.addEventListener('submit', event => {
      event.preventDefault();
      activate();
      navigate(input.value, 1);
    });
    previous.addEventListener('click', () => navigate(state.query, state.page - 1));
    next.addEventListener('click', () => navigate(state.query, state.page + 1));
    window.addEventListener('popstate', () => { state = readState(); render(); });

    function activate() {
      if (staticPagination) staticPagination.hidden = true;
      dynamic.hidden = false;
    }

    form.hidden = false;
    // Preserve the build-time page until a search is submitted. Static paging
    // and every item detail work without JavaScript or a successful index fetch.
    if (location.search) { activate(); render(); }
    else status.textContent = '可按名称或物品 ID 搜索，也可通过下方链接浏览完整目录。';
  } catch (error) {
    status.textContent = `搜索索引加载失败（${error.message}）。仍可使用下方静态目录和翻页链接。`;
  }
}

if (root) start();
