# Report PDF/MD Download Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Afegir descàrrega del report generat en format MD i PDF des del frontend, amb un botó desplegable que apareix quan el report s'ha completat.

**Architecture:** S'estén l'endpoint de descàrrega existent `GET /api/report/<id>/download` amb el paràmetre `?format=md|pdf`. El backend converteix `full_report.md` → HTML (via `markdown`) → PDF (via `PyMuPDF` / `fitz.Story`). El frontend afegeix un botó desplegable a `Step4Report.vue` amb opcions MD i PDF que obren una URL de descàrrega directa.

**Tech Stack:** Python `markdown>=3.6` (nova dep), `PyMuPDF>=1.24.0` (ja instal·lat), Vue 3 SPA.

---

## Arxius afectats

| Arxiu | Canvi |
|---|---|
| `backend/pyproject.toml` | +`"markdown>=3.6"` a dependencies |
| `backend/app/api/report.py` | Ampliar `download_report()` amb `?format` + generar PDF |
| `frontend/src/api/report.js` | +`getReportDownloadUrl(reportId, format)` |
| `frontend/src/components/Step4Report.vue` | +botó desplegable MD/PDF quan `isComplete` |

---

## Task 1: Afegir dependència `markdown` al backend

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Afegir la dependència**

A `backend/pyproject.toml`, afegir `"markdown>=3.6"` a la llista `dependencies`, just després de `"PyMuPDF>=1.24.0"`:

```toml
    # 文件处理
    "PyMuPDF>=1.24.0",
    "markdown>=3.6",
```

- [ ] **Step 2: Instal·lar la dependència**

```bash
cd backend && uv sync
```

Resultat esperat: `markdown` s'instal·la sense errors.

- [ ] **Step 3: Verificar que s'importa correctament**

```bash
cd backend && uv run python -c "import markdown; print(markdown.__version__)"
```

Resultat esperat: imprimeix una versió ≥ 3.6 (p.ex. `3.7`).

- [ ] **Step 4: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore(deps): add markdown>=3.6 for PDF generation"
```

---

## Task 2: Escriure el test de l'endpoint de descàrrega PDF

**Files:**
- Test: `backend/tests/test_report_download.py`

- [ ] **Step 1: Escriure el test**

Crear el fitxer `backend/tests/test_report_download.py`:

```python
"""Tests for report download endpoint (MD and PDF formats)."""
import io
import os
import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from app import create_app


@pytest.fixture
def app():
    app = create_app({'TESTING': True})
    yield app


@pytest.fixture
def client(app):
    return app.test_client()


def _make_mock_report(report_id="report_test123", content="# Test Report\n\nHello **world**."):
    mock = MagicMock()
    mock.report_id = report_id
    mock.markdown_content = content
    return mock


