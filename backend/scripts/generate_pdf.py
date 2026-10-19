import json
import os
import sys
import shutil
import subprocess
import html

report_id = sys.argv[1] if len(sys.argv) > 1 else "report_ebf48751e789"
report_dir = f"backend/uploads/reports/{report_id}"
meta_path = os.path.join(report_dir, "meta.json")
md_path = os.path.join(report_dir, "full_report.md")

with open(meta_path, "r", encoding="utf-8") as f:
    meta = json.load(f)

raw_md = ""
if os.path.exists(md_path):
    with open(md_path, "r", encoding="utf-8") as f:
        raw_md = f.read()

title = meta.get("outline", {}).get("title", "MiroFish 仿真分析报告")
summary = meta.get("outline", {}).get("summary", "")
sections = meta.get("outline", {}).get("sections", [])
sim_id = meta.get("simulation_id", "")
report_id = meta.get("report_id", report_id)
created_at = meta.get("completed_at", "2026-10-19")[:10]
requirement = meta.get("simulation_requirement", "")

def format_text(text):
    text = html.escape(text)
    import re
    # Bold
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    # Quotes
    return text

sections_html = []
for i, sec in enumerate(sections, 1):
    sec_title = html.escape(sec.get("title", f"Section {i}"))
    sec_content = sec.get("content", "")
    
    # Process paragraphs and blockquotes
    paragraphs = sec_content.split("\n\n")
    p_html = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        if p.startswith(">"):
            # Blockquote
            quote_text = p.lstrip("> ").strip()
            if quote_text.startswith('"') and quote_text.endswith('"'):
                quote_text = quote_text[1:-1]
            p_html.append(f'''
            <div class="quote-card">
                <div class="quote-icon">“</div>
                <div class="quote-body">{format_text(quote_text)}</div>
            </div>
            ''')
        else:
            p_html.append(f'<p>{format_text(p)}</p>')
    
    sections_html.append(f'''
    <section class="report-section">
        <div class="section-badge">SECTION 0{i}</div>
        <h2 class="section-title">{sec_title}</h2>
        <div class="section-body">
            {''.join(p_html)}
        </div>
    </section>
    ''')

html_content = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>{html.escape(title)}</title>
<style>
    @page {{
        size: A4;
        margin: 18mm 16mm 20mm 16mm;
        @bottom-right {{
            content: counter(page);
            font-size: 9pt;
            color: #888;
        }}
    }}
    * {{
        box-sizing: border-box;
        margin: 0;
        padding: 0;
    }}
    body {{
        font-family: -apple-system, BlinkMacSystemFont, "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans SC", sans-serif;
        color: #1a1a1a;
        line-height: 1.8;
        font-size: 10.5pt;
        background: #ffffff;
        padding: 0;
    }}
    .header-bar {{
        display: flex;
        justify-content: space-between;
        align-items: center;
        border-bottom: 2px solid #0f172a;
        padding-bottom: 12px;
        margin-bottom: 28px;
    }}
    .brand {{
        font-family: -apple-system, monospace;
        font-weight: 900;
        font-size: 13pt;
        letter-spacing: 2px;
        color: #0f172a;
    }}
    .doc-type {{
        font-size: 8.5pt;
        font-weight: 600;
        color: #64748b;
        letter-spacing: 1px;
        text-transform: uppercase;
    }}
    .report-title {{
        font-size: 20pt;
        font-weight: 800;
        color: #0f172a;
        line-height: 1.35;
        margin-bottom: 16px;
        letter-spacing: -0.3px;
    }}
    .meta-grid {{
        display: grid;
        grid-template-columns: repeat(4, 1fr);
        gap: 12px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 14px 16px;
        margin-bottom: 24px;
    }}
    .meta-item {{
        display: flex;
        flex-direction: column;
    }}
    .meta-label {{
        font-size: 7.5pt;
        text-transform: uppercase;
        color: #64748b;
        font-weight: 700;
        letter-spacing: 0.5px;
        margin-bottom: 3px;
    }}
    .meta-value {{
        font-size: 9.5pt;
        font-weight: 600;
        color: #0f172a;
        word-break: break-all;
    }}
    .summary-card {{
        background: #f1f5f9;
        border-left: 4px solid #0f172a;
        border-radius: 0 8px 8px 0;
        padding: 16px 20px;
        margin-bottom: 32px;
    }}
    .summary-title {{
        font-size: 9.5pt;
        font-weight: 800;
        color: #0f172a;
        text-transform: uppercase;
        letter-spacing: 0.8px;
        margin-bottom: 6px;
    }}
    .summary-text {{
        font-size: 10.5pt;
        color: #334155;
        line-height: 1.7;
    }}
    .report-section {{
        margin-bottom: 32px;
        page-break-inside: avoid;
    }}
    .section-badge {{
        display: inline-block;
        font-size: 7.5pt;
        font-weight: 800;
        color: #475569;
        background: #e2e8f0;
        padding: 2px 8px;
        border-radius: 4px;
        letter-spacing: 0.8px;
        margin-bottom: 6px;
    }}
    .section-title {{
        font-size: 13.5pt;
        font-weight: 800;
        color: #0f172a;
        margin-bottom: 14px;
        padding-bottom: 6px;
        border-bottom: 1px solid #e2e8f0;
    }}
    .section-body p {{
        margin-bottom: 12px;
        text-align: justify;
        color: #1e293b;
    }}
    .quote-card {{
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-left: 3.5px solid #2563eb;
        border-radius: 4px;
        padding: 12px 16px;
        margin: 14px 0;
        display: flex;
        gap: 10px;
    }}
    .quote-icon {{
        font-size: 20pt;
        line-height: 1;
        color: #2563eb;
        font-family: Georgia, serif;
    }}
    .quote-body {{
        font-size: 9.8pt;
        color: #334155;
        font-style: normal;
        line-height: 1.6;
    }}
    .footer {{
        margin-top: 40px;
        border-top: 1px solid #e2e8f0;
        padding-top: 12px;
        display: flex;
        justify-content: space-between;
        font-size: 8pt;
        color: #94a3b8;
    }}
