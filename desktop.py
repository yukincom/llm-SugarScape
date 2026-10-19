"""Mac application window hosting the existing SugarScape screen and engine."""

import base64
import os
from pathlib import Path
import plistlib
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

ROOT = (Path(os.environ["RESOURCEPATH"]) if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent)
# py2app removes Resources from sys.path. Native callbacks also need the same
# bundled application modules that Streamlit loads from this directory.
if getattr(sys, "frozen", False):
    sys.path.insert(0, str(ROOT))
APP_NAME = "LLM SugarScape"
JAPANESE = {
    "global.quitConfirmation": "アプリを終了しますか？", "global.ok": "OK",
    "global.quit": "終了", "global.cancel": "キャンセル", "global.saveFile": "ファイルを保存",
    "cocoa.menu.about": "このアプリについて", "cocoa.menu.services": "サービス",
    "cocoa.menu.view": "表示", "cocoa.menu.edit": "編集", "cocoa.menu.hide": "隠す",
    "cocoa.menu.hideOthers": "ほかを隠す", "cocoa.menu.showAll": "すべてを表示",
    "cocoa.menu.quit": "終了", "cocoa.menu.fullscreen": "フルスクリーンにする",
    "cocoa.menu.cut": "切り取り", "cocoa.menu.copy": "コピー",
    "cocoa.menu.paste": "ペースト", "cocoa.menu.selectAll": "すべてを選択",
}


def data_directory():
    override = os.environ.get("SUGARSCAPE_DATA_DIR")
    return (Path(override).expanduser() if override else
            Path.home() / "Library" / "Application Support" / "LLM SugarScape").resolve()


def application_directory():
    # Resources is inside <folder>/<app>.app/Contents/Resources. Experiment
    # files belong beside the app, never inside its signed bundle.
    return (ROOT.parents[2] if getattr(sys, "frozen", False) else ROOT).resolve()


def output_directory():
    override = os.environ.get("SUGARSCAPE_OUTPUT_DIR")
    if override:
        return Path(override).expanduser().resolve()
    return application_directory() / "outputs"


def select_output_directory(window, current):
    """Let the user select or create a folder in the native Mac dialog."""
    from webview import FileDialog

    directory = Path(current).expanduser().resolve()
    while not directory.is_dir() and directory != directory.parent:
        directory = directory.parent
    selected = window.create_file_dialog(FileDialog.FOLDER, directory=str(directory), allow_multiple=False)
    if not selected:
        return None
    destination = Path(selected[0]).resolve()
    if not destination.is_dir():
        raise ValueError("The selected folder no longer exists")
    return str(destination)


def open_experiment_directory(directory, run_id):
    """Open the recorded folder itself in Finder, including after a rename."""
    from run_data import locate_run_directory

    destination = locate_run_directory({"output_dir": directory, "run_id": run_id})
    if not destination.is_dir():
        raise ValueError("The experiment folder no longer exists")
    subprocess.run(["/usr/bin/open", "-a", "Finder", str(destination)], check=True)


def server_command(port, route):
    if getattr(sys, "frozen", False):
        contents = ROOT.parent
        with (contents / "Info.plist").open("rb") as handle:
            executable = plistlib.load(handle)["CFBundleExecutable"]
        command = [str(contents / "MacOS" / executable)]
    else:
        command = [sys.executable, str(ROOT / "desktop.py")]
    return [*command, "--serve-window", str(port), route, str(os.getpid())]


def serve_window(port, route, parent_pid):
    """Run the usual Streamlit bootstrap in our own child, never a shared server."""
    from AppKit import NSApplication, NSApplicationActivationPolicyProhibited
    from streamlit.web import bootstrap

    NSApplication.sharedApplication().setActivationPolicy_(NSApplicationActivationPolicyProhibited)
    def watch_parent():
        while os.getppid() == parent_pid:
            time.sleep(1)
        # Only this owned child is stopped if the window process disappears.
        os.kill(os.getpid(), signal.SIGTERM)

    threading.Thread(target=watch_parent, daemon=True).start()
    options = {
        "global.developmentMode": False,
        "server.address": "127.0.0.1", "server.port": port,
        "server.baseUrlPath": route, "server.headless": True,
        "server.fileWatcherType": "none", "server.runOnSave": False,
        "browser.gatherUsageStats": False, "logger.hideWelcomeMessage": True,
        "client.toolbarMode": "minimal", "server.cookieSecret": uuid4().hex,
    }
    bootstrap.load_config_options(options)
    bootstrap.run(str(ROOT / "main.py"), False, [], options)


