// RE9 Save Manager — frontend logic

const API = '';  // same origin
let selectedSave = null;
let currentEngine = 're_engine';
let currentMode = 'pc2ps5';
let garlicPendingFiles = [];

// ── boot ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', async () => {
  await loadConfig();
  setupDrag();
});

async function loadConfig() {
  try {
    const cfg = await get('/api/config');
    const d = cfg.defaults;
    setVal('convSrcId', d.steam_id);
    setVal('convTgtId', d.ps5_id);
    setVal('inspSrcId', d.steam_id);
    setVal('mjNewId',   d.ps5_id);
    setVal('mjOldId',   d.steam_id);

    dot('convDot', cfg.conv_available ? 'ok' : 'err');
    dot('mjDot',   cfg.mj_available   ? 'ok' : 'warn');

    // fill game profile dropdown
    const sel = document.getElementById('mjGameSelect');
    if (sel && cfg.profiles && cfg.profiles.length > 0) {
      sel.innerHTML = cfg.profiles.map(p =>
        `<option value="${p.path}">${p.name}</option>`
      ).join('');
      // auto-select RE9 Requiem (non-Epic, non-Demo)
      const re9 = cfg.profiles.find(p =>
        p.name.includes('Resident Evil 9 Requiem') &&
        !p.name.includes('EPIC') &&
        !p.name.includes('Demo')
      );
      if (re9) sel.value = re9.path;
    }

    log('info', `convert_re9_ps5: ${cfg.conv_available ? '✓' : '✗ NOT FOUND'}`);
    log('info', `MandarinJuice:   ${cfg.mj_available   ? '✓' : '✗ NOT FOUND (set MJ_BIN)'}`);
    log('info', `Profiles loaded: ${(cfg.profiles||[]).length}`);
  } catch (e) {
    log('err', 'Could not load config: ' + e);
  }
}

// ── navigation ─────────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tool-panel').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  document.querySelector(`[data-tab="${name}"]`).classList.add('active');
}

// ── sidebar scan ───────────────────────────────────────────────────────────
async function scanDir() {
  const dir = val('scanDir').trim();
  if (!dir) return;
  log('head', `Scanning: ${dir}`);
  try {
    const res = await get(`/api/scan?dir=${encodeURIComponent(dir)}`);
    renderSaveList(res.saves || []);
    log('ok', `Found ${res.saves?.length || 0} saves`);
  } catch (e) {
    log('err', 'Scan failed: ' + e);
  }
}

function renderSaveList(saves) {
  const el = document.getElementById('saveList');
  if (!saves.length) {
    el.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px">No saves found</div>';
    return;
  }
  el.innerHTML = saves.map((s, i) => `
    <div class="save-item" onclick="selectSave(${i})" id="si-${i}">
      <div class="name">${esc(s.label)}
        <span class="engine-tag ${s.engine === 're_engine' ? 're' : s.engine === 'unreal_engine' ? 'ue' : 'unk'}">
          ${s.engine === 're_engine' ? 'RE' : s.engine === 'unreal_engine' ? 'UE' : '?'}
        </span>
      </div>
      <div class="meta">${esc(s.name)} · ${esc(s.size_str)} · ${esc(s.mtime_str)}</div>
    </div>
  `).join('');
  el._saves = saves;
}

function selectSave(idx) {
  const saves = document.getElementById('saveList')._saves;
  if (!saves) return;
  selectedSave = saves[idx];
  _lastDetect = null;  // clear previous detect result
  document.querySelectorAll('.save-item').forEach((el, i) =>
    el.classList.toggle('selected', i === idx));

  // auto-detect engine
  if (selectedSave.engine === 'unreal_engine') setEngine('unreal_engine');
  else setEngine('re_engine');

  // fill selected-file boxes
  const box = `<div>
    <div class="fname">${esc(selectedSave.name)}</div>
    <div class="fmeta">${esc(selectedSave.size_str)} · ${esc(selectedSave.mtime_str)} · ${esc(selectedSave.path)}</div>
  </div>`;
  document.getElementById('convSelectedBox').innerHTML = box;
  document.getElementById('inspSelectedBox').innerHTML = box;
  setVal('inspFilePath', selectedSave.path);

  // hide previous detect banner and auto-trigger detection for RE Engine saves
  const banner = document.getElementById('detectBanner');
  if (banner) banner.style.display = 'none';
  if (selectedSave.engine !== 'unreal_engine') {
    // small delay so the UI updates first
    setTimeout(() => runAutoDetect(), 100);
  }
}

// ── engine / mode toggles ──────────────────────────────────────────────────
function setEngine(engine, btn) {
  currentEngine = engine;
  document.querySelectorAll('[data-engine]').forEach(b =>
    b.classList.toggle('active', b.dataset.engine === engine));
  document.getElementById('reFields').style.display  = engine === 're_engine'     ? '' : 'none';
  document.getElementById('ueFields').style.display  = engine === 'unreal_engine' ? '' : 'none';
}

