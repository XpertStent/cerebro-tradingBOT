from flask import Flask, render_template_string, send_file, jsonify, make_response
from flask_sock import Sock
from moomoo import OpenQuoteContext, RET_OK
import socket
import threading
import os

app = Flask(__name__)
sock = Sock(app)

OPEND_HOST = "opend"
OPEND_API_PORT = 11111
OPEND_TELNET_PORT = 22222
CAPTCHA = "/root/.com.moomoo.OpenD/F3CNN/PicVerifyCode.png"

HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OpenD</title>

<style>
:root{
    --bg:#f5f7fb;
    --card:#fff;
    --text:#111827;
    --muted:#6b7280;
    --border:#e5e7eb;
    --green:#16a34a;
    --amber:#d97706;
    --red:#dc2626;
    --blue:#2563eb;
    --terminal:#0b0f16;
}

*{box-sizing:border-box}

body{
    margin:0;
    font-family:Arial,sans-serif;
    background:var(--bg);
    color:var(--text);
}

.wrap{
    max-width:980px;
    margin:28px auto;
    padding:0 16px 40px;
}

.header{
    display:flex;
    align-items:center;
    gap:12px;
    margin-bottom:18px;
}

h1{
    margin:0;
    font-size:30px;
}

.status{
    display:flex;
    align-items:center;
    gap:8px;
    font-size:14px;
    font-weight:700;
}

.dot{
    width:10px;
    height:10px;
    border-radius:50%;
    background:var(--amber);
}

.dot.ok{background:var(--green)}
.dot.bad{background:var(--red)}

.stateGrid{
    display:grid;
    grid-template-columns:1fr 1fr;
    gap:12px;
    margin-bottom:16px;
}

.stateBox{
    background:var(--card);
    border:1px solid var(--border);
    border-radius:14px;
    padding:14px 16px;
}

.label{
    font-size:12px;
    text-transform:uppercase;
    letter-spacing:.04em;
    color:var(--muted);
    font-weight:700;
    margin-bottom:5px;
}

.value{
    font-size:15px;
    font-weight:700;
}

.section{
    background:var(--card);
    border:1px solid var(--border);
    border-radius:16px;
    margin-bottom:16px;
    overflow:hidden;
}

.sectionHeader{
    width:100%;
    border:0;
    background:transparent;
    padding:15px 18px;
    display:flex;
    align-items:center;
    gap:9px;
    font-size:16px;
    font-weight:800;
    cursor:pointer;
    text-align:left;
}

.chev{
    width:16px;
    display:inline-block;
    transition:transform .15s ease;
}

.chev.open{
    transform:rotate(90deg);
}

.sectionBody{
    padding:0 16px 16px;
}

.hidden{
    display:none;
}

/* terminal as one component */

.terminalShell{
    border-radius:12px;
    overflow:hidden;
    border:1px solid #1f2937;
    background:var(--terminal);
}

#terminal{
    color:#f3f4f6;
    min-height:390px;
    max-height:520px;
    overflow:auto;
    padding:16px;
    white-space:pre-wrap;
    font-family:Consolas,monospace;
    font-size:14px;
    line-height:1.35;
}

.terminalInputRow{
    display:flex;
    border-top:1px solid #2a3340;
    background:#111827;
}

.terminalInputRow input{
    flex:1;
    border:0;
    outline:0;
    padding:13px 14px;
    background:#111827;
    color:#fff;
    font-size:15px;
}

.terminalInputRow button{
    border:0;
    border-left:1px solid #2a3340;
    background:#1f2937;
    color:#fff;
    padding:0 18px;
    cursor:pointer;
    font-weight:700;
}

.authBlock{
    padding:14px 0;
}

.authBlock + .authBlock{
    border-top:1px solid var(--border);
}

.authTitle{
    font-weight:800;
    margin-bottom:10px;
}

.authInput{
    width:260px;
    max-width:100%;
    padding:10px 12px;
    border:1px solid #d1d5db;
    border-radius:10px;
    font-size:14px;
    outline:none;
}

