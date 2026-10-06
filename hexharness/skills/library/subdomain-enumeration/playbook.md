# Subdomain Enumeration

Goal: map the subdomain attack surface of an in-scope apex domain, then narrow to
hosts worth deeper testing. Every host you discover must be confirmed in-scope
before any active probing — the Scope Guard will reject out-of-scope targets, but
do not waste a turn discovering that.

## Preconditions
- An apex domain (e.g. `example.com`) that is explicitly in scope.
- ROE permits at least PASSIVE+ACTIVE recon for this phase.

## Steps
1. **Passive collection (no packets at target).** Pull known subdomains from
   Certificate Transparency logs and passive DNS. This is read-only OSINT and is
   safe before any authorization to touch the target.
2. **Resolve.** For each candidate, resolve A/AAAA/CNAME. Drop NXDOMAIN. Keep the
   wildcard answer aside — a wildcard record inflates the list with false hosts;
   detect it by resolving a random nonexistent label and discarding anything that
   matches that IP.
3. **Dedupe by resolved IP.** Many names collapse to one host; cluster them so you
   test each host once, not each name.
4. **Liveness triage.** Probe 80/443 for an HTTP response. Record status code,
   final URL after redirects, server header, and page title.
5. **Prioritize.** Rank for follow-up: non-standard ports, dev/staging/admin
   hostnames, distinct tech stacks, and anything with auth surfaces.

## Output
A table of `subdomain → IP → open web ports → title/status`, plus a shortlist of
high-interest hosts and the reason each was flagged.

## Pitfalls
- Wildcard DNS producing phantom hosts — always run the random-label check.
- Treating a name as live without an actual response (NXDOMAIN != down).
- Probing a resolved IP that falls outside the engagement's scope.