</style>
</head>
<body>

<div class="header-bar">
    <div class="brand">MIROFISH / INTELLIGENCE</div>
    <div class="doc-type">PREDICTIVE SIMULATION REPORT</div>
</div>

<h1 class="report-title">{html.escape(title)}</h1>

<div class="meta-grid">
    <div class="meta-item">
        <span class="meta-label">REPORT ID</span>
        <span class="meta-value">{html.escape(report_id)}</span>
    </div>
    <div class="meta-item">
        <span class="meta-label">SIMULATION ID</span>
        <span class="meta-value">{html.escape(sim_id)}</span>
    </div>
    <div class="meta-item">
        <span class="meta-label">DATE</span>
        <span class="meta-value">{html.escape(created_at)}</span>
    </div>
    <div class="meta-item">
        <span class="meta-label">STATUS</span>
        <span class="meta-value">COMPLETED</span>
    </div>
</div>

<div class="summary-card">
    <div class="summary-title">Executive Summary</div>
    <div class="summary-text">{html.escape(summary)}</div>
</div>

{''.join(sections_html)}

<div class="footer">
    <span>Generated by MiroFish Swarm Intelligence Platform</span>
    <span>Powered by Gemini 3.5 & Zep GraphRAG</span>
</div>

</body>
</html>'''

html_path = f"backend/uploads/reports/{report_id}/report.html"
pdf_path_in_report = f"backend/uploads/reports/{report_id}/{report_id}.pdf"
pdf_path_root = f"{report_id}.pdf"

with open(html_path, "w", encoding="utf-8") as f:
    f.write(html_content)

print(f"HTML generated at {html_path}")

def get_chrome_executable():
    env_bin = os.environ.get("CHROME_BIN")
    if env_bin and os.path.exists(env_bin):
        return env_bin
    
    candidates = [
        shutil.which("google-chrome"),
        shutil.which("google-chrome-stable"),
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
    ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            return cand
    return None

chrome_bin = get_chrome_executable()
if not chrome_bin:
    print("Warning: Google Chrome / Chromium executable not found. HTML was saved, but PDF export requires Chrome/Chromium.")
    sys.exit(0)

cmd = [
    chrome_bin,
    "--headless=new",
    "--disable-gpu",
    f"--print-to-pdf={pdf_path_in_report}",
    "--no-pdf-header-footer",
    f"file://{os.path.abspath(html_path)}"
]
subprocess.run(cmd, check=True)

print(f"PDF generated successfully at:")
print(f"  - {os.path.abspath(pdf_path_in_report)}")

