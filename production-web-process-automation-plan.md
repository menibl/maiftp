# Production Web Process Automation Platform - Implementation Plan

## 1. Goal

Build a production-ready local/self-hosted system that can automate repeatable browser processes for clients: log in, handle OTP challenges through an approved human/agent bridge, navigate client portals, download documents, and return verified outputs with audit logs.

The system must be reliable enough for client work, secure enough to handle credentials, and maintainable when websites change.

## 2. Product Scope

### Primary Use Cases

- Automate client billing portals, supplier portals, government portals, and SaaS dashboards.
- Download receipts, invoices, reports, certificates, statements, and other client documents.
- Run workflows manually, on schedule, or from an agent command.
- Pause safely when OTP, CAPTCHA, consent, or unexpected user action is required.
- Produce a clear run result: success/failure, downloaded files, screenshots, logs, and audit metadata.

### Non-Goals for the First Production Version

- Fully autonomous solving of hostile anti-bot flows.
- Storing OTPs.
- Bypassing CAPTCHA, MFA, or site security controls.
- Depending on a hosted third-party automation service.
- Letting an LLM freely control the whole browser without deterministic guardrails.

## 3. Recommended Architecture

Use Playwright as the deterministic browser engine, with a structured workflow runner around it.

The core idea:

1. A workflow recipe defines the expected process.
2. A deterministic runner executes the recipe.
3. A secure secret store provides credentials.
4. An OTP/action bridge asks the main agent or operator for live codes.
5. A verification layer confirms the downloaded output is correct.
6. Logs, screenshots, and audit records are stored for client accountability.

```text
Client Request / Schedule / Agent
        |
        v
Workflow Orchestrator
        |
        v
Workflow Runner CLI / API
        |
        +--> Recipe Store
        +--> Secret Store
        +--> Browser Session Manager
        +--> OTP / Human Action Bridge
        +--> Download & Verification Service
        +--> Audit Log
```

## 4. System Components

### 4.1 Workflow Orchestrator

Responsible for starting, tracking, retrying, and reporting workflow runs.

Required features:

- Create a run with `client_id`, `workflow_id`, parameters, and requested output.
- Track status: `queued`, `running`, `waiting_for_input`, `succeeded`, `failed`, `cancelled`.
- Enforce concurrency limits per client and per domain.
- Retry only safe steps.
- Resume after OTP or human input.
- Store final result metadata.

Recommended first implementation:

- Local CLI plus small HTTP API.
- Later upgrade to a job queue such as Redis Queue, Celery, or Dramatiq if needed.

### 4.2 Recipe Store

Stores versioned workflow definitions.

Each recipe should include:

- Workflow name and version.
- Allowed domains.
- Required inputs.
- Required secrets.
- Browser mode preferences.
- Step list.
- Selector candidates per step.
- Timeout/retry policy.
- Expected download rules.
- Verification rules.
- Last successful run metadata.

Example shape:

```json
{
  "workflow_id": "acme_receipt",
  "version": 3,
  "allowed_domains": ["portal.acme.com"],
  "inputs": {
    "month": { "type": "string", "required": true }
  },
  "secrets": {
    "username": { "scope": "client" },
    "password": { "scope": "client" }
  },
  "steps": [
    {
      "id": "login_email",
      "action": "fill",
      "value": "{{secret:username}}",
      "selectors": [
        { "type": "role", "role": "textbox", "name": "Email" },
        { "type": "label", "value": "Email" },
        { "type": "css", "value": "input[name='email']" }
      ],
      "sensitive": true
    },
    {
      "id": "login_password",
      "action": "fill",
      "value": "{{secret:password}}",
      "selectors": [
        { "type": "label", "value": "Password" },
        { "type": "css", "value": "input[type='password']" }
      ],
      "sensitive": true
    },
    {
      "id": "submit_login",
      "action": "click",
      "selectors": [
        { "type": "role", "role": "button", "name": "Sign in" }
      ]
    },
    {
      "id": "otp",
      "action": "request_otp",
      "prompt": "Acme one-time code",
      "selectors": [
        { "type": "label", "value": "One-time code" }
      ],
      "timeout_seconds": 180
    },
    {
      "id": "download_receipt",
      "action": "download",
      "selectors": [
        { "type": "role", "role": "button", "name": "Download receipt" }
      ],
      "save_as": "receipt-{{input:month}}.pdf",
      "verify": {
        "file_type": "pdf",
        "min_size_bytes": 10000,
        "must_contain_text": ["Receipt", "{{input:month}}"]
      }
    }
  ]
}
```

### 4.3 Browser Session Manager

Responsible for Playwright browser setup and isolation.

Production requirements:

- Use a fresh isolated browser context per run.
- Support headed mode for debugging and learning.
- Support headless mode for scheduled production runs.
- Store traces, screenshots, and videos only when needed.
- Redact sensitive fields from traces and logs.
- Never reuse browser state across clients unless explicitly configured.
- Support proxy settings per client if required.
- Detect navigation outside allowed domains and stop the run.

