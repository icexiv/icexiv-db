// Single runtime asset resolver: maps per-kind game-assets bases to URLs.
// Expects site-assets JSON with per-kind bases: { icons, portraits, orchestrion, models }.
let cached;

function defaultRoot() {
  return globalThis.location?.href || 'http://localhost/';
}

export function siteAssets() {
  if (cached !== undefined) return cached;
  const node = document.querySelector('#site-assets');
  cached = node ? JSON.parse(node.textContent) : null;
  return cached;
}

export function resolveAsset(logicalPath, assetRoot) {
  if (!logicalPath) return '';
  if (/^https?:\/\//.test(logicalPath)) return logicalPath;
  const root = assetRoot || defaultRoot();
  if (logicalPath.startsWith('/')) {
    return new URL(logicalPath.replace(/^\/+/, ''), root).href;
  }
  const assets = siteAssets();
  if (!assets) return '';
  const slash = logicalPath.indexOf('/');
  if (slash <= 0) return '';
  const kind = logicalPath.slice(0, slash);
  const rest = logicalPath.slice(slash + 1);
  const base = assets[kind];
  if (!base) return '';
  if (base.startsWith('/')) {
    return new URL(`${base.replace(/^\/+/, '')}/${rest}`, root).href;
  }
  return `${base}/${rest}`;
}

export function iconUrl(icon, assetRoot) {
  const root = assetRoot || defaultRoot();
  const placeholder = new URL('icon-placeholder.svg', root).href;
  if (!icon) return placeholder;
  if (typeof icon === 'string') return new URL(icon.replace(/^\//, ''), root).href;
  return resolveAsset(`icons/${icon}.webp`, root) || placeholder;
}

export function portraitUrl(image, assetRoot) {
  const root = assetRoot || defaultRoot();
  if (!image) return '';
  if (typeof image === 'string') return new URL(image.replace(/^\//, ''), root).href;
  return resolveAsset(`portraits/${image}.webp`, root);
}
