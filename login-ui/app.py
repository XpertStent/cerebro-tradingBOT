from flask import Flask, request, session, redirect, url_for, render_template_string, send_file
import socket
import time
import uuid
import os

app = Flask(__name__)
app.secret_key = "moomoo-opend-login-ui"

HOST = "opend"
PORT = 22222
CAPTCHA = "/root/.com.moomoo.OpenD/F3CNN/PicVerifyCode.png"

connections = {}

PAGE = """
<!doctype html>
<html>
<head>
<title>Moomoo OpenD Login</title>
<style>
body { font-family: Arial; max-width:600px; margin:50px auto; }
input,button { width:100%; padding:12px; margin:6px 0; box-sizing:border-box; }
.status { padding:12px; background:#eee; margin-bottom:15px; white-space:pre-wrap; }
.error { background:#ffd6d6; }
.success { background:#d7ffd7; }
img { display:block; margin:15px auto; max-width:100%; }
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

{% elif step == "pic_request" %}
<form method="post">
<button name="value" value="req_pic_verify_code">Load verification image</button>
</form>

{% elif step == "pic_code" %}
<img src="/captcha?x={{ nonce }}">
<form method="post">
<input name="value" placeholder="Enter code shown above" required autofocus>
<button>Verify</button>
</form>

{% elif step == "sms_request" %}
<form method="post">
<button name="value" value="req_phone_verify_code">Request SMS code</button>
</form>

{% elif step == "sms_code" %}
<form method="post">
<input name="value" placeholder="6 digit SMS code" required autofocus>
<button>Verify</button>
</form>

{% elif step == "success" %}
<div class="status success">OpenD login successful and ready.</div>

{% endif %}

<form method="post" action="/reset">
<button>Start over</button>
</form>

</body>
</html>
"""

def recv_available(sock, wait=0.6):
    time.sleep(wait)
    sock.settimeout(0.2)
    result = []

    while True:
        try:
            data = sock.recv(8192)
            if not data:
                break
            result.append(data.decode(errors="replace"))
        except socket.timeout:
            break

    return "".join(result)


def get_conn():
    sid = session.setdefault("sid", str(uuid.uuid4()))

    if sid not in connections:
        s = socket.create_connection((HOST, PORT), timeout=5)
        connections[sid] = s
        session["buffer"] = recv_available(s)

    return connections[sid]


def send(value):
    s = get_conn()
    s.sendall((value + "\r\n").encode())
    output = recv_available(s)
    session["buffer"] = output
    return output


def detect(text):
    t = text.lower()

    if "login successful" in t or "required data is ready" in t:
        return "success", "Login successful.", "success"

    if "please enter account" in t:
        return "account", None, ""

    if "please enter password" in t:
        return "password", None, ""

    if "remember the password" in t:
        return "remember", None, ""

    if "graphic verification code required" in t:
        return "pic_request", "Graphic verification required.", ""

    if "graphic verification code downloaded" in t:
        return "pic_code", None, ""

    if "sms verification code required" in t:
        return "sms_request", "SMS verification required.", ""

    if "sms verification code requested successfully" in t:
        return "sms_code", "SMS code sent.", ""

    if "input_phone_verify_code" in t:
        return "sms_code", None, ""

    return session.get("step", "account"), text.strip() or None, ""


@app.route("/", methods=["GET", "POST"])
def index():
    get_conn()

    if request.method == "POST":
        value = request.form["value"]
        step = session.get("step")

        if step == "pic_code":
            value = f"input_pic_verify_code -code={value}"

        elif step == "sms_code":
            value = f"input_phone_verify_code -code={value}"

        output = send(value)
    else:
        output = session.get("buffer", "")

    step, message, css = detect(output)
    session["step"] = step

    return render_template_string(
        PAGE,
        step=step,
        message=message,
        css=css,
        nonce=time.time()
    )


@app.get("/captcha")
def captcha():
    if not os.path.exists(CAPTCHA):
        return "Captcha not available", 404

    return send_file(CAPTCHA, mimetype="image/png")


@app.post("/reset")
def reset():
    sid = session.get("sid")

    if sid in connections:
        try:
            connections[sid].close()
        except Exception:
            pass

        connections.pop(sid, None)

    session.clear()
    return redirect(url_for("index"))


app.run(host="0.0.0.0", port=6789)
