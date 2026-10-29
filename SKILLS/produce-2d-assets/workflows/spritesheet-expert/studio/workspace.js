import {request} from './studio-client.js';

const $ = id => document.getElementById(`workspace-${id}`);
let catalogue;
const action = fn => async event => {
  try { await fn(event); } catch (error) { $('status').textContent = error.message; }
};
function text(tag, value, className = '') {
  const node = document.createElement(tag); node.textContent = value; node.className = className; return node;
}
function button(label, fn) {
  const node = text('button', label, 'secondary-button'); node.type = 'button';
  node.addEventListener('click', action(fn)); return node;
}

function render() {
  if (!catalogue) return;
  const search = $('search').value.trim().toLowerCase(), collection = $('collection').value;
  const runs = catalogue.runs.filter(run => (!run.archived || $('archived').checked)
    && (!collection || run.collection === collection)
    && `${run.name} ${run.id} ${run.collection || ''}`.toLowerCase().includes(search));
  $('runs').replaceChildren(...runs.map(run => {
    const card = text('article', '', 'panel workspace-run'); card.dataset.runId = run.id;
    card.append(text('p', run.collection || 'Unsorted', 'eyebrow'), text('h3', run.name),
      text('p', `${run.lane} · ${run.status}${run.archived ? ' · archived' : ''}`, 'muted'),
      text('code', run.path || run.id), text('p', run.error || (run.items === undefined ? 'Not processed yet.'
        : run.lane !== 'static-items' ? `${run.items} declared frames · copied snapshot, not production approval`
        : `${run.items} sprites · ${run.unreviewed} awaiting review · ${run.pendingPixels} pending pixels`)));
    const actions = text('div', '', 'button-row');
    if (run.lane === 'static-items') actions.append(button('Open run', () => window.dispatchEvent(new CustomEvent('studio:open-run', {detail: run.id}))));
    else if (!run.error) {
      actions.append(button('Save snapshot ZIP', async () => {
        await request(`/api/runs/${run.id}/archive-snapshot`, {}); await refresh();
      }), button('Copy final-check arguments', async () => {
        await navigator.clipboard.writeText(JSON.stringify({lane: run.lane, argv: run.finalCheckArgv}, null, 2));
        $('status').textContent = 'Typed arguments copied. A copied snapshot is not approval.';
      }));
      const proofs = document.createElement('details'); proofs.append(text('summary', 'Inspect saved evidence'));
      const picker = document.createElement('select'); picker.setAttribute('aria-label', `Evidence for ${run.name}`);
      picker.append(new Option('Select evidence', ''), ...(run.previews || []).map(path => new Option(path, path)));
      const frame = document.createElement('iframe'); frame.title = `Saved evidence for ${run.name}`;
      frame.sandbox = 'allow-scripts'; frame.style.cssText = 'width:100%;height:480px;border:0'; frame.hidden = true;
      picker.addEventListener('change', () => {
        frame.hidden = !picker.value; frame.src = picker.value ? `/api/runs/${run.id}/files/${picker.value}` : 'about:blank';
      });
      proofs.append(picker, frame); card.append(proofs);
    }
    actions.append(button(run.archived ? 'Restore' : 'Archive', async () => {
        await request(`/api/runs/${run.id}/organize`, {archived: !run.archived}); await refresh(); changed();
      }));
    const details = document.createElement('details'); details.append(text('summary', 'Name and collection'));
    const form = text('form', '', 'workspace-organize');
    const name = document.createElement('input'), group = document.createElement('input');
    name.value = run.name; name.required = true; name.maxLength = 160; name.setAttribute('aria-label', 'Run name');
    group.value = run.collection || ''; group.maxLength = 160; group.setAttribute('aria-label', 'Collection');
    const save = text('button', 'Save', 'secondary-button'); save.type = 'submit'; form.append(name, group, save);
    form.addEventListener('submit', action(async event => {
      event.preventDefault(); await request(`/api/runs/${run.id}/organize`, {name: name.value, collection: group.value});
      await refresh(); changed();
    }));
    details.append(form); card.append(actions, details); return card;
  }));
  if (!runs.length) $('runs').append(text('p', 'No runs in this view. Import a sheet or copy an existing run below.', 'muted'));
  $('exports').replaceChildren(...catalogue.exports.map(record => {
    const row = text('div', '', 'workspace-export');
    if (record.error) { row.append(text('p', record.error)); return row; }
    const run = catalogue.runs.find(item => item.id === record.runId);
    const link = text('a', `${run?.name || record.runId} · ${record.kind === 'workspace-snapshot' ? 'Snapshot' : record.draft ? 'Draft' : 'Delivery'}`);
    link.href = `/api/exports/${record.id}`; link.download = '';
    row.append(link, text('code', record.path), text('small', `${new Date(record.createdAt).toLocaleString()} · ${(record.bytes / 1048576).toFixed(1)} MiB`, 'muted'));
    return row;
  }));
  if (!catalogue.exports.length) $('exports').append(text('p', 'Exports are saved here when you export from Process a sheet.', 'muted'));
}
function changed() { window.dispatchEvent(new Event('studio:runs-changed')); }
async function refresh() {
  catalogue = await request('/api/workspace');
  $('name').textContent = catalogue.name; $('path').textContent = catalogue.root;
  $('identity').textContent = `Workspace ${catalogue.id}`; $('badge').textContent = catalogue.name;
  const selected = $('collection').value;
  $('collection').replaceChildren(new Option('All collections', ''), ...catalogue.collections.map(value => new Option(value, value)));
  $('collection').value = catalogue.collections.includes(selected) ? selected : ''; render();
}
for (const id of ['search', 'collection', 'archived']) $(id).addEventListener('input', render);
$('refresh').addEventListener('click', action(refresh));
window.addEventListener('studio:workspace-changed', action(refresh));
for (const kind of ['create', 'open']) $(kind + '-form').addEventListener('submit', action(async event => {
  event.preventDefault();
  if (!window.dispatchEvent(new Event('studio:before-workspace-change', {cancelable: true})))
    throw new Error('Save or clear the current Atlas Lab work and apply or undo mask strokes before switching workspaces.');
  await request(`/api/workspace/${kind}`, {path: $(kind + '-path').value, ...(kind === 'create' ? {name: $('create-name').value} : {})});
  location.hash = 'workspaces'; location.reload();
}));
$('adopt-form').addEventListener('submit', action(async event => {
  event.preventDefault(); const submit = event.submitter; submit.disabled = true;
  $('status').textContent = 'Copying the run and checking its evidence…';
  try {
    await request('/api/workspace/adopt', {path: $('adopt-path').value, name: $('adopt-name').value, collection: $('adopt-collection').value,
      ...($('adopt-lane').value ? {lane: $('adopt-lane').value} : {})});
    await refresh(); changed(); $('status').textContent = 'Run copied. Its original files are unchanged.';
  } finally { submit.disabled = false; }
}));
$('copy').addEventListener('click', action(async () => {
  const {root, ...portable} = await request('/api/workspace');
  for (const run of portable.runs || []) {
    delete run.finalCheckArgv;
    run.finalCheck = {lane: run.lane || 'static-items', runPath: run.path, command: 'check_workflow.py'};
  }
  await navigator.clipboard.writeText(`Open this Spritesheet Expert workspace. All artifact paths below are relative to its folder. Use the active client's tools, model and permissions. Prepared jobs are not execution permission; automatic results are not human approval. Preserve originals and current review heads.\n\n${JSON.stringify(portable, null, 2)}`);
  $('status').textContent = 'Workspace context copied. Tell the agent where you opened this folder.';
}));
await action(async () => { await refresh(); $('status').textContent = 'Saved on disk. Archive keeps all files.'; })();
