"""The HexHarness sandbox image: Kali + tools, built from a Dockerfile shipped in the
package. Built on demand (the executor auto-builds it if missing) or explicitly via
`python -m hexharness build-image`.
"""
from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

DEFAULT_SANDBOX_IMAGE = "hexharness/kali:latest"


def dockerfile_dir() -> Path:
    return Path(__file__).parent / "docker"


def is_hexharness_image(image: str) -> bool:
    return image == DEFAULT_SANDBOX_IMAGE


def image_exists(image: str, *, docker_bin: str = "docker") -> bool:
    if not shutil.which(docker_bin):
        return False
    import subprocess

    return subprocess.run([docker_bin, "image", "inspect", image],
                          capture_output=True).returncode == 0


async def build_image(tag: str = DEFAULT_SANDBOX_IMAGE, *, docker_bin: str = "docker",
                      on_output=None) -> tuple[bool, str]:
    """Build the sandbox image from the packaged Dockerfile. Returns (ok, tail-of-output)."""
    ctx = dockerfile_dir()
    cmd = [docker_bin, "build", "-t", tag, "-f", str(ctx / "Dockerfile"), str(ctx)]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    chunks: list[str] = []
    assert proc.stdout is not None
    async for raw in proc.stdout:
        line = raw.decode(errors="replace")
        chunks.append(line)
        if on_output:
            on_output(line.rstrip())
    await proc.wait()
    return proc.returncode == 0, "".join(chunks[-20:])
