"""
app.py — Panoptic Panoramic Imaging System
Full integration: login/logout, per-user captures, admin panel, SQLite database.

python app.py

Admin panel:  http://localhost:5000/admin/login   (password: admin1234)
User login:   http://localhost:5000/login
"""

import os
import shutil
from functools import wraps
from datetime import datetime
from flask import (Flask, render_template_string, send_file,
                   jsonify, request, redirect, url_for, session)

from database import (init_db, verify_user, create_user, get_all_users,
                      delete_user, save_capture, get_user_captures,
                      delete_capture, get_conn)
from sync   import sync_capture, check_camera_status, set_resolution
from stitch import stitch_images

# ── app config ───────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = "panoptic-bau-2026-change-before-presenting"

GALLERY_DIR = "captures"
ADMIN_PASS  = "admin1234"

os.makedirs(GALLERY_DIR, exist_ok=True)
init_db()


# ── auth decorators ───────────────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated


# ── shared styles ─────────────────────────────────────────────────────────────
CSS = """
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3.31.0/dist/tabler-icons.min.css">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Georgia', serif; background: #fafaf8; color: #1a1a18; min-height: 100vh; }

  /* header */
  header {
    display: flex; align-items: center; justify-content: space-between;
    padding: 1.25rem 2.5rem; border-bottom: 0.5px solid #e0ddd4;
    background: #fff; position: sticky; top: 0; z-index: 10;
  }
  .logo { font-size: 14px; font-weight: 500; letter-spacing: 0.1em; }
  .logo span { color: #9a9891; font-weight: 400; }
  .hdr-right { display: flex; align-items: center; gap: 16px; font-size: 13px; color: #9a9891; }
  .hdr-right a { color: #185FA5; text-decoration: none; }
  .hdr-right a:hover { text-decoration: underline; }

  /* layout */
  main { max-width: 860px; margin: 0 auto; padding: 2.5rem 2rem 4rem; }

  /* labels */
  .lbl {
    font-size: 10.5px; letter-spacing: 0.14em; text-transform: uppercase;
    color: #b0ad9f; margin-bottom: 1rem; display: block;
  }

  /* card */
  .card { background: #fff; border: 0.5px solid #e0ddd4; border-radius: 14px; padding: 1.75rem; }

  /* form */
  .field { margin-bottom: 1.25rem; }
  .field label { display: block; font-size: 11px; letter-spacing: 0.1em;
                 text-transform: uppercase; color: #b0ad9f; margin-bottom: 6px; }
  .field input {
    width: 100%; padding: 9px 12px; font-size: 14px; font-family: inherit;
    border: 0.5px solid #e0ddd4; border-radius: 8px; background: #fafaf8;
    color: #1a1a18; outline: none; transition: border-color 0.15s;
  }
  .field input:focus { border-color: #1a1a18; }

  /* buttons */
  .btn {
    display: inline-flex; align-items: center; gap: 8px; padding: 10px 24px;
    font-size: 13.5px; font-family: inherit; border-radius: 8px; cursor: pointer;
    border: none; transition: opacity 0.15s, transform 0.1s; letter-spacing: 0.02em;
  }
  .btn:active  { transform: scale(0.98); }
  .btn-primary { background: #1a1a18; color: #fafaf8; }
  .btn-primary:hover { opacity: 0.85; }
  .btn-danger  { background: transparent; border: 0.5px solid #F7C1C1; color: #A32D2D; }
  .btn-danger:hover  { background: #FCEBEB; }
  .btn-sm { padding: 5px 12px; font-size: 12px; }

  /* alerts */
  .alert { padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 1.25rem; }
  .alert-error   { background: #FCEBEB; color: #A32D2D; border: 0.5px solid #F7C1C1; }
  .alert-success { background: #EAF3DE; color: #3B6D11; border: 0.5px solid #c0dd97; }

  /* camera pills */
  .status-bar { display: flex; align-items: center; gap: 10px; margin-bottom: 2rem; flex-wrap: wrap; }
  .pill {
    display: inline-flex; align-items: center; gap: 8px; padding: 6px 16px;
    border-radius: 100px; font-size: 12.5px; border: 0.5px solid #e0ddd4;
    background: #fff; color: #9a9891; transition: border-color 0.2s, color 0.2s;
  }
  .pill.online  { border-color: #c0dd97; color: #3B6D11; }
  .pill.offline { border-color: #F7C1C1; color: #A32D2D; }
  .dot { width: 7px; height: 7px; border-radius: 50%; background: currentColor; opacity: 0.8; }
  .refresh-btn {
    margin-left: auto; background: none; border: none; cursor: pointer;
    color: #b0ad9f; font-size: 13px; display: flex; align-items: center;
    gap: 5px; padding: 4px 8px; border-radius: 6px;
  }
  .refresh-btn:hover { background: #f0ede4; }

  /* settings grid */
  .settings-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin-bottom: 1rem; }
  .setting-card  { background: #fff; border: 0.5px solid #e0ddd4; border-radius: 10px; padding: 12px 14px; }
  .setting-card label { display: block; font-size: 10.5px; letter-spacing: 0.1em;
                        text-transform: uppercase; color: #b0ad9f; margin-bottom: 6px; }
  .setting-card select { width: 100%; font-size: 13px; color: #1a1a18;
                         background: transparent; border: none; outline: none;
                         cursor: pointer; font-family: inherit; }

  /* save params row */
  .save-params-row {
    display: flex; align-items: center; gap: 8px;
    margin-bottom: 2rem; padding: 0 2px;
  }
  .save-params-row input[type="checkbox"] {
    width: 14px; height: 14px; cursor: pointer; accent-color: #1a1a18; flex-shrink: 0;
  }
  .save-params-row label {
    font-size: 11px; letter-spacing: 0.08em; text-transform: uppercase;
    color: #b0ad9f; cursor: pointer; user-select: none;
  }

  /* capture card */
  .capture-card {
    background: #fff; border: 0.5px solid #e0ddd4; border-radius: 14px;
    padding: 2rem; text-align: center; margin-bottom: 2.5rem;
  }
  .capture-btn {
    display: inline-flex; align-items: center; gap: 9px; padding: 11px 32px;
    background: #1a1a18; color: #fafaf8; border: none; border-radius: 8px;
    font-size: 14px; font-family: inherit; cursor: pointer;
    transition: opacity 0.15s, transform 0.1s;
  }
  .capture-btn:hover    { opacity: 0.85; }
  .capture-btn:active   { transform: scale(0.98); }
  .capture-btn:disabled { opacity: 0.4; cursor: not-allowed; transform: none; }
  #status-msg { margin-top: 14px; font-size: 13px; color: #9a9891; min-height: 20px; }
  #status-msg.error { color: #A32D2D; }
  #status-msg.ok    { color: #3B6D11; }

  /* progress */
  .prog-wrap { height: 2px; background: #f0ede4; border-radius: 2px;
               margin-top: 16px; overflow: hidden; opacity: 0; transition: opacity 0.2s; }
  .prog-wrap.on { opacity: 1; }
  .prog-bar  { height: 100%; background: #1a1a18; border-radius: 2px;
               width: 0%; transition: width 0.4s ease; }

  /* preview */
  #pano-wrap  { display: none; margin-top: 20px; }
  #pano-img   { width: 100%; border-radius: 8px; border: 0.5px solid #e0ddd4; display: block; }
  .dl-link    { display: inline-flex; align-items: center; gap: 5px; margin-top: 10px;
                font-size: 12.5px; color: #185FA5; text-decoration: none; }
  .dl-link:hover { text-decoration: underline; }

  /* gallery */
  .gallery-hdr  { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
  .gallery-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; }
  .g-card       { background: #fff; border: 0.5px solid #e0ddd4; border-radius: 10px; overflow: hidden; }
  .g-thumb      { width: 100%; height: 80px; object-fit: cover; display: block; }
  .g-placeholder{ width: 100%; height: 80px; background: #f5f2eb;
                  display: flex; align-items: center; justify-content: center; color: #c8c5bb; font-size: 24px; }
  .g-info       { padding: 10px 12px; }
  .g-name       { font-size: 12px; color: #1a1a18; margin-bottom: 2px;
                  white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .g-meta       { font-size: 11px; color: #b0ad9f; margin-bottom: 6px; }
  .g-actions    { display: flex; gap: 10px; align-items: center; }
  .g-dl  { font-size: 11.5px; color: #185FA5; text-decoration: none;
           display: inline-flex; align-items: center; gap: 4px; }
  .g-del { font-size: 11.5px; color: #A32D2D; background: none; border: none; padding: 0;
           cursor: pointer; display: inline-flex; align-items: center; gap: 4px; font-family: inherit; }
  .g-del:hover { text-decoration: underline; }
  .g-empty { text-align: center; padding: 2.5rem; color: #c8c5bb; font-size: 13px;
             border: 0.5px dashed #e0ddd4; border-radius: 10px; }

  /* admin table */
  .tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
  .tbl th { text-align: left; font-size: 10.5px; letter-spacing: 0.1em; text-transform: uppercase;
            color: #b0ad9f; padding: 8px 12px; border-bottom: 0.5px solid #e0ddd4; font-weight: 400; }
  .tbl td { padding: 10px 12px; border-bottom: 0.5px solid #f0ede4; vertical-align: middle; }
  .tbl tr:last-child td { border-bottom: none; }

  /* helpers */
  .mt1  { margin-top: 1rem; }
  .mt2  { margin-top: 2rem; }
  .mb2  { margin-bottom: 2rem; }
  .muted { color: #b0ad9f; }
</style>
"""