.authButtons{
    display:flex;
    gap:8px;
    margin-top:9px;
    flex-wrap:wrap;
}

.authButtons button{
    padding:9px 12px;
    border-radius:10px;
    border:1px solid var(--border);
    background:#fff;
    cursor:pointer;
    font-weight:700;
}

.authButtons .primary{
    background:var(--blue);
    color:#fff;
    border-color:var(--blue);
}

#captchaWrap{
    display:none;
    margin-bottom:10px;
}

#captchaImg{
    max-width:260px;
    border:1px solid var(--border);
    border-radius:10px;
    background:#fff;
    padding:6px;
}

@media(max-width:700px){
    .stateGrid{grid-template-columns:1fr}
}
</style>
</head>

<body>
<div class="wrap">

    <div class="header">
        <h1>OpenD</h1>
        <div class="status">
            <span id="statusDot" class="dot"></span>
            <span id="statusText">Waiting</span>
        </div>
    </div>

    <div class="stateGrid">
        <div class="stateBox">
            <div class="label">State</div>
            <div class="value" id="stateValue">Waiting for login</div>
        </div>

        <div class="stateBox">
            <div class="label">Program status</div>
            <div class="value" id="programValue">Unknown</div>
        </div>
    </div>

    <div class="section">
        <button class="sectionHeader" onclick="toggleSection('terminalBody','terminalChev')">
            <span id="terminalChev" class="chev open">›</span>
            OpenD terminal
        </button>

        <div id="terminalBody" class="sectionBody">
            <div class="terminalShell">
                <div id="terminal">Connecting to OpenD...</div>

                <div class="terminalInputRow">
                    <input id="command"
                           type="text"
                           autocomplete="off"
                           placeholder="Enter response or command">
                    <button onclick="sendCommand()">Send</button>
                </div>
            </div>
        </div>
    </div>

    <div class="section">
        <button class="sectionHeader" onclick="toggleSection('authBody','authChev')">
            <span id="authChev" class="chev">›</span>
            Additional authentication tools
        </button>

        <div id="authBody" class="sectionBody hidden">

            <div class="authBlock">
                <div class="authTitle">Graphic verification</div>

                <div id="captchaWrap">
                    <img id="captchaImg">
                </div>

                <input id="captchaCode"
                       class="authInput"
                       type="text"
                       autocomplete="off"
                       placeholder="Captcha code">

                <div class="authButtons">
                    <button onclick="requestCaptcha()">Refresh image</button>
                    <button class="primary" onclick="submitCaptcha()">Submit</button>
                </div>
            </div>

            <div class="authBlock">
                <div class="authTitle">SMS verification</div>

                <input id="smsCode"
                       class="authInput"
                       type="text"
                       autocomplete="off"
                       placeholder="6 digit SMS code">

                <div class="authButtons">
                    <button onclick="requestSMS()">Request SMS</button>
                    <button class="primary" onclick="submitSMS()">Submit</button>
                </div>
            </div>

        </div>
    </div>

</div>

<script>
let ws;
let captchaMtime = 0;

function toggleSection(bodyId, chevId){
    const body = document.getElementById(bodyId);
    const chev = document.getElementById(chevId);

    body.classList.toggle("hidden");
    chev.classList.toggle("open");
}

function connectTerminal(){
    const protocol = location.protocol === "https:" ? "wss://" : "ws://";
    ws = new WebSocket(protocol + location.host + "/ws");

    ws.onmessage = event => {
        const t = document.getElementById("terminal");
        t.textContent += event.data;
        t.scrollTop = t.scrollHeight;
    };

    ws.onclose = () => {
        setTimeout(connectTerminal, 1500);
    };
}

function sendRaw(value){
    if(!value || !value.trim()) return;
    if(ws && ws.readyState === WebSocket.OPEN){
        ws.send(value);
    }
}

function sendCommand(){
    const el = document.getElementById("command");
    const value = el.value.trim();
    if(!value) return;

    sendRaw(value);
    el.value = "";
    el.focus();
}

