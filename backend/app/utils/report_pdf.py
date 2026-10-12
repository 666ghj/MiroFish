"""Render a markdown report to PDF (PyMuPDF Story + python-markdown)."""

import io

import fitz
import markdown

_CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.5; color: #111; }
h1 { font-size: 20pt; margin: 0 0 10pt 0; }
h2 { font-size: 14pt; margin: 16pt 0 6pt 0; border-bottom: 1px solid #ccc; }
h3 { font-size: 12pt; margin: 12pt 0 4pt 0; }
blockquote { margin: 8pt 0; padding-left: 10pt; border-left: 3px solid #999; color: #444; }
code { font-family: monospace; font-size: 9.5pt; background-color: #f2f2f2; }
pre { font-family: monospace; font-size: 9pt; background-color: #f2f2f2; padding: 6pt; }
table { border-collapse: collapse; }
th, td { border: 1px solid #bbb; padding: 3pt 5pt; }
hr { border: 0; border-top: 1px solid #ccc; }
"""


def markdown_to_pdf_bytes(md_text: str) -> bytes:
    html = markdown.markdown(
        md_text, extensions=["extra", "sane_lists", "tables", "fenced_code"]
    )
    story = fitz.Story(html=html, user_css=_CSS)

    buffer = io.BytesIO()
    writer = fitz.DocumentWriter(buffer)
    page_rect = fitz.paper_rect("a4")
    content_rect = page_rect + (54, 54, -54, -54)

    more = True
    while more:
        device = writer.begin_page(page_rect)
        more, _ = story.place(content_rect)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buffer.getvalue()
