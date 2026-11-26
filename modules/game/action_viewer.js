function assetRoot() {
  const lookup = document.querySelector('#item-lookup');
  return new URL(lookup?.dataset.assets ?? '../', document.baseURI);
}

export default class GameActionViewer extends HTMLElement {
  async connectedCallback() {
    if (this._mounted) return;
    this._mounted = true;
    const manifestPath = this.getAttribute('notist-manifest') ?? '';
    if (!manifestPath) return;

    const root = assetRoot();
    const {resolveAsset, siteAssets} = await import(new URL('assets.js', root));
    const assets = siteAssets();
    if (!resolveAsset(manifestPath) || !assets?.actionActors) return;

    const section = document.createElement('section');
    section.id = 'action-preview';
    section.dataset.manifest = manifestPath;
    section.hidden = true;
    const heading = document.createElement('h2');
    heading.textContent = '情感动作预览';
    const note = document.createElement('p');
    note.textContent = '通用角色演示，动作与特效取自游戏资源。';
    section.append(heading, note);
    this.replaceChildren(section);

    const {mountActionPreview} = await import(new URL('action-viewer.js', root));
    mountActionPreview(section, assets);
  }
}
