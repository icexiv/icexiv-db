function assetRoot() {
  const lookup = document.querySelector('#item-lookup');
  return new URL(lookup?.dataset.assets ?? '../', document.baseURI);
}

export default class GameCustomizeViewer extends HTMLElement {
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
    section.id = 'customize-preview';
    section.dataset.manifest = manifestPath;
    section.hidden = true;
    const heading = document.createElement('h2');
    heading.textContent = '外观预览';
    const note = document.createElement('p');
    note.textContent = '通用角色演示，发型与面妆取自游戏资源。';
    section.append(heading, note);
    this.replaceChildren(section);

    const {mountCustomizePreview} = await import(new URL('customize-viewer.js', root));
    mountCustomizePreview(section, assets);
  }
}
