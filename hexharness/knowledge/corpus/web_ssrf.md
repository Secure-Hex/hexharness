# Server-Side Request Forgery (SSRF) Testing Playbook

SSRF occurs when an application fetches a URL supplied or influenced by the user, letting an
attacker make the server send requests to internal services it should not reach. Test any
parameter that takes a URL, hostname, or file reference (webhooks, link previews, PDF/image
fetchers, import-by-URL) by pointing it at a server you control and watching for the callback.

Confirm by retrieving something only the server can reach: cloud metadata endpoints
(`http://169.254.169.254/latest/meta-data/`), internal hosts, or `localhost` admin ports.
Watch for blind SSRF via out-of-band DNS/HTTP interactions, and test bypasses of weak filters
(alternate IP encodings, redirects, `[::]`, DNS rebinding). Map findings to CWE-918 and ATT&CK
technique T1190 (Exploit Public-Facing Application).

Remediation: allowlist destination hosts/schemes, resolve and validate the target IP (block
private/link-local/loopback ranges), disable unused URL schemes and redirects, require
authentication on internal services, and use IMDSv2 / disable the metadata endpoint where
possible.
