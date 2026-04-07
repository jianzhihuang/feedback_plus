import argparse
import base64
import hashlib
import json
import mimetypes
import os
import socket
import subprocess
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}
_HISTORY_FILE = '.feedback_history.json'
_DAEMON_STARTUP_TIMEOUT = 5.0
_RESULT_TTL = 120.0  # 結果保留秒數（防競態）

# State file 放在 home 目錄，每個專案獨立一份（以 git root hash 區隔）
_GLOBAL_STATE_DIR = Path.home() / '.feedback_plus'


def _project_key() -> str:
    """
    專案識別碼（優先順序）：
    1. 環境變數 FEEDBACK_PROJECT_KEY（使用者手動指定）
    2. git rev-parse --show-toplevel（git 專案）
    3. 往上找專案標記檔（package.json / pyproject.toml / go.mod 等）
    4. CWD（fallback）
    """
    # 1. 環境變數覆蓋
    env_key = os.environ.get('FEEDBACK_PROJECT_KEY', '').strip()
    if env_key:
        return hashlib.md5(env_key.encode()).hexdigest()[:8]

    # 2. git root
    try:
        r = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True, text=True, timeout=2,
        )
        if r.returncode == 0 and r.stdout.strip():
            return hashlib.md5(r.stdout.strip().encode()).hexdigest()[:8]
    except Exception:
        pass

    # 3. 找專案標記檔（往上至 home 或 /）
    _MARKERS = {
        'package.json', 'pyproject.toml', 'setup.py', 'setup.cfg',
        'Cargo.toml', 'go.mod', 'pom.xml', 'build.gradle',
        'Makefile', 'CMakeLists.txt', 'composer.json',
    }
    cwd = Path.cwd()
    home = Path.home()
    candidate = cwd
    while True:
        if any((candidate / m).exists() for m in _MARKERS):
            return hashlib.md5(str(candidate).encode()).hexdigest()[:8]
        parent = candidate.parent
        if parent == candidate or candidate == home:
            break
        candidate = parent

    # 4. CWD fallback
    return hashlib.md5(str(cwd).encode()).hexdigest()[:8]


def _preferred_port(key: str) -> int:
    """每個專案有一致的 port（17100–17999），重啟後仍是同一 URL。"""
    return 17100 + (int(key, 16) % 900)


def _state_path(_feedback_dir: Path = None) -> Path:
    _GLOBAL_STATE_DIR.mkdir(exist_ok=True)
    return _GLOBAL_STATE_DIR / f'{_project_key()}.json'


def _read_state(_feedback_dir: Path = None):
    try:
        p = _state_path()
        if p.exists():
            return json.loads(p.read_text('utf-8'))
    except Exception:
        pass
    return None


def _write_state(_feedback_dir: Path, port: int, token: str,
                 instance_id: str) -> None:
    _state_path().write_text(
        json.dumps({'port': port, 'token': token,
                    'instance_id': instance_id}),
        'utf-8',
    )


def _alive(port: int) -> bool:
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1):
            return True
    except OSError:
        return False


def _request(port: int, token: str, method: str, path: str, body=None) -> dict:
    import http.client
    conn = http.client.HTTPConnection('127.0.0.1', port, timeout=5)
    headers = {'X-Daemon-Token': token}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    conn.request(method, path, body=data, headers=headers)
    result = json.loads(conn.getresponse().read())
    conn.close()
    return result


def open_feedback_page(url: str) -> bool:
    try:
        if os.name == 'nt':
            os.startfile(url)
            return True
        if sys.platform == 'darwin':
            subprocess.Popen(['open', url])
            return True
        return webbrowser.open(url, new=1, autoraise=True)
    except Exception:
        return False


# ── Public API ─────────────────────────────────────────────────────────────────

def collect_feedback_web(summary: str = '', timeout: int = 600):
    """
    收集使用者回饋 - Web模式（持久化伺服器）

    同一 terminal session 複用同一個 port，瀏覽器 tab 自動重置表單，
    不會每次開啟新的 port 或新的 tab。
    """
    feedback_dir = Path.cwd() / 'feedback'
    feedback_dir.mkdir(exist_ok=True)

    state = _read_state()
    port, token = None, None
    is_reuse = False

    # daemon 存活就直接複用（不比對 session_key，因為各工具呼叫的 SID 不穩定）
    if state:
        p, t = state.get('port', 0), state.get('token', '')
        if p and t and _alive(p):
            try:
                _request(p, t, 'GET', '/api/ping')
                port, token = p, t
                is_reuse = True
            except Exception:
                port = None

    if port is None:
        port, token = _spawn_daemon(feedback_dir)

    # 啟動新一輪回饋（取得 session_id）
    try:
        resp = _request(port, token, 'POST', '/api/new-session', {'summary': summary, 'timeout': timeout})
        session_id = resp['session_id']
    except Exception as exc:
        raise RuntimeError(f'無法連線至回饋伺服器: {exc}')

    url = f'http://127.0.0.1:{port}/'
    if not is_reuse:
        # 第一次：開啟瀏覽器
        if not open_feedback_page(url):
            print(f'請在瀏覽器開啟回饋頁面: {url}', flush=True)
    # 複用時：瀏覽器 tab 透過 JS 輪詢（每 1.5s）偵測 session_id 改變，自動重置表單
    # 不呼叫 open，因為會開新視窗/tab

    print(f'⏳ 等待使用者在瀏覽器回饋… {url}', flush=True)
    return _wait_result(port, token, timeout, session_id)


