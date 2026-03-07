#!/usr/bin/env bash
set -euo pipefail

ASOT_CONFIG_DIR="${ASOT_CONFIG_DIR:-$HOME/.config/asot}"
PLAYWRIGHT_CORE_DIR="${PLAYWRIGHT_CORE_DIR:-}"
CHROME_BIN="${CHROME_BIN:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
ENV_FILE="${ENV_FILE:-$ASOT_CONFIG_DIR/asot.env}"
CAPTION="Playwright screenshot"
OUT_FILE="${OUT_FILE:-/tmp/telegram-playwright-shot.png}"
REMOTE_DEBUGGING_PORT="${REMOTE_DEBUGGING_PORT:-9222}"
URL="data:text/html,%3C!doctype%20html%3E%3Chtml%3E%3Chead%3E%3Cmeta%20charset%3D%22utf-8%22%3E%3Cstyle%3Ebody%7Bmargin%3A0%3Bfont-family%3AArial%2Csans-serif%3Bbackground%3Alinear-gradient(135deg%2C%23f5f7fa%2C%23c3cfe2)%3Bdisplay%3Aflex%3Balign-items%3Acenter%3Bjustify-content%3Acenter%3Bheight%3A100vh%7D.card%7Bbackground%3Awhite%3Bpadding%3A48px%2056px%3Bborder-radius%3A24px%3Bbox-shadow%3A0%2024px%2080px%20rgba(0%2C0%2C0%2C.18)%3Btext-align%3Acenter%7Dh1%7Bmargin%3A0%200%2012px%3Bfont-size%3A42px%7Dp%7Bmargin%3A0%3Bfont-size%3A22px%3Bcolor%3A%23475569%7D%3C/style%3E%3C/head%3E%3Cbody%3E%3Cdiv%20class%3D%22card%22%3E%3Ch1%3EPlaywright%20Test%3C/h1%3E%3Cp%3EChrome%20opened%20and%20screenshot%20captured.%3C/p%3E%3C/div%3E%3C/body%3E%3C/html%3E"

usage() {
  cat <<'EOF'
usage: playwright-screenshot-to-telegram.sh [options]

options:
  --url URL            Page URL to capture
  --caption TEXT       Telegram caption
  --out PATH           Screenshot output path
  --env-file PATH      Telegram env file
  --port PORT          Chrome remote debugging port
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --url)
      URL="${2:-}"
      shift 2
      ;;
    --caption)
      CAPTION="${2:-}"
      shift 2
      ;;
    --out)
      OUT_FILE="${2:-}"
      shift 2
      ;;
    --env-file)
      ENV_FILE="${2:-}"
      shift 2
      ;;
    --port)
      REMOTE_DEBUGGING_PORT="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "unknown arg: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

[[ -n "$PLAYWRIGHT_CORE_DIR" ]] || { echo "PLAYWRIGHT_CORE_DIR is required" >&2; exit 1; }
[[ -d "$PLAYWRIGHT_CORE_DIR" ]] || { echo "playwright-core not found: $PLAYWRIGHT_CORE_DIR" >&2; exit 1; }
[[ -x "$CHROME_BIN" ]] || { echo "chrome not found: $CHROME_BIN" >&2; exit 1; }
[[ -f "$ENV_FILE" ]] || { echo "telegram env not found: $ENV_FILE" >&2; exit 1; }

USER_DATA_DIR="$(mktemp -d /tmp/chrome-pw-telegram.XXXXXX)"
cleanup() {
  if [[ -n "${CHROME_PID:-}" ]]; then
    kill "$CHROME_PID" >/dev/null 2>&1 || true
  fi
  rm -rf "$USER_DATA_DIR"
}
trap cleanup EXIT

"$CHROME_BIN" \
  --remote-debugging-port="$REMOTE_DEBUGGING_PORT" \
  --user-data-dir="$USER_DATA_DIR" \
  --new-window about:blank \
  >/tmp/chrome-pw-telegram.log 2>&1 &
CHROME_PID=$!

for _ in $(seq 1 30); do
  if python3 - <<PY
import socket
s = socket.socket()
s.settimeout(0.5)
s.connect(("127.0.0.1", int("$REMOTE_DEBUGGING_PORT")))
s.close()
PY
  then
    break
  fi
  sleep 1
done

node - <<'JS' "$PLAYWRIGHT_CORE_DIR" "$REMOTE_DEBUGGING_PORT" "$URL" "$OUT_FILE"
const playwrightCoreDir = process.argv[2];
const port = process.argv[3];
const url = process.argv[4];
const outFile = process.argv[5];
const { chromium } = require(playwrightCoreDir);

(async () => {
  const browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`);
  const context = browser.contexts()[0] || await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await context.newPage();
  await page.goto(url, { waitUntil: "load" });
  await page.screenshot({ path: outFile, fullPage: true });
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
JS

python3 - <<'PY' "$ENV_FILE" "$OUT_FILE" "$CAPTION"
import sys
import urllib.request
from pathlib import Path

env_file = Path(sys.argv[1])
image_path = Path(sys.argv[2])
caption = sys.argv[3]

values = {}
for raw in env_file.read_text(encoding="utf-8").splitlines():
    line = raw.strip()
    if not line or line.startswith("#"):
        continue
    if line.startswith("export "):
        line = line[7:]
    if "=" in line:
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()

bot_token = values["TELEGRAM_BOT_TOKEN"]
chat_id = values["TELEGRAM_CHAT_ID"]
image_bytes = image_path.read_bytes()
boundary = b"----TelegramFormBoundary"
parts = []

def add_text(name, value):
    parts.extend([
        b"--" + boundary,
        ('Content-Disposition: form-data; name="%s"' % name).encode(),
        b"",
        value.encode(),
    ])

add_text("chat_id", chat_id)
add_text("caption", caption)
parts.extend([
    b"--" + boundary,
    b'Content-Disposition: form-data; name="document"; filename="playwright-shot.png"',
    b"Content-Type: image/png",
    b"",
    image_bytes,
    b"--" + boundary + b"--",
    b"",
])

body = b"\r\n".join(parts)
req = urllib.request.Request(
    "https://api.telegram.org/bot%s/sendDocument" % bot_token,
    data=body,
    headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary.decode()},
)
with urllib.request.urlopen(req, timeout=20) as response:
    print(response.read().decode("utf-8"))
PY
