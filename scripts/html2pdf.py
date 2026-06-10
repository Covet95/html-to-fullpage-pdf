#!/usr/bin/env python3
"""
html2pdf.py - Convert local HTML files to high-quality PDF and screenshots.

Default output is a vector PDF (<stem>-vector.pdf). Use --mode raster for the
legacy screenshot-based PNG/PDF pair, or --mode both to generate all outputs.
"""

import argparse
import base64
import functools
import http.server
import json
import os
from pathlib import Path
import shutil
import socket
import socketserver
import struct
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request


CHROME_PATHS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/snap/bin/chromium",
]

CSS_DPI = 96


class ReusableTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Convert local HTML files to vector PDF, raster PNG/PDF, or both."
    )
    parser.add_argument("html_files", nargs="*", help="Local .html/.htm files")
    parser.add_argument(
        "--mode",
        choices=("vector", "raster", "both"),
        default="vector",
        help="Output mode. Default: vector",
    )
    parser.add_argument(
        "--width",
        type=int,
        default=1400,
        help="CSS pixel width used for layout before measuring/exporting. Default: 1400",
    )
    parser.add_argument(
        "--selector",
        default="body",
        help="Element used to determine output height. Default: body",
    )
    parser.add_argument(
        "--padding-bottom",
        type=int,
        default=0,
        help="Extra CSS pixels to keep below the measured selector. Default: 0",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=2.0,
        help="Seconds to wait after navigation for rendering/assets. Default: 2.0",
    )
    parser.add_argument(
        "--device-scale-factor",
        type=float,
        default=1.0,
        help="Raster screenshot scale. Default: 1.0",
    )
    return parser.parse_args(argv)


def find_chrome():
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    raise FileNotFoundError("Chrome/Edge not found. Update CHROME_PATHS in html2pdf.py.")


def find_free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def build_page_url(port, html_path):
    return f"http://127.0.0.1:{port}/{urllib.parse.quote(Path(html_path).name)}"


