# API Security Testing Playbook

APIs (REST/GraphQL) expose object and function endpoints directly, so authorization flaws
dominate. Start by mapping the API: collect endpoints from documentation, a Postman collection
(`postman_list`), traffic, or archived URLs, noting each method, path, parameters and the auth
it expects.

Test broken object-level authorization (BOLA/IDOR) by swapping an object id for one belonging
to another user and checking whether the server returns it. Test broken function-level
authorization by calling admin or privileged operations as a low-privilege user. Also probe
mass assignment (sending extra fields like `role` or `isAdmin`), missing rate limiting, and
excessive data exposure in responses. Replay single requests with `postman_run` to confirm.
Confirm an issue when a request you should not be allowed to make returns the protected data or
performs the privileged action. Map authorization findings to CWE-639 / CWE-285 and ATT&CK
technique T1190 (Exploit Public-Facing Application).

Remediation: enforce object- and function-level authorization server-side on every request,
bind objects to the authenticated principal, use allowlists for writable fields, apply rate
limiting, and return only the fields the client needs.
