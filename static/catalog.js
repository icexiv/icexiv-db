const root = document.querySelector('#catalog');
const status = document.querySelector('#catalog-status');
const rows = document.querySelector('#item-rows');
const form = document.querySelector('#search-form');
const input = document.querySelector('#query');
const previous = document.querySelector('#previous');
const next = document.querySelector('#next');
const pageStatus = document.querySelector('#page-status');
const pageSize = Number(root.dataset.pageSize);
const staticPagination = document.querySelector('[aria-label="静态物品目录分页"]');

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
  status.textContent = '正在加载物品搜索索引…';
  try {
    const response = await fetch(root.dataset.indexUrl);
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
      for (const [id, name, category] of results.slice((state.page - 1) * pageSize, state.page * pageSize)) {
        const row = document.createElement('tr');
        const idCell = document.createElement('td');
        idCell.className = 'numeric';
        idCell.textContent = id;
        const nameCell = document.createElement('td');
        const link = document.createElement('a');
        const target = new URL(`${root.dataset.detailBase}${id}.html`, location.href);
        link.href = target.href;
        link.textContent = name;
        nameCell.append(link);
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
      const url = new URL(root.dataset.catalogUrl, location.href);
      url.search = '';
      if (state.query) url.searchParams.set('q', state.query);
      if (state.page > 1) url.searchParams.set('page', state.page);
      history.pushState(null, '', url);
    }

    form.addEventListener('submit', event => {
      event.preventDefault();
      navigate(input.value, 1);
    });
    previous.addEventListener('click', () => navigate(state.query, state.page - 1));
    next.addEventListener('click', () => navigate(state.query, state.page + 1));
    window.addEventListener('popstate', () => { state = readState(); render(); });
    form.hidden = false;
    // Preserve the build-time page until a search is submitted. Static paging
    // and every item detail work without JavaScript or a successful index fetch.
    const activate = () => {
      staticPagination.hidden = true;
      document.querySelector('#pagination').hidden = false;
    };
    form.addEventListener('submit', activate);
    if (location.search) { activate(); render(); }
    else status.textContent = '可按名称或物品 ID 搜索，也可通过下方链接浏览完整目录。';
  } catch (error) {
    status.textContent = `搜索索引加载失败（${error.message}）。仍可使用下方静态目录和翻页链接。`;
  }
}

start();
