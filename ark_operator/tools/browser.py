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
                    opts: list[str] = []
                    for opt in el.query_selector_all("option"):
                        ov = (opt.get_attribute("value") or "").strip()
                        ol = " ".join((opt.inner_text() or "").split())[:60]
                        if ov or ol:
                            opts.append(f"{ov}:{ol}" if ov else ol)
                    opt_s = ",".join(opts[:24])
                    lines.append(f'[{ref}] select "{label}" id={eid} options=[{opt_s}]')
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

    def _goto(self, url: str) -> ToolResult:
        page = self._ensure()
        target = url if url.startswith("http") else f"{self.base_url}{url}"
        before = self._screenshot("before_goto")
        page.goto(target, wait_until="domcontentloaded")
        after = self._screenshot("after_goto")
        obs = self._observe()
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
        try:
            el.select_option(value)
        except Exception:
            # LLM often passes visible option label; match by contains.
            matched = False
            for opt in el.query_selector_all("option"):
                label = (opt.inner_text() or "").strip()
                oval = opt.get_attribute("value") or ""
                if value in label and oval:
                    el.select_option(oval)
                    matched = True
                    break
            if not matched:
                return ToolResult(
                    ok=False,
                    failure=Failure(
                        kind=FailureKind.ELEMENT_NOT_FOUND,
                        message=f"No option matching {value!r} for {ref}",
                        retryable=True,
                    ),
                )
        obs = self._observe()
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
        recovered_from_label = False
        if self.prefer_label_first:
            try:
                page.get_by_role("button", name=re.compile(r"^Submit invoice$", re.I)).click(
                    timeout=1500
                )
            except Exception:
                # UI_CHANGED / renamed label — recover via stable element id (SPEC §6.6).
                self.label_fallbacks += 1
                recovered_from_label = True
                page.click("#submit-invoice-button")
        else:
            page.click("#submit-invoice-button")
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


def _select_option_containing(page: Any, selector: str, text: str) -> None:
    options = page.query_selector_all(f"{selector} option")
    for opt in options:
        label = (opt.inner_text() or "").strip()
        value = opt.get_attribute("value") or ""
        if text in label and value:
            page.select_option(selector, value=value)
            return
    raise RuntimeError(f"No option containing {text!r} in {selector}")


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
