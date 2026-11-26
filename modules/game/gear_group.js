const RELATION_SHARD = 16;
const jsonCache = new Map();
let modulesPromise;
let assetsPromise;
let observer;

function getLookup() {
  const lookup = document.querySelector('#item-lookup');
  if (!lookup) return null;
  return {
    assetRoot: new URL(lookup.dataset.assets, document.baseURI),
    indexUrl: new URL(lookup.dataset.index, document.baseURI),
  };
}

function fetchJson(url) {
  if (!jsonCache.has(url)) {
    jsonCache.set(url, fetch(url).then(r => {
      if (!r.ok) throw Error(`HTTP ${r.status}`);
      return r.json();
    }).catch(err => { jsonCache.delete(url); throw err; }));
  }
  return jsonCache.get(url);
}

function getObserver() {
  if (observer || typeof IntersectionObserver === 'undefined') return observer;
  observer = new IntersectionObserver(entries => {
    for (const entry of entries) {
      if (!entry.isIntersecting) continue;
      observer.unobserve(entry.target);
      entry.target._activate?.();
    }
  }, {rootMargin: '400px 0px'});
  return observer;
}

export default class GameGearGroup extends HTMLElement {
  connectedCallback() {
    if (this._init) return;
    this._init = true;
    const key = this.getAttribute('notist-key') ?? '';
    if (!this.id && key) this.id = `gear-group-${key}`;
    if (!this.childElementCount) {
      const p = document.createElement('p');
      p.textContent = '关联组按需加载，需要启用 JavaScript。';
      this.append(p);
    }
    const obs = getObserver();
    if (obs) obs.observe(this);
    else this._activate();
  }

  _activate() {
    if (!this.isConnected || this._loaded) return;
    this._loaded = true;
    this._load().catch(() => {
      this._loaded = false;
      const p = document.createElement('p');
      p.textContent = '明细加载失败，刷新页面重试。';
      this.replaceChildren(p);
    });
  }

  async _load() {
    const info = getLookup();
    if (!info) return;
    const {assetRoot, indexUrl} = info;
    const key = Number(this.getAttribute('notist-key') ?? '');
    const currentId = this.getAttribute('notist-item') ?? '';
    const dataUrl = path => new URL(path, indexUrl).href;
    const itemHref = itemId => new URL(`items/${itemId}.html`, assetRoot).href;

    const shard = await fetchJson(dataUrl(`relations/${Math.floor(key / RELATION_SHARD)}.json`));
    const group = shard.find(entry => String(entry[0]) === String(key));
    if (!group) return;
    const mods = await (modulesPromise ??= import(new URL('item-list.js', assetRoot)));
    const {iconUrl} = await (assetsPromise ??= import(new URL('assets.js', assetRoot)));

    const grid = mods.element('ul', null, 'item-grid');
    for (const [id, name, src, kind, version] of group[2]) {
      if (String(id) === String(currentId)) continue;
      const img = mods.element('img', null, 'item-icon');
      img.src = iconUrl(src, assetRoot);
      img.alt = '';
      img.width = img.height = 32;
      img.loading = 'lazy';
      img.decoding = 'async';
      const link = mods.element('a');
      link.href = itemHref(id);
      link.dataset.resultId = String(id);
      grid.append(mods.itemCard({id, name, kind, patch: version, icon: img, link}));
    }
    if (!this.isConnected) return;
    this.replaceChildren(grid);
  }
}
