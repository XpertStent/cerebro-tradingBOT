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

<style>
body {
    font-family: Arial, sans-serif;
    max-width: 950px;
    margin: 30px auto;
    padding: 0 16px;
    background: #fafafa;
}

.card {
    background: white;
    padding: 24px;
    border-radius: 10px;
    margin-bottom: 18px;
    box-shadow: 0 1px 5px #ccc;
}

.success {
    border-left: 6px solid #2e9d52;
}

.waiting {
    border-left: 6px solid #d89b20;
}

#terminal {
    background: #111;
    color: #eee;
    height: 430px;
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
    padding: 12px;
    font-size: 15px;
    box-sizing: border-box;
}

#command {
    flex: 1;
}

button {
    cursor: pointer;
}

#captcha {
    display: none;
    margin-top: 15px;
    max-width: 400px;
    border: 1px solid #aaa;
}

code {
    background: #eee;
    padding: 2px 5px;
}

.detail {
    margin: 7px 0;
}

#terminalSection {
    display: block;
}
</style>
</head>

<body>

<h1>Moomoo OpenD</h1>

<div id="statusCard" class="card waiting">
    <h2 id="statusTitle">Waiting for OpenD login...</h2>

    <div id="statusDetails">
        API health check runs automatically every 2 seconds.
    </div>

    <button id="terminalButton"
            style="display:none"
            onclick="toggleTerminal()">
        Open terminal
    </button>
</div>

<div id="terminalSection">

    <div id="terminal">Connecting to OpenD control console...</div>

    <div class="row">
        <input
            id="command"
            type="text"
            autocomplete="off"
            placeholder="Enter OpenD response or command">
        <button onclick="sendCommand()">Send</button>
    </div>

    <div class="card">
        <strong>Verification commands</strong>

        <p>
        Request captcha:
        <code>req_pic_verify_code</code>
        </p>

        <p>
        Submit captcha:
        <code>input_pic_verify_code -code=XXXX</code>
        </p>

        <p>
        Request SMS:
        <code>req_phone_verify_code</code>
        </p>

        <p>
        Submit SMS:
        <code>input_phone_verify_code -code=123456</code>
        </p>

        <img id="captcha">
    </div>

</div>

<script>
let ws;
let healthy = false;
let terminalVisible = true;
let captchaMtime = 0;

function connectTerminal() {

    const protocol =
        location.protocol === "https:" ? "wss://" : "ws://";

    ws = new WebSocket(
        protocol + location.host + "/ws"
    );

    ws.onmessage = event => {

        const terminal =
            document.getElementById("terminal");

        terminal.textContent += event.data;

        terminal.scrollTop =
            terminal.scrollHeight;
    };

    ws.onclose = () => {

        // Login API status is authoritative.
        // Only retry the terminal transport.
        setTimeout(connectTerminal, 1500);
    };
}

function sendCommand() {

    const input =
        document.getElementById("command");

    const value =
        input.value.trim();

    if (!value)
        return;

    if (
        ws &&
        ws.readyState === WebSocket.OPEN
    ) {
        ws.send(value);
    }

    /*
      Deliberately do NOT echo user input here.

      OpenD itself controls what gets displayed,
      which prevents passwords from being leaked
      by this webpage.
    */

    input.value = "";
    input.focus();
}

document
.getElementById("command")
.addEventListener("keydown", e => {

    if (e.key === "Enter") {

        e.preventDefault();
        sendCommand();
    }
});

function toggleTerminal() {

    const section =
        document.getElementById("terminalSection");

    terminalVisible =
        !terminalVisible;

    section.style.display =
        terminalVisible ? "block" : "none";

    document.getElementById(
        "terminalButton"
    ).textContent =
        terminalVisible
        ? "Hide terminal"
        : "Open terminal";
}

async function checkAPI() {

    try {

        const r =
            await fetch(
                "/api-status?t=" + Date.now(),
                {cache:"no-store"}
            );

        const d =
            await r.json();

        const card =
            document.getElementById("statusCard");

        const title =
            document.getElementById("statusTitle");

        const details =
            document.getElementById("statusDetails");

        const button =
            document.getElementById("terminalButton");

        if (d.ready) {

            healthy = true;

            card.className =
                "card success";

            title.textContent =
                "✓ OpenD logged in successfully";

            details.innerHTML = `
                <div class="detail">
                    <b>API:</b> Connected
                </div>

                <div class="detail">
                    <b>OpenD:</b>
                    ${d.server_ver || "Unknown"}
                </div>

                <div class="detail">
                    <b>Quote server:</b>
                    ${d.qot_logined ? "Logged in" : "Not logged in"}
                </div>

                <div class="detail">
                    <b>Trade server:</b>
                    ${d.trd_logined ? "Logged in" : "Not logged in"}
                </div>

                <div class="detail">
                    <b>Program status:</b>
                    ${d.program_status || "Unknown"}
                </div>

                ${
                    d.account
                    ? `<div class="detail">
                         <b>Account:</b> ${d.account}
                       </div>`
                    : ""
                }

                <hr>

                <div class="detail">
                    <b>API test:</b>
                    ${d.test_code}
                    ${d.test_name}
                </div>

                <div class="detail">
                    <b>Latest price:</b>
                    ${d.test_price}
                </div>

                <div class="detail">
                    <b>Market-data update:</b>
                    ${d.test_update}
                </div>
            `;

            button.style.display =
                "inline-block";

            if (terminalVisible) {

                terminalVisible = false;

                document.getElementById(
                    "terminalSection"
                ).style.display = "none";

                button.textContent =
                    "Open terminal";
            }

        } else {

            healthy = false;

            card.className =
                "card waiting";

            title.textContent =
                "Waiting for OpenD login...";

            details.textContent =
                d.error ||
                "API is not ready yet.";

            button.style.display =
                "none";

            /*
              If API stops working, automatically
              bring the login terminal back.
            */

            if (!terminalVisible) {

                terminalVisible = true;

                document.getElementById(
                    "terminalSection"
                ).style.display = "block";
            }
        }

    } catch (e) {

        console.log(e);
    }
}

