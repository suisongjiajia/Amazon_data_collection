from __future__ import annotations

import re
from dataclasses import dataclass

LOCALE_PATH_PATTERN = re.compile(r"^/(-/([a-z]{2}(?:-[a-z]{2})?))/")

SITE_DEFAULTS: dict[str, dict[str, str]] = {
    "www.amazon.com": {
        "currency": "USD",
        "accept_language": "en-US,en;q=0.9",
        "country": "US",
        "lc_main": "en_US",
    },
    "www.amazon.co.uk": {
        "currency": "GBP",
        "accept_language": "en-GB,en;q=0.9",
        "country": "GB",
        "lc_main": "en_GB",
    },
    "www.amazon.de": {
        "currency": "EUR",
        "accept_language": "de-DE,de;q=0.9,en;q=0.8",
        "country": "DE",
        "lc_main": "de_DE",
    },
    "www.amazon.fr": {
        "currency": "EUR",
        "accept_language": "fr-FR,fr;q=0.9,en;q=0.8",
        "country": "FR",
        "lc_main": "fr_FR",
    },
    "www.amazon.co.jp": {
        "currency": "JPY",
        "accept_language": "ja-JP,ja;q=0.9,en;q=0.8",
        "country": "JP",
        "lc_main": "ja_JP",
    },
    "www.amazon.ca": {
        "currency": "CAD",
        "accept_language": "en-CA,en;q=0.9",
        "country": "CA",
        "lc_main": "en_CA",
    },
}

LOCALE_LANGUAGE: dict[str, str] = {
    "zh": "zh-CN,zh;q=0.9,en;q=0.8",
    "de": "de-DE,de;q=0.9,en;q=0.8",
    "fr": "fr-FR,fr;q=0.9,en;q=0.8",
    "es": "es-ES,es;q=0.9,en;q=0.8",
    "it": "it-IT,it;q=0.9,en;q=0.8",
    "ja": "ja-JP,ja;q=0.9,en;q=0.8",
    "pt": "pt-BR,pt;q=0.9,en;q=0.8",
    "nl": "nl-NL,nl;q=0.9,en;q=0.8",
    "pl": "pl-PL,pl;q=0.9,en;q=0.8",
    "tr": "tr-TR,tr;q=0.9,en;q=0.8",
    "ar": "ar-AE,ar;q=0.9,en;q=0.8",
}


@dataclass(frozen=True)
class MarketplaceContext:
    host: str
    locale_prefix: str
    accept_language: str
    currency: str
    country_code: str
    cookie_domain: str

    def build_product_url(self, asin: str) -> str:
        if self.locale_prefix:
            return f"https://{self.host}{self.locale_prefix}/dp/{asin}"
        return f"https://{self.host}/dp/{asin}"

    def build_home_url(self) -> str:
        if self.locale_prefix:
            return f"https://{self.host}{self.locale_prefix}/"
        return f"https://{self.host}/"

    def cookie_items(self) -> dict[str, str]:
        site = _resolve_site_defaults(self.host)
        return {
            "i18n-prefs": self.currency,
            "lc-main": site["lc_main"],
            "sp-cdn": f"L5Z9:{self.country_code}",
        }


def extract_locale_prefix(path: str) -> str:
    match = LOCALE_PATH_PATTERN.match(path or "")
    if match:
        return match.group(0).rstrip("/")
    return ""


def build_marketplace_context(host: str, locale_prefix: str = "") -> MarketplaceContext:
    site = _resolve_site_defaults(host)
    accept_language = site["accept_language"]
    locale_code = locale_prefix.replace("/-/", "").split("/")[0] if locale_prefix else ""
    if locale_code in LOCALE_LANGUAGE:
        accept_language = LOCALE_LANGUAGE[locale_code]

    root_domain = _cookie_domain(host)
    return MarketplaceContext(
        host=host,
        locale_prefix=locale_prefix,
        accept_language=accept_language,
        currency=site["currency"],
        country_code=site["country"],
        cookie_domain=root_domain,
    )


def _resolve_site_defaults(host: str) -> dict[str, str]:
    normalized_host = host.lower()
    if normalized_host in SITE_DEFAULTS:
        return SITE_DEFAULTS[normalized_host]

    for site_host, defaults in SITE_DEFAULTS.items():
        if normalized_host.endswith(site_host.replace("www.", "")):
            return defaults

    return SITE_DEFAULTS["www.amazon.com"]


def _cookie_domain(host: str) -> str:
    parts = host.lower().split(".")
    if len(parts) >= 2:
        return "." + ".".join(parts[-2:])
    return host