# ── Client internals ───────────────────────────────────────────────────────────

def _spawn_daemon(feedback_dir: Path):
    """啟動獨立 daemon 伺服器，回傳 (port, token)。"""
    try:
        _state_path(feedback_dir).unlink()
    except FileNotFoundError:
        pass

    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),
        '--daemon',
        '--feedback-dir', str(feedback_dir),
    ]
    kw = {
        'stdout': subprocess.DEVNULL, 'stderr': subprocess.DEVNULL,
        'stdin': subprocess.DEVNULL, 'close_fds': True,
    }
    if os.name == 'nt':
        kw['creationflags'] = 0x00000008  # DETACHED_PROCESS
    else:
        kw['start_new_session'] = True

    subprocess.Popen(cmd, **kw)

    deadline = time.monotonic() + _DAEMON_STARTUP_TIMEOUT
    while time.monotonic() < deadline:
        s = _read_state(feedback_dir)
        if s:
            p, t = s.get('port', 0), s.get('token', '')
            if p and t and _alive(p):
                return p, t
        time.sleep(0.1)

    raise RuntimeError('回饋伺服器啟動逾時（5 秒）')


def _wait_result(port: int, token: str, timeout: int, session_id: str) -> list:
    """輪詢直到伺服器有此 session 的結果。"""
    deadline = time.monotonic() + timeout if timeout and timeout > 0 else None
    while True:
        if deadline and time.monotonic() > deadline:
            try:
                _request(port, token, 'POST', '/api/cancel',
                         {'session_id': session_id})
            except Exception:
                pass
            return []
        try:
            r = _request(port, token, 'GET', f'/api/result/{session_id}')
            if r.get('ready'):
                return r.get('feedback', [])
        except Exception:
            pass
        time.sleep(0.5)


# ── History persistence ────────────────────────────────────────────────────────

def _load_history(feedback_dir: Path) -> list:
    try:
        p = feedback_dir / _HISTORY_FILE
        if p.exists():
            return json.loads(p.read_text('utf-8'))
    except Exception:
        pass
    return []


def _save_history(feedback_dir: Path, history: list) -> None:
    try:
        (feedback_dir / _HISTORY_FILE).write_text(
            json.dumps(history, ensure_ascii=False, indent=2), 'utf-8')
    except Exception:
        pass


# ── Server (daemon) ────────────────────────────────────────────────────────────

