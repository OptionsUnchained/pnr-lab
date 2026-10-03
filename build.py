from pathlib import Path
root = Path(__file__).resolve().parent
html = (root / 'index.template.html').read_text()
for placeholder, filename in [('/*STYLE*/', 'styles.css'), ('/*CORE*/', 'core.js'), ('/*APP*/', 'app.js'), ('/*OCR*/', 'ocr.js'), ('/*SCREENSHOT*/', 'screenshot.js')]:
    html = html.replace(placeholder, (root / filename).read_text())
(root / 'index.html').write_text(html)
print('Built index.html (standalone; no external dependencies)')
