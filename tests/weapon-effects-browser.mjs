// Local WebGPU acceptance against a *real* site and mounted assets (no mocks).
// node tests/weapon-effects-browser.mjs http://127.0.0.1:8001 [output-directory]
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {once} from 'node:events';
import {mkdtempSync, mkdirSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';

const [base, output] = process.argv.slice(2);
const profile = mkdtempSync(join(tmpdir(), 'icexiv-vfx-'));
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
    if (msg.method === 'Runtime.consoleAPICalled' && msg.params.type === 'error') failures.push(msg.params.args.map(a=>a.value).join(' '));
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
  // A development rebuild must not navigate away between two input events.
  await send('Network.enable');await send('Network.setBlockedURLs',{urls:['*/_notist/serve/client.js*']});
  for (const item of [47470,16053,16063]) {
    const load = new Promise(resolve => {onLoad=resolve;});
    await send('Page.navigate',{url:`${base}/items/${item}.html`});await load;
    const state = await evaluate(`(async()=>{
      window.host=document.querySelector('#model-preview');
      window.progressSamples=[];
      host.addEventListener('loadprogress',({detail})=>{
        const meter=host.querySelector('.preview-progress'), bar=meter.querySelector('progress');
        progressSamples.push([detail.phase,bar.hasAttribute('value')?bar.value:null,!meter.hidden]);
      },false);
      const m=await (await fetch(host.dataset.manifest)).json();
      const fxHashes=new Set(Object.entries(m.parts[0].effect?.files??{}).filter(([p])=>/\\.(?:avfx|atex)$/.test(p)).map(([,h])=>h));
      window.isFx=url=>fxHashes.has(String(url).split('/').slice(-2).join(''));
      await host.querySelector('button').onclick();
      window.toggle=host.querySelector('[data-action=effect]');
      return [!!toggle,performance.getEntriesByType('resource').some(e=>fxHashes.has(e.name.split('/').slice(-2).join('')))];
    })()`);
    assert.deepEqual(state, [item !== 47470,item !== 47470]);
    const capture = async () => {
      const clip = await evaluate(`(async()=>{const el=host.querySelector('icexiv-equipment-canvas:not([hidden])');
        const c=el.shadowRoot.querySelector('canvas');c.scrollIntoView({block:'center'});
        await new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)));const b=c.getBoundingClientRect();
        return {x:b.x+scrollX,y:b.y+scrollY,width:b.width,height:b.height,scale:1};})()`);
      return (await send('Page.captureScreenshot',{clip,captureBeyondViewport:true})).data;
    };
    if(!state[0]){
      if(output){mkdirSync(output,{recursive:true});writeFileSync(join(output,`${item}.png`),Buffer.from(await capture(),'base64'));}
      continue;
    }
    assert.equal(await evaluate(`toggle.getAttribute('aria-pressed')`),'true');
    await evaluate(`toggle.onclick()`);
    await evaluate(`window.original=host.querySelector('icexiv-equipment-canvas');original.shadowRoot.querySelector('[data-step="1"]').click()`);
    await evaluate(`new Promise(r=>setTimeout(r,300))`);
    await evaluate(`toggle.onclick()`);
    assert.equal(await evaluate(`original===host.querySelector('icexiv-equipment-canvas') && original.shadowRoot.querySelector('output').textContent==='112%'`),true);
    assert.equal(await evaluate(`toggle.getAttribute('aria-pressed')`),'true');
    assert.equal(await evaluate(`['model-files','effect-files'].every(p=>progressSamples.some(([phase,n,visible])=>phase===p&&n>0&&visible))
      && progressSamples.some(([p,n,v])=>p==='unpack-effect'&&n===null&&v) && host.querySelector('.preview-progress').hidden`),true);
    const a = await capture();
    await evaluate(`new Promise(r=>setTimeout(r,850))`);
    const b = await capture();assert.notEqual(a,b,'effect canvas did not animate');
    await evaluate(`toggle.onclick()`);
    // Disabling drains the last particle pass; the drained frame must then stay still.
    await evaluate(`new Promise(r=>setTimeout(r,1200))`);
    const restored = await capture();
    await evaluate(`new Promise(r=>setTimeout(r,600))`);
    assert.equal(await capture(), restored,
      'switching particles off did not settle to a still frame on the same canvas');
    await evaluate(`toggle.onclick()`);
    if (output) {
      mkdirSync(output,{recursive:true});
      writeFileSync(join(output,`${item}.png`),Buffer.from(b,'base64'));
    }
    const ended = await evaluate(`(async()=>{
      host.querySelector('[data-action=replay]').click();
      const fx=host.querySelector('icexiv-equipment-canvas:not([hidden])');
      await toggle.onclick();
      if(fx.hidden || toggle.getAttribute('aria-pressed')!=='false')throw Error('static weapon not retained');
      await toggle.onclick();
      if(fx!==host.querySelector('icexiv-equipment-canvas:not([hidden])'))throw Error('effect scene was rebuilt');
      const stages=host.querySelectorAll('icexiv-equipment-canvas:not([hidden])').length;
      host.querySelector('.preview-close').click();return [stages,host.querySelectorAll('icexiv-equipment-canvas').length];
    })()`);
    assert.deepEqual(ended,[1,0]);
    // A missing effect object must not destroy the already usable static viewer.
    const fallback = await evaluate(`(async()=>{
      const fetchAsset=window.fetch;
      window.fetch=(url,opts)=>isFx(url)?Promise.resolve(new Response(null,{status:404})):fetchAsset(url,opts);
      try {await host.querySelector('button').onclick();}finally{window.fetch=fetchAsset;}
      return [host.querySelector('[role=status]').textContent,host.querySelectorAll('icexiv-equipment-canvas:not([hidden])').length];
    })()`);
    assert.match(fallback[0],/HTTP 404/);assert.equal(fallback[1],1);
    console.log(item, 'animated, replay/stop/dispose OK');
  }
  assert.deepEqual(failures,[]);
  ws.close();
} finally {
  clearTimeout(deadline);browser.kill();await stopped;rmSync(profile,{recursive:true,force:true});
}
