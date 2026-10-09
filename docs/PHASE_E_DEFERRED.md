# Phase E — deferred

A second declarative procedure / tiny second workflow was **not** landed in submission hardening.

**Why deferred:** Introducing a second control plane beside `InvoicePipeline` risks breaking the hiring demo’s proven invoice path (events, policy clearance, a11y loop, independent verifier). D1 explicitly skipped a risky pipeline split for the same reason.

**What remains true:** Operator is a narrow invoice demo with reusable substrate (event store, FSM, tools, browser loop, verifier). Generic multi-workflow runtime is an explicit non-goal for v1.0-submission.

**If revisited later:** keep InvoicePipeline intact; add a declarative procedure registry behind a feature flag; ship one tiny non-invoice workflow with its own expected_outcomes + eval scenario — never by editing `expected_outcomes.json` to greenwash.
