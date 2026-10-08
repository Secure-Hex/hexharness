# Workflow Chaining (run_workflow)

Goal: run several tools as ONE ordered pipeline, passing values between steps, instead
of calling them one by one. Every step is still checked by the control plane (scope, ROE,
approval) exactly as a direct tool call — a step on an out-of-scope target is denied and
the pipeline stops.

## When to use it
- A fixed recon → enum → exploit sequence you want to run in one shot.
- Repeating the same step across many items (every open port, every host).
- A reproducible, auditable playbook (the whole pipeline is one recorded action).

Prefer calling tools directly when you need to *decide* the next step from a result the
pipeline can't express (complex branching). run_workflow handles order, templating,
one-level iteration and simple conditions — not arbitrary logic.

## Input shape
`run_workflow` takes `variables` (initial values) and `steps`. Each step:

| field | meaning |
|---|---|
| `tool` | tool name to run |
| `input` | that tool's input; strings may contain `{{var}}` templates |
| `output` | (optional) bind this step's result text to a variable name |
| `for_each` | (optional) a `{{var}}` holding a list/multiline value; runs the step once per item, with `{{item}}` bound |
| `condition` | (optional) skip the step unless truthy |

Templating is STRING-level (tool outputs are plain text):
- `{{target}}` → the value of `target`.
- A list (or a step's multiline output used in `for_each`) splits on newlines then commas.
- `condition` supports `{{x}} == text`, `{{x}} != text`, `{{x}} contains text`, or a bare
  `{{x}}` (truthy when non-empty and not `false`/`0`/`none`).

Execution: steps run in order, output binds to variables, and the pipeline STOPS at the
first failing step (or the first out-of-scope/denied step).

## Example: recon → per-service probe → conditional exploit
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
What happens: resolve DNS, scan ports (result bound to `ports`), probe each port
(`for_each` over `ports`, `{{item}}` is the port; results bound to `probes`), then run the
exploit ONLY if a probe mentioned nginx. Each `exploit_run` still needs approval and an
in-scope `target`.

## Gotchas
- `for_each` iterates a value you already bound with `output` in an earlier step.
- Outputs are text, so you cannot do `{{banners.service}}`; match with `contains` instead.
- Keep pipelines short and linear; for real branching, drive the tools yourself.
