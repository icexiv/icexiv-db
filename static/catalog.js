import {element, itemCard} from './item-list.js';
import {iconUrl as resolveIconUrl, portraitUrl as resolvePortraitUrl} from './assets.js';

const root = document.querySelector('#catalog');
const flagLabels = {tradable:'可交易', craftable:'可合成'};
const filterKeys = ['area', 'category', 'patch', ...Object.keys(flagLabels), 'job', 'slot', 'equipMin', 'equipMax', 'itemMin', 'itemMax'];
const defaultSort = '-release';
const sortModes = {'-release':'版本 · 从新到旧', release:'版本 · 从旧到新', id:'编号 ↑', '-id':'编号 ↓', name:'名称 ↑', '-name':'名称 ↓'};
const crafting = '刻木匠 锻铁匠 铸甲匠 雕金匠 制革匠 裁衣匠 炼金术士 烹调师'.split(' ');
const gathering = ['采矿工', '园艺工', '捕鱼人'];
const fashionCategories = new Set([34,35,36,37,38,40,41,42,43]);
// 家具、庭具、桌台、桌上、壁挂、地毯
const furnishingCategories = new Set([57,76,77,78,79,80]);
const fashionSlots = new Set(['头部','身体','手部','腿部','脚部','耳部','颈部','腕部','手指']);
const emptyFilters = () => Object.fromEntries(filterKeys.map(k => [k, '']));

function readState() {
  const params = new URLSearchParams(location.search);
  const staticPage = location.pathname.match(/\/page\/(\d+)\.html$/)?.[1] || 1;
  const parsed = Number(params.get('page') || staticPage);
  return {
    query: params.get('q') ?? params.get('name') ?? '',
    view: ['gear', 'material', 'furnishing', 'unlock'].includes(params.get('view')) ? params.get('view') : '',
    fashion: params.get('view') === 'gear' && params.get('fashion') === '1',
    sort: Object.hasOwn(sortModes, params.get('sort')) ? params.get('sort') : defaultSort,
    bySet: params.has('sets') ? params.get('sets') === '1' : params.get('view') === 'gear',
    byPatch: params.get('versions') !== '0',
    ...Object.fromEntries(filterKeys.map(k => [k, params.get(k) || ''])),
    area: params.get('view') === 'furnishing' && ['indoor','garden'].includes(params.get('area')) ? params.get('area') : '',
    page: Number.isSafeInteger(parsed) && parsed > 0 ? parsed : 1,
  };
}

function pageNumbers(current, total) {
  const start = Math.max(1, Math.min(current - 2, total - 4));
  const visible = new Set([1,total]);
  for (let n = start; n <= total && n < start + 5; n++) visible.add(n);
  const numbers = [];
  let last = 0;
  for (const n of [...visible].sort((a,b) => a-b)) {
    if (n-last === 2) numbers.push(n-1);
    if (n-last > 2) numbers.push(null);
    numbers.push(n);
    last = n;
  }
  return numbers;
}

function itemRow({id, name, kind, icon, link}) {
  const row = element('tr');
  const nameCell = element('td');
  link.textContent = name;
  nameCell.append(icon, document.createTextNode(' '), link);
  row.append(element('td', id, 'numeric'), nameCell, element('td', kind, 'numeric'));
  return row;
}

// Preserve the selected sort order within each group and order groups by their
// first matching item. Group before paginating so a family stays contiguous.
function batches(items, groupPatch, groupSet, sets) {
  const split = (list, key) => {
    const groups = new Map();
    for (const row of list) {
      const k = key(row);
      if (!groups.has(k)) groups.set(k, []);
      groups.get(k).push(row);
    }
    return groups;
  };
  const result = [];
  for (const [patch, list] of groupPatch ? split(items, r => r[8] || '未归档') : [[null, items]]) {
    if (!groupSet) { result.push({patch, list}); continue; }
    const families = split(list, r => sets.get(r[0]));
    for (const [family, members] of families) {
      if (family) result.push({patch, family:family[0], list:members});
    }
    if (families.has(undefined)) result.push({patch, family:'未归入套装', list:families.get(undefined)});
  }
  return result;
}

