// Offline search rendering test; no browser, network or game installation.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { test } = require('node:test');
const vm = require('node:vm');

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.events = {}; }
  append(...children) { this.children.push(...children); }
  before(node) { node.preceding = this.preceding; this.preceding = node; }
  after(node) { this.following = node; }
  setAttribute() {}
  addEventListener(name, callback) { this.events[name] = callback; }
  replaceChildren(fragment) { this.children = fragment.tag === 'fragment' ? fragment.children : [fragment]; }
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
    const search = '?q=甲&versions=0' + (gear ? '&view=gear&job=战斗精英&slot=副手,主手&equipMin=49&equipMax=50&itemMin=90&itemMax=100' : '');
    const location = { href: `https://example.test/db/items/${path}${search}`,
      pathname: `/db/items/${path}`, search };
    const listeners = {};
    const custom = new Map();
    const context = {
      HTMLElement: Element, customElements: {define(name, cls) { custom.set(name, cls); }},
      document: {
        querySelector: () => root,
        createElement: tag => custom.has(tag) ? new (custom.get(tag))(tag) : new Element(tag),
        createDocumentFragment: () => new Element('fragment'),
        createTextNode: text => ({ text }),
      },
      location, URL, URLSearchParams,
      window: { addEventListener: (event, callback) => { listeners[event] = callback; } },
      history: { pushState() {}, replaceState(_, __, url) {
        location.href = url.href;
        location.search = url.search;
      } },
      fetch: async url => ({ ok: true, json: async () => url.endsWith('filters.json')
        ? { categories: {2:['单手剑','装备 · 武器与盾'], 57:['家具','住宅与部队工房'],
          76:['庭具','住宅与部队工房'], 78:['桌上','住宅与部队工房'], 90:['飞空艇部件（船体）','住宅与部队工房']}, jobs:{1:['骑士']}, slots:{1:['主手']},
          unlocks:{坐骑:[1], 宠物:[2]} } : [
        [1, '甲<script>', 2, gear ? 'https://cdn.example/objects/sha256/ab/cd' : '/generated/hash/icons/12.png', 50, 90, 1, 1, '7.0', 1, 0],
        [2, '甲占位', 2, '/icon-placeholder.svg', 51, 90, 1, 1, '7.0', 0, 1],
        [9, '室内座椅', 57, '/a'], [10, '庭院长椅', 76, '/a'], [11, '船体', 90, '/a'], [12, '花瓶', 78, '/a'],
        ...(gear ? [[3, '甲', 2, '/a', 50, 89, 1, 1], [4, '甲', 2, '/a', 50, 90, 2, 1],
          [5, '甲', 2, '/a', 50, 90, 1, 2], [6, '甲', 45, '/a', 50, 99, 1, 1],
          [7, '甲', 2, '/a', 48, 90, 1, 1], [8, '甲', 2, '/a', 50, 101, 1, 1]] : []),
      ] }),
    };
    vm.createContext(context);
    const code = readFileSync(`${__dirname}/../static/catalog.js`, 'utf8')
      .replace("import {element, itemCard} from './item-list.js';",
        readFileSync(`${__dirname}/../static/item-list.js`, 'utf8').replaceAll('export function', 'function'))
      .replace("import {iconUrl as resolveIconUrl, portraitUrl as resolvePortraitUrl} from './assets.js';",
        readFileSync(`${__dirname}/../static/assets.js`, 'utf8')
          .replaceAll('export function', 'function')
          .replace('function iconUrl(', 'function resolveIconUrl(')
          .replace('function portraitUrl(', 'function resolvePortraitUrl('))
      .replace('if (root) start();', 'globalThis.completion = start();');
    vm.runInContext(code, context);
    await context.completion;
    const grid = status.following;
    assert.equal(grid.hidden, false);
    assert.equal(grid.children.length, gear ? 1 : 2);
    const card = grid.children[0].children[0];
    assert.equal(card.tag, 'div');
    assert.equal(card.className, 'item-card');
    const link = card.children[0];
    const icon = link.children[0];
    assert.equal(icon.src, gear ? 'https://cdn.example/objects/sha256/ab/cd' : 'https://example.test/db/generated/hash/icons/12.png');
    assert.equal(icon.alt, '');
    assert.equal(icon.loading, 'lazy');
    assert.equal(icon.width, 32);
    assert.equal(icon.height, 32);
    assert.equal(link.children[1].children[1].textContent, '#1');
    assert.equal(link.children[1].children[2].textContent, '甲<script>');
    const [cards, list] = status.preceding.children.find(n => n.className === 'layout-switch').children;
    list.events.click();
    assert.equal(new URL(location.href).searchParams.get('layout'), 'list');
    assert.equal(grid.hidden, true);
    assert.equal(rows.children.length, gear ? 1 : 2);
    assert.equal(rows.children[0].children[1].children[2].href, link.href);
    if (!gear) assert.equal(rows.children[1].children[1].children[0].src,
      'https://example.test/db/icon-placeholder.svg');
    if (!gear) {
      for (const [flags, names] of [
        ['tradable=1&craftable=0', ['甲<script>']], ['tradable=0&craftable=1', ['甲占位']],
        ['tradable=1&craftable=1', []], ['tradable=0&craftable=0', ['甲<script>', '甲占位']],
      ]) {
        location.search = `?${flags}&q=甲&layout=list&versions=0`;
        listeners.popstate();
        assert.deepEqual(rows.children.map(r => r.children[1].children[2].textContent), names);
      }
      location.search = '?view=unlock&category=坐骑&q=甲&layout=list&versions=0';
      listeners.popstate();
      assert.equal(rows.children.length, 1);
      assert.equal(rows.children[0].children[2].textContent, '坐骑');
      const form = status.preceding.preceding;
      const box = form.children.find(n => n.className === 'filter-box');
      const queryInput = box.children.find(n => n.className.startsWith('filters')).children
        .find(n => n.className === 'name-field').children[0];
      assert.equal(queryInput.value, '甲');
      queryInput.value = '1';
      queryInput.events.input({});
      assert.equal(new URLSearchParams(location.search).get('q'), '1');
      assert.equal(rows.children[0].children[1].children[2].textContent, '甲<script>');
      const section = box.children.at(-1);
      const panel = section.children.find(n => n.tag === 'details');
      const [summary, areaBox, unlockBand] = panel.children;
      assert.equal(section.hidden, false);
      assert.equal(unlockBand.hidden, false);
      assert.equal(areaBox.hidden, true);
      assert.equal(summary.textContent, '解锁筛选 · 坐骑');
      for (const [filters, expected] of [['', ['家具','庭具','桌上']], ['category=76', ['庭具']],
        ['area=indoor', ['家具','桌上']], ['area=indoor&category=78', ['桌上']], ['area=garden&category=78', ['庭具']]]) {
        location.search = `?view=furnishing&${filters}&layout=list&versions=0&sort=id`;
        listeners.popstate();
        assert.deepEqual(rows.children.map(r => r.children[2].textContent), expected);
      }
      assert.equal(areaBox.hidden, false);
      assert.equal(queryInput.value, '');
      assert.equal(unlockBand.hidden, true);
      assert.equal(summary.textContent, '摆设筛选 · 庭具');
      const [all, garden, indoor] = areaBox.children[1].children;
      for (const [button, expected] of [[indoor.children[1].children.find(b => b.textContent === '桌上'), ['桌上']],
        [garden.children[0], ['庭具']], [indoor.children[0], ['家具','桌上']], [all, ['家具','庭具','桌上']]]) {
        button.events.click();
        assert.deepEqual(rows.children.map(r => r.children[2].textContent), expected);
      }
      location.search = search;
    }
    listeners.popstate();
    cards.events.click();
    assert.equal(grid.hidden, false);
    assert.equal(grid.children[0].children[0].children[0].children[0].src, icon.src);
  });
}
