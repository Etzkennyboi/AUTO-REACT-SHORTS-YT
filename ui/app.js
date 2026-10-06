// ── State ──────────────────────────────────────────────────────────────────
let currentJobId = null;
let evtSource    = null;
let probeDur     = null;   // parsed from [probe] line for encode progress calc

// ── DOM refs ───────────────────────────────────────────────────────────────
const urlInput    = document.getElementById('urlInput');
const forceSelect = document.getElementById('forceSelect');
const goBtn       = document.getElementById('goBtn');
const jobSection  = document.getElementById('jobSection');
const terminal    = document.getElementById('terminal');
const progressFill= document.getElementById('progressFill');
const progressLbl = document.getElementById('progressLbl');
const jobBadge    = document.getElementById('jobBadge');
const resultsGrid = document.getElementById('resultsGrid');
const reactDot    = document.getElementById('reactDot');
const reactLbl    = document.getElementById('reactLbl');

// ── Init ───────────────────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  checkReact();
  loadJobs();

  urlInput.addEventListener('keydown', e => {
    if (e.key === 'Enter') startJob();
  });

  // paste & go shortcut
  urlInput.addEventListener('paste', () => {
    setTimeout(() => {
      if (urlInput.value.includes('http')) startJob();
    }, 80);
  });
});

// ── React status ───────────────────────────────────────────────────────────
async function checkReact() {
  try {
    const r = await fetch('/api/react-status');
    const d = await r.json();
    if (d.found) {
      reactDot.className = 'dot dot-green';
      reactLbl.textContent = `react.mp4 · ${d.size}`;
    } else {
      reactDot.className = 'dot dot-red';
      reactLbl.textContent = 'storage/react.mp4 missing';
    }
  } catch {
    reactDot.className = 'dot dot-red';
    reactLbl.textContent = 'server offline?';
  }
}

// ── Start job ──────────────────────────────────────────────────────────────
async function startJob() {
  const url = urlInput.value.trim();
  if (!url) {
    urlInput.classList.add('shake');
    setTimeout(() => urlInput.classList.remove('shake'), 500);
    return;
  }

  setBtnLoading(true);
  probeDur = null;

  try {
    const r = await fetch('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, force: forceSelect.value }),
    });
    const d = await r.json();
    currentJobId = d.job_id;

    showJobSection();
    setProgress(0, 'running');
    setBadge('running');

    connectStream(currentJobId);
  } catch (e) {
    alert('Failed to start job: ' + e.message);
    setBtnLoading(false);
  }
}

// ── SSE stream ─────────────────────────────────────────────────────────────
function connectStream(jobId) {
  if (evtSource) evtSource.close();

  evtSource = new EventSource(`/api/stream/${jobId}`);

  evtSource.onmessage = e => {
    const { line } = JSON.parse(e.data);
    appendLog(line);
    tickProgress(line);
  };

  evtSource.addEventListener('done', e => {
    evtSource.close();
    const { status } = JSON.parse(e.data);

    if (status === 'done') {
      setProgress(100, 'done');
      setBadge('done');
    } else {
      setProgress(100, 'error');
      setBadge('error');
    }

    setBtnLoading(false);
    loadJobs();
  });

  evtSource.onerror = () => {
    evtSource.close();
    setBtnLoading(false);
  };
}

// ── Log terminal ───────────────────────────────────────────────────────────
function appendLog(line) {
  const el = document.createElement('div');
  el.className = 'log-line ' + logClass(line);
  el.textContent = line;
  terminal.appendChild(el);
  terminal.scrollTop = terminal.scrollHeight;
}

function logClass(line) {
  if (line.startsWith('[error]'))    return 'log-error';
  if (line.startsWith('[done]'))     return 'log-done';
  if (line.startsWith('[download]')) return 'log-download';
  if (line.startsWith('[probe]'))    return 'log-probe';
  if (line.startsWith('[classify]')) return 'log-classify';
  if (line.startsWith('[encode]'))   return 'log-encode';
  if (line.startsWith('[info]'))     return 'log-info';
  return 'log-default';
}

