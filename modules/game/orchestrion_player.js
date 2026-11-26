function assetRoot() {
  const lookup = document.querySelector('#item-lookup');
  return new URL(lookup?.dataset.assets ?? '../', document.baseURI);
}

export default class GameOrchestrionPlayer extends HTMLElement {
  async connectedCallback() {
    if (this._mounted) return;
    this._mounted = true;
    const logicalPath = this.getAttribute('notist-audio') ?? '';
    if (!logicalPath) return;

    const root = assetRoot();
    const {resolveAsset} = await import(new URL('assets.js', root));
    const url = resolveAsset(logicalPath);
    if (!url) return;

    const section = document.createElement('section');
    section.id = 'orchestrion-preview';
    section.dataset.audio = logicalPath;

    const heading = document.createElement('h2');
    heading.textContent = '乐谱播放';

    const player = document.createElement('audio');
    player.controls = true;
    player.preload = 'none';
    player.id = 'orchestrion-player';
    player.setAttribute('aria-label', '播放本页乐谱');
    player.src = url;

    const error = document.createElement('p');
    error.id = 'orchestrion-error';
    error.setAttribute('role', 'status');
    error.hidden = true;
    error.textContent = '未能加载音频，请检查网络后重试。';
    player.addEventListener('error', () => { error.hidden = false; });

    section.append(heading, player, error);
    this.replaceChildren(section);
  }
}
