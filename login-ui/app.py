from flask import Flask, render_template_string, send_file, jsonify, make_response
from flask_sock import Sock
from moomoo import OpenQuoteContext, RET_OK
import socket
import threading
import os
import re

app = Flask(__name__)
sock = Sock(app)

OPEND_HOST = "opend"
OPEND_API_PORT = 11111
OPEND_TELNET_PORT = 22222
CAPTCHA = "/root/.com.moomoo.OpenD/F3CNN/PicVerifyCode.png"

terminal_history = ""
history_lock = threading.Lock()

HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Moomoo OpenD</title>
<meta name="viewport" content="width=device-width, initial-scale=1">

<style>
:root {
    --bg: #f5f7fb;
    --card: #ffffff;
    --text: #111827;
    --muted: #6b7280;
    --border: #e5e7eb;
    --shadow: 0 8px 30px rgba(0,0,0,.08);
    --green: #16a34a;
    --amber: #d97706;
    --red: #dc2626;
    --blue: #2563eb;
    --black: #0b0f16;
}

* { box-sizing: border-box; }

body {
    margin: 0;
    font-family: Arial, sans-serif;
    background: linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
    color: var(--text);
}

.wrap {
    max-width: 1080px;
    margin: 28px auto;
    padding: 0 16px 40px;
}

.topbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 18px;
    flex-wrap: wrap;
}

.titleRow {
    display: flex;
    align-items: center;
    gap: 12px;
}

h1 {
    margin: 0;
    font-size: 30px;
    line-height: 1.1;
}

.statusPill {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    padding: 7px 12px;
    border-radius: 999px;
    background: #fff;
    border: 1px solid var(--border);
    box-shadow: var(--shadow);
    font-size: 14px;
    font-weight: 700;
}

.dot {
    width: 10px;
    height: 10px;
    border-radius: 999px;
    display: inline-block;
}

.dot.waiting { background: var(--amber); box-shadow: 0 0 0 4px rgba(217,119,6,.12); }
.dot.ok      { background: var(--green); box-shadow: 0 0 0 4px rgba(22,163,74,.12); }
.dot.bad     { background: var(--red); box-shadow: 0 0 0 4px rgba(220,38,38,.12); }

.toolbar {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

button {
    appearance: none;
    border: 1px solid var(--border);
    background: #fff;
    color: var(--text);
    border-radius: 12px;
    padding: 11px 14px;
    font-size: 14px;
    font-weight: 700;
    cursor: pointer;
    transition: .15s ease;
}

button:hover {
    transform: translateY(-1px);
    box-shadow: 0 6px 20px rgba(0,0,0,.08);
}

button.primary {
    background: var(--blue);
    color: white;
    border-color: var(--blue);
}

button.success {
    background: var(--green);
    color: white;
    border-color: var(--green);
}

button.warn {
    background: #fff7ed;
    color: #9a3412;
    border-color: #fdba74;
}

button.ghost {
    background: #f9fafb;
}

.grid {
    display: grid;
    grid-template-columns: 1.1fr .9fr;
    gap: 16px;
    align-items: start;
}

@media (max-width: 920px) {
    .grid {
        grid-template-columns: 1fr;
    }
}

.card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 18px;
    box-shadow: var(--shadow);
    overflow: hidden;
}

.cardHeader {
    padding: 14px 18px;
    border-bottom: 1px solid var(--border);
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
}

.cardTitle {
    font-size: 16px;
    font-weight: 800;
}

.cardBody {
    padding: 16px;
}

.metaRow {
    display: grid;
    grid-template-columns: repeat(2, minmax(0,1fr));
    gap: 10px;
}

@media (max-width: 700px) {
    .metaRow {
        grid-template-columns: 1fr;
    }
}

.statBox {
    background: #f8fafc;
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 12px 14px;
}

.statLabel {
    color: var(--muted);
    font-size: 12px;
    margin-bottom: 6px;
    text-transform: uppercase;
    letter-spacing: .04em;
    font-weight: 700;
}

.statValue {
    font-size: 14px;
    font-weight: 700;
    word-break: break-word;
}

