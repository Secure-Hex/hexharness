# Capability Reference: Analysis Tools

Static binary analysis and API-collection tools. The binary tools never execute the target;
Postman tools replay API requests.

## binary_info
Risk ACTIVE. Approval: no. Scope-sensitive: no. Inputs: path. Statically identify a binary in
the workspace: file type (via `file`) plus notable ASCII strings (via `strings -n 8`). Does
not execute the target. First step when triaging an unknown binary.

## checksec
Risk ACTIVE. Approval: no. Scope-sensitive: no. Inputs: path. Report binary hardening
(RELRO / NX / PIE / Stack Canary) for an ELF, parsed from `readelf -a`. Heuristic, does not
execute. Use to judge which memory-corruption techniques are viable.

## disassemble
Risk ACTIVE. Approval: no. Scope-sensitive: no. Inputs: path, optional section, max_lines.
Disassemble a workspace binary with `objdump -d` (optionally one section), truncated to
max_lines. Does not execute. Use to inspect specific functions during binary review.

## postman_list
Risk PASSIVE. Approval: no. Scope-sensitive: no. Inputs: collection path. List the requests
(name, method, path) in a local Postman collection. Use to see what an API collection covers
before running anything.

## postman_run
Risk INTRUSIVE. Approval: yes. Scope-sensitive: yes. Inputs: collection, request, base_url.
Execute ONE request from a Postman collection against base_url (the collection's method/path/
headers/body, the given host). Scope-checked and approval-gated. Use to exercise a specific
API endpoint during testing.