# ═══════════════════════════════════════════════════════════════════════════════
#  LOGIN / LOGOUT
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = verify_user(request.form["username"], request.form["password"])
        if user:
            session["user_id"]  = user["id"]
            session["username"] = user["username"]
            return redirect(url_for("index"))
        error = "Incorrect username or password."

    html = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
    <title>Panoptic — Sign in</title>{{ css|safe }}</head><body>
    <header>
      <div class="logo">PANOPTIC <span>/ imaging system</span></div>
      <div class="hdr-right"><span>BAU Capstone 2026</span></div>
    </header>
    <main style="max-width:420px">
      <br><span class="lbl">sign in</span>
      <div class="card">
        {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
        <form method="POST">
          <div class="field">
            <label>Username</label>
            <input name="username" type="text" autocomplete="username" required autofocus>
          </div>
          <div class="field" style="margin-bottom:1.5rem">
            <label>Password</label>
            <input name="password" type="password" autocomplete="current-password" required>
          </div>
          <button class="btn btn-primary" type="submit" style="width:100%">
            <i class="ti ti-login"></i> Sign in
          </button>
        </form>
      </div>
    </main></body></html>"""
    return render_template_string(html, css=CSS, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ═══════════════════════════════════════════════════════════════════════════════
#  ADMIN
# ═══════════════════════════════════════════════════════════════════════════════

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if request.form["password"] == ADMIN_PASS:
            session["is_admin"] = True
            return redirect(url_for("admin_panel"))
        error = "Wrong admin password."

    html = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
    <title>Panoptic — Admin</title>{{ css|safe }}</head><body>
    <header><div class="logo">PANOPTIC <span>/ admin</span></div></header>
    <main style="max-width:420px">
      <br><span class="lbl">admin access</span>
      <div class="card">
        {% if error %}<div class="alert alert-error">{{ error }}</div>{% endif %}
        <form method="POST">
          <div class="field" style="margin-bottom:1.5rem">
            <label>Admin password</label>
            <input name="password" type="password" required autofocus>
          </div>
          <button class="btn btn-primary" type="submit" style="width:100%">
            <i class="ti ti-lock"></i> Enter
          </button>
        </form>
      </div>
    </main></body></html>"""
    return render_template_string(html, css=CSS, error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_panel():
    users = get_all_users()
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT user_id, COUNT(*) as n FROM captures GROUP BY user_id"
        ).fetchall()
    counts = {r["user_id"]: r["n"] for r in rows}
    msg    = request.args.get("msg", "")

    html = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
    <title>Panoptic — Admin Panel</title>{{ css|safe }}</head><body>
    <header>
      <div class="logo">PANOPTIC <span>/ admin panel</span></div>
      <div class="hdr-right">
        <a href="{{ url_for('index') }}">Back to app</a>
        <a href="{{ url_for('admin_logout') }}">Sign out</a>
      </div>
    </header>
    <main>
      {% if msg %}
      <div class="alert {% if 'Error' in msg or 'taken' in msg %}alert-error{% else %}alert-success{% endif %}">
        {{ msg }}
      </div>
      {% endif %}

      <span class="lbl">create user</span>
      <div class="card mb2">
        <form method="POST" action="{{ url_for('admin_create_user') }}"
              style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
          <div class="field" style="margin:0;flex:1;min-width:150px">
            <label>Username</label>
            <input name="username" type="text" required>
          </div>
          <div class="field" style="margin:0;flex:1;min-width:150px">
            <label>Password</label>
            <input name="password" type="password" required>
          </div>
          <button class="btn btn-primary" type="submit">
            <i class="ti ti-user-plus"></i> Create
          </button>
        </form>
      </div>

      <span class="lbl">users ({{ users|length }})</span>
      <div class="card">
        {% if users %}
        <table class="tbl">
          <thead><tr>
            <th>ID</th><th>Username</th><th>Created</th><th>Captures</th><th></th>
          </tr></thead>
          <tbody>
            {% for u in users %}
            <tr>
              <td class="muted">{{ u.id }}</td>
              <td><strong>{{ u.username }}</strong></td>
              <td class="muted">{{ u.created_at }}</td>
              <td>{{ counts.get(u.id, 0) }}</td>
              <td>
                <form method="POST" action="{{ url_for('admin_delete_user') }}"
                      onsubmit="return confirm('Delete {{ u.username }} and all their captures?')">
                  <input type="hidden" name="user_id" value="{{ u.id }}">
                  <button class="btn btn-danger btn-sm" type="submit">
                    <i class="ti ti-trash"></i> Delete
                  </button>
                </form>
              </td>
            </tr>
            {% endfor %}
          </tbody>
        </table>
        {% else %}
          <p class="muted" style="font-size:13px">No users yet — create one above.</p>
        {% endif %}
      </div>
    </main></body></html>"""
    return render_template_string(html, css=CSS, users=users, counts=counts, msg=msg)


@app.route("/admin/create-user", methods=["POST"])
@admin_required
def admin_create_user():
    ok, msg = create_user(request.form["username"], request.form["password"])
    return redirect(url_for("admin_panel", msg=msg))


@app.route("/admin/delete-user", methods=["POST"])
@admin_required
def admin_delete_user():
    ok, msg = delete_user(int(request.form["user_id"]))
    return redirect(url_for("admin_panel", msg=msg))


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ═══════════════════════════════════════════════════════════════════════════════

MAIN_HTML = """<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Panoptic — Panoramic Imaging</title>{{ css|safe }}</head><body>
<header>
  <div class="logo">PANOPTIC <span>/ imaging system</span></div>
  <div class="hdr-right">
    <span><i class="ti ti-user" style="font-size:14px;vertical-align:-2px"></i>
      {{ username }}</span>
    <a href="{{ url_for('logout') }}">Sign out</a>
  </div>
</header>

<main>

  <!-- Camera status -->
  <span class="lbl">camera status</span>
  <div class="status-bar">
    <div class="pill" id="pill-cam1">
      <div class="dot"></div> Camera 1 &nbsp;<small id="ip1" style="opacity:0.6"></small>
    </div>
    <div class="pill" id="pill-cam2">
      <div class="dot"></div> Camera 2 &nbsp;<small id="ip2" style="opacity:0.6"></small>
    </div>
    <button class="refresh-btn" onclick="refreshStatus()">
      <i class="ti ti-refresh"></i> refresh
    </button>
  </div>

  <!-- Settings -->
  <span class="lbl">capture settings</span>
  <div class="settings-grid">
    <div class="setting-card">
      <label for="sel-res">Resolution</label>
      <select id="sel-res" onchange="setResolution(this.value)">
        <option value="11">800 × 600 (SVGA)</option>
        <option value="10">640 × 480 (VGA)</option>
        <option value="9">480 × 320 (HVGA)</option>
      </select>
    </div>
          <!-- Save parameters checkbox -->
      <div class="save-params-row">
        <input type="checkbox" id="chk-save-params">
        <label for="chk-save-params">Save stitch parameters</label>
      </div>
  </div>



  <!-- Capture -->
  <span class="lbl">capture</span>
  <div class="capture-card">
    <button class="capture-btn" id="capture-btn" onclick="doCapture()">
      <i class="ti ti-camera"></i> Capture &amp; stitch
    </button>
    <p id="status-msg">Ready — aim cameras with ~30% overlap</p>
    <div class="prog-wrap" id="prog-wrap">
      <div class="prog-bar"  id="prog-bar"></div>
    </div>
    <div id="pano-wrap">
      <img id="pano-img" src="" alt="Stitched panorama">
      <a id="dl-link" class="dl-link" href="" download>
        <i class="ti ti-download"></i> Download panorama
      </a>
    </div>
  </div>

  <!-- Gallery -->
  <div class="gallery-hdr">
    <span class="lbl" style="margin:0">your captures</span>
    <span class="muted" id="g-count" style="font-size:12px"></span>
  </div>
  <div class="gallery-grid" id="g-grid"></div>

</main>

<script>
// ── status ───────────────────────────────────────────────────────────────────
async function refreshStatus() {
  const d = await api('/api/status');
  if (!d) return;
  ['cam1','cam2'].forEach((k, i) => {
    document.getElementById('pill-'+k).className = 'pill '+(d[k].online ? 'online':'offline');
    document.getElementById('ip'+(i+1)).textContent = d[k].ip;
  });
}

// ── resolution ───────────────────────────────────────────────────────────────
async function setResolution(val) {
  await api('/api/resolution', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ val })
  });
}

