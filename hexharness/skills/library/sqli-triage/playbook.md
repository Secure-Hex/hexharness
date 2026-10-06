# SQL Injection Triage

Goal: decide whether a suspected parameter is actually injectable (CWE-89) and
classify the injection type, using the least intrusive proof possible. Stop at
confirmation — demonstrating impact beyond a benign proof needs explicit ROE
sign-off and usually human approval.

## Preconditions
- A specific request + parameter you suspect (URL query, form field, header,
  JSON value, or cookie).
- Target is in scope and ROE permits INTRUSIVE testing for this phase.

## Steps
1. **Baseline.** Capture the normal response: status, length, timing, and any
   error text. Everything below is a comparison against this baseline.
2. **Break then repair.** Send a single quote (or `)`/`"`) to try to break
   syntax; watch for a DB error, 500, or changed response. Then send a payload
   that repairs the statement (`'||'` , `' '` , comment-out) and confirm the
   response returns to baseline. Break-then-repair is far stronger evidence than
   an error alone.
3. **Boolean differential.** Compare `' AND 1=1-- -` versus `' AND 1=2-- -`. A
   stable, repeatable difference between true and false conditions confirms
   boolean-based injection.
4. **Time-based fallback.** If responses look identical (blind, no error), use a
   small conditional delay (e.g. 3s) and confirm it is reproducible and tracks the
   condition. Keep delays short; never stack long sleeps that amount to a DoS.
5. **Classify.** Record the type (error / union / boolean-blind / time-blind) and
   the back-end DBMS if fingerprintable from errors or function behavior.

## Output
A finding with: the exact request + parameter, the proof payloads and their
observed responses, the injection class, inferred DBMS, and CWE-89. Include the
benign proof only — no data exfiltration dumps.

## Pitfalls / do-NOT
- No `DROP`/`DELETE`/`UPDATE`, no stacked queries that mutate data, no mass row
  extraction. Those are DESTRUCTIVE and out of bounds for triage.
- A WAF block or random 500 is not a confirmation — require a repeatable,
  condition-tracking signal.
- Re-running time-based payloads many times can degrade the target; cap attempts.
