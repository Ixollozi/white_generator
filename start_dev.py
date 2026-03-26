#!/usr/bin/env python3
"""
Запуск dev-окружения: FastAPI (uvicorn) + Vite frontend.

- Один экземпляр скрипта (блокировка файла .dev/start_dev.lock).
- Если порты API/frontend заняты — завершает слушающие процессы (Windows: taskkill /T;
  Unix: SIGTERM/SIGKILL). Повтор: --no-kill — только сообщение, без завершения.
- При занятой блокировке пытается один раз завершить PID из .dev/start_dev.lock (прошлый
  экземпляр скрипта), затем снова взять lock.
- Проверяет зависимости; опционально pip install / npm install.
- Ждёт /api/health перед запуском Vite.
- На Windows Vite запускается через `node …/vite.js` (без npm.cmd/vite.cmd), чтобы при Ctrl+C
  не появлялось «Завершить выполнение пакетного файла [Y/N]?».

  python start_dev.py
  python start_dev.py --open-browser
  python start_dev.py --api-port 8000 --frontend-port 5173

Коды выхода: 2 — уже запущен; 3/4 — порт занят; 5–11 — Python;
12–15 — Node; 16 — порт frontend при ожидании; 17 — таймаут API; 18 — ошибка блокировки;
19 — нет node или бинарника Vite.
"""
from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path
from typing import BinaryIO, Optional


