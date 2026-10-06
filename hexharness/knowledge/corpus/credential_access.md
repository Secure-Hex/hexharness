# Credential Access Playbook

Credential access covers techniques for obtaining account names and secrets. Password
brute force and spraying attempt many guesses against login services; throttle and
respect lockout policies to avoid denial of service. This maps to ATT&CK technique
T1110 (Brute Force).

Once code execution is obtained, dump operating system credentials from memory, the
SAM/NTDS databases, or process memory such as LSASS. This maps to T1003 (OS Credential
Dumping). Harvested hashes can be cracked offline or passed directly to remote
services for lateral movement.

Reuse of valid accounts across systems maps to T1078 (Valid Accounts). Remediation
includes strong unique passwords, multi-factor authentication, and monitoring for
anomalous authentication patterns.
