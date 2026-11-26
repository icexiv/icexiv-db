// Local WebGPU acceptance for an emote detail page.
// node tests/action-preview-browser.mjs http://127.0.0.1:8001 [output-directory]
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtempSync, mkdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [base, output] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), 'icexiv-action-'));
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
  const capture = async clip => (await send('Page.captureScreenshot', {clip, captureBeyondViewport: true})).data;
  await send('Page.bringToFront');
  // A development rebuild must not navigate away between two input events.
  await send('Network.enable');
  await send('Network.setBlockedURLs', {urls: ['*/_notist/serve/client.js*']});
  await send('Page.enable');await send('Runtime.enable');await send('Log.enable');
  const clipOf = () => evaluate(`(async()=>{const f=host.querySelector('.preview-frame');f.scrollIntoView({block:'center'});
    await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));
    const b=f.getBoundingClientRect();return {x:b.x+scrollX,y:b.y+scrollY,width:b.width,height:b.height,scale:1};})()`);
  for (const item of [12041, 52290]) {
    const load = new Promise(resolve => {onLoad = resolve;});
    await send('Page.navigate', {url: `${base}/items/${item}.html`});
    await load;
    const state = await evaluate(`(async()=>{
      window.host=document.querySelector('#action-preview');
      await host.querySelector('button').onclick();
      await new Promise(r=>setTimeout(r,1500));
      const stage=host.querySelector('icexiv-equipment-canvas:not([hidden])');
      const pressed=host.querySelector('.action-gender button[aria-pressed="true"]');
      return [!!stage, host.querySelector('.preview-replay')?.textContent,
        stage?.shadowRoot.querySelector('output').textContent, host.querySelector('[role=status]').textContent,
        host.querySelector('.action-race').value, pressed?.dataset.gender];
    })()`);
    assert.equal(state[0], true, `${item} has no canvas`);
    assert.equal(state[1], '重播动作');
    assert.equal(state[2], '65%');
    assert.match(state[3], /循环播放/);
    // The shared actor defaults to Au Ra female and exposes both genders.
    assert.deepEqual(state.slice(4), ['6', '1']);
    const clip = await clipOf();
    const first = await capture(clip);
    await new Promise(resolve => setTimeout(resolve, 900));
    const second = await capture(clip);
    assert.notEqual(first, second, `${item} action did not animate`);
    const switched = await evaluate(`(async()=>{
      const race=host.querySelector('.action-race');
      race.value='1'; race.dispatchEvent(new Event('change'));
      await new Promise(r=>setTimeout(r,1500));
      return [race.value, host.querySelector('.action-gender button[data-gender="0"]').disabled];
    })()`);
    assert.deepEqual(switched, ['1', false]);
    const third = await capture(clip);
    assert.notEqual(second, third, `${item} race switch did not change the actor`);
    const male = await evaluate(`(async()=>{
      host.querySelector('.action-gender button[data-gender="0"]').click();
      await new Promise(r=>setTimeout(r,1500));
      return host.querySelector('.action-gender button[aria-pressed="true"]').dataset.gender;
    })()`);
    assert.equal(male, '0');
    const hrothgar = await evaluate(`(async()=>{
      const race=host.querySelector('.action-race');
      race.value='7'; race.dispatchEvent(new Event('change'));
      await new Promise(r=>setTimeout(r,1500));
      return [host.querySelector('.action-gender button[data-gender="1"]').disabled,
        host.querySelector('.action-gender button[aria-pressed="true"]').dataset.gender];
    })()`);
    assert.deepEqual(hrothgar, [true, '0']);
    assert.equal(failures.length, 0);
    await evaluate(`host.querySelector('.preview-replay').click()`);
    if (output) {
      mkdirSync(output, {recursive: true});
      writeFileSync(join(output, `${item}.png`), Buffer.from(second, 'base64'));
    }
    console.log(item, 'emote loops, replays and switches actors OK');
  }
  assert.deepEqual(failures, []);
  ws.close();
} finally {
  clearTimeout(deadline);browser.kill();await stopped;rmSync(profile,{recursive:true,force:true});
}
