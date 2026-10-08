# Cross-Site Scripting (XSS) Testing Playbook

XSS occurs when untrusted input is reflected into an HTML response (or stored and later
served) without proper encoding, letting an attacker run script in a victim's browser. Test by
injecting a benign marker into each parameter, form field and header that may be echoed, then
check where and how it appears in the response — HTML body, attribute, JavaScript context or
URL.

Confirm by escalating the marker to a context-appropriate payload: `<script>alert(1)</script>`
in an HTML body, `"><svg onload=alert(1)>` to break out of an attribute, or a JS-context
breakout for inline script. Stored XSS is confirmed when the payload executes for a different
request/user; reflected XSS executes in the same response; DOM XSS is confirmed by tracing a
sink like `innerHTML` or `document.write` fed from `location`. Map findings to CWE-79 and
ATT&CK technique T1059.007 (Command and Scripting Interpreter: JavaScript).

Remediation: context-aware output encoding, a strict Content-Security-Policy, framework
auto-escaping (do not disable it), HttpOnly cookies, and input validation at the boundary.
