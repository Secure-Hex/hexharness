"""Passive knowledge lookup. Read-only, not scope-sensitive — safe in any phase.

A tiny built-in CWE table today; the full MITRE ATT&CK/CWE + RAG knowledge layer is a
later phase. Still a real tool (static reference data), not a mock.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from hexharness.tools.base import RiskLevel, Tool

_CWE = {
    # --- existing entries (unchanged) ---
    "79": ("Cross-site Scripting (XSS)", "Improper neutralization of input during web page generation."),
    "89": ("SQL Injection", "Improper neutralization of special elements used in an SQL command."),
    "22": ("Path Traversal", "Improper limitation of a pathname to a restricted directory."),
    "78": ("OS Command Injection", "Improper neutralization of special elements used in an OS command."),
    "352": ("Cross-Site Request Forgery (CSRF)", "Web app does not verify a request was intentionally sent."),
    "287": ("Improper Authentication", "Incorrect proof of identity verification."),
    # --- CWE Top 25 (2023) + common web/app weaknesses ---
    "787": ("Out-of-bounds Write", "Software writes data past the end or before the beginning of a buffer."),
    "20": ("Improper Input Validation", "Input is not validated or is validated incorrectly before use."),
    "125": ("Out-of-bounds Read", "Software reads data past the end or before the beginning of a buffer."),
    "416": ("Use After Free", "Memory is referenced after it has been freed."),
    "434": ("Unrestricted Upload of File with Dangerous Type", "App allows upload of files with dangerous types that can be processed."),
    "862": ("Missing Authorization", "App does not perform an authorization check before granting access to a resource."),
    "476": ("NULL Pointer Dereference", "A NULL pointer is dereferenced, typically causing a crash."),
    "190": ("Integer Overflow or Wraparound", "A calculation produces a value larger than the integer type can hold and wraps around."),
    "502": ("Deserialization of Untrusted Data", "Untrusted data is deserialized without sufficient verification."),
    "77": ("Command Injection", "Improper neutralization of special elements used in a command."),
    "119": ("Improper Restriction of Operations within the Bounds of a Memory Buffer", "Operations on a buffer read from or write to locations outside its bounds."),
    "798": ("Use of Hard-coded Credentials", "Software contains hard-coded credentials for authentication or encryption."),
    "918": ("Server-Side Request Forgery (SSRF)", "Server fetches a remote resource from a user-controlled URL without validation."),
    "306": ("Missing Authentication for Critical Function", "A critical function does not require authentication."),
    "362": ("Race Condition", "Concurrent execution using a shared resource with improper synchronization."),
    "269": ("Improper Privilege Management", "Software does not properly assign, track, or revoke privileges."),
    "94": ("Code Injection", "Improper control of generation of code from externally influenced input."),
    "863": ("Incorrect Authorization", "App performs an authorization check but does so incorrectly."),
    "276": ("Incorrect Default Permissions", "Default permissions grant overly broad access to a resource at installation."),
    "200": ("Exposure of Sensitive Information to an Unauthorized Actor", "Sensitive information is disclosed to actors not authorized to see it."),
    "522": ("Insufficiently Protected Credentials", "Credentials are transmitted or stored without adequate protection."),
    "611": ("Improper Restriction of XML External Entity Reference (XXE)", "XML parser processes external entity references from untrusted input."),
    "732": ("Incorrect Permission Assignment for Critical Resource", "A critical resource is assigned permissions allowing unintended access."),
    "400": ("Uncontrolled Resource Consumption", "Software does not limit consumption of a resource, enabling exhaustion."),
    "427": ("Uncontrolled Search Path Element", "Software uses a search path containing an element under attacker control."),
    "601": ("URL Redirection to Untrusted Site (Open Redirect)", "App redirects to a URL from user-controlled input without validation."),
    "319": ("Cleartext Transmission of Sensitive Information", "Sensitive information is transmitted in cleartext over a network."),
    "538": ("Insertion of Sensitive Information into Externally-Accessible File or Directory", "Sensitive information is placed in a file or directory accessible to unauthorized actors."),
    "295": ("Improper Certificate Validation", "Software does not validate, or incorrectly validates, a certificate."),
    "915": ("Improperly Controlled Modification of Dynamically-Determined Object Attributes (Mass Assignment)", "App lets input modify object attributes that should not be externally writable."),
    "639": ("Authorization Bypass Through User-Controlled Key (IDOR)", "Access control is bypassed by manipulating a key referencing another user's resource."),
    "384": ("Session Fixation", "App reuses an existing session identifier across an authentication boundary."),
    "532": ("Insertion of Sensitive Information into Log File", "Sensitive information is written to log files accessible to unauthorized actors."),
    "614": ("Sensitive Cookie in HTTPS Session Without 'Secure' Attribute", "A security-sensitive cookie is set without the Secure attribute over HTTPS."),
}


class CweLookupInput(BaseModel):
    cwe_id: str = Field(description="CWE numeric id, e.g. '79' or 'CWE-79'")


class CweLookupTool(Tool):
    name = "cwe_lookup"
    description = "Look up a CWE weakness by id. Returns its name and a one-line description."
    input_model = CweLookupInput
    risk_level = RiskLevel.PASSIVE
    scope_sensitive = False
    requires_approval = False

    async def run(self, tool_input: dict) -> str:
        cid = str(tool_input.get("cwe_id", "")).upper().replace("CWE-", "").strip()
        entry = _CWE.get(cid)
        if not entry:
            return f"CWE-{cid}: not in local table. Known: {', '.join(sorted(_CWE))}"
        name, desc = entry
        return f"CWE-{cid} — {name}: {desc}"
