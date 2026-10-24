"""Canvas course archival engine. Uses only content available to the signed-in user."""
from __future__ import annotations

import html
import json
import mimetypes
import re
import shutil
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright

DEFAULT_ORIGIN = "https://baumancollege.instructure.com"
MAX_PAGES = 200
CHUNK = 1024 * 1024


def safe_name(value: object, limit: int = 130) -> str:
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", str(value or "untitled"))
    return (text.strip(" .")[:limit].rstrip(" .") or "untitled")


def safe_slug(value: object) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value)).strip("-") or "item"


def validate_origin(origin: str) -> str:
    parsed = urlparse(origin)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Canvas server must be a valid HTTPS URL")
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise ValueError("Enter the Canvas origin only, without a path")
    return origin.rstrip("/")


class Cancelled(Exception):
    pass


@dataclass
class Session:
    origin: str = DEFAULT_ORIGIN
    state_file: Path = Path.home() / ".coursevault" / "session.json"
    access_token: str | None = None

    def __post_init__(self):
        self.origin = validate_origin(self.origin)
        self.state_file = Path(self.state_file)

    def login(self, notify=None, cancel=None):
        """Sign in through Canvas, including supported institutional SSO flows.

        Verify login via the Canvas API from the Canvas origin, not the SSO
        provider origin. Display actionable status and allow cancellation.
        """
        import time
        emit = notify or (lambda message: None)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as pw:
            emit("Launching Canvas sign-in browser…")
            browser = pw.chromium.launch(headless=False)
            context = None
            try:
                options = {"accept_downloads": False}
                if self.state_file.exists():
                    options["storage_state"] = str(self.state_file)
                context = browser.new_context(**options)
                page = context.new_page()
                emit("Opening Canvas. Complete sign-in in the browser window…")
                page.goto(self.origin, wait_until="commit", timeout=30000)
                deadline = time.monotonic() + 180
                while time.monotonic() < deadline:
                    if cancel is not None and cancel.is_set():
                        raise Cancelled("Sign-in cancelled")
                    if not context.pages:
                        raise RuntimeError("Sign-in browser was closed before authentication completed.")
                    # Authentication might finish in a different browser tab.
                    for tab in context.pages:
                        if tab.is_closed():
                            continue
                        try:
                            current = urlparse(tab.url)
                            if current.netloc != urlparse(self.origin).netloc:
                                continue
                            result = tab.evaluate("""async () => {
                                try {
                                  const response = await fetch('/api/v1/users/self', {
                                    credentials:'same-origin',
                                    headers:{Accept:'application/json'}
                                  });
                                  if (!response.ok) return false;
                                  const data = await response.json();
                                  return Boolean(data && data.id);
                                } catch {return false;}
                            }""")
                            if result:
                                context.storage_state(path=str(self.state_file))
                                try: self.state_file.chmod(0o600)
                                except OSError: pass
                                emit("Canvas login verified.")
                                return True
                        except Exception:
                            pass
                    time.sleep(1.5)
                raise RuntimeError(
                    "Canvas login timed out after 3 minutes. Check the sign-in browser "
                    "and any institutional SSO/MFA prompts, then try again."
                )
            finally:
                if context: context.close()
                browser.close()

    def clear_session(self):
        self.state_file.unlink(missing_ok=True)

    def _request_context(self, pw):
        if self.access_token:
            return pw.request.new_context(
                extra_http_headers={"Authorization": "Bearer " + self.access_token},
                timeout=90000, max_redirects=10
            )
        if not self.state_file.exists():
            raise RuntimeError("Sign in first, or use a Canvas access token.")
        return pw.request.new_context(storage_state=str(self.state_file), timeout=90000, max_redirects=10)

    def _get_json(self, request, path: str):
        url = urljoin(self.origin + "/", path)
        if urlparse(url).netloc != urlparse(self.origin).netloc:
            raise ValueError("Cross-origin Canvas API request blocked")
        response = request.get(url, headers={"Accept":"application/json"})
        if response.status in (401, 403):
            raise RuntimeError("Canvas denied access (HTTP %s); sign in again or check course permissions." % response.status)
        if not response.ok:
            raise RuntimeError("Canvas API returned HTTP %s for %s" % (response.status, path))
        return response.json(), response.headers.get("link", "")

    def _all(self, request, path: str):
        current = path + ("&" if "?" in path else "?") + "per_page=100"
        rows = []
        for _ in range(MAX_PAGES):
            data, links = self._get_json(request, current)
            if not isinstance(data, list):
                return data
            rows.extend(data)
            next_url = None
            for segment in links.split(","):
                if 'rel="next"' in segment:
                    match = re.search(r"<([^>]+)>", segment)
                    if match: next_url = match.group(1)
            if not next_url:
                return rows
            parsed = urlparse(next_url)
            if parsed.netloc != urlparse(self.origin).netloc:
                raise RuntimeError("Unexpected cross-origin pagination")
            current = parsed.path + ("?" + parsed.query if parsed.query else "")
        raise RuntimeError("Canvas pagination exceeded safety limit")

    def courses(self):
        with sync_playwright() as pw:
            request = self._request_context(pw)
            try:
                self._get_json(request, "/api/v1/users/self")
                result = self._all(request, "/api/v1/courses?enrollment_state=active")
                return [c for c in result if isinstance(c, dict) and c.get("id") and c.get("name")]
            finally: request.dispose()

    def inventory(self, request, course_id: int, notify=lambda _: None):
        root = "/api/v1/courses/" + str(int(course_id))
        data = {"modules":[],"pages":[],"files":[],"assignments":[],"discussions":[],"quizzes":[],"errors":[]}
        for kind, path in (("modules","modules"),("pages","pages"),("files","files"),
                           ("assignments","assignments"),("discussions","discussion_topics"),("quizzes","quizzes")):
            notify("Discovering " + kind + "…")
            try: data[kind] = self._all(request, root + "/" + path)
            except Exception as exc: data["errors"].append(kind + ": " + str(exc))
        for module in data["modules"]:
            try: module["items"] = self._all(request, root + "/modules/" + str(module["id"]) + "/items")
            except Exception as exc: data["errors"].append("module " + str(module.get("id")) + ": " + str(exc))
        for index, page in enumerate(data["pages"]):
            try:
                slug = quote(str(page["url"]), safe="")
                data["pages"][index] = self._get_json(request, root + "/pages/" + slug)[0]
            except Exception as exc: data["errors"].append("page " + str(page.get("url")) + ": " + str(exc))
        return data

    def export(self, course: dict, output: Path, notify=lambda _: None, cancel: threading.Event | None = None):
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        report = {"course":course.get("name"),"downloaded":[],"skipped":[],"errors":[]}
        with tempfile.TemporaryDirectory(prefix="coursevault-") as temp, sync_playwright() as pw:
            request = self._request_context(pw)
            root = Path(temp)
            try:
                inventory = self.inventory(request, int(course["id"]), notify)
                report["errors"].extend(inventory["errors"])
                for dirname in ("pages","files","assignments","discussions","quizzes"):
                    (root / dirname).mkdir()
                (root / "course.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding="utf-8")
                page_links = []
                direct_media = []
                for index, page in enumerate(inventory["pages"]):
                    if cancel and cancel.is_set(): raise Cancelled("Export cancelled")
                    filename = f'{index+1:03d}-{safe_name(page.get("title") or page.get("url"))}.html'
                    body = page.get("body") or ""
                    soup = BeautifulSoup(body, "html.parser")
                    for node in soup.select("iframe[src],video[src],source[src],audio[src]"):
                        source = node.get("src")
                        if not source: continue
                        resolved = urljoin(self.origin + "/", source)
                        parsed_media = urlparse(resolved)
                        # Only explicit, direct downloadable media on the Canvas origin.
                        if (node.name != "iframe" and parsed_media.netloc == urlparse(self.origin).netloc
                                and parsed_media.path.lower().endswith((".mp4",".webm",".mp3",".m4a",".ogg"))):
                            direct_media.append((resolved, str(page.get("title") or "lesson")))
                        else:
                            report["skipped"].append({"media":source,"reason":"Embedded or hosted media: no supported direct download"})
                    html_doc = "<!doctype html><html><head><meta charset='utf-8'><title>" + html.escape(str(page.get("title") or "")) + "</title></head><body>" + str(soup) + "</body></html>"
                    (root / "pages" / filename).write_text(html_doc, encoding="utf-8")
                    page_links.append(("pages/" + filename, str(page.get("title") or filename)))
                for category in ("assignments","discussions","quizzes"):
                    for item in inventory[category]:
                        name = safe_name(item.get("name") or item.get("title") or item.get("id"))
                        filename = safe_slug(item.get("id")) + "-" + name + ".json"
                        (root / category / filename).write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
                (root / "media").mkdir()
                for media_index, (media_url, media_title) in enumerate(direct_media):
                    if cancel and cancel.is_set(): raise Cancelled("Export cancelled")
                    media_name = f"{media_index+1:03d}-" + safe_name(media_title) + Path(urlparse(media_url).path).suffix.lower()
                    notify("Downloading direct Canvas media: " + media_name)
                    try:
                        response = request.get(media_url, timeout=180000)
                        if not response.ok: raise RuntimeError("HTTP " + str(response.status))
                        if "text/html" in response.headers.get("content-type",""):
                            raise RuntimeError("Media URL returned HTML")
                        payload = response.body()
                        (root / "media" / media_name).write_bytes(payload)
                        report["downloaded"].append({"name":media_name,"bytes":len(payload)})
                        page_links.append(("media/" + media_name,media_name))
                    except Exception as exc:
                        report["skipped"].append({"media":media_url,"reason":str(exc)})
                total = len(inventory["files"])
                for index, file in enumerate(inventory["files"]):
                    if cancel and cancel.is_set(): raise Cancelled("Export cancelled")
                    name = safe_name(file.get("display_name") or file.get("filename") or file.get("id"))
                    filename = str(file.get("id",index)) + "-" + name
                    notify(f"Downloading file {index+1}/{total}: {name}")
                    try:
                        if file.get("locked_for_user") or file.get("locked"):
                            raise RuntimeError("Canvas file is locked")
                        url = file.get("url")
                        if not url: raise RuntimeError("No authorized download URL returned by Canvas")
                        parsed = urlparse(url)
                        if parsed.scheme != "https": raise RuntimeError("Insecure download URL")
                        if self.access_token and parsed.netloc != urlparse(self.origin).netloc:
                            raise RuntimeError("External file host requires separate safe download handling in token mode")
                        # Canvas may return expiring signed URLs on trusted storage hosts.
                        # Playwright APIRequestContext follows redirects with current Canvas cookies.
                        if self.access_token:
                            # Do not forward Canvas authorization headers across redirects.
                            import httpx
                            current_url = url
                            with httpx.Client(follow_redirects=False,timeout=120) as http:
                                for redirect_count in range(8):
                                    destination = urlparse(current_url)
                                    if destination.scheme != "https":
                                        raise RuntimeError("Insecure file redirect")
                                    headers = {}
                                    if destination.netloc == urlparse(self.origin).netloc:
                                        headers["Authorization"] = "Bearer " + self.access_token
                                    with http.stream("GET",current_url,headers=headers) as stream:
                                        if stream.status_code in (301,302,303,307,308):
                                            location = stream.headers.get("location")
                                            if not location: raise RuntimeError("Redirect without location")
                                            current_url = urljoin(current_url,location)
                                            continue
                                        stream.raise_for_status()
                                        if "text/html" in stream.headers.get("content-type",""):
                                            raise RuntimeError("Server returned HTML instead of a file")
                                        target = root / "files" / filename
                                        with target.open("wb") as handle:
                                            for chunk in stream.iter_bytes(chunk_size=1024*1024):
                                                if cancel and cancel.is_set(): raise Cancelled("Export cancelled")
                                                handle.write(chunk)
                                        payload_size = target.stat().st_size
                                        break
                                else:
                                    raise RuntimeError("Too many file redirects")
                        else:
                            response = request.get(url, timeout=180000)
                            if not response.ok: raise RuntimeError("HTTP " + str(response.status))
                            content_type = response.headers.get("content-type","")
                            if "text/html" in content_type: raise RuntimeError("Server returned HTML instead of a file")
                            payload = response.body()
                            (root / "files" / filename).write_bytes(payload)
                            payload_size = len(payload)
                        (root / "files" / filename).write_bytes(payload)
                        report["downloaded"].append({"name":name,"bytes":payload_size})
                        page_links.append(("files/" + filename,name))
                    except Exception as exc:
                        report["skipped"].append({"file":name,"reason":str(exc)})
                links = "\n".join("<li><a href='" + html.escape(path,quote=True) + "'>" + html.escape(label) + "</a></li>" for path,label in page_links)
                index_html = "<!doctype html><html><head><meta charset='utf-8'><title>CourseVault</title><style>body{font:16px system-ui;max-width:900px;margin:50px auto;padding:20px;background:#10131b;color:#eee}a{color:#a99fff}li{padding:8px}</style></head><body><h1>" + html.escape(str(course.get("name"))) + "</h1><p>Offline archive — some embedded resources require internet access.</p><ul>" + links + "</ul></body></html>"
                (root / "index.html").write_text(index_html, encoding="utf-8")
                (root / "export-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2), encoding="utf-8")
                temporary_zip = output.with_suffix(output.suffix + ".partial")
                try:
                    with zipfile.ZipFile(temporary_zip,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
                        for path in root.rglob("*"):
                            if cancel and cancel.is_set(): raise Cancelled("Export cancelled")
                            if path.is_file(): archive.write(path,path.relative_to(root))
                    temporary_zip.replace(output)
                finally: temporary_zip.unlink(missing_ok=True)
                notify("Export complete")
                return report
            finally: request.dispose()