function setMode(mode, btn) {
  currentMode = mode;
  document.querySelectorAll('[data-mode]').forEach(b =>
    b.classList.toggle('active', b.dataset.mode === mode));

  if (mode === 'pc2ps5') {
    // source = steam, target = ps5
    const src = val('convSrcId'), tgt = val('convTgtId');
    // swap if they look reversed
  } else {
    // source = ps5, target = steam
  }
}

function onRegionChange() {
  const v = val('convRegion');
  document.getElementById('customRegionRow').style.display = v === 'custom' ? '' : 'none';
}

// ── auto-detect ────────────────────────────────────────────────────────────
let _lastDetect = null;  // cached result for applyDetectedSettings()

async function runAutoDetect() {
  if (!selectedSave) { alert('Select a save file first'); return; }
  const btn = document.getElementById('detectBtn');
  const spn = document.getElementById('detectSpinner');
  const banner = document.getElementById('detectBanner');
  const info  = document.getElementById('detectInfo');
  btn.disabled = true; spn.classList.add('active');
  info.innerHTML = '⏳ Detecting…';
  banner.style.display = '';

  log('head', `Auto-detect: ${selectedSave.name}`);

  try {
    const res = await post('/api/autodetect', {
      file_path: selectedSave.path,
      steam_id:  val('convSrcId') || undefined,
      ps5_id:    val('convTgtId') || undefined,
    });

    if (res.success) {
      _lastDetect = res;
      const plat  = res.platform === 'PC' ? '🖥️ PC/Steam' : '🎮 PS5';
      const rHex  = res.region_hash_hex || '—';
      const rLbl  = res.region_hash_label || '—';
      const vHex  = res.app_version_hex  || '—';
      const vLbl  = res.app_version_label || '—';
      const patch = res.needs_region_patch  ? '→ <b>needs region patch</b>' : '→ region already matches target';
      const vPatch= res.needs_version_patch ? ' + version patch' : '';
      const sz    = res.decrypted_size ? ` · ${(res.decrypted_size/1024).toFixed(0)} KB` : '';
      const flags = res.flags ? ` · ${res.flags}` : '';

      const sugMode = res.suggested_mode === 'pc2ps5' ? 'PC → PS5' : 'PS5 → PC';

      info.innerHTML =
        `<b style="font-size:14px">${plat}</b>${sz}${flags}<br>` +
        `<b>_MainRegionHash</b>: ${rHex} = <i>${rLbl}</i><br>` +
        `<b>_ApplicationVersion</b>: ${vHex} = <i>${vLbl}</i><br>` +
        `<span style="color:var(--accent)">${patch}${vPatch} · suggested: ${sugMode}</span>`;

      banner.style.borderColor = res.needs_region_patch
        ? 'rgba(255,180,0,0.4)' : 'rgba(90,195,90,0.3)';
      banner.style.background  = res.needs_region_patch
        ? 'rgba(255,180,0,0.07)' : 'rgba(90,195,90,0.08)';

      log('ok', `Detected: ${plat} · ${rHex} (${rLbl}) · ${vHex}`);
    } else {
      _lastDetect = null;
      info.innerHTML = `<span style="color:var(--err)">✗ ${res.error || 'Detection failed'}</span>`;
      banner.style.borderColor = 'rgba(255,80,80,0.3)';
      banner.style.background  = 'rgba(255,80,80,0.07)';
      log('err', res.error || 'Detection failed');
      if (res.log) res.log.forEach(l => log('info', l));
    }
  } catch (e) {
    _lastDetect = null;
    info.innerHTML = `<span style="color:var(--err)">✗ ${e}</span>`;
    log('err', String(e));
  }
  btn.disabled = false; spn.classList.remove('active');
}

function applyDetectedSettings() {
  if (!_lastDetect) return;
  const r = _lastDetect;

  // Set mode
  const mode = r.suggested_mode || (r.platform === 'PC' ? 'pc2ps5' : 'ps52pc');
  document.querySelectorAll('[data-mode]').forEach(b => {
    b.classList.toggle('active', b.dataset.mode === mode);
  });
  currentMode = mode;

  // Set IDs
  if (r.platform === 'PC') {
    setVal('convSrcId', r.source_id);
    if (r.suggested_target_id) setVal('convTgtId', r.suggested_target_id);
  } else {
    setVal('convSrcId', r.source_id);
    if (r.suggested_target_id) setVal('convTgtId', r.suggested_target_id);
  }

  // Set region hash
  const regionTarget = String(r.suggested_region || '');
  const regionSel = document.getElementById('convRegion');
  let found = false;
  for (const opt of regionSel.options) {
    if (opt.value === regionTarget) { opt.selected = true; found = true; break; }
  }
  if (!found) {
    // set custom
    for (const opt of regionSel.options) {
      if (opt.value === 'custom') { opt.selected = true; break; }
    }
    setVal('convRegionCustom', regionTarget);
    document.getElementById('customRegionRow').style.display = '';
  }

  // Set version
  const verTarget = String(r.suggested_version || '');
  const verSel = document.getElementById('convVer');
  for (const opt of verSel.options) {
    if (opt.value === verTarget) { opt.selected = true; break; }
  }

  log('ok', `Auto-filled: mode=${mode}, region=${regionTarget}, version=${verTarget}`);

  // Flash the fields card
  const card = document.getElementById('reFields');
  card.style.transition = 'box-shadow 0.4s';
  card.style.boxShadow  = '0 0 0 2px rgba(120,200,120,0.6)';
  setTimeout(() => { card.style.boxShadow = ''; }, 1200);
}

