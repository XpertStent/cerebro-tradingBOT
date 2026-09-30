from flask import Flask, request, jsonify, send_file, render_template_string
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
body {
    font-family: Arial;
    max-width: 850px;
    margin: 40px auto;
}
#terminal {
    background: #111;
    color: #eee;
    padding: 20px;
    min-height: 350px;
    white-space: pre-wrap;
    font-family: monospace;
    overflow-y: auto;
}
input, button {
    padding: 12px;
    font-size: 16px;
    box-sizing: border-box;
}
input { width: 78%; }
button { width: 20%; }
#captcha {
    margin: 15px 0;
    max-width: 400px;
}
</style>
</head>

<body>

<h2>Moomoo OpenD</h2>

<pre id="terminal">Connecting...</pre>

<img id="captcha" style="display:none">

<form id="form">
    <input id="cmd" autocomplete="off" autofocus>
    <button>Send</button>
</form>

<script>
async function poll() {
    const r = await fetch("/poll");
    const d = await r.json();

    const terminal = document.getElementById("terminal");
    terminal.textContent = d.output;
    terminal.scrollTop = terminal.scrollHeight;

    const input = document.getElementById("cmd");

    if (d.output.toLowerCase().includes("please enter password")) {
        input.type = "password";
        input.placeholder = "Password";
    } else {
        input.type = "text";
        input.placeholder = "Enter response or OpenD command";
    }

    if (d.captcha) {
        const img = document.getElementById("captcha");
        img.src = "/captcha?" + Date.now();
        img.style.display = "block";
    }
}

document.getElementById("form").onsubmit = async e => {
    e.preventDefault();

    const input = document.getElementById("cmd");
    const value = input.value;

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
    with lock:
        try:
            connect()
        except Exception as e:
            global history
            history += f"Connection error: {e}\n"

    return render_template_string(HTML)


@app.route("/poll")
def poll():
    global history

    with lock:
        try:
            connect()
            history += read_socket()
        except Exception as e:
            history += f"\nConnection error: {e}\n"

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

            # Do not store passwords typed by user in history
            if "please enter password" not in history.lower()[-200:]:
                history += f">>> {value}\n"
            else:
                history += ">>> ********\n"

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

    return send_file(CAPTCHA, mimetype="image/png")


app.run(host="0.0.0.0", port=6789)
