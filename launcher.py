"""Start this PC's sites (the Home Page server) on Windows: ``python launcher.py`` (or start.bat).

- prepares the server's own virtual environment (%LOCALAPPDATA%\\HomePage\\venvs\\<folder hash>) with
  waitress and what each Python site of sites.toml needs (its requirements.txt);
- registers the start-at-logon task (HomePage-Server-<folder hash>), so the sites come back after the
  PC restarts (``--no-logon`` removes it);
- runs homepage.server and keeps it running: exit 75 (new code, see homepage/server.py) starts it
  again at once, after updating the packages when a requirements file changed; a crash starts it
  again after a pause; ``Ctrl+C`` stops it.

``--background`` is how the logon task starts it: no window, the output goes to instance/server.log,
it waits for the network to come up, and does nothing when the server already answers.
Needs Python 3.11 or newer.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import tomllib
import venv
import webbrowser
from datetime import datetime
from pathlib import Path
from xml.etree import ElementTree

HOME = Path(__file__).resolve().parent
CONFIG = HOME / "sites.toml"
INSTANCE = HOME / "instance"
LOG_PATH = INSTANCE / "server.log"
LOG_MAX_BYTES = 1_000_000
TASK_RECORD = INSTANCE / "server-task.json"
FOLDER_ID = hashlib.sha256(str(HOME).casefold().encode("utf-8")).hexdigest()[:8]
TASK_NAME = f"HomePage-Server-{FOLDER_ID}"
RUNTIME = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "HomePage" / "venvs" / FOLDER_ID
PACKAGES = ("waitress>=3.0,<4",)
RESTART_EXIT_CODE = 75
QUICK_FAILURE_SECONDS = 30
NETWORK_WAIT_SECONDS = 300
NETWORK_WAIT_STEP = 10
CREATE_NO_WINDOW = 0x08000000


def runtime_python() -> Path:
    return RUNTIME / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def server_settings() -> tuple[int, list[Path]]:
    """sites.toml's port and the requirements files of its Python sites."""
    try:
        data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return 5000, []
    server = data.get("server") if isinstance(data.get("server"), dict) else {}
    port = server.get("port", 5000) if isinstance(server.get("port", 5000), int) else 5000
    sites = data.get("site") if isinstance(data.get("site"), list) else []
    files = [(CONFIG.parent / str(entry["python"])).resolve() / "requirements.txt"
             for entry in sites if isinstance(entry, dict) and isinstance(entry.get("python"), str)]
    return port, [file for file in files if file.is_file()]


def requirements_digest(files: list[Path]) -> str:
    digest = hashlib.sha256("\n".join(PACKAGES).encode())
    for file in files:
        try:
            digest.update(file.read_bytes())
        except OSError:
            pass
    return digest.hexdigest()


def prepare_runtime() -> Path:
    """The virtual environment with the packages installed (created on first use)."""
    python = runtime_python()
    if not python.is_file():
        print(f"サーバー用の仮想環境を作ります: {RUNTIME}", flush=True)
        venv.EnvBuilder(with_pip=True).create(RUNTIME)
    install_packages(python)
    return python


def install_packages(python: Path) -> None:
    """Install what the server and its Python sites need, unless that is already done for these files."""
    _, files = server_settings()
    digest = requirements_digest(files)
    marker = RUNTIME / "installed.txt"
    try:
        if marker.read_text(encoding="utf-8") == digest:
            return
    except OSError:
        pass
    command = [str(python), "-m", "pip", "install", "--disable-pip-version-check", "-q", *PACKAGES]
    for file in files:
        command += ["-r", str(file)]
    print("必要なパッケージを入れています...", flush=True)
    subprocess.run(command, check=True)
    marker.write_text(digest, encoding="utf-8")


# -- start at logon ----------------------------------------------------------------------------------