class WindowServer:
    """Lifecycle for one app instance; no fixed port and no process discovery."""

    def __init__(self, directory=None):
        self.directory = Path(directory) if directory else data_directory()
        self.process = None
        self.log = None
        self.closed = threading.Event()
        self.lock = threading.Lock()
        self.url = None

    def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        cache = self.directory / "cache"
        cache.mkdir(exist_ok=True)
        logs = self.directory / "logs"
        logs.mkdir(exist_ok=True)
        self.log_path = logs / f"window-{time.strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:8]}.log"
        route = uuid4().hex
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            port = reservation.getsockname()[1]
        environment = os.environ.copy()
        environment["MPLCONFIGDIR"] = str(cache / "matplotlib")
        environment["SUGARSCAPE_OUTPUT_DIR"] = str(output_directory())
        environment["SUGARSCAPE_DESKTOP"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        with self.lock:
            if self.closed.is_set():
                raise RuntimeError("Window closed")
            self.log = self.log_path.open("ab")
            self.process = subprocess.Popen(server_command(port, route), cwd=self.directory,
                                            env=environment, stdin=subprocess.DEVNULL,
                                            stdout=self.log, stderr=subprocess.STDOUT)
        self.url = f"http://127.0.0.1:{port}/{route}/"
        # The per-instance route prevents accidentally attaching to another
        # program if it takes the port between reservation and child startup.
        deadline = time.monotonic() + 60
        while not self.closed.is_set() and time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise RuntimeError("Window server exited")
            try:
                with urlopen(self.url + "_stcore/health", timeout=1) as response:
                    if response.status == 200 and response.read(32).strip() == b"ok":
                        return self.url
            except (OSError, URLError):
                pass
            self.closed.wait(0.15)
        raise RuntimeError("Window server did not become ready")

    def close(self):
        self.closed.set()
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=5)
            if self.log is not None:
                self.log.close()
                self.log = None


LOGO_DATA = base64.b64encode((ROOT / "assets/branding/llm-sugar-scape-logo.png").read_bytes()).decode("ascii")
LOADING = """<!doctype html><html lang="ja"><meta charset="utf-8">
<style>body{font:18px -apple-system,sans-serif;background:#f7f8f3;color:#24372c;
display:grid;place-items:center;height:95vh;margin:0}main{max-width:560px;padding:40px}
img{display:block;width:520px;max-width:100%;height:auto}p{line-height:1.8;color:#536359}</style>
<main><img src="data:image/png;base64,LOGO_DATA" alt="LLM Sugar Scape"><p>小さな世界を準備しています…</p>
<p>このウインドウで、そのまま実験を始められます。</p></main></html>""".replace("LOGO_DATA", LOGO_DATA)


def launch():
    import webview

    server = WindowServer()
    window = webview.create_window(APP_NAME, html=LOADING, width=1280, height=900,
                                   min_size=(980, 680), background_color="#f7f8f3")
    window.events.closed += server.close
    dialog_lock = threading.Lock()
    folder_chosen = False

    def choose_output_directory(current):
        nonlocal folder_chosen
        if server.closed.is_set() or not dialog_lock.acquire(blocking=False):
            return None
        try:
            initial = current if folder_chosen else str(application_directory())
            selected = select_output_directory(window, initial)
            if selected:
                folder_chosen = True
            return selected
        finally:
            dialog_lock.release()

    window.expose(choose_output_directory, open_experiment_directory)

    def load():
        try:
            url = server.start()
            if not server.closed.is_set():
                window.load_url(url)
        except Exception:
            if not server.closed.is_set():
                import html
                path = html.escape(str(getattr(server, "log_path", server.directory)))
                window.load_html(LOADING.replace(
                    "小さな世界を準備しています…", "起動できませんでした。アプリを閉じて、もう一度開いてください。"
                ).replace("このウインドウで、そのまま実験を始められます。", f"起動記録: {path}"))
            server.close()

    try:
        webview.start(load, gui="cocoa", private_mode=True, localization=JAPANESE)
    finally:
        server.close()


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--serve-window":
        try:
            serve_window(int(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
        except Exception:
            import traceback
            traceback.print_exc()
            sys.stderr.flush()
            # py2app would otherwise open a separate launch-error dialog for
            # this hidden child. The visible window reports startup failure.
            os._exit(1)
    else:
        launch()
