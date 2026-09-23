#!/usr/bin/env python3
"""Build the three-language static introduction site into build/website."""

import html
import json
import shutil
from html.parser import HTMLParser
from pathlib import Path
from string import Template
from urllib.parse import unquote, urlsplit
from xml.etree.ElementTree import Element, ElementTree, SubElement

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "website"
OUTPUT = ROOT / "build" / "website"
LANGUAGES = {"zh-Hant": ("index.html", "繁體中文"), "en": ("en.html", "English"), "ja": ("ja.html", "日本語")}
SITE_URL = "https://kcayut.github.io/SidecarSwitch/"


class References(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.ids = set()
        self.canonical = []
        self.alternates = {}

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "link" and values.get("rel") == "canonical":
            self.canonical.append(values.get("href"))
        if tag == "link" and values.get("rel") == "alternate":
            self.alternates[values.get("hreflang")] = values.get("href")
        if "id" in values:
            self.ids.add(values["id"])
        for key in ("href", "src"):
            if values.get(key):
                self.links.append(values[key])


def main():
    translations = json.loads((SOURCE / "content.json").read_text(encoding="utf-8"))
    if set(translations) != set(LANGUAGES):
        raise ValueError("Expected Traditional Chinese, English and Japanese content")
    if any(set(content) != set(translations["zh-Hant"]) for content in translations.values()):
        raise ValueError("Translation fields must match across all three languages")
    template = Template((SOURCE / "template.html").read_text(encoding="utf-8"))
    (OUTPUT / "media").mkdir(parents=True, exist_ok=True)
    shutil.copy2(SOURCE / "style.css", OUTPUT / "style.css")
    assets = {
        "icon.png": ROOT / "assets/sidecarswitch-icon.png",
        "headless-boot-demo.mp4": ROOT / "docs/videos/headless-boot-demo.mp4",
        **{name: ROOT / "docs/images/support" / name for name in ("opay.png", "ecpay.png", "paypal.svg", "ko-fi.png")},
        **{f"{lang}-paired.png": ROOT / f"docs/images/quick-start/{lang}-paired.png" for lang in LANGUAGES},
    }
    for name, source in assets.items():
        shutil.copy2(source, OUTPUT / "media" / name)
    page_urls = {lang: SITE_URL + ("" if page == "index.html" else page) for lang, (page, _) in LANGUAGES.items()}
    alternates = {**page_urls, "x-default": SITE_URL}
    for lang, (page, _) in LANGUAGES.items():
        values = {key: html.escape(value, quote=True) for key, value in translations[lang].items()}
        values.update(lang=lang, page=page)
        values["canonical_url"] = page_urls[lang]
        values["alternate_links"] = "\n  ".join(
            f'<link rel="alternate" hreflang="{code}" href="{url}">'
            for code, url in alternates.items()
        )
        values["language_links"] = "".join(
            f'<a href="{filename}" lang="{code}" hreflang="{code}"'
            + (' aria-current="page"' if code == lang else '')
            + f'>{label}</a>' for code, (filename, label) in LANGUAGES.items()
        )
        (OUTPUT / page).write_text(template.substitute(values), encoding="utf-8")
    sitemap = Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for url in page_urls.values():
        SubElement(SubElement(sitemap, "url"), "loc").text = url
    ElementTree(sitemap).write(OUTPUT / "sitemap.xml", encoding="utf-8", xml_declaration=True)
    # A build must not ship broken local media, language links or section anchors.
    for lang, (page, _) in LANGUAGES.items():
        references = References()
        references.feed((OUTPUT / page).read_text(encoding="utf-8"))
        if references.canonical != [page_urls[lang]] or references.alternates != alternates:
            raise ValueError(f"{page}: invalid canonical or language URLs")
        for link in references.links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            if parsed.path and not (OUTPUT / unquote(parsed.path)).is_file():
                raise ValueError(f"{page}: missing asset or page: {link}")
            if not parsed.path and parsed.fragment not in references.ids:
                raise ValueError(f"{page}: missing section: {link}")
    print(f"Built and checked 3 languages, search metadata, sitemap and all local links: {OUTPUT}")


if __name__ == "__main__":
    main()