// ── capture ──────────────────────────────────────────────────────────────────
async function doCapture() {
  const btn  = document.getElementById('capture-btn');
  const msg  = document.getElementById('status-msg');
  const pw   = document.getElementById('prog-wrap');
  const pb   = document.getElementById('prog-bar');
  const wrap = document.getElementById('pano-wrap');

  btn.disabled = true;
  msg.className = '';
  pw.classList.add('on');
  wrap.style.display = 'none';

  const steps = [
    [15, 'Fetching camera images…'],
    [45, 'Transferring to server…'],
    [70, 'Detecting features…'],
    [90, 'Stitching panorama…'],
  ];
  let si = 0;
  const tick = setInterval(() => {
    if (si < steps.length) {
      pb.style.width   = steps[si][0] + '%';
      msg.textContent  = steps[si][1];
      si++;
    }
  }, 1300);

  const data = await api('/api/capture', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      save_parameters: document.getElementById('chk-save-params').checked,
    })
  });

  clearInterval(tick);
  pb.style.width = '100%';
  setTimeout(() => { pw.classList.remove('on'); pb.style.width = '0%'; }, 600);

  if (data && data.ok) {
    msg.className   = 'ok';
    msg.textContent = 'Done! Panorama generated successfully.';
    const ts = Date.now();
    document.getElementById('pano-img').src = '/panorama?t=' + ts;
    document.getElementById('dl-link').href = '/panorama?t=' + ts;
    wrap.style.display = 'block';
    loadGallery();
  } else {
    msg.className   = 'error';
    msg.textContent = 'Error: ' + (data ? data.error : 'Server unreachable');
  }
  btn.disabled = false;
}