#terminal {
    background: var(--black);
    color: #f3f4f6;
    min-height: 440px;
    max-height: 540px;
    overflow-y: auto;
    padding: 18px;
    white-space: pre-wrap;
    font-family: Consolas, monospace;
    font-size: 15px;
    line-height: 1.35;
}

.controlGroup {
    margin-bottom: 14px;
    padding: 14px;
    border: 1px solid var(--border);
    border-radius: 14px;
    background: #fbfcfe;
}

.controlTitle {
    font-size: 14px;
    font-weight: 800;
    margin-bottom: 10px;
}

.row {
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
}

input[type="text"], input[type="password"] {
    width: 100%;
    border: 1px solid #d1d5db;
    border-radius: 12px;
    padding: 12px 14px;
    font-size: 15px;
    outline: none;
    background: white;
}

input[type="text"]:focus, input[type="password"]:focus {
    border-color: #93c5fd;
    box-shadow: 0 0 0 4px rgba(59,130,246,.10);
}

.grow {
    flex: 1 1 240px;
}

.fixed {
    flex: 0 0 auto;
}

.help {
    margin-top: 8px;
    color: var(--muted);
    font-size: 13px;
}

#captchaWrap {
    margin-top: 12px;
    display: none;
}

#captchaImg {
    max-width: 280px;
    border: 1px solid var(--border);
    border-radius: 12px;
    background: white;
    padding: 8px;
}

.hidden {
    display: none !important;
}
</style>
</head>
<body>
<div class="wrap">

    <div class="topbar">
        <div class="titleRow">
            <h1>OpenD</h1>
            <div class="statusPill">
                <span id="statusDot" class="dot waiting"></span>
                <span id="statusText">Waiting</span>
            </div>
        </div>

        <div class="toolbar">
            <button id="toggleTerminalBtn" class="ghost" onclick="toggleTerminal()">Hide terminal</button>
        </div>
    </div>

    <div class="grid">

        <div id="leftColumn">
            <div id="summaryCard" class="card">
                <div class="cardHeader">
                    <div class="cardTitle">Connection summary</div>
                </div>
                <div class="cardBody">
                    <div class="metaRow">
                        <div class="statBox">
                            <div class="statLabel">State</div>
                            <div class="statValue" id="summaryState">Waiting for OpenD login</div>
                        </div>
                        <div class="statBox">
                            <div class="statLabel">Program status</div>
                            <div class="statValue" id="summaryProgram">Unknown</div>
                        </div>
                        <div class="statBox">
                            <div class="statLabel">Account</div>
                            <div class="statValue" id="summaryAccount">—</div>
                        </div>
                        <div class="statBox">
                            <div class="statLabel">API test</div>
                            <div class="statValue" id="summaryTest">Not ready</div>
                        </div>
                    </div>
                </div>
            </div>

            <div id="terminalCard" class="card" style="margin-top:16px;">
                <div class="cardHeader">
                    <div class="cardTitle">OpenD terminal</div>
                </div>
                <div id="terminal">Connecting to OpenD control console...</div>
            </div>
        </div>

        <div id="rightColumn">
            <div class="card">
                <div class="cardHeader">
                    <div class="cardTitle">Quick actions</div>
                </div>
                <div class="cardBody">

                    <div class="controlGroup">
                        <div class="controlTitle">Manual command</div>
                        <div class="row">
                            <input id="command" class="grow" type="text" autocomplete="off" placeholder="Enter OpenD response or command">
                            <button class="primary fixed" onclick="sendCommand()">Send</button>
                        </div>
                        <div class="help">Use this for direct interaction with OpenD if needed.</div>
                    </div>

                    <div class="controlGroup">
                        <div class="controlTitle">Graphic verification</div>
                        <div class="row" style="margin-bottom:10px;">
                            <button class="warn fixed" onclick="requestCaptcha()">Request captcha</button>
                        </div>
                        <div class="row">
                            <input id="captchaCode" class="grow" type="text" autocomplete="off" placeholder="Enter captcha text">
                            <button class="primary fixed" onclick="submitCaptcha()">Submit captcha</button>
                        </div>

                        <div id="captchaWrap">
                            <div class="help" style="margin-bottom:8px;">Latest captcha image:</div>
                            <img id="captchaImg" alt="Captcha">
                        </div>
                    </div>

                    <div class="controlGroup">
                        <div class="controlTitle">SMS verification</div>
                        <div class="row" style="margin-bottom:10px;">
                            <button class="warn fixed" onclick="requestSMS()">Request SMS code</button>
                        </div>
                        <div class="row">
                            <input id="smsCode" class="grow" type="text" autocomplete="off" placeholder="Enter 6 digit SMS code">
                            <button class="primary fixed" onclick="submitSMS()">Submit SMS code</button>
                        </div>
                    </div>

                </div>
            </div>
        </div>

    </div>
