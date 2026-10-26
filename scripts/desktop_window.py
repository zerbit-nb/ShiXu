"""Windows window for the local app, with tray and graceful backend exit."""
import ctypes
from ctypes import wintypes
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import threading

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.services.desktop import server_state

URL = 'http://127.0.0.1:8000'
ICON_PATH = ROOT / 'assets' / 'brand' / 'windows' / 'shixu.ico'



def instance_name(root):
    digest = hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode()).hexdigest()
    return r'Local\CampusFlowWindow-' + digest


class WindowInstance:
    """Kernel handles disappear on process exit, so no stale PID file is needed."""
    def __init__(self, root):
        self.kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        definitions = {
            'CreateMutexW': ([ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            'CreateEventW': ([ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], wintypes.HANDLE),
            'SetEvent': ([wintypes.HANDLE], wintypes.BOOL),
            'WaitForSingleObject': ([wintypes.HANDLE, wintypes.DWORD], wintypes.DWORD),
            'CloseHandle': ([wintypes.HANDLE], wintypes.BOOL),
        }
        for name, (args, result) in definitions.items():
            function = getattr(self.kernel, name)
            function.argtypes, function.restype = args, result
        name = instance_name(root)
        self.mutex = self.kernel.CreateMutexW(None, False, name)
        if not self.mutex:
            raise ctypes.WinError(ctypes.get_last_error())
        self.primary = ctypes.get_last_error() != 183
        self.event = self.kernel.CreateEventW(None, False, False, name + '-activate')
        if not self.event:
            self.kernel.CloseHandle(self.mutex)
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.primary:
            self.kernel.SetEvent(self.event)

    def wait(self, milliseconds):
        result = self.kernel.WaitForSingleObject(self.event, milliseconds)
        if result == 0xFFFFFFFF:
            raise ctypes.WinError(ctypes.get_last_error())
        return result == 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.kernel.CloseHandle(self.event)
        self.kernel.CloseHandle(self.mutex)


def prepare_backend(root):
    runtime = root / 'runtime'
    runtime.mkdir(exist_ok=True)
    with (runtime / 'desktop-window.log').open('ab') as log:
        try:
            result = subprocess.run(
                [sys.executable, '-X', 'utf8', str(root / 'scripts/desktop.py'), '--no-browser'],
                cwd=root, stdin=subprocess.DEVNULL, stdout=log, stderr=log, timeout=75,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError('启动检查超时。请使用 StartCampusFlow.cmd 检查后台状态后重试。') from None
    if result.returncode:
        raise RuntimeError('拾序启动失败。请使用 StartCampusFlow.cmd 查看提示；日志位于 runtime/desktop-window.log。')
    with httpx.Client(trust_env=False, timeout=3) as client:
        if server_state(root, URL, client) != 'ready':
            raise RuntimeError('无法确认 8000 端口是当前项目的拾序，请检查端口占用后重试。')


def open_window(view, instance=None):
    from scripts.desktop_tray import TrayController, WindowsTray
    from app.services.desktop_control import BackendStopper
    view.settings['ALLOW_DOWNLOADS'] = False
    view.settings['ALLOW_FILE_URLS'] = False
    view.settings['REMOTE_DEBUGGING_PORT'] = None
    window = view.create_window('拾序', URL, width=1280, height=860,
                                min_size=(800, 600), background_color='#f6f5f2', confirm_close=False)
    tray = WindowsTray(window)
    controller = TrayController(window, tray, BackendStopper(ROOT))
    stopped = threading.Event()
    worker = None

    def closing():
        try:
            return controller.closing()
        except Exception:
            # An event exception alone does NOT cancel pywebview's close.
            show_error('无法收起到托盘。窗口已保留，请重试。')
            return False

    def before_show():
        try:
            tray.install(controller)
        except Exception:
            # Keep a native exit menu available if tray initialization fails.
            from System.Windows.Forms import MenuStrip, ToolStripMenuItem
            menu = MenuStrip(); item = ToolStripMenuItem('退出 拾序')
            item.Click += lambda *_: controller.request_exit()
            menu.Items.Add(item); window.native.Controls.Add(menu)
            window.native.MainMenuStrip = menu
            show_error('托盘不可用，窗口将保持打开。可用顶部菜单退出 拾序。')

    def activate():
        while not stopped.is_set():
            if instance.wait(250) and not stopped.is_set():
                tray.restore()

    def shown():
        nonlocal worker
        if instance is not None and worker is None:
            worker = threading.Thread(target=activate, daemon=True)
            worker.start()

    window.events.before_show += before_show
    window.events.shown += shown
    window.events.closing += closing
    window.events.closed += lambda: stopped.set()
    try:
        view.start(gui='edgechromium', debug=False, private_mode=True, icon=str(ICON_PATH))
    finally:
        stopped.set()
        if worker is not None:
            worker.join(timeout=2)
        tray.dispose()


def show_error(message):
    ctypes.windll.user32.MessageBoxW(None, message, '拾序', 0x10)


def main():
    if os.name != 'nt':
        raise RuntimeError('桌面窗口目前仅支持 Windows。')
    try:
        import webview
    except ImportError:
        show_error(r'缺少桌面依赖。请在项目目录运行 .venv\Scripts\python.exe -m pip install -r requirements-desktop.txt，或使用 StartCampusFlow.cmd。')
        return 1
    try:
        with WindowInstance(ROOT) as instance:
            if not instance.primary:
                return 0
            prepare_backend(ROOT)
            open_window(webview, instance)
        return 0
    except RuntimeError as exc:
        show_error(str(exc))
    except Exception:
        show_error('桌面窗口无法启动。请确认 Microsoft Edge WebView2 Runtime 已安装；可先用 StartCampusFlow.cmd 打开浏览器版本。')
    return 1


if __name__ == '__main__':
    sys.exit(main())
