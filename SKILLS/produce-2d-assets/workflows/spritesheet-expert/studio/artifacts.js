// Shared exact artifact identities. File names and suffixes are not identities.
export const MAX_FILE_BYTES = 256 * 1024 * 1024;
export const hashFile = async file => {
  if (!file || file.size > MAX_FILE_BYTES) throw new Error('Missing or oversized artifact');
  return [...new Uint8Array(await crypto.subtle.digest('SHA-256', await file.arrayBuffer()))]
    .map(value => value.toString(16).padStart(2, '0')).join('');
};
export function safeRelative(relative) {
  return typeof relative === 'string' && relative.length > 0 && !relative.startsWith('/') &&
    !/[\\:]/.test(relative) && !relative.split('/').some(part => !part || part === '.' || part === '..');
}
export function exactFile(files, relative, root = '') {
  if (!safeRelative(relative)) throw new Error(`Unsafe artifact path: ${relative}`);
  const file = files.get(root + relative);
  if (!file) throw new Error(`Missing exact artifact: ${root + relative}`);
  if (file.size > MAX_FILE_BYTES) throw new Error(`Artifact exceeds byte budget: ${relative}`);
  return file;
}
export function indexFiles(fileList) {
  const files = new Map();
  for (const file of fileList) {
    const path = file.webkitRelativePath || file.name;
    if (!safeRelative(path) || files.has(path)) throw new Error(`Duplicate or unsafe file path: ${path}`);
    files.set(path, file);
  }
  return files;
}
export async function verifyManifestFiles(manifestFile, manifest, files) {
  const expected = await hashFile(manifestFile), matches = [];
  for (const [path, file] of files) {
    if (file.name === manifestFile.name && await hashFile(file) === expected) matches.push(path);
  }
  if (matches.length !== 1) throw new Error('Select one run folder containing the exact manifest; duplicate manifests are ambiguous');
  const root = matches[0].slice(0, matches[0].lastIndexOf('/') + 1), verified = new Map();
  const pages = manifest.pages || [manifest.atlas];
  const needed = [...pages.map(page => [page.path, page.sha256]),
    [manifest.evidence.sourceRgba, manifest.evidence.sourceRgbaSha256],
    ...manifest.items.map(item => [item.artifacts.rgba, item.artifacts.sha256])];
  for (const [relative, digest] of needed) {
    const file = exactFile(files, relative, root);
    if (!/^[a-f0-9]{64}$/.test(digest) || await hashFile(file) !== digest) throw new Error(`SHA-256 mismatch: ${relative}`);
    verified.set(relative, file);
  }
  return {root, verified, manifestSha256: expected};
}