### 4.4 Secret Store

Credentials must never live in recipes, logs, screenshots, or LLM prompts.

Recommended design:

- Desktop: OS keychain through Python `keyring`.
- Server: encrypted secrets file or database table.
- Master key: environment variable, Docker secret, Windows DPAPI, macOS Keychain, cloud KMS, or another approved secret manager.
- Scope secrets by client and workflow.
- Rotate secrets without editing recipes.
- Log secret access events without logging values.

Required commands:

```text
set-secret --client CLIENT --name NAME
list-secrets --client CLIENT
delete-secret --client CLIENT --name NAME
test-secret-access --client CLIENT
```

### 4.5 OTP and Human Action Bridge

The runner must pause and request live input through a structured protocol.

The bridge should support:

- OTP from email.
- OTP from SMS forwarded to email.
- OTP entered manually by an operator.
- Approval prompts.
- "I cannot continue" responses.
- Timeouts and retry limits.

Recommended protocol:

Runner emits a JSON event:

```json
{
  "event": "input_required",
  "run_id": "run_123",
  "type": "otp",
  "client_id": "client_acme",
  "workflow_id": "acme_receipt",
  "hint": "Acme one-time code",
  "expires_in_seconds": 180
}
```

The orchestrator or agent responds:

```json
{
  "run_id": "run_123",
  "type": "otp_response",
  "value": "123456"
}
```

Transport options:

- MVP: subprocess stdout/stdin with newline-delimited JSON.
- Production: local HTTP API or websocket.
- Server scale: queue-based events.

Important rule: OTP values are never stored after use.

### 4.6 Download and Verification Service

Do not treat "file downloaded" as success by itself.

Verification should include:

- File exists.
- File size is above minimum.
- File extension and MIME type match expected output.
- PDF text contains expected strings.
- Optional checksum.
- Optional invoice number, month, client name, or amount validation.
- Final screenshot of success page.

Each successful run should return:

```json
{
  "status": "succeeded",
  "run_id": "run_123",
  "files": [
    {
      "path": "downloads/client_acme/acme_receipt/run_123/receipt-2026-05.pdf",
      "type": "pdf",
      "verified": true
    }
  ],
  "audit_log": "runs/run_123/audit.json"
}
```

### 4.7 Audit, Logging, and Observability

Every run must produce a structured audit trail.

Store:

- Client ID.
- Workflow ID and version.
- Run ID.
- Start and end time.
- Parameters used.
- Domains visited.
- Steps completed.
- Input requests made.
- Downloaded files.
- Verification result.
- Failure reason.
- Screenshots or trace links when safe.

Never store:

- Passwords.
- OTP values.
- Session cookies unless explicitly encrypted and required.
- Full page screenshots containing sensitive client data unless there is a retention policy.

## 5. Learning and Maintenance Workflow

For production, do not rely on "watch once and run forever."

Use this workflow:

1. Create or update a recipe in headed mode.
2. Capture Playwright codegen/trace as a helper artifact.
3. Convert the flow into a structured recipe.
4. Mark sensitive fields before saving.
5. Run validation against a test account.
6. Run once against the real client account with operator supervision.
7. Promote the recipe version to production.
8. Monitor future runs for failures.

Learning automation can be added, but it should assist recipe creation rather than silently generating production workflows.

## 6. Failure Handling

The runner should classify failures clearly.

Failure types:

- `selector_not_found`
- `navigation_timeout`
- `login_failed`
- `otp_timeout`
- `otp_invalid`
- `captcha_required`
- `unexpected_page`
- `download_missing`
- `download_verification_failed`
- `domain_violation`
- `secret_missing`
- `permission_required`

For each failure, store:

- Step ID.
- URL.
- Sanitized screenshot.
- Sanitized DOM snippet if safe.
- Suggested next action.

Retry policy:

- Retry transient waits/navigation.
- Do not retry login many times.
- Do not brute-force OTP.
- Stop immediately on domain violation.
- Escalate CAPTCHA or consent pages to human input.

## 7. Security and Compliance Requirements

Production client automation needs explicit guardrails.

Required:

- Written authorization from each client for each portal.
- Per-client data isolation.
- Per-client credentials.
- Least-privilege accounts where possible.
- Encryption at rest for secrets and sensitive run artifacts.
- TLS for any local/remote API.
- Role-based access for operators.
- Audit logs for secret access and workflow runs.
- Configurable retention policy.
- Manual confirmation before running a recipe on a new domain.
- No security bypassing.

Recommended:

- Separate production and development environments.
- Separate test clients/accounts.
- Signed workflow recipe versions.
- Immutable audit logs.
- Periodic credential rotation.
- Alerting on repeated failures.

## 8. Repository Structure

