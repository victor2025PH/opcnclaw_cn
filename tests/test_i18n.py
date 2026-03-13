"""Tests for i18n module."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.gui.i18n import t, set_locale, get_locale, available_locales


class TestI18n:

    def test_default_locale_is_zh(self):
        set_locale("zh")
        assert get_locale() == "zh"

    def test_set_locale_en(self):
        set_locale("en")
        assert get_locale() == "en"
        set_locale("zh")

    def test_invalid_locale_ignored(self):
        set_locale("zh")
        set_locale("fr")
        assert get_locale() == "zh"

    def test_translate_zh(self):
        set_locale("zh")
        assert t("save") == "保存设置"
        assert t("tab_ai") == "🤖  AI 平台"

    def test_translate_en(self):
        set_locale("en")
        assert t("save") == "Save Settings"
        assert t("tab_ai") == "🤖  AI Platform"
        set_locale("zh")

    def test_missing_key_returns_key(self):
        assert t("nonexistent_key_xyz") == "nonexistent_key_xyz"

    def test_available_locales(self):
        locales = available_locales()
        assert len(locales) >= 2
        codes = [c for c, _ in locales]
        assert "zh" in codes
        assert "en" in codes

    def test_tab_translations_complete(self):
        tabs = ["tab_ai", "tab_voice", "tab_bridge", "tab_skills",
                "tab_mcp", "tab_model", "tab_system"]
        for locale in ("zh", "en"):
            set_locale(locale)
            for tab in tabs:
                result = t(tab)
                assert result != tab, f"Missing translation: {tab} for {locale}"
        set_locale("zh")
