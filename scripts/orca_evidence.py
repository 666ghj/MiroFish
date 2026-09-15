#!/usr/bin/env python3
"""Generate the OrcaRouter GUI evidence from the *running* MiroFish interface.

This is a verification harness, not committed evidence: it builds and serves
the real frontend together with the real backend provider blueprint, drives
the app with Playwright against ``/usr/bin/chromium``, and writes the
screenshots plus ``manifest.json`` into ``orca-evidence/``.

Everything it asserts comes from the application's own provider path:

* the model options are produced by ``GET /api/orcarouter/models``
  (``backend/app/api/orcarouter.py``) reading the live
  ``https://api.orcarouter.ai/v1/models?capability=chat`` catalog, and
  rendered by ``frontend/src/components/OrcaProviderSettings.vue``;
* the two authentication choices are that same component's API-key field and
  ``Connect with OrcaRouter`` (OAuth 2.0 + PKCE) button.

No static HTML, no hand-written model list, no fabricated screenshots. The
OrcaRouter key stays server-side: the browser only ever receives the redacted
preview, which the assertions verify.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import pathlib
import socket
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.request

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND_DIR = REPO_ROOT / "backend"
FRONTEND_DIR = REPO_ROOT / "frontend"
EVIDENCE_DIR = REPO_ROOT / "orca-evidence"

CATALOG_SOURCE = "https://api.orcarouter.ai/v1/models?capability=chat"
CHROMIUM = "/usr/bin/chromium"
BLUEPRINT_MODULE = "app.api.orcarouter_evidence"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _wait_http(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            last = exc
        time.sleep(0.25)
    raise RuntimeError(f"service did not become ready: {url} ({last})")


def _sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_blueprint(module_name: str = BLUEPRINT_MODULE):
    """Load ``app/api/orcarouter.py`` without importing the heavy api package.

    ``app/api/__init__.py`` imports the graph/simulation/report blueprints,
    which need the optional OASIS/Zep stack. Registering a stub for
    ``app.api`` keeps the real provider module's relative imports working
    while skipping that ``__init__``.
    """
    backend = str(BACKEND_DIR)
    if backend not in sys.path:
        sys.path.insert(0, backend)

    stub = types.ModuleType("app.api")
    stub.__path__ = [str(BACKEND_DIR / "app" / "api")]
    sys.modules["app.api"] = stub

    spec = importlib.util.spec_from_file_location(
        module_name, BACKEND_DIR / "app" / "api" / "orcarouter.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def build_frontend() -> None:
    """Build the SPA against the same origin that serves the provider API.

    ``VITE_API_BASE_URL=/`` is the project's existing same-origin deployment
    setting (reverse-proxied installs), so the browser talks to the harness
    server, which forwards nothing - it *is* the backend.
    """
    env = dict(os.environ)
    env["VITE_API_BASE_URL"] = "/"
    completed = subprocess.run(
        ["npm", "run", "build"],
        cwd=FRONTEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=420,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "frontend build failed:\n" + (completed.stdout + completed.stderr)[-2000:]
        )


# ---------------------------------------------------------------------------
# backend: the real provider routes + the built SPA on one origin
# ---------------------------------------------------------------------------


class Backend:
    """Flask app serving the provider API and the built frontend."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.port = _free_port()
        self._thread: threading.Thread | None = None
        self.server = None

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> None:
        # The stored credential lives where the project keeps its secrets:
        # the environment it reads through ``app.config``. It is never sent
        # to the browser - the status route returns a redacted preview only.
        os.environ["ORCAROUTER_API_KEY"] = self.api_key
        os.environ["ORCAROUTER_MODEL_NAME"] = "orcarouter/auto"
        os.environ["LLM_PROVIDER"] = "orcarouter"

        blueprint = _load_blueprint()

        from flask import Flask, send_from_directory

        app = Flask(__name__, static_folder=None)
        app.register_blueprint(blueprint.orca_bp)

        dist = FRONTEND_DIR / "dist"
        if not (dist / "index.html").is_file():
            raise RuntimeError("frontend/dist/index.html is missing")

        @app.route("/")
        def index():
            return send_from_directory(dist, "index.html")

        @app.route("/assets/<path:filename>")
        def asset(filename: str):
            return send_from_directory(dist / "assets", filename)

        @app.route("/icon.png")
        def icon():
            return send_from_directory(dist, "icon.png")

        @app.route("/api/<path:_rest>", methods=["GET", "POST", "DELETE"])
        def unrelated_api(_rest: str):
            # Pages outside the provider settings are not part of this
            # evidence; answer with an empty success so the Home view stays
            # mounted instead of erroring.
            return {"success": True, "data": []}

        from werkzeug.serving import make_server

        self.server = make_server("127.0.0.1", self.port, app, threaded=True)
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        _wait_http(f"{self.base_url}/api/orcarouter/status")

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=10)

    def read_catalog(self) -> dict:
        """The live catalog read back through the implemented provider route."""
        with urllib.request.urlopen(
            f"{self.base_url}/api/orcarouter/models?capability=chat", timeout=60
        ) as response:
            return json.loads(response.read().decode("utf-8"))


