"""Local language navigation and diagnostic anchors must resolve in every locale."""
import re
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit

from core.gui import SettingsWindow, get_documentation_url, get_troubleshooting_url

ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_about_content_does_not_refresh_for_hardware_changes(self):
        app = SettingsWindow.__new__(SettingsWindow)
        app.current_tab = 'about'
        app._display_language = 'en'
        original = app._content_signature()
        app.view = {'actual': {'timestamp': 1, 'online_displays': [{'name': 'Other display'}]}}
        self.assertEqual(app._content_signature(), original)
        app._display_language = 'ja'
        self.assertNotEqual(app._content_signature(), original)

    def test_gui_language_paths_and_diagnostic_anchors(self):
        for language, suffix in [('zh-Hant', ''), ('en', '.en'), ('ja', '.ja'), ('unknown', '.en')]:
            for name in ('README', 'docs/TROUBLESHOOTING'):
                url = urlsplit(get_documentation_url(f'{name}.md', language))
                self.assertEqual(url.scheme, 'file')
                self.assertEqual(Path(unquote(url.path)), ROOT / f'{name}{suffix}.md')
                self.assertTrue(Path(unquote(url.path)).is_file())
            for label, anchor in [('FileVault', 'filevault'), ('macOS 自動登入', 'filevault'),
                                  ('BetterDisplay 控制介面', 'betterdisplay'), ('登入啟動', 'autostart'),
                                  ('背景服務', 'autostart'), ('Sidecar', 'sidecar-session'), ('其他', '')]:
                url = urlsplit(get_troubleshooting_url(label, language))
                self.assertEqual(url.fragment, anchor)
                self.assertEqual(Path(unquote(url.path)), ROOT / f'docs/TROUBLESHOOTING{suffix}.md')
                if anchor:
                    self.assertIn(f'id="{anchor}"', Path(unquote(url.path)).read_text())

    def test_document_translations_and_local_links_exist(self):
        documents = list((ROOT / 'docs').rglob('*.md')) + list(ROOT.glob('README*.md'))
        for source in documents:
            if not source.name.endswith(('.en.md', '.ja.md')):
                for suffix in ('.en.md', '.ja.md'):
                    self.assertTrue(source.with_suffix(suffix).is_file(), source)
            content = source.read_text()
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


if __name__ == '__main__':
    unittest.main()
