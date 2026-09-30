from flask import Flask, request, session, redirect, url_for, render_template_string
import socket
import time
import uuid

app = Flask(__name__)
app.secret_key = "change-this-later"

OPEND_HOST = "opend"
OPEND_PORT = 22222

connections = {}

PAGE = """
<!doctype html>
<html>
<head>
<title>Moomoo OpenD Login</title>
<style>
body { font-family: Arial; max-width: 600px; margin: 50px auto; }
input, button { width:100%; padding:12px; margin:6px 0; box-sizing:border-box; }
.status { padding:12px; background:#eee; margin-bottom:15px; }
.error { background:#ffd6d6; }
.success { background:#d7ffd7; }
</style>
</head>
<body>
<h2>Moomoo OpenD Login</h2>

{% if message %}
<div class="status {{ css }}">{{ message }}</div>
{% endif %}

{% if step == "account" %}
<form method="post">
<input name="value" placeholder="Moomoo account/email" required autofocus>
<button>Continue</button>
</form>

{% elif step == "password" %}
<form method="post">
<input name="value" type="password" placeholder="Password" required autofocus>
<button>Continue</button>
</form>

{% elif step == "remember" %}
<form method="post">
<button name="value" value="Y">Remember password</button>
<button name="value" value="N">Do not remember</button>
</form>

{% elif step == "sms_request" %}
<form method="post">
<button name="value" value="req_phone_verify_code">Request SMS code</button>
</form>

{% elif step == "sms_code" %}
<form method="post">
<input name="value" placeholder="6 digit verification code" required autofocus>
<button>Verify</button>
</form>

{% elif step == "success" %}
<div class="status success">OpenD login successful.</div>

{% elif step == "error" %}
<form method="post" action="/reset">
<button>Start over</button>
</form>
{% endif %}
</body>
</html>
"""

def recv_available(sock, wait=0.8):
    time.sleep(wait)
    sock.settimeout(0.25)
    chunks = []
    while True:
        try:
            data = sock.recv(8192)
            if not data:
                break
            chunks.append(data.decode(errors="replace"))
        except socket.timeout:
            break
    return "".join(chunks)

def get_conn():
    sid = session.setdefault("sid", str(uuid.uuid4()))

    if sid not in connections:
        s = socket.create_connection((OPEND_HOST, OPEND_PORT), timeout=5)
        connections[sid] = s
        session["buffer"] = recv_available(s)

    return connections[sid]

def send(value):
    s = get_conn()
    s.sendall((value + "\r\n").encode())
    output = recv_available(s)
    session["buffer"] = output
    return output

def detect_step(text):
    t = text.lower()

    if "login successful" in t:
        return "success", "Login successful.", "success"

    if "please enter account" in t:
        return "account", None, ""

    if "please enter password" in t:
        return "password", None, ""

    if "remember the password" in t:
        return "remember", None, ""

    if "sms verification code required" in t:
        return "sms_request", "SMS verification required.", ""

    if "verification code requested successfully" in t:
        return "sms_code", "SMS code sent.", ""

    if "input_phone_verify_code" in t:
        return "sms_code", None, ""

    if "failed" in t or "error" in t or "incorrect" in t:
        return "error", text.strip(), "error"

    return "account", text.strip() or None, ""

@app.route("/", methods=["GET", "POST"])
def index():
    s = get_conn()

    if request.method == "POST":
        value = request.form["value"]
        current = session.get("step")

        if current == "sms_code":
            value = f"input_phone_verify_code -code={value}"

        output = send(value)
    else:
        output = session.get("buffer", "")

    step, message, css = detect_step(output)
    session["step"] = step

    return render_template_string(
        PAGE,
        step=step,
        message=message,
        css=css
    )

@app.post("/reset")
def reset():
    sid = session.get("sid")
    if sid in connections:
        try:
            connections[sid].close()
        except:
            pass
        connections.pop(sid, None)

    session.clear()
    return redirect(url_for("index"))

app.run(host="0.0.0.0", port=6789)
