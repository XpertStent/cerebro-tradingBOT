from flask import Flask, request, render_template_string
import socket
import time

app = Flask(__name__)

HOST = "opend"
PORT = 22222

PAGE = """
<!doctype html>
<html>
<head>
<title>Moomoo OpenD Login</title>
<style>
body { font-family: Arial; max-width: 600px; margin: 50px auto; }
input,button { width:100%; padding:12px; margin:6px 0; box-sizing:border-box; }
pre { background:#111; color:#eee; padding:15px; white-space:pre-wrap; }
</style>
</head>
<body>
<h2>Moomoo OpenD Login</h2>

<form method="post" action="/login">
<input name="account" placeholder="Moomoo account/email" required>
<input name="password" type="password" placeholder="Password" required>
<button>Login</button>
</form>

<form method="post" action="/request-sms">
<button>Request SMS Verification Code</button>
</form>

<form method="post" action="/verify">
<input name="code" placeholder="6 digit verification code" required>
<button>Verify SMS Code</button>
</form>

{% if output %}
<h3>OpenD response</h3>
<pre>{{ output }}</pre>
{% endif %}
</body>
</html>
"""

def communicate(lines):
    output = ""

    with socket.create_connection((HOST, PORT), timeout=5) as s:
        s.settimeout(1)

        try:
            output += s.recv(8192).decode("utf-8", errors="replace")
        except:
            pass

        for line in lines:
            s.sendall((line + "\r\n").encode())
            time.sleep(1)

            try:
                while True:
                    data = s.recv(8192)
                    if not data:
                        break
                    output += data.decode("utf-8", errors="replace")
            except socket.timeout:
                pass

    return output


@app.get("/")
def index():
    return render_template_string(PAGE)


@app.post("/login")
def login():
    account = request.form["account"]
    password = request.form["password"]

    output = communicate([
        account,
        password,
        "Y"
    ])

    return render_template_string(PAGE, output=output)


@app.post("/request-sms")
def request_sms():
    output = communicate(["req_phone_verify_code"])
    return render_template_string(PAGE, output=output)


@app.post("/verify")
def verify():
    code = request.form["code"]
    output = communicate([
        f"input_phone_verify_code -code={code}"
    ])
    return render_template_string(PAGE, output=output)


app.run(host="0.0.0.0", port=6789)