function requestCaptcha(){
    sendRaw("req_pic_verify_code");
    setTimeout(checkCaptcha, 500);
}

function submitCaptcha(){
    const el = document.getElementById("captchaCode");
    const code = el.value.trim();
    if(!code) return;

    sendRaw("input_pic_verify_code -code=" + code);
    el.value = "";
}

function requestSMS(){
    sendRaw("req_phone_verify_code");
}

function submitSMS(){
    const el = document.getElementById("smsCode");
    const code = el.value.trim();
    if(!code) return;

    sendRaw("input_phone_verify_code -code=" + code);
    el.value = "";
}

document.getElementById("command").addEventListener("keydown",e=>{
    if(e.key==="Enter"){
        e.preventDefault();
        sendCommand();
    }
});

document.getElementById("captchaCode").addEventListener("keydown",e=>{
    if(e.key==="Enter"){
        e.preventDefault();
        submitCaptcha();
    }
});

document.getElementById("smsCode").addEventListener("keydown",e=>{
    if(e.key==="Enter"){
        e.preventDefault();
        submitSMS();
    }
});

async function checkCaptcha(){
    try{
        const r = await fetch("/captcha-status?t="+Date.now(), {cache:"no-store"});
        const d = await r.json();

        const wrap = document.getElementById("captchaWrap");
        const img = document.getElementById("captchaImg");

        if(d.exists){
            wrap.style.display = "block";

            if(d.mtime !== captchaMtime){
                captchaMtime = d.mtime;
                img.src = "/captcha?t="+Date.now();
            }
        }else{
            wrap.style.display = "none";
        }
    }catch(_){}
}

function setStatus(mode,text){
    const dot = document.getElementById("statusDot");
    dot.className = "dot";

    if(mode==="ok") dot.classList.add("ok");
    if(mode==="bad") dot.classList.add("bad");

    document.getElementById("statusText").textContent = text;
}

async function checkAPI(){
    try{
        const r = await fetch("/api-status?t="+Date.now(), {cache:"no-store"});
        const d = await r.json();

        if(d.ready){
            setStatus("ok","Connected");
            document.getElementById("stateValue").textContent = "Logged in";
            document.getElementById("programValue").textContent =
                d.program_status || "Ready";
        }else{
            setStatus("","Waiting");
            document.getElementById("stateValue").textContent =
                d.error || "Waiting for login";
            document.getElementById("programValue").textContent =
                d.program_status || "Unknown";
        }

    }catch(e){
        setStatus("bad","Error");
        document.getElementById("stateValue").textContent = "API unavailable";
        document.getElementById("programValue").textContent = "Unknown";
    }
}

connectTerminal();
checkAPI();
checkCaptcha();

setInterval(checkAPI,2000);
setInterval(checkCaptcha,1000);
</script>
</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)


@sock.route("/ws")
def terminal_ws(ws):
    conn = socket.create_connection((OPEND_HOST, OPEND_TELNET_PORT), timeout=10)
    conn.settimeout(0.5)
    closed = threading.Event()

    def reader():
        try:
            while not closed.is_set():
                try:
                    data = conn.recv(8192)
                    if not data:
                        break

                    ws.send(data.decode("utf-8", errors="replace"))

                except socket.timeout:
                    continue
                except Exception:
                    break
        finally:
            closed.set()

    threading.Thread(target=reader, daemon=True).start()

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
                error="Waiting for OpenD login",
                program_status=str(state.get("program_status_type", "Unknown"))
            )

        ret, snapshot = ctx.get_market_snapshot(["US.AAPL"])

        if ret != RET_OK:
            return jsonify(
                ready=False,
                error=str(snapshot),
                program_status=str(state.get("program_status_type", "Unknown"))
            )

        return jsonify(
            ready=True,
            program_status=str(state.get("program_status_type", "Ready"))
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

    return jsonify(
        exists=True,
        mtime=os.path.getmtime(CAPTCHA)
    )


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
