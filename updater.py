"""
自動アップデート処理 (標準ライブラリのみ)

流れ:
  1. 本体(main.py)が最新Releaseの zip をダウンロード → SHA256を検証 → exeを取り出す
  2. 実行中のexe自身を一時フォルダにコピーし、「--apply-update」モードで起動して本体は終了する
  3. コピーされた側(run_apply)が本体の終了を待ち、exeを差し替え、新しいexeを再起動する
     (実行中のexeは上書き・削除できないため、この二段構えにしている)
"""
import ctypes
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile

REPO_PREFIX = "https://github.com/yamatyann/ExcelToProject/releases/download/"
EXE_NAME = "ExcelToProject.exe"
ASSET_RE = re.compile(r"^ExcelToProject_v[\d.]+\.zip$")  # 自動更新用 (exeのみ入ったzip)

DETACHED = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
NO_WINDOW = 0x08000000


class UpdateError(Exception):
    pass


def app_dir():
    """ exe (またはスクリプト) があるフォルダ """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def can_self_update():
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def pick_asset(release):
    """ Releaseの情報から、自動更新用zipの (ダウンロードURL, SHA256) を選ぶ。無ければ (None, None) """
    for asset in release.get("assets", []):
        url = asset.get("browser_download_url", "")
        digest = asset.get("digest") or ""
        if ASSET_RE.match(asset.get("name", "")) and url.startswith(REPO_PREFIX) and digest.startswith("sha256:"):
            return url, digest.split(":", 1)[1].lower()
    return None, None


def is_dir_writable(path):
    try:
        with tempfile.TemporaryFile(dir=path):
            return True
    except OSError:
        return False


def download_and_extract(url, sha256, work_dir, progress_cb=None, is_cancelled=None, allowed_prefix=REPO_PREFIX):
    """ zipをダウンロードして検証し、展開したexeのパスを返す """
    if not url.startswith(allowed_prefix):
        raise UpdateError("ダウンロード元が想定外のため中止しました。")
    os.makedirs(work_dir, exist_ok=True)
    zip_path = os.path.join(work_dir, "update.zip")

    req = urllib.request.Request(url, headers={"User-Agent": "ExcelToProject-Updater"})
    h = hashlib.sha256()
    try:
        with urllib.request.urlopen(req, timeout=30) as res, open(zip_path, "wb") as f:
            total = int(res.headers.get("Content-Length") or 0)
            done = 0
            while True:
                if is_cancelled and is_cancelled():
                    raise UpdateError("キャンセルされました。")
                chunk = res.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress_cb:
                    progress_cb(done, total)
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(f"ダウンロードに失敗しました。\n{e}")

    if h.hexdigest().lower() != sha256.lower():
        raise UpdateError("ダウンロードしたファイルの検証(SHA256)に失敗しました。更新を中止します。")

    new_dir = os.path.join(work_dir, "new")
    os.makedirs(new_dir, exist_ok=True)
    new_exe = os.path.join(new_dir, EXE_NAME)
    try:
        with zipfile.ZipFile(zip_path) as z:
            member = next((n for n in z.namelist() if os.path.basename(n) == EXE_NAME), None)
            if member is None:
                raise UpdateError(f"zipの中に {EXE_NAME} が見つかりません。")
            # 展開先は自分で決める (zip内のパスは使わない)
            with z.open(member) as src, open(new_exe, "wb") as dst:
                shutil.copyfileobj(src, dst)
    except zipfile.BadZipFile:
        raise UpdateError("zipファイルが壊れています。")

    with open(new_exe, "rb") as f:
        head = f.read(2)
    if head != b"MZ" or os.path.getsize(new_exe) < 1024 * 1024:
        raise UpdateError("取り出したファイルが実行ファイルとして不正です。")
    os.remove(zip_path)
    return new_exe


def _reset_env():
    env = dict(os.environ)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"  # 親のPyInstaller展開先を子が使い回さないようにする
    return env


def start_apply(new_exe, work_dir, keep_bak, need_admin):
    """ 更新用プロセスを起動する。起動できたらTrue (呼び出し側はその後アプリを終了する) """
    target = sys.executable
    updater_exe = os.path.join(work_dir, "updater.exe")
    shutil.copy2(target, updater_exe)
    args = ["--apply-update", str(os.getpid()), target, new_exe, "bak" if keep_bak else "delete", work_dir]
    if need_admin:
        args.append("--elevated")
        os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        ret = ctypes.windll.shell32.ShellExecuteW(None, "runas", updater_exe, subprocess.list2cmdline(args), None, 0)
        return ret > 32
    subprocess.Popen([updater_exe] + args, env=_reset_env(), creationflags=DETACHED, close_fds=True)
    return True


# ---------------------------------------------------------
# ここから下は「--apply-update」で起動された更新用プロセスの処理
# ---------------------------------------------------------
def _message(text, title="ExcelToProject アップデート"):
    try:
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10 | 0x40000)
    except Exception:
        pass


def _wait_for_exit(pid, timeout=60):
    SYNCHRONIZE = 0x00100000
    handle = ctypes.windll.kernel32.OpenProcess(SYNCHRONIZE, False, pid)
    if handle:
        ctypes.windll.kernel32.WaitForSingleObject(handle, timeout * 1000)
        ctypes.windll.kernel32.CloseHandle(handle)


def run_apply(argv, relaunch=True):
    """ argv: [pid, 旧exe, 新exe, "bak"|"delete", 作業フォルダ, (--elevated)] """
    pid, target, new_exe, mode, work_dir = int(argv[0]), argv[1], argv[2], argv[3], argv[4]
    elevated = "--elevated" in argv
    bak = target + ".bak"

    _wait_for_exit(pid)

    moved = False
    for _ in range(60):  # 本体が完全に終了するまで最大30秒リトライ
        try:
            if os.path.exists(bak):
                os.remove(bak)
            os.replace(target, bak)
            moved = True
            break
        except OSError:
            time.sleep(0.5)
    if not moved:
        _message("実行中のExcelToProject.exeを置き換えられませんでした。\nアプリを終了してから、もう一度お試しください。")
        _cleanup(work_dir)
        return False

    try:
        shutil.move(new_exe, target)
    except Exception as e:
        try:
            os.replace(bak, target)  # 失敗したら元に戻す
        except OSError:
            pass
        _message(f"新しいexeの配置に失敗したため、元のバージョンに戻しました。\n{e}")
        _cleanup(work_dir)
        return False

    if mode == "delete":
        try:
            os.remove(bak)
        except OSError:
            pass

    if relaunch:
        try:
            if elevated:
                # 管理者権限のまま起動しないよう、エクスプローラー経由で通常権限で起動する
                subprocess.Popen(["explorer.exe", target], creationflags=NO_WINDOW)
            else:
                subprocess.Popen([target], cwd=os.path.dirname(target), env=_reset_env(),
                                 creationflags=DETACHED, close_fds=True)
        except Exception as e:
            _message(f"更新は完了しましたが、自動で再起動できませんでした。\n手動で起動してください。\n{e}")
    _cleanup(work_dir)
    return True


def _cleanup(work_dir):
    """ 作業フォルダ(ダウンロード物・更新用のexeコピー)を、このプロセスの終了後に削除する """
    try:
        subprocess.Popen(
            f'cmd.exe /c ping -n 4 127.0.0.1 >nul & rmdir /s /q "{work_dir}"',
            creationflags=NO_WINDOW, close_fds=True)
    except Exception:
        pass
