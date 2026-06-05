"""The Sandboxed Garden: Docker-based isolated execution environment."""

import os
import shutil
import tempfile
import time
import uuid
from contextlib import suppress
from dataclasses import dataclass
from typing import Optional

import docker
from docker.errors import DockerException, ImageNotFound

from orchestrator.utils import console


@dataclass
class SandboxResult:
    """Result of sandboxed code execution."""

    success: bool
    stdout: str
    stderr: str
    exit_code: int
    container_id: str
    execution_time_ms: float


class SandboxedGarden:
    """Manages Docker containers for isolated code execution."""

    def __init__(self, config: dict):
        sandbox_cfg = config.get("sandbox", {})
        tenancy_cfg = config.get("tenancy", {})
        self.image = sandbox_cfg["image"]
        self.timeout = sandbox_cfg["timeout_seconds"]
        self.memory = sandbox_cfg["memory_limit"]
        self.cpu = sandbox_cfg["cpu_limit"]
        self.network_mode = sandbox_cfg["network_mode"]
        self.read_only = sandbox_cfg["read_only_rootfs"]
        self.allowed_dirs = sandbox_cfg.get("allowed_directories", [])
        self.blocked_caps = sandbox_cfg.get("blocked_syscalls", [])
        self.pids_limit = int(sandbox_cfg.get("pids_limit", 256))
        self.tmpfs_size = str(sandbox_cfg.get("tmpfs_size", "64m"))
        self.cap_drop = sandbox_cfg.get("cap_drop") or self.blocked_caps
        self.run_as_user = sandbox_cfg.get("run_as_user")
        self.codebase_write_requires_tag = bool(
            sandbox_cfg.get("codebase_write_requires_tag", True)
        )
        self.tenant_storage_mount = tenancy_cfg.get("storage_mount", "/tenant_storage")
        self.tenant_secrets_mount = tenancy_cfg.get("secrets_mount", "/tenant_secrets")
        self.codebase_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                self._client = docker.from_env()
                console.print("[dim]Docker client initialized.[/dim]")
            except DockerException:
                raise RuntimeError(
                    "Docker is not running or not installed.\n"
                    "  1. Install:   brew install --cask docker\n"
                    "  2. Start:      open /Applications/Docker.app\n"
                    "  3. Wait for the whale icon to show 'Docker is running'\n"
                    "  4. Build:      docker build -f Dockerfile.sandbox -t constitutional-sandbox ."
                )
        return self._client

    @property
    def client(self):
        return self._get_client()

    def _ensure_image(self) -> None:
        """Ensure the sandbox image exists; try to build if missing."""
        try:
            self.client.images.get(self.image)
            return
        except ImageNotFound:
            console.print(
                f"[yellow]Sandbox image '{self.image}' not found. Attempting to build...[/yellow]"
            )
            dockerfile_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)), "Dockerfile.sandbox"
            )
            if os.path.exists(dockerfile_path):
                try:
                    self.client.images.build(
                        path=os.path.dirname(dockerfile_path),
                        dockerfile="Dockerfile.sandbox",
                        tag=self.image,
                    )
                    console.print(f"[green]Built sandbox image '{self.image}'.[/green]")
                except Exception as e:
                    console.print(f"[red]Failed to build image: {e}[/red]")
                    raise
            else:
                msg = (
                    f"No Dockerfile.sandbox found at {dockerfile_path}. "
                    "Please create the sandbox image manually."
                )
                console.print(f"[red]{msg}[/red]")
                raise RuntimeError(msg)

    def execute(
        self,
        code: str,
        language: str = "python",
        input_data: Optional[str] = None,
        work_dir: Optional[str] = None,
        network_enabled: bool = False,
        codebase_write: bool = False,
        tenant_storage_dir: Optional[str] = None,
        tenant_secrets_dir: Optional[str] = None,
    ) -> SandboxResult:
        """Execute code inside an isolated Docker container."""
        self._ensure_image()

        task_id = str(uuid.uuid4())[:8]
        own_dir = work_dir is None
        temp_dir = work_dir or tempfile.mkdtemp(prefix=f"orchestrator_{task_id}_")

        try:
            # Write code to file
            if language == "python":
                code_file = os.path.join(temp_dir, "script.py")
            elif language in ("sh", "bash"):
                code_file = os.path.join(temp_dir, "script.sh")
            else:
                code_file = os.path.join(temp_dir, "script.txt")

            with open(code_file, "w") as f:
                f.write(code)

            # Write optional input data
            if input_data:
                input_file = os.path.join(temp_dir, "input.txt")
                with open(input_file, "w") as f:
                    f.write(input_data)

            console.print(
                f"[dim]Spinning up sandbox container for task {task_id}...[/dim]"
            )

            # Security configuration
            security_opt = ["no-new-privileges:true"]
            cap_drop = self.cap_drop

            # Run the container
            if language == "python":
                cmd = ["python3", "/workspace/script.py"]
            elif language in ("sh", "bash"):
                cmd = ["sh", "/workspace/script.sh"]
            else:
                cmd = ["cat", "/workspace/script.txt"]

            start = time.time()

            # Dynamic Network Switch: grant bridge access only when explicitly requested;
            # otherwise enforce full isolation with "none" regardless of config default.
            active_network = self.network_mode if network_enabled else "none"

            # Build volume config. We map the target codebase to /codebase
            volumes_dict = {temp_dir: {"bind": "/workspace", "mode": "rw"}}

            if tenant_storage_dir:
                tenant_storage_dir = os.path.abspath(tenant_storage_dir)
            if tenant_secrets_dir:
                tenant_secrets_dir = os.path.abspath(tenant_secrets_dir)

            # Map the repository root so /codebase is stable regardless of process cwd.
            codebase_mode = "rw" if codebase_write else "ro"
            volumes_dict[self.codebase_dir] = {"bind": "/codebase", "mode": codebase_mode}

            if tenant_storage_dir:
                volumes_dict[tenant_storage_dir] = {
                    "bind": self.tenant_storage_mount,
                    "mode": "rw",
                }

            if tenant_secrets_dir:
                volumes_dict[tenant_secrets_dir] = {
                    "bind": self.tenant_secrets_mount,
                    "mode": "ro",
                }

            tmpfs_mounts = None
            if self.read_only and self.tmpfs_size:
                tmpfs_mounts = {"/tmp": f"rw,noexec,nosuid,size={self.tmpfs_size}"}

            container = self.client.containers.run(
                image=self.image,
                command=cmd,
                volumes=volumes_dict,
                working_dir="/workspace",
                network_mode=active_network,
                mem_limit=self.memory,
                cpu_quota=int(float(self.cpu) * 100000),
                cpu_period=100000,
                read_only=self.read_only,
                tmpfs=tmpfs_mounts,
                pids_limit=self.pids_limit,
                security_opt=security_opt,
                cap_drop=cap_drop,
                user=self.run_as_user,
                detach=True,
                stdout=True,
                stderr=True,
            )

            try:
                result = container.wait(timeout=self.timeout)
                # Capture stdout and stderr separately; calling logs() with both=True
                # merges the two streams into one undifferentiated byte string.
                stdout = container.logs(stdout=True, stderr=False, timestamps=False).decode(
                    "utf-8", errors="replace"
                )
                stderr = container.logs(stdout=False, stderr=True, timestamps=False).decode(
                    "utf-8", errors="replace"
                )
                exit_code = result.get("StatusCode", -1)
            except Exception:
                # Timeout or error
                container.kill()
                stdout = "Execution timed out or was interrupted."
                stderr = "Container killed by orchestrator (timeout or error)."
                exit_code = 137

            duration = int((time.time() - start) * 1000)

            # Cleanup
            with suppress(Exception):
                container.remove(force=True)

            success = exit_code == 0
            if not success:
                stdout += f"\n\n[Container exited with code {exit_code}]"

            console.print(
                f"[{'green' if success else 'red'}]"
                f"Sandbox execution {'succeeded' if success else 'failed'}"
                f" (exit {exit_code}, {duration}ms)[/{'green' if success else 'red'}]"
            )

            return SandboxResult(
                success=success,
                stdout=stdout,
                stderr=stderr,
                exit_code=exit_code,
                container_id=container.id[:12],
                execution_time_ms=duration,
            )

        finally:
            if own_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

    def health_check(self) -> bool:
        """Check if Docker is accessible and the sandbox image is available."""
        try:
            self.client.ping()
            self._ensure_image()
            return True
        except Exception as e:
            console.print(f"[red]Sandbox health check failed: {e}[/red]")
            return False