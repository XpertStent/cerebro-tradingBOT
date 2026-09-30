from flask import Flask, request, jsonify, send_file, render_template_string, make_response
import socket
import threading
import time
import os

app = Flask(__name__)

HOST = "opend"
PORT = 22222
CAPTCHA = "/root/.com.moomoo.OpenD/F3CNN/PicVerifyCode.png"

sock = None
history = ""
lock = threading.Lock()

HTML = """
<!doctype html>
<html>
<head>
<title>Moomoo OpenD Login</title>
<style>
body { font-family: Arial; max-width: 850px; margin: 40px auto; }
#terminal {
    background:#111;
    color:#eee;
    padding:20px;
    min-height:350px;
    white-space:pre-wrap;
    font-family:monospace;
    overflow-y:auto;
}
input, button {
    padding:12px;
    font-size:16px;
    box-sizing:border-box;
}
input { width:78%; }
button { width:20%; }
#captcha {
    margin:15px 0;
    max-width:400px;
    display:none;
}
</style>
</head>
<body>

<h2>Moomoo OpenD</h2>

<pre id="terminal">Connecting...</pre>

<img id="captcha">

<form id="form">
    <input id="cmd" autocomplete="off" autofocus>
    <button>Send</button>
</form>

<script>
let captchaVisible = false;

async function poll() {
    const r = await fetch("/poll", {cache:"no-store"});
    const d = await r.json();

    const terminal = document.getElementById("terminal");
    terminal.textContent = d.output;
    terminal.scrollTop = terminal.scrollHeight;

    const input = document.getElementById("cmd");
    const lower = d.output.toLowerCase();

    if (lower.includes("please enter password")) {
        input.type = "password";
        input.placeholder = "Password";
    } else if (lower.includes("graphic verification code")) {
        input.type = "text";
        input.placeholder = "Enter captcha code";
    } else if (lower.includes("sms verification code")) {
        input.type = "text";
        input.placeholder = "Enter SMS code or command";
    } else {
        input.type = "text";
        input.placeholder = "Enter response or OpenD command";
    }

    captchaVisible = d.captcha;

    const img = document.getElementById("captcha");
    if (captchaVisible) {
        img.src = "/captcha?t=" + Date.now();
        img.style.display = "block";
    } else {
        img.style.display = "none";
    }
}

document.getElementById("form").onsubmit = async e => {
    e.preventDefault();

    const input = document.getElementById("cmd");
    let value = input.value.trim();

    if (!value) return;

    const terminalText = document.getElementById("terminal").textContent.toLowerCase();

    if (captchaVisible && !value.startsWith("input_pic_verify_code")) {
        value = "input_pic_verify_code -code=" + value;
    } else if (
        terminalText.includes("sms verification code") &&
        /^[0-9]{4,8}$/.test(value) &&
        !value.startsWith("input_phone_verify_code")
    ) {
        value = "input_phone_verify_code -code=" + value;
    }

    input.value = "";

    await fetch("/send", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({value})
    });

    poll();
};

setInterval(poll, 1000);
poll();
</script>

</body>
</html>
"""

def connect():
    global sock, history

    if sock:
        return

    sock = socket.create_connection((HOST, PORT), timeout=5)
    sock.settimeout(0.2)
    history += read_socket()

def read_socket():
    global sock
    result = ""

    if not sock:
        return result

    while True:
        try:
            data = sock.recv(8192)
            if not data:
                break
            result += data.decode(errors="replace")
        except socket.timeout:
            break
        except Exception:
            break

    return result

@app.route("/")
def index():
    global history
    with lock:
        try:
            connect()
        except Exception as e:
            history += f"Connection error: {e}\n"
    return render_template_string(HTML)

@app.route("/poll")
def poll():
    global history, sock

    with lock:
        try:
            connect()
            history += read_socket()
        except Exception as e:
            history += f"\nConnection error: {e}\n"
            sock = None

    return jsonify({
        "output": history,
        "captcha": os.path.exists(CAPTCHA)
    })

@app.post("/send")
def send():
    global history, sock

    value = request.json.get("value", "")

    with lock:
        try:
            connect()
            sock.sendall((value + "\r\n").encode())

            if "password" in history.lower()[-200:]:
                history += ">>> ********\n"
            else:
                history += f">>> {value}\n"

            time.sleep(0.3)
            history += read_socket()

        except Exception as e:
            history += f"\nError: {e}\n"
            sock = None

    return {"ok": True}

@app.route("/captcha")
def captcha():
    if not os.path.exists(CAPTCHA):
        return "No captcha available", 404

    response = make_response(send_file(CAPTCHA, mimetype="image/png"))
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

app.run(host="0.0.0.0", port=6789)
