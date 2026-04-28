---
name: html-to-fullpage-pdf
description: Convert any HTML file to a full-page screenshot (PNG) and a visually faithful PDF that looks exactly like the browser view — no layout distortion, no A4 reformatting. Use this skill whenever the user wants to: export an HTML report/page to PDF without distortion, convert HTML to a long image, take a full-page screenshot of an HTML file, or generate a PDF that preserves the original design perfectly. Trigger on phrases like "convert HTML to PDF", "HTML 转 PDF", "生成长图", "转成图片", "export as PDF", "screenshot this page", "网页截图", "保存为PDF", "HTML转图片". Always use this skill before reaching for browser print-to-PDF — the result is significantly more faithful.
---

## What this skill does

Converts an HTML file into two outputs, both saved **in the same directory as the input file**:

| Output | Description |
|--------|-------------|
| `<stem>-fullpage.png` | Full-page screenshot, 1400px wide, exact visual match |
| `<stem>-fullpage.pdf` | PDF generated directly from the PNG — zero layout distortion |

The key insight: browser print-to-PDF reformats content for A4 paper and breaks visual designs. This skill screenshots the page first (like a camera), then wraps that image into a PDF — so what you see in the browser is exactly what you get in the PDF.

## How to run

Use the bundled script `scripts/html2pdf.py`. It requires:
- **Python 3.x** with **Pillow** (`pip install Pillow`)
- **Google Chrome** or **Microsoft Edge** installed (standard system paths)

### Single file
```bash
python scripts/html2pdf.py "C:/path/to/file.html"
```

### Multiple files
```bash
python scripts/html2pdf.py "file1.html" "file2.html"
```

### Interactive (file picker dialog)
```bash
python scripts/html2pdf.py
```

## How it works internally

1. Starts a **local HTTP server** (random free port) — this lets Chrome load the HTML with correct relative paths for CSS/JS/images
2. Launches **Chrome headless** with remote debugging enabled
3. Connects via **Chrome DevTools Protocol (CDP)** over WebSocket
4. Navigates to the page and waits for it to render (`networkidle`)
5. Queries the actual `scrollHeight` to determine the true page length
6. Sets the viewport to the full page height and **captures a screenshot** via CDP
7. Converts the PNG to PDF using Pillow — one page, exact dimensions

No external Python packages beyond Pillow are required. The CDP WebSocket client is implemented from scratch using only stdlib.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Chrome not found | Update `CHROME_PATHS` list at the top of `scripts/html2pdf.py` |
| `ModuleNotFoundError: PIL` | Run `pip install Pillow` |
| Page renders incorrectly | The HTML may rely on external fonts/resources; ensure network access |
| Very tall pages (>15,000px) | Chrome has memory limits; split the content or reduce page width |

## When NOT to use this skill

- The user wants to convert a **live URL** (not a local HTML file) → use browser print or a different approach
- The user wants a **multi-page PDF** with proper pagination → use browser print-to-PDF
- The user wants to **edit** the PDF content → this skill produces image-based PDFs
