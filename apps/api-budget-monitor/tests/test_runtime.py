import json
import os
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

from api_budget_monitor.config import AppConfig, ExternalAgentsRuntimeConfig, load_config, save_config
from api_budget_monitor.runtime import (
    BackendProbe,
    RuntimeManager,
    RuntimeSnapshot,
    _backend_probe,
    _redact_log_line,
    _tunnel_probe,
    _worker_command,
    runtime_transition_messages,
    tunnel_profile_path,
)


class RuntimeConfigTests(unittest.TestCase):
    def test_default_tunnel_profile_path_matches_tunnel_client_on_windows(self):
        with tempfile.TemporaryDirectory() as appdata:
            with patch.dict(os.environ, {
                "APPDATA": appdata,
                "TUNNEL_CLIENT_PROFILE_DIR": "",
                "XDG_CONFIG_HOME": "",
            }, clear=False), patch("api_budget_monitor.runtime.os.name", "nt"):
                expected = Path.home() / ".config" / "tunnel-client" / "external-agents.yaml"
                self.assertEqual(tunnel_profile_path("external-agents"), expected)

    def test_runtime_settings_round_trip_without_secrets(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            config = AppConfig(external_agents=ExternalAgentsRuntimeConfig(
                enabled_on_startup=True,
                service_path=r"C:\External Agents\services\external-agents",
                tunnel_profile="external-agents",
                tunnel_client_path=r"C:\External Agents\tunnel-client.exe",
            ))
            save_config(path, config)
            serialized = path.read_text(encoding="utf-8")
            self.assertNotIn("CONTROL_PLANE_API_KEY", serialized)
            self.assertNotIn("EXTERNAL_AGENTS_MCP_TOKEN", serialized)
            loaded = load_config(path)
            self.assertTrue(loaded.external_agents.enabled_on_startup)
            self.assertEqual(loaded.external_agents.service_path, config.external_agents.service_path)
            self.assertEqual(loaded.external_agents.tunnel_profile, "external-agents")
            self.assertEqual(loaded.external_agents.tunnel_client_path, config.external_agents.tunnel_client_path)


class RuntimeWorkflowTests(unittest.TestCase):
    def manager(self, directory):
        return RuntimeManager(Path(directory), AppConfig(), start_timeout=0.01, poll_interval=0)

    def test_healthy_backend_and_tunnel_are_not_started_again(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            spawn = Mock()
            with patch("api_budget_monitor.runtime._backend_probe", return_value=BackendProbe("ready", False)), \
                 patch("api_budget_monitor.runtime._tunnel_probe", return_value="connected"), \
                 patch.object(manager, "_spawn_worker", spawn):
                result = manager.start()
            self.assertEqual((result.backend, result.tunnel), ("Running", "Connected"))
            spawn.assert_not_called()

    def test_backend_readiness_precedes_tunnel_start(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            sequence = []
            active = set()
            backend = iter([BackendProbe("stopped"), BackendProbe("ready"), BackendProbe("ready")])
            tunnel = iter(["stopped", "connected", "connected"])

            def spawn(component):
                sequence.append(component)
                active.add(component)
                return True

            manager._valid_backend = lambda: (Path(directory), "node")
            manager._worker_running = lambda component: component in active
            with patch("api_budget_monitor.runtime._backend_probe", side_effect=lambda *_: next(backend)), \
                 patch("api_budget_monitor.runtime._tunnel_probe", side_effect=lambda *_: next(tunnel)), \
                 patch("api_budget_monitor.runtime.tunnel_profile_path", return_value=Path(directory) / "profile.yaml"), \
                 patch("api_budget_monitor.runtime.tunnel_client_path", return_value=Path(directory) / "tunnel-client.exe"), \
                 patch("api_budget_monitor.runtime.has_tunnel_credential", return_value=True), \
                 patch("api_budget_monitor.runtime.tunnel_health_port", return_value=47832), \
                 patch.object(manager, "_spawn_worker", side_effect=spawn):
                (Path(directory) / "profile.yaml").touch()
                (Path(directory) / "tunnel-client.exe").touch()
                result = manager.start()
            self.assertEqual(sequence, ["backend", "tunnel"])
            self.assertEqual((result.backend, result.tunnel), ("Running", "Connected"))

    def test_backend_start_failure_does_not_start_tunnel(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            active = set()
            spawn = Mock(side_effect=lambda component: active.add(component) or True)
            manager._valid_backend = lambda: (Path(directory), "node")
            manager._worker_running = lambda component: component in active
            with patch("api_budget_monitor.runtime._backend_probe", return_value=BackendProbe("stopped")), \
                 patch("api_budget_monitor.runtime._tunnel_probe", return_value="stopped"), \
                 patch.object(manager, "_spawn_worker", spawn):
                manager.start()
            self.assertEqual([call.args[0] for call in spawn.call_args_list], ["backend"])

    def test_invalid_service_path_returns_without_spawning_a_command(self):
        with tempfile.TemporaryDirectory() as directory:
            config = AppConfig(external_agents=ExternalAgentsRuntimeConfig(service_path=directory))
            manager = RuntimeManager(Path(directory) / "app", config, start_timeout=0, poll_interval=0)
            with patch("api_budget_monitor.runtime._backend_probe", return_value=BackendProbe("error")), \
                 patch("api_budget_monitor.runtime._tunnel_probe", return_value="needs_configuration"), \
                 patch.object(manager, "_spawn_worker") as spawn:
                manager.start()
            spawn.assert_not_called()

    def test_mismatched_owner_record_is_not_terminated(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            owner_file = manager._owner_path("backend")
            owner_file.write_text(json.dumps({"pid": 99, "started": "old", "image": "python.exe"}), encoding="utf-8")
            with patch("api_budget_monitor.runtime._process_identity", return_value={"pid": 99, "started": "new", "image": "python.exe"}), \
                 patch("api_budget_monitor.runtime._terminate_owner") as terminate:
                manager._stop_worker("backend")
            terminate.assert_not_called()

    def test_worker_launch_is_detached_from_monitor_lifetime(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            fake = Mock(pid=12345)
            with patch("api_budget_monitor.runtime.subprocess.Popen", return_value=fake) as popen, \
                 patch("api_budget_monitor.runtime._process_identity", return_value={"pid": 12345, "started": "1", "image": "python.exe"}):
                self.assertTrue(manager._spawn_worker("backend"))
            kwargs = popen.call_args.kwargs
            if os.name == "nt":
                flags = kwargs["creationflags"]
                self.assertTrue(flags & getattr(subprocess, "DETACHED_PROCESS", 0x8))
                self.assertTrue(flags & getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
                self.assertTrue(flags & getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0x01000000))
            self.assertEqual(kwargs["stdout"], subprocess.DEVNULL)

    def test_tunnel_key_is_passed_through_environment_not_process_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "external-agents.yaml"
            profile.write_text('health:\n  listen_addr: "127.0.0.1:47832"\n', encoding="utf-8")
            client = Path(directory) / "tunnel-client.exe"
            client.touch()
            config = AppConfig(external_agents=ExternalAgentsRuntimeConfig(service_path=directory))
            key = "test-tunnel-runtime-key"
            with patch("api_budget_monitor.runtime.tunnel_profile_path", return_value=profile), \
                 patch("api_budget_monitor.runtime.tunnel_client_path", return_value=client), \
                 patch("api_budget_monitor.runtime.get_tunnel_credential", return_value=key):
                command, _, environment, logged_credential = _worker_command("tunnel", config, Path(directory), Path(directory))
            self.assertNotIn(key, command)
            self.assertEqual(environment["CONTROL_PLANE_API_KEY"], key)
            self.assertEqual(logged_credential, key)

    def test_runtime_log_redacts_the_tunnel_key(self):
        self.assertEqual(_redact_log_line("key=test-secret-value", "test-secret-value"), "key=[REDACTED]")

    def test_tunnel_status_requires_a_successful_health_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            with patch("api_budget_monitor.runtime._backend_probe", return_value=BackendProbe("stopped")), \
                 patch("api_budget_monitor.runtime._tunnel_probe", return_value="error"), \
                 patch("api_budget_monitor.runtime.has_tunnel_credential", return_value=True), \
                 patch.object(manager, "_worker_running", return_value=False):
                result = manager.snapshot()
            self.assertEqual(result.tunnel, "Error / Unknown")
            self.assertNotEqual(result.tunnel, "Connected")

    def test_tunnel_connected_requires_health_cli_control_plane_confirmation(self):
        class HealthResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_):
                return False

        with tempfile.TemporaryDirectory() as directory:
            profile = Path(directory) / "profile.yaml"
            client = Path(directory) / "tunnel-client.exe"
            profile.touch()
            client.touch()
            config = AppConfig(external_agents=ExternalAgentsRuntimeConfig(service_path=directory))
            with patch("api_budget_monitor.runtime.tunnel_profile_path", return_value=profile), \
                 patch("api_budget_monitor.runtime.tunnel_client_path", return_value=client), \
                 patch("api_budget_monitor.runtime.tunnel_health_port", return_value=47832), \
                 patch("api_budget_monitor.runtime.urlopen", return_value=HealthResponse()), \
                 patch("api_budget_monitor.runtime.subprocess.run", return_value=Mock(returncode=1)) as health:
                self.assertEqual(_tunnel_probe(config, Path(directory)), "error")
            self.assertIn("--require-control-plane-poll", health.call_args.args[0])

    def test_backend_probe_uses_authenticated_local_health_and_gate_metadata(self):
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.headers.get("Authorization") != "Bearer local-test-token":
                    self.send_response(401)
                    self.end_headers()
                    return
                body = b'{"status":"ready","paid_calls_enabled":false}'
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_):
                pass

        with tempfile.TemporaryDirectory() as directory:
            service = Path(directory)
            (service / "src").mkdir()
            (service / "src" / "server.js").touch()
            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with patch("api_budget_monitor.runtime.backend_port", return_value=server.server_port), \
                     patch("api_budget_monitor.runtime.read_mcp_token", return_value="local-test-token"):
                    result = _backend_probe(service)
            finally:
                server.shutdown()
                server.server_close()
            self.assertEqual(result, BackendProbe("ready", False))

    def test_missing_tunnel_key_is_reported_as_needs_authentication(self):
        with tempfile.TemporaryDirectory() as directory:
            manager = self.manager(directory)
            with patch("api_budget_monitor.runtime._backend_probe", return_value=BackendProbe("stopped")), \
                 patch("api_budget_monitor.runtime._tunnel_probe", return_value="stopped"), \
                 patch("api_budget_monitor.runtime.has_tunnel_credential", return_value=False), \
                 patch.object(manager, "_worker_running", return_value=False):
                self.assertEqual(manager.snapshot().tunnel, "Needs authentication/configuration")

    def test_transition_notifications_are_emitted_once_per_state_change(self):
        was_ready = RuntimeSnapshot("Running", "Connected", False)
        unavailable = RuntimeSnapshot("Stopped", "Disconnected / Stopped", False)
        self.assertEqual(len(runtime_transition_messages(was_ready, unavailable)), 2)
        self.assertEqual(runtime_transition_messages(unavailable, unavailable), [])
        recovered = RuntimeSnapshot("Running", "Connected", False)
        self.assertEqual(len(runtime_transition_messages(unavailable, recovered)), 1)


if __name__ == "__main__":
    unittest.main()