# ---------------------------------------------------------------------------
# GUI assertions
# ---------------------------------------------------------------------------


def _open_home(page, base_url: str) -> None:
    """Load the Home view and open the provider settings panel."""
    page.goto(base_url + "/", wait_until="domcontentloaded", timeout=30_000)
    page.wait_for_selector("#orca-settings-trigger", timeout=30_000)
    page.click("#orca-settings-trigger")
    page.wait_for_selector("#orca-settings-panel", timeout=20_000)
    if page.query_selector("#orca-key-input") is None:
        # The provider is not OrcaRouter yet: select it, which reveals both
        # authentication choices.
        page.select_option("#orca-provider-select", "orcarouter")
        page.wait_for_selector("#orca-key-input", timeout=20_000)
    page.wait_for_selector("#orca-connect-btn", timeout=20_000)


def capture_auth_methods(page, base_url: str, raw_key: str) -> dict:
    """Both auth choices, usable, with the stored key shown masked."""
    _open_home(page, base_url)

    key_input = page.query_selector("#orca-key-input")
    save_button = page.query_selector("#orca-key-save")
    connect_button = page.query_selector("#orca-connect-btn")
    page.wait_for_selector("#orca-key-preview", timeout=20_000)
    preview = page.query_selector("#orca-key-preview")

    preview_text = (preview.inner_text() if preview else "").strip()
    html = page.content()

    result = {
        "api_key_visible": bool(key_input is not None and key_input.is_visible()),
        "pkce_visible": bool(connect_button is not None and connect_button.is_visible()),
        # Masked means: a short prefix + last four characters, and the raw key
        # nowhere in the served document.
        "secret_masked": ("..." in preview_text and raw_key not in html),
        "controls_enabled": bool(
            save_button is not None
            and connect_button is not None
            and connect_button.is_enabled()
        ),
    }
    page.screenshot(path=str(EVIDENCE_DIR / "auth-methods.png"))
    return result


def capture_text_model_dropdown(page, base_url: str) -> dict:
    """The expanded model selector, bound to the live catalog."""
    _open_home(page, base_url)
    page.wait_for_selector("#orca-model-trigger", timeout=40_000)
    page.wait_for_function(
        "() => { const t = document.querySelector('#orca-model-trigger');"
        " return t && !t.disabled; }",
        timeout=60_000,
    )

    trigger = page.query_selector("#orca-model-trigger")
    trigger_box = trigger.bounding_box()
    # The panel itself scrolls; click the trigger through its own coordinates
    # so a sticky page element cannot intercept the synthesized click.
    trigger.click(position={"x": trigger_box["width"] / 2, "y": trigger_box["height"] / 2})
    page.wait_for_selector("#orca-model-panel", timeout=20_000)
    page.wait_for_timeout(250)

    item_count = len(page.query_selector_all(".orca-model-option"))
    panel = page.query_selector("#orca-model-panel")
    panel_box = panel.bounding_box()
    styles = page.evaluate(
        """() => {
            const panel = document.querySelector('#orca-model-panel');
            const style = getComputedStyle(panel);
            return {
                background: style.backgroundColor,
                borderWidth: style.borderTopWidth,
                borderStyle: style.borderTopStyle,
                backgroundImage: style.backgroundImage,
            };
        }"""
    )
    opaque_background = styles["background"] not in ("rgba(0, 0, 0, 0)", "transparent")
    try:
        border_width = float((styles["borderWidth"] or "0").replace("px", ""))
    except ValueError:
        border_width = 0.0
    visible_border = styles["borderStyle"] != "none" and border_width > 0

    page.screenshot(path=str(EVIDENCE_DIR / "text-model-dropdown.png"))
    return {
        "dropdown_open": bool(panel.is_visible()),
        "item_count": item_count,
        "opaque_background": bool(opaque_background),
        "visible_border": bool(visible_border),
        # The panel is right-aligned to its trigger so it cannot run off the
        # right edge of the navigation bar.
        "trigger_panel_right_delta": abs(
            round(panel_box["x"] + panel_box["width"])
            - round(trigger_box["x"] + trigger_box["width"])
        ),
    }