def _make_md_file(tmp_path, report_id, content):
    md_path = os.path.join(tmp_path, f"{report_id}_full_report.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(content)
    return md_path


class TestDownloadMD:
    def test_download_md_format_param(self, client, tmp_path):
        """?format=md returns a .md file."""
        mock_report = _make_mock_report()
        md_path = _make_md_file(tmp_path, mock_report.report_id, mock_report.markdown_content)

        with patch('app.api.report.ReportManager.get_report', return_value=mock_report), \
             patch('app.api.report.ReportManager._get_report_markdown_path', return_value=md_path):
            resp = client.get(f'/api/report/{mock_report.report_id}/download?format=md')

        assert resp.status_code == 200
        assert 'attachment' in resp.headers.get('Content-Disposition', '')
        assert '.md' in resp.headers.get('Content-Disposition', '')

    def test_download_default_is_md(self, client, tmp_path):
        """No format param defaults to md."""
        mock_report = _make_mock_report()
        md_path = _make_md_file(tmp_path, mock_report.report_id, mock_report.markdown_content)

        with patch('app.api.report.ReportManager.get_report', return_value=mock_report), \
             patch('app.api.report.ReportManager._get_report_markdown_path', return_value=md_path):
            resp = client.get(f'/api/report/{mock_report.report_id}/download')

        assert resp.status_code == 200
        assert '.md' in resp.headers.get('Content-Disposition', '')


class TestDownloadPDF:
    def test_download_pdf_returns_pdf_bytes(self, client, tmp_path):
        """?format=pdf returns a valid PDF file."""
        mock_report = _make_mock_report()
        md_path = _make_md_file(tmp_path, mock_report.report_id, mock_report.markdown_content)

        with patch('app.api.report.ReportManager.get_report', return_value=mock_report), \
             patch('app.api.report.ReportManager._get_report_markdown_path', return_value=md_path):
            resp = client.get(f'/api/report/{mock_report.report_id}/download?format=pdf')

        assert resp.status_code == 200
        assert resp.headers.get('Content-Type', '').startswith('application/pdf')
        assert resp.data[:4] == b'%PDF'

    def test_download_pdf_report_not_found(self, client):
        """Returns 404 when report does not exist."""
        with patch('app.api.report.ReportManager.get_report', return_value=None):
            resp = client.get('/api/report/nonexistent/download?format=pdf')

        assert resp.status_code == 404

    def test_download_pdf_invalid_format(self, client, tmp_path):
        """Returns 400 for unknown format parameter."""
        mock_report = _make_mock_report()
        md_path = _make_md_file(tmp_path, mock_report.report_id, mock_report.markdown_content)

        with patch('app.api.report.ReportManager.get_report', return_value=mock_report), \
             patch('app.api.report.ReportManager._get_report_markdown_path', return_value=md_path):
            resp = client.get(f'/api/report/{mock_report.report_id}/download?format=docx')

        assert resp.status_code == 400
```

- [ ] **Step 2: Executar els tests per verificar que fallen**

```bash
cd backend && uv run pytest tests/test_report_download.py -v 2>&1 | head -40
```

Resultat esperat: FAILED (la nova funcionalitat PDF encara no existeix).

---

## Task 3: Implementar la generació de PDF al backend

**Files:**
- Modify: `backend/app/api/report.py` (funció `download_report`, línies 398–441)

- [ ] **Step 1: Afegir imports al capdamunt de `report.py`**

Localitza el bloc d'imports a `backend/app/api/report.py` (línies 1–19) i afegeix:

```python
import io
import tempfile
import markdown as md_lib
import fitz  # PyMuPDF
```

Si `import io` ja existeix, no el dupliquis. Afegeix els que faltin just després de `import traceback`.

- [ ] **Step 2: Afegir la funció helper `_generate_pdf_bytes`**

Afegeix aquesta funció just **abans** de `@report_bp.route('/<report_id>/download', ...)` (línia 398):

```python
def _generate_pdf_bytes(markdown_content: str) -> bytes:
    """Convert Markdown string to PDF bytes using PyMuPDF (fitz.Story)."""
    html_body = md_lib.markdown(
        markdown_content,
        extensions=['tables', 'fenced_code']
    )
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: sans-serif; font-size: 12pt; line-height: 1.6;
         margin: 40px; color: #1a1a1a; }}
  h1 {{ font-size: 22pt; border-bottom: 2px solid #333; padding-bottom: 6px; }}
  h2 {{ font-size: 16pt; margin-top: 28px; }}
  h3 {{ font-size: 13pt; }}
  pre {{ background: #f4f4f4; padding: 10px; border-radius: 4px;
         font-size: 10pt; overflow-x: auto; }}
  code {{ background: #f4f4f4; padding: 1px 4px; border-radius: 3px; font-size: 10pt; }}
  blockquote {{ border-left: 3px solid #aaa; margin-left: 0;
                padding-left: 12px; color: #555; }}
  table {{ border-collapse: collapse; width: 100%; margin: 12px 0; }}
  th, td {{ border: 1px solid #ccc; padding: 6px 10px; text-align: left; }}
  th {{ background: #f0f0f0; }}
</style>
</head>
<body>{html_body}</body>
</html>"""

    story = fitz.Story(html)
    buf = io.BytesIO()
    writer = fitz.DocumentWriter(buf)
    mediabox = fitz.paper_rect("a4")
    where = mediabox + (36, 36, -36, -36)  # margins
    more = True
    while more:
        device = writer.begin_page(mediabox)
        more, _ = story.place(where)
        story.draw(device)
        writer.end_page()
    writer.close()
    return buf.getvalue()
```

- [ ] **Step 3: Substituir la funció `download_report` completa**

Substitueix tot el contingut de `download_report` (línies 398–441) per:

```python
@report_bp.route('/<report_id>/download', methods=['GET'])
def download_report(report_id: str):
    """
    Download report in the requested format.

    Query params:
        format: 'md' (default) | 'pdf'
    """
    try:
        fmt = request.args.get('format', 'md').lower()
        if fmt not in ('md', 'pdf'):
            return jsonify({
                "success": False,
                "error": f"Unsupported format '{fmt}'. Use 'md' or 'pdf'."
            }), 400

        report = ReportManager.get_report(report_id)
        if not report:
            return jsonify({
                "success": False,
                "error": t('api.reportNotFound', id=report_id)
            }), 404

        md_path = ReportManager._get_report_markdown_path(report_id)
        if os.path.exists(md_path):
            with open(md_path, 'r', encoding='utf-8') as f:
                markdown_content = f.read()
        else:
            markdown_content = report.markdown_content

        if fmt == 'md':
            if os.path.exists(md_path):
                return send_file(
                    md_path,
                    as_attachment=True,
                    download_name=f"{report_id}.md"
                )
            with tempfile.NamedTemporaryFile(mode='w', suffix='.md',
                                             delete=False, encoding='utf-8') as f:
                f.write(markdown_content)
                temp_path = f.name
            return send_file(temp_path, as_attachment=True,
                             download_name=f"{report_id}.md")

        # fmt == 'pdf'
        pdf_bytes = _generate_pdf_bytes(markdown_content)
        return send_file(
            io.BytesIO(pdf_bytes),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"{report_id}.pdf"
        )

    except Exception as e:
        logger.error(f"Failed to download report: {str(e)}")
        return jsonify({
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc()
        }), 500
```

- [ ] **Step 4: Executar els tests**

```bash
cd backend && uv run pytest tests/test_report_download.py -v
```

Resultat esperat: tots els tests en PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/report.py backend/tests/test_report_download.py
git commit -m "feat(report): add PDF download endpoint via PyMuPDF"
```

---

## Task 4: Afegir helper al frontend API

**Files:**
- Modify: `frontend/src/api/report.js`

- [ ] **Step 1: Afegir `getReportDownloadUrl` al final de `report.js`**

Afegeix al final de `frontend/src/api/report.js`:

```javascript
/**
 * Build the direct download URL for a report.
 * @param {string} reportId
 * @param {'md'|'pdf'} format
 * @returns {string} URL absoluta per fer servir com a href de descàrrega
 */
export const getReportDownloadUrl = (reportId, format = 'md') => {
  const base = import.meta.env.VITE_API_BASE_URL || ''
  return `${base}/api/report/${reportId}/download?format=${format}`
}
```

- [ ] **Step 2: Verificar que el frontend compila sense errors**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Resultat esperat: build sense errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/report.js
git commit -m "feat(report): add getReportDownloadUrl helper"
```

---

## Task 5: Afegir botó desplegable MD/PDF al component Vue

**Files:**
- Modify: `frontend/src/components/Step4Report.vue`

Els canvis s'estructuren en 3 sub-passos: (a) importar la funció, (b) afegir el template, (c) afegir els estils.

- [ ] **Step 1: Afegir l'import de `getReportDownloadUrl`**

A `Step4Report.vue`, localitza la línia d'imports de `report.js`. Busca quelcom com:

```javascript
import { getReport, ... } from '../api/report'
```

Afegeix `getReportDownloadUrl` a la llista d'imports d'aquell fitxer. Si no hi ha imports de `report.js`, afegeix:

```javascript
import { getReportDownloadUrl } from '../api/report'
```

- [ ] **Step 2: Afegir l'estat reactiu del menú**

Localitza la línia `const isComplete = ref(false)` (línia ~427) i afegeix just a sota:

```javascript
const showDownloadMenu = ref(false)
```

- [ ] **Step 3: Afegir la funció de tancament del menú al clicar fora**

Localitza la funció `goToInteraction` (línia ~410) i afegeix just a sobre:

```javascript
const closeDownloadMenu = () => { showDownloadMenu.value = false }
```

- [ ] **Step 4: Afegir el botó desplegable al template**

Localitza el bloc del botó "next step" al template (línia ~130):

```html
          <!-- Next Step Button - 在完成后显示 -->
          <button v-if="isComplete" class="next-step-btn" @click="goToInteraction">
```

Afegeix el botó desplegable de descàrrega **just abans** d'aquest bloc:

```html
          <!-- Download Button - apareix quan el report és complet -->
          <div v-if="isComplete" class="download-wrapper" v-click-outside="closeDownloadMenu">
            <button class="download-toggle-btn" @click="showDownloadMenu = !showDownloadMenu">
              <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path>
                <polyline points="7 10 12 15 17 10"></polyline>
                <line x1="12" y1="15" x2="12" y2="3"></line>
              </svg>
              <span>{{ $t('step4.downloadReport') }}</span>
              <svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" class="chevron-icon" :class="{ open: showDownloadMenu }">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </button>
            <div v-if="showDownloadMenu" class="download-menu">
              <a :href="getReportDownloadUrl(reportId, 'md')" download class="download-option" @click="showDownloadMenu = false">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                </svg>
                <span>Markdown (.md)</span>
              </a>
              <a :href="getReportDownloadUrl(reportId, 'pdf')" download class="download-option" @click="showDownloadMenu = false">
                <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>
                  <polyline points="14 2 14 8 20 8"></polyline>
                  <line x1="16" y1="13" x2="8" y2="13"></line>
                  <line x1="16" y1="17" x2="8" y2="17"></line>
                  <polyline points="10 9 9 9 8 9"></polyline>
                </svg>
                <span>PDF (.pdf)</span>
              </a>
            </div>
          </div>
```

**Nota:** Vue 3 no té `v-click-outside` built-in. Si el projecte no té aquesta directiva, substitueix `v-click-outside="closeDownloadMenu"` per res i afegeix al `<script setup>` un event listener:

```javascript
// Tanca el menú si es clica fora
import { onMounted, onUnmounted } from 'vue'
const handleClickOutside = (e) => {
  if (!e.target.closest('.download-wrapper')) showDownloadMenu.value = false
}
onMounted(() => document.addEventListener('click', handleClickOutside))
onUnmounted(() => document.removeEventListener('click', handleClickOutside))
```

- [ ] **Step 5: Afegir les claus i18n**

A `locales/en.json`, dins l'objecte `step4`, afegeix:

```json
"downloadReport": "Download Report"
```

A `locales/zh.json`, dins l'objecte `step4`, afegeix:

```json
"downloadReport": "下载报告"
```

- [ ] **Step 6: Afegir estils CSS**

Al final del bloc `<style>` de `Step4Report.vue` (just abans del tancament `</style>`), afegeix:

```css
/* Download dropdown */
.download-wrapper {
  position: relative;
  margin: 8px 20px 0 20px;
}

.download-toggle-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  padding: 11px 20px;
  font-size: 13px;
  font-weight: 500;
  color: #D1D5DB;
  background: #111827;
  border: 1px solid #374151;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.download-toggle-btn:hover {
  background: #1F2937;
  color: #F9FAFB;
}

.chevron-icon {
  transition: transform 0.2s ease;
  margin-left: auto;
}

.chevron-icon.open {
  transform: rotate(180deg);
}

.download-menu {
  position: absolute;
  bottom: calc(100% + 4px);
  left: 0;
  right: 0;
  background: #1F2937;
  border: 1px solid #374151;
  border-radius: 8px;
  overflow: hidden;
  z-index: 100;
  box-shadow: 0 -4px 12px rgba(0,0,0,0.3);
}

.download-option {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 16px;
  font-size: 13px;
  color: #D1D5DB;
  text-decoration: none;
  transition: background 0.15s ease;
}

.download-option:hover {
  background: #374151;
  color: #F9FAFB;
}
```

- [ ] **Step 7: Verificar que el frontend compila**

```bash
cd frontend && npm run build 2>&1 | tail -20
```

Resultat esperat: build sense errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Step4Report.vue locales/en.json locales/zh.json
git commit -m "feat(report): add MD/PDF download dropdown button"
```

---

## Verificació end-to-end

1. Inicia el servidor: `npm run dev` (des de l'arrel del projecte)
2. Genera un report complet en qualsevol projecte existent
3. Quan el report es completa, ha d'aparèixer el botó "Download Report" sobre el botó "Go to Interaction"
4. Fes clic al botó: ha d'aparèixer un menú desplegable amb les opcions "Markdown (.md)" i "PDF (.pdf)"
5. Fes clic a "Markdown (.md)": ha de descarregar-se un fitxer `.md` llegible
6. Fes clic a "PDF (.pdf)": ha de descarregar-se un fitxer `.pdf` que s'obre correctament
7. Tanca el menú clicant fora: ha de tancar-se el desplegable
8. Executa els tests del backend: `cd backend && uv run pytest tests/test_report_download.py -v`
