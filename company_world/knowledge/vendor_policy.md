# Vendor Policy

**Owner:** Procurement / Compliance  
**Last reviewed:** 2026-03-01

## Vendor master

Every invoice must map to a vendor in the AcmeCorp Procure vendor master.

### Status values

- **ACTIVE** — may receive invoices and payments subject to other policies.
- **BLOCKED** — must **never** be paid. Do not submit invoices for payment. Refuse and escalate.

### Blocked vendors (seed)

- **Pied Piper Cloud** is `BLOCKED`. Invoices from this vendor (e.g. INV-1009) must be refused and escalated even if a PO exists.

## Aliases

Vendors may invoice under trade names. Resolve aliases via the vendor master **before** matching POs or checking duplicates.

| Alias on document | Canonical vendor |
|-------------------|------------------|
| Northwind Supply Co | Northwind Supplies |

Example: INV-1007 shows “Northwind Supply Co” and should match Northwind Supplies / PO-507.

## Matching rules

1. Normalize the invoice vendor name through alias resolution.
2. Reject if canonical vendor is `BLOCKED`.
3. Require the PO’s vendor to equal the canonical vendor after resolution.
4. Never invent a vendor or silently remap beyond the alias table.
