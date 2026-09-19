from __future__ import annotations

import concurrent.futures
import logging
import os
import queue
import threading
from typing import Any
from urllib.parse import quote

logger = logging.getLogger(__name__)

COMPOSER_API = "https://www.ozon.ru/api/composer-api.bx/page/json/v2"
HOME_URL = "https://www.ozon.ru/"

_ANTIBOT_MARKERS = (
    "antibot challenge",
    "abt-challenge",
    "access denied",
    "variti",
    "qrator",
    "подтвердите, что вы не робот",
    "доступ ограничен",
)


def ozon_browser_enabled() -> bool:
    return os.getenv("OZON_BROWSER_ENABLED", "true").strip().lower() in ("1", "true", "yes", "on")


def ozon_browser_cdp_url() -> str:
    return (os.getenv("OZON_BROWSER_CDP_URL") or "http://127.0.0.1:9222").strip()


def ozon_browser_launch_fallback() -> bool:
    """默认不另开浏览器；仅显式开启时才 launch（易被反爬）。"""
    return os.getenv("OZON_BROWSER_LAUNCH_FALLBACK", "false").strip().lower() in ("1", "true", "yes", "on")


def ozon_browser_headless() -> bool:
    return os.getenv("OZON_BROWSER_HEADLESS", "true").strip().lower() not in ("0", "false", "no", "off")


def _looks_like_antibot(payload: dict[str, Any] | None, text: str = "", status: int = 200) -> bool:
    if status in (401, 403, 429):
        return True
    if payload is not None:
        if payload.get("incidentId") and not payload.get("widgetStates"):
            return True
        if not payload.get("widgetStates") and payload.get("pageInfo", {}).get("pageType") == "error":
            return True
    lowered = (text or "").lower()
    # 真实商品页也可能出现 "challenge" 字样，要求更严格
    if "antibot challenge" in lowered or "abt-challenge" in lowered:
        return True
    return any(marker in lowered for marker in _ANTIBOT_MARKERS)


class _Command:
    __slots__ = ("name", "args", "future")

    def __init__(self, name: str, args: dict[str, Any], future: concurrent.futures.Future[Any]) -> None:
        self.name = name
        self.args = args
        self.future = future


