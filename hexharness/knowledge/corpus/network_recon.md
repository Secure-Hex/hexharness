# Network Reconnaissance Playbook

Reconnaissance begins with host discovery and port scanning to map the attack surface.
Use nmap to identify open TCP and UDP ports, running services, and software versions.
A typical sweep starts with a fast top-ports scan, then a targeted service/version
scan (`-sV`) and default script scan (`-sC`) against discovered hosts.

Enumerate network services such as SMB, SSH, HTTP, DNS, and SNMP. Banner grabbing and
service fingerprinting reveal versions that can be matched against known
vulnerabilities. This maps to ATT&CK technique T1046 (Network Service Discovery).

Record every open port, service, and version as evidence. Scope discipline matters:
only scan hosts explicitly in the engagement's rules of engagement, and prefer passive
or low-rate scans first to avoid disrupting production systems.
