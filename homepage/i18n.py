"""The languages of this PC's sites: one choice for all of them.

A visitor picks a language with ``?lang=<code>`` on any address (the portal answers with a cookie
and the same address without it) or with a site's own menu; the ``lang`` cookie is for the whole
host, so the portal, News Site and CoreLab all show the same language. Without a choice the
browser's languages decide (Accept-Language), and Japanese when it sends none.

Texts are written in Japanese and looked up here by that Japanese (``text(lang, "サイト一覧")``);
a text without a translation is shown in Japanese.
"""

from __future__ import annotations

import html
from datetime import datetime
from http.cookies import SimpleCookie
from urllib.parse import parse_qsl, urlencode

LANGS = ("ja", "ko", "en-GB", "zh-TW")
DEFAULT = "ja"
#: Each language in its own words (the menu).
NAMES = {"ja": "日本語", "ko": "한국어", "en-GB": "English (UK)", "zh-TW": "中文（台灣）"}
#: og:locale
LOCALES = {"ja": "ja_JP", "ko": "ko_KR", "en-GB": "en_GB", "zh-TW": "zh_TW"}
COOKIE = "lang"
COOKIE_SECONDS = 365 * 24 * 3600

TEXTS = {
    "サイト一覧": {"ko": "사이트 목록", "en-GB": "All sites", "zh-TW": "網站列表"},
    "サイト一覧へ戻る": {"ko": "사이트 목록으로 돌아가기", "en-GB": "Back to all sites", "zh-TW": "回到網站列表"},
    "言語": {"ko": "언어", "en-GB": "Language", "zh-TW": "語言"},
    "ダークモード {state}": {"ko": "다크 모드 {state}", "en-GB": "Dark mode: {state}", "zh-TW": "深色模式：{state}"},
    "ダークモード: 自動 → オフ → オン": {
        "ko": "다크 모드: 자동 → 끔 → 켬",
        "en-GB": "Dark mode: auto → off → on",
        "zh-TW": "深色模式：自動 → 關 → 開",
    },
    "自動": {"ko": "자동", "en-GB": "auto", "zh-TW": "自動"},
    "オフ": {"ko": "끔", "en-GB": "off", "zh-TW": "關"},
    "オン": {"ko": "켬", "en-GB": "on", "zh-TW": "開"},
    "特徴": {"ko": "특징", "en-GB": "Features", "zh-TW": "特色"},
    "新着": {"ko": "새 소식", "en-GB": "Latest", "zh-TW": "最新"},
    "{name} を開く": {"ko": "{name} 열기", "en-GB": "Open {name}", "zh-TW": "開啟 {name}"},
    "非公開（このPCからだけ）": {
        "ko": "비공개 (이 PC에서만)",
        "en-GB": "Private (this PC only)",
        "zh-TW": "未公開（僅限本機）",
    },
    "サイト {count} 件": {"ko": "사이트 {count}개", "en-GB": "{count} sites", "zh-TW": "共 {count} 個網站"},
    "エラー {status}": {"ko": "오류 {status}", "en-GB": "Error {status}", "zh-TW": "錯誤 {status}"},
    "ページが見つかりません": {"ko": "페이지를 찾을 수 없습니다", "en-GB": "Page not found", "zh-TW": "找不到這個頁面"},
    "アドレスが変わったか、なくなった可能性があります。": {
        "ko": "주소가 바뀌었거나 페이지가 없어졌을 수 있습니다.",
        "en-GB": "The address may have changed, or the page may no longer exist.",
        "zh-TW": "網址可能已變更，或頁面已不存在。",
    },
    "{name} のトップへ": {"ko": "{name} 첫 화면으로", "en-GB": "{name} home", "zh-TW": "前往 {name} 首頁"},
    # 持ち主のログイン (/owner)
    "持ち主のログイン": {"ko": "소유자 로그인", "en-GB": "Owner sign-in", "zh-TW": "擁有者登入"},
    "このサイトの持ち主だけが使うページです。ログインすると、この端末ではすべての機能が使えます。": {
        "ko": "이 사이트의 소유자만 쓰는 페이지입니다. 로그인하면 이 기기에서 모든 기능을 쓸 수 있습니다.",
        "en-GB": "This page is for the owner of these sites. Once signed in, this device can use every feature.",
        "zh-TW": "這是網站擁有者專用的頁面。登入後，這台裝置就能使用所有功能。",
    },
    "この端末は持ち主としてログインしています。公開中のページでも、すべての機能が使えます。": {
        "ko": "이 기기는 소유자로 로그인되어 있습니다. 공개 중인 페이지에서도 모든 기능을 쓸 수 있습니다.",
        "en-GB": "This device is signed in as the owner, so every feature works on the public pages too.",
        "zh-TW": "這台裝置已用擁有者身分登入，在公開的頁面上也能使用所有功能。",
    },
    "パスワード": {"ko": "비밀번호", "en-GB": "Password", "zh-TW": "密碼"},
    "ログイン": {"ko": "로그인", "en-GB": "Sign in", "zh-TW": "登入"},
    "ログアウト": {"ko": "로그아웃", "en-GB": "Sign out", "zh-TW": "登出"},
    "パスワードが違います。": {
        "ko": "비밀번호가 맞지 않습니다.",
        "en-GB": "That password is not right.",
        "zh-TW": "密碼不正確。",
    },
    "試した回数が多すぎます。少し待ってからもう一度どうぞ。": {
        "ko": "시도 횟수가 너무 많습니다. 잠시 후 다시 시도해 주세요.",
        "en-GB": "Too many tries. Please wait a little and try again.",
        "zh-TW": "嘗試次數過多，請稍候再試。",
    },
    "ログインはまだ設定されていません。": {
        "ko": "로그인이 아직 설정되지 않았습니다.",
        "en-GB": "Sign-in has not been set up yet.",
        "zh-TW": "尚未設定登入。",
    },
}

