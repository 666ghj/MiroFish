"""Local Markdown-to-PDF export; independent from report generation and AI."""
from html import escape
import json
from pathlib import Path
import subprocess
import sys
import tempfile


CSS = '''
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.45; color: #24313d; }
h1 { font-size: 24pt; line-height: 1.15; color: #152b38; margin: 0 0 18pt; }
h2 { font-size: 16pt; color: #152b38; margin: 20pt 0 9pt; page-break-after: avoid; }
h3, h4, h5, h6 { font-size: 12pt; margin: 14pt 0 7pt; page-break-after: avoid; }
p { margin: 0 0 10pt; }
a { color: #17677a; }
blockquote { margin: 12pt 0; padding: 10pt 14pt; border-left: 3pt solid #17677a; }
blockquote p { margin: 0 0 5pt; }
ul, ol { padding-left: 20pt; margin: 8pt 0 12pt; }
li { margin-bottom: 5pt; }
table { border-collapse: collapse; width: 100%; font-size: 9pt; margin: 12pt 0; }
th, td { border: 0.5pt solid #ced8dd; padding: 7pt; vertical-align: top; }
th { background-color: #edf4f5; font-weight: bold; }
pre { white-space: pre-wrap; font-size: 9pt; padding: 10pt; background-color: #f2f4f5; }
code { font-family: monospace; font-size: 9pt; }
hr { border: 0; border-top: 0.5pt solid #ced8dd; margin: 15pt 0; }
'''


def _render(markdown, title):
    import pymupdf
    from markdown_it import MarkdownIt
    from markdown_it.token import Token

    parser = MarkdownIt('commonmark', {'html': False}).enable('table')
    # Reports are text evidence. Never fetch remote images or read local files
    # named in generated Markdown; preserve their descriptions as text.
    parser.renderer.rules['image'] = lambda tokens, index, *_: '<span>[Image: ' + escape(tokens[index].content) + ']</span>'
    tokens = parser.parse(markdown)
    counters = []
    for index, token in enumerate(tokens):
        if token.type in {'ordered_list_open', 'bullet_list_open'}:
            counters.append(int(token.attrGet('start') or 1) if token.type == 'ordered_list_open' else None)
            if counters[-1] is not None:
                token.attrSet('style', 'list-style-type: none')
        elif token.type in {'ordered_list_close', 'bullet_list_close'}:
            counters.pop()
        elif token.type == 'list_item_open' and counters and counters[-1] is not None:
            # MuPDF ignores <ol start>. Put the original marker into the text so
            # quotations between numbered recommendations cannot reset every item.
            for following in tokens[index + 1:]:
                if following.type in {'list_item_open', 'list_item_close'}:
                    break
                if following.type == 'inline':
                    marker = Token('text', '', 0)
                    marker.content = f'{counters[-1]}. '
                    following.children.insert(0, marker)
                    break
            counters[-1] += 1
    html = parser.renderer.render(tokens, parser.options, {})
    story = pymupdf.Story(html=html, user_css=CSS)
    paper = pymupdf.paper_rect('a4')
    content = pymupdf.Rect(46, 58, paper.width - 46, paper.height - 52)

    def rectangle(number, filled):
        if number >= 300:
            raise ValueError('Report exceeds the PDF page limit')
        return paper, content, None

    with story.write_with_links(rectangle) as document:
        document.set_metadata({'title': title, 'author': 'My Own Researcher',
                               'creator': 'My Own Researcher'})
        for index, page in enumerate(document):
            page.insert_text((46, 31), 'MY OWN RESEARCHER', fontsize=8, color=(.22, .34, .39))
            page.draw_line((46, 39), (paper.width - 46, 39), color=(.8, .85, .87), width=.5)
            page.insert_textbox(pymupdf.Rect(46, paper.height - 33, paper.width - 46, paper.height - 18),
                                f'{index + 1} / {len(document)}', fontsize=8, align=2, color=(.35, .4, .44))
        return document.tobytes(garbage=4, deflate=True)


def render_report_pdf(markdown, title):
    # PyMuPDF must not share a threaded Flask process with other rendering work.
    # A short-lived subprocess also bounds export time and frees native resources.
    with tempfile.TemporaryDirectory(prefix='research-report-pdf-') as folder:
        output = Path(folder) / 'report.pdf'
        subprocess.run([sys.executable, str(Path(__file__).resolve()), str(output)],
                       input=json.dumps({'markdown': markdown, 'title': title}).encode(),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True, timeout=60)
        return output.read_bytes()


if __name__ == '__main__':
    data = json.load(sys.stdin)
    Path(sys.argv[1]).write_bytes(_render(data['markdown'], data['title']))
