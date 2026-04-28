"""Guards against Chinese (CJK) text re-entering the source tree.

The MiroFish LLM previously reasoned in Chinese because Chinese strings
appeared in prompts, system messages, and tool descriptions sent to the
model. We translated everything to English; this test makes sure CJK
characters do not regress.

Allowlist: a small set of files / lines is permitted to retain CJK on
purpose (e.g. legacy gender normalization keys, CN-language-aware regex
filters in zep_tools, locale routing). See ALLOWED_CJK below.
"""

import re
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]  # MiroFish/

# Match CJK Unified Ideographs only (NOT punctuation U+3000–U+303F or full-width
# punctuation U+FF00–U+FFEF — those are runtime data, e.g. sentence-boundary
# splitters in file_parser.py).
CJK_RE = re.compile(r"[一-鿿]")

# Files allowed to contain CJK chars. Use posix-relative paths from MiroFish/.
# Keep this list TIGHT — every entry needs a justification comment.
ALLOWED_CJK_FILES = {
    # Locale source-of-truth: Chinese translations live here on purpose.
    "locales/zh.json",
    "locales/languages.json",
    # README in Chinese is intentional.
    "README-ZH.md",
    # locale.py routes between en/zh translations; comments may reference CJK.
    "backend/app/utils/locale.py",
    # Runtime data, not prompts:
    # - oasis_profile_generator: gender-normalization dict keys ("男"/"女"/...) for
    #   legacy LLM output coming back in Chinese.
    # - zep_tools: regex filters that strip Chinese question prefixes ("问题1") from
    #   agent output.
    "backend/app/services/oasis_profile_generator.py",
    "backend/app/services/zep_tools.py",
}

# Scan only source dirs, not vendored / build artifacts.
SCAN_DIRS = ["backend/app", "backend/scripts", "frontend/src"]
SCAN_EXTS = {".py", ".vue", ".js", ".ts", ".tsx", ".jsx", ".md", ".json", ".toml"}

def iter_source_files():
    for d in SCAN_DIRS:
        base = ROOT / d
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in SCAN_EXTS:
                continue
            rel = path.relative_to(ROOT).as_posix()
            if rel in ALLOWED_CJK_FILES:
                continue
            yield path, rel

def test_no_cjk_in_source():
    offenders: list[tuple[str, int, str]] = []
    for path, rel in iter_source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if CJK_RE.search(line):
                offenders.append((rel, lineno, line.strip()[:120]))
    if offenders:
        msg = "Chinese (CJK) characters found in source files. Translate to English or add to ALLOWED_CJK_FILES with justification:\n"
        for rel, lineno, snippet in offenders[:30]:
            msg += f"  {rel}:{lineno}: {snippet}\n"
        if len(offenders) > 30:
            msg += f"  ... and {len(offenders) - 30} more\n"
        raise AssertionError(msg)

def test_locale_files_kept_in_chinese():
    """Negative test — make sure we did NOT accidentally strip CJK from locale files."""
    zh = (ROOT / "locales/zh.json").read_text(encoding="utf-8")
    assert CJK_RE.search(zh), "locales/zh.json should contain Chinese translations"
