# Capability Reference: Evidence and Reporting Tools

Tools for recording findings and producing the client report. All PASSIVE, no approval, not
scope-sensitive — but a finding only reaches the report after a human confirms it.

## record_finding
Risk PASSIVE. Approval: no. Scope-sensitive: no. Inputs: title, severity, target, description,
reproduction (PoC / step-by-step), evidence refs, CWE. Record a security finding as a
CANDIDATE in the evidence store. It reaches the report only after a human confirms it. Give a
clear reproduction so a human can verify the issue is real.

## list_findings
Risk PASSIVE. Approval: no. Scope-sensitive: no. Inputs: optional detail. List findings
recorded this engagement with status (candidate/confirmed/rejected), severity and target. Use
it before recording to avoid duplicates; set `detail=true` for full description, reproduction
and evidence.

## generate_report
Risk PASSIVE. Approval: no. Scope-sensitive: no. Inputs: output path. Render a client report
from the engagement's CONFIRMED findings into the workspace. The extension picks the format
(.html / .pdf / .docx / .md). Run it at the end once findings are confirmed.
