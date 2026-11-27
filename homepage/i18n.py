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
    "最近の変更": {"ko": "최근 변경", "en-GB": "Recent changes", "zh-TW": "最近的更動"},
    "新着": {"ko": "새 소식", "en-GB": "Latest", "zh-TW": "最新"},
    "{name} を開く": {"ko": "{name} 열기", "en-GB": "Open {name}", "zh-TW": "開啟 {name}"},
    "非公開（持ち主だけ）": {
        "ko": "비공개 (소유자만)",
        "en-GB": "Private (owner only)",
        "zh-TW": "未公開（僅限擁有者）",
    },
    "検索": {"ko": "검색", "en-GB": "Search", "zh-TW": "搜尋"},
    "{name} の中を検索": {"ko": "{name}에서 검색", "en-GB": "Search {name}", "zh-TW": "在 {name} 中搜尋"},
    "よく使うページ": {"ko": "자주 쓰는 페이지", "en-GB": "Popular pages", "zh-TW": "常用頁面"},
    "サイトへ移動": {"ko": "사이트로 이동", "en-GB": "Go to a site", "zh-TW": "前往網站"},
    "検索するサイト": {"ko": "검색할 사이트", "en-GB": "Site to search", "zh-TW": "要搜尋的網站"},
    "サイトを選んで検索": {"ko": "사이트를 골라 검색", "en-GB": "Pick a site, then search", "zh-TW": "選擇網站後搜尋"},
    "検索する言葉": {"ko": "검색어", "en-GB": "Search words", "zh-TW": "搜尋字詞"},
    "サイト {count} 件": {"ko": "사이트 {count}개", "en-GB": "{count} sites", "zh-TW": "共 {count} 個網站"},
    "エラー {status}": {"ko": "오류 {status}", "en-GB": "Error {status}", "zh-TW": "錯誤 {status}"},
    "ページが見つかりません": {"ko": "페이지를 찾을 수 없습니다", "en-GB": "Page not found", "zh-TW": "找不到這個頁面"},
    "アドレスが変わったか、なくなった可能性があります。": {
        "ko": "주소가 바뀌었거나 페이지가 없어졌을 수 있습니다.",
        "en-GB": "The address may have changed, or the page may no longer exist.",
        "zh-TW": "網址可能已變更，或頁面已不存在。",
    },
    "{name} のトップへ": {"ko": "{name} 첫 화면으로", "en-GB": "{name} home", "zh-TW": "前往 {name} 首頁"},
    # 持ち主向けの欄（一覧の下、訪問者には出ない）
    "持ち主向け": {"ko": "소유자용", "en-GB": "For the owner", "zh-TW": "擁有者專用"},
    "持ち主としてログイン中です（ログアウト）": {
        "ko": "소유자로 로그인되어 있습니다 (로그아웃)",
        "en-GB": "Signed in as the owner (sign out)",
        "zh-TW": "已用擁有者身分登入（登出）",
    },
    "サイトを足すには sites.toml に [[site]] を1つ書き足します（VM へは master に push して約 1 分）。": {
        "ko": "사이트를 추가하려면 sites.toml에 [[site]]를 하나 덧붙입니다 (VM에는 master에 push하면 약 1분).",
        "en-GB": "To add a site, add one [[site]] to sites.toml (on the VM: push to master, about a minute).",
        "zh-TW": "要新增網站，請在 sites.toml 加上一個 [[site]]（VM 上：推送到 master 後約 1 分鐘）。",
    },
    "この欄は訪問者には表示されません。": {
        "ko": "이 칸은 방문자에게는 보이지 않습니다.",
        "en-GB": "Visitors never see this box.",
        "zh-TW": "訪客看不到這個欄位。",
    },
    "動いている版": {"ko": "실행 중인 버전", "en-GB": "Running versions", "zh-TW": "執行中的版本"},
    "起動 {when}": {"ko": "시작 {when}", "en-GB": "Started {when}", "zh-TW": "啟動於 {when}"},
    "新しいコードで再起動待ち": {
        "ko": "새 코드로 재시작 대기 중",
        "en-GB": "Restart into new code pending",
        "zh-TW": "等待以新程式碼重新啟動",
    },
    "負荷 {load}": {"ko": "부하 {load}", "en-GB": "Load {load}", "zh-TW": "負載 {load}"},
    "メモリ {used} / {total}": {
        "ko": "메모리 {used} / {total}",
        "en-GB": "Memory {used} / {total}",
        "zh-TW": "記憶體 {used} / {total}",
    },
    "スワップ {used} / {total}": {
        "ko": "스왑 {used} / {total}",
        "en-GB": "Swap {used} / {total}",
        "zh-TW": "交換空間 {used} / {total}",
    },
    "このサーバー {size}": {"ko": "이 서버 {size}", "en-GB": "This server {size}", "zh-TW": "本伺服器 {size}"},
    "ディスクの空き {size}": {"ko": "디스크 여유 {size}", "en-GB": "Disk free {size}", "zh-TW": "磁碟剩餘 {size}"},
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


def month_day(lang: str, day: datetime) -> str:
    """A short date: 10月27日 / 27 Oct."""
    if lang == "en-GB":
        return f"{day.day} {_EN_MONTHS[day.month - 1][:3]}"
    if lang == "ko":
        return f"{day.month}월 {day.day}일"
    return f"{day.month}月{day.day}日"


def moment(lang: str, when: datetime) -> str:
    """A day and time: 11月19日 12:34 / 19 Nov 12:34 (the time where ``when`` is: JST on the portal)."""
    return f"{month_day(lang, when)} {when:%H:%M}"


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
