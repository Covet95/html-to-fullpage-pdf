# html-to-fullpage-pdf

Convert any HTML file to a full-page screenshot (PNG) and a visually faithful PDF — no layout distortion, no A4 reformatting.

## Why

Browser print-to-PDF reformats content for A4 paper and breaks visual designs. This tool screenshots the page first (like a camera), then wraps that image into a PDF — so what you see in the browser is exactly what you get in the PDF.

## Output

For each input file, two files are saved **in the same directory as the HTML**:

| File | Description |
|------|-------------|
| `<stem>-fullpage.png` | Full-page screenshot, 1400px wide |
| `<stem>-fullpage.pdf` | PDF generated directly from the PNG |

## Requirements

- Python 3.x
- [Pillow](https://pypi.org/project/Pillow/) — `pip install Pillow`
- Google Chrome or Microsoft Edge installed at a standard system path

## Usage

```bash
# Single file
python scripts/html2pdf.py "C:/path/to/file.html"

# Multiple files
python scripts/html2pdf.py file1.html file2.html

# Interactive file picker (no arguments)
python scripts/html2pdf.py
```

## How it works

1. Starts a local HTTP server so Chrome loads the HTML with correct relative paths
2. Launches Chrome headless with remote debugging (CDP)
3. Fixes sticky/fixed elements to avoid duplicate rendering
4. Queries the true `scrollHeight` of the page
5. Sets viewport to full page height and captures a screenshot
6. Auto-crops trailing blank rows
7. Converts the PNG to a single-page PDF via Pillow

No external packages beyond Pillow — the CDP WebSocket client is pure stdlib.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Chrome not found | Update `CHROME_PATHS` at the top of `scripts/html2pdf.py` |
| `ModuleNotFoundError: PIL` | Run `pip install Pillow` |
| Page renders incorrectly | HTML may rely on external resources; ensure network access |
| Very tall pages (>15,000px) | Chrome has memory limits; reduce content or page width |

## Limitations

- Local HTML files only (not live URLs)
- Single-page PDF output (no pagination)
- Image-based PDF (text is not selectable)
