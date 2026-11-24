const root = document.querySelector('#catalog');
const filterKeys = ['category', 'patch', 'job', 'slot', 'equipMin', 'equipMax', 'itemMin', 'itemMax'];
const crafting = '刻木匠 锻铁匠 铸甲匠 雕金匠 制革匠 裁衣匠 炼金术士 烹调师'.split(' ');
const gathering = ['采矿工', '园艺工', '捕鱼人'];
const fashionCategories = new Set([34,35,36,37,38,40,41,42,43]);
const fashionSlots = new Set(['头部','身体','手部','腿部','脚部','耳部','颈部','腕部','手指']);
const emptyFilters = () => Object.fromEntries(filterKeys.map(k => [k, '']));

function readState() {
  const params = new URLSearchParams(location.search);
  const staticPage = location.pathname.match(/\/page\/(\d+)\.html$/)?.[1] || 1;
  const parsed = Number(params.get('page') || staticPage);
  return {
    query: (params.get('q') || '').trim(),
    view: ['gear', 'material', 'unlock'].includes(params.get('view')) ? params.get('view') : '',
    fashion: params.get('view') === 'gear' && params.get('fashion') === '1',
    ...Object.fromEntries(filterKeys.map(k => [k, params.get(k) || ''])),
    page: Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 1,
  };
}

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text != null) node.textContent = text;
  if (className) node.className = className;
  return node;
}

function itemCard({id, name, kind, patch, levels, icon, link}) {
  const card = element('li');
  const body = element('span', null, 'card-body');
  body.append(element('small', [kind, patch].filter(Boolean).join(' · '), 'card-kind'),
    element('small', `#${id}`, 'card-id'), element('strong', name));
  if (levels) body.append(element('small', levels));
  link.append(icon, body);
  card.append(link);
  return card;
}

function itemRow({id, name, kind, icon, link}) {
  const row = element('tr');
  const nameCell = element('td');
  link.textContent = name;
  nameCell.append(icon, document.createTextNode(' '), link);
  row.append(element('td', id, 'numeric'), nameCell, element('td', kind, 'numeric'));
  return row;
}

