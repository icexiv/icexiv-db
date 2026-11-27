// Emote previews: unified WebGPU scene (<icexiv-viewport>) + Ranim-style <icexiv-controls>.
import {resolveAsset} from './assets.js';
import {createObjectLoader} from './model-viewer.js';

export function mountActionPreview(host, assets) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = '查看动作';
  const status = document.createElement('span');
  status.setAttribute('role', 'status');
  host.append(button, status);
  host.hidden = false;

  const viewportUrl = new URL('./model-sdk/icexiv-viewport.js', import.meta.url);
  const controlsUrl = new URL('./model-sdk/icexiv-controls.js', import.meta.url);
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
      status.textContent = ` 无法显示动作：${err.message}`;
    };
    button.hidden = true;
    status.textContent = '';
    const actors = assets.actionActors || {};
    const races = [[1, '人族'], [2, '精灵族'], [3, '拉拉菲尔族'], [4, '猫魅族'],
      [5, '鲁加族'], [6, '敖龙族'], [7, '硌狮族']]
      .filter(([id]) => actors[`${id}-0`] || actors[`${id}-1`]);
    const defaultKey = assets.actionDefault || '6-1';
    const [defaultRace, defaultGender] = defaultKey.split('-');
    controls = document.createElement('div');
    controls.innerHTML = `<section class="preview-frame" aria-label="情感动作视窗">
      <div class="preview-head"><strong>情感动作预览</strong><div class="preview-head-tools">
      <select class="action-race" aria-label="预览种族"></select>
      <div class="action-gender" role="group" aria-label="预览性别">
      <button type="button" data-gender="0" aria-pressed="false">男</button>
      <button type="button" data-gender="1" aria-pressed="false">女</button></div>
      <div class="preview-camera-presets" role="group" aria-label="镜头预设">
      <button type="button" data-preset="full" aria-pressed="true">全身</button>
      <button type="button" data-preset="upper" aria-pressed="false">半身</button>
      <button type="button" data-preset="head" aria-pressed="false">头部</button></div>
      <button type="button" class="preview-replay">重播</button>
      <button type="button" class="preview-close" aria-label="关闭动作">关闭 <span aria-hidden="true">×</span></button>
      </div></div><div class="preview-stage"><label class="preview-progress"><span></span><progress></progress></label></div></section>`;
    const stageBox = controls.querySelector('.preview-stage');
    const meter = stageBox.querySelector('.preview-progress');
    const meterText = meter.querySelector('span');
    const meterBar = meter.querySelector('progress');
    const phases = {
      manifest: '读取动作清单', engine: '加载渲染器', 'model-files': '加载模型文件',
      'actor-files': '加载角色文件', 'action-files': '加载动作文件',
      'unpack-model': '装配模型', 'unpack-effect': '装配特效', 'first-frame': '绘制首帧',
      materials: '加载材质', geometry: '读取模型几何',
    };
    const progress = (phase, done = 0, total = 0) => {
      if (signal.aborted) return;
      meter.hidden = !phase;
      if (!phase) return;
      meterText.textContent = (phases[phase] ?? phase) + (total > 0 ? ` · ${done}/${total}` : '…');
      if (total > 0) { meterBar.max = total; meterBar.value = done; } else meterBar.removeAttribute('value');
    };
    const raceSelect = controls.querySelector('.action-race');
    const genderBox = controls.querySelector('.action-gender');
    const genderButtons = [...genderBox.querySelectorAll('button')];
    const presetButtons = [...controls.querySelectorAll('.preview-camera-presets button')];
    let genderValue = Number(defaultGender);
    const replay = controls.querySelector('.preview-replay');
    const closeBtn = controls.querySelector('.preview-close');
    for (const [id, label] of races) raceSelect.add(new Option(label, id));
    status.before(controls);
    closeBtn.onclick = () => { close(); button.focus({preventScroll: true}); };
    closeBtn.focus({preventScroll: true});

    let stage, ctrlBar, current;
    try {
      if (!navigator.gpu) throw Error('浏览器不支持 WebGPU');
      progress('manifest');
      const manifestUrl = resolveAsset(host.dataset.manifest);
      if (!manifestUrl) throw Error('动作资源未启用');
      const response = await fetch(manifestUrl, {signal});
      if (!response.ok) throw Error(`动作清单 HTTP ${response.status}`);
      const manifest = await response.json();
      const loader = createObjectLoader();
      const read = (path, sha) => loader.read(path, sha, signal);

      const actorCache = new Map();
      const actorFor = key => {
        if (!actors[key]) throw Error('此种族没有该性别');
        if (!actorCache.has(key)) {
          actorCache.set(key, fetch(resolveAsset(actors[key]), {signal}).then(r => {
            if (!r.ok) throw Error(`角色清单 HTTP ${r.status}`);
            return r.json();
          }));
        }
        return actorCache.get(key);
      };
      progress('engine');
      await Promise.all([import(viewportUrl), import(controlsUrl)]);
      signal.throwIfAborted();

      stage = document.createElement('icexiv-viewport');
      stage.addEventListener('loadprogress', ({detail}) => progress(detail.phase, detail.done, detail.total));
      stage.addEventListener('error', ({detail}) => fail(detail instanceof Error ? detail : Error(String(detail))));
      ctrlBar = document.createElement('icexiv-controls');
      ctrlBar.target = stage;
      stageBox.append(stage, ctrlBar);

      const start = async key => {
        progress('actor-files');
        const actor = await actorFor(key);
        await stage.setActorBundle(actor, read);
        await stage.playActionBundle(manifest.bundle, manifest.preview, read);
        current = key;
      };
      const gendersFor = id => [0, 1].filter(g => actors[`${id}-${g}`]);
      const syncGender = () => {
        const options = gendersFor(raceSelect.value);
        if (!options.includes(genderValue)) genderValue = options[0] ?? 0;
        for (const btn of genderButtons) {
          const value = Number(btn.dataset.gender);
          btn.setAttribute('aria-pressed', String(value === genderValue));
          btn.disabled = !options.includes(value);
        }
        genderBox.title = options.length < 2 ? '此种族只有一种性别' : '';
      };
      const pickActor = async () => {
        syncGender();
        const key = `${raceSelect.value}-${genderValue}`;
        if (key === current || signal.aborted) return;
        status.textContent = '切换角色…';
        try {
          await start(key);
          progress(null);
          status.textContent = '循环播放，可拖动视角或展开时间轴查看轨道。';
        } catch (error) {
          progress(null);
          if (!signal.aborted) status.textContent = ` 无法切换角色：${error.message}`;
        }
      };
      raceSelect.value = races.some(([id]) => String(id) === defaultRace) ? defaultRace : String(races[0]?.[0]);
      genderValue = Number(defaultGender);
      syncGender();
      await stage.openScene();
      signal.throwIfAborted();
      await stage.setCameraPreset('full');
      await start(`${raceSelect.value}-${genderValue}`);
      signal.throwIfAborted();
      progress(null);

      raceSelect.onchange = pickActor;
      for (const btn of genderButtons) {
        btn.onclick = () => {
          if (btn.disabled) return;
          genderValue = Number(btn.dataset.gender);
          pickActor();
        };
      }
      for (const btn of presetButtons) {
        btn.onclick = async () => {
          for (const b of presetButtons) b.setAttribute('aria-pressed', String(b === btn));
          await stage.setCameraPreset(btn.dataset.preset);
        };
      }
      replay.onclick = () => {
        stage.seek(0);
        stage.play();
      };
      status.textContent = '循环播放，可拖动视角或展开时间轴查看轨道。';
    } catch (err) { progress(null); fail(err); }
    finally { if (!signal.aborted) button.disabled = false; }
  }

  button.onclick = () => open();
}
