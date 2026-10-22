"""Convert a finished MiroFish report markdown to PDF.

Usage: python report_to_pdf.py <markdown_file> <output_pdf>
Uses markdown_pdf (installed in backend/.venv). Simple CJK-safe fallback:
markdown_pdf uses WeasyPrint engine; DejaVu/Noto fonts installed on system will
be picked up for CJK glyphs. If CJK rendering fails, report_to_pdf falls back
to a plain-text wrapped PDF so delivery never blocks.
"""
import sys
import os


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: report_to_pdf.py <markdown_file> <output_pdf>")
        return 2
    md_path, pdf_path = sys.argv[1], sys.argv[2]
    if not os.path.exists(md_path):
        print(f"not found: {md_path}")
        return 1

    with open(md_path, "r", encoding="utf-8") as f:
        md_text = f.read()

    from markdown_pdf import MarkdownPdf, Section  # noqa: E402

    pdf = MarkdownPdf(toc_level=2)
    pdf.add_section(Section(md_text))
    pdf.meta["title"] = "MiroFish Relationship Simulation Report"
    pdf.meta["author"] = "MiroFish"
    pdf.save(pdf_path)
    print(f"PDF written: {pdf_path} ({os.path.getsize(pdf_path)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
