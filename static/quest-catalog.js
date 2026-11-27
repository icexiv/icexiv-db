// Quest catalog: static pages remain the no-JS fallback; this module filters,
// groups and paginates the full index in the browser.
const root = document.querySelector('#quest-catalog');
const pageRoot = document.querySelector('#quest-catalog-page');
const status = document.querySelector('#quest-catalog-status');

if (root && pageRoot && status) start();

function el(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function readState() {
  const params = new URLSearchParams(location.search);
  const page = Number(params.get('page') || 1);
  return {
    query: params.get('q') || '',
    view: params.get('view') || '',
    expansion: params.get('exp') || '',
    category: params.get('cat') || '',
    place: params.get('place') || '',
    levelMin: params.get('lvlMin') || '',
    levelMax: params.get('lvlMax') || '',
    sort: ['story', 'level', '-level', 'name', 'id'].includes(params.get('sort')) ? params.get('sort') : 'story',
    page: Number.isSafeInteger(page) && page > 0 ? page : 1,
  };
}

function writeState(state) {
  const url = new URL(location.href);
  const set = (key, value) => value ? url.searchParams.set(key, value) : url.searchParams.delete(key);
  set('q', state.query.trim());
  set('view', state.view);
  set('exp', state.expansion);
  set('cat', state.category);
  set('place', state.place);
  set('lvlMin', state.levelMin);
  set('lvlMax', state.levelMax);
  if (state.sort !== 'story') url.searchParams.set('sort', state.sort);
  else url.searchParams.delete('sort');
  if (state.page > 1) url.searchParams.set('page', String(state.page));
  else url.searchParams.delete('page');
  return url;
}

function start() {
  const staticTable = root.querySelector('.table-scroll');
  const staticPager = root.querySelector('.pagination');
  const pageSize = Number(pageRoot.dataset.pageSize) || 100;
  const documentUrl = location.href;
  const indexUrl = pageRoot.dataset.indexUrl;
  const filtersUrl = pageRoot.dataset.filtersUrl;
  const detailBase = new URL(pageRoot.dataset.detailBase || '', documentUrl);
  const catalogUrl = pageRoot.dataset.catalogUrl || 'index.html';

  status.textContent = '正在加载任务索引…';
  Promise.all([indexUrl, filtersUrl].map(async url => {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })).then(([index, filters]) => {
    const state = readState();
    const collator = new Intl.Collator('zh-CN', {numeric: true});
    const sectionOrder = new Map(filters.sections.map(([key], i) => [key, i]));
    const sectionLabel = new Map(filters.sections.map(([key, label]) => [key, label]));
    const categories = filters.categories;
    const places = filters.places;
    const expansions = filters.expansions;
    const detailHref = id => new URL(`${id}.html`, detailBase).href;

    const form = el('section', null, 'search-form');
    status.before(form);

    const tabs = el('div', null, 'view-tabs');
    const tabButtons = [['', '全部任务'], ...filters.sections.map(([key, label]) => [key, label])].map(([key, label]) => {
      const button = el('button', label);
      button.type = 'button';
      button.addEventListener('click', () => {
        state.view = key;
        state.category = '';
        state.page = 1;
        navigate();
      });
      tabs.append(button);
      return [key, button];
    });
    form.append(tabs);

    const filtersBox = el('section', null, 'filter-box');
    const heading = el('div', null, 'filter-heading');
    heading.append(el('h2', '筛选条件'));
    const grid = el('div', null, 'filters quest-filters');
    filtersBox.append(heading, grid);
    form.append(filtersBox);

    const queryLabel = el('label', '名称或 ID', 'name-field');
    const queryInput = el('input');
    queryInput.type = 'search';
    queryInput.placeholder = '筛选当前结果';
    queryInput.value = state.query;
    queryLabel.append(queryInput);
    grid.append(queryLabel);
    queryInput.addEventListener('input', () => {
      if (queryInput.isComposing) return;
      state.query = queryInput.value;
      state.page = 1;
      navigate();
    });
    queryInput.addEventListener('compositionend', () => {
      state.query = queryInput.value;
      state.page = 1;
      navigate();
    });

    const select = (labelText, options, value, onChange) => {
      const label = el('label', labelText);
      const control = el('select');
      for (const [key, text] of options) {
        const option = el('option', text);
        option.value = key;
        control.append(option);
      }
      control.value = value;
      control.addEventListener('change', () => onChange(control.value));
      label.append(control);
      grid.append(label);
      return control;
    };

    select('资料片', [['', '全部资料片'], ...Object.entries(expansions)], state.expansion, value => {
      state.expansion = value;
      state.page = 1;
      navigate();
    });

    let categorySelect;
    const rebuildCategories = () => {
      const options = [['', '全部章节']];
      for (const [id, [name, section]] of Object.entries(categories)) {
        if (state.view && section !== state.view) continue;
        options.push([id, name]);
      }
      const current = categorySelect.value;
      categorySelect.replaceChildren(...options.map(([key, text]) => {
        const option = el('option', text);
        option.value = key;
        return option;
      }));
      categorySelect.value = options.some(([key]) => key === current) ? current : '';
    };
    categorySelect = select('章节', [['', '全部章节']], state.category, value => {
      state.category = value;
      state.page = 1;
      navigate();
    });

    const levelWrap = el('label', '等级');
    const levelRange = el('span', null, 'quest-level-range');
    const minInput = el('input');
    minInput.type = 'number';
    minInput.min = String(filters.levels[0]);
    minInput.max = String(filters.levels[1]);
    minInput.value = state.levelMin;
    minInput.placeholder = String(filters.levels[0]);
    const maxInput = el('input');
    maxInput.type = 'number';
    maxInput.min = String(filters.levels[0]);
    maxInput.max = String(filters.levels[1]);
    maxInput.value = state.levelMax;
    maxInput.placeholder = String(filters.levels[1]);
    const applyLevels = () => {
      state.levelMin = minInput.value;
      state.levelMax = maxInput.value;
      state.page = 1;
      navigate();
    };
    minInput.addEventListener('change', applyLevels);
    maxInput.addEventListener('change', applyLevels);
    levelRange.append(minInput, el('span', '～'), maxInput);
    levelWrap.append(levelRange);
    grid.append(levelWrap);

    select('地区', [['', '全部地区'], ...Object.entries(places).sort((a, b) => collator.compare(a[1], b[1]))],
      state.place, value => {
        state.place = value;
        state.page = 1;
        navigate();
      });

    const toolbar = el('div', null, 'results-toolbar');
    const sortLabel = el('label', '排序 ');
    const sortSelect = el('select');
    for (const [key, text] of [['story', '故事顺序'], ['level', '等级 · 从低到高'], ['-level', '等级 · 从高到低'], ['name', '名称'], ['id', '编号']]) {
      const option = el('option', text);
      option.value = key;
      sortSelect.append(option);
    }
    sortSelect.value = state.sort;
    sortSelect.addEventListener('change', () => {
      state.sort = sortSelect.value;
      state.page = 1;
      navigate();
    });
    sortLabel.append(sortSelect);
    status.before(toolbar);

    const results = el('div', null, 'quest-results');
    const pager = el('nav', null, 'pagination');
    pager.setAttribute('aria-label', '任务目录分页');
    status.after(results);
    results.after(pager);
    if (staticTable) staticTable.hidden = true;
    if (staticPager) staticPager.hidden = true;
    toolbar.append(sortLabel, status);

    function navigate() {
      const url = writeState(state);
      if (url.href !== location.href) history.pushState(history.state, '', url);
      render();
    }

    function filteredRows() {
      const query = state.query.trim().toLowerCase();
      const min = state.levelMin ? Number(state.levelMin) : -Infinity;
      const max = state.levelMax ? Number(state.levelMax) : Infinity;
      const rows = index.filter(row => {
        const [id, name, section, category, , level, expansion, place] = row;
        if (state.view && section !== state.view) return false;
        if (state.expansion && String(expansion) !== state.expansion) return false;
        if (state.category && String(category) !== state.category) return false;
        if (state.place && String(place) !== state.place) return false;
        if (level < min || level > max) return false;
        if (query && !name.toLowerCase().includes(query) && !String(id).includes(query)) return false;
        return true;
      });
      const categoryName = id => categories[String(id)]?.[0] || `未分类 #${id}`;
      const byStory = (a, b) =>
        (sectionOrder.get(a[2]) ?? 99) - (sectionOrder.get(b[2]) ?? 99)
        || Number(a[3]) - Number(b[3])
        || (a[8] || 1e9) - (b[8] || 1e9)
        || a[0] - b[0];
      rows.sort((a, b) => {
        if (state.sort === 'level') return a[5] - b[5] || collator.compare(a[1], b[1]);
        if (state.sort === '-level') return b[5] - a[5] || collator.compare(a[1], b[1]);
        if (state.sort === 'name') return collator.compare(a[1], b[1]);
        if (state.sort === 'id') return a[0] - b[0];
        return byStory(a, b);
      });
      return rows;
    }

    function render() {
      rebuildCategories();
      for (const [key, button] of tabButtons) button.setAttribute('aria-pressed', key === state.view ? 'true' : 'false');
      sortSelect.value = state.sort;
      const rows = filteredRows();
      const stepById = new Map();
      const counters = new Map();
      for (const row of rows) {
        const key = row[3];
        const step = (counters.get(key) || 0) + 1;
        counters.set(key, step);
        stepById.set(row[0], step);
      }
      const pageCount = Math.max(1, Math.ceil(rows.length / pageSize));
      state.page = Math.min(state.page, pageCount);
      const start = (state.page - 1) * pageSize;
      const pageRows = rows.slice(start, start + pageSize);

      const groups = new Map();
      for (const row of pageRows) {
        const key = row[3];
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(row);
      }
      const fragment = document.createDocumentFragment();
      for (const [category, members] of groups) {
        const section = el('section', null, 'quest-group');
        const head = el('div', null, 'quest-group-head');
        head.append(el('h2', categories[String(category)]?.[0] || `未分类 #${category}`));
        head.append(el('small', `${categories[String(category)]?.[2] ?? members.length} 个任务`));
        const list = el('div', null, 'quest-rows');
        for (const row of members) {
          const [id, name, , , , level, , place, , , gil, exp, itemCount] = row;
          const link = el('a', null, 'quest-row');
          link.href = detailHref(id);
          link.append(el('span', String(stepById.get(id) || '–'), 'quest-step'));
          link.append(el('span', String(level), 'quest-level'));
          link.append(el('span', name, 'quest-name'));
          link.append(el('span', places[String(place)] || '', 'quest-place'));
          const rewards = el('span', null, 'quest-rewards-mini');
          if (gil) rewards.append(el('span', `${gil} G`));
          if (exp) rewards.append(el('span', `EXP×${exp}`));
          if (itemCount) rewards.append(el('span', `${itemCount} 件道具`));
          link.append(rewards, el('span', '›', 'quest-arrow'));
          list.append(link);
        }
        section.append(head, list);
        fragment.append(section);
      }
      if (!pageRows.length) fragment.append(el('p', '没有匹配的任务。', 'notice'));
      results.replaceChildren(fragment);

      const pagerFragment = document.createDocumentFragment();
      const previous = el('button', '上一页');
      previous.type = 'button';
      previous.disabled = state.page <= 1;
      previous.addEventListener('click', () => { state.page--; navigate(); });
      pagerFragment.append(previous);
      const numbers = el('span', null, 'page-links');
      const visible = new Set([1, pageCount]);
      for (let n = Math.max(1, state.page - 2); n <= Math.min(pageCount, state.page + 2); n++) visible.add(n);
      let last = 0;
      for (const n of [...visible].sort((a, b) => a - b)) {
        if (n - last === 2) numbers.append(el('span', String(n - 1)));
        else if (n - last > 2) numbers.append(el('span', '…'));
        const button = el('button', String(n));
        button.type = 'button';
        if (n === state.page) button.setAttribute('aria-current', 'page');
        else button.addEventListener('click', () => { state.page = n; navigate(); });
        numbers.append(button);
        last = n;
      }
      const next = el('button', '下一页');
      next.type = 'button';
      next.disabled = state.page >= pageCount;
      next.addEventListener('click', () => { state.page++; navigate(); });
      pagerFragment.append(numbers, next);
      pager.replaceChildren(pagerFragment);

      status.textContent = `${rows.length} 个任务 · 第 ${state.page} / ${pageCount} 页`;
      const canonical = new URL(catalogUrl, documentUrl);
      canonical.search = writeState(state).search;
      if (state.page > 1) canonical.searchParams.set('page', String(state.page));
      else canonical.searchParams.delete('page');
    }

    window.addEventListener('popstate', () => {
      Object.assign(state, readState());
      queryInput.value = state.query;
      minInput.value = state.levelMin;
      maxInput.value = state.levelMax;
      render();
    });

    render();
  }).catch(error => {
    status.textContent = '任务索引加载失败，当前显示静态目录。';
    console.error(error);
  });
}
