# Workflow Chaining with run_workflow

The `run_workflow` tool runs an ordered list of tool steps as ONE pipeline, passing values
between steps, instead of calling each tool by hand. It handles order, `{{var}}` templating,
one-level iteration and simple conditions. EVERY step still passes the control plane (scope,
ROE, approval) exactly like a direct call — an out-of-scope or unapproved step is denied and
the pipeline stops there.

## Input shape
`run_workflow` takes `variables` (initial values) and `steps`. Each step is:

| field | meaning |
|---|---|
| `tool` | tool name to run |
| `input` | that tool's input; strings may contain `{{var}}` templates |
| `output` | (optional) bind this step's result text to a variable name, reused by later steps |
| `for_each` | (optional) a `{{var}}` holding a list/multiline value; runs the step once per item, with `{{item}}` bound |
| `condition` | (optional) skip the step unless truthy |

## Templating and control
- Templating is STRING-level (tool outputs are plain text): `{{target}}` expands to its value.
- A list, or a step's multiline output used in `for_each`, splits on newlines then commas.
- `output` binds a step's result to a variable; a later step reads it with `{{name}}`.
- `condition` supports `{{x}} == text`, `{{x}} != text`, `{{x}} contains text`, or a bare
  `{{x}}` (truthy when non-empty and not `false`/`0`/`none`).
- Steps run in order; the pipeline STOPS at the first failing (or denied) step.

## Example: recon -> port_scan -> per-port http_probe -> conditional exploit
```json
{
  "variables": { "target": "app.example" },
  "steps": [
    { "tool": "dns_enum", "input": { "host": "{{target}}" } },

    { "tool": "port_scan",
      "input": { "host": "{{target}}", "ports": "1-1000" },
      "output": "ports" },

    { "tool": "http_probe",
      "input": { "url": "http://{{target}}:{{item}}" },
      "for_each": "{{ports}}",
      "output": "probes" },

    { "tool": "exploit_run",
      "input": { "target": "{{target}}", "argv": ["sh", "-c", "echo run-exploit"] },
      "condition": "{{probes}} contains Server: nginx" }
  ]
}
```
Resolve DNS, scan ports (bound to `ports`), probe each port (`for_each` over `ports`,
`{{item}}` is the port, results bound to `probes`), then run the exploit ONLY if a probe
mentioned nginx. The `port_scan` and `exploit_run` steps still require approval and an
in-scope target.

## Gotchas
- `for_each` iterates a value you bound with `output` in an earlier step.
- Outputs are text — you cannot do `{{probes.title}}`; match with `contains` instead.
- Keep pipelines short and linear. For real branching, drive the tools yourself.
