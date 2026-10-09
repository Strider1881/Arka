# Deploy (private VM / tunnel)

Operator is two long-running Python processes plus Playwright Chromium:

| Process | Default | Public? |
|---------|---------|---------|
| AcmeCorp Procure portal | `127.0.0.1:8765` | **No** — keep loopback; browser automation uses `PORTAL_BASE_URL` |
| Operator UI | `127.0.0.1:8877` | Only behind **HTTP Basic Auth** (or SSH tunnel / VPN / Access) |

The Operator UI has **no product login**. Never bind it to `0.0.0.0` or a public tunnel without `OPERATOR_UI_BASIC_AUTH_*`.

## Local / private VM

```bash
cp deploy.env.example deploy.env   # edit secrets; never commit
make setup
make deploy-up                     # portal + UI, health-checked
# … demo …
make deploy-down
```

Defaults bind **loopback**. For SSH access from your laptop:

```bash
ssh -L 8877:127.0.0.1:8877 -L 8765:127.0.0.1:8765 user@host
```

Then open `http://127.0.0.1:8877` locally.

## Shareable URL (Cloudflare quick tunnel)

Exposes **only** the Operator UI. Portal stays on loopback.

```bash
# In deploy.env — required:
OPERATOR_UI_BASIC_AUTH_USER=evaluator
OPERATOR_UI_BASIC_AUTH_PASS=<strong-secret>

make deploy-up
make deploy-tunnel                 # prints https://….trycloudflare.com
```

Limitations: quick-tunnel URLs are ephemeral (process lifetime; URL changes on restart). Free; no Cloudflare account required for trycloudflare.com. For a stable hostname, use a named Cloudflare Tunnel + Access (account required).

## Safety invariants

1. `deploy-up` **refuses** non-loopback `OPERATOR_HOST` without Basic Auth env vars.
2. `deploy-tunnel` **refuses** to start without Basic Auth.
3. `/health` stays unauthenticated for probes; all HTML/API routes require Basic Auth when configured.
4. Secrets live only in `deploy.env` / provider env — never in git (see `.gitignore`).
5. FakeLLM runs when `ANTHROPIC_API_KEY` is unset; do not claim Haiku scores without a keyed run.

## Demo honesty (INV-1003)

Operator **approve** on INV-1003 ≠ portal ledger `APPROVED`. After operator approval the portal row is `PENDING_APPROVAL` (manager gate). Proof copy: **Submitted, awaiting manager approval**.

## Makefile targets

| Target | Purpose |
|--------|---------|
| `make deploy-up` | Start portal + UI |
| `make deploy-down` | Stop portal + UI (+ tunnel) |
| `make deploy-tunnel` | Cloudflare quick tunnel for UI |
| `make portal` / `make ui` | Unchanged local interactive workflow |
| `make demo` / `make eval` | Unchanged |

## Not used

GitHub Pages (static only). Prefer this process deploy, Fly/Railway/Render with secrets + auth, or a named tunnel — not Pages.
