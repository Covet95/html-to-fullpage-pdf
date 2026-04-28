#!/usr/bin/env python3
"""
html2pdf.py — HTML → Full-Page PNG + PDF Converter

Usage:
  python html2pdf.py <file.html>          # convert one file
  python html2pdf.py f1.html f2.html ...  # convert multiple files
  python html2pdf.py                      # open file-picker dialog

Outputs (same directory as input):
  <stem>-fullpage.png   full-page screenshot at 1400px width
  <stem>-fullpage.pdf   PDF generated from the PNG (exact visual match)

Requirements:
  Python 3.x, Pillow  (pip install Pillow)
  Google Chrome or Microsoft Edge installed at a standard system path
"""

import sys
import os
import time
import threading
import subprocess
import socket
import json
import base64
import struct
import http.server
import socketserver
import urllib.request
from pathlib import Path


# ── Chrome / Edge locations ───────────────────────────────────────────────────
CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",  # macOS
    "/usr/bin/google-chrome",                                         # Linux
    "/usr/bin/chromium-browser",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def find_chrome():
    for p in CHROME_PATHS:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(
        "Chrome/Edge not found. Update CHROME_PATHS in this script."
    )


def find_free_port():
    with socket.socket() as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def start_http_server(directory, port):
    os.chdir(directory)

    class SilentHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    httpd = socketserver.TCPServer(("", port), SilentHandler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


# ── Minimal WebSocket client (stdlib only) ────────────────────────────────────

def _ws_handshake(sock, host, path):
    key = base64.b64encode(os.urandom(16)).decode()
    sock.sendall((
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n\r\n"
    ).encode())
    buf = b""
    while b"\r\n\r\n" not in buf:
        buf += sock.recv(4096)


def _ws_send(sock, message):
    data = message.encode()
    n = len(data)
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    header = b"\x81"
    if n < 126:
        header += bytes([0x80 | n])
    elif n < 65536:
        header += struct.pack("!BH", 0xFE, n)
    else:
        header += struct.pack("!BQ", 0xFF, n)
    sock.sendall(header + mask + masked)


def _ws_recv(sock):
    def read_exact(n):
        buf = b""
        while len(buf) < n:
            chunk = sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("WebSocket connection closed")
            buf += chunk
        return buf

    h = read_exact(2)
    masked = (h[1] & 0x80) != 0
    length = h[1] & 0x7F
    if length == 126:
        length = struct.unpack("!H", read_exact(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read_exact(8))[0]
    mask_key = read_exact(4) if masked else None
    payload = read_exact(length)
    if masked:
        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))
    return payload.decode("utf-8", errors="replace")


def _cdp_connect(ws_url):
    parsed = urllib.request.urlparse(ws_url)
    host, port_str = parsed.netloc.split(":")
    sock = socket.create_connection((host, int(port_str)))
    _ws_handshake(sock, parsed.netloc, parsed.path)
    sock.settimeout(30)
    return sock