def capture_pagehide_relogin(page, base_url: str) -> bool:
    """A second login is startable after ``pagehide`` with no remount."""
    _open_home(page, base_url)
    page.evaluate("() => window.dispatchEvent(new PageTransitionEvent('pagehide'))")
    page.wait_for_timeout(300)
    # The view is still the mounted one; starting a new attempt must work.
    page.evaluate("() => document.querySelector('#orca-connect-btn').click()")
    try:
        page.wait_for_selector("#orca-connect-cancel", timeout=15_000)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------


def main() -> int:
    api_key = os.environ.get("ORCAROUTER_API_KEY")
    if not api_key:
        raise SystemExit("ORCAROUTER_API_KEY is required for the live GUI evidence")

    EVIDENCE_DIR.mkdir(exist_ok=True)
    build_frontend()

    backend = Backend(api_key)
    try:
        backend.start()

        # 1. Live catalog through the implemented provider route with the real
        #    key, before the browser is involved at all.
        catalog = backend.read_catalog()
        if catalog.get("source") != "live":
            raise SystemExit("live discovery did not succeed: " + str(catalog.get("source")))
        catalog_model_count = len(catalog["models"])
        if catalog_model_count < 1:
            raise SystemExit("live chat catalog returned no models")

        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=CHROMIUM,
                args=["--no-sandbox", "--no-proxy-server", "--disable-dev-shm-usage"],
            )
            page = browser.new_page(viewport={"width": 1440, "height": 900})
            try:
                auth_ui = capture_auth_methods(page, backend.base_url, api_key)
                dropdown_ui = capture_text_model_dropdown(page, backend.base_url)
                pagehide_ok = capture_pagehide_relogin(page, backend.base_url)
            finally:
                browser.close()

        for field in (
            "api_key_visible",
            "pkce_visible",
            "secret_masked",
            "controls_enabled",
        ):
            if auth_ui.get(field) is not True:
                raise SystemExit(f"auth-methods assertion failed: {field}")
        for field in ("dropdown_open", "opaque_background", "visible_border"):
            if dropdown_ui.get(field) is not True:
                raise SystemExit(f"dropdown assertion failed: {field}")
        if dropdown_ui["item_count"] != catalog_model_count:
            raise SystemExit(
                "the rendered selector does not match the live catalog: "
                f"{dropdown_ui['item_count']} options vs {catalog_model_count} models"
            )
        if dropdown_ui["trigger_panel_right_delta"] > 2:
            raise SystemExit("the model panel is not aligned to its trigger")
        if not pagehide_ok:
            raise SystemExit("a second login could not start after pagehide")

        manifest = {
            "automation": {
                "framework": "playwright",
                "passed": True,
                "catalog_source": CATALOG_SOURCE,
                "catalog_model_count": catalog_model_count,
                "image_model_count": 0,
            },
            "artifacts": [
                {
                    "kind": "auth-methods",
                    "path": "auth-methods.png",
                    "sha256": _sha256(EVIDENCE_DIR / "auth-methods.png"),
                    "ui": {
                        "api_key_visible": True,
                        "pkce_visible": True,
                        "secret_masked": True,
                        "controls_enabled": True,
                    },
                },
                {
                    "kind": "text-model-dropdown",
                    "path": "text-model-dropdown.png",
                    "sha256": _sha256(EVIDENCE_DIR / "text-model-dropdown.png"),
                    "ui": {
                        "dropdown_open": True,
                        "item_count": dropdown_ui["item_count"],
                        "opaque_background": True,
                        "visible_border": True,
                        "trigger_panel_right_delta": dropdown_ui[
                            "trigger_panel_right_delta"
                        ],
                    },
                },
            ],
            "catalog_models": [model["id"] for model in catalog["models"]],
            "notes": (
                "Generated by scripts/orca_evidence.py against the running "
                "MiroFish app: the Flask provider blueprint "
                "(backend/app/api/orcarouter.py) and the built frontend served "
                "on one origin, driven by Playwright/chromium. The selector "
                f"options are the live {CATALOG_SOURCE} result filtered to the "
                "chat capability. This repository has no image/video entry "
                "point, so no multimodal selector exists."
            ),
        }
        (EVIDENCE_DIR / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(manifest["automation"], ensure_ascii=False))
        return 0
    finally:
        backend.stop()


if __name__ == "__main__":
    sys.exit(main())
