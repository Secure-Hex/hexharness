"""shodan_host parsing + it drives the out-of-band secret flow via required_secrets."""
from __future__ import annotations

from hexharness.control.secrets import CallbackSecretRequester, DenySecretRequester
from hexharness.control.vault import Vault
from hexharness.events.types import EventType
from hexharness.tools.base import RiskLevel
from hexharness.tools.native.shodan import ShodanHostTool

from tests.conftest import ctx, make_control
from hexharness.control.policy import Autonomy, Mode, Phase


def test_declares_required_secret_and_scope():
    t = ShodanHostTool(Vault())
    assert t.required_secrets == ["SHODAN_API_KEY"]
    assert t.scope_sensitive and t.target_field == "host"
    assert t.risk_level is RiskLevel.ACTIVE


async def test_control_plane_prompts_for_key_then_tool_uses_it():
    # operator supplies the key out-of-band when the control plane asks
    cp, events = make_control(scope=__import__("hexharness.control.scope_guard",
                              fromlist=["Scope"]).Scope(cidrs=("1.1.1.0/24",)))
    cp.vault = Vault()
    cp.secret_requester = CallbackSecretRequester(lambda name, reason: "sk-shodan")

    tool = ShodanHostTool(cp.vault, opener=lambda url: {"org": "ACME", "ports": [22, 80],
                                                        "data": [{"port": 22, "product": "OpenSSH"}], "vulns": []})
    d = await cp.authorize(ctx(Mode(Autonomy.AUTO, Phase.ENUMERATION)), tool, {"host": "1.1.1.10"})
    assert d.allowed
    assert cp.vault.get("SHODAN_API_KEY") == "sk-shodan"
    # the secret VALUE never appears in the audit log — only its name
    assert "sk-shodan" not in str([e.payload for e in events.all()])
    assert any(e.type is EventType.SECRET_PROVIDED for e in events.all())

    out = await tool.run({"host": "1.1.1.10"})
    assert "ports: 22, 80" in out and "OpenSSH" in out


async def test_cancel_secret_denies():
    cp, _ = make_control(scope=__import__("hexharness.control.scope_guard",
                         fromlist=["Scope"]).Scope(cidrs=("1.1.1.0/24",)))
    cp.vault = Vault()
    cp.secret_requester = DenySecretRequester()
    d = await cp.authorize(ctx(Mode(Autonomy.AUTO, Phase.ENUMERATION)), ShodanHostTool(cp.vault), {"host": "1.1.1.10"})
    assert d.effect.value == "deny" and d.gate == "secrets"