// ── convert ────────────────────────────────────────────────────────────────
async function runConvert() {
  if (!selectedSave) { alert('Select a save file first'); return; }
  const btn = document.getElementById('convBtn');
  const spn = document.getElementById('convSpinner');
  btn.disabled = true; spn.classList.add('active');
  banner('convResult', '', '');

  const regionVal = val('convRegion') === 'custom' ? val('convRegionCustom') : val('convRegion');
  const srcFile = selectedSave.path;
  const outFile = srcFile.replace(/\.bin$/, `_${currentMode}.bin`);

  const body = {
    source_file: srcFile,
    output_file: outFile,
    mode: currentMode,
    engine: currentEngine,
    source_id: val('convSrcId'),
    target_id: val('convTgtId'),
    region_hash: regionVal,
    app_version: val('convVer'),
  };

  log('head', `Converting: ${selectedSave.name}`);
  log('info', `  mode=${currentMode}  engine=${currentEngine}`);
  log('info', `  source_id=${body.source_id}  target_id=${body.target_id}`);
  log('info', `  region_hash=${regionVal}  app_version=${body.app_version}`);

  try {
    const res = await post('/api/convert', body);
    if (res.success) {
      banner('convResult', 'ok', `✓ Saved: ${res.output}`);
      log('ok', 'Conversion successful');
      log('info', res.output);
      if (res.log) log('info', res.log.trim());
    } else {
      banner('convResult', 'err', `✗ ${res.error}`);
      log('err', res.error);
      if (res.log) log('warn', res.log.trim());
    }
  } catch (e) {
    banner('convResult', 'err', `✗ ${e}`);
    log('err', String(e));
  }
  btn.disabled = false; spn.classList.remove('active');
}

async function runBatchConvert() {
  if (!selectedSave) { alert('Select a save to get the directory'); return; }
  const srcDir = selectedSave.path.replace(/\/[^/]+$/, '');
  const outDir = srcDir + `_${currentMode}`;
  const regionVal = val('convRegion') === 'custom' ? val('convRegionCustom') : val('convRegion');

  const btn = document.getElementById('batchBtn');
  btn.disabled = true;
  log('head', `Batch convert: ${srcDir}`);

  const body = {
    source_dir: srcDir,
    output_dir: outDir,
    mode: currentMode,
    source_id: val('convSrcId'),
    target_id: val('convTgtId'),
    region_hash: regionVal,
    app_version: val('convVer'),
  };

  try {
    const res = await post('/api/convert_batch', body);
    if (res.success) {
      banner('convResult', 'ok', `✓ Batch done → ${res.output_dir}`);
      log('ok', `Batch done → ${res.output_dir}`);
      if (res.log) log('info', res.log.trim());
    } else {
      banner('convResult', 'err', `✗ ${res.error}`);
      log('err', res.error);
      if (res.log) log('warn', res.log.trim());
    }
  } catch (e) {
    log('err', String(e));
  }
  btn.disabled = false;
}

// ── inspect ────────────────────────────────────────────────────────────────
async function runInspect() {
  if (!selectedSave) { alert('Select a save file first'); return; }
  const btn = document.getElementById('inspBtn');
  const spn = document.getElementById('inspSpinner');
  btn.disabled = true; spn.classList.add('active');
  banner('inspResult', '', '');

  log('head', `Inspecting: ${selectedSave.name}`);
  try {
    const res = await post('/api/inspect_fields', {
      file_path: selectedSave.path,
      source_id: val('inspSrcId'),
    });
    if (res.success) {
      showInspectFields(res.fields);
      log('ok', `Detected: mode=${res.detected_mode}`);
    } else {
      banner('inspResult', 'err', `✗ ${res.error || 'Could not parse fields'}`);
      log('err', res.error || 'Field inspection failed');
    }
    if (res.log) log('info', res.log.trim());
  } catch (e) {
    banner('inspResult', 'err', `✗ ${e}`);
    log('err', String(e));
  }
  btn.disabled = false; spn.classList.remove('active');
}

