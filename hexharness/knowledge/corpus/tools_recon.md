# Capability Reference: Recon Tools

Active/passive reconnaissance tools. Most are scope-sensitive (the target must be in scope);
the heavier scanners are INTRUSIVE and require approval.

## dns_lookup
Risk ACTIVE. Approval: no. Scope-sensitive: yes. Inputs: host. Resolve a hostname to its
A/AAAA records. Quick first step to turn a name into addresses before scanning.

## dns_enum
Risk ACTIVE. Approval: no. Scope-sensitive: yes. Inputs: host. Enumerate DNS records
(A/AAAA/MX/NS/TXT) via the native resolver (no sandbox). Use to map a domain's mail,
nameserver and TXT surface early in recon.

## whois_lookup
Risk PASSIVE. Approval: no. Scope-sensitive: yes. Inputs: domain. Raw WHOIS registration
lookup. Passive OSINT for registrant, dates and nameservers without touching the target.

## port_scan
Risk INTRUSIVE. Approval: yes. Scope-sensitive: yes. Inputs: host, ports, flags (any nmap
flags: SYN/version/OS/NSE). Sandboxed nmap scan with raw sockets. The core single-host port
and service discovery step; pass `flags` to tune the scan.

## parallel_scan
Risk INTRUSIVE. Approval: yes. Scope-sensitive: no (out-of-scope hosts skipped
automatically). Inputs: hosts list, flags. nmap across MANY hosts concurrently. Use when
sweeping a whole in-scope range rather than one host.

## banner_grab
Risk ACTIVE. Approval: no. Scope-sensitive: yes. Inputs: host, port, optional probe. Open a
TCP connection, optionally send a probe, read ~2KB of the service banner. Use to fingerprint
a service on a known open port.

## ssh_info
Risk ACTIVE. Approval: no. Scope-sensitive: yes. Inputs: host, port. Read the SSH
identification banner (e.g. `SSH-2.0-OpenSSH_9.6`). Quick version fingerprint of an SSH
service.

## ftp_check
Risk ACTIVE. Approval: no. Scope-sensitive: yes. Inputs: host, port. Attempt an anonymous FTP
login and list the root directory. Use to detect anonymous/open FTP exposure.

## http_probe
Risk ACTIVE. Approval: no. Scope-sensitive: yes. Inputs: url. GET a URL and report status,
key/security response headers, and the page `<title>`. First-look tool for a web service;
good inside a `for_each` over discovered ports.

## smb_enum
Risk INTRUSIVE. Approval: yes. Scope-sensitive: yes. Inputs: host. List SMB shares anonymously
via smbclient (sandboxed). Use to find exposed/anonymous Windows shares.

## browser
Risk ACTIVE. Approval: no. Scope-sensitive: yes. Inputs: url, steps (list of
{action, selector?, value?}). Drive a headless Playwright browser: open a URL, click/fill/
press/wait, read page text, capture screenshots to the workspace. Use for web app testing and
visual evidence.