def logon_task_xml(command: Path, arguments: str, account: str) -> ElementTree.ElementTree:
    """Task Scheduler definition: start the sites (no window) 30 s after this user logs on."""
    namespace = "http://schemas.microsoft.com/windows/2004/02/mit/task"
    ElementTree.register_namespace("", namespace)

    def element(parent, name: str, text: str | None = None, **attributes):
        node = ElementTree.SubElement(parent, f"{{{namespace}}}{name}", attributes)
        if text is not None:
            node.text = text
        return node

    task = ElementTree.Element(f"{{{namespace}}}Task", {"version": "1.3"})
    element(element(task, "RegistrationInfo"), "Description",
            "Start this PC's sites (Home Page: the site list, News Site, CoreLab) in the background at logon.")
    trigger = element(element(task, "Triggers"), "LogonTrigger")
    element(trigger, "Enabled", "true")
    element(trigger, "UserId", account)
    element(trigger, "Delay", "PT30S")
    principal = element(element(task, "Principals"), "Principal", id="SitesUser")
    element(principal, "UserId", account)
    element(principal, "LogonType", "InteractiveToken")
    element(principal, "RunLevel", "LeastPrivilege")
    settings = element(task, "Settings")
    for name, value in (("MultipleInstancesPolicy", "IgnoreNew"), ("DisallowStartIfOnBatteries", "false"),
                        ("StopIfGoingOnBatteries", "false"), ("AllowHardTerminate", "true"),
                        ("StartWhenAvailable", "false"), ("RunOnlyIfNetworkAvailable", "false"),
                        ("WakeToRun", "false"), ("Enabled", "true"), ("Hidden", "false"),
                        ("ExecutionTimeLimit", "PT0S"), ("Priority", "7")):
        element(settings, name, value)
    execute = element(element(task, "Actions", Context="SitesUser"), "Exec")
    element(execute, "Command", str(command))
    element(execute, "Arguments", arguments)
    element(execute, "WorkingDirectory", str(HOME))
    return ElementTree.ElementTree(task)


