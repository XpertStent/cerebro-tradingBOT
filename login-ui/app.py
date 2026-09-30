from flask import Flask, render_template_string, send_file, jsonify, make_response
from flask_sock import Sock
import socket
import os

app = Flask(__name__)
sock = Sock(app)

OPEND_HOST = "opend"
OPEND_PORT = 22222
CAPTCHA = "/root/.com.moomoo.OpenD/F3CNN/PicVerifyCode.png"

HTML = r"""
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Moomoo OpenD</title>
<style>
body {
    font-family: Arial, sans-serif;
    max-width: 950px;
    margin: 30px auto;
    padding: 0 15px;
}
#terminal {
    background: #111;
    color: #eee;
    min-height: 420px;
    max-height: 600px;
    overflow-y: auto;
    padding: 18px;
    white-space: pre-wrap;
    font-family: monospace;
    font-size: 15px;
}
.row {
    display: flex;
    gap: 8px;
    margin-top: 10px;
}
input, button {
    padding: 11px;
    font-size: 15px;
    box-sizing: border-box;
}
#command {
    flex: 1;
}
button {
    cursor: pointer;
}
.panel {
    margin-top: 20px;
    padding: 15px;
    background: #f3f3f3;
}
#captcha {
    display: none;
    margin: 10px 0;
    max-width: 350px;
}
.small {
    font-size: 13px;
    color: #555;
}
</style>
</head>

<body>

<h2>Moomoo OpenD</h2>

<div id="terminal">Connecting to OpenD...</div>

<div class="row">
    <input id="command"
           type="text"
           autocomplete="off"
           placeholder="Enter account, password, Y/N, or OpenD command">
    <button onclick="sendCommand()">Send</button>
</div>

<div class="small">
Input is not echoed by this webpage. OpenD's own response is shown above.
</div>

<div class="panel">
<h3>Graphic verification</h3>

<button onclick="sendRaw('req_pic_verify_code')">
Request / refresh image
</button>

<img id="captcha">

<div class="row">
    <input id="picCode" placeholder="Captcha code">
    <button onclick="submitPic()">Submit captcha</button>
</div>

<div class="small">
Equivalent command:
<code>input_pic_verify_code -code=XXXX</code>
</div>
</div>

<div class="panel">
<h3>SMS verification</h3>

<button onclick="sendRaw('req_phone_verify_code')">
Request SMS code
</button>

<div class="row">
    <input id="smsCode" placeholder="SMS verification code">
    <button onclick="submitSms()">Submit SMS code</button>
</div>

<div class="small">
Equivalent command:
<code>input_phone_verify_code -code=123456</code>
</div>
</div>

<script>
let ws;
let captchaMtime = 0;

function connect() {
    const protocol = location.protocol === "https:" ? "wss://" : "ws://";
    ws = new WebSocket(protocol + location.host + "/ws");

    ws.onmessage = event => {
        const terminal = document.getElementById("terminal");
        terminal.textContent += event.data;
        terminal.scrollTop = terminal.scrollHeight;
    };

    ws.onclose = () => {
        const terminal = document.getElementById("terminal");
        terminal.textContent += "\\n[Disconnected. Retrying...]\\n";
        setTimeout(connect, 2000);
    };
}

function sendRaw(value) {
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(value);
    }
}

function sendCommand() {
    const input = document.getElementById("command");
    if (!input.value) return;

    sendRaw(input.value);

    // Never display or retain submitted text in the browser UI.
    input.value = "";
    input.focus();
}

function submitPic() {
    const input = document.getElementById("picCode");
    if (!input.value) return;

    sendRaw("input_pic_verify_code -code=" + input.value.trim());
    input.value = "";
}

function submitSms() {
    const input = document.getElementById("smsCode");
    if (!input.value) return;

    sendRaw("input_phone_verify_code -code=" + input.value.trim());
    input.value = "";
}

document.getElementById("command").addEventListener("keydown", e => {
    if (e.key === "Enter") {
        e.preventDefault();
        sendCommand();
    }
});

async function refreshCaptcha() {
    try {
        const r = await fetch("/captcha-status?t=" + Date.now(), {
            cache: "no-store"
        });

        const d = await r.json();
        const img = document.getElementById("captcha");

        if (d.exists) {
            if (d.mtime !== captchaMtime) {
                captchaMtime = d.mtime;
                img.src = "/captcha?t=" + Date.now();
            }

            img.style.display = "block";
        } else {
            img.style.display = "none";
        }
    } catch (_) {}
}

connect();
setInterval(refreshCaptcha, 1000);
refreshCaptcha();
</script>

</body>
</html>
"""

@app.route("/")
def index():
    return render_template_string(HTML)


@sock.route("/ws")
def websocket(ws):
    conn = socket.create_connection((OPEND_HOST, OPEND_PORT), timeout=10)
    conn.settimeout(0.25)

    try:
        # Send anything OpenD already has waiting.
        while True:
            try:
                data = conn.recv(8192)
                if not data:
                    break
                ws.send(data.decode("utf-8", errors="replace"))
            except socket.timeout:
                break

        while True:
            # Browser -> OpenD
            try:
                message = ws.receive(timeout=0.1)
                if message is not None:
                    conn.sendall((message + "\r\n").encode())
            except TypeError:
                # Compatibility with websocket implementations without timeout=
                message = ws.receive()
                if message is None:
                    break
                conn.sendall((message + "\r\n").encode())

            # OpenD -> Browser
            try:
                while True:
                    data = conn.recv(8192)
                    if not data:
                        return
                    ws.send(data.decode("utf-8", errors="replace"))
            except socket.timeout:
                pass

    finally:
        conn.close()


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
        return "Captcha not available", 404

    response = make_response(send_file(CAPTCHA, mimetype="image/png"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


app.run(host="0.0.0.0", port=6789)
