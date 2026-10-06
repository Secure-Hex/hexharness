# Linux Privilege Escalation Playbook

After gaining a foothold with a low-privileged shell, enumerate the host for paths to
root. Check sudo rights with `sudo -l`, hunt for setuid/setgid binaries, inspect cron
jobs and systemd timers, and review writable files owned by privileged users.

Kernel and service exploits can yield privilege escalation when the host is unpatched;
map these to ATT&CK technique T1068 (Exploitation for Privilege Escalation). Abuse of
sudo, setuid binaries, or weak capabilities maps to T1548 (Abuse Elevation Control
Mechanism). Scheduled tasks abused for persistence or escalation map to T1053.

Collect system information — kernel version, distribution, installed packages — to
match against public exploits. Always capture proof of the escalation (a root shell or
a read of a root-only file) as evidence before proceeding.
