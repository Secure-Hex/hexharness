"""Session container names must be valid Docker names even for non-ASCII engagements."""
import re

from hexharness.sandbox.executor import SandboxExecutor

DOCKER_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]+$")


def test_session_name_is_docker_safe():
    ex = SandboxExecutor()
    ws = ".hexharness/análisis-local-del-repositorio-morluto-rea/workspace"
    name = ex._session_name(ws)
    assert name == "hexharness-analisis-local-del-repositorio-morluto-rea"
    assert DOCKER_NAME.match(name)
    assert ex._session_name(".hexharness/日本/workspace") == "hexharness-default"
    assert ex._session_name(None) == "hexharness-default"
