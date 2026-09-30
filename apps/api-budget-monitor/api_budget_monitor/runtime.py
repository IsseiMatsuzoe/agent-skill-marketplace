from __future__ import annotations

import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import AppConfig, load_config


APP_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BACKEND_PORT = 47831
DEFAULT_TUNNEL_HEALTH_PORT = 47832
START_TIMEOUT_SECONDS = 45
RUNTIME_LOG_BYTES = 1_000_000
RUNTIME_LOG_BACKUPS = 2
TUNNEL_CREDENTIAL_TARGET = "ApiBudgetMonitor/ExternalAgentsTunnel"
PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class RuntimeSnapshot:
    backend: str = "Stopped"
    tunnel: str = "Needs authentication/configuration"
    paid_calls_enabled: bool | None = None
    backend_detail: str = ""
    tunnel_detail: str = ""


@dataclass(frozen=True)
class BackendProbe:
    state: str  # ready, stopped, or error
    paid_calls_enabled: bool | None = None


def repository_service_path() -> Path:
    return APP_ROOT.parent.parent / "services" / "external-agents"


def runtime_directory(config_dir: Path) -> Path:
    path = config_dir / "runtime"
    path.mkdir(parents=True, exist_ok=True)
    return path


def service_path(config: AppConfig) -> Path:
    configured = config.external_agents.service_path.strip()
    return Path(configured).expanduser().resolve() if configured else repository_service_path()


def tunnel_client_path(config: AppConfig) -> Path:
    configured = config.external_agents.tunnel_client_path.strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return service_path(config) / ".local" / "tunnel-client" / "tunnel-client.exe"


def tunnel_profile_path(profile: str) -> Path:
    if not PROFILE_NAME_RE.fullmatch(profile):
        raise ValueError("Invalid tunnel profile name.")
    if os.getenv("TUNNEL_CLIENT_PROFILE_DIR"):
        directory = Path(os.environ["TUNNEL_CLIENT_PROFILE_DIR"])
    elif os.getenv("XDG_CONFIG_HOME"):
        directory = Path(os.environ["XDG_CONFIG_HOME"]) / "tunnel-client"
    elif os.getenv("HOME"):
        directory = Path(os.environ["HOME"]) / ".config" / "tunnel-client"
    elif os.name == "nt":
        # Verified with tunnel-client 0.0.15 on Windows. Without HOME it
        # uses the native config directory, despite the CLI help's Unix default.
        if not os.getenv("APPDATA"):
            raise ValueError("APPDATA is required to locate the Windows tunnel profile.")
        directory = Path(os.environ["APPDATA"]) / "tunnel-client"
    else:
        directory = Path.home() / ".config" / "tunnel-client"
    return directory / f"{profile}.yaml"


def tunnel_health_port(profile_file: Path) -> int:
    """Read only the loopback health port; never return profile credential fields."""
    if not profile_file.is_file():
        return DEFAULT_TUNNEL_HEALTH_PORT
    in_health = False
    for line in profile_file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        indent = len(line) - len(line.lstrip())
        if indent == 0:
            in_health = stripped == "health:"
        elif in_health and stripped.startswith("listen_addr:"):
            address = stripped.split(":", 1)[1].strip().strip('"\'')
            match = re.fullmatch(r"(?:127\.0\.0\.1|localhost):(\d{1,5})", address)
            if match and 1 <= int(match.group(1)) <= 65535:
                return int(match.group(1))
            raise ValueError("Tunnel health must use a loopback address.")
    return DEFAULT_TUNNEL_HEALTH_PORT


def read_mcp_token(service: Path) -> str | None:
    if os.getenv("EXTERNAL_AGENTS_MCP_TOKEN"):
        return os.environ["EXTERNAL_AGENTS_MCP_TOKEN"]
    secrets_file = service / ".local" / "secrets.env"
    try:
        for line in secrets_file.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("EXTERNAL_AGENTS_MCP_TOKEN="):
                value = line.split("=", 1)[1].strip().strip('"\'')
                return value or None
    except OSError:
        return None
    return None


def backend_port(service: Path) -> int:
    try:
        port = int(json.loads((service / ".local" / "settings.json").read_text(encoding="utf-8")).get("port", DEFAULT_BACKEND_PORT))
        return port if 1 <= port <= 65535 else DEFAULT_BACKEND_PORT
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return DEFAULT_BACKEND_PORT