// ── gallery ──────────────────────────────────────────────────────────────────
async function loadGallery() {
  const data = await api('/api/gallery');
  if (!data) return;
  const grid  = document.getElementById('g-grid');
  const count = document.getElementById('g-count');
  count.textContent = data.length + ' capture' + (data.length !== 1 ? 's' : '');

  if (data.length === 0) {
    grid.innerHTML = '<div class="g-empty">No captures yet — take your first panorama above.</div>';
    return;
  }

  grid.innerHTML = data.map(item => `
    <div class="g-card" id="gc-${item.id}">
      <img class="g-thumb"
           src="/captures/${item.filename}?t=${Date.now()}"
           alt="${item.filename}"
           onerror="this.style.display='none';this.nextElementSibling.style.display='flex'">
      <div class="g-placeholder" style="display:none">
        <i class="ti ti-photo"></i>
      </div>
      <div class="g-info">
        <div class="g-name">${item.filename}</div>
        <div class="g-meta">${item.date} · ${item.size}</div>
        <div class="g-actions">
          <a class="g-dl" href="/captures/${item.filename}" download>
            <i class="ti ti-download"></i> download
          </a>
          <button class="g-del" onclick="deleteCapture(${item.id})">
            <i class="ti ti-trash"></i> delete
          </button>
        </div>
      </div>
    </div>`).join('');
}