async function checkCaptcha() {

    try {

        const r =
            await fetch(
                "/captcha-status?t=" + Date.now(),
                {cache:"no-store"}
            );

        const d =
            await r.json();

        const img =
            document.getElementById("captcha");

        if (d.exists) {

            if (d.mtime !== captchaMtime) {

                captchaMtime =
                    d.mtime;

                img.src =
                    "/captcha?t=" +
                    Date.now();
            }

            img.style.display =
                "block";

        } else {

            img.style.display =
                "none";
        }

    } catch (_) {}
}

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

        # Prevent unlimited memory growth
        if len(terminal_history) > 100000:
            terminal_history = terminal_history[-100000:]


@app.route("/")
def index():
    return render_template_string(HTML)


@sock.route("/ws")
def terminal_ws(ws):

    conn = socket.create_connection(
        (OPEND_HOST, OPEND_TELNET_PORT),
        timeout=10
    )

    conn.settimeout(0.5)

    closed = threading.Event()

    def opend_to_browser():

        try:

            while not closed.is_set():

                try:
                    data = conn.recv(8192)

                    if not data:
                        break

                    text = data.decode(
                        "utf-8",
                        errors="replace"
                    )

                    append_history(text)

                    ws.send(text)

                except socket.timeout:
                    continue

                except Exception:
                    break

        finally:
            closed.set()

    reader = threading.Thread(
        target=opend_to_browser,
        daemon=True
    )

    reader.start()

    try:

        while not closed.is_set():

            message = ws.receive()

            if message is None:
                break

            conn.sendall(
                (message + "\r\n").encode()
            )

            # NEVER store browser input.
            # OpenD decides what is echoed/masked.

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

        ctx = OpenQuoteContext(
            host=OPEND_HOST,
            port=OPEND_API_PORT
        )

        ret, state = ctx.get_global_state()

        if ret != RET_OK:
            return jsonify(
                ready=False,
                error=str(state)
            )

        if not state.get(
            "qot_logined",
            False
        ):
            return jsonify(
                ready=False,
                error="OpenD quote server is not logged in."
            )

        ret, snapshot = (
            ctx.get_market_snapshot(
                ["US.AAPL"]
            )
        )

        if ret != RET_OK:
            return jsonify(
                ready=False,
                error=str(snapshot)
            )

        row = snapshot.iloc[0]

        account = None

        with history_lock:

            match = re.search(
                r"Login Account:\s*([0-9]+)",
                terminal_history
            )

            if match:
                account = match.group(1)

        return jsonify(

            ready=True,

            server_ver=state.get(
                "server_ver"
            ),

            qot_logined=bool(
                state.get("qot_logined")
            ),

            trd_logined=bool(
                state.get("trd_logined")
            ),

            program_status=str(
                state.get(
                    "program_status_type",
                    ""
                )
            ),

            account=account,

            test_code=str(
                row.get(
                    "code",
                    "US.AAPL"
                )
            ),

            test_name=str(
                row.get(
                    "name",
                    ""
                )
            ),

            test_price=str(
                row.get(
                    "last_price",
                    ""
                )
            ),

            test_update=str(
                row.get(
                    "update_time",
                    ""
                )
            )
        )

    except Exception as e:

        return jsonify(
            ready=False,
            error=str(e)
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

        return jsonify(
            exists=False,
            mtime=0
        )

    return jsonify(

        exists=True,

        mtime=os.path.getmtime(
            CAPTCHA
        )
    )


@app.route("/captcha")
def captcha():

    if not os.path.exists(CAPTCHA):

        return (
            "Captcha not available",
            404
        )

    response = make_response(
        send_file(
            CAPTCHA,
            mimetype="image/png"
        )
    )

    response.headers[
        "Cache-Control"
    ] = "no-store, no-cache, must-revalidate, max-age=0"

    response.headers[
        "Pragma"
    ] = "no-cache"

    response.headers[
        "Expires"
    ] = "0"

    return response


app.run(
    host="0.0.0.0",
    port=6789,
    threaded=True
)
