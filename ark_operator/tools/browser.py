"""Playwright Chromium browser tool (SPEC §6.7)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ark_operator.domain.enums import FailureKind, RiskLevel
from ark_operator.domain.models import Evidence, Failure, Observation
from ark_operator.tools.base import BaseTool, ToolResult
from ark_operator.tools.secrets import portal_operator_credentials, redact_secrets


class BrowserTool(BaseTool):
    """Persistent context per run; accessibility-tree observations with [eN] refs."""

    name = "browser"
    risk_class = RiskLevel.IRREVERSIBLE
    timeout_seconds = 60.0
    description = "Drive Chromium with a11y refs; login uses secrets provider"

    def __init__(
        self,
        *,
        base_url: str,
        evidence_dir: Path,
        headless: bool = True,
        prefer_label_first: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.evidence_dir = Path(evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self.headless = headless
        # When True (no episodic lessons yet), try visible button text before stable ids.
        # Under ui_rename this fails once and we fall back — teaching the lesson for run 2.
        self.prefer_label_first = prefer_label_first
        self._pw: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._refs: dict[str, Any] = {}
        self.evidence: list[Evidence] = []
        self._logged_in = False
        self.label_fallbacks = 0

    def close(self) -> None:
        if self._context:
            self._context.close()
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()
        self._pw = self._browser = self._context = self._page = None

    def _ensure(self) -> Any:
        if self._page is not None:
            return self._page
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        self._page = self._context.new_page()
        return self._page

    def _screenshot(self, label: str) -> Evidence:
        page = self._ensure()
        path = self.evidence_dir / f"{label}.png"
        page.screenshot(path=str(path), full_page=True)
        ev = Evidence(id=label, label=label, path=str(path), kind="screenshot")
        self.evidence.append(ev)
        return ev

    def _observe(self) -> dict[str, Any]:
        page = self._ensure()
        self._refs.clear()
        title = page.title()
        url = page.url
        elements = page.query_selector_all("a, button, input, select, textarea, [role='button']")
        lines: list[str] = []
        idx = 0
        for el in elements:
            try:
                if not el.is_visible():
                    continue
                tag = el.evaluate("e => e.tagName.toLowerCase()")
                role = el.get_attribute("role") or tag
                # Keep each element on ONE line so [eN] stays with id= (selects'
                # inner_text includes option newlines otherwise).
                raw_text = (el.inner_text() or el.get_attribute("value") or "").strip()
                text = " ".join(raw_text.split())[:80]
                eid = el.get_attribute("id") or ""
                name = el.get_attribute("name") or ""
                ref = f"e{idx}"
                self._refs[ref] = el
                label = text or eid or name or role
                if tag == "select":
                    # Do NOT use inner_text (all options concatenated — always starts
                    # with placeholder "Select…"). Expose selected value so agents can
                    # confirm select_option succeeded (generic dropdown semantics).
                    selected_val = ""
                    selected_label = ""
                    try:
                        selected_val = (el.input_value() or "").strip()
                    except Exception:
                        selected_val = ""
                    opts: list[str] = []
                    for opt in el.query_selector_all("option"):
                        ov = (opt.get_attribute("value") or "").strip()
                        ol = " ".join((opt.inner_text() or "").split())[:60]
                        if ov or ol:
                            opts.append(f"{ov}:{ol}" if ov else ol)
                        try:
                            if opt.is_selected():
                                selected_label = ol
                                if not selected_val:
                                    selected_val = ov
                        except Exception:
                            pass
                    opt_s = ",".join(opts[:24])
                    shown = selected_label or eid or name or "select"
                    lines.append(
                        f'[{ref}] select "{shown}" id={eid} '
                        f"value={selected_val!r} options=[{opt_s}]"
                    )
                elif tag == "input":
                    itype = el.get_attribute("type") or "text"
                    val = (el.input_value() if itype != "password" else "")[:80]
                    lines.append(f'[{ref}] input/{itype} "{label}" id={eid} value={val!r}')
                else:
                    lines.append(f'[{ref}] {role} "{label}" id={eid}')
                idx += 1
            except Exception:
                continue
        banners = []
        for sel in ("#flash", "#error", "#submit-banner", "#session-expired"):
            node = page.query_selector(sel)
            if node and node.is_visible():
                banners.append(node.inner_text().strip())
        return {
            "title": title,
            "url": url,
            "elements": lines,
            "banners": banners,
        }

    def _run(self, args: dict[str, Any]) -> ToolResult:
        action = str(args.get("action", "observe"))
        try:
            if action == "goto":
                return self._goto(str(args["url"]))
            if action == "login":
                return self._login()
            if action == "observe":
                obs = self._observe()
                return ToolResult(
                    ok=True,
                    observation=Observation(summary=f"On {obs['url']}", data=obs),
                    data=obs,
                )
            if action == "click":
                return self._click(str(args["ref"]))
            if action == "fill":
                return self._fill(str(args["ref"]), str(args["text"]))
            if action == "select":
                return self._select(str(args["ref"]), str(args["value"]))
            if action == "press":
                return self._press(str(args.get("key") or "Enter"), ref=args.get("ref"))
            if action == "screenshot":
                ev = self._screenshot(str(args.get("label", "shot")))
                return ToolResult(ok=True, data={"evidence": ev.model_dump()})
            if action == "submit_invoice":
                # CI / FakeLLM fast path only — real Haiku path uses a11y step loop.
                return self._submit_invoice(args)
            if action == "wait_for":
                page = self._ensure()
                if "text" in args:
                    page.wait_for_selector(f"text={args['text']}", timeout=10000)
                if "url" in args:
                    page.wait_for_url(re.compile(str(args["url"])), timeout=10000)
                return ToolResult(ok=True, observation=Observation(summary="wait done"))
            return ToolResult(
                ok=False,
                failure=Failure(kind=FailureKind.VALIDATION, message=f"Unknown action {action}"),
            )
        except Exception as exc:  # noqa: BLE001
            msg = redact_secrets(str(exc), portal_operator_credentials().password)
            kind = FailureKind.TRANSIENT
            low = msg.lower()
            if "login" in low or "sign in" in low:
                kind = FailureKind.AUTH_EXPIRED
            elif "timeout" in low:
                kind = FailureKind.TIMEOUT
            elif "not found" in low or "strict mode" in low:
                kind = FailureKind.ELEMENT_NOT_FOUND
            return ToolResult(ok=False, failure=Failure(kind=kind, message=msg, retryable=True))

    def _auth_expired_result(
        self,
        obs: dict[str, Any],
        *,
        evidence: list[str] | None = None,
        message: str = "session expired",
    ) -> ToolResult:
        self._logged_in = False
        banners = " ".join(obs.get("banners") or [])
        return ToolResult(
            ok=False,
            failure=Failure(
                kind=FailureKind.AUTH_EXPIRED,
                message=banners or message,
                retryable=True,
            ),
            observation=Observation(summary="Auth expired", data=obs, success=False),
            data={
                "observation": obs,
                "evidence": evidence or [],
                "url": obs.get("url"),
            },
        )

    def _goto(self, url: str) -> ToolResult:
        page = self._ensure()
        target = url if url.startswith("http") else f"{self.base_url}{url}"
        before = self._screenshot("before_goto")
        page.goto(target, wait_until="domcontentloaded")
        after = self._screenshot("after_goto")
        obs = self._observe()
        # Session-expiry fault redirects protected pages to /login — surface AUTH_EXPIRED.
        if "/login" in str(obs.get("url") or "") and "/login" not in target:
            return self._auth_expired_result(
                obs, evidence=[before.id, after.id], message="redirected to login"
            )
        return ToolResult(
            ok=True,
            observation=Observation(summary=f"Navigated to {obs['url']}", data=obs),
            data={"observation": obs, "evidence": [before.id, after.id]},
        )

    def _login(self) -> ToolResult:
        """Login using secrets provider — password never returned to LLM."""
        creds = portal_operator_credentials()
        page = self._ensure()
        page.goto(f"{self.base_url}/login", wait_until="domcontentloaded")
        self._screenshot("before_login")
        page.fill("#email", creds.email)
        page.fill("#password", creds.password)
        page.click("#login-submit")
        page.wait_for_url("**/dashboard", timeout=10000)
        self._screenshot("after_login")
        self._logged_in = True
        obs = self._observe()
        # Ensure password not in observation
        blob = str(obs)
        if creds.password and creds.password in blob:
            raise RuntimeError("Secret leaked into observation")
        return ToolResult(
            ok=True,
            observation=Observation(summary="Logged in", data={"url": obs["url"]}),
            data={"observation": obs, "logged_in": True},
        )

    def _resolve_ref(self, ref: str) -> Any | None:
        """Resolve [eN] against the last observation without remapping refs first."""
        if not self._refs:
            self._observe()
        return self._refs.get(ref)

    def _click(self, ref: str) -> ToolResult:
        page = self._ensure()
        el = self._resolve_ref(ref)
        if el is None:
            return ToolResult(
                ok=False,
                failure=Failure(
                    kind=FailureKind.ELEMENT_NOT_FOUND,
                    message=f"Unknown ref {ref}",
                    retryable=True,
                ),
            )
        before = self._screenshot(f"before_click_{ref}")
        try:
            with page.expect_navigation(timeout=5000, wait_until="domcontentloaded"):
                el.click()
        except Exception:
            # Non-navigating click: click already ran inside expect_navigation.
            page.wait_for_timeout(300)
        after = self._screenshot(f"after_click_{ref}")
        obs = self._observe()
        body = ""
        try:
            body = page.content()[:800]
        except Exception:
            body = ""
        banners = " ".join(obs.get("banners") or [])
        if "injected flaky_500" in body or "flaky_500" in body:
            return ToolResult(
                ok=False,
                failure=Failure(
                    kind=FailureKind.TRANSIENT,
                    message="flaky_500",
                    retryable=True,
                ),
                observation=Observation(summary="flaky_500 after click", data=obs, success=False),
                data={"observation": obs, "evidence": [before.id, after.id], "url": obs["url"]},
            )
        if "/login" in obs["url"]:
            return self._auth_expired_result(
                obs, evidence=[before.id, after.id], message=banners or "session expired"
            )
        return ToolResult(
            ok=True,
            observation=Observation(summary=f"Clicked {ref}", data=obs),
            data={"observation": obs, "evidence": [before.id, after.id]},
        )

    def _fill(self, ref: str, text: str) -> ToolResult:
        el = self._resolve_ref(ref)
        if el is None:
            return ToolResult(
                ok=False,
                failure=Failure(
                    kind=FailureKind.ELEMENT_NOT_FOUND,
                    message=f"Unknown ref {ref}",
                    retryable=True,
                ),
            )
        el.fill(text)
        obs = self._observe()
        if "/login" in str(obs.get("url") or ""):
            return self._auth_expired_result(obs, message="session expired during fill")
        return ToolResult(
            ok=True, observation=Observation(summary=f"Filled {ref}", data=obs), data=obs
        )

    def _select(self, ref: str, value: str) -> ToolResult:
        el = self._resolve_ref(ref)
        if el is None:
            return ToolResult(
                ok=False,
                failure=Failure(
                    kind=FailureKind.ELEMENT_NOT_FOUND,
                    message=f"Unknown ref {ref}",
                    retryable=True,
                ),
            )
        options: list[tuple[str, str]] = []
        for opt in el.query_selector_all("option"):
            oval = (opt.get_attribute("value") or "").strip()
            olabel = " ".join((opt.inner_text() or "").split())
            options.append((oval, olabel))
        chosen = resolve_select_option(value, options)
        if chosen is None:
            return ToolResult(
                ok=False,
                failure=Failure(
                    kind=FailureKind.ELEMENT_NOT_FOUND,
                    message=f"No unambiguous option matching {value!r} for {ref}",
                    retryable=True,
                ),
            )
        try:
            el.select_option(chosen)
        except Exception as exc:  # noqa: BLE001
            return ToolResult(
                ok=False,
                failure=Failure(
                    kind=FailureKind.ELEMENT_NOT_FOUND,
                    message=f"select_option failed for {value!r} on {ref}: {exc}",
                    retryable=True,
                ),
            )
        obs = self._observe()
        if "/login" in str(obs.get("url") or ""):
            return self._auth_expired_result(obs, message="session expired during select")
        return ToolResult(
            ok=True, observation=Observation(summary=f"Selected {ref}", data=obs), data=obs
        )

    def _press(self, key: str, *, ref: str | None = None) -> ToolResult:
        page = self._ensure()
        if ref:
            el = self._resolve_ref(ref)
            if el is None:
                return ToolResult(
                    ok=False,
                    failure=Failure(
                        kind=FailureKind.ELEMENT_NOT_FOUND,
                        message=f"Unknown ref {ref}",
                        retryable=True,
                    ),
                )
            el.press(key)
        else:
            page.keyboard.press(key)
        obs = self._observe()
        return ToolResult(
            ok=True, observation=Observation(summary=f"Pressed {key}", data=obs), data=obs
        )

    def re_resolve(
        self,
        *,
        role: str | None = None,
        name: str | None = None,
        label: str | None = None,
        element_id: str | None = None,
        timeout_ms: int = 1500,
    ) -> Any | None:
        """Re-resolve a control by role/name/label then stable id (SPEC §6.6)."""
        page = self._ensure()
        # 1) role + accessible name
        if role and name:
            try:
                loc = page.get_by_role(role, name=re.compile(rf"^{re.escape(name)}$", re.I))
                if loc.count() > 0:
                    return loc.first
            except Exception:
                pass
        # 2) label text (form controls)
        if label:
            try:
                loc = page.get_by_label(re.compile(re.escape(label), re.I))
                if loc.count() > 0:
                    return loc.first
            except Exception:
                pass
        # 3) name= attribute
        if name:
            try:
                loc = page.locator(f"[name={name!r}]")
                if loc.count() > 0 and loc.first.is_visible():
                    return loc.first
            except Exception:
                pass
        # 4) stable element id (survives ui_rename)
        if element_id:
            try:
                loc = page.locator(f"#{element_id}")
                if loc.count() > 0:
                    return loc.first
            except Exception:
                pass
        _ = timeout_ms
        return None

    def click_submit_resolved(self, *, prefer_label_first: bool | None = None) -> tuple[bool, bool]:
        """Click submit via role/name → stable id. Returns (clicked, recovered_from_label)."""
        page = self._ensure()
        prefer = self.prefer_label_first if prefer_label_first is None else prefer_label_first
        recovered = False
        if prefer:
            el = self.re_resolve(role="button", name="Submit invoice")
            if el is not None:
                try:
                    el.click(timeout=1500)
                    return True, False
                except Exception:
                    pass
            # Label miss / rename — fall through to stable id.
            recovered = True
            self.label_fallbacks += 1
        el = self.re_resolve(
            role="button",
            name="Submit invoice",
            element_id="submit-invoice-button",
        )
        if el is None:
            # Last resort: raw id selector (ids stay stable under ui_rename).
            page.click("#submit-invoice-button")
            return True, recovered
        el.click(timeout=3000)
        return True, recovered

    def _submit_invoice(self, args: dict[str, Any]) -> ToolResult:
        """High-level portal submit using stable element ids (survives ui_rename)."""
        page = self._ensure()
        if not self._logged_in or "/login" in page.url:
            login = self._login()
            if not login.ok:
                return login
        before = self._screenshot(f"before_submit_{args.get('invoice_number', 'inv')}")
        page.goto(f"{self.base_url}/invoices/submit", wait_until="domcontentloaded")
        _select_option_containing(page, "#vendor_id", str(args["vendor"]))
        page.fill("#invoice_number", str(args["invoice_number"]))
        if args.get("po_number"):
            _select_option_containing(page, "#po_id", str(args["po_number"]))
        page.fill("#amount", f"{float(args['amount']):.2f}")
        if args.get("invoice_date"):
            page.fill("#invoice_date", str(args["invoice_date"]))
        if args.get("attachment_name"):
            page.fill("#attachment_name", str(args["attachment_name"]))
        _, recovered_from_label = self.click_submit_resolved()
        page.wait_for_timeout(400)
        after = self._screenshot(f"after_submit_{args.get('invoice_number', 'inv')}")
        obs = self._observe()
        banner = " ".join(obs.get("banners") or [])
        body = ""
        try:
            body = page.content()[:500]
        except Exception:
            body = ""
        # flaky_500 returns JSON 500 — treat as TRANSIENT failure, not success.
        flaky_500 = "injected flaky_500" in body or "flaky_500" in body
        # Success lands on invoice detail or list, not the submit form / login / JSON error.
        landed_ok = "/invoices/" in obs["url"] and "/submit" not in obs["url"]
        ok = (
            landed_ok
            and "Duplicate submit blocked" not in banner
            and "/login" not in obs["url"]
            and not flaky_500
        )
        failure = None
        if not ok:
            kind = FailureKind.TRANSIENT if flaky_500 or "500" in body else FailureKind.UI_CHANGED
            if "/login" in obs["url"]:
                kind = FailureKind.AUTH_EXPIRED
            msg = banner or ("flaky_500" if flaky_500 else f"Submit did not land: {obs['url']}")
            failure = Failure(kind=kind, message=msg, retryable=True)
        return ToolResult(
            ok=ok,
            failure=failure,
            observation=Observation(
                summary="Submitted invoice form" if ok else f"Submit issue: {banner or obs['url']}",
                data=obs,
                success=ok,
            ),
            data={
                "observation": obs,
                "evidence": [before.id, after.id],
                "url": obs["url"],
                "banner": banner,
                "recovered_from_label": recovered_from_label,
            },
        )


def resolve_select_option(requested: str, options: list[tuple[str, str]]) -> str | None:
    """Resolve a select value/label token to an option *value*.

    Order: exact value → exact label → unique label/value contains.
    Observation tokens like ``6:Umbrella Corp (ACTIVE)`` are split into candidates.
    Ambiguous substring matches return None (fail closed — never guess a vendor/PO).
    """
    raw = (requested or "").strip()
    if not raw:
        return None
    candidates: list[str] = [raw]
    if ":" in raw:
        left, right = raw.split(":", 1)
        if left.strip():
            candidates.append(left.strip())
        if right.strip():
            candidates.append(right.strip())
    # Prefer longer / more specific candidates first for contains checks.
    uniq_candidates: list[str] = []
    for c in candidates:
        if c and c not in uniq_candidates:
            uniq_candidates.append(c)

    for cand in uniq_candidates:
        for oval, _olabel in options:
            if oval and oval == cand:
                return oval
    for cand in uniq_candidates:
        for oval, olabel in options:
            if olabel and olabel == cand and oval:
                return oval

    for cand in sorted(uniq_candidates, key=len, reverse=True):
        hits = [
            oval for oval, olabel in options if oval and cand and (cand in olabel or cand in oval)
        ]
        # Deduplicate while preserving order
        seen: list[str] = []
        for h in hits:
            if h not in seen:
                seen.append(h)
        if len(seen) == 1:
            return seen[0]
        if len(seen) > 1:
            return None
    return None


def _select_option_containing(page: Any, selector: str, text: str) -> None:
    options = page.query_selector_all(f"{selector} option")
    pairs = [
        ((opt.get_attribute("value") or "").strip(), " ".join((opt.inner_text() or "").split()))
        for opt in options
    ]
    chosen = resolve_select_option(text, pairs)
    if not chosen:
        raise RuntimeError(f"No unambiguous option matching {text!r} in {selector}")
    page.select_option(selector, value=chosen)


class DesktopTool(BaseTool):
    """STUB adapter interface for computer-use in Docker/Xvfb (SPEC §6.7)."""

    name = "desktop"
    risk_class = RiskLevel.IRREVERSIBLE
    description = "STUB: DesktopTool not implemented"

    def _run(self, args: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=False,
            failure=Failure(
                kind=FailureKind.UNRECOVERABLE,
                message="STUB: DesktopTool (out of scope)",
            ),
        )
