from flask import Flask

from app.utils.locale import get_language_instruction, get_locale


def test_registered_spanish_language_guides_report_even_without_ui_translation():
    app = Flask(__name__)
    with app.test_request_context(headers={"Accept-Language": "es"}):
        assert get_locale() == "es"
        assert "español" in get_language_instruction()