function enablePortraitTips(container, previews, assetRoot) {
  const tip = element('aside', null, 'portrait-tip');
  tip.id = 'portrait-tip';
  tip.setAttribute('role', 'tooltip');
  tip.hidden = true;
  document.body.append(tip);
  let anchor, timer;
  function hide() {
    clearTimeout(timer);
    anchor?.removeAttribute('aria-describedby');
    anchor = null;
    tip.hidden = true;
  }
  function show(link) {
    if (!link || link === anchor) return;
    hide();
    anchor = link;
    timer = setTimeout(() => {
      if (!link.isConnected) return hide();
      const [image, summary] = previews[link.dataset.portrait];
      tip.replaceChildren(element('strong', '解锁内容'), element('span', summary));
      const src = resolvePortraitUrl(image, assetRoot);
      if (src) {
        const img = element('img');
        img.alt = '';
        img.src = src;
        tip.prepend(img);
      }
      link.setAttribute('aria-describedby', tip.id);
      tip.hidden = false;
      const box = link.getBoundingClientRect();
      const left = Math.min(box.left, innerWidth - tip.offsetWidth - 8);
      const top = box.bottom + tip.offsetHeight <= innerHeight - 8 ? box.bottom : box.top - tip.offsetHeight;
      tip.style.left = `${Math.max(8, left)}px`;
      tip.style.top = `${Math.max(8, top)}px`;
    }, 240);
  }
  container.addEventListener('pointerover', event => {
    if (event.pointerType === 'mouse') show(event.target.closest('[data-portrait]'));
  });
  container.addEventListener('pointerout', event => {
    if (anchor && !anchor.contains(event.relatedTarget) && !tip.contains(event.relatedTarget)) hide();
  });
  tip.addEventListener('pointerleave', hide);
  container.addEventListener('focusin', event => {
    if (event.target.matches(':focus-visible')) show(event.target.closest('[data-portrait]'));
  });
  container.addEventListener('focusout', hide);
  document.addEventListener('keydown', event => { if (event.key === 'Escape') hide(); });
  window.addEventListener('scroll', hide, true);
  window.addEventListener('resize', hide);
  return hide;
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

  const dynamic = document.createElement('nav');
  dynamic.setAttribute('aria-label','物品目录分页');
  dynamic.id = 'pagination';
  dynamic.className = 'pagination';
  dynamic.hidden = true;
  const previous = document.createElement('button');
  previous.id = 'previous';
  previous.type = 'button';
  previous.textContent = '上一页';
  const pageLinks = element('span', null, 'page-links');
  const next = document.createElement('button');
  next.id = 'next';
  next.type = 'button';
  next.textContent = '下一页';
  dynamic.append(previous, pageLinks, next);
  if (staticPagination) staticPagination.after(dynamic);
  else root.append(dynamic);

  status.textContent = '正在加载物品搜索索引…';
  try {
    const [index, facets] = await Promise.all(['index.json', 'filters.json'].map(async file => {
      const response = await fetch(pageRoot.dataset.indexUrl.replace(/index\.json$/, file));
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      return response.json();
    }));
    const hideTip = Object.keys(facets.portraits || {}).length
      ? enablePortraitTips(root, facets.portraits, new URL(pageRoot.dataset.assetRoot, documentUrl)) : null;
    let state = readState();
    let presets = history.state?.gearPresets || {};
    let lastGear = presets.last || 'normal';
    const sets = new Map();
    for (const family of facets.sets || []) for (const id of family[1]) sets.set(id, family);
    const releaseRank = new Map((facets.releaseOrder || []).map((p,i) => [p,i]));
    const collator = new Intl.Collator('zh-CN', {numeric:true});
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
    const inView = (id, view, area = '') => {
      if (view === 'furnishing') return furnishingCategories.has(id) && (!area || (id === 76) === (area === 'garden'));
      const [, group] = categoryOf(id);
      return !view || (view === 'gear' ? group.startsWith('装备') : group === '素材');
    };
    const tabs = document.createElement('div');
    tabs.className = 'view-tabs';
    const setGrouping = new Map();
    const buttons = [['', '全部物品'], ['gear', '装备'], ['material', '素材'], ['furnishing', '家具/庭具'],
      ...(unlockKinds.length ? [['unlock', '解锁']] : [])].map(([view, title]) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = title;
      button.addEventListener('click', () => {
        if (state.view === view) return;
        rememberGear();
        const query = state.query;
        setGrouping.set(state.view, state.bySet);
        const display = {sort:state.sort, bySet:setGrouping.get(view) ?? (view === 'gear'), byPatch:state.byPatch};
        state = view === 'gear' && presets[lastGear] ? restoreGear(lastGear)
          : {query, view, fashion:false, ...emptyFilters(), page:1};
        Object.assign(state,display);
        navigate(state.query, state.page);
      });
      tabs.append(button);
      return [view, button];
    });
    form.append(tabs);
    const filterBox = element('section', null, 'filter-box');
    filterBox.setAttribute('aria-label','筛选条件');
    const filterHeading = element('div', null, 'filter-heading');
    filterHeading.append(element('h2','筛选条件'));
    const filters = element('div', null, 'filters');
    const areaBox = element('div', null, 'gear-band furnishing-band');
    areaBox.setAttribute('role','group');
    areaBox.setAttribute('aria-label','摆设分类');
    const areas = element('div');
    areaBox.append(element('span','分类'), areas);
    const furnishingButtons = [];
    function furnishingButton(parent, label, area, category = '') {
      const button = element('button', label);
      button.type = 'button';
      button.addEventListener('click', () => {
        Object.assign(state, {area, category});
        navigate(state.query, 1);
      });
      parent.append(button);
      furnishingButtons.push({button, area, category});
    }
    furnishingButton(areas, '全部摆设', '');
    for (const [area,label] of [['garden','庭具'], ['indoor','家具']]) {
      const line = element('div', null, 'job-line');
      furnishingButton(line, label, area);
      if (area === 'indoor') {
        const types = element('div');
        for (const id of furnishingCategories) {
          if (id !== 76 && facets.categories[id]) furnishingButton(types, id === 57 ? '一般家具' : categoryOf(id)[0], area, String(id));
        }
        line.append(types);
      }
      areas.append(line);
    }
    filterBox.append(filterHeading, filters);
    form.append(filterBox);
    const unlockCloud = element('div', null, 'gear-band');
    unlockCloud.setAttribute('role','group');
    unlockCloud.setAttribute('aria-label','解锁分类');
    const tags = document.createElement('div');
    unlockCloud.append(element('span','分类'), tags);
    const fashionSwitch = document.createElement('button');
    fashionSwitch.type = 'button';
    fashionSwitch.className = 'filter-switch fashion-switch';
    fashionSwitch.setAttribute('role','switch');
    fashionSwitch.textContent = '时装';
    fashionSwitch.title = '仅看装备等级 1 的防具和饰品，包含部分新手装备。';
    fashionSwitch.addEventListener('click', () => {
      rememberGear();
      state = {...restoreGear(state.fashion ? 'normal' : 'fashion'), sort:state.sort, bySet:state.bySet, byPatch:state.byPatch};
      navigate(state.query, state.page);
    });
    const gearSection = element('div', null, 'gear-section');
    const panel = document.createElement('details');
    panel.className = 'gear-panel';
    const defaultPanel = true;
    function restoreDisplay() {
      const params = new URLSearchParams(location.search);
      layout = params.get('layout') === 'list' ? 'list' : 'cards';
      panel.open = params.has('panel') ? params.get('panel') === 'open' : defaultPanel;
    }
    function writeDisplay(url) {
      if (layout === 'list') url.searchParams.set('layout', 'list');
      else url.searchParams.delete('layout');
      if (panel.open !== defaultPanel) url.searchParams.set('panel', panel.open ? 'open' : 'closed');
      else url.searchParams.delete('panel');
    }
    function saveDisplay() {
      const url = new URL(location.href);
      writeDisplay(url);
      if (url.href !== location.href) history.replaceState(history.state, '', url);
    }
    const summary = document.createElement('summary');
    panel.append(summary, areaBox, unlockCloud);
    const nameLabel = element('label','名称或 ID', 'name-field');
    nameLabel.htmlFor = 'catalog-name';
    const nameInput = element('input');
    nameInput.type = 'search';
    nameInput.id = 'catalog-name';
    nameInput.placeholder = '筛选当前结果';
    nameInput.addEventListener('input', event => {
      if (event.isComposing) return;
      navigate(nameInput.value, 1, true);
    });
    nameInput.addEventListener('compositionend', () => {
      navigate(nameInput.value, 1, true);
    });
    nameLabel.append(nameInput);
    filters.append(nameLabel);
    gearSection.append(panel, fashionSwitch);
    filterBox.append(gearSection);
    const grid = document.createElement('ul');
    grid.className = 'item-grid';
    status.after(grid);
    let layout = 'cards';
    restoreDisplay();
    panel.addEventListener('toggle', saveDisplay);
    const toolbar = element('div', null, 'results-toolbar');
    toolbar.tabIndex = -1;
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
        saveDisplay();
        render();
      });
      switcher.append(button);
      return [mode, button];
    });
    status.before(toolbar);
    const groupButtons = [['bySet','按照套装分组'],['byPatch','按照版本分组']].map(([key,title]) => {
      const button = element('button',title);
      button.type = 'button';
      button.addEventListener('click', () => {state[key] = !state[key]; navigate(state.query,1);});
      toolbar.append(button);
      return [key,button];
    });
    const sortLabel = element('label','排序 ');
    const sorting = element('select');
    for (const [key,text] of Object.entries(sortModes)) {
      const option = element('option',text);
      option.value = key;
      sorting.append(option);
    }
    sorting.addEventListener('change', () => {state.sort = sorting.value; navigate(state.query,1);});
    sortLabel.append(sorting);
    toolbar.append(sortLabel, switcher, status);
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
    jobs.body.className = 'job-picker';
    const names = [...new Set(Object.values(facets.jobs).flat())];
    chip(jobs.body, 'job', '', '全部职业');
    const jobGroups = {
      战斗精英:names.filter(n => !crafting.includes(n) && !gathering.includes(n)),
      能工巧匠:names.filter(n => crafting.includes(n)), 大地使者:names.filter(n => gathering.includes(n)),
    };
    const jobSelect = element('select');
    jobSelect.setAttribute('aria-label', '具体职业');
    jobSelect.addEventListener('change', () => {
      state.job = jobSelect.value;
      navigate(state.query, 1);
    });
    const jobOptions = [];
    for (const [group, members] of Object.entries(jobGroups)) {
      if (!members.length) continue;
      chip(jobs.body, 'job', group, group);
      for (const name of members) jobOptions.push([name, name, group]);
    }
    options(jobSelect, jobOptions, '选择具体职业');
    jobs.body.append(jobSelect);
    const slots = band('部位');
    chip(slots.body, 'slot', '', '全部部位');
    for (const slot of new Set(Object.values(facets.slots).flat())) chip(slots.body, 'slot', slot, slot);
    const ranges = band('范围');
    const hasSlots = Object.keys(facets.slots).length > 0;
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
      const numeric = /(?:Min|Max)$/.test(key);
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
    const flagSwitches = Object.entries(flagLabels).map(([key, label]) => {
      const button = element('button', label, 'filter-switch');
      button.type = 'button';
      button.setAttribute('role', 'switch');
      button.addEventListener('click', () => {
        state[key] = state[key] === '1' ? '' : '1';
        navigate(state.query, 1);
      });
      filters.append(button);
      return [key, button];
    });
    const reset = document.createElement('button');
    reset.type = 'button';
    reset.textContent = '清除筛选';
    reset.addEventListener('click', () => {
      for (const key of filterKeys) state[key] = '';
      navigate('', 1);
    });
    filterHeading.append(reset);
    function options(field, entries, placeholder = '不限') {
      const fragment = document.createDocumentFragment();
      const groups = new Map();
      for (const [value, name, group] of [['', placeholder], ...entries]) {
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
    const hasCrafting = index.some(row => row[10] != null);
    options(fields.patch.field, [...new Set(index.map(r => r[8]).filter(Boolean))]
      .sort().reverse().map(p => [p,p,/^\d\./.test(p) ? `${p[0]}.x` : '其他记录']));
    let lastView;

    function render() {
      hideTip?.();
      for (const [key, button] of flagSwitches) {
        button.hidden = key === 'craftable' && !hasCrafting;
        if (state[key] !== '1' || button.hidden) state[key] = '';
        button.setAttribute('aria-checked', String(state[key] === '1'));
      }
      const query = state.query.trim().toLocaleLowerCase();
      const gear = state.view === 'gear';
      jobSelect.value = Object.hasOwn(jobGroups, state.job) ? '' : state.job;
      const allowSets = (gear || !state.view) && sets.size > 0;
      const groupSet = state.bySet && allowSets;
      sorting.value = state.sort;
      groupButtons[0][1].hidden = !allowSets;
      for (const [key,button] of groupButtons) button.setAttribute('aria-pressed',String(state[key]));
      if (nameInput.value !== state.query) nameInput.value = state.query;
      const unlock = state.view === 'unlock';
      const furnishing = state.view === 'furnishing';
      areaBox.hidden = !furnishing;
      if (furnishing) {
        if (state.category && !inView(Number(state.category), state.view, state.area)) state.category = '';
        if (!state.area && state.category) state.area = state.category === '76' ? 'garden' : 'indoor';
        if (state.area === 'garden') state.category = '';
        for (const {button, area, category} of furnishingButtons) {
          button.setAttribute('aria-pressed', String(state.area === area && state.category === category));
        }
      }
      filters.className = unlock || furnishing ? 'filters filters-no-category' : 'filters';
      unlockCloud.hidden = !unlock;
      const fashion = gear && state.fashion;
      if (fashion) {
        state.equipMin = state.equipMax = '1';
        if (!fashionCategories.has(Number(state.category))) state.category = '';
        state.slot = state.slot.split(',').filter(s => fashionSlots.has(s)).join(',');
      }
      fashionSwitch.hidden = !gear;
      fashionSwitch.setAttribute('aria-checked',String(fashion));
      rangeGroups.item.hidden = !Object.keys(facets.jobs).length;
      gearSection.hidden = !gear && !furnishing && !unlock;
      jobs.row.hidden = !gear || !names.length;
      slots.row.hidden = !gear || !hasSlots;
      ranges.row.hidden = !gear;
      const cards = layout === 'cards';
      grid.hidden = !cards;
      table.hidden = cards;
      for (const [mode, button] of layoutButtons) button.setAttribute('aria-pressed', String(mode === layout));
      const selectedSlots = state.slot.split(',').filter(Boolean);
      const editable = filterKeys.filter(key => !(fashion && key.startsWith('equip')));
      const active = editable.filter(key => !['area','category','patch'].includes(key) && !(key in flagLabels) && state[key]).length;
      const title = unlock ? '解锁筛选' : furnishing ? '摆设筛选' : '装备筛选';
      let selection = '';
      if (unlock) selection = state.category;
      if (furnishing && state.area) selection = furnishingButtons.find(
        choice => choice.area === state.area && choice.category === state.category)?.button.textContent;
      if (gear && active) selection = `已选 ${active} 项条件`;
      summary.textContent = selection ? `${title} · ${selection}` : title;
      for (const {key, value, button} of chipStates) {
        button.hidden = fashion && key === 'slot' && !!value && !fashionSlots.has(value);
        const selected = key === 'slot' && value ? selectedSlots.includes(value) : state[key] === value;
        button.setAttribute('aria-pressed', String(selected));
      }
      const viewKey = fashion ? 'fashion' : state.view;
      if (!unlock && !furnishing && lastView !== viewKey) {
        options(fields.category.field, categories.filter(id => inView(id, state.view) && (!fashion || fashionCategories.has(id)))
          .sort((a,b) => a-b).map(id => [id, ...categoryOf(id)]));
        lastView = viewKey;
      }
      for (const [view, button] of buttons) button.setAttribute('aria-pressed', String(view === state.view));
      for (const [key, {wrap, field}] of Object.entries(fields)) {
        wrap.hidden = ((unlock || furnishing) && key === 'category')
          || (key.startsWith('item') && !Object.keys(facets.jobs).length);
        field.value = state[key];
        field.disabled = fashion && key.startsWith('equip');
      }
      reset.hidden = !state.query && !editable.some(k => state[k]);
      const results = index.filter(([id, name, cat, , level, ilvl, slot, job, patch, tradable, craftable]) =>
        (!state.tradable || tradable === Number(state.tradable)) &&
        (!state.craftable || craftable === Number(state.craftable)) &&
        (!state.patch || state.patch === patch) &&
        (unlock ? unlocks.has(id) && (!state.category || unlocks.get(id) === state.category)
          : inView(cat, state.view, state.area) && (!state.category || String(cat) === state.category))
        && (!fashion || fashionCategories.has(cat))
        && (!gear || ((!state.equipMin || level >= Number(state.equipMin))
          && (!state.equipMax || level <= Number(state.equipMax))
          && (!state.itemMin || ilvl >= Number(state.itemMin))
          && (!state.itemMax || ilvl <= Number(state.itemMax))
          && (!selectedSlots.length || facets.slots[slot]?.some(s => selectedSlots.includes(s)))
          && (!state.job || facets.jobs[job]?.some(j => (jobGroups[state.job] || [state.job]).includes(j)))))
        && (!query || String(id).includes(query) || name.toLocaleLowerCase().includes(query)));
      const sort = state.sort.replace('-', ''), direction = state.sort.startsWith('-') ? -1 : 1;
      if (state.sort !== 'id') results.sort((a,b) => {
        let cmp;
        if (sort === 'release') {
          const x = releaseRank.get(a[8]), y = releaseRank.get(b[8]);
          if ((x == null) !== (y == null)) return x == null ? 1 : -1;
          cmp = (x ?? 0) - (y ?? 0);
        } else cmp = sort === 'name' ? collator.compare(a[1],b[1]) : a[0]-b[0];
        return direction * cmp || a[0]-b[0];
      });
      const pages = Math.max(1, Math.ceil(results.length / pageSize));
      state.page = Math.min(state.page, pages);
      const fragment = document.createDocumentFragment();
      function groupHeading(title, count, level) {
        const row = element(cards ? 'li' : 'tr', null,'result-heading');
        const cell = cards ? row : element('th');
        if (!cards) {cell.colSpan = 3; row.append(cell);}
        const head = element(level,title);
        if (count != null) head.append(element('small',` · ${count} 件`));
        cell.append(head);
        fragment.append(row);
      }
      let offset = (state.page-1)*pageSize, remaining = pageSize, previousPatch;
      for (const batch of batches(results,state.byPatch,groupSet,sets)) {
        if (offset >= batch.list.length) {offset -= batch.list.length; continue;}
        if (batch.patch && batch.patch !== previousPatch) groupHeading(batch.patch,null,'h2');
        previousPatch = batch.patch;
        if (batch.family) groupHeading(batch.family,batch.list.length,batch.patch ? 'h3' : 'h2');
        const slice = batch.list.slice(offset,offset+remaining);
        for (const [id, name, category, iconUrl, level, ilvl,,,patch] of slice) {
        const icon = document.createElement('img');
        icon.className = 'item-icon';
        icon.src = resolveIconUrl(iconUrl, new URL(pageRoot.dataset.assetRoot, documentUrl));
        icon.alt = '';
        icon.width = 32;
        icon.height = 32;
        icon.loading = 'lazy';
        icon.decoding = 'async';
        const link = document.createElement('a');
        const target = new URL(`${pageRoot.dataset.detailBase}${id}.html`, documentUrl);
        link.href = target.href;
        if (facets.portraits?.[id]) link.dataset.portrait = id;
        const kind = unlock ? unlocks.get(id) : categoryOf(category)[0];
        const levels = inView(category, 'gear') ? `装备等级 ${level}${ilvl == null ? '' : ` · 品级 ${ilvl}`}` : '';
        fragment.append((cards ? itemCard : itemRow)({id, name, kind, patch, detail: levels, icon, link}));
        }
        offset = 0;
        remaining -= slice.length;
        if (!remaining) break;
      }
      (cards ? grid : rows).replaceChildren(fragment);
      status.textContent = results.length
        ? `共 ${results.length.toLocaleString('zh-CN')} 件物品${state.query ? `，搜索“${state.query}”` : ''}`
        : '没有符合条件的物品。可以清除筛选，或换一个关键词。';
      const links = document.createDocumentFragment();
      for (const n of pageNumbers(state.page,pages)) {
        if (n === null) {links.append(element('span','…')); continue;}
        const current = n === state.page;
        const link = element(current ? 'strong' : 'a', String(n));
        link.setAttribute('aria-label', `第 ${n} 页`);
        if (current) link.setAttribute('aria-current','page');
        else {
          link.href = catalogUrl(n).href;
          link.addEventListener('click', event => {
            if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
            event.preventDefault();
            turnPage(n);
          });
        }
        links.append(link);
      }
      pageLinks.replaceChildren(links);
      previous.disabled = state.page === 1;
      next.disabled = state.page === pages;
    }

    function catalogUrl(page) {
      const url = new URL(pageRoot.dataset.catalogUrl, documentUrl);
      url.search = '';
      if (state.query) url.searchParams.set('q', state.query);
      if (state.fashion) url.searchParams.set('fashion','1');
      if (state.sort !== defaultSort) url.searchParams.set('sort',state.sort);
      if (state.bySet !== (state.view === 'gear')) url.searchParams.set('sets',state.bySet ? '1' : '0');
      if (!state.byPatch) url.searchParams.set('versions','0');
      for (const key of ['view', ...filterKeys]) if (state[key]) url.searchParams.set(key, state[key]);
      if (page > 1) url.searchParams.set('page', page);
      writeDisplay(url);
      return url;
    }

    function navigate(query, page, replace = false) {
      state = { ...state, query, page };
      render();
      const url = catalogUrl(state.page);
      rememberGear();
      history[replace ? 'replaceState' : 'pushState']({gearPresets:presets}, '', url);
    }

    function turnPage(n) {
      navigate(state.query, n);
      toolbar.focus({preventScroll:true});
      toolbar.scrollIntoView({block:'start'});
    }
    previous.addEventListener('click', () => turnPage(state.page - 1));
    next.addEventListener('click', () => turnPage(state.page + 1));
    window.addEventListener('popstate', () => {
      presets = history.state?.gearPresets || {};
      lastGear = presets.last || 'normal';
      state = readState();
      restoreDisplay();
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