def ensure_logon_task(enabled: bool) -> None:
    """Register (or with ``enabled`` False, remove) the start-at-logon task."""
    scheduler = shutil.which("schtasks.exe") or shutil.which("schtasks")
    if os.name != "nt" or not scheduler:
        return
    if not enabled:
        subprocess.run([scheduler, "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True, errors="replace")
        TASK_RECORD.unlink(missing_ok=True)
        print(f"ログオン時の自動起動を解除しました（タスク {TASK_NAME}）。")
        return
    # The task runs the launcher with the Python it was set up with (windowless pythonw).
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    user, domain = os.environ.get("USERNAME", ""), os.environ.get("USERDOMAIN", "")
    account = f"{domain}\\{user}" if domain else user
    if not pythonw.is_file() or not account:
        print("警告: pythonw.exe が見つからないため、ログオン時の自動起動を登録できませんでした。")
        return
    arguments = f'"{HOME / "launcher.py"}" --background'
    record = {"task_name": TASK_NAME, "command": str(pythonw), "arguments": arguments}
    try:
        previous = json.loads(TASK_RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        previous = {}
    query = subprocess.run([scheduler, "/Query", "/TN", TASK_NAME], capture_output=True, text=True, errors="replace")
    if query.returncode == 0 and previous == record:
        return
    INSTANCE.mkdir(parents=True, exist_ok=True)
    definition = INSTANCE / f"server-task-{os.getpid()}.xml"
    try:
        logon_task_xml(pythonw, arguments, account).write(definition, encoding="utf-16", xml_declaration=True)
        created = subprocess.run([scheduler, "/Create", "/TN", TASK_NAME, "/XML", str(definition), "/F"],
                                 capture_output=True, text=True, errors="replace")
    finally:
        definition.unlink(missing_ok=True)
    if created.returncode:
        print(f"警告: ログオン時の自動起動を登録できませんでした: {(created.stderr or created.stdout).strip()}")
        return
    TASK_RECORD.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"PCにログオンすると自動で起動するよう登録しました（タスク {TASK_NAME}）。")


# -- running ----------------------------------------------------------------------------------------------

def answering(port: int) -> bool:
    """Whether something answers on this PC at ``port`` (the server is running already)."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except OSError:
        return False


def network_up() -> bool:
    """Tailscale's or the LAN's address is there (loopback alone means: not up yet)."""
    sys.path.insert(0, str(HOME))
    from homepage.server import Settings, addresses
    return len(addresses(Settings())) > 1


def wait_for_network(limit: float = NETWORK_WAIT_SECONDS) -> None:
    deadline = time.monotonic() + limit
    while not network_up():
        if time.monotonic() >= deadline:
            print(f"ネットワークの準備を {int(limit)} 秒待ちましたが、このまま起動します。", flush=True)
            return
        print("ネットワークの準備を待っています。", flush=True)
        time.sleep(NETWORK_WAIT_STEP)


def supervise(python: Path, background: bool) -> int:
    """Run the server until it stops on its own (Ctrl+C); start it again after a restart or a crash."""
    env = dict(os.environ, HOME_SUPERVISED="1", PYTHONIOENCODING="utf-8")
    extra = {"creationflags": CREATE_NO_WINDOW} if background and os.name == "nt" else {}
    if background:
        extra.update(stdout=sys.stdout, stderr=subprocess.STDOUT)
    quick_failures = 0
    while True:
        started = time.monotonic()
        code = subprocess.run([str(python), "-m", "homepage.server"], cwd=HOME, env=env, **extra).returncode
        if code == 0:
            return 0
        if code == RESTART_EXIT_CODE:
            quick_failures = 0
            try:
                install_packages(python)
            except (OSError, subprocess.CalledProcessError) as error:
                print(f"警告: パッケージを更新できませんでした（{error}）。今の環境で再起動します。", flush=True)
            print("新しいコードで再起動します...", flush=True)
            continue
        quick_failures = quick_failures + 1 if time.monotonic() - started < QUICK_FAILURE_SECONDS else 1
        delay = min(300, 10 * quick_failures)
        print(f"サーバーが終了しました（コード {code}）。{delay} 秒後に起動し直します（Ctrl+C で終了）。", flush=True)
        time.sleep(delay)


def open_log():
    INSTANCE.mkdir(parents=True, exist_ok=True)
    try:
        if LOG_PATH.stat().st_size > LOG_MAX_BYTES:
            LOG_PATH.replace(LOG_PATH.with_suffix(".old.log"))
    except OSError:
        pass
    log = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    log.write(f"--- {datetime.now().astimezone():%Y-%m-%d %H:%M:%S} logon start ---\n")
    return log


def python_site_servers() -> list[int]:
    """Processes that serve a Python site of sites.toml on their own (its launcher.py or app.py,
    never its collector): what ``--take-over`` stops. Windows only."""
    try:
        data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return []
    folders = [str((CONFIG.parent / entry["python"]).resolve()).casefold() for entry in data.get("site", [])
               if isinstance(entry, dict) and isinstance(entry.get("python"), str)]
    if os.name != "nt" or not folders:
        return []
    listing = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-CimInstance Win32_Process | ForEach-Object { \"$($_.ProcessId)`t$($_.CommandLine)\" }"],
                             capture_output=True, text=True, errors="replace", creationflags=CREATE_NO_WINDOW).stdout
    found = []
    for line in listing.splitlines():
        pid, _, command = line.partition("\t")
        command = command.casefold()
        if pid.isdecimal() and any(f"{folder}\\{name}" in command for folder in folders for name in ("launcher.py", "app.py")):
            found.append(int(pid))
    return found


def take_over(port: int) -> int:
    """Make this the server of the PC's sites from now on: register the start at logon, stop the
    Python sites' own servers (News Site's launcher and app.py), and start this one in the background."""
    prepare_runtime()
    ensure_logon_task(True)
    if not TASK_RECORD.is_file():
        print("ログオン時の自動起動を登録できなかったので、切り替えを中止しました。", file=sys.stderr)
        return 1
    stopped = python_site_servers()
    for pid in stopped:  # the launchers first are among them: none of them starts the app again
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, text=True, errors="replace")
    if stopped:
        print(f"これまでのサーバーを止めました（{len(stopped)} 個のプロセス）。")
    deadline = time.monotonic() + 20
    while answering(port) and time.monotonic() < deadline:
        time.sleep(1)
    if answering(port):
        print(f"ポート {port} がまだ使われています。使っているプログラムを止めてからやり直してください。", file=sys.stderr)
        return 1
    scheduler = shutil.which("schtasks.exe") or "schtasks"
    subprocess.run([scheduler, "/Run", "/TN", TASK_NAME], capture_output=True, text=True, errors="replace")
    print("Home Page のサーバーを起動しています...", flush=True)
    deadline = time.monotonic() + 180
    while not answering(port):
        if time.monotonic() > deadline:
            print(f"起動を確認できませんでした。{LOG_PATH} を見てください。", file=sys.stderr)
            return 1
        time.sleep(2)
    print(f"切り替えました。サイト一覧: http://127.0.0.1:{port}/ （記録: {LOG_PATH}）")
    webbrowser.open(f"http://127.0.0.1:{port}/")
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if sys.version_info < (3, 11):
        print("Python 3.11 以上が必要です。", file=sys.stderr)
        return 1
    port, _ = server_settings()
    if "--no-logon" in argv:
        ensure_logon_task(False)
        return 0
    if "--take-over" in argv:
        return take_over(port)
    if "--background" in argv:
        sys.stdout = sys.stderr = open_log()
        if answering(port):
            print("すでに起動しています。")
            return 0
        wait_for_network()
        return supervise(prepare_runtime(), background=True)
    if answering(port):
        print(f"ポート {port} ではもうサーバーが動いています。サイト一覧を開きます。")
        webbrowser.open(f"http://127.0.0.1:{port}/")
        return 0
    python = prepare_runtime()
    ensure_logon_task(True)
    print(f"サイト一覧: http://127.0.0.1:{port}/ （このウィンドウを閉じるか Ctrl+C で終了）", flush=True)
    return supervise(python, background=False)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(0)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"起動できませんでした: {error}", file=sys.stderr)
        raise SystemExit(1)