function showInspectFields(f) {
  const card = document.getElementById('inspResultCard');
  const grid = document.getElementById('inspFields');
  if (!f || !Object.keys(f).length) {
    card.style.display = 'none'; return;
  }
  card.style.display = '';
  const rows = [];
  if (f._MainRegionHash !== undefined)
    rows.push(`<span class="fk">_MainRegionHash</span><span class="fv">${f._MainRegionHash} <span class="platform">${f.platform_hint || ''}</span></span>`);
  if (f._ApplicationVersion !== undefined)
    rows.push(`<span class="fk">_ApplicationVersion</span><span class="fv">${f._ApplicationVersion} <span class="platform">${f.version_label || ''}</span></span>`);
  if (f.decrypted_size !== undefined)
    rows.push(`<span class="fk">Decrypted size</span><span class="fv">${f.decrypted_size_str}</span>`);
  if (f.flags)
    rows.push(`<span class="fk">Flags</span><span class="fv">${esc(f.flags)}</span>`);
  grid.innerHTML = rows.join('');
}

// ── MandarinJuice ──────────────────────────────────────────────────────────
function onMjGameChange() {}

function getMjProfile() {
  const sel = document.getElementById('mjGameSelect');
  return sel ? sel.value : '';
}

async function runBrute() {
  const btn = document.getElementById('mjBtn');
  const spn = document.getElementById('mjSpinner');
  btn.disabled = true; spn.classList.add('active');
  banner('mjResult', '', '');

  const profile = getMjProfile();
  if (!profile) { alert('Select a game profile'); btn.disabled=false; spn.classList.remove('active'); return; }
  const body = {
    save_path:    val('mjSavePath'),
    game_profile: profile,
  };
  if (!body.save_path) { alert('Enter save path'); btn.disabled=false; spn.classList.remove('active'); return; }

  log('head', 'MandarinJuice brute force…');
  try {
    const res = await post('/api/bruteforce', body);
    if (res.success) {
      banner('mjResult', 'ok', `✓ Found Steam ID: ${res.steam_id}`);
      log('ok', `Steam ID found: ${res.steam_id}`);
      setVal('convSrcId', res.steam_id);
      setVal('mjOldId',   res.steam_id);
    } else {
      banner('mjResult', 'err', `✗ ${res.error}`);
      log('err', res.error);
    }
    if (res.log) log('info', res.log.trim());
  } catch (e) {
    banner('mjResult', 'err', `✗ ${e}`);
    log('err', String(e));
  }
  btn.disabled = false; spn.classList.remove('active');
}

async function runResign() {
  const btn = document.getElementById('resignBtn');
  const spn = document.getElementById('resignSpinner');
  btn.disabled = true; spn.classList.add('active');
  banner('resignResult', '', '');

  const body = {
    save_dir:     val('mjResignDir'),
    game_profile: getMjProfile(),
    old_id:       val('mjOldId'),
    new_id:       val('mjNewId'),
  };
  log('head', `Re-sign: ${body.old_id} → ${body.new_id}`);
  try {
    const res = await post('/api/mj_resign', body);
    if (res.success) {
      banner('resignResult', 'ok', '✓ Re-signed successfully');
      log('ok', 'Re-sign done');
    } else {
      banner('resignResult', 'err', `✗ ${res.error}`);
      log('err', res.error);
    }
    if (res.log) log('info', res.log.trim());
  } catch (e) {
    banner('resignResult', 'err', `✗ ${e}`);
    log('err', String(e));
  }
  btn.disabled = false; spn.classList.remove('active');
}

// ── Garlic Package ─────────────────────────────────────────────────────────
function setupDrag() {
  // ── Garlic import ZIP drop area ────────────────────────────────────────────
  const importArea = document.getElementById('garlicImportUpload');
  if (importArea) {
    importArea.addEventListener('dragover', e => { e.preventDefault(); importArea.classList.add('drag'); });
    importArea.addEventListener('dragleave', () => importArea.classList.remove('drag'));
    importArea.addEventListener('drop', e => {
      e.preventDefault(); importArea.classList.remove('drag');
      const file = e.dataTransfer.files[0];
      if (!file) return;
      // Trigger the same import flow
      const input = document.getElementById('garlicImportInput');
      // We can't set input.files directly; instead fake an event object
      importGarlicZip({ target: { files: [file] } });
    });
  }

  // ── Garlic upload area ─────────────────────────────────────────────────────
  const garlic = document.getElementById('garlicUpload');
  garlic.addEventListener('dragover', e => { e.preventDefault(); garlic.classList.add('drag'); });
  garlic.addEventListener('dragleave', () => garlic.classList.remove('drag'));
  garlic.addEventListener('drop', e => {
    e.preventDefault(); garlic.classList.remove('drag');
    addGarlicFiles([...e.dataTransfer.files]);
  });

  // ── Convert tab: drag .bin directly onto the selected-file box ─────────────
  const convBox = document.getElementById('convSelectedBox');
  if (convBox) {
    convBox.addEventListener('dragover', e => {
      e.preventDefault();
      convBox.style.outline    = '2px dashed var(--accent)';
      convBox.style.background = 'rgba(100,180,255,0.06)';
    });
    convBox.addEventListener('dragleave', () => {
      convBox.style.outline    = '';
      convBox.style.background = '';
    });
    convBox.addEventListener('drop', e => {
      e.preventDefault();
      convBox.style.outline    = '';
      convBox.style.background = '';
      const file = e.dataTransfer.files[0];
      if (!file) return;
      handleDroppedFile(file, convBox);
    });
  }
}

