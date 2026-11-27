function assetRoot() {
  const lookup = document.querySelector('#item-lookup');
  return new URL(lookup?.dataset.assets ?? '../', document.baseURI);
}

export default class GameModelViewer extends HTMLElement {
  async connectedCallback() {
    if (this._mounted) return;
    this._mounted = true;
    const manifestPath = this.getAttribute('notist-manifest') ?? '';
    if (!manifestPath) return;

    const root = assetRoot();
    const {resolveAsset, siteAssets} = await import(new URL('assets.js', root));
    if (!resolveAsset(manifestPath)) return;

    const section = document.createElement('section');
    section.id = 'model-preview';
    section.dataset.manifest = manifestPath;
    section.hidden = true;
    const heading = document.createElement('h2');
    heading.textContent = '物品模型';
    section.append(heading);
    this.replaceChildren(section);

    const {mountModelPreview} = await import(new URL('model-viewer.js', root));
    mountModelPreview(section, siteAssets());
  }
}
