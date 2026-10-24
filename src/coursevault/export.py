"""Export accessible Canvas content; never bypass provider download restrictions."""
import json
import re
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlparse
from bs4 import BeautifulSoup

def safe_name(value):
    return re.sub(r'[<>:"/\\|?*\\x00-\\x1f]', "_", str(value or "untitled")).strip(". ") or "untitled"

def export_course(client, course, output: Path, progress=None):
    inventory = client.inventory(course["id"])
    report = {"course":course.get("name"),"downloaded":[],"skipped":[],"errors":inventory["errors"]}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory() as temp:
        root = Path(temp)
        (root/"pages").mkdir()
        (root/"files").mkdir()
        for page in inventory["pages"]:
            title = safe_name(page.get("title") or page.get("url"))
            html = page.get("body") or ""
            (root/"pages"/(title+".html")).write_text(
                "<!doctype html><meta charset='utf-8'><title>"+title+"</title>"+html,encoding="utf-8")
            for iframe in BeautifulSoup(html,"html.parser").select("iframe[src],video[src],source[src]"):
                report["skipped"].append({"page":title,"media":iframe.get("src"),"reason":"Embedded media requires provider-supported download"})
        for index, file in enumerate(inventory["files"]):
            name = safe_name(file.get("display_name") or file.get("filename") or str(file.get("id")))
            url = file.get("url") or ""
            try:
                parsed = urlparse(url)
                if parsed.scheme != "https":
                    raise ValueError("No HTTPS download URL")
                # Canvas may return signed external URLs; these are not fetched automatically.
                if parsed.netloc != urlparse(client.origin).netloc:
                    raise ValueError("External signed download URL: provider adapter required")
                response = client.context.request.get(url, timeout=120000)
                if not response.ok: raise RuntimeError("HTTP "+str(response.status))
                data = response.body()
                if len(data)>250_000_000: raise ValueError("File too large for v0.1")
                (root/"files"/name).write_bytes(data)
                report["downloaded"].append(name)
            except Exception as exc:
                report["skipped"].append({"file":name,"reason":str(exc)})
            if progress: progress(index+1,len(inventory["files"]))
        (root/"course.json").write_text(json.dumps(inventory,indent=2,default=str),encoding="utf-8")
        (root/"export-report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        links = "".join("<li><a href='pages/"+p.name+"'>"+p.stem+"</a></li>" for p in (root/"pages").glob("*.html"))
        (root/"index.html").write_text("<!doctype html><meta charset='utf-8'><h1>"+safe_name(course.get("name"))+"</h1><ul>"+links+"</ul>",encoding="utf-8")
        with zipfile.ZipFile(output,"w",zipfile.ZIP_DEFLATED) as archive:
            for file in root.rglob("*"):
                if file.is_file(): archive.write(file,file.relative_to(root))
    return report