// Upload a dropped file to the server, then use the returned server path.
// Works even inside the browser sandbox where file.path is unavailable.
async function handleDroppedFile(file, convBox) {
  const sizeStr = `${(file.size / 1024).toFixed(1)} KB`;

  // Optimistic UI update
  convBox.innerHTML = `<div>
    <div class="fname">${esc(file.name)}</div>
    <div class="fmeta">${esc(sizeStr)} · Uploading…</div>
  </div>`;

  // Upload to server
  let serverPath = null;
  try {
    const res = await fetch('/api/upload?name=' + encodeURIComponent(file.name), {
      method: 'POST',
      body: file,
      headers: { 'Content-Type': 'application/octet-stream' }
    }).then(r => r.json());

    if (res.success && res.saves && res.saves[0]) {
      serverPath = res.saves[0].path;
    } else if (res.zip_path) {
      serverPath = res.zip_path;
    }
  } catch (err) {
    log('err', `Upload failed: ${err}`);
  }

  if (!serverPath) {
    log('err', `Upload failed for ${file.name} — no server path returned`);
    convBox.innerHTML = `<span style="color:var(--accent2)">Upload failed — try again</span>`;
    return;
  }

  selectedSave = {
    name:      file.name,
    path:      serverPath,
    size:      file.size,
    size_str:  sizeStr,
    mtime_str: 'uploaded',
    engine:    're_engine',
    label:     file.name,
  };
  _lastDetect = null;
  setEngine('re_engine');

  const html = `<div>
    <div class="fname">${esc(file.name)}</div>
    <div class="fmeta">${esc(sizeStr)} · ${esc(serverPath)}</div>
  </div>`;
  convBox.innerHTML = html;
  document.getElementById('inspSelectedBox').innerHTML = html;
  setVal('inspFilePath', serverPath);
  document.getElementById('detectBanner').style.display = 'none';

  log('ok', `Dropped & uploaded: ${file.name} → ${serverPath}`);
  setTimeout(() => runAutoDetect(), 100);
}

function garlicFilesSelected(e) {
  addGarlicFiles([...e.target.files]);
  e.target.value = '';
}

function addGarlicFiles(files) {
  files.forEach(f => {
    if (!garlicPendingFiles.find(p => p.name === f.name))
      garlicPendingFiles.push(f);
  });
  renderGarlicFiles();
}

function renderGarlicFiles() {
  const wrap = document.getElementById('garlicFileList');
  const items = document.getElementById('garlicFileItems');
  if (!garlicPendingFiles.length) { wrap.style.display = 'none'; return; }
  wrap.style.display = '';
  items.innerHTML = garlicPendingFiles.map((f, i) => `
    <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px">
      <span style="color:var(--green)">●</span>
      <span>${esc(f.name)}</span>
      <span style="color:var(--muted);font-size:11px">${(f.size/1024).toFixed(1)} KB</span>
      <button class="btn sm" onclick="removeGarlicFile(${i})">✕</button>
    </div>
  `).join('');
}

function removeGarlicFile(i) {
  garlicPendingFiles.splice(i, 1);
  renderGarlicFiles();
}

async function buildGarlic(mode) {
  const spn = document.getElementById('garlicSpinner');
  banner('garlicResult', '', '');
  document.getElementById('garlicSlots').style.display = 'none';

  if (!garlicPendingFiles.length) {
    alert('Add .bin files first');
    return;
  }

  spn.classList.add('active');
  log('head', `Building Garlic package (${mode})…`);

  // Upload files first, collect server paths
  const serverPaths = [];
  for (const f of garlicPendingFiles) {
    try {
      const res = await uploadFile(f);
      if (res.is_archive) {
        log('warn', `${f.name}: archive uploaded, expecting .bin`);
      } else if (res.saves?.length) {
        serverPaths.push(res.saves[0].path);
        log('info', `Uploaded: ${f.name} → ${res.saves[0].path}`);
      }
    } catch (e) {
      log('err', `Upload failed: ${f.name}: ${e}`);
    }
  }

  if (!serverPaths.length) {
    spn.classList.remove('active');
    banner('garlicResult', 'err', '✗ No files could be uploaded');
    return;
  }

  const outDir = val('garlicOutDir') || '/tmp/garlic_out';
  const body = {
    files: serverPaths,
    output_dir: outDir,
    as_zip: mode === 'zip',
    zip_path: outDir.replace(/\/$/, '') + '/garlic_package.zip',
  };

  try {
    const res = await post('/api/garlic_package', body);
    if (res.success) {
      const msg = mode === 'zip'
        ? `✓ ZIP: ${res.zip}`
        : `✓ Folder: ${outDir}`;
      banner('garlicResult', 'ok', msg);
      log('ok', msg);
      if (res.download_url) {
        const dl = `<a href="${res.download_url}" class="link" download>⬇ Download ZIP</a>`;
        document.getElementById('garlicResult').innerHTML += '&nbsp;&nbsp;' + dl;
      }
      showGarlicSlots(res.built || []);
    } else {
      banner('garlicResult', 'err', `✗ ${res.errors?.join(', ') || res.error}`);
      log('err', JSON.stringify(res.errors));
    }
  } catch (e) {
    banner('garlicResult', 'err', `✗ ${e}`);
    log('err', String(e));
  }
  spn.classList.remove('active');
}

