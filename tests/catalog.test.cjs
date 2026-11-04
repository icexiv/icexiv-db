// Offline search rendering test; no browser, network or game installation.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; }
  append(...children) { this.children.push(...children); }
  before() {}
  after() {}
  setAttribute() {}
  addEventListener(name, callback) { this.events[name] = callback; }
  replaceChildren(fragment) { this.children = fragment.children; }
}

for (const [path, prefix] of [['index.html', '../'], ['page/2.html', '../../']]) {
  test(`search icons resolve under a deployment prefix from ${path}`, async () => {
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
    const location = { href: `https://example.test/db/items/${path}?q=甲`,
      pathname: `/db/items/${path}`, search: '?q=甲' };
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
      fetch: async () => ({ ok: true, json: async () => [
        [1, '甲<script>', 2, '/generated/hash/icons/12.png'],
        [2, '甲占位', 2, '/icon-placeholder.svg'],
      ] }),
    };
    vm.createContext(context);
    const code = readFileSync(`${__dirname}/../static/catalog.js`, 'utf8')
      .replace('if (root) start();', 'globalThis.completion = start();');
    vm.runInContext(code, context);
    await context.completion;
    assert.equal(rows.children.length, 2);
    const [icon, , link] = rows.children[0].children[1].children;
    assert.equal(icon.src, 'https://example.test/db/generated/hash/icons/12.png');
    assert.equal(icon.alt, '');
    assert.equal(icon.loading, 'lazy');
    assert.equal(icon.width, 32);
    assert.equal(icon.height, 32);
    assert.equal(link.textContent, '甲<script>');
    assert.equal(rows.children[1].children[1].children[0].src,
      'https://example.test/db/icon-placeholder.svg');
    listeners.popstate();
    assert.equal(rows.children[0].children[1].children[0].src, icon.src);
  });
}