def start_http_server(directory, port):
    class SilentHandler(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(SilentHandler, directory=str(directory))
    httpd = ReusableTCPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


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
    mask = os.urandom(4)
    masked = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    header = b"\x81"
    if len(data) < 126:
        header += bytes([0x80 | len(data)])
    elif len(data) < 65536:
        header += struct.pack("!BH", 0xFE, len(data))
    else:
        header += struct.pack("!BQ", 0xFF, len(data))
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

    header = read_exact(2)
    opcode = header[0] & 0x0F
    length = header[1] & 0x7F
    masked = (header[1] & 0x80) != 0
    if length == 126:
        length = struct.unpack("!H", read_exact(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read_exact(8))[0]
    mask = read_exact(4) if masked else None
    payload = read_exact(length)
    if mask:
        payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
    if opcode == 8:
        raise ConnectionError("WebSocket closed by peer")
    return payload.decode("utf-8", errors="replace")


def _cdp_connect(ws_url):
    parsed = urllib.parse.urlparse(ws_url)
    host, port = parsed.netloc.split(":")
    sock = socket.create_connection((host, int(port)))
    _ws_handshake(sock, parsed.netloc, parsed.path)
    sock.settimeout(60)
    return sock


def _cdp_call(sock, cmd_id, method, params=None, timeout=60):
    _ws_send(sock, json.dumps({"id": cmd_id, "method": method, "params": params or {}}))
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            data = json.loads(_ws_recv(sock))
        except socket.timeout:
            continue
        if data.get("id") != cmd_id:
            continue
        if "error" in data:
            raise RuntimeError(f"{method}: {data['error']}")
        return data.get("result", {})
    raise TimeoutError(method)


def _wait_for_chrome(debug_port, retries=40):
    for _ in range(retries):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{debug_port}/json", timeout=1) as res:
                return json.loads(res.read())
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("Chrome did not start in time")


def _first_page_ws_url(debug_port):
    tabs = _wait_for_chrome(debug_port)
    for tab in tabs:
        if tab.get("type") == "page" and tab.get("webSocketDebuggerUrl"):
            return tab["webSocketDebuggerUrl"]
    raise RuntimeError("No debuggable Chrome page found")


def launch_chrome(chrome_path, debug_port):
    profile = tempfile.mkdtemp(prefix="html2pdf-chrome-")
    proc = subprocess.Popen(
        [
            chrome_path,
            f"--remote-debugging-port={debug_port}",
            f"--user-data-dir={profile}",
            "--headless=new",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return proc, profile


def close_chrome(proc, profile):
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    shutil.rmtree(profile, ignore_errors=True)


def prepare_page(debug_port, page_url, width, wait_seconds, device_scale_factor=1.0):
    sock = _cdp_connect(_first_page_ws_url(debug_port))
    _cdp_call(sock, 1, "Page.enable")
    _cdp_call(sock, 2, "Emulation.setDeviceMetricsOverride", {
        "width": width,
        "height": 1200,
        "deviceScaleFactor": device_scale_factor,
        "mobile": False,
    })
    _cdp_call(sock, 3, "Emulation.setEmulatedMedia", {"media": "screen"})
    _cdp_call(sock, 4, "Page.navigate", {"url": page_url})
    time.sleep(wait_seconds)
    _cdp_call(sock, 5, "Runtime.evaluate", {
        "expression": (
            "document.querySelectorAll('*').forEach(function(el){"
            "  var p = getComputedStyle(el).position;"
            "  if (p === 'sticky' || p === 'fixed') el.style.position = 'static';"
            "});"
        )
    })
    return sock


def measure_content(sock, selector, width, padding_bottom=0):
    js_selector = json.dumps(selector)
    result = _cdp_call(sock, 10, "Runtime.evaluate", {
        "expression": f"""
        (() => {{
          const target = document.querySelector({js_selector}) || document.body || document.documentElement;
          const doc = document.documentElement;
          const body = document.body || doc;
          const rect = target.getBoundingClientRect();
          const bodyRect = body.getBoundingClientRect();
          const right = Math.ceil(rect.right + window.scrollX);
          const bottom = Math.ceil(rect.bottom + window.scrollY);
          const bodyBottom = Math.ceil(bodyRect.bottom + window.scrollY);
          const trailingBodyGap = Math.max(0, Math.min(80, bodyBottom - bottom));
          return {{
            width: Math.max({width}, doc.scrollWidth, body.scrollWidth, right),
            height: Math.max(1, bottom + trailingBodyGap + {padding_bottom}),
            selector: {js_selector},
            target: {{
              top: rect.top,
              left: rect.left,
              width: rect.width,
              height: rect.height,
              bottom: rect.bottom,
              right: rect.right
            }},
            trailingBodyGap,
            scroll: {{
              width: doc.scrollWidth,
              height: doc.scrollHeight
            }}
          }};
        }})()
        """,
        "returnByValue": True,
    })
    value = result.get("result", {}).get("value")
    if not value:
        raise RuntimeError("Could not measure page content")
    return value


def print_vector_pdf(sock, pdf_path, width, height):
    result = _cdp_call(sock, 20, "Page.printToPDF", {
        "printBackground": True,
        "landscape": False,
        "displayHeaderFooter": False,
        "paperWidth": width / CSS_DPI,
        "paperHeight": height / CSS_DPI,
        "marginTop": 0,
        "marginBottom": 0,
        "marginLeft": 0,
        "marginRight": 0,
        "scale": 1,
        "preferCSSPageSize": False,
        "transferMode": "ReturnAsBase64",
    })
    data = result.get("data")
    if not data:
        raise RuntimeError("Chrome returned an empty PDF")
    pdf_path.write_bytes(base64.b64decode(data))


def capture_raster_png(sock, png_path, width, height, device_scale_factor=1.0):
    _cdp_call(sock, 30, "Emulation.setDeviceMetricsOverride", {
        "width": width,
        "height": height,
        "deviceScaleFactor": device_scale_factor,
        "mobile": False,
    })
    time.sleep(0.2)
    result = _cdp_call(sock, 31, "Page.captureScreenshot", {
        "format": "png",
        "captureBeyondViewport": True,
    }, timeout=90)
    data = result.get("data")
    if not data:
        raise RuntimeError("Chrome returned an empty screenshot")
    png_path.write_bytes(base64.b64decode(data))


def png_to_pdf(png_path, pdf_path, resolution):
    from PIL import Image

    image = Image.open(png_path)
    if image.mode == "RGBA":
        image = image.convert("RGB")
    image.save(str(pdf_path), "PDF", resolution=resolution)


def convert(html_file, args=None):
    if args is None:
        args = parse_args([str(html_file)])

    html_path = Path(html_file).resolve()
    if not html_path.exists():
        print(f"[ERROR] File not found: {html_path}")
        return False

    vector_pdf = html_path.parent / f"{html_path.stem}-vector.pdf"
    png_path = html_path.parent / f"{html_path.stem}-fullpage.png"
    raster_pdf = html_path.parent / f"{html_path.stem}-fullpage.pdf"

    print(f"\n[html2pdf] {html_path.name}")
    chrome = find_chrome()
    http_port = find_free_port()
    debug_port = find_free_port()
    httpd = start_http_server(html_path.parent, http_port)
    chrome_proc, chrome_profile = launch_chrome(chrome, debug_port)

    sock = None
    try:
        page_url = build_page_url(http_port, html_path)
        sock = prepare_page(
            debug_port,
            page_url,
            args.width,
            args.wait,
            device_scale_factor=1.0,
        )
        dims = measure_content(sock, args.selector, args.width, args.padding_bottom)
        width = int(dims["width"])
        height = int(dims["height"])
        print(f"  Layout {width} x {height} CSS px using selector {args.selector!r}")

        if args.mode in ("vector", "both"):
            print("  Writing vector PDF...")
            print_vector_pdf(sock, vector_pdf, width, height)
            print(f"  PDF  ->  {vector_pdf.name}")

        if args.mode in ("raster", "both"):
            print("  Capturing raster screenshot...")
            capture_raster_png(
                sock,
                png_path,
                width,
                height,
                device_scale_factor=args.device_scale_factor,
            )
            print(f"  PNG  ->  {png_path.name}")
            print("  Wrapping PNG in PDF...")
            png_to_pdf(png_path, raster_pdf, CSS_DPI * args.device_scale_factor)
            print(f"  PDF  ->  {raster_pdf.name}")
        return True

    except Exception as exc:
        print(f"  [ERROR] {exc}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        close_chrome(chrome_proc, chrome_profile)
        httpd.shutdown()
        httpd.server_close()


def choose_files_interactively():
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        return list(filedialog.askopenfilenames(
            title="Select HTML file(s)",
            filetypes=[("HTML files", "*.html *.htm"), ("All files", "*.*")],
        ))
    except Exception as exc:
        print(f"Error opening file picker: {exc}")
        return []


def main(argv=None):
    args = parse_args(argv)
    files = args.html_files or choose_files_interactively()
    if not files:
        print("Usage: python html2pdf.py [--mode vector|raster|both] <file.html> [...]")
        return 1

    results = [convert(path, args) for path in files]
    print(f"\nDone: {sum(results)}/{len(results)} file(s) converted.")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