def _run_daemon(feedback_dir: Path) -> None:
    """作為持久化 HTTP daemon 執行。透過 --daemon flag 呼叫。"""
    token = str(uuid.uuid4())
    instance_id = str(uuid.uuid4())

    shared = {
        'lock': threading.Lock(),
        'session_id': '',
        'summary': '',
        'status': 'idle',   # idle | active | done
        'feedback': [],
        'results': {},       # {session_id: (feedback_list, expiry_time)}
        'history': _load_history(feedback_dir),  # 從檔案載入歷史
        'image_counter': 0,
        'timeout': 0,        # 本輪 timeout 秒數（0=無限制）
    }

    def reset_session(summary: str, timeout: int = 0) -> str:
        sid = str(uuid.uuid4())
        with shared['lock']:
            shared['session_id'] = sid
            shared['summary'] = summary
            shared['status'] = 'active'
            shared['feedback'] = []
            shared['timeout'] = max(0, int(timeout))
        return sid

    def store_result(sid: str, feedback: list) -> None:
        now = time.monotonic()
        with shared['lock']:
            shared['results'][sid] = (feedback, now + _RESULT_TTL)
            # 清除過期結果
            shared['results'] = {
                k: v for k, v in shared['results'].items() if v[1] > now
            }

    def append_history(sid: str, summary: str, items: list, cancelled: bool) -> None:
        text = ''
        img_count = 0
        for item in items:
            if item['type'] == 'text':
                text = item['content']
            elif item['type'] == 'image':
                img_count += 1
        entry = {
            'session_id': sid,
            'summary': summary,
            'feedback_text': text,
            'image_count': img_count,
            'timestamp': datetime.now().isoformat(),
            'cancelled': cancelled,
        }
        with shared['lock']:
            shared['history'].append(entry)
            h_copy = list(shared['history'])
        _save_history(feedback_dir, h_copy)

    # ── HTML builder ───────────────────────────────────────────────────────────
    def build_page() -> str:
        with shared['lock']:
            summary = shared['summary']
            sess_id = shared['session_id']

        fb_dir_esc = escape(str(feedback_dir.resolve()))
        fb_dir_json = json.dumps(str(feedback_dir.resolve()), ensure_ascii=False)
        tok_json = json.dumps(token)
        sid_json = json.dumps(sess_id)

        summary_inner_html = (
            f'<div class="summary-box">{escape(summary)}</div>'
            if summary
            else '<div class="no-summary">（AI 尚未提供摘要）</div>'
        )

        return f"""<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Feedback</title>
  <style>
    :root{{--bg:#f4f8fc;--panel:#ffffffee;--line:#d6e0ea;--text:#17324d;--muted:#60758a;--accent:#1f699f;--danger:#bc4e57;--shadow:0 20px 40px rgba(18,54,86,.12)}}
    *{{box-sizing:border-box}}
    body{{margin:0;font-family:"Aptos","Segoe UI","PingFang TC","Microsoft JhengHei UI",sans-serif;color:var(--text);background:radial-gradient(circle at top left,rgba(58,128,184,.18),transparent 24%),linear-gradient(180deg,#fbfdff 0%,var(--bg) 100%)}}
    .page{{max-width:1120px;margin:0 auto;padding:24px}}
    .hero,.panel{{background:var(--panel);border:1px solid var(--line);border-radius:24px;box-shadow:var(--shadow)}}
    .hero{{padding:28px;background:linear-gradient(135deg,#13324c 0%,#1f699f 72%,#56a1d2 100%);color:#fff}}
    .hero h1{{margin:14px 0 10px;font-size:clamp(30px,5vw,44px);line-height:1.05;letter-spacing:-.03em}}
    .hero p{{margin:0;max-width:760px;line-height:1.7;color:rgba(255,255,255,.84)}}
    .eyebrow{{display:inline-block;padding:7px 12px;border-radius:999px;background:rgba(255,255,255,.15);font-size:12px;letter-spacing:.08em;text-transform:uppercase}}
    .chips{{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}}
    .chip{{padding:10px 14px;border-radius:999px;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.12);font-size:13px}}
    .stack{{display:grid;gap:16px;margin-top:18px}}
    .grid{{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(320px,1fr);gap:16px}}
    .panel{{padding:20px}}
    .section-title{{font-size:22px;font-weight:700;letter-spacing:-.02em}}
    .sub{{margin-top:6px;color:var(--muted);font-size:13px;line-height:1.6}}
    .summary-box{{margin-top:14px;padding:18px;border-radius:18px;border:1px solid #d7e3ef;background:linear-gradient(180deg,#fbfdff 0%,#f2f8fd 100%);white-space:pre-wrap;word-break:break-word;line-height:1.7}}
    textarea{{width:100%;min-height:340px;margin-top:14px;padding:18px;border-radius:18px;border:1px solid #d7e3ef;background:linear-gradient(180deg,#ffffff 0%,#f8fbfe 100%);font:inherit;font-size:15px;line-height:1.7;color:var(--text);resize:vertical;outline:none}}
    textarea:focus{{border-color:rgba(31,105,159,.55);box-shadow:0 0 0 4px rgba(31,105,159,.12)}}
    textarea:disabled{{border-color:#d7e3ef !important;box-shadow:none !important;opacity:.55;cursor:not-allowed;color:var(--muted);background:linear-gradient(180deg,#f6f8fa 0%,#f0f4f8 100%)}}
    .dropzone{{margin-top:14px;padding:18px;border-radius:20px;border:1.5px dashed #aac0d5;background:linear-gradient(180deg,#fbfdff 0%,#f3f8fc 100%)}}
    .dropzone.dragover{{border-color:var(--accent);background:linear-gradient(180deg,#eff7fe 0%,#e4f1fb 100%)}}
    .buttons,.actions{{display:flex;flex-wrap:wrap;gap:10px}}
    .buttons{{margin-top:14px}}
    button{{appearance:none;border:none;border-radius:999px;padding:12px 18px;font:inherit;font-size:14px;cursor:pointer;transition:transform .15s ease}}
    button:hover{{transform:translateY(-1px)}}
    button:disabled{{opacity:.65;cursor:not-allowed;transform:none}}
    .primary{{background:linear-gradient(135deg,var(--accent) 0%,#2f79b4 100%);color:#fff}}
    .secondary{{background:#fff;color:var(--text);border:1px solid #d7e3ef}}
    .danger{{background:linear-gradient(135deg,var(--danger) 0%,#d3626a 100%);color:#fff}}
    .hidden{{display:none}}
    .attachments{{display:grid;gap:10px;margin-top:16px}}
    .empty,.attachment,.status,.done{{padding:16px;border-radius:16px;border:1px solid #d7e3ef;background:linear-gradient(180deg,#fbfdff 0%,#f4f8fc 100%)}}
    .empty,.meta{{color:var(--muted);font-size:14px;line-height:1.6}}
    .attachment{{display:flex;justify-content:space-between;gap:12px;align-items:center}}
    .name{{display:block;font-weight:700;word-break:break-all}}
    .meta{{margin-top:4px;font-size:12px;text-transform:uppercase;letter-spacing:.06em}}
    .remove{{background:#fff;color:var(--danger);border:1px solid rgba(188,78,87,.24)}}
    .status,.done{{line-height:1.7}}
    .done{{display:none;background:linear-gradient(135deg,#eef8ff 0%,#f9fcff 100%)}}
    .done.show{{display:block}}
    .tab-bar{{display:flex;gap:2px;border-bottom:1px solid var(--line);margin:-20px -20px 16px;padding:12px 20px 0;background:linear-gradient(180deg,#f8fbff 0%,#f2f7fd 100%);border-radius:24px 24px 0 0}}
    .tab{{appearance:none;border:none;background:none;padding:9px 20px;font:inherit;font-size:14px;font-weight:600;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;margin-bottom:-1px;border-radius:8px 8px 0 0;transition:color .15s,border-color .15s}}
    .tab:hover{{color:var(--text)}}
    .tab.tab-active{{color:var(--accent);border-bottom-color:var(--accent)}}
    .no-summary{{padding:14px 0;color:var(--muted);font-size:14px}}
    .history-list{{display:grid;gap:10px;margin-top:4px}}
    .history-empty{{color:var(--muted);font-size:14px;padding:20px 0;text-align:center}}
    .history-entry{{padding:14px 16px;border-radius:14px;border:1px solid #d7e3ef;background:linear-gradient(180deg,#fbfdff 0%,#f4f8fc 100%);display:grid;gap:6px}}
    .history-row{{display:flex;justify-content:space-between;align-items:center;gap:8px}}
    .history-time{{font-size:12px;color:var(--muted);letter-spacing:.04em}}
    .history-summary{{font-size:13px;color:var(--muted);white-space:pre-wrap;word-break:break-word;line-height:1.5;max-height:58px;overflow:hidden}}
    .history-feedback{{font-size:14px;line-height:1.6;white-space:pre-wrap;word-break:break-word}}
    .htag{{display:inline-block;padding:2px 10px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:.06em}}
    .htag-done{{background:#e8f4ea;color:#2d7a3a}}.htag-cancel{{background:#fde8e8;color:#bc4e57}}
    .wait-timer{{position:absolute;top:20px;right:24px;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.25);border-radius:14px;padding:10px 18px;color:#fff;font-size:14px;font-weight:600;letter-spacing:.05em;font-variant-numeric:tabular-nums}}
    @media (max-width:900px){{.grid{{grid-template-columns:1fr}}textarea{{min-height:240px}}.wait-timer{{position:static;margin-bottom:12px;display:inline-block}}}}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero" style="position:relative">
      <div id="waitTimer" class="wait-timer hidden"></div>
      <span class="eyebrow">AI Feedback Portal</span>
      <h1>把文字和截圖一次交給 AI</h1>
      <p>這個頁面只在本機 localhost 運作。你可以輸入文字、拖曳圖片、上傳檔案，或直接用 Ctrl/Cmd + V 貼上截圖，最後用 Ctrl/Cmd + Enter 提交。</p>
      <div class="chips">
        <span class="chip">本機頁面</span>
        <span class="chip">圖片會存到 feedback 資料夾</span>
        <span class="chip" id="countChip">目前 0 項回饋</span>
      </div>
    </section>

    <div class="stack">
      <div class="panel" id="infoCard">
        <div class="tab-bar">
          <button class="tab tab-active" id="tabSummary">AI 工作摘要</button>
          <button class="tab" id="tabHistory">📋 紀錄</button>
        </div>
        <div id="summaryContent">{summary_inner_html}</div>
        <div id="historyContent" class="hidden"></div>
      </div>
      <section class="grid">
        <section class="panel">
          <div class="section-title">文字回饋</div>
          <div class="sub">可以直接描述問題、補充需求，或告訴 AI 下一步要做什麼。</div>
          <textarea id="feedbackText" placeholder="輸入你的回饋內容..."></textarea>
        </section>
        <section class="panel">
          <div class="section-title">圖片回饋</div>
          <div class="sub">支援拖曳、上傳與剪貼簿貼上。剛截圖的話，直接 Ctrl/Cmd + V 即可。</div>
          <div class="dropzone" id="dropzone">
            <div>把圖片拖進來，或用下面按鈕加入。</div>
            <div class="buttons">
              <button class="secondary" id="uploadButton" type="button">上傳圖片</button>
              <button class="secondary" id="pasteButton" type="button">讀取剪貼簿圖片</button>
            </div>
            <input id="fileInput" class="hidden" type="file" accept="image/*" multiple>
          </div>
          <div class="attachments" id="attachmentList">
            <div class="empty">目前還沒有圖片。你可以拖曳、選檔，或直接貼上截圖。</div>
          </div>
        </section>
      </section>
      <section class="panel">
        <div class="status" id="statusText">等待提交回饋</div>
        <div class="sub" id="statusHint">快捷鍵：Ctrl/Cmd + Enter 提交，Ctrl/Cmd + V 貼上圖片。圖片會儲存到 {fb_dir_esc}。</div>
        <div class="done" id="doneBox"></div>
        <div class="actions" style="margin-top:16px">
          <button class="primary" id="submitButton" type="button">提交給 AI</button>
          <button class="danger" id="cancelButton" type="button">取消</button>
        </div>
      </section>
    </div>
  </main>

  <script>
    const TOKEN = {tok_json};
    const FEEDBACK_DIR = {fb_dir_json};
    let currentSessionId = {sid_json};

    const textInput    = document.getElementById("feedbackText");
    const fileInput    = document.getElementById("fileInput");
    const uploadButton = document.getElementById("uploadButton");
    const pasteButton  = document.getElementById("pasteButton");
    const submitButton = document.getElementById("submitButton");
    const cancelButton = document.getElementById("cancelButton");
    const attachmentList = document.getElementById("attachmentList");
    const statusText   = document.getElementById("statusText");
    const statusHint   = document.getElementById("statusHint");
    const countChip    = document.getElementById("countChip");
    const doneBox      = document.getElementById("doneBox");
    const dropzone     = document.getElementById("dropzone");
    const summaryContent = document.getElementById("summaryContent");
    const historyContent = document.getElementById("historyContent");
    const tabSummary   = document.getElementById("tabSummary");
    const tabHistory   = document.getElementById("tabHistory");
    const waitTimer    = document.getElementById("waitTimer");

    // ── Wait timer ────────────────────────────────────────────────────────────
    let _timerInterval = null;
    function startTimer(timeoutSec) {{
      clearInterval(_timerInterval);
      if (!timeoutSec || timeoutSec <= 0) {{ waitTimer.classList.add('hidden'); return; }}
      let remaining = timeoutSec;
      waitTimer.classList.remove('hidden');
      function tick() {{
        const mm = String(Math.floor(remaining / 60)).padStart(2, '0');
        const ss = String(remaining % 60).padStart(2, '0');
        waitTimer.textContent = `⏱ 剩餘 ${{mm}}:${{ss}}`;
        if (remaining <= 0) {{
          clearInterval(_timerInterval);
          cancelFeedback();
        }}
        remaining--;
      }}
      tick();
      _timerInterval = setInterval(tick, 1000);
    }}
    function stopTimer() {{
      clearInterval(_timerInterval);
      waitTimer.classList.add('hidden');
    }}

    // ── Tab switching ─────────────────────────────────────────────────────────
    tabSummary.addEventListener('click', () => {{
      tabSummary.classList.add('tab-active'); tabHistory.classList.remove('tab-active');
      summaryContent.classList.remove('hidden'); historyContent.classList.add('hidden');
    }});
    tabHistory.addEventListener('click', async () => {{
      tabHistory.classList.add('tab-active'); tabSummary.classList.remove('tab-active');
      historyContent.classList.remove('hidden'); summaryContent.classList.add('hidden');
      historyContent.innerHTML = '<div class="history-empty">載入中…</div>';
      try {{
        const resp = await fetch('/api/history', {{ headers: {{ 'X-Daemon-Token': TOKEN }} }});
        const data = await resp.json();
        renderHistory(data.history || []);
      }} catch(_) {{ historyContent.innerHTML = '<div class="history-empty">載入失敗</div>'; }}
    }});
    function renderHistory(entries) {{
      if (!entries.length) {{
        historyContent.innerHTML = '<div class="history-empty">尚無紀錄。</div>';
        return;
      }}
      const items = [...entries].reverse().map(e => {{
        const timeStr = new Date(e.timestamp).toLocaleString('zh-TW', {{hour12:false}});
        const tag = e.cancelled
          ? '<span class="htag htag-cancel">已取消</span>'
          : '<span class="htag htag-done">已提交</span>';
        const summaryPart = e.summary
          ? `<div class="history-summary">📋 ${{h(e.summary)}}</div>` : '';
        const imgPart = e.image_count > 0 ? ` ＋ ${{e.image_count}} 張圖片` : '';
        const feedbackPart = e.feedback_text
          ? `<div class="history-feedback">💬 ${{h(e.feedback_text)}}${{imgPart}}</div>`
          : (e.image_count > 0 ? `<div class="history-feedback">🖼️ ${{e.image_count}} 張圖片</div>` : '');
        return `<div class="history-entry">
          <div class="history-row"><span class="history-time">${{h(timeStr)}}</span>${{tag}}</div>
          ${{summaryPart}}${{feedbackPart}}
        </div>`;
      }}).join('');
      historyContent.innerHTML = `<div class="history-list">${{items}}</div>`;
    }}
    // ─────────────────────────────────────────────────────────────────────────

    const state = {{ attachments: [], busy: false, finished: false }};

    function h(s) {{
      return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    }}

    function feedbackCount() {{
      return state.attachments.length + (textInput.value.trim() ? 1 : 0);
    }}

    function updateStatus(message = "等待提交回饋") {{
      countChip.textContent = `目前 ${{feedbackCount()}} 項回饋`;
      statusText.textContent = message;
      statusHint.textContent = `快捷鍵：Ctrl/Cmd + Enter 提交，Ctrl/Cmd + V 貼上圖片。圖片會儲存到 ${{FEEDBACK_DIR}}`;
      submitButton.disabled = state.busy || state.finished || feedbackCount() === 0;
      uploadButton.disabled = state.busy || state.finished;
      pasteButton.disabled  = state.busy || state.finished;
      cancelButton.disabled = state.busy || state.finished;
      textInput.disabled    = state.finished;
    }}

    function setBusy(flag) {{ state.busy = flag; updateStatus(statusText.textContent); }}

    function renderAttachments() {{
      if (!state.attachments.length) {{
        attachmentList.innerHTML = '<div class="empty">目前還沒有圖片。你可以拖曳、選檔，或直接貼上截圖。</div>';
        updateStatus(); return;
      }}
      attachmentList.innerHTML = "";
      state.attachments.forEach((item) => {{
        const row = document.createElement("div");
        row.className = "attachment";
        row.innerHTML = `<div><span class="name">${{item.name}}</span><div class="meta">${{item.source === "paste" ? "clipboard paste" : "local upload"}}</div></div><button type="button" class="remove">移除</button>`;
        row.querySelector(".remove").addEventListener("click", () => {{
          state.attachments = state.attachments.filter((e) => e.id !== item.id);
          renderAttachments(); updateStatus("已移除圖片");
        }});
        attachmentList.appendChild(row);
      }});
      updateStatus();
    }}

    function addFiles(files, source) {{
      const valid = Array.from(files || []).filter((f) => f && f.type && f.type.startsWith("image/"));
      if (!valid.length) {{ updateStatus("沒有偵測到可加入的圖片"); return; }}
      const now = Date.now();
      valid.forEach((file, i) => {{
        const ext = (file.type.split("/")[1] || "png").replace("jpeg","jpg");
        state.attachments.push({{ id:`${{now}}-${{i}}-${{Math.random().toString(16).slice(2)}}`, file, source, name: file.name || `image-${{now}}-${{i+1}}.${{ext}}` }});
      }});
      renderAttachments(); updateStatus(`已加入 ${{valid.length}} 張圖片`);
    }}

    function fileToDataUrl(file) {{
      return new Promise((res, rej) => {{
        const r = new FileReader();
        r.onload  = () => res({{ name: file.name, mime_type: file.type, data_url: r.result }});
        r.onerror = () => rej(new Error(`無法讀取檔案：${{file.name}}`));
        r.readAsDataURL(file);
      }});
    }}

    async function readClipboardImages() {{
      if (!navigator.clipboard?.read) {{ updateStatus("這個瀏覽器不支援按鈕讀取剪貼簿，請直接按 Ctrl/Cmd + V"); return; }}
      try {{
        const items = await navigator.clipboard.read();
        const files = []; let idx = 0;
        for (const item of items) {{
          for (const type of item.types) {{
            if (!type.startsWith("image/")) continue;
            const blob = await item.getType(type);
            const ext = (type.split("/")[1] || "png").replace("jpeg","jpg");
            files.push(new File([blob], `clipboard-${{Date.now()}}-${{++idx}}.${{ext}}`, {{ type }}));
          }}
        }}
        if (!files.length) {{ updateStatus("剪貼簿裡沒有圖片"); return; }}
        addFiles(files, "paste");
      }} catch (_) {{ updateStatus("無法直接讀取剪貼簿，請改用 Ctrl/Cmd + V 貼上圖片"); }}
    }}

    function apiHeaders() {{
      return {{ 'Content-Type': 'application/json', 'X-Daemon-Token': TOKEN }};
    }}

    async function submitFeedback() {{
      if (state.busy || state.finished) return;
      const text = textInput.value.trim();
      if (!text && !state.attachments.length) {{ updateStatus("請先輸入文字或加入圖片"); return; }}
      setBusy(true); updateStatus("正在提交回饋...");
      try {{
        const images = await Promise.all(
          state.attachments.map((item) => fileToDataUrl(item.file).then((p) => ({{ ...p, source: item.source }})))
        );
        const resp = await fetch("/api/submit", {{
          method: "POST", headers: apiHeaders(),
          body: JSON.stringify({{ session_id: currentSessionId, text, images }})
        }});
        const payload = await resp.json();
        if (!resp.ok || !payload.ok) throw new Error(payload.error || "提交失敗");
        state.finished = true;
        textInput.blur();
        stopTimer();
        doneBox.classList.add("show");
        doneBox.innerHTML = `<strong>已提交完成。</strong><br>共送出 ${{payload.count}} 項回饋。終端已收到結果，等待下一次 AI 呼叫時此頁面會自動重置。`;
        updateStatus(`提交完成，共 ${{payload.count}} 項回饋`);
      }} catch (e) {{ updateStatus(`提交失敗：${{e.message}}`); }}
      finally {{ setBusy(false); }}
    }}

    async function cancelFeedback() {{
      if (state.busy || state.finished) return;
      setBusy(true); updateStatus("正在取消...");
      try {{
        await fetch("/api/cancel", {{
          method: "POST", headers: apiHeaders(),
          body: JSON.stringify({{ session_id: currentSessionId }})
        }});
        state.finished = true;
        textInput.blur();
        stopTimer();
        doneBox.classList.add("show");
        doneBox.innerHTML = "<strong>已取消。</strong><br>等待下一次 AI 呼叫時此頁面會自動重置。";
        updateStatus("已取消回饋");
      }} catch (e) {{ updateStatus("取消失敗，請重新嘗試"); }}
      finally {{ setBusy(false); }}
    }}

    // ── Session polling：偵測 AI 新一輪呼叫，自動重置表單 ──────────────────────
    function resetForm(summary, timeoutSec) {{
      state.attachments = []; state.busy = false; state.finished = false;
      textInput.value = ''; textInput.disabled = false;
      doneBox.classList.remove('show'); doneBox.innerHTML = '';
      renderAttachments(); updateStatus('等待提交回饋');
      summaryContent.innerHTML = summary
        ? `<div class="summary-box">${{h(summary)}}</div>`
        : '<div class="no-summary">（AI 尚未提供摘要）</div>';
      // 自動切回摘要 tab
      tabSummary.classList.add('tab-active'); tabHistory.classList.remove('tab-active');
      summaryContent.classList.remove('hidden'); historyContent.classList.add('hidden');
      startTimer(timeoutSec || 0);
      textInput.focus();
    }}

    // 頁面載入時若 session 已啟動，從 session-info 取得 timeout 開始倒數
    (async () => {{
      if (!currentSessionId) return;
      try {{
        const resp = await fetch('/api/session-info', {{ headers: {{ 'X-Daemon-Token': TOKEN }} }});
        if (resp.ok) {{ const d = await resp.json(); startTimer(d.timeout || 0); }}
      }} catch(_) {{}}
    }})();

    setInterval(async () => {{
      if (document.hidden) return;  // tab 在背景時暫停輪詢
      try {{
        const resp = await fetch('/api/session-info', {{ headers: {{ 'X-Daemon-Token': TOKEN }} }});
        if (!resp.ok) return;
        const data = await resp.json();
        if (data.session_id !== currentSessionId) {{
          currentSessionId = data.session_id;
          resetForm(data.summary || '', data.timeout || 0);
        }}
      }} catch (_) {{}}
    }}, 1500);
    // ─────────────────────────────────────────────────────────────────────────

    document.addEventListener("paste", (ev) => {{
      const files = Array.from(ev.clipboardData?.items || [])
        .filter((i) => i.type?.startsWith("image/")).map((i) => i.getAsFile()).filter(Boolean);
      if (!files.length) return;
      ev.preventDefault(); addFiles(files, "paste");
    }});
    document.addEventListener("keydown", (ev) => {{
      if (ev.key === "Enter" && (ev.ctrlKey || ev.metaKey)) {{ ev.preventDefault(); submitFeedback(); }}
    }});
    textInput.addEventListener("input", () => updateStatus());
    uploadButton.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {{ addFiles(fileInput.files, "upload"); fileInput.value = ""; }});
    pasteButton.addEventListener("click", readClipboardImages);
    submitButton.addEventListener("click", submitFeedback);
    cancelButton.addEventListener("click", cancelFeedback);
    dropzone.addEventListener("dragover", (ev) => {{ ev.preventDefault(); dropzone.classList.add("dragover"); }});
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (ev) => {{
      ev.preventDefault(); dropzone.classList.remove("dragover");
      addFiles(ev.dataTransfer?.files, "upload");
    }});

    textInput.focus(); updateStatus();
  </script>
</body>
</html>"""

    # ── Image helpers ──────────────────────────────────────────────────────────
    def next_image_path(filename: str, mime_type: str) -> Path:
        with shared['lock']:
            shared['image_counter'] += 1
            index = shared['image_counter']
        suffix = Path(filename or '').suffix.lower()
        if suffix == '.jpe':
            suffix = '.jpg'
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            suffix = mimetypes.guess_extension(mime_type or '') or '.png'
        if suffix == '.jpe':
            suffix = '.jpg'
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            suffix = '.png'
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        return feedback_dir / f'feedback_image_{ts}_{index}{suffix}'

    def save_image(payload) -> str:
        if not isinstance(payload, dict):
            raise ValueError('圖片資料格式錯誤')
        data_url = payload.get('data_url', '')
        if not isinstance(data_url, str) or not data_url.startswith('data:image/'):
            raise ValueError('圖片資料不是有效的 data URL')
        try:
            header, encoded = data_url.split(',', 1)
        except ValueError as exc:
            raise ValueError('圖片資料損毀') from exc
        if ';base64' not in header:
            raise ValueError('圖片資料不是 base64 編碼')
        mime = payload.get('mime_type') or header[5:].split(';')[0].strip().lower()
        try:
            raw = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError('圖片 base64 解碼失敗') from exc
        path = next_image_path(payload.get('name', ''), mime)
        path.write_bytes(raw)
        return str(path.resolve())

    # ── HTTP Handler ───────────────────────────────────────────────────────────
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            return

        def _auth(self) -> bool:
            return self.headers.get('X-Daemon-Token') == token

        def send_json(self, code, payload):
            data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ('/', '/index.html'):
                page = build_page().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(page)))
                self.end_headers()
                self.wfile.write(page)
                return
            if self.path == '/favicon.ico':
                self.send_response(204)
                self.end_headers()
                return
            if not self._auth():
                self.send_json(403, {'ok': False, 'error': 'Forbidden'})
                return
            if self.path == '/api/ping':
                self.send_json(200, {'ok': True, 'instance_id': instance_id})
                return
            if self.path == '/api/session-info':
                with shared['lock']:
                    self.send_json(200, {
                        'session_id': shared['session_id'],
                        'summary': shared['summary'],
                        'status': shared['status'],
                        'timeout': shared['timeout'],
                    })
                return
            if self.path == '/api/history':
                with shared['lock']:
                    h_copy = list(shared['history'])
                self.send_json(200, {'history': h_copy})
                return
            if self.path.startswith('/api/result/'):
                sid = self.path[len('/api/result/'):]
                with shared['lock']:
                    if sid in shared['results']:
                        fb, _ = shared['results'][sid]
                        self.send_json(200, {'ready': True, 'feedback': fb})
                        return
                    if shared['session_id'] == sid and shared['status'] == 'done':
                        self.send_json(200, {'ready': True, 'feedback': shared['feedback']})
                        return
                self.send_json(200, {'ready': False})
                return
            self.send_json(404, {'ok': False, 'error': 'Not found'})

        def do_POST(self):
            if not self._auth():
                self.send_json(403, {'ok': False, 'error': 'Forbidden'})
                return
            length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(length) if length else b'{}'
            try:
                payload = json.loads(body.decode('utf-8'))
            except json.JSONDecodeError:
                self.send_json(400, {'ok': False, 'error': 'JSON 格式錯誤'})
                return

            if self.path == '/api/new-session':
                sid = reset_session(str(payload.get('summary', '')), payload.get('timeout', 0))
                self.send_json(200, {'ok': True, 'session_id': sid})
                return

            if self.path == '/api/submit':
                caller_sid = payload.get('session_id', '')
                with shared['lock']:
                    if shared['session_id'] != caller_sid or shared['status'] != 'active':
                        self.send_json(409, {'ok': False, 'error': '會話已過期，請等待 AI 下次呼叫'})
                        return
                text = str(payload.get('text', '')).strip()
                images = payload.get('images', [])
                if not isinstance(images, list):
                    self.send_json(400, {'ok': False, 'error': 'images 必須是清單'})
                    return
                if not text and not images:
                    self.send_json(400, {'ok': False, 'error': '請提供回饋內容'})
                    return
                items = []
                try:
                    for img in images:
                        items.append({'type': 'image', 'content': save_image(img),
                                      'timestamp': datetime.now().isoformat()})
                except ValueError as exc:
                    self.send_json(400, {'ok': False, 'error': str(exc)})
                    return
                except OSError as exc:
                    self.send_json(500, {'ok': False, 'error': f'儲存圖片失敗: {exc}'})
                    return
                if text:
                    items.append({'type': 'text', 'content': text,
                                  'timestamp': datetime.now().isoformat()})
                with shared['lock']:
                    shared['feedback'] = items
                    shared['status'] = 'done'
                store_result(caller_sid, items)
                with shared['lock']:
                    _summary = shared['summary']
                append_history(caller_sid, _summary, items, False)
                self.send_json(200, {'ok': True, 'count': len(items)})
                return

            if self.path == '/api/cancel':
                caller_sid = payload.get('session_id', '')
                with shared['lock']:
                    if shared['session_id'] == caller_sid and shared['status'] == 'active':
                        shared['feedback'] = []
                        shared['status'] = 'done'
                store_result(caller_sid, [])
                with shared['lock']:
                    _summary = shared['summary']
                append_history(caller_sid, _summary, [], True)
                self.send_json(200, {'ok': True})
                return

            self.send_json(404, {'ok': False, 'error': 'Not found'})

    # ── 啟動伺服器（優先固定 port，被佔用則 fallback 隨機）──────────────────────
    try:
        server = ThreadingHTTPServer(('127.0.0.1', _preferred_port(_project_key())), Handler)
    except OSError:
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    _write_state(feedback_dir, server.server_port, token, instance_id)
    server.serve_forever()


# ── Entry point ────────────────────────────────────────────────────────────────

def _cli_main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--daemon', action='store_true')
    parser.add_argument('--feedback-dir', type=Path)
    args, _ = parser.parse_known_args()
    if args.daemon and args.feedback_dir:
        _run_daemon(args.feedback_dir)


if __name__ == '__main__':
    _cli_main()
