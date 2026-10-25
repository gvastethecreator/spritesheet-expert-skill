// Landing workbench. Asset files and gate lists come from docs/assets/worlds/<world>/manifest.json.
(() => {
  const WORLDS = {
    scifi: {
      blurb: 'KELP-9, a vending-machine maintenance drone, mops a flooded orbital laundromat.',
      assets: [
        { id: 'walk', title: 'KELP-9 walk cycle', lane: 'Animation', fps: 10,
          pixel: { row: 'walk-pixel-atlas.png', frames: 8, cols: 8, source: 'walk-pixel-source.png' },
          hd: { row: 'walk-hd-atlas.png', frames: 8, cols: 8, source: 'walk-hd-source.png' } },
        { id: 'props', title: 'Laundromat props', lane: 'Item atlas',
          pixel: { image: 'props-atlas.png', source: 'props-source.png' } },
        { id: 'bg', title: 'Parallax background', lane: 'Background pack',
          pixel: { image: 'bg-scroll.gif', source: 'bg-layers.png', smooth: true } },
      ],
    },
    fight: {
      blurb: 'Grandma Oyone, a pressure-point grappler, against Dock-Crane Barros in an underground arena.',
      assets: [
        { id: 'strike', title: 'Oyone palm strike', lane: 'Animation', fps: 12,
          pixel: { row: 'oyone-strike-px-row.png', frames: 6, cols: 6, source: 'oyone-strike-px-source.png' },
          hd: { row: 'oyone-strike-hd-row.png', frames: 6, cols: 6, source: 'oyone-strike-hd-source.png' } },
        { id: 'idle', title: 'Barros fighting idle', lane: 'Animation', fps: 6,
          pixel: { row: 'barros-idle-px-row.png', frames: 4, cols: 4, source: 'barros-idle-px-source.png' } },
        { id: 'spark', title: 'Hit spark', lane: 'VFX', fps: 14,
          pixel: { row: 'hit-spark-px-row.png', frames: 8, cols: 4, rows: 2, source: 'hit-spark-px-source.png' } },
        { id: 'matchup', title: 'Matchup board', lane: 'Presentation',
          pixel: { image: 'fight-matchup.gif', source: 'fight-arena-px.png' } },
      ],
    },
    dungeon: {
      blurb: 'A crypt run as a bureaucracy: a burned-out mimic accountant, a goblin union rep, and a nervous intern.',
      assets: [
        { id: 'mimic', title: 'Mimic accountant idle', lane: 'Animation', fps: 5,
          pixel: { row: 'mimic-idle-pixel-atlas.png', frames: 4, cols: 4, source: 'mimic-idle-pixel-source.png' },
          hd: { row: 'mimic-idle-hd-atlas.png', frames: 4, cols: 4, source: 'mimic-idle-hd-source.png' } },
        { id: 'intern', title: 'Intern, four directions', lane: 'Pose set', fps: 2,
          pixel: { row: 'intern-directions-atlas.png', frames: 4, cols: 4, source: 'intern-directions-source.png' } },
        { id: 'loot', title: 'Office loot', lane: 'Item atlas',
          pixel: { image: 'loot-pixel-atlas.png', source: 'loot-pixel-source.png' },
          hd: { image: 'loot-hd-atlas.png', source: 'loot-hd-source.png', smooth: true } },
        { id: 'ui', title: 'Bureaucratic UI kit', lane: 'UI kit',
          pixel: { image: 'ui-state-board.png', source: 'ui-nine-slice.png' } },
      ],
    },
  };

  const LANES = [
    { title: 'Loose items → packed atlas', world: 'dungeon', from: 'loot-hd-source.png', to: 'loot-hd-atlas.png', text: 'Items anywhere on a transparent sheet. Each one keeps its exact pixels and gets its own atlas rect.', cmd: 'run_item_atlas_workflow.py loot.png --output-dir run' },
    { title: 'Animation grid → runtime row', world: 'fight', from: 'oyone-strike-hd-source.png', to: 'oyone-strike-hd.gif', smooth: true, text: 'A compact grid drifts less than a long strip. Frames land on one baseline, at one scale, with a combat phase contract.', cmd: 'extract_sprite_row_frames.py --run-dir run' },
    { title: 'Fake pixels → real pixel art', world: 'fight', single: 'pixel-conversion-before-after.png', text: 'Models paint pixel-looking art on an irregular grid. The conversion lane puts it on an exact grid with a fixed palette and hard alpha.', cmd: 'convert_pixel_art.py convert --request conversion.json --output out' },
    { title: 'Character → pose set', world: 'dungeon', from: 'intern-directions-source.png', to: 'intern-directions-atlas.png', text: 'Four facings with one camera, one scale, and one identity. No empty slot passes.', cmd: 'validate_run.py --run-dir run --stage post-extract' },
    { title: 'Effect → VFX row', world: 'fight', from: 'hit-spark-px-source.png', to: 'hit-spark-px.gif', text: 'A fixed emitter with build-up, peak, and decay. The contract fails flat or static effects.', cmd: 'check_animation_contracts.py --run-dir run' },
    { title: 'Layers → parallax pack', world: 'scifi', from: 'bg-layers.png', to: 'bg-scroll.gif', smooth: true, text: 'Each layer is checked for horizontal repeat, then rendered as a composite and a scroll proof.', cmd: 'validate_background_pack.py --pack pack.json' },
    { title: 'UI pieces → raster kit', world: 'dungeon', from: 'ui-state-board.png', to: 'ui-nine-slice.png', fromLabel: 'States on four mattes', toLabel: 'Nine-slice stretch', text: 'Every state and density on four backgrounds, and proof that panels stretch with intact corners.', cmd: 'validate_ui_kit.py --kit ui-kit.json' },
    { title: 'Tiles → repeat proof', world: 'dungeon', single: 'tiles-repeat-proof.png', text: 'Floor tiles are measured at their edges and shown in a 3×3 repeat before they reach a map.', cmd: 'check_asset_slots.py --run-dir run' },
    { title: 'Props → pixel item atlas', world: 'scifi', from: 'props-source.png', to: 'props-atlas.png', text: 'The same item lane on converted pixel art: 12 of 12 items, zero unowned pixels.', cmd: 'validate_item_delivery.py --run-dir run' },
    { title: 'Assets → labeled board', world: 'fight', single: 'fight-matchup.gif', text: 'Presentation boards are composed from validated runtime frames and labeled as boards, never as gameplay captures.', cmd: 'prepare_presentation.py --presentation board.json' },
  ];

  const TOOLS = [
    { file: 'workbench.png', name: 'Preview workbench', text: 'Play, step, and scrub every state. Each QA report shows its pass or fail chip.' },
    { file: 'item-playground.png', name: 'Item playground', text: 'Approve or reject every atlas item with notes, then export the review file.' },
    { file: 'studio.png', name: 'Studio', text: 'Launch workflows, review atlases, and keep portable workspaces with evidence.' },
    { file: 'motion-workbench.png', name: 'Motion workbench', text: 'Light-table frame alignment with onion skin, guides, and correction packets.' },
  ];

  const $ = (id) => document.getElementById(id);
  const manifests = {};
  const state = { world: 'fight', asset: null, style: 'pixel', view: 'runtime', bg: 'checker', frame: 0, playing: false, timer: 0 };
  const canvas = $('sprite');
  const ctx = canvas.getContext('2d');
  const sourceImg = $('source-img');
  const images = new Map();
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const worldPath = (world, file) => `assets/worlds/${world}/${file}`;
  const loadImage = (src) => {
    if (!images.has(src)) {
      images.set(src, new Promise((resolve, reject) => {
        const img = new Image();
        img.onload = () => resolve(img);
        img.onerror = () => reject(new Error(src));
        img.src = src;
      }));
    }
    return images.get(src);
  };
  const entries = (world) => {
    const data = manifests[world];
    if (!data) return [];
    return Array.isArray(data) ? data : data.files || data.items || [];
  };
  const entry = (world, file) => entries(world).find((item) => item.file === file) || {};
  const gatesOf = (item) => item.gates || item.gates_passed || [];

  function setPressed(selector, attr, value) {
    document.querySelectorAll(selector).forEach((el) => el.setAttribute('aria-pressed', String(el.dataset[attr] === value)));
  }

  function current() {
    const asset = WORLDS[state.world].assets.find((a) => a.id === state.asset) || WORLDS[state.world].assets[0];
    const variant = asset[state.style] || asset.pixel;
    return { asset, variant };
  }

  function renderList() {
    const list = $('asset-list');
    list.replaceChildren(...WORLDS[state.world].assets.map((asset) => {
      const li = document.createElement('li');
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'list-row';
      btn.dataset.asset = asset.id;
      btn.setAttribute('aria-pressed', String(asset.id === state.asset));
      const name = document.createElement('span');
      name.textContent = asset.title;
      const meta = document.createElement('span');
      meta.className = 'meta';
      const v = asset.pixel;
      meta.textContent = `${asset.lane}${v.frames ? ` · ${v.frames} fr` : ''}${asset.hd ? ' · pixel + HD' : ''}`;
      btn.append(name, meta);
      btn.addEventListener('click', () => selectAsset(asset.id));
      li.append(btn);
      return li;
    }));
  }

  function renderRail() {
    const { asset, variant } = current();
    const file = variant.row || variant.image;
    const info = entry(state.world, file);
    $('asset-title').textContent = asset.title;
    $('asset-caption').textContent = info.caption || '';
    const facts = [['Lane', asset.lane], ['Style', state.style === 'hd' && asset.hd ? 'HD' : 'Pixel']];
    if (variant.frames) facts.push(['Frames', String(variant.frames)], ['FPS', String(asset.fps)]);
    facts.push(['File', file]);
    $('asset-facts').replaceChildren(...facts.flatMap(([k, v]) => {
      const dt = document.createElement('dt'); dt.textContent = k;
      const dd = document.createElement('dd'); dd.textContent = v;
      return [dt, dd];
    }));
    const gates = gatesOf(info);
    $('asset-gates').replaceChildren(...(gates.length ? gates : ['Manifest not loaded']).map((gate) => {
      const li = document.createElement('li');
      li.className = 'list-row';
      const name = document.createElement('span'); name.textContent = gate;
      const chip = document.createElement('span'); chip.className = 'chip';
      chip.dataset.status = gates.length ? 'pass' : 'missing';
      chip.textContent = gates.length ? 'pass' : 'n/a';
      li.append(name, chip);
      return li;
    }));
    const styleButtons = document.querySelectorAll('[data-style]');
    styleButtons.forEach((btn) => { btn.disabled = btn.dataset.style === 'hd' && !asset.hd; });
    setPressed('[data-style]', 'style', asset.hd ? state.style : 'pixel');
  }

  async function draw() {
    const { asset, variant } = current();
    const showSource = state.view === 'source';
    const status = $('bench-status');
    if (showSource || !variant.row) {
      stop();
      canvas.hidden = true;
      sourceImg.hidden = false;
      const file = showSource ? variant.source : variant.image;
      sourceImg.src = worldPath(state.world, file);
      sourceImg.alt = `${asset.title}: ${showSource ? 'provider output' : 'delivered file'}`;
      sourceImg.style.imageRendering = variant.smooth || showSource ? 'auto' : 'pixelated';
      setTransport(1);
      status.textContent = showSource ? 'provider output, before the pipeline' : 'delivered file';
      return;
    }
    canvas.hidden = false;
    sourceImg.hidden = true;
    const img = await loadImage(worldPath(state.world, variant.row)).catch(() => null);
    if (!img) { status.textContent = 'could not load asset'; return; }
    const cols = variant.cols;
    const rows = variant.rows || 1;
    const cw = img.naturalWidth / cols;
    const ch = img.naturalHeight / rows;
    const box = $('stage').parentElement;
    const zoom = Math.max(1, Math.floor(Math.min((box.clientWidth - 48) / cw, 380 / ch)));
    canvas.width = cw;
    canvas.height = ch;
    canvas.style.width = `${cw * zoom}px`;
    canvas.style.height = 'auto';
    const f = state.frame % variant.frames;
    ctx.clearRect(0, 0, cw, ch);
    ctx.imageSmoothingEnabled = state.style === 'hd' && !!asset.hd;
    canvas.dataset.sampling = ctx.imageSmoothingEnabled ? 'linear' : 'nearest';
    ctx.drawImage(img, (f % cols) * cw, Math.floor(f / cols) * ch, cw, ch, 0, 0, cw, ch);
    setTransport(variant.frames);
    status.textContent = `${asset.title} · frame ${f + 1} · ${zoom}× ${canvas.dataset.sampling}`;
  }

  function setTransport(frames) {
    const scrub = $('scrub');
    scrub.max = String(Math.max(0, frames - 1));
    scrub.value = String(state.frame % frames);
    scrub.disabled = frames < 2;
    ['prev', 'next', 'play'].forEach((id) => { $(id).disabled = frames < 2; });
    $('readout').textContent = `${(state.frame % frames) + 1} / ${frames}`;
    $('play').textContent = state.playing ? 'Pause' : 'Play';
    $('play').setAttribute('aria-label', state.playing ? 'Pause animation' : 'Play animation');
  }

  function stop() { state.playing = false; clearInterval(state.timer); }
  function play() {
    const { asset, variant } = current();
    if (!variant.frames || state.view === 'source') return;
    stop();
    state.playing = true;
    state.timer = setInterval(() => { state.frame = (state.frame + 1) % variant.frames; draw(); }, 1000 / asset.fps);
    draw();
  }
  function step(delta) {
    const { variant } = current();
    if (!variant.frames) return;
    stop();
    state.frame = (state.frame + delta + variant.frames) % variant.frames;
    draw();
  }

  function selectAsset(id) {
    stop();
    state.asset = id;
    state.frame = 0;
    const { asset } = current();
    if (!asset.hd) state.style = 'pixel';
    setPressed('[data-asset]', 'asset', id);
    renderRail();
    draw().then(() => { if (!reducedMotion && current().variant.frames > 1) play(); });
  }

  function selectWorld(world) {
    state.world = world;
    setPressed('[data-world]', 'world', world);
    $('world-blurb').textContent = WORLDS[world].blurb;
    state.asset = WORLDS[world].assets[0].id;
    renderList();
    selectAsset(state.asset);
  }

  function setBackground(bg) {
    state.bg = bg;
    $('stage').dataset.background = bg;
    setPressed('[data-bg]', 'bg', bg);
  }

  function figure(world, file, label, smooth) {
    const fig = document.createElement('figure');
    const shot = document.createElement('div');
    shot.className = 'shot';
    const img = document.createElement('img');
    img.src = worldPath(world, file);
    img.loading = 'lazy';
    img.alt = entry(world, file).caption || label;
    if (!smooth) img.className = 'pixel';
    shot.append(img);
    const cap = document.createElement('figcaption');
    cap.textContent = label;
    fig.append(shot, cap);
    return fig;
  }

  function renderLanes() {
    $('lane-grid').replaceChildren(...LANES.map((lane) => {
      const card = document.createElement('article');
      card.className = 'lane';
      const head = document.createElement('header');
      head.className = 'lane-head';
      const h = document.createElement('h3'); h.textContent = lane.title;
      const meta = document.createElement('span'); meta.className = 'meta'; meta.textContent = { scifi: 'Sci-fi', fight: 'Fighting', dungeon: 'Dungeon' }[lane.world];
      head.append(h, meta);
      const pair = document.createElement('div');
      pair.className = lane.single ? 'lane-pair single' : 'lane-pair';
      if (lane.single) pair.append(figure(lane.world, lane.single, 'Proof', lane.smooth));
      else pair.append(figure(lane.world, lane.from, lane.fromLabel || 'Provider', true), figure(lane.world, lane.to, lane.toLabel || 'Delivered', lane.smooth));
      const foot = document.createElement('div');
      foot.className = 'lane-foot';
      const p = document.createElement('p'); p.textContent = lane.text;
      const chips = document.createElement('div'); chips.className = 'chips';
      gatesOf(entry(lane.world, lane.single || lane.to)).forEach((gate) => {
        const chip = document.createElement('span'); chip.className = 'chip'; chip.dataset.status = 'pass'; chip.textContent = gate;
        chips.append(chip);
      });
      const code = document.createElement('code'); code.textContent = lane.cmd;
      foot.append(p, chips, code);
      card.append(head, pair, foot);
      return card;
    }));
  }

  function renderTools() {
    $('tool-grid').replaceChildren(...TOOLS.map((tool) => {
      const fig = document.createElement('figure');
      fig.className = 'tool-card';
      const img = document.createElement('img');
      img.src = `assets/tools/${tool.file}`;
      img.loading = 'lazy';
      img.alt = `${tool.name} screenshot`;
      const cap = document.createElement('figcaption');
      const strong = document.createElement('strong'); strong.textContent = tool.name;
      const span = document.createElement('span'); span.textContent = tool.text;
      cap.append(strong, span);
      fig.append(img, cap);
      return fig;
    }));
  }

  document.querySelectorAll('[data-world]').forEach((b) => b.addEventListener('click', () => selectWorld(b.dataset.world)));
  document.querySelectorAll('[data-bg]').forEach((b) => b.addEventListener('click', () => setBackground(b.dataset.bg)));
  document.querySelectorAll('[data-style]').forEach((b) => b.addEventListener('click', () => {
    state.style = b.dataset.style; setPressed('[data-style]', 'style', state.style); renderRail(); draw();
  }));
  document.querySelectorAll('[data-view]').forEach((b) => b.addEventListener('click', () => {
    state.view = b.dataset.view; setPressed('[data-view]', 'view', state.view); draw();
  }));
  $('play').addEventListener('click', () => (state.playing ? (stop(), draw()) : play()));
  $('prev').addEventListener('click', () => step(-1));
  $('next').addEventListener('click', () => step(1));
  $('scrub').addEventListener('input', (e) => { stop(); state.frame = Number(e.target.value); draw(); });
  $('stage').addEventListener('keydown', (e) => {
    if (e.key === ' ') { e.preventDefault(); state.playing ? (stop(), draw()) : play(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); step(1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); step(-1); }
    else if (e.key.toLowerCase() === 'b') {
      const order = ['checker', 'black', 'gray', 'white'];
      setBackground(order[(order.indexOf(state.bg) + 1) % order.length]);
    }
  });
  addEventListener('resize', () => draw());
  document.querySelectorAll('[data-copy]').forEach((b) => b.addEventListener('click', async () => {
    try { await navigator.clipboard.writeText($(b.dataset.copy).textContent); b.textContent = 'Copied'; }
    catch (_error) { b.textContent = 'Select and copy'; }
    setTimeout(() => { b.textContent = 'Copy'; }, 1600);
  }));

  Promise.all(Object.keys(WORLDS).map((world) => fetch(worldPath(world, 'manifest.json'))
    .then((r) => (r.ok ? r.json() : null)).catch(() => null).then((data) => { manifests[world] = data; })))
    .then(() => { renderLanes(); renderRail(); });
  renderTools();
  selectWorld(state.world);
})();
