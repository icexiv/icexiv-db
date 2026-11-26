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

export function mountModelPreview(host) {
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
      let stage, playing = false, partRequest;
      const replaceStage = () => {
        stage?.remove();
        stage = document.createElement('icexiv-equipment-canvas');
        stage.setAttribute('framed', '');
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