class OzonBrowserSession:
    """
    优先通过 CDP 接入本机已打开的 Chrome（复用你的登录/反爬状态），
    在独立线程内调用 Playwright sync API，供 FastAPI 线程池安全使用。
    """

    def __init__(self) -> None:
        self._queue: queue.Queue[_Command | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._start_lock = threading.Lock()
        self._ready = threading.Event()
        self._closed = False
        self._last_error: str | None = None
        self._warmed = False
        self._mode: str = "none"  # cdp | launch

    @property
    def last_error(self) -> str | None:
        return self._last_error

    @property
    def warmed(self) -> bool:
        return self._warmed

    def ensure_started(self, timeout: float = 90.0) -> None:
        if self._closed:
            raise RuntimeError("Ozon 浏览器会话已关闭")
        with self._start_lock:
            if self._thread is None or not self._thread.is_alive():
                self._ready.clear()
                self._thread = threading.Thread(
                    target=self._worker_loop,
                    name="ozon-browser-session",
                    daemon=True,
                )
                self._thread.start()
        if not self._ready.wait(timeout=timeout):
            raise RuntimeError(
                self._last_error
                or (
                    "无法接入本机 Chrome。请先运行 start-ozon-chrome.ps1，"
                    f"打开 ozon.ru 过一遍验证，再采集（CDP: {ozon_browser_cdp_url()}）"
                )
            )

    def fetch_composer(self, page_path: str, *, timeout_seconds: int = 45) -> dict[str, Any]:
        self.ensure_started()
        return self._call(
            "fetch_composer",
            {"page_path": page_path, "timeout_seconds": timeout_seconds},
            timeout=float(timeout_seconds) + 30.0,
        )

    def fetch_html(self, page_path: str, *, timeout_seconds: int = 45) -> str:
        self.ensure_started()
        return self._call(
            "fetch_html",
            {"page_path": page_path, "timeout_seconds": timeout_seconds},
            timeout=float(timeout_seconds) + 30.0,
        )

    def reset(self) -> None:
        if self._thread is None or not self._thread.is_alive():
            return
        try:
            self._call("reset", {}, timeout=90.0)
        except Exception as exc:
            logger.warning("reset browser session failed: %s", exc)

    def close(self) -> None:
        """断开 Playwright 连接；CDP 模式下不会关掉你的 Chrome。"""
        self._closed = True
        thread = self._thread
        if thread is None:
            return
        self._queue.put(None)
        thread.join(timeout=15.0)
        self._thread = None
        self._warmed = False

    def status(self) -> dict[str, Any]:
        alive = self._thread is not None and self._thread.is_alive()
        return {
            "enabled": ozon_browser_enabled(),
            "mode": self._mode,
            "cdp_url": ozon_browser_cdp_url(),
            "launch_fallback": ozon_browser_launch_fallback(),
            "headless": ozon_browser_headless(),
            "alive": alive,
            "warmed": self._warmed,
            "last_error": self._last_error,
        }

    def _call(self, name: str, args: dict[str, Any], *, timeout: float) -> Any:
        future: concurrent.futures.Future[Any] = concurrent.futures.Future()
        self._queue.put(_Command(name, args, future))
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            raise RuntimeError(f"Ozon 浏览器操作超时: {name}") from exc

    def _worker_loop(self) -> None:
        playwright = None
        browser = None
        context = None
        page = None
        owns_browser = False  # launch 模式才负责关闭

        def cleanup(*, kill_browser: bool) -> None:
            nonlocal browser, context, page, playwright
            if page is not None and owns_browser:
                try:
                    page.close()
                except Exception:
                    pass
            page = None
            if owns_browser:
                for closer in (context, browser):
                    try:
                        if closer is not None:
                            closer.close()
                    except Exception:
                        pass
            elif browser is not None:
                # CDP：只断开连接，绝不 browser.close() 以免关掉用户 Chrome
                try:
                    browser.close()  # playwright CDP close = disconnect
                except Exception:
                    pass
            context = browser = None
            if playwright is not None:
                try:
                    playwright.stop()
                except Exception:
                    pass
                playwright = None

        def boot() -> None:
            nonlocal playwright, browser, context, page, owns_browser
            cleanup(kill_browser=owns_browser)
            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:
                raise RuntimeError(
                    "未安装 playwright。请执行: pip install playwright && playwright install chromium"
                ) from exc

            playwright = sync_playwright().start()
            cdp = ozon_browser_cdp_url()
            last_exc: Exception | None = None

            # 1) 优先接入已打开的 Chrome
            try:
                browser = playwright.chromium.connect_over_cdp(cdp)
                if not browser.contexts:
                    raise RuntimeError("已连接 Chrome，但没有任何上下文")
                context = browser.contexts[0]
                page = self._pick_or_create_page(context)
                owns_browser = False
                self._mode = "cdp"
                self._warmup_cdp(page)
                self._warmed = True
                self._last_error = None
                logger.info("Ozon browser attached via CDP %s", cdp)
                return
            except Exception as exc:
                last_exc = exc
                logger.warning("CDP attach failed (%s): %s", cdp, exc)
                try:
                    if browser is not None:
                        browser.close()
                except Exception:
                    pass
                browser = context = page = None

            # 2) 可选：自行 launch（默认关闭，因为极易被反爬）
            if not ozon_browser_launch_fallback():
                raise RuntimeError(
                    "无法接入本机已打开的 Chrome。"
                    "请先运行项目根目录 start-ozon-chrome.ps1（会开带调试端口的 Chrome），"
                    "在窗口里打开 ozon.ru 并完成验证后，再点采集。"
                    f" CDP={cdp}；原因: {last_exc}"
                )

            browser = playwright.chromium.launch(
                headless=ozon_browser_headless(),
                channel=os.getenv("OZON_BROWSER_CHANNEL", "").strip() or None,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                ],
            )
            context = browser.new_context(
                locale="ru-RU",
                timezone_id="Europe/Moscow",
                viewport={"width": 1440, "height": 900},
            )
            page = context.new_page()
            page.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            owns_browser = True
            self._mode = "launch"
            self._warmup_launch(page)
            self._warmed = True
            self._last_error = None

        try:
            try:
                boot()
            except Exception as exc:
                self._last_error = str(exc)
                self._warmed = False
                logger.exception("Ozon browser boot failed")
            finally:
                self._ready.set()

            while True:
                command = self._queue.get()
                if command is None:
                    break
                try:
                    if page is None or not self._warmed:
                        boot()
                    assert page is not None
                    if command.name == "fetch_composer":
                        result = self._do_fetch_composer(
                            page,
                            command.args["page_path"],
                            int(command.args["timeout_seconds"]),
                        )
                    elif command.name == "fetch_html":
                        result = self._do_fetch_html(
                            page,
                            command.args["page_path"],
                            int(command.args["timeout_seconds"]),
                        )
                    elif command.name == "reset":
                        boot()
                        result = True
                    else:
                        raise RuntimeError(f"unknown command: {command.name}")
                    command.future.set_result(result)
                except Exception as exc:
                    self._last_error = str(exc)
                    self._warmed = False
                    logger.warning("Ozon browser command %s failed: %s", command.name, exc)
                    if not command.future.done():
                        command.future.set_exception(exc)
                    try:
                        boot()
                    except Exception:
                        pass
        finally:
            cleanup(kill_browser=owns_browser)
            self._warmed = False

    @staticmethod
    def _pick_or_create_page(context: Any) -> Any:
        """优先复用已打开的 www.ozon.ru 前台标签，避免选到 seller / 反爬页。"""

        def score(url: str) -> int:
            u = (url or "").lower()
            if "challenge" in u or "abt-challenge" in u:
                return -100
            if "www.ozon.ru" in u:
                return 100
            if "ozon.ru" in u and "seller.ozon.ru" not in u and "api-seller" not in u:
                return 80
            if "seller.ozon.ru" in u:
                return 10
            return 0

        best = None
        best_score = 0
        for candidate in context.pages:
            try:
                s = score(candidate.url or "")
            except Exception:
                continue
            if s > best_score:
                best = candidate
                best_score = s
        if best is not None and best_score >= 80:
            return best

        # 没有可用前台页时再新建（不要复用 seller 页去打前台 API）
        return context.new_page()

    def _warmup_cdp(self, page: Any) -> None:
        """已打开浏览器：尽量不折腾导航；能打通 composer 即可。"""
        try:
            current = (page.url or "").lower()
        except Exception:
            current = ""
        if "www.ozon.ru" not in current:
            page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            page.wait_for_timeout(1500)

        probe = self._page_fetch_json(page, f"{COMPOSER_API}?url={quote('/', safe='')}", 30)
        status = int(probe.get("status") or 0)
        payload = probe.get("json")
        if isinstance(payload, dict) and payload.get("widgetStates"):
            return
        # 首页 composer 偶发 403，商品页导航后再打通常可恢复——预热不硬失败
        logger.warning(
            "CDP warmup probe weak: status=%s keys=%s",
            status,
            list(payload.keys())[:6] if isinstance(payload, dict) else None,
        )

    def _warmup_launch(self, page: Any) -> None:
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        page.wait_for_timeout(2500)
        content = (page.content() or "").lower()
        if _looks_like_antibot(None, content):
            raise RuntimeError(
                "自行启动的浏览器被 Ozon 反爬拦截。请改用 start-ozon-chrome.ps1 接入你已验证的 Chrome。"
            )
        probe = self._page_fetch_json(page, f"{COMPOSER_API}?url={quote('/', safe='')}", 30)
        if _looks_like_antibot(probe.get("json"), probe.get("text", ""), int(probe.get("status") or 0)):
            raise RuntimeError("Ozon composer-api 预热失败（反爬）")

    def _do_fetch_composer(self, page: Any, page_path: str, timeout_seconds: int) -> dict[str, Any]:
        page_path = page_path if page_path.startswith("/") else f"/{page_path}"
        # 确保在 www.ozon.ru 同源上下文中 fetch（不要用 seller 页）
        try:
            current = (page.url or "").lower()
        except Exception:
            current = ""
        if "www.ozon.ru" not in current:
            try:
                page.goto(HOME_URL, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            except Exception:
                pass

        encoded = quote(page_path, safe="/?=&%")
        url = f"{COMPOSER_API}?url={encoded}"
        result = self._page_fetch_json(page, url, timeout_seconds)
        status = int(result.get("status") or 0)
        payload = result.get("json")
        text = str(result.get("text") or "")

        # 停在首页时商品 composer 常 403：先打开目标页再重试
        weak = (
            not isinstance(payload, dict)
            or not payload.get("widgetStates")
            or status in (401, 403, 429)
        )
        if weak:
            target = f"https://www.ozon.ru{page_path}"
            logger.info("composer weak (HTTP %s), navigate then retry: %s", status, page_path)
            page.goto(target, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
            page.wait_for_timeout(2000)
            result = self._page_fetch_json(page, url, timeout_seconds)
            status = int(result.get("status") or 0)
            payload = result.get("json")
            text = str(result.get("text") or "")

        if not isinstance(payload, dict):
            if _looks_like_antibot(None, text, status):
                raise RuntimeError("Ozon 反爬拦截（请在已接入的 Chrome 里手动过一遍验证）")
            raise RuntimeError(f"composer API 返回非 JSON (HTTP {status})")
        if not payload.get("widgetStates"):
            if _looks_like_antibot(payload, text, status):
                raise RuntimeError("Ozon 反爬拦截（请在已接入的 Chrome 里手动过一遍验证）")
            raise RuntimeError(f"composer API 无 widgetStates (HTTP {status})")
        return payload

    def _do_fetch_html(self, page: Any, page_path: str, timeout_seconds: int) -> str:
        page_path = page_path if page_path.startswith("/") else f"/{page_path}"
        url = f"https://www.ozon.ru{page_path}"
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_seconds * 1000)
        page.wait_for_timeout(800)
        html = page.content() or ""
        if _looks_like_antibot(None, html):
            raise RuntimeError("Ozon HTML 页面被反爬拦截")
        return html

    @staticmethod
    def _page_fetch_json(page: Any, url: str, timeout_seconds: int) -> dict[str, Any]:
        return page.evaluate(
            """async ({ url, timeoutMs }) => {
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), timeoutMs);
                try {
                    const response = await fetch(url, {
                        method: 'GET',
                        credentials: 'include',
                        headers: {
                            'Accept': 'application/json',
                            'x-o3-app-name': 'dweb_client',
                        },
                        signal: controller.signal,
                    });
                    const text = await response.text();
                    let json = null;
                    try { json = JSON.parse(text); } catch (e) { json = null; }
                    return { status: response.status, text, json };
                } finally {
                    clearTimeout(timer);
                }
            }""",
            {"url": url, "timeoutMs": max(5_000, timeout_seconds * 1000)},
        )


_SESSION: OzonBrowserSession | None = None
_SESSION_LOCK = threading.Lock()


def get_ozon_browser_session() -> OzonBrowserSession:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is None or _SESSION._closed:
            _SESSION = OzonBrowserSession()
        return _SESSION


def shutdown_ozon_browser_session() -> None:
    global _SESSION
    with _SESSION_LOCK:
        if _SESSION is not None:
            _SESSION.close()
            _SESSION = None
