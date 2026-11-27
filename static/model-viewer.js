// DB resolves item manifests; the renderer SDK's <icexiv-equipment-canvas> owns the GPU lifecycle.
import {resolveAsset} from './assets.js';

export function createObjectLoader() {
  const cache = new Map();
  return {
    loadFile(path, sha, signal) {
      if (!sha) throw Error(`清单缺少 ${path}`);
      const url = resolveAsset(`models/objects/sha256/${sha.slice(0, 2)}/${sha.slice(2)}`);
      if (!url) throw Error(`资源未启用：${path}`);
      const integrity = `sha256-${btoa(String.fromCharCode(...sha.match(/../g).map(x => parseInt(x, 16))))}`;
      return fetch(url, {signal, integrity}).then(async bytes => {
        if (!bytes.ok) throw Error(`${path}: HTTP ${bytes.status}`);
        return new Uint8Array(await bytes.arrayBuffer());
      });
    },
    read(path, sha, signal) {
      if (!sha) throw Error(`清单缺少 ${path}`);
      if (!cache.has(sha)) cache.set(sha, this.loadFile(path, sha, signal));
      return cache.get(sha);
    },
  };
}

const SLOT_CATEGORY = {met: 3, top: 4, glv: 5, dwn: 7, sho: 8, ear: 9, nek: 10, wrs: 11, rir: 12, ril: 12};
const RACES = [[1, '人族'], [2, '精灵族'], [3, '拉拉菲尔族'], [4, '猫魅族'], [5, '鲁加族'], [6, '敖龙族'], [7, '硌狮族']];

function materialVariant(part) {
  for (const p of Object.values(part?.materials ?? {})) {
    const m = /\/material\/v(\d{4})\//.exec(p);
    if (m) return Number(m[1]);
  }
  return 1;
}

function tryOnInfo(manifest) {
  const parts = manifest.parts ?? [manifest];
  if (manifest.kind === 'barding') {
    const spec = {kind: 'chocobo', headId: 1, bodyId: 1, feetId: 1, headVariant: 1, bodyVariant: 1, feetVariant: 1};
    let found = false;
    for (const p of parts) {
      const m = /chara\/demihuman\/d0001\/obj\/equipment\/e(\d{4})\/model\/d0001e\d{4}_(met|top|sho)\.mdl$/.exec(p.model ?? '');
      if (!m) continue;
      found = true;
      const id = Number(m[1]), v = materialVariant(p);
      if (m[2] === 'met') { spec.headId = id; spec.headVariant = v; }
      else if (m[2] === 'top') { spec.bodyId = id; spec.bodyVariant = v; }
      else if (m[2] === 'sho') { spec.feetId = id; spec.feetVariant = v; }
    }
    return found ? {host: 'chocobo', spec} : null;
  }
  if (manifest.kind === 'armor' || manifest.kind === 'accessory') {
    const p = parts[manifest.defaultPart ?? 0];
    const m = /chara\/(?:equipment|accessory)\/[ea](\d{4})\/model\/c\d{4}[ea]\d{4}_(met|top|glv|dwn|sho|ear|nek|wrs|rir|ril)\.mdl$/.exec(p?.model ?? '');
    if (!m || !SLOT_CATEGORY[m[2]]) return null;
    const id = BigInt(Number(m[1])), v = BigInt(materialVariant(p));
    const modelMain = String((v << 16n) | id);
    const preset = ['met', 'ear', 'nek'].includes(m[2]) ? 'head' : 'full';
    return {host: 'actor', equipment: [{modelMain, equipSlotCategory: SLOT_CATEGORY[m[2]], itemId: 0, stainIds: [0, 0]}], preset};
  }
  if (manifest.kind === 'weapon' || manifest.kind === 'heldProp') {
    const p = parts[manifest.defaultPart ?? 0];
    const m = /chara\/weapon\/w(\d{4})\/obj\/body\/b(\d{4})\/model\//.exec(p?.model ?? '');
    if (!m) return null;
    const w = BigInt(Number(m[1])), b = BigInt(Number(m[2])), v = BigInt(materialVariant(p));
    const modelMain = String((v << 32n) | (b << 16n) | w);
    return {host: 'actor', prop: {modelMain, bone: 'n_buki_r'}, preset: 'full'};
  }
  return null;
}

