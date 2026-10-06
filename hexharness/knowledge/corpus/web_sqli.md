# SQL Injection Testing Playbook

SQL injection occurs when untrusted input is concatenated into a SQL query. To test,
probe each parameter with a single quote and observe error messages or behavioral
changes. Confirm with boolean-based payloads such as `' OR '1'='1` and time-based
payloads using `SLEEP()` or `pg_sleep()` to detect blind injection.

Enumerate the database by extracting version strings, table names from
information_schema, and column names. Tools like sqlmap automate detection and
exploitation, but manual confirmation of a single injectable parameter is the goal of
the testing phase. Map findings to CWE-89 and ATT&CK technique T1190 (Exploit
Public-Facing Application).

Remediation: use parameterized queries / prepared statements, apply least-privilege
database accounts, and validate input at the application boundary.