// ── Progress ───────────────────────────────────────────────────────────────
function tickProgress(line) {
  if (line.startsWith('[info]'))                             setProgress(5,  'running');
  else if (line.includes('[download] Starting'))             setProgress(10, 'running');
  else if (line.includes('Cache hit') || line.includes('Complete ✓')) setProgress(40, 'running');
  else if (line.startsWith('[probe]') && line.includes('×')) {
    // "[probe] 1920×1080, 16.33s"
    const m = line.match(/([\d.]+)s/);
    if (m) probeDur = parseFloat(m[1]);
    setProgress(50, 'running');
  }
  else if (line.startsWith('[classify] Mode'))               setProgress(60, 'running');
  else if (line.startsWith('[encode] Starting'))             setProgress(65, 'running');
  else if (line.startsWith('[encode]') && line.includes('/') && probeDur) {
    // "[encode] 8.1s / 16.3s (49%)"
    const m = line.match(/([\d.]+)s\s*\/\s*([\d.]+)s/);
    if (m) {
      const pct = 65 + (parseFloat(m[1]) / parseFloat(m[2])) * 30;
      setProgress(Math.min(94, pct), 'running');
    }
  }
  else if (line.startsWith('[done]'))                        setProgress(100, 'done');
}

function setProgress(pct, state) {
  pct = Math.round(pct);
  progressFill.style.width = pct + '%';
  progressFill.className = 'progress-fill fill-' + state;
  progressLbl.textContent = state === 'done' ? 'Complete' : state === 'error' ? 'Failed' : pct + '%';
}

// ── Badge ──────────────────────────────────────────────────────────────────
function setBadge(state) {
  const map = { running: ['Running', 'badge-running'], done: ['✓ Done', 'badge-success'], error: ['✗ Error', 'badge-error'] };
  jobBadge.textContent = map[state][0];
  jobBadge.className = 'job-badge ' + map[state][1];
}

// ── Button ─────────────────────────────────────────────────────────────────
function setBtnLoading(loading) {
  goBtn.disabled = loading;
  goBtn.innerHTML = loading
    ? '<span class="spinner"></span> Processing...'
    : '▶ Go';
}

// ── Job section visibility ─────────────────────────────────────────────────
function showJobSection() {
  terminal.innerHTML = '';
  jobSection.style.display = 'block';
  jobSection.classList.add('visible');
  jobSection.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ── Jobs list ──────────────────────────────────────────────────────────────
async function loadJobs() {
  try {
    const r = await fetch('/api/jobs');
    renderJobs(await r.json());
  } catch { /* server may not be ready */ }
}

function renderJobs(jobs) {
  if (!jobs.length) {
    resultsGrid.innerHTML = '<p class="empty-msg">No jobs yet.<br>Paste a Shorts, Reels, or TikTok URL above and hit <strong>Go</strong>.</p>';
    return;
  }

  resultsGrid.innerHTML = jobs.map(j => {
    const dotCls = j.status === 'done' ? 'dot-green' : j.status === 'error' ? 'dot-red' : 'dot-yellow dot-pulse';
    const actions = [];
    if (j.status === 'done')    actions.push(`<button class="btn-sm btn-dl"    onclick="dlJob('${j.id}')">⬇ Download</button>`);
    if (j.status === 'running') actions.push(`<button class="btn-sm btn-watch"  onclick="watchJob('${j.id}')">👁 Watch</button>`);
    if (j.status === 'error')   actions.push(`<span class="err-label">✗ ${esc(j.error||'Failed')}</span>`);
    actions.push(`<button class="btn-sm btn-del" onclick="delJob('${j.id}')">🗑</button>`);

    return `<div class="job-card" id="jc-${j.id}">
  <div class="jc-header">
    <span class="dot ${dotCls}"></span>
    <span class="jc-id">#${j.id}</span>
    <span class="jc-time">${timeAgo(j.created)}</span>
  </div>
  <div class="jc-url">${esc(fmtUrl(j.url))}</div>
  <div class="jc-actions">${actions.join('')}</div>
</div>`;
  }).join('');
}

function dlJob(id)   { window.location.href = `/api/download/${id}`; }
function watchJob(id) {
  showJobSection();
  terminal.innerHTML = '';
  currentJobId = id;
  setProgress(0,'running');
  setBadge('running');
  connectStream(id);
}
async function delJob(id) {
  await fetch(`/api/jobs/${id}`, { method:'DELETE' });
  loadJobs();
}

// ── Utils ──────────────────────────────────────────────────────────────────
function timeAgo(ts) {
  const d = Date.now()/1000 - ts;
  if (d < 60)   return 'just now';
  if (d < 3600) return Math.floor(d/60) + 'm ago';
  return Math.floor(d/3600) + 'h ago';
}

function fmtUrl(url) {
  try {
    const u = new URL(url);
    const path = u.pathname.length > 32 ? u.pathname.slice(0,32)+'…' : u.pathname;
    return u.hostname + path;
  } catch { return url.slice(0,55); }
}

function esc(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}