async function deleteCapture(id) {
  if (!confirm('Delete this capture?')) return;
  const d = await api('/api/capture/' + id, { method: 'DELETE' });
  if (d && d.ok) {
    document.getElementById('gc-' + id)?.remove();
    loadGallery();
  } else {
    alert(d ? d.error : 'Delete failed');
  }
}

// ── helper ───────────────────────────────────────────────────────────────────
async function api(url, opts) {
  try { const r = await fetch(url, opts); return await r.json(); }
  catch(e) { console.error(e); return null; }
}

// ── init ─────────────────────────────────────────────────────────────────────
refreshStatus();
loadGallery();
</script>
</body></html>"""


@app.route("/")
@login_required
def index():
    return render_template_string(MAIN_HTML, css=CSS, username=session["username"])


# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/api/status")
@login_required
def api_status():
    return jsonify(check_camera_status())


@app.route("/api/resolution", methods=["POST"])
@login_required
def api_set_resolution():
    body = request.get_json(silent=True) or {}
    val  = body.get("val", "11")
    ok, err = set_resolution(val)
    return jsonify({"ok": ok, "error": err if not ok else ""})


@app.route("/api/capture", methods=["POST"])
@login_required
def api_capture():
    body            = request.get_json(silent=True) or {}
    save_parameters = bool(body.get("save_parameters", False))
    user_id         = session["user_id"]

    # unique filename per user per timestamp
    ts       = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"panorama_{user_id}_{ts}.jpg"
    out_path = os.path.join(GALLERY_DIR, filename)

    # 1. fetch images from cameras
    ok, err = sync_capture()
    if not ok:
        return jsonify({"ok": False, "error": err})

    # 2. stitch
    try:
        stitch_images(input_images=["cam1.jpg", "cam2.jpg"], out_path=out_path, save_parameters=save_parameters)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

    # 3. copy as "latest" for the preview endpoint
    shutil.copy(out_path, "panorama.jpg")

    # 4. save to database
    size = os.path.getsize(out_path)
    save_capture(user_id, filename, size)

    return jsonify({"ok": True, "file": filename})


@app.route("/api/gallery")
@login_required
def api_gallery():
    rows   = get_user_captures(session["user_id"])
    result = []
    for r in rows:
        kb       = r["size_bytes"] / 1024
        size_str = f"{kb/1024:.1f} MB" if kb > 1024 else f"{kb:.0f} KB"
        result.append({
            "id":       r["id"],
            "filename": r["filename"],
            "date":     r["date"],
            "size":     size_str,
        })
    return jsonify(result)


@app.route("/api/capture/<int:capture_id>", methods=["DELETE"])
@login_required
def api_delete_capture(capture_id):
    ok, msg = delete_capture(capture_id, session["user_id"])
    return jsonify({"ok": ok, "error": "" if ok else msg})


@app.route("/panorama")
@login_required
def panorama():
    if not os.path.exists("panorama.jpg"):
        return "No panorama yet", 404
    return send_file("panorama.jpg", mimetype="image/jpeg")


@app.route("/captures/<filename>")
@login_required
def serve_capture(filename):
    path = os.path.join(GALLERY_DIR, filename)
    if not os.path.exists(path):
        return "Not found", 404
    return send_file(path, mimetype="image/jpeg")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)