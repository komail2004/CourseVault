"""Authenticated Canvas access through a browser the user controls."""
import re
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

ORIGIN = "https://baumancollege.instructure.com"

class CanvasClient:
    def __init__(self, profile: Path, origin: str = ORIGIN):
        parsed = urlparse(origin)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Canvas origin must be HTTPS")
        self.origin = origin.rstrip("/")
        self.profile = Path(profile)
        self.profile.mkdir(parents=True, exist_ok=True)
        self.playwright = None
        self.context = None
        self.page = None

    def open(self):
        self.playwright = sync_playwright().start()
        self.context = self.playwright.chromium.launch_persistent_context(
            str(self.profile), headless=False, accept_downloads=False)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.goto(self.origin + "/login/canvas", wait_until="domcontentloaded")

    def wait_for_login(self):
        self.page.wait_for_url(re.compile(r"https://baumancollege\.instructure\.com/(?!login)"), timeout=180000)
        self.api("/api/v1/users/self")

    def api(self, path):
        if not path.startswith("/api/v1/"):
            raise ValueError("Canvas API path required")
        return self.page.evaluate("""async path => {
          const r = await fetch(path, {credentials:'same-origin',headers:{Accept:'application/json'}});
          if (!r.ok) throw Error('Canvas API HTTP '+r.status);
          return {data:await r.json(),next:(r.headers.get('link')||'').match(/<([^>]+)>; rel="next"/)?.[1]||null};
        }""", path)

    def all(self, path):
        items = []
        current = path + ("&" if "?" in path else "?") + "per_page=100"
        for _ in range(100):
            response = self.api(current)
            if not isinstance(response["data"], list):
                return response["data"]
            items.extend(response["data"])
            if not response["next"]:
                return items
            next_url = urlparse(response["next"])
            if next_url.netloc != urlparse(self.origin).netloc:
                raise ValueError("Cross-origin pagination blocked")
            current = next_url.path + ("?"+next_url.query if next_url.query else "")
        raise RuntimeError("Too many Canvas pages")

    def courses(self):
        return self.all("/api/v1/courses?enrollment_state=active")

    def inventory(self, course_id):
        root = "/api/v1/courses/" + str(int(course_id))
        result = {"modules":[],"pages":[],"files":[],"assignments":[],"errors":[]}
        for kind, endpoint in [("modules","/modules"),("pages","/pages"),("files","/files"),("assignments","/assignments")]:
            try: result[kind] = self.all(root + endpoint)
            except Exception as e: result["errors"].append(kind + ": " + str(e))
        for module in result["modules"]:
            try: module["items"] = self.all(root + "/modules/" + str(module["id"]) + "/items")
            except Exception as e: result["errors"].append("module: " + str(e))
        for i, page in enumerate(result["pages"]):
            try: result["pages"][i] = self.api(root + "/pages/" + page["url"])["data"]
            except Exception as e: result["errors"].append("page: " + str(e))
        return result

    def close(self):
        if self.context: self.context.close()
        if self.playwright: self.playwright.stop()
