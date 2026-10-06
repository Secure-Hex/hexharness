from __future__ import annotations

from hexharness.knowledge import KnowledgeBase, KnowledgeSearchTool, MitreAttackTool
from hexharness.tools.base import RiskLevel


async def test_attack_lookup_by_id():
    out = await MitreAttackTool().run({"query": "T1059"})
    assert "T1059" in out
    assert "Command and Scripting Interpreter" in out


async def test_attack_lookup_by_id_loose():
    # Accepts the bare number without the T prefix.
    out = await MitreAttackTool().run({"query": "1046"})
    assert "T1046" in out
    assert "Network Service Discovery" in out


async def test_attack_lookup_by_keyword():
    out = await MitreAttackTool().run({"query": "brute force"})
    assert "T1110" in out
    assert "Brute Force" in out


async def test_attack_lookup_miss():
    out = await MitreAttackTool().run({"query": "T9999"})
    assert "No ATT&CK technique matched" in out


def test_tfidf_ranks_relevant_doc_first():
    kb = KnowledgeBase()
    kb.index([
        ("sql", "SQL injection testing with payloads and parameterized queries to fix it."),
        ("ports", "Port scanning with nmap to discover open network services and versions."),
        ("creds", "Password brute force and credential dumping from memory."),
    ])
    hits = kb.search("how do I test for sql injection", k=3)
    assert hits, "expected at least one hit"
    assert hits[0][0] == "sql"
    # Scores are sorted descending.
    scores = [s for _, s, _ in hits]
    assert scores == sorted(scores, reverse=True)


def test_tfidf_returns_snippet_and_no_query_terms_empty():
    kb = KnowledgeBase()
    kb.index([("a", "alpha beta gamma"), ("b", "delta epsilon")])
    assert kb.search("", k=3) == []
    hits = kb.search("beta", k=3)
    assert hits[0][0] == "a"
    assert "beta" in hits[0][2]


async def test_knowledge_search_tool_returns_snippets():
    tool = KnowledgeSearchTool()
    assert tool.risk_level is RiskLevel.PASSIVE
    assert tool.scope_sensitive is False
    out = await tool.run({"query": "nmap port scan network service discovery"})
    assert "network_recon.md" in out
    assert "nmap" in out.lower()


async def test_knowledge_search_tool_empty():
    out = await KnowledgeSearchTool().run({"query": ""})
    assert "empty query" in out