function showGarlicSlots(slots) {
  const wrap = document.getElementById('garlicSlots');
  if (!slots.length) { wrap.style.display = 'none'; return; }
  wrap.style.display = '';
  wrap.innerHTML = slots.map(s => `
    <div class="garlic-entry">
      <span class="slot-num">Slot ${s.slot}</span>
      <span>${esc(s.folder)}/<strong>${esc(s.file)}</strong></span>
    </div>
  `).join('');
}

// ── PS5 Push ───────────────────────────────────────────────────────────────
async function checkPs5() {
  const btn = document.getElementById('ps5Dot');
  const spn = document.getElementById('ps5Spinner');
  spn.classList.add('active');
  banner('ps5ConnResult', '', '');
  document.getElementById('ps5SlotList').style.display = 'none';

  const ip = val('ps5Ip'), port = val('ps5Port');
  log('head', `Checking PS5 at ${ip}:${port}…`);
  try {
    const res = await get(`/api/ps5_status?ip=${ip}&port=${port}`);
    if (res.success) {
      dot('ps5Dot', 'ok');
      banner('ps5ConnResult', 'ok', `✓ Connected — ${(res.saves?.saves || []).length} save slots`);
      log('ok', 'PS5 connected');
      showPs5Slots(res.saves?.saves || []);
    } else {
      dot('ps5Dot', 'err');
      banner('ps5ConnResult', 'err', `✗ ${res.error}`);
      log('err', res.error);
    }
  } catch (e) {
    dot('ps5Dot', 'err');
    banner('ps5ConnResult', 'err', `✗ ${e}`);
    log('err', String(e));
  }
  spn.classList.remove('active');
}

function showPs5Slots(slots) {
  const wrap = document.getElementById('ps5SlotList');
  if (!slots.length) { wrap.style.display = 'none'; return; }
  wrap.style.display = '';
  wrap.innerHTML = slots.map((s, i) => `
    <div class="ps5-slot">
      <div class="slot-info">
        <div class="slot-name">${esc(s.title || s.name || `Save ${i}`)}</div>
        <div class="slot-tid">${esc(s.title_id || '')} · Slot ${i}</div>
      </div>
    </div>
  `).join('');
}

async function pushToPs5() {
  const spn = document.getElementById('pushSpinner');
  spn.classList.add('active');
  banner('pushResult', '', '');

  const body = {
    ip: val('ps5Ip'),
    port: val('ps5Port'),
    title_id: val('pushTitleId'),
    bin_path: val('pushBinPath'),
  };
  if (!body.bin_path) { alert('Enter bin path'); spn.classList.remove('active'); return; }

  log('head', `Pushing to PS5: ${body.bin_path}`);
  try {
    const res = await post('/api/garlic_push', body);
    if (res.success) {
      banner('pushResult', 'ok', '✓ Pushed to PS5 successfully');
      log('ok', 'Push done');
    } else {
      banner('pushResult', 'err', `✗ ${res.error}`);
      log('err', res.error);
    }
  } catch (e) {
    banner('pushResult', 'err', `✗ ${e}`);
    log('err', String(e));
  }
  spn.classList.remove('active');
}

// ── helpers ────────────────────────────────────────────────────────────────
async function uploadFile(file) {
  const ab = await file.arrayBuffer();
  const r = await fetch(`${API}/api/upload?name=${encodeURIComponent(file.name)}`, {
    method: 'POST',
    body: ab,
    headers: { 'Content-Type': 'application/octet-stream' },
  });
  return r.json();
}