class Colors:
    CYAN = "\033[96m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    GRAY = "\033[90m"
    RESET = "\033[0m"


def _use_color() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def info(msg: str) -> None:
    p = f"{Colors.CYAN}[*]{Colors.RESET} " if _use_color() else "[*] "
    print(p + msg, flush=True)


def ok(msg: str) -> None:
    p = f"{Colors.GREEN}[+]{Colors.RESET} " if _use_color() else "[+] "
    print(p + msg, flush=True)


def warn(msg: str) -> None:
    p = f"{Colors.YELLOW}[!]{Colors.RESET} " if _use_color() else "[!] "
    print(p + msg, flush=True)


def err(msg: str) -> None:
    p = f"{Colors.RED}[x]{Colors.RESET} " if _use_color() else "[x] "
    print(p + msg, flush=True)


def gray_line(msg: str) -> None:
    if _use_color():
        print(f"{Colors.GRAY}      {msg}{Colors.RESET}", flush=True)
    else:
        print(f"      {msg}", flush=True)


REPO_ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = REPO_ROOT / "frontend"
REQ_FILE = REPO_ROOT / "requirements.txt"
LOCK_PATH = REPO_ROOT / ".dev" / "start_dev.lock"
STATE_PATH = REPO_ROOT / ".dev" / "start_dev.state.json"


def port_is_open(host: str, port: int) -> bool:
    """True, если на порту что-то принимает TCP-соединения."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(0.35)
    try:
        return s.connect_ex((host, port)) == 0
    finally:
        s.close()


def listeners_info_windows(port: int) -> list[tuple[int, str]]:
    try:
        out = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=(subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0),
        )
        if out.returncode != 0:
            return []
        lines = []
        for line in out.stdout.splitlines():
            if "LISTENING" not in line.upper():
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            local = parts[1]
            if not (local.endswith(f":{port}") or local.endswith(f"]:{port}")):
                continue
            pid = parts[-1]
            if not pid.isdigit():
                continue
            name = "(unknown)"
            try:
                if sys.platform == "win32":
                    q = subprocess.run(
                        ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                        capture_output=True,
                        text=True,
                        timeout=5,
                        creationflags=subprocess.CREATE_NO_WINDOW,
                    )
                    if q.stdout.strip():
                        name = q.stdout.strip().split(",")[0].strip('"')
            except OSError:
                pass
            lines.append((int(pid), name))
        return list({x[0]: x for x in lines}.values())
    except (OSError, subprocess.TimeoutExpired):
        return []


def _run_hidden(cmd: list[str], timeout: float = 30) -> subprocess.CompletedProcess:
    kw: dict = {"capture_output": True, "text": True, "timeout": timeout}
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    return subprocess.run(cmd, **kw)


def listeners_info_posix(port: int) -> list[tuple[int, str]]:
    pids: dict[int, str] = {}
    for cmd in (
        ["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"],
        ["lsof", "-t", f"-i:{port}", "-sTCP:LISTEN"],
    ):
        try:
            r = _run_hidden(cmd, timeout=12)
            if r.returncode != 0 or not (r.stdout or "").strip():
                continue
            for line in r.stdout.splitlines():
                p = line.strip()
                if p.isdigit():
                    pids[int(p)] = "listener"
        except (OSError, subprocess.TimeoutExpired):
            continue
        if pids:
            return list(pids.items())
    try:
        r = _run_hidden(["ss", "-lntp"], timeout=12)
        if r.returncode == 0 and r.stdout:
            for m in re.finditer(rf":{port}\b.*?pid=(\d+)", r.stdout, re.IGNORECASE):
                pids[int(m.group(1))] = "listener"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return list(pids.items())


def listeners_on_port(port: int) -> list[tuple[int, str]]:
    if sys.platform == "win32":
        return listeners_info_windows(port)
    return listeners_info_posix(port)


def force_kill_pid(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        if sys.platform == "win32":
            r = _run_hidden(["taskkill", "/PID", str(pid), "/T", "/F"], timeout=45)
            out = ((r.stderr or "") + (r.stdout or "")).lower()
            if r.returncode == 0:
                return True
            if "not found" in out or "не найден" in out:
                return True
            return False
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return True
        for _ in range(35):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True
        return True
    except OSError:
        return False


def kill_listeners_on_port(port: int) -> int:
    listeners = listeners_on_port(port)
    if not listeners and sys.platform != "win32":
        try:
            r = _run_hidden(["fuser", "-k", f"{port}/tcp"], timeout=20)
            if r.returncode == 0:
                warn(f"fuser -k {port}/tcp — завершены процессы на порту {port}")
                return 1
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            pass
    killed = 0
    seen: set[int] = set()
    for pid, name in listeners:
        if pid in seen:
            continue
        seen.add(pid)
        if force_kill_pid(pid):
            killed += 1
            ok(f"Завершён PID {pid} ({name}), порт {port}")
        else:
            warn(f"Не удалось завершить PID {pid} ({name}), порт {port}")
    return killed


def ensure_port_free(port: int, role: str, allow_kill: bool) -> bool:
    if not port_is_open("127.0.0.1", port):
        return True
    if not allow_kill:
        show_port_conflict(port, role)
        return False
    warn(f"Порт {port} занят ({role}) — завершаю слушающие процессы…")
    for _ in range(4):
        kill_listeners_on_port(port)
        time.sleep(0.55)
        if not port_is_open("127.0.0.1", port):
            ok(f"Порт {port} свободен.")
            return True
    err(f"Не удалось освободить порт {port} ({role}).")
    show_port_conflict(port, role)
    return False


def read_lock_holder_pid() -> Optional[int]:
    try:
        raw = LOCK_PATH.read_text(encoding="utf-8").strip()
        if raw.isdigit():
            p = int(raw)
            return p if p > 0 else None
    except OSError:
        pass
    return None


def write_state(data: dict) -> None:
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except OSError:
        pass


def clear_state() -> None:
    try:
        if STATE_PATH.is_file():
            STATE_PATH.unlink()
    except OSError:
        pass


def show_port_conflict(port: int, role: str) -> None:
    err(f"Порт {port} уже занят ({role}). Запуск отменён, чтобы не плодить процессы.")
    if sys.platform == "win32":
        lst = listeners_info_windows(port)
        if lst:
            for pid, name in lst:
                gray_line(f"PID {pid} ({name})")
        else:
            warn("Не удалось определить PID через netstat.")
            info(f'Проверьте: netstat -ano | findstr ":{port}"')
    else:
        info(f"Проверьте: ss -lntp | grep :{port}  или  lsof -i :{port}")
    info("Или запустите без флага --no-kill, чтобы скрипт сам завершил слушающие процессы.")


def acquire_single_instance_lock(allow_kill_lock_holder: bool) -> tuple[Optional[BinaryIO], int]:
    """
    Возвращает (file_object, 0) при успехе или (None, exit_code) при ошибке.
    Файл нужно держать открытым до выхода.
    """
    # Safety-first: do not kill an arbitrary PID from a stale lock file by default.
    # If lock is held, it means another instance is currently running.
    for attempt in range(1):
        try:
            LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
            fp = open(LOCK_PATH, "a+b")
        except OSError as e:
            err(f"Не удалось открыть lock-файл: {e}")
            return None, 18

        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fp.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fp.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            fp.close()
            err("Скрипт уже запущен в другом терминале (или блокировка не снята).")
            holder = read_lock_holder_pid()
            if holder is not None:
                gray_line(f"PID в lock-файле: {holder}")
            info("Закройте другой терминал со start_dev.py и попробуйте снова.")
            return None, 2
        break
    else:
        return None, 2

    def _release() -> None:
        try:
            clear_state()
            fp.seek(0)
            fp.truncate()
            if sys.platform == "win32":
                import msvcrt

                try:
                    fp.seek(0)
                    msvcrt.locking(fp.fileno(), msvcrt.LK_UNLCK, 1)
                except OSError:
                    pass
            else:
                import fcntl

                try:
                    fcntl.flock(fp.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass
        finally:
            fp.close()

    atexit.register(_release)
    fp.seek(0)
    fp.truncate()
    fp.write(str(os.getpid()).encode("utf-8"))
    fp.flush()
    return fp, 0


def python_ok_for_imports() -> bool:
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except ImportError:
        return False
    return True


def verify_server_import() -> tuple[bool, str]:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(REPO_ROOT), os.environ.get("PYTHONPATH", "")])}
    r = subprocess.run(
        [sys.executable, "-c", "from server.app import app"],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, out.strip()


def start_uvicorn(api_host: str, api_port: int) -> subprocess.Popen:
    """
    Один процесс в текущей консоли (и на Windows без отдельного окна).
    Так проще останавливать dev и не оставлять «забытый» uvicorn на порту.
    """
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT)}
    kw: dict = {}
    if sys.platform == "win32":
        # keep child attached to this console, but allow clean termination
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "server.app:app",
            "--reload",
            f"--host={api_host}",
            f"--port={api_port}",
        ],
        cwd=REPO_ROOT,
        env=env,
        **kw,
    )


def stop_api_process(proc: Optional[subprocess.Popen]) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
    except OSError:
        pass


def start_vite(frontend_port: int) -> subprocess.Popen:
    vcmd = vite_dev_command(frontend_port)
    if vcmd is None:
        raise SystemExit(19)
    kw: dict = {}
    if sys.platform == "win32":
        kw["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(vcmd, cwd=FRONTEND_DIR, **kw)


def stop_process(proc: Optional[subprocess.Popen], name: str) -> None:
    if proc is None or proc.poll() is not None:
        return
    try:
        warn(f"Останавливаю {name} (PID {proc.pid})…")
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
    except OSError:
        pass


def vite_dev_command(frontend_port: int) -> Optional[list[str]]:
    """Команда запуска dev-сервера Vite без npm.cmd/vite.cmd (важно для Windows + Ctrl+C)."""
    node = shutil.which("node")
    if not node:
        return None
    vite_js = FRONTEND_DIR / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_js.is_file():
        return None
    return [node, str(vite_js), "dev", "--port", str(frontend_port), "--strictPort"]


def wait_for_health(url: str, timeout_sec: float, frontend_port: int) -> str:
    """
    Возвращает 'ok' | 'timeout' | 'frontend_busy'.
    При 'frontend_busy' вызывающий код останавливает api_proc.
    """
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if port_is_open("127.0.0.1", frontend_port):
            warn(f"Порт {frontend_port} стал занят во время ожидания API — прерывание.")
            return "frontend_busy"
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    return "ok"
        except (urllib.error.URLError, OSError, TimeoutError):
            pass
        time.sleep(0.4)
    return "timeout"


def main() -> None:
    parser = argparse.ArgumentParser(description="Dev: uvicorn + Vite")
    parser.add_argument("--api-port", type=int, default=8000)
    parser.add_argument("--frontend-port", type=int, default=5173)
    parser.add_argument("--skip-deps", action="store_true", help="Не ставить pip/npm зависимости автоматически")
    parser.add_argument(
        "--no-kill",
        action="store_true",
        help="Не завершать процессы на портах и держателя lock (старое поведение)",
    )
    parser.add_argument("--open-browser", action="store_true")
    args = parser.parse_args()

    if not (1 <= args.api_port <= 65535 and 1 <= args.frontend_port <= 65535):
        err("Некорректный порт")
        sys.exit(1)

    if sys.version_info < (3, 10):
        err("Нужен Python 3.10 или новее.")
        sys.exit(6)

    allow_kill = not args.no_kill
    lock_fp, code = acquire_single_instance_lock(allow_kill_lock_holder=allow_kill)
    if lock_fp is None:
        sys.exit(code)

    api_host = "127.0.0.1"
    api_proc: Optional[subprocess.Popen] = None
    vite_proc: Optional[subprocess.Popen] = None

    def _shutdown(exit_code: int) -> None:
        stop_process(vite_proc, "Vite")
        stop_api_process(api_proc)
        clear_state()
        raise SystemExit(exit_code)

    def _on_signal(signum: int, _frame: object | None = None) -> None:
        _shutdown(130 if signum in (getattr(signal, "SIGINT", 2),) else 143)

    try:
        signal.signal(signal.SIGINT, _on_signal)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _on_signal)  # type: ignore[arg-type]
    except Exception:
        pass

    try:
        os.chdir(REPO_ROOT)
        info(f"Корень проекта: {REPO_ROOT}")

        if not ensure_port_free(args.api_port, "API (uvicorn)", allow_kill):
            sys.exit(3)
        if not ensure_port_free(args.frontend_port, "Frontend (Vite)", allow_kill):
            sys.exit(4)

        ok(f"Python: {sys.version.split()[0]}")

        if not REQ_FILE.is_file():
            err(f"Не найден файл: {REQ_FILE}")
            sys.exit(7)

        if not python_ok_for_imports():
            if args.skip_deps:
                err("Не установлены fastapi/uvicorn. Запустите без --skip-deps или: pip install -r requirements.txt")
                sys.exit(8)
            warn("Ставлю зависимости Python (pip install -r requirements.txt)...")
            r = subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(REQ_FILE)], cwd=REPO_ROOT)
            if r.returncode != 0:
                err("pip install завершился с ошибкой.")
                sys.exit(9)
            if not python_ok_for_imports():
                err("После установки импорт fastapi/uvicorn всё ещё не работает.")
                sys.exit(10)

        ok_imp, imp_out = verify_server_import()
        if not ok_imp:
            err("Не удалось импортировать server.app (зависимости / структура проекта).")
            if imp_out:
                print(imp_out, flush=True)
            sys.exit(11)

        npm = shutil.which("npm")
        if not npm:
            err("Не найден npm. Установите Node.js LTS.")
            sys.exit(12)
        nv = subprocess.run([npm, "--version"], capture_output=True, text=True, cwd=REPO_ROOT)
        ok(f"npm: {(nv.stdout or nv.stderr).strip()}")

        pkg = FRONTEND_DIR / "package.json"
        if not pkg.is_file():
            err(f"Не найден frontend: {pkg}")
            sys.exit(13)

        node_modules = FRONTEND_DIR / "node_modules"
        if not node_modules.is_dir():
            if args.skip_deps:
                err("Нет node_modules. Запустите npm install в frontend или уберите --skip-deps.")
                sys.exit(14)
            warn("Ставлю npm-зависимости (npm install)...")
            r = subprocess.run([npm, "install"], cwd=FRONTEND_DIR)
            if r.returncode != 0:
                err("npm install завершился с ошибкой.")
                sys.exit(15)

        info(f"Запуск API: http://{api_host}:{args.api_port}/")
        info("(uvicorn в фоне этого терминала; логи API идут сюда же, выше/ниже вывода Vite)")
        api_proc = start_uvicorn(api_host, args.api_port)
        write_state(
            {
                "script_pid": os.getpid(),
                "api_pid": api_proc.pid,
                "vite_pid": None,
                "api_port": args.api_port,
                "frontend_port": args.frontend_port,
                "started_at": time.time(),
            }
        )

        health_url = f"http://{api_host}:{args.api_port}/api/health"
        info(f"Ожидание ответа API ({health_url})...")
        health = wait_for_health(health_url, 45.0, args.frontend_port)
        if health == "frontend_busy":
            stop_api_process(api_proc)
            sys.exit(16)
        if health == "timeout":
            err("API не ответил за 45 с. Проверьте процесс uvicorn (порт, импорты, firewall).")
            stop_api_process(api_proc)
            sys.exit(17)

        ok("API готов.")

        info(f"Запуск Vite: http://localhost:{args.frontend_port}/")
        info("Скрипт следит за процессами: если один упал/закрылся — второй будет остановлен, чтобы не оставлять «хвостов».")

        if args.open_browser:
            webbrowser.open(f"http://localhost:{args.frontend_port}/")

        try:
            vite_proc = start_vite(args.frontend_port)
        except SystemExit:
            err("Не найдены node или frontend/node_modules/vite/bin/vite.js. Выполните npm install в frontend.")
            raise
        write_state(
            {
                "script_pid": os.getpid(),
                "api_pid": api_proc.pid if api_proc else None,
                "vite_pid": vite_proc.pid if vite_proc else None,
                "api_port": args.api_port,
                "frontend_port": args.frontend_port,
                "started_at": time.time(),
            }
        )

        # Main loop: keep running until one process exits.
        while True:
            time.sleep(0.35)
            if api_proc and api_proc.poll() is not None:
                err(f"API завершился (код {api_proc.returncode}). Останавливаю Vite…")
                _shutdown(int(api_proc.returncode or 1))
            if vite_proc and vite_proc.poll() is not None:
                info(f"Vite завершился (код {vite_proc.returncode}). Останавливаю API…")
                _shutdown(int(vite_proc.returncode or 0))
    except SystemExit as e:
        stop_process(vite_proc, "Vite")
        stop_api_process(api_proc)
        clear_state()
        raise
    except KeyboardInterrupt:
        stop_process(vite_proc, "Vite")
        stop_api_process(api_proc)
        clear_state()
        sys.exit(130)


if __name__ == "__main__":
    main()