def _read_credential_windows() -> str | None:
    if os.name != "nt":
        return None

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.c_uint32), ("Type", ctypes.c_uint32),
            ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
            ("LastWritten", FILETIME), ("CredentialBlobSize", ctypes.c_uint32),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", ctypes.c_uint32), ("AttributeCount", ctypes.c_uint32),
            ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
            ("UserName", ctypes.c_wchar_p),
        ]

    advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    pointer = ctypes.POINTER(CREDENTIALW)()
    advapi.CredReadW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    advapi.CredReadW.restype = ctypes.c_int
    if not advapi.CredReadW(TUNNEL_CREDENTIAL_TARGET, 1, 0, ctypes.byref(pointer)):
        if ctypes.get_last_error() == 1168:  # ERROR_NOT_FOUND
            return None
        raise RuntimeError("Windows Credential Manager could not be read.")
    try:
        credential = pointer.contents
        blob = bytearray(ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize))
        try:
            return blob.decode("utf-16-le").rstrip("\0")
        finally:
            blob[:] = b"\0" * len(blob)
            if credential.CredentialBlobSize:
                ctypes.memset(credential.CredentialBlob, 0, credential.CredentialBlobSize)
    finally:
        advapi.CredFree.argtypes = [ctypes.c_void_p]
        advapi.CredFree(pointer)


def save_tunnel_credential(value: str) -> None:
    value = value.strip()
    if not value:
        raise ValueError("Enter a tunnel runtime key.")
    if os.name != "nt":
        raise RuntimeError("Windows Credential Manager is available only on Windows.")
    blob = (value + "\0").encode("utf-16-le")
    if len(blob) > 5120:
        raise ValueError("The tunnel runtime key is too long.")

    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", ctypes.c_uint32), ("dwHighDateTime", ctypes.c_uint32)]

    class CREDENTIALW(ctypes.Structure):
        _fields_ = [
            ("Flags", ctypes.c_uint32), ("Type", ctypes.c_uint32),
            ("TargetName", ctypes.c_wchar_p), ("Comment", ctypes.c_wchar_p),
            ("LastWritten", FILETIME), ("CredentialBlobSize", ctypes.c_uint32),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", ctypes.c_uint32), ("AttributeCount", ctypes.c_uint32),
            ("Attributes", ctypes.c_void_p), ("TargetAlias", ctypes.c_wchar_p),
            ("UserName", ctypes.c_wchar_p),
        ]

    buffer = ctypes.create_string_buffer(blob, len(blob))
    credential = CREDENTIALW()
    credential.Type = 1  # CRED_TYPE_GENERIC
    credential.TargetName = TUNNEL_CREDENTIAL_TARGET
    credential.CredentialBlobSize = len(blob)
    credential.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte))
    credential.Persist = 2  # CRED_PERSIST_LOCAL_MACHINE, scoped to the current user
    credential.UserName = "External Agents"
    advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi.CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), ctypes.c_uint32]
    advapi.CredWriteW.restype = ctypes.c_int
    try:
        if not advapi.CredWriteW(ctypes.byref(credential), 0):
            raise RuntimeError("Windows Credential Manager could not save the tunnel key.")
    finally:
        ctypes.memset(buffer, 0, len(blob))


def get_tunnel_credential() -> str | None:
    value = _read_credential_windows()
    return value or os.getenv("CONTROL_PLANE_API_KEY") or None


def has_tunnel_credential() -> bool:
    return bool(get_tunnel_credential())


def _backend_probe(service: Path, timeout: float = 1.5) -> BackendProbe:
    if not (service / "src" / "server.js").is_file():
        return BackendProbe("error")
    token = read_mcp_token(service)
    if not token:
        return BackendProbe("error")
    request = Request(
        f"http://127.0.0.1:{backend_port(service)}/health",
        headers={"Authorization": f"Bearer {token}"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read(4096).decode("utf-8"))
        if data.get("status") != "ready":
            return BackendProbe("error")
        paid = data.get("paid_calls_enabled")
        return BackendProbe("ready", paid if isinstance(paid, bool) else None)
    except HTTPError:
        return BackendProbe("error")
    except (URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return BackendProbe("stopped")


def _tunnel_probe(config: AppConfig, runtime_dir: Path, timeout: float = 4.0) -> str:
    client = tunnel_client_path(config)
    profile = config.external_agents.tunnel_profile.strip() or "external-agents"
    try:
        profile_file = tunnel_profile_path(profile)
        port = tunnel_health_port(profile_file)
    except (OSError, ValueError):
        return "needs_configuration"
    if not client.is_file() or not profile_file.is_file():
        return "needs_configuration"
    try:
        with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=0.5):
            pass
    except (URLError, TimeoutError, OSError):
        return "stopped"
    try:
        command = [str(client), "health", "--port", str(port), "--require-control-plane-poll", "--json"]
        pid_file = runtime_dir / "tunnel-client.pid"
        if pid_file.is_file():
            command.extend(["--pid-file", str(pid_file)])
        result = subprocess.run(
            command,
            capture_output=True, text=True, timeout=timeout, check=False,
            creationflags=_hidden_creation_flags(),
        )
        return "connected" if result.returncode == 0 else "error"
    except (OSError, subprocess.TimeoutExpired):
        return "error"


def _hidden_creation_flags() -> int:
    if os.name == "nt":
        return getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return 0


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value), encoding="utf-8")
    os.replace(temporary, path)


