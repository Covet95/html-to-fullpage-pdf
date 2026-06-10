---
name: html-to-fullpage-pdf
description: >-
  Use when converting local HTML files to PDF or PNG, exporting HTML reports,
  resumes, dashboards, or pages without A4 reflow, preserving browser layout,
  creating high-resolution/text-selectable PDFs, taking full-page screenshots,
  long images, or handling requests like HTML 转 PDF, 保存为PDF, 网页截图, 生成长图.
---

## What this skill does

Converts a local HTML file through Chrome/CDP while preserving the browser layout. Outputs are saved **in the same directory as the input file**.

| Mode | Output | Use when |
|------|--------|----------|
| `vector` (default) | `<stem>-vector.pdf` | User wants a clear PDF, text should stay sharp/selectable, or screenshots look blurry/noisy |
| `raster` | `<stem>-fullpage.png`, `<stem>-fullpage.pdf` | User explicitly wants a screenshot, long image, or PNG-wrapped PDF |
| `both` | all outputs above | User asks for both image and PDF variants |

Default to `vector`. Do not use the raster PNG-to-PDF path for resumes, documents, or text-heavy reports unless the user explicitly wants an image-based PDF; it will blur text when zoomed.

## How to run

Use the bundled script `scripts/html2pdf.py`. It requires:
- **Python 3.x**
- **Pillow** only for `--mode raster` or `--mode both` (`pip install Pillow`)
- **Google Chrome** or **Microsoft Edge** installed (standard system paths)

### High-quality PDF (default)
```bash
python scripts/html2pdf.py "C:/path/to/file.html"
```

### Screenshot/long-image output
```bash
python scripts/html2pdf.py --mode raster "C:/path/to/file.html"
```

### Multiple files
```bash
python scripts/html2pdf.py "file1.html" "file2.html"
```

### Crop height to a specific content element
Use this when the body/viewport contains extra background below the actual document, such as a centered resume card.

```bash
python scripts/html2pdf.py --selector ".resume" "resume.html"
```

The script sets the final layout width first, then measures the selected element's bottom edge. This avoids the failure mode where text wraps differently at export width and leaves a large blank area at the bottom.

### Interactive (file picker dialog)
```bash
python scripts/html2pdf.py
```

## How it works internally

1. Starts a **local HTTP server** (random free port) — this lets Chrome load the HTML with correct relative paths for CSS/JS/images
2. Launches **Chrome headless** with remote debugging enabled
3. Connects via **Chrome DevTools Protocol (CDP)** over WebSocket
4. Navigates to the percent-encoded local URL, so Chinese characters and spaces in filenames work
5. Sets the final layout width before measuring content height
6. Measures the selected content element (`body` by default, or `--selector`) and uses that exact bottom edge for page height
7. In `vector` mode, calls Chrome `Page.printToPDF` with custom page size and zero margins
8. In `raster` mode, captures a full-page PNG and wraps it into a PDF using Pillow

The CDP WebSocket client is implemented from scratch using only stdlib.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Chrome not found | Update `CHROME_PATHS` list at the top of `scripts/html2pdf.py` |
| `ModuleNotFoundError: PIL` | Run `pip install Pillow`, or use default `vector` mode |
| Page renders incorrectly | The HTML may rely on external fonts/resources; ensure network access |
| PDF text is blurry/noisy | Use default `vector` mode, not `--mode raster` |
| Large blank area at bottom | Re-run with a document wrapper selector, e.g. `--selector ".resume"`, and keep the same `--width` used for export |
| Content is cut off | Use a broader selector such as `body`, or add `--padding-bottom 20` |
| Very tall pages (>15,000px) | Chrome has memory limits; split the content or reduce page width |

## When NOT to use this skill

- The user wants to convert a **live URL** (not a local HTML file) → use browser print or a different approach
- The user wants a **multi-page PDF** with proper pagination → use browser print-to-PDF
- The user wants to **edit** PDF content after export → use a document/PDF editing workflow instead
