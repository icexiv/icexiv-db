// Offline search rendering test; no browser, network or game installation.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; }
  append(...children) { this.children.push(...children); }
  before(node) { this.preceding = node; }
  after(node) { this.following = node; }
  setAttribute() {}
  addEventListener(name, callback) { this.events[name] = callback; }
  replaceChildren(fragment) { this.children = fragment.children; }
}

for (const [path, prefix, gear] of [['index.html', '../', false], ['page/2.html', '../../', false],
  ['index.html', '../', true]]) {
  test(`search from ${path} with ${gear ? 'combined equipment filters' : 'keyword only'}`, async () => {
    const rows = new Element('tbody');
    const status = new Element('p');
    const pagination = new Element('p');
    const root = new Element('main');
    root.dataset = {
      pageSize: '100', assetRoot: prefix, indexUrl: `${prefix}generated/hash/index.json`,
      detailBase: path.startsWith('page/') ? '../' : './', catalogUrl: `${prefix}items/index.html`,
    };
    root.querySelector = selector => ({ '#catalog-status': status, table: { tBodies: [rows] },
      '.pagination': pagination })[selector];
    const search = gear ? '?q=甲&view=gear&job=战斗精英&slot=副手,主手&equipMin=49&equipMax=50&itemMin=90&itemMax=100' : '?q=甲';
    const location = { href: `https://example.test/db/items/${path}${search}`,
      pathname: `/db/items/${path}`, search };
    const listeners = {};
    const context = {
      document: {
        querySelector: () => root,
        createElement: tag => new Element(tag),
        createDocumentFragment: () => new Element('fragment'),
        createTextNode: text => ({ text }),
      },
      location, URL, URLSearchParams,
      window: { addEventListener: (event, callback) => { listeners[event] = callback; } },
      history: { pushState() {} },
      fetch: async url => ({ ok: true, json: async () => url.endsWith('filters.json')
        ? { categories: {2:['单手剑','装备 · 武器与盾']}, jobs:{1:['骑士']}, slots:{1:['主手']},
          unlocks:{坐骑:[1], 宠物:[2]} } : [
        [1, '甲<script>', 2, '/generated/hash/icons/12.png', 50, 90, 1, 1],
        [2, '甲占位', 2, '/icon-placeholder.svg', 51, 90, 1, 1],
        ...(gear ? [[3, '甲', 2, '/a', 50, 89, 1, 1], [4, '甲', 2, '/a', 50, 90, 2, 1],
          [5, '甲', 2, '/a', 50, 90, 1, 2], [6, '甲', 45, '/a', 50, 99, 1, 1],
          [7, '甲', 2, '/a', 48, 90, 1, 1], [8, '甲', 2, '/a', 50, 101, 1, 1]] : []),
      ] }),
    };
    vm.createContext(context);
    const code = readFileSync(`${__dirname}/../static/catalog.js`, 'utf8')
      .replace('if (root) start();', 'globalThis.completion = start();');
    vm.runInContext(code, context);
    await context.completion;
    const grid = status.following;
    assert.equal(grid.hidden, false);
    assert.equal(grid.children.length, gear ? 1 : 2);
    const link = grid.children[0].children[0];
    const icon = link.children[0];
    assert.equal(icon.src, 'https://example.test/db/generated/hash/icons/12.png');
    assert.equal(icon.alt, '');
    assert.equal(icon.loading, 'lazy');
    assert.equal(icon.width, 32);
    assert.equal(icon.height, 32);
    assert.equal(link.children[1].children[1].textContent, '#1');
    assert.equal(link.children[1].children[2].textContent, '甲<script>');
    const [cards, list] = status.preceding.children[1].children;
    list.events.click();
    assert.equal(grid.hidden, true);
    assert.equal(rows.children.length, gear ? 1 : 2);
    assert.equal(rows.children[0].children[1].children[2].href, link.href);
    if (!gear) assert.equal(rows.children[1].children[1].children[0].src,
      'https://example.test/db/icon-placeholder.svg');
    if (!gear) {
      location.search = '?view=unlock&category=坐骑&q=甲';
      listeners.popstate();
      assert.equal(rows.children.length, 1);
      assert.equal(rows.children[0].children[2].textContent, '坐骑');
      location.search = search;
    }
    listeners.popstate();
    cards.events.click();
    assert.equal(grid.hidden, false);
    assert.equal(grid.children[0].children[0].children[0].src, icon.src);
  });
}