```text
web-process-automation/
  SKILL.md
  pyproject.toml
  README.md
  runner/
    cli.py
    orchestrator.py
    recipes.py
    replay.py
    selectors.py
    secrets.py
    otp_bridge.py
    downloads.py
    verification.py
    audit.py
    browser.py
    errors.py
  workflows/
    acme_receipt.json
  runs/
    .gitkeep
  tests/
    test_recipe_schema.py
    test_secret_redaction.py
    test_otp_bridge.py
    test_download_verification.py
    test_selector_resolution.py
  docs/
    recipe-format.md
    security.md
    operations.md
```

## 9. Phased Delivery Plan

### Phase 1: Production MVP Foundation

Build:

- CLI entry point.
- Recipe schema.
- Manual recipe authoring.
- Playwright deterministic runner.
- Secret store abstraction.
- OTP bridge over newline-delimited JSON.
- Download capture.
- PDF/basic file verification.
- Audit log.
- Error classification.

Exit criteria:

- One real workflow can run end-to-end with OTP.
- Secrets are never written to recipe or logs.
- Failed runs produce useful debugging artifacts.

Estimated effort: 1-2 weeks.

### Phase 2: Client-Ready Operations

Build:

- Client/workflow/run IDs.
- Per-client secret scopes.
- Allowed-domain enforcement.
- Retention policy.
- Sanitized screenshots and traces.
- Run result folders.
- Retry policy.
- Small local API for orchestration.
- Operator input UI or agent bridge.

Exit criteria:

- Multiple clients can be automated without data mixing.
- Operator can approve/provide OTP when required.
- Every run has a clear audit record.

Estimated effort: 2-3 weeks.

### Phase 3: Recipe Learning Tools

Build:

- Headed learning mode.
- Playwright trace/codegen capture.
- Recipe draft generator.
- Selector candidate ranking.
- Secret-field marking UI/prompt.
- Test-run validator.
- Recipe versioning and promotion.

Exit criteria:

- New workflows can be created faster, but still reviewed before production.
- Generated recipes are validated before being used for clients.

Estimated effort: 2-4 weeks.

### Phase 4: Hardening and Scale

Build:

- Queue-based runs.
- Worker processes.
- Dashboard.
- Failure alerts.
- More advanced PDF/data validation.
- Optional AI-assisted repair suggestions.
- Optional self-healing for low-risk selector changes.
- Deployment packaging for Windows, macOS, and Linux server.

Exit criteria:

- System can run scheduled client workflows reliably.
- Failures are actionable.
- Maintenance burden is manageable.

Estimated effort: ongoing.

## 10. Recommended MVP Build Order

1. `recipes.py`: schema, validation, loading.
2. `secrets.py`: keyring/encrypted fallback, redaction utilities.
3. `otp_bridge.py`: JSON event protocol.
4. `browser.py`: Playwright context setup.
5. `selectors.py`: selector resolution and fallback.
6. `replay.py`: execute recipe steps.
7. `downloads.py`: capture and store files.
8. `verification.py`: verify downloaded output.
9. `audit.py`: structured run logs.
10. `cli.py`: `run`, `set-secret`, `validate-recipe`, `doctor`.
11. `SKILL.md`: instructions for the agent.
12. First production pilot workflow.

## 11. Key Design Decisions

Recommended decisions:

- Use Playwright Python as the browser engine.
- Use deterministic recipes as the production source of truth.
- Keep AI as an assistant for drafting or repair, not the primary execution engine.
- Start with manually reviewed recipes.
- Add learning mode only after the runner is stable.
- Store credentials in a scoped secret store.
- Never store OTPs.
- Require explicit allowed domains per workflow.
- Verify outputs before declaring success.
- Keep audit logs for every client run.

## 12. Risks

### Website Changes

Mitigation:

- Multiple selector candidates.
- Last-known-good screenshots.
- Recipe versioning.
- Fast repair workflow.

### MFA, CAPTCHA, and Consent Pages

Mitigation:

- Human/agent bridge.
- Clear failure classification.
- No bypass attempts.

### Credential Leakage

Mitigation:

- Sensitive field marking.
- Secret redaction tests.
- No raw values in traces or recipes.
- Encrypted secret store.

### Client Data Mixing

Mitigation:

- Per-client run folders.
- Per-client secret scopes.
- Separate audit records.
- Strong naming and access controls.

### Over-Automation

Mitigation:

- Approval gates.
- Allowed domains.
- Workflow version promotion.
- Operator review for new workflows.

## 13. Production Acceptance Checklist

- Secrets are encrypted and scoped per client.
- Recipes contain no raw credentials.
- OTP values are never stored.
- Runs cannot navigate outside allowed domains.
- Every run has a structured audit log.
- Downloads are verified.
- Failures are classified.
- Screenshots/traces are redacted or disabled for sensitive pages.
- Multiple clients can run without shared browser state.
- Recipes are versioned.
- There is a documented process for client authorization.
- There is a documented process for fixing broken workflows.
- There is a retention policy for run artifacts.

## 14. Final Recommendation

Build the deterministic runner first. That is the production core.

The "learn by watching once" feature should come later as a recipe-authoring assistant. For client automation, reliability, auditability, and secret safety are more important than making the first recording feel magical.

