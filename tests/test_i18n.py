import ast
import contextlib
import io
import json
from pathlib import Path
import runpy
from string import Formatter
import unittest
from unittest.mock import MagicMock, patch

from core.config import Config
from core.i18n import LANGUAGES, TRANSLATIONS, set_language, tr, tr_message
from core.settings import apply_change

ROOT = Path(__file__).resolve().parents[1]


class LanguageTests(unittest.TestCase):
    def tearDown(self):
        set_language('zh-Hant')

    def test_validation_roundtrip_and_daemon_no_display_effects(self):
        self.assertEqual(Config.from_dict({}).language, 'zh-Hant')
        self.assertEqual(Config.from_dict({'language': ['en']}).language, 'zh-Hant')
        cfg = Config()
        for language in LANGUAGES:
            self.assertFalse(apply_change(cfg, 'set_language', {'language': language}))
            self.assertEqual(Config.from_dict(cfg.to_dict()).language, language)
        for payload in ({}, {'language': 'fr'}, {'language': None}, {'language': []}, {'language': 'en', 'extra': True}):
            with self.assertRaises(ValueError):
                apply_change(cfg, 'set_language', payload)
        daemon_type = runpy.run_path(str(ROOT / 'bin/padpilotd'))['PadPilotDaemon']
        daemon = daemon_type.__new__(daemon_type)
        daemon.config = Config()
        daemon.engine = MagicMock()
        daemon.detector = MagicMock()
        namespace = daemon.apply_config_change.__globals__
        with patch.dict(namespace, save_config=MagicMock(), notify_swiftbar=MagicMock()):
            response = json.loads(daemon.handle_client_cmd(json.dumps({'command': 'set_language', 'params': {'language': 'en'}})))
        self.assertTrue(response['ok'])
        self.assertEqual(daemon.config.language, 'en')
        daemon.engine.reset_automation.assert_not_called()
        daemon.engine.evaluate.assert_not_called()
        self.assertEqual(daemon.config.revision, 2)
        cli = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))['submit_settings']
        stored = []
        with patch.dict(cli.__globals__, send_daemon_cmd=lambda *a, **k: 'Daemon is not running',
                        load_config=lambda: Config(), save_config=stored.append, notify_swiftbar=MagicMock()):
            with contextlib.redirect_stdout(io.StringIO()):
                cli('set_language', {'language': 'ja'})
        self.assertEqual(stored[0].language, 'ja')
        self.assertEqual(stored[0].revision, 2)

    def test_catalog_coverage_placeholders_and_menu_data(self):
        fields = lambda text: [(f, spec, conv) for _, f, spec, conv in Formatter().parse(text) if f is not None]
        for source, translations in TRANSLATIONS.items():
            self.assertTrue(translations['en'])
            self.assertTrue(translations['ja'])
            for text in translations.values():
                self.assertEqual(fields(source), fields(text), source)
        for path in ('core/gui.py', 'swiftbar/padpilot.30s.py'):
            for node in ast.walk(ast.parse((ROOT / path).read_text())):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'tr'
                        and node.args and isinstance(node.args[0], ast.Constant)):
                    text = node.args[0].value
                    if any('\u4e00' <= c <= '\u9fff' for c in text):
                        self.assertIn(text, TRANSLATIONS)
        render = runpy.run_path(str(ROOT / 'swiftbar/padpilot.30s.py'))['render']
        for language in LANGUAGES:
            set_language(language)
            message = 'Physical display detected (我的螢幕 {0}). Automatic Sidecar not required.'
            self.assertIn('我的螢幕 {0}', tr_message(message))
            self.assertEqual(tr_message('Unrecognized error {raw}'), 'Unrecognized error {raw}')
            self.assertIn('4.0', tr_message('Physical display disconnected. Waiting debounce (4.0s remaining)...'))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                render({}, {'language': language, 'ipad': {'name': '運作模式 {0} | test', 'usb_serial': 'USB123'}}, False)
            text = output.getvalue()
            self.assertIn(tr('設定與配對'), text)
            self.assertIn('運作模式 {0} ｜ test', text)
            self.assertIn('USB123', text)
            if language == 'en':
                self.assertNotIn('狀態未知', text)
            self.assertEqual(tr('主螢幕：{0}', '主螢幕 {0}'), {'zh-Hant':'主螢幕：主螢幕 {0}', 'en':'Main display: 主螢幕 {0}', 'ja':'メイン：主螢幕 {0}'}[language])