def _redact_log_line(line: str, credential: str | None) -> str:
    return line.replace(credential, "[REDACTED]") if credential else line


def _linux_process_identity(pid: int) -> dict | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        # Fields after the final ')' begin at field 3; starttime is field 22.
        start = raw[raw.rfind(")") + 2 :].split()[19]
        executable = os.path.realpath(f"/proc/{pid}/exe")
        return {"pid": pid, "started": start, "image": os.path.normcase(executable)}
    except (OSError, IndexError):
        return None


def _windows_process_identity(pid: int, existing_handle=None) -> dict | None:
    if os.name != "nt":
        return None
    from ctypes import wintypes

    kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    handle = existing_handle
    owns_handle = handle is None
    if owns_handle:
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000 | 0x00100000, False, pid)  # query + synchronize
        if not handle:
            return None
    class FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    created, exited, kernel_time, user_time = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    kernel.GetProcessTimes.argtypes = [wintypes.HANDLE, ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME), ctypes.POINTER(FILETIME)]
    kernel.GetProcessTimes.restype = wintypes.BOOL
    image_buffer = ctypes.create_unicode_buffer(32768)
    image_size = wintypes.DWORD(len(image_buffer))
    kernel.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    try:
        if not kernel.GetProcessTimes(handle, ctypes.byref(created), ctypes.byref(exited), ctypes.byref(kernel_time), ctypes.byref(user_time)):
            return None
        if not kernel.QueryFullProcessImageNameW(handle, 0, image_buffer, ctypes.byref(image_size)):
            return None
        started = (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)
        return {"pid": pid, "started": str(started), "image": os.path.normcase(image_buffer.value)}
    finally:
        if owns_handle:
            kernel.CloseHandle(handle)


def _process_identity(pid: int) -> dict | None:
    return _windows_process_identity(pid) if os.name == "nt" else _linux_process_identity(pid)


def _matches_owner(owner: dict) -> bool:
    try:
        current = _process_identity(int(owner["pid"]))
        return bool(current and current["started"] == str(owner["started"]) and current["image"] == os.path.normcase(str(owner["image"])))
    except (KeyError, TypeError, ValueError):
        return False


def _terminate_owner(owner: dict, timeout: float = 5.0) -> bool:
    try:
        pid = int(owner["pid"])
    except (KeyError, TypeError, ValueError):
        return False
    if os.name == "nt":
        from ctypes import wintypes

        kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x0001 | 0x1000 | 0x00100000, False, pid)
        if not handle:
            return False
        try:
            current = _windows_process_identity(pid, handle)
            if not current or current["started"] != str(owner.get("started")) or current["image"] != os.path.normcase(str(owner.get("image", ""))):
                return False
            if not kernel.TerminateProcess(handle, 1):
                return False
            kernel.WaitForSingleObject(handle, max(0, int(timeout * 1000)))
            return True
        finally:
            kernel.CloseHandle(handle)
    if not _matches_owner(owner):
        return False
    try:
        os.killpg(pid, signal.SIGTERM)
        return True
    except (OSError, ProcessLookupError):
        return False


