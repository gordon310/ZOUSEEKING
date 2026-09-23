# On-call and alert path

This runbook defines the pre-production response path. It does not authorize a deployment, database mutation, credential change, or customer-data access.

## Ownership and acknowledgement

Hermes is the first responder: acknowledge alerts within 15 minutes, preserve the alert and read-only evidence, and classify impact. Codex investigates and prepares a bounded fix or forward-fix. The user is the final decision-maker（最终决策）for customer communication, any authorized change, traffic reduction, rollback, provider action, or production deployment.

If Hermes has no acknowledgement after 15 minutes, notify the user. If user impact, suspected data exposure, payment loss, or a security boundary failure is indicated, notify the user immediately; do not wait for diagnosis. Codex provides a written mitigation recommendation within 60 minutes of a confirmed actionable incident, subject to access and evidence availability.

## Alert conditions

| Signal | Alert when | Initial action |
| --- | --- | --- |
| health | `/health/ready` fails twice in five minutes, or liveness fails once | Read endpoint/status and correlated logs; do not restart or deploy without authorization. |
| backup freshness | latest manifest exceeds the configured freshness threshold | Read manifest time/checksum and backup job result; user decides recovery action. |
| report outbox | failed, zombie-running, or pending-due count is non-zero | Read queue age/status and worker health; pause intake only with authorization. |
| quota anomaly | rate-limit storage unavailable, unexpected sustained 429s, or entitlement consumption spikes outside invited baseline | Preserve aggregate counts only; no raw IP/email in alert text. |
| payment webhook | any terminal webhook validation/processing failure or retry exhaustion | Preserve provider event identifier only; user decides payment-provider action. |

## 只读 self-check versus 授权变更

Read-only self-checks may inspect health endpoints, logs, metrics, migration ledger, queue aggregate counts, backup metadata, and checksums. They must redact secrets and PII. An authorized change requires the user's explicit approval and a target, rollback/forward-fix path, and verification query; examples include migrations, restarting/scaling services, changing rate-limit parameters, replaying jobs, provider configuration, traffic changes, billing changes, and any deployment. Never put secrets in this document, alerts, tickets, or logs.

## Escalation and closure

Hermes records timestamp, symptom, scope, read-only evidence, and current owner. Codex records the suspected class and proposed remediation. The user either authorizes a specific change or keeps the system in safe degraded mode. Close only after a fresh health/queue/backup or webhook verification appropriate to the incident; document residual risk and any follow-up. Production alert delivery and rehearsal remain `NOT_EXECUTED` until separately authorized.