_WEEKDAYS = {"ja": "月火水木金土日", "ko": "월화수목금토일", "zh-TW": "一二三四五六日"}
_EN_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
_EN_MONTHS = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def text(lang: str, ja: str, **values) -> str:
    """``ja`` in ``lang`` (Japanese when there is no translation), with ``{name}`` filled in."""
    if lang == "en-GB" and values.get("count") == 1 and ja == "サイト {count} 件":
        return "1 site"
    return TEXTS.get(ja, {}).get(lang, ja).format(**values)


def date(lang: str, day: datetime) -> str:
    """The day as people write it in ``lang``: 2026年10月27日（火） / Tuesday 27 October 2026."""
    if lang == "en-GB":
        return f"{_EN_WEEKDAYS[day.weekday()]} {day.day} {_EN_MONTHS[day.month - 1]} {day.year}"
    if lang == "ko":
        return f"{day.year}년 {day.month}월 {day.day}일 ({_WEEKDAYS['ko'][day.weekday()]})"
    weekday = _WEEKDAYS.get(lang, _WEEKDAYS["ja"])[day.weekday()]
    return f"{day.year}年{day.month}月{day.day}日（{'週' if lang == 'zh-TW' else ''}{weekday}）"


def month_day(lang: str, day: datetime) -> str:
    """A short date: 10月27日 / 27 Oct."""
    if lang == "en-GB":
        return f"{day.day} {_EN_MONTHS[day.month - 1][:3]}"
    if lang == "ko":
        return f"{day.month}월 {day.day}일"
    return f"{day.month}月{day.day}日"


def updated(lang: str, day: datetime) -> str:
    return {"ko": "업데이트 {d}", "en-GB": "Updated {d}", "zh-TW": "更新於 {d}"}.get(lang, "更新 {d}").format(
        d=month_day(lang, day)
    )


def chosen(environ) -> str:
    """The visitor's language: the ``lang`` cookie, else the browser's first language we have, else Japanese."""
    cookie = SimpleCookie()
    try:
        cookie.load(environ.get("HTTP_COOKIE", ""))
    except Exception:  # a malformed cookie header is no choice
        cookie = SimpleCookie()
    value = cookie[COOKIE].value if COOKIE in cookie else ""
    return value if value in LANGS else from_browser(environ.get("HTTP_ACCEPT_LANGUAGE", ""))


def from_browser(header: str) -> str:
    """Accept-Language to one of LANGS: zh-* reads Traditional Chinese, en-* British English; a browser
    that names none of ours gets English (more likely read than Japanese), one that sends nothing Japanese."""
    if not header.strip():
        return DEFAULT
    ranked = []
    for number, part in enumerate(header.split(",")):
        tag, _, rest = part.strip().partition(";")
        try:
            weight = float(rest.strip()[2:]) if rest.strip().startswith("q=") else 1.0
        except ValueError:
            weight = 0.0
        ranked.append((-weight, number, tag.strip().lower()))
    for weight, _, tag in sorted(ranked):
        if weight >= 0:
            continue
        for prefix, lang in (("ja", "ja"), ("ko", "ko"), ("zh", "zh-TW"), ("en", "en-GB")):
            if tag == prefix or tag.startswith(prefix + "-"):
                return lang
    return "en-GB"


def asked(environ) -> tuple[str, str] | None:
    """``?lang=<code>`` on a GET: (the code, the query without it), or None."""
    if environ.get("REQUEST_METHOD", "GET") not in ("GET", "HEAD"):
        return None
    pairs = parse_qsl(environ.get("QUERY_STRING", ""), keep_blank_values=True)
    values = [value for key, value in pairs if key == COOKIE]
    if not values or values[-1] not in LANGS:
        return None
    return values[-1], urlencode([(key, value) for key, value in pairs if key != COOKIE])


def set_cookie(lang: str, secure: bool = False) -> tuple[str, str]:
    """The header that remembers ``lang`` for every site of this host."""
    return (
        "Set-Cookie",
        f"{COOKIE}={lang}; Path=/; Max-Age={COOKIE_SECONDS}; SameSite=Lax" + ("; Secure" if secure else ""),
    )


def menu(lang: str) -> str:
    """The language menu every site shows in its header: a <details> that needs no script
    (each choice is a link with ?lang=), the current language marked."""
    current = ' aria-current="true"'
    items = "".join(
        f'<li><a href="?{COOKIE}={code}" lang="{code}" hreflang="{code}"{current if code == lang else ""}>'
        f"{html.escape(NAMES[code])}</a></li>"
        for code in LANGS
    )
    label = html.escape(text(lang, "言語"))
    return (
        f'<details class="lang"><summary title="{label}" aria-label="{label}: {html.escape(NAMES[lang])}">'
        f'<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.6 3.8 5.6 3.8 9s-1.3 6.4-3.8 9c-2.5-2.6-3.8-5.6-3.8-9S9.5 5.6 12 3z"/></svg>'
        f"<span>{html.escape(NAMES[lang])}</span></summary><ul>{items}</ul></details>"
    )