async function start() {
  const pageRoot = document.querySelector('#catalog-page') || root;
  const status = root.querySelector('#catalog-status');
  const table = root.querySelector('table');
  const rows = table?.tBodies[0];
  if (!status || !rows) return;
  const pageSize = Number(pageRoot.dataset.pageSize);
  const staticPagination = root.querySelector('.pagination');
  // Relative asset and detail paths belong to the document that was loaded,
  // even after history.pushState changes a home or deep pagination URL.
  const documentUrl = location.href;

  // The static page works without JavaScript. Build the search controls and
  // dynamic pager only when the index can be loaded, matching the old markup.
  const form = document.createElement('section');
  form.className = 'search-form';
  form.hidden = true;
  status.before(form);
  status.setAttribute('role', 'status');

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
    const [index, facets] = await Promise.all(['index.json', 'filters.json'].map(async file => {
      const response = await fetch(pageRoot.dataset.indexUrl.replace(/index\.json$/, file));
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }));
    let state = readState();
    let presets = history.state?.gearPresets || {};
    let lastGear = presets.last || 'normal';
    function rememberGear() {
      if (state.view !== 'gear') return;
      lastGear = state.fashion ? 'fashion' : 'normal';
      presets = {...presets, last:lastGear, [lastGear]:{...state}};
    }
    function restoreGear(mode) {
      return {...emptyFilters(), query:'', page:1, ...presets[mode], view:'gear', fashion:mode === 'fashion'};
    }
    const categoryOf = id => facets.categories[id] || [`类型 #${id}`, '其他'];
    const unlocks = new Map();
    const unlockKinds = Object.keys(facets.unlocks || {});
    for (const kind of unlockKinds) {
      for (const id of facets.unlocks[kind]) unlocks.set(id, kind);
    }
    const inView = (id, view) => {
      const [, group] = categoryOf(id);
      return !view || (view === 'gear' ? group.startsWith('装备') : group === '素材');
    };
    const tabs = document.createElement('div');
    tabs.className = 'view-tabs';
    const buttons = [['', '全部物品'], ['gear', '装备'], ['material', '素材'],
      ...(unlockKinds.length ? [['unlock', '解锁']] : [])].map(([view, title]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = title;
      button.addEventListener('click', () => {
        if (state.view === view) return;
        rememberGear();
        const query = state.query;
        state = view === 'gear' && presets[lastGear] ? restoreGear(lastGear)
          : {query, view, fashion:false, ...emptyFilters(), page:1};
        navigate(state.query, state.page);
      });
      tabs.append(button);
      return [view, button];
    });
    form.append(tabs);
    const unlockCloud = document.createElement('fieldset');
    unlockCloud.className = 'unlock-cloud';
    const legend = document.createElement('legend');
    legend.textContent = '解锁分类';
    const tags = document.createElement('div');
    unlockCloud.append(legend, tags);
    form.append(unlockCloud);
    const fashionSwitch = document.createElement('button');
    fashionSwitch.type = 'button';
    fashionSwitch.className = 'fashion-switch';
    fashionSwitch.setAttribute('role','switch');
    fashionSwitch.textContent = '时装';
    fashionSwitch.addEventListener('click', () => {
      rememberGear();
      state = restoreGear(state.fashion ? 'normal' : 'fashion');
      navigate(state.query, state.page);
    });
    const hint = document.createElement('p');
    hint.className = 'fashion-hint';
    hint.textContent = '时装预设：仅看装备等级 1 的防具和饰品，包含部分新手装备。';
    const filters = document.createElement('div');
    filters.className = 'filters';
    form.append(filters);
    const panel = document.createElement('details');
    panel.className = 'gear-panel';
    panel.open = !window.matchMedia?.('(max-width: 48rem)').matches;
    const summary = document.createElement('summary');
    panel.append(summary);
    panel.append(fashionSwitch, hint);
    form.append(panel);
    const grid = document.createElement('ul');
    grid.className = 'item-grid';
    status.after(grid);
    let layout = 'cards';
    const toolbar = element('div', null, 'results-toolbar');
    const switcher = element('div', null, 'layout-switch');
    switcher.setAttribute('role', 'group');
    switcher.setAttribute('aria-label', '结果显示方式');
    const layoutButtons = [
      ['cards', '卡片视图', 'M3 3h5v5H3z M12 3h5v5h-5z M3 12h5v5H3z M12 12h5v5h-5z'],
      ['list', '列表视图', 'M3 4h1m4 0h9 M3 10h1m4 0h9 M3 16h1m4 0h9'],
    ].map(([mode, label, path]) => {
      const button = element('button');
      button.type = 'button';
      button.title = label;
      button.setAttribute('aria-label', label);
      button.innerHTML = `<svg aria-hidden="true" width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"/></svg>`;
      button.addEventListener('click', () => {
        if (layout === mode) return;
        layout = mode;
        render();
      });
      switcher.append(button);
      return [mode, button];
    });
    status.before(toolbar);
    toolbar.append(status, switcher);
    function band(title) {
      const row = document.createElement('div');
      row.className = 'gear-band';
      row.setAttribute('role','group');
      row.setAttribute('aria-label',title);
      const caption = document.createElement('span');
      caption.textContent = title;
      const body = document.createElement('div');
      row.append(caption, body);
      panel.append(row);
      return {body, row};
    }
    const chipStates = [];
    function chip(parent, key, value, text) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = text;
      parent.append(button);
      chipStates.push({button,key,value});
      button.addEventListener('click', () => {
        if (key === 'slot' && value) {
          const set = new Set(state.slot.split(',').filter(Boolean));
          if (!set.delete(value)) set.add(value);
          state.slot = [...set].join(',');
        } else state[key] = value;
        navigate(state.query, 1);
      });
    }
    chip(tags, 'category', '', '全部解锁');
    for (const kind of unlockKinds) chip(tags, 'category', kind, kind);
    const jobs = band('职业');
    const names = [...new Set(Object.values(facets.jobs).flat())];
    chip(jobs.body, 'job', '', '全部职业');
    const jobGroups = {
      战斗精英:names.filter(n => !crafting.includes(n) && !gathering.includes(n)),
      能工巧匠:names.filter(n => crafting.includes(n)), 大地使者:names.filter(n => gathering.includes(n)),
    };
    for (const [group, members] of Object.entries(jobGroups)) {
      if (!members.length) continue;
      const line = document.createElement('div');
      line.className = 'job-line';
      chip(line, 'job', group, group);
      const choices = document.createElement('div');
      for (const name of members) chip(choices, 'job', name, name);
      line.append(choices);
      jobs.body.append(line);
    }
    const slots = band('部位');
    chip(slots.body, 'slot', '', '全部部位');
    for (const slot of new Set(Object.values(facets.slots).flat())) chip(slots.body, 'slot', slot, slot);
    const ranges = band('范围');
    jobs.row.hidden = !names.length;
    slots.row.hidden = !Object.keys(facets.slots).length;
    const fields = {};
    const rangeGroups = {};
    for (const [key, name] of [['equip','装备等级'], ['item','物品品级']]) {
      const group = document.createElement('fieldset');
      const legend = document.createElement('legend');
      legend.textContent = name;
      group.append(legend);
      ranges.body.append(group);
      rangeGroups[key] = group;
    }
    for (const [key, title] of Object.entries({category:'物品类型', patch:'首次收录版本', equipMin:'最低装备等级', equipMax:'最高装备等级', itemMin:'最低物品品级', itemMax:'最高物品品级'})) {
      const wrap = document.createElement('label');
      const numeric = key !== 'category' && key !== 'patch';
      if (!numeric) wrap.textContent = title;
      const field = document.createElement(numeric ? 'input' : 'select');
      if (numeric) {
        field.type = 'number';
        field.min = '0';
        field.placeholder = key.endsWith('Min') ? '最低' : '最高';
        field.setAttribute('aria-label',title);
      }
      field.name = key;
      wrap.append(field);
      const target = numeric ? rangeGroups[key.slice(0,-3)] : filters;
      if (key.endsWith('Max')) {
        const dash = document.createElement('span');
        dash.textContent = '–';
        dash.setAttribute('aria-hidden','true');
        target.append(dash);
      }
      target.append(wrap);
      fields[key] = {field, wrap};
      field.addEventListener('change', () => {
        if (numeric && !field.validity.valid) return;
        state[key] = field.value;
        navigate(state.query, 1);
      });
    }
    const reset = document.createElement('button');
    reset.type = 'button';
    reset.textContent = '清除筛选';
    reset.addEventListener('click', () => {
      for (const key of filterKeys) state[key] = '';
      navigate('', 1);
    });
    filters.append(reset);
    function options(field, entries) {
      const fragment = document.createDocumentFragment();
      const groups = new Map();
      for (const [value, name, group] of [['', '不限'], ...entries]) {
        if (group && !groups.has(group)) {
          const section = document.createElement('optgroup');
          section.label = group;
          groups.set(group, section);
          fragment.append(section);
        }
        const option = document.createElement('option');
        option.value = value;
        option.textContent = name;
        (groups.get(group) || fragment).append(option);
      }
      field.replaceChildren(fragment);
    }
    const categories = [...new Set(index.map(r => r[2]))];
    options(fields.patch.field, [...new Set(index.map(r => r[8]).filter(Boolean))]
      .sort().reverse().map(p => [p,p,/^\d\./.test(p) ? `${p[0]}.x` : '其他记录']));
    let lastView;

    function render() {
      const query = state.query.toLocaleLowerCase();
      const gear = state.view === 'gear';
      const unlock = state.view === 'unlock';
      unlockCloud.hidden = !unlock;
      const fashion = gear && state.fashion;
      if (fashion) {
        state.equipMin = state.equipMax = '1';
        if (!fashionCategories.has(Number(state.category))) state.category = '';
        state.slot = state.slot.split(',').filter(s => fashionSlots.has(s)).join(',');
      }
      fashionSwitch.hidden = !gear;
      fashionSwitch.setAttribute('aria-checked',String(fashion));
      hint.hidden = !fashion;
      rangeGroups.item.hidden = !Object.keys(facets.jobs).length;
      panel.hidden = !gear;
      const cards = layout === 'cards';
      grid.hidden = !cards;
      table.hidden = cards;
      for (const [mode, button] of layoutButtons) button.setAttribute('aria-pressed', String(mode === layout));
      const selectedSlots = state.slot.split(',').filter(Boolean);
      const editable = filterKeys.filter(key => !(fashion && key.startsWith('equip')));
      const active = editable.filter(key => key !== 'category' && state[key]).length;
      summary.textContent = active ? `装备筛选 · 已选 ${active} 项条件` : '装备筛选';
      for (const {key, value, button} of chipStates) {
        button.hidden = fashion && key === 'slot' && !!value && !fashionSlots.has(value);
        const selected = key === 'slot' && value ? selectedSlots.includes(value) : state[key] === value;
        button.setAttribute('aria-pressed', String(selected));
      }
      const viewKey = fashion ? 'fashion' : state.view;
      if (!unlock && lastView !== viewKey) {
        options(fields.category.field, categories.filter(id => inView(id, state.view) && (!fashion || fashionCategories.has(id)))
          .sort((a,b) => a-b).map(id => [id, ...categoryOf(id)]));
        lastView = viewKey;
      }
      for (const [view, button] of buttons) button.setAttribute('aria-pressed', String(view === state.view));
      for (const [key, {wrap, field}] of Object.entries(fields)) {
        wrap.hidden = (unlock && key === 'category') || (key.startsWith('item') && !Object.keys(facets.jobs).length);
        field.value = state[key];
        field.disabled = fashion && key.startsWith('equip');
      }
      reset.hidden = !state.query && !editable.some(k => state[k]);
      const results = index.filter(([id, name, cat, , level, ilvl, slot, job, patch]) =>
        (!state.patch || state.patch === patch) &&
        (unlock ? unlocks.has(id) && (!state.category || unlocks.get(id) === state.category)
          : inView(cat, state.view) && (!state.category || String(cat) === state.category))
        && (!fashion || fashionCategories.has(cat))
        && (!gear || ((!state.equipMin || level >= Number(state.equipMin))
          && (!state.equipMax || level <= Number(state.equipMax))
          && (!state.itemMin || ilvl >= Number(state.itemMin))
          && (!state.itemMax || ilvl <= Number(state.itemMax))
          && (!selectedSlots.length || facets.slots[slot]?.some(s => selectedSlots.includes(s)))
          && (!state.job || facets.jobs[job]?.some(j => (jobGroups[state.job] || [state.job]).includes(j)))))
        && (!query || String(id).includes(query) || name.toLocaleLowerCase().includes(query)));
      const pages = Math.max(1, Math.ceil(results.length / pageSize));
      state.page = Math.min(state.page, pages);
      const fragment = document.createDocumentFragment();
      for (const [id, name, category, iconUrl, level, ilvl,,,patch] of results.slice((state.page - 1) * pageSize, state.page * pageSize)) {
        const icon = document.createElement('img');
        icon.className = 'item-icon';
        icon.src = new URL(`${pageRoot.dataset.assetRoot}${iconUrl.slice(1)}`, documentUrl).href;
        icon.alt = '';
        icon.width = 32;
        icon.height = 32;
        icon.loading = 'lazy';
        icon.decoding = 'async';
        const link = document.createElement('a');
        const target = new URL(`${pageRoot.dataset.detailBase}${id}.html`, documentUrl);
        link.href = target.href;
        const kind = unlock ? unlocks.get(id) : categoryOf(category)[0];
        const levels = inView(category, 'gear') ? `装备等级 ${level}${ilvl == null ? '' : ` · 品级 ${ilvl}`}` : '';
        fragment.append((cards ? itemCard : itemRow)({id, name, kind, patch, levels, icon, link}));
      }
      (cards ? grid : rows).replaceChildren(fragment);
      status.textContent = results.length
        ? `共 ${results.length.toLocaleString('zh-CN')} 件物品${state.query ? `，搜索“${state.query}”` : ''}`
        : '没有符合条件的物品。可以清除筛选，或换一个关键词。';
      pageStatus.textContent = `第 ${state.page} / ${pages} 页`;
      previous.disabled = state.page === 1;
      next.disabled = state.page === pages;
    }

    function navigate(query, page) {
      state = { ...state, query: query.trim(), page };
      render();
      const url = new URL(pageRoot.dataset.catalogUrl, documentUrl);
      url.search = '';
      if (state.query) url.searchParams.set('q', state.query);
      if (state.fashion) url.searchParams.set('fashion','1');
      for (const key of ['view', ...filterKeys]) if (state[key]) url.searchParams.set(key, state[key]);
      if (state.page > 1) url.searchParams.set('page', state.page);
      rememberGear();
      history.pushState({gearPresets:presets}, '', url);
    }

    previous.addEventListener('click', () => navigate(state.query, state.page - 1));
    next.addEventListener('click', () => navigate(state.query, state.page + 1));
    window.addEventListener('popstate', () => {
      presets = history.state?.gearPresets || {};
      lastGear = presets.last || 'normal';
      state = readState();
      render();
    });

    function activate() {
      if (staticPagination) staticPagination.hidden = true;
      dynamic.hidden = false;
    }

    form.hidden = false;
    activate();
    render();
  } catch (error) {
    status.textContent = `搜索索引加载失败（${error.message}）。仍可使用下方静态目录和翻页链接。`;
  }
}

if (root) start();
