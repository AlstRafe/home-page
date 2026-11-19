"""The portal's own small pages (404, the owner's login) and what every page of it carries:
the light/dark script and button."""

from __future__ import annotations

import base64
import gzip
import hashlib
import html

from homepage import i18n, web

#: Light or dark: the device's setting until the visitor picks one with the button in the header
#: (automatic -> light -> dark), the same choice News Site and CoreLab read (localStorage "theme": the
#: sites share one origin). Inline in <head>, so the page is painted in it from the start; the CSP
#: allows exactly this script, by its hash. Phone toolbars (theme-color) follow a forced choice too.
#: It also closes the language menu on a click elsewhere or Escape (back on its button), as the sites do.
THEME_SCRIPT = (
    '(function(){var d=document,r=d.documentElement,o=["auto","light","dark"],c={light:"#edf0f2",dark:"#141822"};'
    'function get(){try{var t=localStorage.getItem("theme");return o.indexOf(t)>0?t:"auto"}'
    'catch(e){return r.getAttribute("data-theme")||"auto"}}'
    'function set(t){if(t==="auto")r.removeAttribute("data-theme");else r.setAttribute("data-theme",t);'
    "d.querySelectorAll('meta[name=\"theme-color\"]').forEach(function(m){"
    'm.content=c[t==="auto"?(m.media.indexOf("dark")<0?"light":"dark"):t]})}'
    "set(get());"
    'd.addEventListener("DOMContentLoaded",function(){var b=d.getElementById("theme");'
    'if(b)b.addEventListener("click",function(){var t=o[(o.indexOf(get())+1)%3];'
    'try{if(t==="auto")localStorage.removeItem("theme");else localStorage.setItem("theme",t)}catch(e){}set(t)});'
    'var l=d.querySelector("details.lang");if(l){d.addEventListener("click",function(e){if(!l.contains(e.target))l.open=false});'
    'l.addEventListener("keydown",function(e){if(e.key==="Escape"&&l.open){l.open=false;l.querySelector("summary").focus()}})}});'
    'addEventListener("storage",function(e){if(e.key==="theme"||e.key===null)set(get())})})();'
)
THEME_HASH = "'sha256-" + base64.b64encode(hashlib.sha256(THEME_SCRIPT.encode()).digest()).decode() + "'"
#: What the login page says after a try (homepage.owner.Owner.login), and its status.
SIGN_IN_PROBLEMS = {
    "wrong": ("401 Unauthorized", "パスワードが違います。"),
    "busy": ("429 Too Many Requests", "試した回数が多すぎます。少し待ってからもう一度どうぞ。"),
    "off": ("403 Forbidden", "ログインはまだ設定されていません。"),
}


def headers(content_type: str, length: int, cache: str, form: bool = False) -> list[tuple[str, str]]:
    """The portal's own answers: nothing but its own styles and pictures, and the theme script
    (by its hash). ``form``: the page sends a form to its own address (the owner's login, the cards' search)."""
    action = "'self'" if form else "'none'"
    return [
        ("Content-Type", content_type),
        ("Content-Length", str(length)),
        ("Cache-Control", cache),
        (
            "Content-Security-Policy",
            f"default-src 'none'; script-src {THEME_HASH}; style-src 'self'; img-src 'self'; "
            f"manifest-src 'self'; base-uri 'none'; form-action {action}; frame-ancestors 'none'",
        ),
        *web.SECURITY_HEADERS,
    ]


def send(
    start_response,
    content_type: str,
    body: bytes,
    cache: str,
    vary: bool = False,
    status: str = "200 OK",
    environ=None,
    extra=(),
    form: bool = False,
):
    """``vary``: the answer is in the visitor's language. ``environ``: gzipped when the browser takes it
    (a page that fits the first packets of a new connection arrives a round trip sooner)."""
    packed = environ is not None and len(body) >= web.GZIP_MIN and web.takes_gzip(environ)
    if packed:
        body = gzip.compress(body, compresslevel=6, mtime=0)
    answer = headers(content_type, len(body), cache, form)
    if packed:
        answer.append(("Content-Encoding", "gzip"))
    varies = [*(["Accept-Encoding"] if environ is not None else []), *(["Cookie", "Accept-Language"] if vary else [])]
    if varies:
        answer.append(("Vary", ", ".join(varies)))
    start_response(status, [*answer, *extra])
    return [body]