</div>

<script>
let ws;
let captchaMtime = 0;
let terminalVisible = true;

function appendTerminal(text) {
    const terminal = document.getElementById("terminal");
    terminal.textContent += text;
    terminal.scrollTop = terminal.scrollHeight;
}

function connectTerminal() {
    const protocol = location.protocol === "https:" ? "wss://" : "ws://";
    ws = new WebSocket(protocol + location.host + "/ws");

    ws.onmessage = (event) => {
        appendTerminal(event.data);
    };

    ws.onclose = () => {
        appendTerminal("\n[Disconnected. Retrying...]\n");
        setTimeout(connectTerminal, 1500);
    };
}

function sendRaw(value) {
    if (!value || !value.trim()) return;
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(value);
    }
}

function sendCommand() {
    const el = document.getElementById("command");
    const value = el.value.trim();
    if (!value) return;
    sendRaw(value);
    el.value = "";
    el.focus();
}

function requestCaptcha() {
    sendRaw("req_pic_verify_code");
    setTimeout(checkCaptcha, 500);
}

function submitCaptcha() {
    const el = document.getElementById("captchaCode");
    const code = el.value.trim();
    if (!code) return;
    sendRaw("input_pic_verify_code -code=" + code);
    el.value = "";
    el.focus();
}

function requestSMS() {
    sendRaw("req_phone_verify_code");
}

function submitSMS() {
    const el = document.getElementById("smsCode");
    const code = el.value.trim();
    if (!code) return;
    sendRaw("input_phone_verify_code -code=" + code);
    el.value = "";
    el.focus();
}

function toggleTerminal() {
    const card = document.getElementById("terminalCard");
    const btn = document.getElementById("toggleTerminalBtn");
    terminalVisible = !terminalVisible;

    if (terminalVisible) {
        card.classList.remove("hidden");
        btn.textContent = "Hide terminal";
    } else {
        card.classList.add("hidden");
        btn.textContent = "Open terminal";
    }
}

async function checkCaptcha() {
    try {
        const r = await fetch("/captcha-status?t=" + Date.now(), { cache: "no-store" });
        const d = await r.json();

        const wrap = document.getElementById("captchaWrap");
        const img = document.getElementById("captchaImg");

        if (d.exists) {
            wrap.style.display = "block";

            if (captchaMtime !== d.mtime) {
                captchaMtime = d.mtime;
                img.src = "/captcha?t=" + Date.now();
            }
        } else {
            wrap.style.display = "none";
        }
    } catch (_) {}
}

function setStatus(state, text) {
    const dot = document.getElementById("statusDot");
    const label = document.getElementById("statusText");

    dot.className = "dot";
    if (state === "ok") dot.classList.add("ok");
    else if (state === "bad") dot.classList.add("bad");
    else dot.classList.add("waiting");

    label.textContent = text;
}

async function checkAPI() {
    try {
        const r = await fetch("/api-status?t=" + Date.now(), { cache: "no-store" });
        const d = await r.json();

        if (d.ready) {
            setStatus("ok", "Connected");

            document.getElementById("summaryState").textContent = "OpenD logged in successfully";
            document.getElementById("summaryProgram").textContent = d.program_status || "Ready";
            document.getElementById("summaryAccount").textContent = d.account || "Unknown";
            document.getElementById("summaryTest").textContent =
                `${d.test_code || ""} ${d.test_name || ""} @ ${d.test_price || ""}`;

        } else {
            setStatus("waiting", "Waiting");

            document.getElementById("summaryState").textContent =
                d.error || "Waiting for OpenD login";
            document.getElementById("summaryProgram").textContent =
                d.program_status || "Unknown";
            document.getElementById("summaryAccount").textContent = "—";
            document.getElementById("summaryTest").textContent = "Not ready";
        }

    } catch (e) {
        setStatus("bad", "Error");
        document.getElementById("summaryState").textContent = "API status check failed";
        document.getElementById("summaryProgram").textContent = "Unknown";
        document.getElementById("summaryAccount").textContent = "—";
        document.getElementById("summaryTest").textContent = "Unavailable";
    }
}

