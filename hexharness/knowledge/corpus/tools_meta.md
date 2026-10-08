# Capability Reference: Meta and Knowledge Tools

Tools for knowledge lookup, skills, engagement setup, workspace files, MCP extension, and
pipelines. Mostly PASSIVE; a few that modify state or connect out require approval.

## knowledge_search
Risk PASSIVE. Approval: no. Scope-sensitive: no. Inputs: query. Search the local pentest
playbook corpus (RAG) for guidance. Returns the top matching playbooks with a relevant
snippet each. Use to find technique guidance before acting.

## skill_lookup
Risk PASSIVE. Approval: no. Scope-sensitive: no. Inputs: optional skill_name. Browse the skill
library: call with no arguments to list skills (name, phase, description); pass skill_name to
load that skill's full playbook.

## skill_install
Risk ACTIVE. Approval: yes. Scope-sensitive: no. Inputs: either inline (name, description,
phase, playbook_markdown) or source_path for an existing on-disk skill. Install a new skill so
it becomes browsable/loadable. Always ask the operator whether to install for this project
(scope='project') or globally (scope='global').

## cwe_lookup
Risk PASSIVE. Approval: no. Scope-sensitive: no. Inputs: id. Look up a CWE weakness by id;
returns its name and a one-line description. Use when tagging a finding.

## mitre_attack_lookup
Risk PASSIVE. Approval: no. Scope-sensitive: no. Inputs: id (e.g. 'T1059') or keyword. Look up
MITRE ATT&CK techniques; returns id, name, tactic and a short description. Use to map a
finding or action to ATT&CK.

## engagement_draft
Risk PASSIVE. Approval: no. Scope-sensitive: no. Inputs: scope.domains/cidrs,
scope.exclusions, roe.max_risk, roe.max_autonomy, roe.max_phase, time windows/budget. Draft a
pentest engagement from a structured scope/ROE spec and write a validated engagement.yaml for
HUMAN review. Drafting does NOT activate it — a human must confirm before any session runs.

## file_read
Risk ACTIVE. Approval: no. Scope-sensitive: no. Inputs: path. Read a text file from the
engagement workspace.

## file_write
Risk INTRUSIVE. Approval: yes. Scope-sensitive: no. Inputs: path, content. Write/overwrite a
text file in the engagement workspace. Intrusive, requires approval.

## mcp_connect
Risk INTRUSIVE. Approval: yes. Scope-sensitive: no. Inputs: stdio command, args, secret_env.
Connect to an MCP server and add its remote tools to the live toolset. Any secrets the server
needs are named in secret_env and acquired out of band.

## run_workflow
Risk ACTIVE. Approval: no. Scope-sensitive: no. Inputs: variables, steps (each
{tool, input, output?, for_each?, condition?}). Run an ordered list of tool steps as one
pipeline, templating values between them. EVERY step still passes scope/ROE/approval. See the
workflow_chaining playbook for the full step shape and an example.
