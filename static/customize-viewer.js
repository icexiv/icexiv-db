// Hairstyle & face-paint previews: opens directly on Actor with head camera preset
// and instant appearance hot-swap (hair/highlight color, face-paint color & flip).
import {resolveAsset} from './assets.js';
import {createObjectLoader} from './model-viewer.js';

const RACES = [[1, '人族'], [2, '精灵族'], [3, '拉拉菲尔族'], [4, '猫魅族'],
  [5, '鲁加族'], [6, '敖龙族'], [7, '硌狮族']];

// Curated palette indices into human.cmp (hair / highlight / face paint).
const HAIR_PRESETS = [
  ['默认', null], ['纯黑', 0], ['深棕', 28], ['栗棕', 54], ['金发', 90],
  ['银白', 184], ['樱粉', 132], ['酒红', 112], ['冰蓝', 156], ['薄荷', 168],
];
const PAINT_PRESETS = [
  ['黑', 0], ['白', 7], ['红', 12], ['粉', 20], ['蓝', 52], ['紫', 68], ['金', 36],
];

export function mountCustomizePreview(host, assets) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = '预览外观';
  const status = document.createElement('span');
  status.setAttribute('role', 'status');
  host.append(button, status);
  host.hidden = false;

  const viewportUrl = new URL('./model-sdk/icexiv-viewport.js', import.meta.url);
  let session;
  let controls;

  function close() {
    session?.abort();
    session = undefined;
    controls?.remove();
    controls = undefined;
    button.disabled = false;
    button.hidden = false;
    status.textContent = '';
  }

  async function open() {
    session = new AbortController();
    const {signal} = session;
    const fail = err => {
      if (signal.aborted) return;
      close();
      status.textContent = ` 无法显示外观：${err.message}`;
    };
    button.hidden = true;
    status.textContent = '';
    const actors = assets?.actionActors || {};

    controls = document.createElement('div');
    controls.innerHTML = `<section class="preview-frame" aria-label="外观预览视窗">
      <div class="preview-head"><strong>外观预览</strong><div class="preview-head-tools">
      <select class="action-race" aria-label="预览种族"></select>
      <div class="action-gender" role="group" aria-label="预览性别">
      <button type="button" data-gender="0" aria-pressed="false">男</button>
      <button type="button" data-gender="1" aria-pressed="false">女</button></div>
      <select class="customize-color" aria-label="颜色预设"></select>
      <button type="button" class="customize-extra" aria-pressed="false" hidden></button>
      <div class="preview-camera-presets" role="group" aria-label="镜头预设">
      <button type="button" data-preset="full" aria-pressed="false">全身</button>
      <button type="button" data-preset="upper" aria-pressed="false">半身</button>
      <button type="button" data-preset="head" aria-pressed="true">头部</button></div>
      <button type="button" class="preview-close" aria-label="关闭预览">关闭 <span aria-hidden="true">×</span></button>
      </div></div><div class="preview-stage"><label class="preview-progress"><span></span><progress></progress></label></div></section>`;
    const stageBox = controls.querySelector('.preview-stage');
    const meter = stageBox.querySelector('.preview-progress');
    const meterText = meter.querySelector('span');
    const meterBar = meter.querySelector('progress');
    const progress = (phase, done = 0, total = 0) => {
      if (signal.aborted) return;
      meter.hidden = !phase;
      if (!phase) return;
      meterText.textContent = (phase === 'actor-files' ? '加载角色与外观文件' : phase === 'engine' ? '加载渲染器' : '读取外观清单')
        + (total > 0 ? ` · ${done}/${total}` : '…');
      if (total > 0) { meterBar.max = total; meterBar.value = done; } else meterBar.removeAttribute('value');
    };
    const raceSelect = controls.querySelector('.action-race');
    const genderButtons = [...controls.querySelectorAll('.action-gender button')];
    const colorSelect = controls.querySelector('.customize-color');
    const extraBtn = controls.querySelector('.customize-extra');
    const presetButtons = [...controls.querySelectorAll('.preview-camera-presets button')];
    const closeBtn = controls.querySelector('.preview-close');
    status.before(controls);
    closeBtn.onclick = () => { close(); button.focus({preventScroll: true}); };
    closeBtn.focus({preventScroll: true});

    try {
      if (!navigator.gpu) throw Error('浏览器不支持 WebGPU');
      progress('manifest');
      const manifestUrl = resolveAsset(host.dataset.manifest);
      if (!manifestUrl) throw Error('外观资源未启用');
      const manifest = await fetch(manifestUrl, {signal}).then(r => {
        if (!r.ok) throw Error(`外观清单 HTTP ${r.status}`);
        return r.json();
      });
      const isFacePaint = manifest.kind === 'facepaint';
      controls.querySelector('.preview-head strong').textContent = isFacePaint ? '面妆预览' : '发型预览';
      const supported = new Set(manifest.actors || Object.keys(actors));
      const availRaces = RACES.filter(([id]) => (actors[`${id}-0`] && supported.has(`${id}-0`)) || (actors[`${id}-1`] && supported.has(`${id}-1`)));
      for (const [id, label] of availRaces) raceSelect.add(new Option(label, id));
      const [defRace, defGender] = (assets.actionDefault || '6-1').split('-');
      raceSelect.value = availRaces.some(([id]) => String(id) === defRace) ? defRace : String(availRaces[0]?.[0]);
      let genderValue = Number(defGender);

      for (const [label, val] of (isFacePaint ? PAINT_PRESETS : HAIR_PRESETS)) {
        colorSelect.add(new Option(`${isFacePaint ? '面妆色' : '发色'}：${label}`, val === null ? '' : String(val)));
      }
      extraBtn.hidden = false;
      extraBtn.textContent = isFacePaint ? '左右翻转' : '挑染';
      let extraOn = false;

      const loader = createObjectLoader();
      const read = (path, sha) => loader.read(path, sha, signal);
      const actorCache = new Map();
      const actorFor = key => {
        if (!actorCache.has(key)) {
          actorCache.set(key, fetch(resolveAsset(actors[key]), {signal}).then(r => {
            if (!r.ok) throw Error(`角色清单 HTTP ${r.status}`);
            return r.json();
          }));
        }
        return actorCache.get(key);
      };

      progress('engine');
      await import(viewportUrl);
      signal.throwIfAborted();

      let hotSwapping = false;
      const vp = document.createElement('icexiv-viewport');
      vp.addEventListener('loadprogress', ({detail}) => {
        if (!hotSwapping) progress(detail.phase, detail.done, detail.total);
      });
      vp.addEventListener('error', ({detail}) => fail(detail instanceof Error ? detail : Error(String(detail))));
      stageBox.append(vp);
      await vp.openScene();
      await vp.setCameraPreset('head');

      let currentActor = null;
      let currentKey = '';
      const buildCustomize = base => {
        const c = Array.from(base);
        if (isFacePaint) {
          c[24] = (manifest.featureId & 0x7f) | (extraOn ? 0x80 : 0);
          c[25] = Number(colorSelect.value || 0);
        } else {
          c[6] = manifest.featureId;
          if (colorSelect.value !== '') c[10] = Number(colorSelect.value);
          c[7] = extraOn ? 0x80 : 0;
          c[11] = extraOn ? 184 : 0;
        }
        return c;
      };
      const syncGender = () => {
        const opts = [0, 1].filter(g => actors[`${raceSelect.value}-${g}`] && supported.has(`${raceSelect.value}-${g}`));
        if (!opts.includes(genderValue)) genderValue = opts[0] ?? 0;
        for (const btn of genderButtons) {
          const v = Number(btn.dataset.gender);
          btn.setAttribute('aria-pressed', String(v === genderValue));
          btn.disabled = !opts.includes(v);
        }
      };
      const applyActor = async (hotSwap = false) => {
        syncGender();
        const key = `${raceSelect.value}-${genderValue}`;
        if (!hotSwap || key !== currentKey) {
          progress('actor-files');
          currentActor = await actorFor(key);
          currentKey = key;
          await vp.setActorBundle(currentActor, read, {
            customize: buildCustomize(currentActor.customize),
            files: manifest.files,
          });
          progress(null);
        } else if (currentActor) {
          hotSwapping = true;
          try {
            await vp.updateActorBundle(currentActor, read, {
              customize: buildCustomize(currentActor.customize),
              files: manifest.files,
            });
          } finally {
            hotSwapping = false;
            progress(null);
          }
        }
      };

      await applyActor(false);
      status.textContent = isFacePaint
        ? '面妆预览（头部特写），可切换种族、颜色与左右翻转。'
        : '发型预览（头部特写），可切换种族、发色与挑染。';

      raceSelect.onchange = () => applyActor(false).catch(fail);
      for (const btn of genderButtons) {
        btn.onclick = () => { if (!btn.disabled) { genderValue = Number(btn.dataset.gender); applyActor(false).catch(fail); } };
      }
      colorSelect.onchange = () => applyActor(true).catch(fail);
      extraBtn.onclick = () => {
        extraOn = !extraOn;
        extraBtn.setAttribute('aria-pressed', String(extraOn));
        applyActor(true).catch(fail);
      };
      for (const btn of presetButtons) {
        btn.onclick = async () => {
          for (const b of presetButtons) b.setAttribute('aria-pressed', String(b === btn));
          await vp.setCameraPreset(btn.dataset.preset);
        };
      }
    } catch (err) { progress(null); fail(err); }
    finally { if (!signal.aborted) button.disabled = false; }
  }

  button.onclick = () => open();
}
