# Reverse-Shell Handler

Goal: catch a reverse shell that an in-scope target calls back, then run commands in it.
All of this is gated: `listener_start` and `shell_exec` are DESTRUCTIVE and need approval,
and a connection whose peer IP is OUT of engagement scope is dropped on connect.

## Lifecycle (four tools, one shared handler)
1. **`listener_start`** `{port}` — bind a TCP listener on the host (this is your LPORT).
   It returns immediately and waits in the background for a shell to connect back.
2. **Deliver a payload** that connects to `LHOST:LPORT`. Generate one with
   `msfvenom_payload` (see the `exploitation` skill) or use a one-liner you drop via an
   exploit. LHOST is the host running HexHarness; LPORT is the port from step 1.
3. **`shell_sessions`** (no args) — list caught shells: each has an `id`, the peer IP, the
   port, and age. It also reports any peers dropped for being out of scope.
4. **`shell_exec`** `{session_id, command}` — run a command in that shell and read the
   output. Output is read until the shell goes quiet (time-based, no prompt detection), so
   keep commands non-interactive (no `vim`, no paging). For long output, redirect to a file.
5. **`listener_stop`** `{session_id?}` — close one session, or (no arg) stop ALL listeners
   and sessions. Everything is torn down automatically when the engagement session ends.

## Notes
- Scope is enforced at CONNECT time by peer IP, so shells you interact with are in-scope by
  construction. If a callback never appears, check `shell_sessions` for a dropped peer.
- One handler is shared across these tools for the whole session; session ids come from
  `shell_sessions`.
- This is post-exploitation on an AUTHORIZED target. Record what you do with `record_finding`.