def theme_button(lang: str) -> str:
    """The header's light/dark button (THEME_SCRIPT makes it work): the words and icon of each
    state are all here, and the stylesheet shows the current one (<html data-theme>), so the
    page is right from its first paint."""
    icons = {
        "auto": '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/>',
        "light": '<circle cx="12" cy="12" r="4"/><path d="M12 2.5v2.5M12 19v2.5M4.6 4.6l1.8 1.8M17.6 17.6l1.8 1.8'
        'M2.5 12H5M19 12h2.5M4.6 19.4l1.8-1.8M17.6 6.4l1.8-1.8"/>',
        "dark": '<path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/>',
    }
    states = {"auto": "自動", "light": "オフ", "dark": "オン"}
    e = html.escape
    spans = "".join(
        f'<span class="t-{key}"><svg viewBox="0 0 24 24" aria-hidden="true">{icons[key]}</svg>'
        f'<span class="words">{e(i18n.text(lang, "ダークモード {state}", state=i18n.text(lang, state)))}</span></span>'
        for key, state in states.items()
    )
    title = e(i18n.text(lang, "ダークモード: 自動 → オフ → オン"))
    return f'<button type="button" class="theme" id="theme" title="{title}">{spans}</button>'


def small_page(lang: str, home: str, title: str, main: str) -> bytes:
    """A page of the portal besides the index (404, the owner's login): its look, the theme, no indexing.
    title and main are HTML already."""
    return (
        f'<!doctype html><html lang="{lang}"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
        f"<title>{title}</title><script>{THEME_SCRIPT}</script>"
        f'<link rel="icon" href="{html.escape(home)}favicon.svg" type="image/svg+xml">'
        f'<link rel="stylesheet" href="{html.escape(web.asset("portal.css", home))}"></head>'
        f'<body class="missing"><main>{main}</main></body></html>'
    ).encode()


def owner_page(environ, start_response, state: str, problem: str = "", extra=()):
    """持ち主のログイン (/owner under a public name, answered by homepage.server.Public): state
    "form" (the password), "in" (this device is the owner's: sign out) or "off" (no password set);
    problem: a SIGN_IN_PROBLEMS key, after a try."""
    lang = i18n.chosen(environ)

    def say(ja: str) -> str:
        return html.escape(i18n.text(lang, ja))

    status, message = SIGN_IN_PROBLEMS.get(problem, ("200 OK", ""))
    if state == "off":
        message = SIGN_IN_PROBLEMS["off"][1]
    alert = f'<p class="problem" role="alert">{say(message)}</p>' if message else ""
    if state == "in":
        lead = say("この端末は持ち主としてログインしています。公開中のページでも、すべての機能が使えます。")
        form = (
            '<form method="post" action="/owner"><input type="hidden" name="do" value="logout">'
            f'<button class="open" type="submit">{say("ログアウト")}</button></form>'
        )
    elif state == "form":
        lead = say("このサイトの持ち主だけが使うページです。ログインすると、この端末ではすべての機能が使えます。")
        form = (
            '<form method="post" action="/owner" class="signin">'
            '<input type="hidden" name="username" value="owner" autocomplete="username">'
            f'<label for="password">{say("パスワード")}</label>'
            '<input id="password" name="password" type="password" autocomplete="current-password" required autofocus>'
            f'<button class="open" type="submit">{say("ログイン")}</button></form>'
        )
    else:
        lead, form = "", ""
    lead = f'<p class="lead">{lead}</p>' if lead else ""
    heading = say("持ち主のログイン")
    back = f'<p class="go"><a class="back" href="/"><span class="arrow-back" aria-hidden="true">←</span>{say("サイト一覧")}</a></p>'
    body = small_page(lang, "/", heading, f"<h1>{heading}</h1>{lead}{alert}{form}{back}")
    return send(
        start_response,
        "text/html; charset=utf-8",
        body,
        "no-store",
        vary=True,
        status=status,
        environ=environ,
        extra=extra,
        form=True,
    )


def not_found(environ, start_response, site: str = ""):
    """404: a page in the visitor's language with the way back for browsers, two words for the rest.
    site: the name of the site the address is under (a link to its top comes first)."""
    if "text/html" not in environ.get("HTTP_ACCEPT", ""):
        return web.plain(start_response, "404 Not Found", b"Not Found")
    lang = i18n.chosen(environ)
    e = html.escape
    home = environ.get("homepage.home", environ.get("SCRIPT_NAME", "") + "/")
    arrow = '<span class="arrow-back" aria-hidden="true">←</span>'
    links = f'<a class="open" href="{e(home)}">{arrow}{e(i18n.text(lang, "サイト一覧"))}</a>'
    if site:
        top = e(environ.get("SCRIPT_NAME", "") + "/")
        links = (
            f'<a class="open" href="{top}">{e(i18n.text(lang, "{name} のトップへ", name=site))}</a>'
            f'<a class="back" href="{e(home)}">{arrow}{e(i18n.text(lang, "サイト一覧"))}</a>'
        )
    heading = e(i18n.text(lang, "ページが見つかりません"))
    main = (
        f'<p class="date">{e(i18n.text(lang, "エラー {status}", status=404))}</p><h1>{heading}</h1>'
        f'<p class="lead">{e(i18n.text(lang, "アドレスが変わったか、なくなった可能性があります。"))}</p>'
        f'<p class="go">{links}</p>'
    )
    return send(
        start_response,
        "text/html; charset=utf-8",
        small_page(lang, home, heading, main),
        "no-cache",
        vary=True,
        status="404 Not Found",
        environ=environ,
    )
