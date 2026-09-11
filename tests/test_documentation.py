"""Versioned GitHub documentation and diagnostic anchors resolve in every locale."""
import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit
from unittest.mock import Mock, patch

from core import __version__
from core.gui import (DOCUMENTATION_REF, GITHUB_URL,
                      get_documentation_ref, get_documentation_url, get_troubleshooting_url)

ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):

    def test_gui_language_paths_and_diagnostic_anchors(self):
        prefix = f'{urlsplit(GITHUB_URL).path}/blob/{DOCUMENTATION_REF}/'
        for language, suffix in [('zh-Hant', ''), ('en', '.en'), ('ja', '.ja'), ('unknown', '.en')]:
            for name in ('README', 'docs/TROUBLESHOOTING'):
                url = urlsplit(get_documentation_url(f'{name}.md', language))
                self.assertEqual((url.scheme, url.netloc), ('https', 'github.com'))
                self.assertEqual(unquote(url.path), f'{prefix}{name}{suffix}.md')
                self.assertTrue((ROOT / f'{name}{suffix}.md').is_file())
            for label, anchor in [('FileVault', 'filevault'), ('macOS 自動登入', 'filevault'),
                                  ('BetterDisplay 控制介面', 'betterdisplay'), ('登入啟動', 'autostart'),
                                  ('背景服務', 'autostart'), ('Sidecar', 'sidecar-session'), ('其他', '')]:
                url = urlsplit(get_troubleshooting_url(label, language))
                self.assertEqual(url.fragment, anchor)
                self.assertEqual(unquote(url.path), f'{prefix}docs/TROUBLESHOOTING{suffix}.md')
                if anchor:
                    self.assertIn(f'id="{anchor}"', (ROOT / f'docs/TROUBLESHOOTING{suffix}.md').read_text())

    def test_documentation_revision_uses_archive_or_checkout_and_freezes_links(self):
        revision = 'a' * 40
        with patch('core.gui.__revision__', revision), patch('core.gui.subprocess.run') as git:
            self.assertEqual(get_documentation_ref(), revision)
            git.assert_not_called()
        with patch('core.gui.__revision__', '$Format:%H$'), \
             patch('core.gui.ROOT') as source, patch('core.gui.subprocess.run') as git:
            (source / '.git').exists.return_value = True
            git.return_value = Mock(stdout=revision + '\n')
            self.assertEqual(get_documentation_ref(), revision)
            original = get_documentation_url('README.md', 'en')
            git.return_value = Mock(stdout='b' * 40 + '\n')
            self.assertEqual(get_documentation_url('README.md', 'en'), original)
            git.side_effect = OSError('git unavailable')
            self.assertEqual(get_documentation_ref(), f'v{__version__}')
            git.reset_mock()
            (source / '.git').exists.return_value = False
            self.assertEqual(get_documentation_ref(), f'v{__version__}')
            git.assert_not_called()

    def test_document_translations_and_local_links_exist(self):
        documents = list((ROOT / 'docs').rglob('*.md')) + list(ROOT.glob('README*.md'))
        for source in documents:
            content = source.read_text()
            if ROOT / 'docs' / 'development' in source.parents:
                self.assertFalse(source.name.endswith(('.en.md', '.ja.md')), source)
            else:
                if not source.name.endswith(('.en.md', '.ja.md')):
                    for suffix in ('.en.md', '.ja.md'):
                        self.assertTrue(source.with_suffix(suffix).is_file(), source)
                self.assertIn('繁體中文', content, source)
                self.assertIn('English', content, source)
                self.assertIn('日本語', content, source)
            for target in re.findall(r'\]\(([^\s)]+)\)|href="([^"]+)"|src="([^"]+)"', content):
                link = urlsplit(next(part for part in target if part))
                if link.scheme or link.netloc:
                    continue
                path = (source.parent / unquote(link.path)).resolve() if link.path else source
                self.assertTrue(path.exists(), (source, link.path))
                if link.fragment and 'TROUBLESHOOTING' in path.name:
                    self.assertIn(f'id="{link.fragment}"', path.read_text())


    def test_native_about_metadata_and_localized_links_ignore_hardware(self):
        from core.config import Config
        from core.gui import build_gui_payload
        from core.i18n import set_language
        view = {'config': Config(language='en'), 'config_error': '', 'actual': {}, 'status': {},
                'fresh': True, 'scanned': False, 'consistency_state': 'CONSISTENT', 'identifiers': []}
        try:
            with patch('core.gui.read_view', return_value=view), \
                 patch('core.gui.BetterDisplayCLI.resolve_cli_path', return_value=None):
                original = build_gui_payload()
                view['actual'] = {'timestamp': 1, 'online_displays': [{'name': 'Other display'}]}
                changed = build_gui_payload()
                for key in ('version', 'links', 'donations', 'strings'):
                    self.assertEqual(changed[key], original[key])
                self.assertEqual(original['version'], __version__)
                self.assertEqual(original['links']['github'], GITHUB_URL)
                self.assertEqual(original['donations'], {'Buy Me a Coffee': '', 'PayPal': ''})
                for language, suffix in [('zh-Hant', ''), ('en', '.en'), ('ja', '.ja')]:
                    view['config'].language = language
                    payload = build_gui_payload()
                    self.assertEqual(payload['links']['help'], get_documentation_url('README.md', language))
                    self.assertIn('README' + suffix + '.md', payload['links']['help'])
        finally:
            set_language('zh-Hant')


if __name__ == '__main__':
    unittest.main()