async function get(path) {
  const r = await fetch(API + path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

async function post(path, body) {
  const r = await fetch(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

function val(id) {
  const el = document.getElementById(id);
  return el ? el.value.trim() : '';
}

function setVal(id, v) {
  const el = document.getElementById(id);
  if (el) el.value = v;
}

function esc(s) {
  if (s == null) return '';
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function spinner(id, active) {
  const el = document.getElementById(id);
  if (!el) return;
  if (active) el.classList.add('active');
  else el.classList.remove('active');
}

function dot(id, state) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'status-dot' + (state ? ' ' + state : '');
}

function banner(id, type, msg) {
  const el = document.getElementById(id);
  if (!el) return;
  el.className = 'result-banner';
  if (type) {
    el.classList.add(type);
    el.innerHTML = msg;
  }
}

function log(type, msg) {
  const out = document.getElementById('logOutput');
  const line = document.createElement('div');
  line.className = 'log-line ' + type;
  // keep it short in display — truncate very long lines
  const display = msg.length > 400 ? msg.slice(0, 400) + '…' : msg;
  line.textContent = display;
  out.appendChild(line);
  out.scrollTop = out.scrollHeight;
}

function clearLog() {
  document.getElementById('logOutput').innerHTML = '';
}

// ── Save Editor — Garlic ZIP import ────────────────────────────────────────
async function importGarlicZip(evt) {
  const file = evt.target.files[0];
  if (!file) return;

  banner('importResult', null, '');
  const area = document.getElementById('garlicImportUpload');
  area.querySelector('div').textContent = `Uploading ${file.name}…`;

  // Upload the ZIP first
  const uploaded = await fetch('/api/upload?name=' + encodeURIComponent(file.name), {
    method: 'POST',
    body: file,
    headers: { 'Content-Type': 'application/octet-stream' }
  }).then(r => r.json()).catch(e => ({ success: false, error: String(e) }));

  area.querySelector('div').textContent = 'Drop Garlic ZIP or click to select';

  if (!uploaded.zip_path && !uploaded.dir) {
    banner('importResult', 'err', `Upload failed: ${esc(uploaded.error || 'unknown')}`);
    return;
  }

  const zipFilePath = uploaded.zip_path;
  const res = await post('/api/garlic_import', { zip_path: zipFilePath });

  if (!res.success) {
    banner('importResult', 'err', `Import failed: ${esc(res.error)}`);
    return;
  }

  const saves = res.saves || [];
  banner('importResult', 'ok',
    `✓ Extracted ${saves.length} save(s) from ${esc(file.name)}`);

  const container = document.getElementById('importedSaves');
  const list = document.getElementById('importedSavesList');
  container.style.display = '';
  list.innerHTML = '';

  saves.forEach(s => {
    const div = document.createElement('div');
    div.className = 'garlic-entry';
    div.style.cursor = 'pointer';
    const platform = s.platform || '?';
    const region = s.region_hash ? ` | Region: ${s.region_hash}` : '';
    div.innerHTML = `
      <span class="slot-num">Slot ${s.slot || 0}</span>
      <span style="flex:1;font-size:11px">${esc(s.path)}</span>
      <span style="font-size:11px;color:var(--muted)">${esc(platform)}${esc(region)}</span>
      <button class="btn sm" onclick="editorLoadFile('${esc(s.path)}')">Load</button>
    `;
    list.appendChild(div);
  });

  if (res.errors && res.errors.length) {
    list.insertAdjacentHTML('beforeend',
      `<div style="font-size:11px;color:var(--yellow);margin-top:4px">${res.errors.map(esc).join('<br>')}</div>`);
  }
}

function editorLoadFile(path) {
  setVal('editorFilePath', path);
  switchTab('editor');
  document.getElementById('editorFilePath').focus();
}

// ── Save Editor — patch presets ───────────────────────────────────────────────
const PATCH_PRESETS = {
  region_eu_as: { label: 'Region: any → EU/AS (481759118)',   find_auto: true, replace: 481759118 },
  region_eu_us: { label: 'Region: any → EU/US (3208943443)',  find_auto: true, replace: 3208943443 },
  region_pc:    { label: 'Region: any → PC (1874947740)',      find_auto: true, replace: 1874947740 },
  ver_ps5:      { label: 'Version: PC (16781314) → PS5 (16785408)', find: 16781314,   replace: 16785408 },
  ver_pc:       { label: 'Version: PS5 (16785408) → PC (16781314)', find: 16785408,   replace: 16781314 },
};

// Region preset logic: "find_auto" means we detect current region from inspect
// and patch FROM whatever it is TO replace value. We'll set find=0 as sentinel
// and the backend will handle it (actually we need find=current region).
// For simplicity: region presets ask user for current region or use detected value.

let _patchRows = [];

function editorAddPreset(key) {
  const p = PATCH_PRESETS[key];
  if (!p) return;
  if (p.find_auto) {
    // For region presets, we need to know the current region.
    // Detect from inspected file if available, else prompt user.
    const fp = document.getElementById('editorFilePath').value.trim();
    if (!fp) {
      alert('Select a save file first (or fill "Save file" field), then use the preset.');
      return;
    }
    // We'll add a patch row with find=0 (meaning auto-detect). User can adjust.
    addPatchRow({ find: '', replace: p.replace, label: `Region → ${p.replace}` });
  } else {
    addPatchRow({ find: p.find, replace: p.replace, label: p.label });
  }
}

function editorAddPatch() {
  addPatchRow({ find: '', replace: '', label: '' });
}

function addPatchRow({ find = '', replace = '', label = '' }) {
  const idx = _patchRows.length;
  _patchRows.push({ find, replace, label });

  const list = document.getElementById('patchList');
  const row = document.createElement('div');
  row.id = `prow_${idx}`;
  row.style.cssText = 'display:flex;gap:6px;align-items:center';
  row.innerHTML = `
    <input type="number" placeholder="Find (uint32)" value="${esc(String(find))}"
           style="flex:1;min-width:0" onchange="patchRowUpdate(${idx},'find',this.value)">
    <span style="color:var(--muted)">→</span>
    <input type="number" placeholder="Replace (uint32)" value="${esc(String(replace))}"
           style="flex:1;min-width:0" onchange="patchRowUpdate(${idx},'replace',this.value)">
    <input type="text" placeholder="Label (opt)" value="${esc(label)}"
           style="flex:1;min-width:0;font-size:11px" onchange="patchRowUpdate(${idx},'label',this.value)">
    <button class="btn sm" style="flex-shrink:0" onclick="removePatchRow(${idx})">✕</button>
  `;
  list.appendChild(row);
}

function patchRowUpdate(idx, field, val) {
  if (_patchRows[idx]) _patchRows[idx][field] = val;
}

function removePatchRow(idx) {
  const el = document.getElementById(`prow_${idx}`);
  if (el) el.remove();
  _patchRows[idx] = null;
}

async function runHexPatch() {
  const fp   = document.getElementById('editorFilePath').value.trim();
  const sid  = document.getElementById('editorSrcId').value.trim();
  const tidRaw = document.getElementById('editorTgtId').value.trim();
  const tid  = tidRaw || sid;
  const mode = document.getElementById('editorMode').value;

  if (!fp)  { banner('patchResult', 'err', 'No save file specified'); return; }
  if (!sid) { banner('patchResult', 'err', 'Source ID required'); return; }

  const patches = _patchRows
    .filter(r => r && r.find !== '' && r.replace !== '')
    .map(r => ({ find: parseInt(r.find), replace: parseInt(r.replace), label: r.label || `${r.find}→${r.replace}` }));

  if (!patches.length) {
    banner('patchResult', 'err', 'Add at least one patch');
    return;
  }

  spinner('patchSpinner', true);
  banner('patchResult', null, '');
  document.getElementById('patchLog').style.display = 'none';

  const res = await post('/api/hex_patch', {
    file_path: fp, source_id: sid, target_id: tid,
    mode, patches,
    region_hash: '1874947740',   // placeholder (not used in chain)
    app_version: '16781314'
  });

  spinner('patchSpinner', false);

  if (res.log) {
    const logEl = document.getElementById('patchLog');
    logEl.style.display = '';
    logEl.innerHTML = res.log.split('\n').map(l =>
      `<div class="log-line ${l.includes('fail') || l.includes('err') ? 'err' : l.includes('→') ? 'ok' : ''}">${esc(l)}</div>`
    ).join('');
  }

  if (res.success) {
    let msg = `✓ Patches applied (${res.patches_applied || 0} step(s))`;
    if (res.output_name) {
      msg += ` — <a class="link" href="/api/download?file=${encodeURIComponent(res.output)}"
                   download="${esc(res.output_name)}">Download ${esc(res.output_name)}</a>`;
    }
    if (res.note) msg += `<br><span style="color:var(--muted);font-size:12px">${esc(res.note)}</span>`;
    banner('patchResult', 'ok', msg);
  } else {
    banner('patchResult', 'err', `✗ ${esc(res.error || 'Patch failed')}`);
  }
}

// ── Python brute-force ───────────────────────────────────────────────────────
async function runBruteforcePy() {
  const fp    = document.getElementById('pyBfFile').value.trim();
  const start = parseInt(document.getElementById('pyBfStart').value) || 0;
  const end   = parseInt(document.getElementById('pyBfEnd').value)   || 100000;

  if (!fp) { banner('pyBfResult', 'err', 'No file specified'); return; }

  spinner('pyBfSpinner', true);
  banner('pyBfResult', null, '');

  const res = await post('/api/bruteforce_py', { file_path: fp, start, end });

  spinner('pyBfSpinner', false);

  if (res.success) {
    banner('pyBfResult', 'ok',
      `✓ Found! Steam32: <b>${res.steam32}</b> → Steam64: <b>${res.steam64}</b>
       <br><span style="font-size:11px;color:var(--muted)">Use this as Source ID in Convert tab</span>`);
    // Auto-fill Steam ID fields
    ['convSrcId', 'inspSrcId', 'mjOldId'].forEach(id => setVal(id, String(res.steam64)));
  } else {
    banner('pyBfResult', 'err', `✗ ${esc(res.error || 'Not found')}`);
  }
}
