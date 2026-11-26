const RECIPE_SHARD = 128;
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

function groupedUses(rows) {
  const groups = new Map();
  for (const [recipe, craft, product, qty] of rows) {
    if (!groups.has(product)) groups.set(product, []);
    groups.get(product).push({recipe, craft, qty});
  }
  return [...groups].map(([product, recipes]) => ({product, recipes}));
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

export default class GameRecipePanel extends HTMLElement {
  connectedCallback() {
    if (this._init) return;
    this._init = true;
    const mode = this.getAttribute('notist-mode') ?? '';
    const id = this.getAttribute('notist-id') ?? '';
    if (!this.id && mode && id) this.id = `recipe-panel-${mode}-${id}`;
    if (!this.childElementCount) {
      const p = document.createElement('p');
      p.textContent = mode === 'uses' ? '材料用途按需加载，需要启用 JavaScript。' : '配方明细按需加载，需要启用 JavaScript。';
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
    const mode = this.getAttribute('notist-mode') ?? '';
    const id = this.getAttribute('notist-id') ?? '';
    const dataUrl = path => new URL(path, indexUrl).href;
    const itemHref = itemId => new URL(`items/${itemId}.html`, assetRoot).href;

    const shard = await fetchJson(dataUrl(`recipes/${Math.floor(Number(id) / RECIPE_SHARD)}.json`));
    const panel = shard.panels?.[String(id)];
    if (!panel) return;
    const mods = await (modulesPromise ??= import(new URL('item-list.js', assetRoot)));
    const {iconUrl} = await (assetsPromise ??= import(new URL('assets.js', assetRoot)));

    const makeIcon = src => {
      const img = mods.element('img', null, 'item-icon');
      img.src = iconUrl(src, assetRoot);
      img.alt = '';
      img.width = img.height = 32;
      img.loading = 'lazy';
      img.decoding = 'async';
      return img;
    };
    const card = (cardId, meta, detailText, inList) => {
      const [name = '', src = '', kind = ''] = meta[String(cardId)] ?? [];
      const link = mods.element('a');
      link.href = itemHref(cardId);
      link.dataset.resultId = String(cardId);
      return (inList ? mods.itemCard : mods.cardElement)(
        {id: cardId, name, kind, detail: detailText, icon: makeIcon(src), link});
    };

    if (mode === 'ingredients') {
      const groups = new Map();
      for (const [recipe, craft, yieldCount, ingredients] of panel.ingredients ?? []) {
        if (!groups.has(recipe)) groups.set(recipe, {craft, yieldCount, materials: []});
        groups.get(recipe).materials.push(...ingredients);
      }
      const nodes = [];
      for (const [recipe, {craft, yieldCount, materials}] of groups) {
        const section = mods.element('section');
        section.id = `recipe-${recipe}`;
        const grid = mods.element('ul', null, 'item-grid');
        for (const [material, qty] of materials) {
          if (material) grid.append(card(material, shard.items, `所需数量 ×${qty}`, true));
        }
        section.append(
          mods.element('h3', `${craft} · 配方 #${recipe}`),
          mods.element('p', `每次制成 ${yieldCount} 件 · 所需材料`),
          grid,
        );
        nodes.push(section);
      }
      if (!this.isConnected) return;
      this.replaceChildren(...nodes);
      if (/^#recipe-\d+$/.test(location.hash)) {
        document.getElementById(location.hash.slice(1))?.scrollIntoView();
      }
      return;
    }

    const book = mode === 'book';
    const entries = book
      ? (panel.book ?? []).map(([recipe, product, qty]) => ({product, recipe, qty}))
      : groupedUses(panel.uses ?? []);
    const grid = mods.element(book ? 'ul' : 'div', null, book ? 'item-grid' : 'item-grid recipe-products');
    const more = mods.element('button');
    more.type = 'button';
    let shown = 0;
    const batch = async () => {
      more.disabled = true;
      try {
        for (const entry of entries.slice(shown, shown + 48)) {
          if (book) {
            grid.append(card(entry.product, shard.items,
              `配方 #${entry.recipe} · 每次产量 ${entry.qty}`, true));
            continue;
          }
          const box = mods.element('div');
          box.append(card(entry.product, shard.items, '', false));
          for (const {recipe, craft, qty} of entry.recipes) {
            const link = mods.element('a', `${craft} · 配方 #${recipe}`);
            link.href = `${itemHref(entry.product)}#recipe-${recipe}`;
            const line = mods.element('p');
            line.append(link, ` · 消耗 ×${qty}`);
            box.append(line);
          }
          grid.append(box);
        }
        shown = Math.min(shown + 48, entries.length);
        more.hidden = shown >= entries.length;
        more.textContent = `显示更多（${shown}/${entries.length}）`;
      } finally {
        more.disabled = false;
      }
    };
    more.onclick = () => batch().catch(() => { more.textContent = '加载失败，点击重试'; });
    await batch();
    if (!this.isConnected) return;
    this.replaceChildren(grid);
    if (entries.length > 48) this.append(more);
  }
}
