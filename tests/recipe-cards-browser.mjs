// Against a full CHS site, including an optional project Pages prefix.
// node tests/recipe-cards-browser.mjs http://127.0.0.1:8000/icexiv-db/
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtempSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const base = new URL(process.argv[2]);
const profile = mkdtempSync(join(tmpdir(), 'recipe-cards-'));
const browser = spawn(process.env.CHROMIUM || 'chromium', ['--headless','--no-sandbox','--no-proxy-server',
  '--remote-debugging-port=0', `--user-data-dir=${profile}`, 'about:blank']);
const stopped = once(browser, 'exit');
const timeout = setTimeout(() => browser.kill(), 45000);
try {
  const port = await new Promise(resolve => browser.stderr.on('data', data => {
    const m = /DevTools listening on ws:\/\/127.0.0.1:(\d+)/.exec(data);
    if (m) resolve(m[1]);
  }));
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
  await once(ws, 'open');
  let id = 0, loaded;
  const pending = new Map();
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id) { pending.get(m.id)?.(m.result); pending.delete(m.id); }
    if (m.method === 'Page.loadEventFired') loaded?.();
  };
  function send(method, params = {}) {
    return new Promise(resolve => { pending.set(++id, resolve); ws.send(JSON.stringify({id,method,params})); });
  }
  async function evalPage(expression) {
    const r = await send('Runtime.evaluate', {expression, returnByValue:true, awaitPromise:true});
    if (r.exceptionDetails) throw Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  }
  await send('Page.enable');
  // [item, panel id, expected text; empty when the panel is a relation group]
  for (const [item, selector, text] of [
    [5056, '#recipe-panel-ingredients-5056', '所需数量 ×2'],
    [7780, '#recipe-panel-book-7780', '每次产量'],
    [5106, '#recipe-panel-uses-5106', '消耗 ×2'],
    [52406, '.gear-relations', '同套装装备'],
    [2, '#recipe-panel-uses-2', '消耗 ×'],
  ]) {
    const url = new URL(`items/${item}.html`, base);
    if (item === 5056) url.hash = 'recipe-170';
    const done = new Promise(r => { loaded = r; });
    await send('Page.navigate', {url:url.href}); await done;
    const result = await evalPage(`(async () => {
      const section = document.querySelector(${JSON.stringify(selector)});
      section.scrollIntoView();
      if (!section.querySelector('.item-card')) await new Promise(resolve => {
        const observer = new MutationObserver(() => {
          if (section.querySelector('.item-card')) { observer.disconnect(); resolve(); }
        });
        observer.observe(section, {subtree:true, childList:true});
      });
      return [section.textContent, [...section.querySelectorAll('.item-card a')].map(a => a.href),
        [...section.querySelectorAll('a[href*="#recipe-"]')].map(a=>a.href)];
    })()`);
    assert.ok(result[0].includes(text), `${item}: ${text}`);
    assert.ok(result[1].length && result[1].every(href => href.startsWith(new URL('items/', base).href)));
    if (item === 5106) assert.ok(result[2].includes(new URL('items/5056.html#recipe-1', base).href));
    if (item === 5056) assert.ok(await evalPage(`(() => {
      const target = document.getElementById(location.hash.slice(1));
      const rect = target.getBoundingClientRect();
      return location.hash === '#recipe-170' && rect.top < innerHeight && rect.bottom > 0;
    })()`));
    if (item === 2) {
      assert.equal(result[1].length, 48);
      assert.equal(await evalPage(`(async () => {
        const section = document.querySelector('#recipe-panel-uses-2');
        await section.querySelector('button').onclick();
        return section.querySelectorAll('.item-card').length;
      })()`), 96);
      const raw = await (await fetch(url)).text();
      assert.ok(!raw.includes('#recipe-143') && !raw.includes('秘银手锤'));
      assert.ok(raw.includes('recipe-panel-uses-2'));
    }
    if (item === 52406) assert.ok(!result[1].includes(url.href));
    console.log(`${item}: ${result[1].length} cards, links and quantities verified`);
  }
  ws.close();
} finally {
  clearTimeout(timeout); browser.kill(); await stopped;
  rmSync(profile, {recursive:true,force:true,maxRetries:3,retryDelay:100});
}
