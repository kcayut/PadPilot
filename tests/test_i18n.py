import argparse
import ast
import contextlib
import io
import json
import os
from pathlib import Path
import runpy
from string import Formatter
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from core.config import Config, detect_system_language, load_config, save_config
from core.i18n import LANGUAGES, LANGUAGE_CODES, TRANSLATIONS, set_language, tr, tr_message
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

    def test_detect_system_language(self):
        cases = [
            ('(\n    "zh-Hant-TW",\n    "en-US"\n)', 'zh-Hant'),
            ('(\n    "zh-TW"\n)', 'zh-Hant'),
            ('(\n    "zh-HK"\n)', 'zh-Hant'),
            ('(\n    "zh-MO"\n)', 'zh-Hant'),
            ('(\n    "ja-JP"\n)', 'ja'),
            ('(\n    "ja"\n)', 'ja'),
            ('(\n    "zh-Hans-CN"\n)', 'en'),  # Simplified Chinese falls back to en
            ('(\n    "zh-CN"\n)', 'en'),
            ('(\n    "zh-SG"\n)', 'en'),
            ('(\n    "en-US"\n)', 'en'),
            ('(\n    "de-DE"\n)', 'en'),
            ('(\n    "fr-FR"\n)', 'en'),
        ]
        for mock_output, expected in cases:
            res = subprocess.CompletedProcess(args=['defaults'], returncode=0, stdout=mock_output)
            with patch('subprocess.run', return_value=res):
                self.assertEqual(detect_system_language(), expected, f"Failed for {mock_output}")

        # Fallback when defaults fails
        fail_res = subprocess.CompletedProcess(args=['defaults'], returncode=1, stdout='')
        with patch('subprocess.run', return_value=fail_res):
            with patch.dict(os.environ, {'LANG': 'zh_TW.UTF-8'}):
                self.assertEqual(detect_system_language(), 'zh-Hant')
            with patch.dict(os.environ, {'LANG': 'ja_JP.UTF-8'}):
                self.assertEqual(detect_system_language(), 'ja')
            with patch.dict(os.environ, {'LANG': 'zh_CN.UTF-8'}):
                self.assertEqual(detect_system_language(), 'en')
            with patch.dict(os.environ, {'LANG': 'C.UTF-8'}):
                self.assertEqual(detect_system_language(), 'en')

    def test_first_run_lifecycle_and_persistence(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_config_path = Path(tmpdir) / "config.json"
            test_fallback_path = Path(tmpdir) / "fallback.json"
            self.assertFalse(test_config_path.exists())

            # 1. First run with English system language -> config initialized to 'en'
            with patch('core.config.CONFIG_FILE', test_config_path), \
                 patch('core.config.FALLBACK_CONFIG_FILE', test_fallback_path), \
                 patch('core.config.APP_SUPPORT_DIR', Path(tmpdir)), \
                 patch('core.config.detect_system_language', return_value='en') as mock_detect:
                cfg = load_config()
                mock_detect.assert_called_once()
                self.assertEqual(cfg.language, 'en')
                self.assertTrue(test_config_path.exists())

            # 2. User manually changes to Japanese
            cfg.language = 'ja'
            with patch('core.config.CONFIG_FILE', test_config_path), \
                 patch('core.config.FALLBACK_CONFIG_FILE', test_fallback_path), \
                 patch('core.config.APP_SUPPORT_DIR', Path(tmpdir)):
                save_config(cfg)

            # 3. Subsequent runs with Chinese system language -> existing config is read, NOT overwritten!
            with patch('core.config.CONFIG_FILE', test_config_path), \
                 patch('core.config.FALLBACK_CONFIG_FILE', test_fallback_path), \
                 patch('core.config.APP_SUPPORT_DIR', Path(tmpdir)), \
                 patch('core.config.detect_system_language', return_value='zh-Hant') as mock_detect_zh:
                reloaded = load_config()
                mock_detect_zh.assert_not_called()
                self.assertEqual(reloaded.language, 'ja')

    def test_ipc_and_offline_revision_ownership(self):
        cli_mod = runpy.run_path(str(ROOT / 'bin/padpilot-cli'))
        cmd_set_lang = cli_mod['cmd_set_language']

        # Case 1: Daemon running. Sends IPC, daemon mutates revision + 1, CLI does NOT save config.
        sent_cmds = []
        mock_save = MagicMock()
        with patch.dict(cli_mod['submit_settings'].__globals__,
                        send_daemon_cmd=lambda cmd, timeout=60.0: sent_cmds.append(cmd) or json.dumps({"ok": True, "config_revision": 2, "message": "OK"}),
                        save_config=mock_save):
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_set_lang(argparse.Namespace(language='ja'))
            self.assertEqual(len(sent_cmds), 1)
            req = json.loads(sent_cmds[0])
            self.assertEqual(req['command'], 'set_language')
            self.assertEqual(req['params'], {'language': 'ja'})
            mock_save.assert_not_called()

        # Case 2: Daemon offline. Fallback mutates config and increments revision exactly once.
        saved_configs = []
        mock_cfg = Config(revision=5, language='en')
        with patch.dict(cli_mod['submit_settings'].__globals__,
                        send_daemon_cmd=lambda *a, **k: 'Daemon is not running',
                        load_config=lambda: mock_cfg,
                        save_config=saved_configs.append,
                        notify_swiftbar=MagicMock()):
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_set_lang(argparse.Namespace(language='ja'))
            self.assertEqual(len(saved_configs), 1)
            self.assertEqual(saved_configs[0].language, 'ja')
            self.assertEqual(saved_configs[0].revision, 6)

        # Case 3: Same language no-op. When language does not change, revision is not incremented.
        saved_configs.clear()
        mock_cfg_same = Config(revision=6, language='ja')
        with patch.dict(cli_mod['submit_settings'].__globals__,
                        send_daemon_cmd=lambda *a, **k: 'Daemon is not running',
                        load_config=lambda: mock_cfg_same,
                        save_config=saved_configs.append,
                        notify_swiftbar=MagicMock()):
            with contextlib.redirect_stdout(io.StringIO()):
                cmd_set_lang(argparse.Namespace(language='ja'))
            self.assertEqual(len(saved_configs), 0)

        # Case 4: SwiftBar menu renders 🌐 Language and dispatches set-language
        render = runpy.run_path(str(ROOT / 'swiftbar/padpilot.30s.py'))['render']
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            render({}, {'language': 'en'}, False)
        text = out.getvalue()
        self.assertIn('🌐 Language |', text)
        self.assertIn("English | ansi=false emojize=false symbolize=false color=#1c1c1e,#f2f2f7 checked=true bash=", text)
        self.assertIn("param1=set-language param2=en", text)
        self.assertIn("param1=set-language param2=zh-Hant", text)
        self.assertIn("param1=set-language param2=ja", text)

        # Case 5: config_revision > status_config_revision applies Applying rules in target language
        out_applying = io.StringIO()
        with contextlib.redirect_stdout(out_applying):
            render({'config_revision': 1, 'actual': {'timestamp': time.time()}},
                   {'language': 'en', 'revision': 2}, False)
        text_applying = out_applying.getvalue()
        self.assertIn('Applying settings…', text_applying)
