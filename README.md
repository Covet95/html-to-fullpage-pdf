# html-to-fullpage-pdf

Convert local HTML files to high-quality PDF and optional full-page screenshots without A4 reflow.

## Output

For each input file, outputs are saved in the same directory as the HTML.

| Mode | Files | Notes |
|------|-------|-------|
| `vector` (default) | `<stem>-vector.pdf` | Sharp/selectable text via Chrome `Page.printToPDF` |
| `raster` | `<stem>-fullpage.png`, `<stem>-fullpage.pdf` | Screenshot-based output for long images or image PDFs |
| `both` | all of the above | Generates both variants |

## Requirements

- Python 3.x
- Google Chrome or Microsoft Edge installed at a standard path
- Pillow only for `--mode raster` or `--mode both`

## Usage

```bash
# High-quality vector PDF
python scripts/html2pdf.py "C:/path/to/file.html"

# Screenshot PNG plus PNG-wrapped PDF
python scripts/html2pdf.py --mode raster "C:/path/to/file.html"

# Avoid bottom blank area by measuring a document wrapper
python scripts/html2pdf.py --selector ".resume" "resume.html"

# Multiple files
python scripts/html2pdf.py file1.html file2.html
```

## Notes

- The script serves the HTML over localhost so relative images/CSS load correctly.
- Filenames are percent-encoded, so Chinese names and spaces work.
- It sets the final layout width before measuring content height. This prevents extra bottom whitespace caused by measuring at one width and exporting at another.
- Use `--mode raster` only when the user wants a screenshot/long image or an image-based PDF; text-heavy PDFs should stay in default vector mode.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Chrome not found | Update `CHROME_PATHS` in `scripts/html2pdf.py` |
| PDF text is blurry/noisy | Use default `vector` mode instead of `--mode raster` |
| Large blank area at bottom | Use `--selector` for the document wrapper, e.g. `.resume` |
| Content is cut off | Use `body` or add `--padding-bottom 20` |
| Raster mode cannot import PIL | `pip install Pillow` |