class RuntimeManager:
    def __init__(self, config_dir: Path, config: AppConfig, *, start_timeout: float = START_TIMEOUT_SECONDS, poll_interval: float = 0.25):
        self.config_dir = config_dir
        self.config = config
        self.directory = runtime_directory(config_dir)
        self.start_timeout = start_timeout
        self.poll_interval = poll_interval
        self._lock = threading.Lock()

    def _owner_path(self, component: str) -> Path:
        return self.directory / f"{component}.owner.json"

    def _stop_path(self, component: str) -> Path:
        return self.directory / f"{component}.stop"

    def _last_worker_state(self, component: str) -> str:
        try:
            return json.loads((self.directory / f"{component}.status.json").read_text(encoding="utf-8")).get("state", "")
        except (OSError, ValueError, AttributeError):
            return ""

    def _owner(self, component: str) -> dict | None:
        try:
            value = json.loads(self._owner_path(component).read_text(encoding="utf-8"))
            return value if _matches_owner(value) else None
        except (OSError, ValueError):
            return None

    def _worker_starting(self, component: str) -> bool:
        owner = self._owner(component)
        if not owner:
            return False
        try:
            return time.time() - float(owner["since"]) <= self.start_timeout
        except (KeyError, TypeError, ValueError):
            return False

    def _worker_running(self, component: str) -> bool:
        return self._owner(component) is not None

    def snapshot(self) -> RuntimeSnapshot:
        service = service_path(self.config)
        backend_probe = _backend_probe(service)
        if backend_probe.state == "ready":
            backend = "Running"
        elif backend_probe.state == "error":
            backend = "Error / Unreachable"
        elif self._worker_starting("backend"):
            backend = "Starting"
        elif self._worker_running("backend"):
            backend = "Error / Unreachable"
        elif self._last_worker_state("backend") in {"error", "exited"}:
            backend = "Error / Unreachable"
        else:
            backend = "Stopped"
        backend_detail = {
            "ready": "",
            "error": "Check the External Agents service path and local backend setup.",
            "stopped": "The backend is not responding on its authenticated health endpoint.",
        }[backend_probe.state]

        tunnel_probe = _tunnel_probe(self.config, self.directory)
        if tunnel_probe == "connected":
            tunnel = "Connected"
        elif tunnel_probe == "error":
            tunnel = "Error / Unknown"
        elif tunnel_probe == "needs_configuration":
            tunnel = "Needs authentication/configuration"
        elif self._worker_starting("tunnel"):
            tunnel = "Starting"
        elif self._worker_running("tunnel"):
            tunnel = "Error / Unknown"
        elif not has_tunnel_credential():
            tunnel = "Needs authentication/configuration"
        elif self._last_worker_state("tunnel") in {"error", "exited"}:
            tunnel = "Error / Unknown"
        else:
            tunnel = "Disconnected / Stopped"
        tunnel_detail = ""
        if tunnel == "Needs authentication/configuration":
            tunnel_detail = "Set up tunnel authentication and verify the selected profile and client path."
        elif tunnel == "Error / Unknown":
            tunnel_detail = "The local tunnel health endpoint did not confirm a control-plane poll."
        elif tunnel == "Disconnected / Stopped":
            tunnel_detail = "The tunnel client is not running."
        return RuntimeSnapshot(backend, tunnel, backend_probe.paid_calls_enabled, backend_detail, tunnel_detail)

    def _valid_backend(self) -> tuple[Path, str] | None:
        service = service_path(self.config)
        node = shutil.which("node.exe" if os.name == "nt" else "node") or shutil.which("node")
        package = service / "package.json"
        try:
            valid_package = json.loads(package.read_text(encoding="utf-8")).get("name") == "external-agents-gateway"
        except (OSError, ValueError, AttributeError):
            valid_package = False
        if (not service.is_dir() or not valid_package or not (service / "src" / "server.js").is_file()
                or not (service / "node_modules" / "@modelcontextprotocol" / "sdk" / "package.json").is_file() or not node):
            return None
        token = read_mcp_token(service)
        if not token:
            return None
        return service, node

    def _spawn_worker(self, component: str) -> bool:
        self._stop_path(component).unlink(missing_ok=True)
        (self.directory / f"{component}.status.json").unlink(missing_ok=True)
        command = [sys.executable, "-m", "api_budget_monitor.runtime", "_worker", component, "--config-dir", str(self.config_dir)]
        flags = _hidden_creation_flags()
        if os.name == "nt":
            flags |= getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            flags |= getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000)
        try:
            child = subprocess.Popen(command, cwd=APP_ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL, creationflags=flags,
                                     start_new_session=(os.name != "nt"))
        except OSError:
            return False
        identity = _process_identity(child.pid)
        if identity:
            identity["since"] = time.time()
            _write_json(self._owner_path(component), identity)
        return True

    def _stop_worker(self, component: str) -> None:
        owner = self._owner(component)
        if not owner:
            self._owner_path(component).unlink(missing_ok=True)
            return
        self._stop_path(component).touch()
        deadline = time.monotonic() + 6.0
        while time.monotonic() < deadline and self._worker_running(component):
            time.sleep(self.poll_interval)
        if self._worker_running(component):
            _terminate_owner(owner)
        if not self._worker_running(component):
            self._owner_path(component).unlink(missing_ok=True)
            self._stop_path(component).unlink(missing_ok=True)

    def _wait_backend(self) -> bool:
        deadline = time.monotonic() + self.start_timeout
        while True:
            if _backend_probe(service_path(self.config)).state == "ready":
                return True
            if not self._worker_running("backend") or time.monotonic() >= deadline:
                return False
            time.sleep(self.poll_interval)

    def _wait_tunnel(self) -> bool:
        deadline = time.monotonic() + self.start_timeout
        while True:
            if _tunnel_probe(self.config, self.directory) == "connected":
                return True
            if not self._worker_running("tunnel") or time.monotonic() >= deadline:
                return False
            time.sleep(self.poll_interval)

    def start(self) -> RuntimeSnapshot:
        with self._lock:
            backend_probe = _backend_probe(service_path(self.config))
            if backend_probe.state != "ready":
                if self._valid_backend() is None:
                    return self.snapshot()
                if not self._worker_running("backend"):
                    if not self._spawn_worker("backend"):
                        return self.snapshot()
                if not self._wait_backend():
                    return self.snapshot()

            tunnel_probe = _tunnel_probe(self.config, self.directory)
            if tunnel_probe == "connected":
                return self.snapshot()
            profile = self.config.external_agents.tunnel_profile.strip() or "external-agents"
            try:
                profile_file = tunnel_profile_path(profile)
                client = tunnel_client_path(self.config)
                if not profile_file.is_file() or not client.is_file() or not has_tunnel_credential():
                    return self.snapshot()
                tunnel_health_port(profile_file)
            except (OSError, ValueError):
                return self.snapshot()
            if tunnel_probe == "error":
                return self.snapshot()  # A live but unverified daemon must not be duplicated.
            if not self._worker_running("tunnel") and not self._spawn_worker("tunnel"):
                return self.snapshot()
            self._wait_tunnel()
            return self.snapshot()

    def restart(self) -> RuntimeSnapshot:
        with self._lock:
            self._stop_worker("tunnel")
            self._stop_worker("backend")
        return self.start()


