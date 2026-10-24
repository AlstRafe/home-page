"""News Site as a Python site of this server, for News Site code from before it had ``newsreader.hosting``
(the News Site patch home-page-server-20261024 adds it, and the server uses that once it is there).

It does what that entry does, with what the older code already has. Delete this file, and its line in
server.COMPAT, once News Site's work/app has newsreader/hosting.py.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def news_site(mount: str, host: dict) -> dict:
    from newsreader import branding, paths, portal
    from newsreader.services.preset import import_relay_token
    from newsreader.services.settings import save_start_at_logon
    from newsreader.web import create_app
    from newsreader.web.run import _record_web_status

    # News Site answers only to the names it trusts: this server's addresses and names too.
    os.environ["NEWS_ALLOWED_HOSTS"] = ",".join(filter(None, [os.environ.get("NEWS_ALLOWED_HOSTS", ""), *host["names"]]))
    import_relay_token()
    app = create_app(mount=mount)
    _record_web_status(app, host["addresses"][0], host["port"], tuple(host["addresses"][1:]))
    # This server is the one started at logon now: News Site's own start would race it for the port.
    save_start_at_logon(False)
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("newsreader_launcher", paths.PROJECT_ROOT / "launcher.py")
        launcher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(launcher)
        launcher.ensure_logon_task(Path(sys.executable), False)
    except Exception as exc:  # noqa: BLE001 - the site is served either way
        print(f"News Site のログオン時の自動起動を外せませんでした: {exc!r}", flush=True)
    return {"app": app, "name": branding.APP_NAME, "subtitle": branding.APP_TAGLINE,
            "preview": lambda: portal.news_now(app), "disallow": ("/api/",), "legacy": ("/relay/",),
            "version": paths.deployed_version}
