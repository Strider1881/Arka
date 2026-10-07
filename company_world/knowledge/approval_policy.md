# Approval Policy

**Owner:** Finance Controls  
**Manager on duty:** Priya Nair (`priya.nair@acmecorp.test`)  
**Last reviewed:** 2026-03-01

## Threshold

Any invoice with an amount **greater than $5,000.00 USD** requires manager approval before it can be treated as approved for payment.

- Amounts of **$5,000.00 or less** may be submitted directly (subject to match, duplicate, and vendor checks).
- Amounts **above $5,000.00** must be recorded as `PENDING_APPROVAL` and placed on the portal approval queue.

## Rules

1. **Named approver:** Priya Nair (manager role) is the default approver for AP invoice exceptions above threshold.
2. **No self-approval:** The person who requested approval must not decide their own request. The portal enforces this when the requester and decider are the same operator identity.
3. **Durable queue:** Approvals are recorded in AcmeCorp Procure’s approval queue with requester, status, and decision metadata.
4. **Decision values:** `APPROVED` or `REJECTED` only. A rejection stops payment processing for that invoice.
5. **Evidence:** The approval decision and policy citation must appear in the operator’s proof report.

## Portal behavior

When an operator submits an over-threshold invoice that otherwise passes checks:

1. Invoice status becomes `PENDING_APPROVAL`.
2. An approval queue item is created.
3. Work on that invoice pauses until a manager decides.
4. On approve → invoice `APPROVED`. On reject → invoice `REJECTED`.

## Examples

- INV-1003 at $12,400.00 → requires Priya’s approval.
- INV-1008 at $4,999.00 → under threshold; may submit without approval if match passes.