def runtime_transition_messages(previous: RuntimeSnapshot | None, current: RuntimeSnapshot) -> list[tuple[str, str]]:
    if previous is None:
        return []
    messages = []
    if previous.backend == "Running" and current.backend != "Running":
        messages.append(("External Agents backend stopped unexpectedly", "The local backend is no longer ready."))
    if previous.tunnel == "Connected" and current.tunnel != "Connected":
        messages.append(("Secure MCP Tunnel disconnected unexpectedly", "The tunnel connection is no longer ready."))
    if ((previous.backend != "Running" or previous.tunnel != "Connected")
            and (current.backend == "Running" or current.tunnel == "Connected")):
        messages.append(("External Agents runtime restored", "A previously unavailable runtime component is ready again."))
    return messages


def _create_job():
    if os.name != "nt":
        return None
    from ctypes import wintypes

    class BASIC_LIMIT(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(name, ctypes.c_uint64) for name in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class EXTENDED_LIMIT(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC_LIMIT), ("IoInfo", IO_COUNTERS),
                    ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    kernel.CreateJobObjectW.restype = wintypes.HANDLE
    job = kernel.CreateJobObjectW(None, None)
    if not job:
        raise RuntimeError("Could not create the runtime process group.")
    limits = EXTENDED_LIMIT()
    limits.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    if not kernel.SetInformationJobObject(job, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
        kernel.CloseHandle(job)
        raise RuntimeError("Could not configure the runtime process group.")
    return job


def _assign_to_job(job, child: subprocess.Popen) -> None:
    if job is None:
        return
    from ctypes import wintypes

    kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    if not kernel.AssignProcessToJobObject(job, child._handle):
        raise RuntimeError("Could not contain the runtime process.")


def _terminate_job(job, child: subprocess.Popen) -> None:
    if job is not None:
        from ctypes import wintypes
        kernel = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel.TerminateJobObject(job, 1)
    elif child.poll() is None:
        if os.name == "nt":
            child.terminate()
        else:
            try:
                os.killpg(child.pid, signal.SIGTERM)
            except OSError:
                child.terminate()


def _worker_command(component: str, config: AppConfig, config_dir: Path, runtime_dir: Path) -> tuple[list[str], Path, dict[str, str], str | None]:
    if component == "backend":
        valid = RuntimeManager(config_dir, config)._valid_backend()
        if valid is None:
            raise RuntimeError("External Agents service is not configured.")
        service, node = valid
        return [node, "src/server.js"], service, os.environ.copy(), None
    if component == "tunnel":
        profile = config.external_agents.tunnel_profile.strip() or "external-agents"
        profile_file = tunnel_profile_path(profile)
        client = tunnel_client_path(config)
        if not profile_file.is_file() or not client.is_file():
            raise RuntimeError("Tunnel configuration is not available.")
        credential = get_tunnel_credential()
        if not credential:
            raise RuntimeError("Tunnel authentication is not configured.")
        port = tunnel_health_port(profile_file)
        url_file = runtime_dir / "tunnel-health.url"
        pid_file = runtime_dir / "tunnel-client.pid"
        # Use exactly the file validated above. The Windows client's named
        # profile loader can reject a regular file with a statat link error.
        # Empty log.file writes to the captured pipe; "stdout" is a filename.
        command = [str(client), "run", "--profile-file", str(profile_file),
                   "--control-plane.api-key", "env:CONTROL_PLANE_API_KEY",
                   "--health.listen-addr", f"127.0.0.1:{port}",
                   "--health.url-file", str(url_file), "--pid.file", str(pid_file),
                   "--log.file", "", "--log.format", "json", "--log.level", "info"]
        env = os.environ.copy()
        env["CONTROL_PLANE_API_KEY"] = credential
        return command, service_path(config), env, credential
    raise ValueError("Unknown runtime component.")


def _run_worker(component: str, config_dir: Path) -> int:
    directory = runtime_directory(config_dir)
    owner_path = directory / f"{component}.owner.json"
    stop_path = directory / f"{component}.stop"
    log_path = directory / f"{component}.log"
    logger = logging.getLogger(f"api_budget_runtime.{component}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = RotatingFileHandler(log_path, maxBytes=RUNTIME_LOG_BYTES, backupCount=RUNTIME_LOG_BACKUPS, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    child = None
    job = None
    credential = None
    worker_state = "error"
    stop_requested = False
    try:
        config = load_config(config_dir / "settings.json")
        command, cwd, env, credential = _worker_command(component, config, config_dir, directory)
        job = _create_job()
        child = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, encoding="utf-8", errors="replace", bufsize=1,
                                 creationflags=_hidden_creation_flags(),
                                 start_new_session=(os.name != "nt"))
        _assign_to_job(job, child)
        logger.info("Started %s runtime component.", component)

        output: queue.Queue[str | None] = queue.Queue()

        def capture() -> None:
            try:
                assert child is not None and child.stdout is not None
                for line in child.stdout:
                    output.put(line.rstrip("\r\n"))
            finally:
                output.put(None)

        reader = threading.Thread(target=capture, daemon=True)
        reader.start()
        output_closed = False
        while child.poll() is None or not output_closed:
            if stop_path.exists():
                stop_requested = True
                logger.info("Stopping owned %s runtime component.", component)
                _terminate_job(job, child)
                stop_path.unlink(missing_ok=True)
            try:
                line = output.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                output_closed = True
            else:
                line = _redact_log_line(line, credential)
                logger.info("%s", line[:8192])
        exit_code = child.wait()
        worker_state = "stopped" if stop_requested else "exited"
        return exit_code
    except Exception as exc:
        # Exception text and child output can contain credentials or private paths.
        logger.error("Runtime component failed (%s).", type(exc).__name__)
        if child is not None:
            _terminate_job(job, child)
            try:
                child.wait(timeout=3)
            except subprocess.TimeoutExpired:
                child.kill()
        return 1
    finally:
        _write_json(directory / f"{component}.status.json", {"state": worker_state, "at": int(time.time())})
        owner_path.unlink(missing_ok=True)
        stop_path.unlink(missing_ok=True)
        if job is not None and os.name == "nt":
            ctypes.WinDLL("Kernel32.dll", use_last_error=True).CloseHandle(job)
        handler.close()
        logger.removeHandler(handler)


def _worker_main(argv: list[str]) -> int:
    if len(argv) != 4 or argv[0] != "_worker" or argv[1] not in {"backend", "tunnel"} or argv[2] != "--config-dir":
        return 2
    return _run_worker(argv[1], Path(argv[3]))


if __name__ == "__main__":
    raise SystemExit(_worker_main(sys.argv[1:]))
