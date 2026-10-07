# Duplicate Invoice Policy

**Owner:** Accounts Payable  
**Last reviewed:** 2026-03-01

## Definition

An invoice is a **duplicate** when either condition holds against an already-seen invoice (inbox or portal):

1. **Same vendor + same invoice number**, or  
2. **Same vendor + same amount + same invoice date**.

Vendor comparison uses the **canonical** vendor after alias resolution.

## Required action

- **Do not submit** a duplicate into Procure as a new payable.
- **Flag** the duplicate for AP review.
- Cite this policy and reference the original invoice number in the operator report.

## Demo case

- INV-1001 — Northwind Supplies, $1,240.00, invoice number INV-1001 (legitimate).
- INV-1004 — Northwind Supplies, $1,240.00, **same invoice number INV-1001** → treat as duplicate of INV-1001; flag; do not submit.

## Portal note

The Procure database enforces uniqueness on `(vendor_id, invoice_number)`. Operators should still detect duplicates from the inbox **before** attempting submit, because a failed insert is not a substitute for policy handling.
