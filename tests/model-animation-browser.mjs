// Local WebGPU acceptance for the shared idle clip on a real detail page.
// node tests/model-animation-browser.mjs http://127.0.0.1:8001 [output-directory]
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtempSync, mkdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [base, output] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), 'icexiv-anim-'));
const browser = spawn(process.env.CHROMIUM || 'chromium', [
  '--disable-background-timer-throttling','--disable-renderer-backgrounding','--disable-backgrounding-occluded-windows',
  '--no-first-run', '--no-proxy-server', '--enable-unsafe-webgpu', '--enable-features=Vulkan',
  '--use-vulkan=native', '--ignore-gpu-blocklist', '--remote-debugging-port=0',
  `--user-data-dir=${profile}`, 'about:blank',
], {stdio: ['ignore', 'ignore', 'pipe']});
const stopped = once(browser, 'exit');
const deadline = setTimeout(() => {browser.kill(); console.error('WebGPU test timed out');process.exit(1);}, 120000);
try {
  const port = await new Promise(resolve => browser.stderr.on('data', data => {
    const match = /DevTools listening on ws:\/\/127\.0\.0\.1:(\d+)/.exec(data);
    if (match) resolve(match[1]);
  }));
  const tabs = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
  const ws = new WebSocket(tabs.find(t => t.type === 'page').webSocketDebuggerUrl);
  await once(ws, 'open');
  let id = 0, onLoad;
  const pending = new Map(), failures = [];
  ws.onmessage = e => {
    const msg = JSON.parse(e.data);
    if (msg.method === 'Page.loadEventFired') onLoad?.();
    if (msg.method === 'Runtime.exceptionThrown') failures.push(msg.params.exceptionDetails);
    if (msg.method === 'Log.entryAdded' && msg.params.entry.level === 'error' && !msg.params.entry.url?.endsWith('/favicon.ico')) failures.push(msg.params.entry.text);
    if (pending.has(msg.id)) {pending.get(msg.id)(msg);pending.delete(msg.id);}
  };
  const send = async (method, params = {}) => {
    const msg = await new Promise(resolve => {pending.set(++id, resolve);ws.send(JSON.stringify({id,method,params}));});
    if (msg.error) throw Error(JSON.stringify(msg.error));
    return msg.result;
  };
  const evaluate = async expression => {
    const r = await send('Runtime.evaluate', {expression,awaitPromise:true,returnByValue:true});
    if (r.exceptionDetails) throw Error(JSON.stringify(r.exceptionDetails));
    return r.result.value;
  };
  await send('Page.bringToFront');await send('Page.enable');await send('Runtime.enable');await send('Log.enable');
  const capture = async () => {
    const clip = await evaluate(`(async()=>{const el=host.querySelector('icexiv-equipment-canvas:not([hidden])');
      const c=el.shadowRoot.querySelector('canvas');c.scrollIntoView({block:'center'});
      await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));const b=c.getBoundingClientRect();
      return {x:b.x+scrollX,y:b.y+scrollY,width:b.width,height:b.height,scale:1};})()`);
    return (await send('Page.captureScreenshot',{clip,captureBeyondViewport:true})).data;
  };
  for (const [item, animated] of [[50745, true], [2984, true], [51749, false]]) {
    const load = new Promise(resolve => {onLoad=resolve;});
    await send('Page.navigate',{url:`${base}/items/${item}.html`});await load;
    const state = await evaluate(`(async()=>{
      window.host=document.querySelector('#model-preview');
      await host.querySelector('button').onclick();
      await new Promise(r=>setTimeout(r,2500));
      const toggle=host.querySelector('.preview-animation-toggle'), seek=host.querySelector('.preview-animation-seek');
      return [toggle.hidden, seek.hidden, toggle.textContent, Number(seek.max), host.querySelector('[role=status]').textContent];
    })()`);
    assert.equal(state[0], !animated, `${item} animation toggle`);
    assert.equal(state[1], !animated, `${item} animation seek`);
    if (!animated) continue;
    assert.ok(state[3] > 0, `${item} duration`);
    const first = await capture();
    await evaluate(`(async()=>{const seek=host.querySelector('.preview-animation-seek');
      seek.value=Number(seek.max)*0.5;seek.dispatchEvent(new Event('input'));
      await new Promise(r=>setTimeout(r,400));})()`);
    const second = await capture();
    assert.notEqual(first, second, `${item} animation did not change the frame`);
    assert.equal(await evaluate(`host.querySelector('.preview-animation-toggle').getAttribute('aria-pressed')`), 'false');
    if (output) {
      mkdirSync(output, {recursive: true});
      writeFileSync(join(output, `${item}-start.png`), Buffer.from(first, 'base64'));
      writeFileSync(join(output, `${item}-half.png`), Buffer.from(second, 'base64'));
    }
    console.log(item, 'idle clip, pause and seek OK');
  }
  assert.deepEqual(failures, []);
  ws.close();
} finally {
  clearTimeout(deadline);browser.kill();await stopped;rmSync(profile,{recursive:true,force:true});
}
