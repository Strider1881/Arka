# Price and Quantity Tolerance Policy

**Owner:** Procurement  
**Last reviewed:** 2026-03-01

## Price variance

Invoice amount may differ from the matched PO amount by at most **2% of the PO amount**.

- Allowed: `|invoice_amount - po_amount| / po_amount <= 0.02`
- If variance exceeds 2%, **do not submit**. Flag as amount mismatch and escalate per `escalation.md`.

### Worked example

- PO-505 amount: $2,000.00  
- Invoice INV-1005 amount: $2,150.00  
- Variance: ($150 / $2000) = **7.5%** → exceeds 2% → **flag mismatch**.

## Quantity

Quantity on the invoice **must match the PO exactly**. There is **no** quantity tolerance.

## Currency

All demo POs and invoices are USD. Cross-currency invoices are out of scope; flag for human review.

## Application order

1. Resolve vendor (including aliases).  
2. Confirm a PO exists and vendor aligns.  
3. Check quantity exactness.  
4. Check price tolerance.  
5. Then apply approval threshold and duplicate rules.