document.getElementById("command").addEventListener("keydown", function(e) {
    if (e.key === "Enter") {
        e.preventDefault();
        sendCommand();
    }
});

document.getElementById("captchaCode").addEventListener("keydown", function(e) {
    if (e.key === "Enter") {
        e.preventDefault();
        submitCaptcha();
    }
});

document.getElementById("smsCode").addEventListener("keydown", function(e) {
    if (e.key === "Enter") {
        e.preventDefault();
        submitSMS();
    }
});

connectTerminal();
setInterval(checkAPI, 2000);
setInterval(checkCaptcha, 1000);
checkAPI();
checkCaptcha();
</script>
</body>
</html>
"""

def append_history(text):
    global terminal_history
    with history_lock:
        terminal_history += text
        if len(terminal_history) > 100000:
            terminal_history = terminal_history[-100000:]


@app.route("/")
def index():
    return render_template_string(HTML)


@sock.route("/ws")
def terminal_ws(ws):
    conn = socket.create_connection((OPEND_HOST, OPEND_TELNET_PORT), timeout=10)
    conn.settimeout(0.5)
    closed = threading.Event()

    def opend_to_browser():
        try:
            while not closed.is_set():
                try:
                    data = conn.recv(8192)
                    if not data:
                        break
                    text = data.decode("utf-8", errors="replace")
                    append_history(text)
                    ws.send(text)
                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            closed.set()

    reader = threading.Thread(target=opend_to_browser, daemon=True)
    reader.start()

    try:
        while not closed.is_set():
            message = ws.receive()
            if message is None:
                break
            conn.sendall((message + "\r\n").encode())
    except Exception:
        pass
    finally:
        closed.set()
        try:
            conn.close()
        except Exception:
            pass


@app.route("/api-status")
def api_status():
    ctx = None
    try:
        ctx = OpenQuoteContext(host=OPEND_HOST, port=OPEND_API_PORT)
        ret, state = ctx.get_global_state()

        if ret != RET_OK:
            return jsonify(
                ready=False,
                error=str(state),
                program_status="Unknown"
            )

        if not state.get("qot_logined", False):
            return jsonify(
                ready=False,
                error="OpenD quote server is not logged in yet.",
                program_status=str(state.get("program_status_type", "Unknown"))
            )

        ret, snapshot = ctx.get_market_snapshot(["US.AAPL"])
        if ret != RET_OK:
            return jsonify(
                ready=False,
                error=str(snapshot),
                program_status=str(state.get("program_status_type", "Unknown"))
            )

        row = snapshot.iloc[0]
        account = None

        with history_lock:
            match = re.search(r"Login Account:\s*([0-9]+)", terminal_history)
            if match:
                account = match.group(1)

        return jsonify(
            ready=True,
            server_ver=state.get("server_ver"),
            qot_logined=bool(state.get("qot_logined")),
            trd_logined=bool(state.get("trd_logined")),
            program_status=str(state.get("program_status_type", "")),
            account=account,
            test_code=str(row.get("code", "US.AAPL")),
            test_name=str(row.get("name", "")),
            test_price=str(row.get("last_price", "")),
            test_update=str(row.get("update_time", ""))
        )

    except Exception as e:
        return jsonify(
            ready=False,
            error=str(e),
            program_status="Unknown"
        )
    finally:
        if ctx:
            try:
                ctx.close()
            except Exception:
                pass


@app.route("/captcha-status")
def captcha_status():
    if not os.path.exists(CAPTCHA):
        return jsonify(exists=False, mtime=0)
    return jsonify(exists=True, mtime=os.path.getmtime(CAPTCHA))


@app.route("/captcha")
def captcha():
    if not os.path.exists(CAPTCHA):
        return ("Captcha not available", 404)

    response = make_response(send_file(CAPTCHA, mimetype="image/png"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


app.run(host="0.0.0.0", port=6789, threaded=True)
