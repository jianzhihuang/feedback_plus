import base64
import json
import mimetypes
import os
import subprocess
import sys
import threading
import webbrowser
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ALLOWED_IMAGE_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.gif', '.bmp', '.webp'}


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


def collect_feedback_web(summary: str = '', timeout: int = 600):
    feedback_dir = Path.cwd() / 'feedback'
    feedback_dir.mkdir(exist_ok=True)

    result_holder = {'feedback': []}
    done_event = threading.Event()
    counter_lock = threading.Lock()
    image_counter = 0

    def build_feedback_page() -> str:
        summary_section = ''
        if summary:
            summary_section = f'''
            <section class="panel summary">
              <div class="section-title">AI 工作摘要</div>
              <div class="summary-box">{escape(summary)}</div>
            </section>
            '''

        template = """<!doctype html>
<html lang="zh-Hant">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Feedback</title>
  <style>
    :root{--bg:#f4f8fc;--panel:#ffffffee;--line:#d6e0ea;--text:#17324d;--muted:#60758a;--accent:#1f699f;--danger:#bc4e57;--shadow:0 20px 40px rgba(18,54,86,.12)}
    *{box-sizing:border-box}
    body{margin:0;font-family:"Aptos","Segoe UI","PingFang TC","Microsoft JhengHei UI",sans-serif;color:var(--text);background:radial-gradient(circle at top left,rgba(58,128,184,.18),transparent 24%),linear-gradient(180deg,#fbfdff 0%,var(--bg) 100%)}
    .page{max-width:1120px;margin:0 auto;padding:24px}
    .hero,.panel{background:var(--panel);border:1px solid var(--line);border-radius:24px;box-shadow:var(--shadow)}
    .hero{padding:28px;background:linear-gradient(135deg,#13324c 0%,#1f699f 72%,#56a1d2 100%);color:#fff}
    .hero h1{margin:14px 0 10px;font-size:clamp(30px,5vw,44px);line-height:1.05;letter-spacing:-.03em}
    .hero p{margin:0;max-width:760px;line-height:1.7;color:rgba(255,255,255,.84)}
    .eyebrow{display:inline-block;padding:7px 12px;border-radius:999px;background:rgba(255,255,255,.15);font-size:12px;letter-spacing:.08em;text-transform:uppercase}
    .chips{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}
    .chip{padding:10px 14px;border-radius:999px;background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.12);font-size:13px}
    .stack{display:grid;gap:16px;margin-top:18px}
    .grid{display:grid;grid-template-columns:minmax(0,1.6fr) minmax(320px,1fr);gap:16px}
    .panel{padding:20px}
    .section-title{font-size:22px;font-weight:700;letter-spacing:-.02em}
    .sub{margin-top:6px;color:var(--muted);font-size:13px;line-height:1.6}
    .summary-box{margin-top:14px;padding:18px;border-radius:18px;border:1px solid #d7e3ef;background:linear-gradient(180deg,#fbfdff 0%,#f2f8fd 100%);white-space:pre-wrap;word-break:break-word;line-height:1.7}
    textarea{width:100%;min-height:340px;margin-top:14px;padding:18px;border-radius:18px;border:1px solid #d7e3ef;background:linear-gradient(180deg,#ffffff 0%,#f8fbfe 100%);font:inherit;font-size:15px;line-height:1.7;color:var(--text);resize:vertical;outline:none}
    textarea:focus{border-color:rgba(31,105,159,.55);box-shadow:0 0 0 4px rgba(31,105,159,.12)}
    .dropzone{margin-top:14px;padding:18px;border-radius:20px;border:1.5px dashed #aac0d5;background:linear-gradient(180deg,#fbfdff 0%,#f3f8fc 100%)}
    .dropzone.dragover{border-color:var(--accent);background:linear-gradient(180deg,#eff7fe 0%,#e4f1fb 100%)}
    .buttons,.actions{display:flex;flex-wrap:wrap;gap:10px}
    .buttons{margin-top:14px}
    button{appearance:none;border:none;border-radius:999px;padding:12px 18px;font:inherit;font-size:14px;cursor:pointer;transition:transform .15s ease}
    button:hover{transform:translateY(-1px)}
    button:disabled{opacity:.65;cursor:not-allowed;transform:none}
    .primary{background:linear-gradient(135deg,var(--accent) 0%,#2f79b4 100%);color:#fff}
    .secondary{background:#fff;color:var(--text);border:1px solid #d7e3ef}
    .danger{background:linear-gradient(135deg,var(--danger) 0%,#d3626a 100%);color:#fff}
    .hidden{display:none}
    .attachments{display:grid;gap:10px;margin-top:16px}
    .empty,.attachment,.status,.done{padding:16px;border-radius:16px;border:1px solid #d7e3ef;background:linear-gradient(180deg,#fbfdff 0%,#f4f8fc 100%)}
    .empty,.meta{color:var(--muted);font-size:14px;line-height:1.6}
    .attachment{display:flex;justify-content:space-between;gap:12px;align-items:center}
    .name{display:block;font-weight:700;word-break:break-all}
    .meta{margin-top:4px;font-size:12px;text-transform:uppercase;letter-spacing:.06em}
    .remove{background:#fff;color:var(--danger);border:1px solid rgba(188,78,87,.24)}
    .status,.done{line-height:1.7}
    .done{display:none;background:linear-gradient(135deg,#eef8ff 0%,#f9fcff 100%)}
    .done.show{display:block}
    @media (max-width:900px){.grid{grid-template-columns:1fr}textarea{min-height:240px}}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
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
      __SUMMARY_SECTION__
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
        <div class="sub" id="statusHint">快捷鍵：Ctrl/Cmd + Enter 提交，Ctrl/Cmd + V 貼上圖片。圖片會儲存到 __FEEDBACK_DIR__。</div>
        <div class="done" id="doneBox"></div>
        <div class="actions" style="margin-top:16px">
          <button class="primary" id="submitButton" type="button">提交給 AI</button>
          <button class="danger" id="cancelButton" type="button">取消</button>
        </div>
      </section>
    </div>
  </main>

  <script>
    const timeoutSeconds = __TIMEOUT__;
    const feedbackDir = __FEEDBACK_DIR_JSON__;
    const textInput = document.getElementById("feedbackText");
    const fileInput = document.getElementById("fileInput");
    const uploadButton = document.getElementById("uploadButton");
    const pasteButton = document.getElementById("pasteButton");
    const submitButton = document.getElementById("submitButton");
    const cancelButton = document.getElementById("cancelButton");
    const attachmentList = document.getElementById("attachmentList");
    const statusText = document.getElementById("statusText");
    const statusHint = document.getElementById("statusHint");
    const countChip = document.getElementById("countChip");
    const doneBox = document.getElementById("doneBox");
    const dropzone = document.getElementById("dropzone");

    const state = { attachments: [], busy: false, finished: false };

    function feedbackCount() {
      return state.attachments.length + (textInput.value.trim() ? 1 : 0);
    }

    function updateStatus(message = "等待提交回饋") {
      countChip.textContent = `目前 ${feedbackCount()} 項回饋`;
      statusText.textContent = message;
      if (!state.finished) {
        statusHint.textContent = `快捷鍵：Ctrl/Cmd + Enter 提交，Ctrl/Cmd + V 貼上圖片。圖片會儲存到 ${feedbackDir}`;
      }
      submitButton.disabled = state.busy || state.finished || feedbackCount() === 0;
      uploadButton.disabled = state.busy || state.finished;
      pasteButton.disabled = state.busy || state.finished;
      cancelButton.disabled = state.busy || state.finished;
      textInput.disabled = state.finished;
    }

    function setBusy(flag) {
      state.busy = flag;
      updateStatus(statusText.textContent);
    }

    function renderAttachments() {
      if (!state.attachments.length) {
        attachmentList.innerHTML = '<div class="empty">目前還沒有圖片。你可以拖曳、選檔，或直接貼上截圖。</div>';
        updateStatus();
        return;
      }

      attachmentList.innerHTML = "";
      state.attachments.forEach((item) => {
        const row = document.createElement("div");
        row.className = "attachment";
        row.innerHTML = `
          <div>
            <span class="name">${item.name}</span>
            <div class="meta">${item.source === "paste" ? "clipboard paste" : "local upload"}</div>
          </div>
          <button type="button" class="remove">移除</button>
        `;
        row.querySelector(".remove").addEventListener("click", () => {
          state.attachments = state.attachments.filter((entry) => entry.id !== item.id);
          renderAttachments();
          updateStatus("已移除圖片");
        });
        attachmentList.appendChild(row);
      });

      updateStatus();
    }

    function addFiles(files, source) {
      const validFiles = Array.from(files || []).filter((file) => file && file.type && file.type.startsWith("image/"));
      if (!validFiles.length) {
        updateStatus("沒有偵測到可加入的圖片");
        return;
      }

      const now = Date.now();
      validFiles.forEach((file, index) => {
        const ext = (file.type.split("/")[1] || "png").replace("jpeg", "jpg");
        state.attachments.push({
          id: `${now}-${index}-${Math.random().toString(16).slice(2)}`,
          file,
          source,
          name: file.name || `image-${now}-${index + 1}.${ext}`
        });
      });

      renderAttachments();
      updateStatus(`已加入 ${validFiles.length} 張圖片`);
    }

    function fileToDataUrl(file) {
      return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onload = () => resolve({
          name: file.name,
          mime_type: file.type,
          data_url: reader.result
        });
        reader.onerror = () => reject(new Error(`無法讀取檔案：${file.name}`));
        reader.readAsDataURL(file);
      });
    }

    async function readClipboardImages() {
      if (!navigator.clipboard || !navigator.clipboard.read) {
        updateStatus("這個瀏覽器不支援按鈕讀取剪貼簿，請直接按 Ctrl/Cmd + V");
        return;
      }

      try {
        const items = await navigator.clipboard.read();
        const files = [];
        let index = 0;
        for (const item of items) {
          for (const type of item.types) {
            if (!type.startsWith("image/")) {
              continue;
            }
            const blob = await item.getType(type);
            const ext = (type.split("/")[1] || "png").replace("jpeg", "jpg");
            files.push(new File([blob], `clipboard-${Date.now()}-${index + 1}.${ext}`, { type }));
            index += 1;
          }
        }

        if (!files.length) {
          updateStatus("剪貼簿裡沒有圖片");
          return;
        }

        addFiles(files, "paste");
      } catch (error) {
        updateStatus("無法直接讀取剪貼簿，請改用 Ctrl/Cmd + V 貼上圖片");
      }
    }

    async function submitFeedback() {
      if (state.busy || state.finished) {
        return;
      }

      const text = textInput.value.trim();
      if (!text && !state.attachments.length) {
        updateStatus("請先輸入文字或加入圖片");
        return;
      }

      setBusy(true);
      updateStatus("正在提交回饋...");

      try {
        const images = await Promise.all(
          state.attachments.map((item) => fileToDataUrl(item.file).then((payload) => ({ ...payload, source: item.source })))
        );
        const response = await fetch("/api/submit", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text, images })
        });
        const payload = await response.json();
        if (!response.ok || !payload.ok) {
          throw new Error(payload.error || "提交失敗");
        }

        state.finished = true;
        doneBox.classList.add("show");
        doneBox.innerHTML = `<strong>已提交完成。</strong><br>共送出 ${payload.count} 項回饋。終端已收到結果，這個頁面現在可以直接關閉。`;
        updateStatus(`提交完成，共 ${payload.count} 項回饋`);
      } catch (error) {
        updateStatus(`提交失敗：${error.message}`);
      } finally {
        setBusy(false);
      }
    }

    async function cancelFeedback() {
      if (state.busy || state.finished) {
        return;
      }

      setBusy(true);
      updateStatus("正在取消...");
      try {
        await fetch("/api/cancel", { method: "POST" });
        state.finished = true;
        doneBox.classList.add("show");
        doneBox.innerHTML = "<strong>已取消。</strong><br>這次沒有送出任何回饋，終端會收到取消結果。";
        updateStatus("已取消回饋");
      } catch (error) {
        updateStatus("取消失敗，請重新嘗試");
      } finally {
        setBusy(false);
      }
    }

    document.addEventListener("paste", (event) => {
      const files = Array.from(event.clipboardData?.items || [])
        .filter((item) => item.type && item.type.startsWith("image/"))
        .map((item) => item.getAsFile())
        .filter(Boolean);
      if (!files.length) {
        return;
      }
      event.preventDefault();
      addFiles(files, "paste");
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        submitFeedback();
      }
    });

    textInput.addEventListener("input", () => updateStatus());
    uploadButton.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
      addFiles(fileInput.files, "upload");
      fileInput.value = "";
    });
    pasteButton.addEventListener("click", readClipboardImages);
    submitButton.addEventListener("click", submitFeedback);
    cancelButton.addEventListener("click", cancelFeedback);

    dropzone.addEventListener("dragover", (event) => {
      event.preventDefault();
      dropzone.classList.add("dragover");
    });
    dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
    dropzone.addEventListener("drop", (event) => {
      event.preventDefault();
      dropzone.classList.remove("dragover");
      addFiles(event.dataTransfer?.files, "upload");
    });

    if (timeoutSeconds > 0) {
      const deadline = Date.now() + timeoutSeconds * 1000;
      window.setInterval(() => {
        if (state.finished) {
          return;
        }
        const remaining = Math.max(0, Math.floor((deadline - Date.now()) / 1000));
        const minutes = Math.floor(remaining / 60);
        const seconds = remaining % 60;
        statusHint.textContent = `快捷鍵：Ctrl/Cmd + Enter 提交，Ctrl/Cmd + V 貼上圖片。剩餘等待時間 ${minutes}:${String(seconds).padStart(2, "0")}，圖片會儲存到 ${feedbackDir}`;
      }, 1000);
    }

    textInput.focus();
    updateStatus();
  </script>
</body>
</html>
"""

        return (
            template
            .replace('__SUMMARY_SECTION__', summary_section)
            .replace('__TIMEOUT__', str(max(int(timeout), 0)))
            .replace('__FEEDBACK_DIR__', escape(str(feedback_dir.resolve())))
            .replace('__FEEDBACK_DIR_JSON__', json.dumps(str(feedback_dir.resolve()), ensure_ascii=False))
        )

    def next_image_path(filename: str, mime_type: str) -> Path:
        nonlocal image_counter
        with counter_lock:
            image_counter += 1
            index = image_counter

        suffix = Path(filename or '').suffix.lower()
        if suffix == '.jpe':
            suffix = '.jpg'
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            suffix = mimetypes.guess_extension(mime_type or '') or '.png'
        if suffix == '.jpe':
            suffix = '.jpg'
        if suffix not in ALLOWED_IMAGE_EXTENSIONS:
            suffix = '.png'

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        return feedback_dir / f'feedback_image_{timestamp}_{index}{suffix}'

    def save_image_from_payload(image_payload) -> str:
        if not isinstance(image_payload, dict):
            raise ValueError('图片资料格式错误')

        data_url = image_payload.get('data_url', '')
        filename = image_payload.get('name', '')
        mime_type = image_payload.get('mime_type', '')

        if not isinstance(data_url, str) or not data_url.startswith('data:image/'):
            raise ValueError('图片资料不是有效的 data URL')

        try:
            header, encoded = data_url.split(',', 1)
        except ValueError as exc:
            raise ValueError('图片资料损坏') from exc

        if ';base64' not in header:
            raise ValueError('图片资料不是 base64 编码')

        if not mime_type:
            mime_type = header[5:].split(';')[0].strip().lower()

        try:
            raw_bytes = base64.b64decode(encoded, validate=True)
        except ValueError as exc:
            raise ValueError('图片 base64 解码失败') from exc

        image_path = next_image_path(filename, mime_type)
        image_path.write_bytes(raw_bytes)
        return str(image_path.resolve())

    class FeedbackRequestHandler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            return

        def send_json(self, status_code: int, payload):
            payload_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
            self.send_response(status_code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload_bytes)))
            self.end_headers()
            self.wfile.write(payload_bytes)

        def do_GET(self):
            if self.path in {'/', '/index.html'}:
                page_bytes = build_feedback_page().encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Content-Length', str(len(page_bytes)))
                self.end_headers()
                self.wfile.write(page_bytes)
                return

            if self.path == '/favicon.ico':
                self.send_response(204)
                self.end_headers()
                return

            self.send_json(404, {'ok': False, 'error': 'Not found'})

        def do_POST(self):
            content_length = int(self.headers.get('Content-Length', '0'))
            body = self.rfile.read(content_length) if content_length else b'{}'

            try:
                payload = json.loads(body.decode('utf-8'))
            except json.JSONDecodeError:
                self.send_json(400, {'ok': False, 'error': 'JSON 格式错误'})
                return

            if self.path == '/api/submit':
                text = str(payload.get('text', '')).strip()
                images = payload.get('images', [])

                if not isinstance(images, list):
                    self.send_json(400, {'ok': False, 'error': 'images 必须是列表'})
                    return
                if not text and not images:
                    self.send_json(400, {'ok': False, 'error': '请提供反馈内容'})
                    return

                feedback_items = []
                try:
                    for image_payload in images:
                        saved_path = save_image_from_payload(image_payload)
                        feedback_items.append({
                            'type': 'image',
                            'content': saved_path,
                            'timestamp': datetime.now().isoformat()
                        })
                except ValueError as exc:
                    self.send_json(400, {'ok': False, 'error': str(exc)})
                    return
                except OSError as exc:
                    self.send_json(500, {'ok': False, 'error': f'保存图片失败: {exc}'})
                    return

                if text:
                    feedback_items.append({
                        'type': 'text',
                        'content': text,
                        'timestamp': datetime.now().isoformat()
                    })

                result_holder['feedback'] = feedback_items
                done_event.set()
                self.send_json(200, {'ok': True, 'count': len(feedback_items)})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            if self.path == '/api/cancel':
                result_holder['feedback'] = []
                done_event.set()
                self.send_json(200, {'ok': True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return

            self.send_json(404, {'ok': False, 'error': 'Not found'})

    server = ThreadingHTTPServer(('127.0.0.1', 0), FeedbackRequestHandler)
    server.daemon_threads = True
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    url = f'http://127.0.0.1:{server.server_port}/'
    if not open_feedback_page(url):
        print(f'请在浏览器打开反馈页面: {url}')

    timed_out = False
    try:
        if timeout and timeout > 0:
            timed_out = not done_event.wait(timeout)
        else:
            done_event.wait()
    finally:
        if timed_out or server_thread.is_alive():
            server.shutdown()
        server_thread.join(timeout=1)
        server.server_close()

    return result_holder['feedback']