export function mountModelPreview(host, assets = null) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = '查看 3D 模型';
  const status = document.createElement('span');
  status.setAttribute('role', 'status');
  host.append(button, status);
  host.hidden = false;

  const sdkUrl = new URL('./model-sdk/icexiv_renderer.js', import.meta.url);
  let session;
  let controls;

  function close() {
    session?.abort();
    session = undefined;
    controls?.remove(); // disconnecting icexiv-equipment-canvas frees its viewer
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
      status.textContent = ` 无法显示模型：${err.message}`;
    };
    button.hidden = true;
    status.textContent = '';
    controls = document.createElement('div');
    controls.innerHTML = `<section class="preview-frame" aria-label="装备模型视窗">
      <div class="preview-head"><strong></strong><div class="preview-head-tools">
      <button type="button" class="preview-animation-toggle" hidden aria-pressed="false">播放动作</button>
      <input class="preview-animation-seek" type="range" min="0" step="0.01" value="0" aria-label="动作进度" hidden>
      <button type="button" class="preview-close" aria-label="关闭模型">关闭 <span aria-hidden="true">×</span></button></div></div>
      <div class="preview-stage"></div></section>`;
    const head = controls.querySelector('.preview-head');
    const viewport = controls.querySelector('.preview-stage');
    const animToggle = head.querySelector('.preview-animation-toggle');
    const animSeek = head.querySelector('.preview-animation-seek');
    head.querySelector('strong').textContent = document.querySelector('#item-detail h1')?.textContent || '装备模型';
    const closeBtn = head.querySelector('.preview-close');
    closeBtn.onclick = () => { close(); button.focus({preventScroll: true}); };
    const meter = document.createElement('label');
    const text = document.createElement('span');
    const bar = document.createElement('progress');
    meter.className = 'preview-progress';
    meter.append(text, bar);
    viewport.append(meter);
    status.before(controls);
    closeBtn.focus({preventScroll: true});

    const phases = {
      manifest: '读取模型清单', engine: '加载渲染器', 'model-files': '加载模型文件', 'effect-files': '加载特效文件',
      'unpack-model': '解包模型并准备场景', 'unpack-effect': '解包武器特效', 'first-frame': '绘制首帧',
      materials: '加载材质', geometry: '读取模型几何',
    };
    const progress = (phase, done, total) => {
      if (signal.aborted) return;
      meter.hidden = !phase;
      if (!phase) return;
      text.textContent = (phases[phase] ?? phase) + (total > 0 ? ` · ${done}/${total}` : '…');
      if (total > 0) { bar.max = total; bar.value = done; } else bar.removeAttribute('value');
    };
    progress('manifest');

    try {
      if (!navigator.gpu) throw Error('浏览器不支持 WebGPU');
      const manifestUrl = resolveAsset(host.dataset.manifest);
      if (!manifestUrl) throw Error('模型资源未启用');
      const response = await fetch(manifestUrl, {signal});
      if (!response.ok) throw Error(`模型清单 HTTP ${response.status}`);
      const manifest = await response.json();
      const loader = createObjectLoader();
      const read = path => loader.read(path, manifest.files[path], signal);

      progress('engine');
      const [api] = await Promise.all([import(sdkUrl), import(new URL('./component.js', sdkUrl))]);
      signal.throwIfAborted();

      const parts = manifest.parts ?? [manifest];
      const tryOn = tryOnInfo(manifest);
      const actors = assets?.actionActors || {};
      const canTryOn = Boolean(tryOn && (tryOn.host === 'chocobo' ? resolveAsset('models/actions/actors/chocobo.json') : Object.keys(actors).length > 0));
      const viewportUrl = new URL('./model-sdk/icexiv-viewport.js', import.meta.url);
      let stage, playing = false, partRequest, mode = 'standalone';
      const replaceStage = (tag = 'icexiv-equipment-canvas') => {
        stage?.remove();
        stage = document.createElement(tag);
        if (tag === 'icexiv-equipment-canvas') stage.setAttribute('framed', '');
        meter.after(stage);
        return stage;
      };
      const toggle = document.createElement('button');
      const replay = document.createElement('button');
      toggle.type = replay.type = 'button';
      toggle.hidden = replay.hidden = true;
      replay.textContent = '重播';
      toggle.slot = replay.slot = 'playback';
      toggle.dataset.action = 'effect';
      replay.dataset.action = 'replay';
      toggle.textContent = '武器特效';
      replay.onclick = () => stage.replayEffect().catch(e => {
        if (!signal.aborted) status.textContent = `无法重播：${e.message}`;
      });
      const setPlaying = async enabled => {
        if (toggle.disabled) return;
        const current = stage;
        toggle.disabled = true;
        try {
          await current.setEffectEnabled(enabled);
          if (current === stage && !signal.aborted) playing = enabled;
        } catch (e) {
          if (current === stage && !signal.aborted) status.textContent = `特效无法播放：${e.message}。仍可查看静态模型。`;
        } finally {
          if (current === stage && !signal.aborted) {
            progress(null);
            toggle.disabled = false;
            replay.hidden = !playing;
            toggle.setAttribute('aria-pressed', String(playing));
          }
        }
      };
      toggle.onclick = () => setPlaying(!playing);

      const load = async (part, fallback = '') => {
        partRequest?.abort();
        partRequest = new AbortController();
        const partSignal = AbortSignal.any([signal, partRequest.signal]);
        let current = replaceStage();
        current.addEventListener('loadprogress', ({detail}) => {
          if (!partSignal.aborted) progress(detail.phase, detail.done, detail.total);
        });
        playing = false;
        toggle.hidden = replay.hidden = true;
        toggle.disabled = false;
        toggle.setAttribute('aria-pressed', 'false');
        if (part.effect && !fallback) {
          try {
            await current.openWeapon(part.effect, (p, sha) => loader.loadFile(p, sha, partSignal));
            partSignal.throwIfAborted();
            current.addEventListener('rendererror', e => {
              if (!partSignal.aborted) load(part, e.detail.message).catch(fail);
            }, {once: true});
            current.addEventListener('renderwarning', e => {
              if (!partSignal.aborted) status.textContent = `特效播放降级：${e.detail.join('；')}`;
            });
            toggle.hidden = false;
            current.append(toggle, replay);
            progress(null);
            status.textContent = part.effect.diagnostics?.length ? `武器特效有 ${part.effect.diagnostics.length} 项限制，见文件明细。` : '';
            await setPlaying(true);
            return;
          } catch (e) {
            partSignal.throwIfAborted();
            fallback = e.message;
            current = replaceStage();
          }
        }
        current.addEventListener('rendererror', ({detail}) => fail(detail), {once: true});
        progress('engine');
        const viewer = await current.open();
        progress('geometry');
        const mdl = await read(part.model);
        signal.throwIfAborted();
        animToggle.hidden = animSeek.hidden = true;
        animToggle.onclick = animSeek.oninput = null;
        let animated = false, animationNote = '';
        if (manifest.animation) {
          try {
            const {sklb, pap, record} = manifest.animation;
            const index = api.animationRecords(await read(pap)).indexOf(record);
            if (index < 0) throw Error(`动作记录 ${record} 不存在`);
            const duration = await current.setAnimatedModel(mdl, await read(sklb), await read(pap), index);
            if (!(duration > 0)) throw Error('动作时长为零');
            let animPlaying = false;
            const sync = () => {
              animToggle.textContent = animPlaying ? '暂停动作' : '播放动作';
              animToggle.setAttribute('aria-pressed', String(animPlaying));
            };
            animSeek.max = duration;
            animSeek.value = 0;
            animToggle.onclick = () => {
              animPlaying = !animPlaying;
              if (animPlaying) current.playAnimation(true); else current.pauseAnimation();
              sync();
            };
            animSeek.oninput = () => {
              current.seekAnimation(Number(animSeek.value));
              if (animPlaying) { current.pauseAnimation(); animPlaying = false; sync(); }
            };
            animToggle.hidden = animSeek.hidden = false;
            current.playAnimation(true);
            animPlaying = animated = true;
            sync();
          } catch (error) { animationNote = `动作不可用：${error.message}`; }
        }
        if (!animated) viewer.setModel(mdl);
        const slots = viewer.materialNames();
        let bound = 0;
        const total = slots.filter(name => part.materials[name]).length;
        let completed = 0;
        progress('materials', 0, total);
        const errors = [];
        await Promise.all(slots.map(async (name, i) => {
          if (!part.materials[name]) return;
          try {
            const material = await read(part.materials[name]);
            const path = (api.baseColorTexture ?? api.colorTexturePath)(material);
            const overlay = api.diffuseOverlay?.(material);
            const [texture, diffuse] = await Promise.all([
              path ? read(path) : new Uint8Array(),
              overlay && manifest.files[overlay] ? read(overlay) : null,
            ]);
            signal.throwIfAborted();
            if (diffuse) viewer.setMaterialWithDiffuse(i, material, texture, diffuse);
            else viewer.setMaterial(i, material, texture);
            bound++;
          } catch (err) { errors.push(err.message); }
          finally { if (!partSignal.aborted) progress('materials', ++completed, total); }
        }));
        signal.throwIfAborted();
        stage.show();
        progress(null);
        status.textContent = [
          `基础配色 ${bound}/${slots.length} 个材质槽。`,
          animated ? '正在播放待机动作，可暂停或拖动进度。' : '', animationNote,
          bound < slots.length ? '未绑定的槽以中性灰显示。' : '',
          part.materialFallbacks?.length ? '部分槽使用回退材质，配色为近似值。' : '',
          manifest.alternativeForms ? '可切换宠物外观。' : parts.length > 1 ? '当前为单部件预览，未组装。' : '',
          manifest.incompleteParts ? '部分声明部件尚未解析。' : '',
          fallback ? `特效场景不可用，显示基础模型：${fallback}` : '',
          ...errors,
        ].join('');
      };

      let select;
      if (parts.length > 1) {
        select = document.createElement('select');
        select.disabled = true;
        select.setAttribute('aria-label', '选择单独预览的模型部件');
        parts.forEach((p, i) => select.add(new Option(`${manifest.alternativeForms ? '外观' : '部件'} ${i + 1}：${p.model.split('/').pop()}`, i)));
        select.selectedIndex = manifest.defaultPart ?? 0;
        closeBtn.before(select);
        select.onchange = async () => {
          select.disabled = true;
          try { await load(parts[Number(select.value)]); }
          catch (err) { fail(err); }
          finally { if (!signal.aborted) select.disabled = false; }
        };
      }
      if (canTryOn) {
        const modeBox = document.createElement('div');
        modeBox.className = 'preview-mode';
        modeBox.setAttribute('role', 'group');
        modeBox.setAttribute('aria-label', '预览模式');
        modeBox.innerHTML = `<button type="button" data-mode="standalone" aria-pressed="true">单件</button><button type="button" data-mode="tryon" aria-pressed="false">试穿</button>`;
        const modeBtns = [...modeBox.querySelectorAll('button')];
        const tryOnTools = document.createElement('div');
        tryOnTools.className = 'preview-head-tools';
        tryOnTools.hidden = true;
        let raceSelect, genderButtons = [], genderValue = 1;
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
        if (tryOn.host === 'actor') {
          const availRaces = RACES.filter(([id]) => actors[`${id}-0`] || actors[`${id}-1`]);
          const [defRace, defGender] = (assets?.actionDefault || '6-1').split('-');
          genderValue = Number(defGender);
          raceSelect = document.createElement('select');
          raceSelect.className = 'action-race';
          raceSelect.setAttribute('aria-label', '试穿种族');
          for (const [id, label] of availRaces) raceSelect.add(new Option(label, id));
          raceSelect.value = availRaces.some(([id]) => String(id) === defRace) ? defRace : String(availRaces[0]?.[0]);
          const gBox = document.createElement('div');
          gBox.className = 'action-gender';
          gBox.setAttribute('role', 'group');
          gBox.setAttribute('aria-label', '试穿性别');
          gBox.innerHTML = `<button type="button" data-gender="0" aria-pressed="false">男</button><button type="button" data-gender="1" aria-pressed="false">女</button>`;
          genderButtons = [...gBox.querySelectorAll('button')];
          const pBox = document.createElement('div');
          pBox.className = 'preview-camera-presets';
          pBox.setAttribute('role', 'group');
          pBox.setAttribute('aria-label', '镜头预设');
          pBox.innerHTML = `<button type="button" data-preset="full" aria-pressed="${tryOn.preset === 'full'}">全身</button><button type="button" data-preset="upper" aria-pressed="false">半身</button><button type="button" data-preset="head" aria-pressed="${tryOn.preset === 'head'}">头部</button>`;
          const pBtns = [...pBox.querySelectorAll('button')];
          for (const b of pBtns) {
            b.onclick = async () => {
              for (const x of pBtns) x.setAttribute('aria-pressed', String(x === b));
              if (mode === 'tryon' && stage?.setCameraPreset) await stage.setCameraPreset(b.dataset.preset);
            };
          }
          tryOnTools.append(raceSelect, gBox, pBox);
        }
        const syncGender = () => {
          if (!raceSelect) return;
          const opts = [0, 1].filter(g => actors[`${raceSelect.value}-${g}`]);
          if (!opts.includes(genderValue)) genderValue = opts[0] ?? 0;
          for (const btn of genderButtons) {
            const v = Number(btn.dataset.gender);
            btn.setAttribute('aria-pressed', String(v === genderValue));
            btn.disabled = !opts.includes(v);
          }
        };
        syncGender();
        const loadTryOn = async () => {
          partRequest?.abort();
          partRequest = new AbortController();
          const pSig = AbortSignal.any([signal, partRequest.signal]);
          animToggle.hidden = animSeek.hidden = true;
          if (select) select.hidden = true;
          tryOnTools.hidden = false;
          progress('engine');
          await import(viewportUrl);
          pSig.throwIfAborted();
          const vp = replaceStage('icexiv-viewport');
          vp.addEventListener('loadprogress', ({detail}) => {
            if (!pSig.aborted) progress(detail.phase, detail.done, detail.total);
          });
          vp.addEventListener('error', ({detail}) => {
            if (!pSig.aborted) status.textContent = `试穿加载失败：${detail?.message ?? detail}`;
          });
          await vp.openScene();
          pSig.throwIfAborted();
          const readObj = (path, sha) => loader.read(path, sha, pSig);
          if (tryOn.host === 'chocobo') {
            progress('model-files');
            const choco = await fetch(resolveAsset('models/actions/actors/chocobo.json'), {signal: pSig}).then(r => {
              if (!r.ok) throw Error(`陆行鸟模型 HTTP ${r.status}`);
              return r.json();
            });
            const merged = {...choco.files, ...manifest.files};
            await vp.setStandalone(tryOn.spec, merged, readObj);
            progress(null);
            status.textContent = '陆行鸟试穿预览，拖动旋转视角。';
          } else {
            syncGender();
            const key = `${raceSelect.value}-${genderValue}`;
            progress('actor-files');
            const actor = await actorFor(key);
            await vp.setCameraPreset(tryOn.preset || 'full');
            await vp.setActorBundle(actor, readObj, tryOn.equipment ? {equipment: tryOn.equipment, files: manifest.files} : {});
            if (tryOn.prop) {
              await vp.addProp('tryon-weapon', tryOn.prop.modelMain, tryOn.prop.bone, manifest.files, readObj);
            }
            progress(null);
            status.textContent = '角色试穿预览，可切换种族、性别与镜头预设。';
          }
        };
        if (raceSelect) {
          raceSelect.onchange = () => { if (mode === 'tryon') loadTryOn().catch(e => { progress(null); if (!signal.aborted) status.textContent = `试穿失败：${e.message}`; }); };
          for (const btn of genderButtons) {
            btn.onclick = () => {
              if (btn.disabled) return;
              genderValue = Number(btn.dataset.gender);
              if (mode === 'tryon') loadTryOn().catch(e => { progress(null); if (!signal.aborted) status.textContent = `试穿失败：${e.message}`; });
            };
          }
        }
        for (const btn of modeBtns) {
          btn.onclick = async () => {
            if (btn.dataset.mode === mode) return;
            mode = btn.dataset.mode;
            for (const b of modeBtns) b.setAttribute('aria-pressed', String(b === btn));
            if (mode === 'tryon') {
              await loadTryOn().catch(e => { progress(null); if (!signal.aborted) status.textContent = `试穿失败：${e.message}`; });
            } else {
              tryOnTools.hidden = true;
              if (select) select.hidden = false;
              await load(parts[select ? Number(select.value) : (manifest.defaultPart ?? 0)]);
            }
          };
        }
        closeBtn.before(modeBox, tryOnTools);
      }
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      const paths = new Set([...Object.keys(manifest.files), ...parts.flatMap(p => Object.keys(p.effect?.files ?? {}))]);
      summary.textContent = `关联游戏文件（${paths.size}） · ${manifest.version ?? manifest.gameVersion}`;
      const list = document.createElement('ul');
      for (const item of [...paths, ...new Set(parts.flatMap(p => (p.effect?.diagnostics ?? []).map(d => `特效：${d}`)))]) {
        const li = document.createElement('li');
        li.textContent = item;
        list.append(li);
      }
      details.append(summary, list);
      if (manifest.gaps?.length) {
        const label = document.createElement('p');
        label.textContent = '未能加载或解析的资源：';
        const issues = document.createElement('ul');
        for (const gap of manifest.gaps) {
          const li = document.createElement('li');
          li.textContent = gap.join(' · ');
          issues.append(li);
        }
        details.append(label, issues);
      }
      controls.append(details);
      await load(parts[manifest.defaultPart ?? 0]);
      if (select && !signal.aborted) select.disabled = false;
    } catch (err) { fail(err); }
    finally { if (!signal.aborted) button.disabled = false; }
  }

  button.onclick = () => open();
}