def _cdp_call(sock, cmd_id, method, params=None, timeout=25):
    _ws_send(sock, json.dumps({"id": cmd_id, "method": method, "params": params or {}}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = json.loads(_ws_recv(sock))
            if data.get("id") == cmd_id:
                return data.get("result", {})
        except socket.timeout:
            break
    return {}


# ── Core screenshot logic ─────────────────────────────────────────────────────

def _wait_for_chrome(debug_port, retries=20):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(
                f"http://localhost:{debug_port}/json", timeout=2
            ) as r:
                return json.loads(r.read())
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("Chrome did not start in time")


def take_fullpage_screenshot(page_url, png_path, debug_port):
    tabs = _wait_for_chrome(debug_port)

    ws_url = next(
        (t["webSocketDebuggerUrl"] for t in tabs if t.get("type") == "page"),
        None,
    )
    if not ws_url:
        raise RuntimeError("No debuggable page tab found")

    # Navigate to the target page
    sock = _cdp_connect(ws_url)
    _cdp_call(sock, 10, "Page.navigate", {"url": page_url})
    time.sleep(3)
    sock.close()

    # Reconnect (navigation may change the WS URL)
    tabs = _wait_for_chrome(debug_port, retries=5)
    ws_url = next(
        (t["webSocketDebuggerUrl"] for t in tabs if t.get("type") == "page"),
        ws_url,
    )
    sock = _cdp_connect(ws_url)

    # Fix sticky/fixed elements so they don't cause duplicate rendering or extra blank space
    _cdp_call(sock, 0, "Runtime.evaluate", {
        "expression": (
            "document.querySelectorAll('*').forEach(function(el){"
            "  var s = getComputedStyle(el).position;"
            "  if (s === 'sticky' || s === 'fixed') el.style.position = 'static';"
            "});"
        ),
        "returnByValue": False,
    })
    time.sleep(0.2)

    # Query true page dimensions
    result = _cdp_call(sock, 1, "Runtime.evaluate", {
        "expression": (
            "({w: document.documentElement.scrollWidth,"
            " h: document.documentElement.scrollHeight})"
        ),
        "returnByValue": True,
    })
    dims = result.get("result", {}).get("value", {})
    width = max(dims.get("w", 1400), 1400)
    height = dims.get("h", 3000)

    # Override device metrics to capture the full page
    _cdp_call(sock, 2, "Emulation.setDeviceMetricsOverride", {
        "width": width, "height": height,
        "deviceScaleFactor": 1, "mobile": False,
    })
    time.sleep(0.5)

    # Capture screenshot
    result = _cdp_call(sock, 3, "Page.captureScreenshot", {
        "format": "png", "captureBeyondViewport": True,
    }, timeout=30)
    sock.close()

    img_data = result.get("data", "")
    if not img_data:
        raise RuntimeError("Empty screenshot data returned by Chrome")

    with open(png_path, "wb") as f:
        f.write(base64.b64decode(img_data))

    # Auto-crop trailing blank rows caused by Chrome viewport height inflation.
    # Uses max-channel brightness > 100 to detect real content vs dark/light
    # background gradients (which typically stay below 65 even in dark themes).
    from PIL import Image as _PILImage
    _img = _PILImage.open(png_path).convert("RGB")
    _w, _h = _img.size
    _content_bottom = _h
    for _y in range(_h - 1, 0, -1):
        _samples = [_img.getpixel((_x, _y)) for _x in range(0, _w, 10)]
        if any(max(_r, _g, _b) > 100 for _r, _g, _b in _samples):
            _content_bottom = min(_y + 41, _h)
            break
    if _content_bottom < _h:
        _img.crop((0, 0, _w, _content_bottom)).save(png_path)
        height = _content_bottom

    return width, height


def png_to_pdf(png_path, pdf_path):
    from PIL import Image
    img = Image.open(png_path)
    if img.mode == "RGBA":
        img = img.convert("RGB")
    img.save(str(pdf_path), "PDF", resolution=96)


# ── Public entry point ────────────────────────────────────────────────────────

def convert(html_file: str):
    """Convert a single HTML file to full-page PNG + PDF."""
    p = Path(html_file).resolve()
    if not p.exists():
        print(f"[ERROR] File not found: {p}")
        return False

    png_path = p.parent / f"{p.stem}-fullpage.png"
    pdf_path = p.parent / f"{p.stem}-fullpage.pdf"

    print(f"\n[html2pdf] {p.name}")

    chrome = find_chrome()
    http_port = find_free_port()
    debug_port = find_free_port()

    httpd = start_http_server(str(p.parent), http_port)
    page_url = f"http://localhost:{http_port}/{p.name}"

    chrome_proc = subprocess.Popen(
        [
            chrome,
            f"--remote-debugging-port={debug_port}",
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-extensions",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        print("  Capturing full-page screenshot...")
        w, h = take_fullpage_screenshot(page_url, png_path, debug_port)
        print(f"  PNG  {w} × {h} px  →  {png_path.name}")

        print("  Converting to PDF...")
        png_to_pdf(png_path, pdf_path)
        print(f"  PDF  →  {pdf_path.name}")
        return True

    except Exception as e:
        print(f"  [ERROR] {e}")
        import traceback; traceback.print_exc()
        return False

    finally:
        chrome_proc.terminate()
        httpd.shutdown()


def main():
    if len(sys.argv) > 1:
        results = [convert(arg) for arg in sys.argv[1:]]
        success = sum(results)
        print(f"\nDone: {success}/{len(results)} file(s) converted.")
    else:
        # Interactive file-picker
        try:
            import tkinter as tk
            from tkinter import filedialog
            root = tk.Tk(); root.withdraw()
            files = filedialog.askopenfilenames(
                title="Select HTML file(s)",
                filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")],
            )
            if files:
                for f in files:
                    convert(f)
            else:
                print("No file selected.")
        except Exception as e:
            print(f"Error: {e}")
            print("Usage: python html2pdf.py <file.html>")

    try:
        input("\nPress Enter to exit...")
    except EOFError:
        pass


if __name__ == "__main__":
    main()
