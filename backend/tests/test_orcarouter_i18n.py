"""Locale catalog invariants for the OrcaRouter provider strings.

The frontend resolves every user-visible OrcaRouter string through
``vue-i18n`` from ``locales/<locale>.json``. A key that exists in one
published locale but not another renders as a raw key for those users, so the
two catalogs must stay in parity, and the component must not reference a key
that no catalog defines.
"""

import json
import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
LOCALES = REPO_ROOT / "locales"
COMPONENT = REPO_ROOT / "frontend" / "src" / "components" / "OrcaProviderSettings.vue"

PUBLISHED_LOCALES = ("en", "zh")


def _catalog(locale):
    return json.loads((LOCALES / f"{locale}.json").read_text(encoding="utf-8"))


def test_published_locales_share_the_same_key_set():
    catalogs = {locale: _catalog(locale) for locale in PUBLISHED_LOCALES}
    reference = set(_flatten(catalogs[PUBLISHED_LOCALES[0]]))
    for locale, catalog in catalogs.items():
        keys = set(_flatten(catalog))
        assert keys == reference, (
            f"{locale} locale key set differs: "
            f"missing={sorted(reference - keys)} extra={sorted(keys - reference)}"
        )


def test_orcarouter_catalog_completes_every_published_locale():
    for locale in PUBLISHED_LOCALES:
        section = _catalog(locale).get("orcarouter")
        assert isinstance(section, dict) and section, f"{locale} has no orcarouter catalog"
        for key, value in section.items():
            assert isinstance(value, str) and value.strip(), f"{locale}.orcarouter.{key} is empty"


def test_component_only_references_defined_orcarouter_keys():
    source = COMPONENT.read_text(encoding="utf-8")
    referenced = set(re.findall(r"\bt\('orcarouter\.([A-Za-z0-9_]+)'", source))
    assert referenced, "the provider component should resolve its strings via i18n"

    for locale in PUBLISHED_LOCALES:
        defined = set(_catalog(locale)["orcarouter"])
        missing = sorted(referenced - defined)
        assert not missing, f"{locale}.json lacks orcarouter keys: {missing}"


def test_provider_strings_are_not_hardcoded_in_the_component():
    source = COMPONENT.read_text(encoding="utf-8")
    template = source.split("<script setup>", 1)[0]
    # Strip i18n calls, then look for prose that should have been translated.
    stripped = re.sub(r"\{\{[^}]*\}\}", "", template)
    for literal in ("Connect with OrcaRouter", "Save API Key", "Loading models"):
        assert literal not in stripped, f"hardcoded user-facing string: {literal}"


def _flatten(mapping, prefix=""):
    for key, value in mapping.items():
        path = f"{prefix}{key}"
        if isinstance(value, dict):
            yield from _flatten(value, path + ".")
        else:
            yield path
