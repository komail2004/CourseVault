"""Build a navigable offline Canvas course from authorized API content."""
import html
import json
import re
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlparse, quote
import httpx
from bs4 import BeautifulSoup

EXTS={".png",".jpg",".jpeg",".webp",".gif",".svg",".pdf",".mp4",".webm",".mp3",".m4a",".wav",".ogg",".vtt",".srt"}

def name(value):
    return (re.sub(r'[^\w. -]',"_",str(value or "untitled")).strip(" .")[:100] or "untitled")

def page_html(title, body):
    return "<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><style>body{max-width:850px;margin:30px auto;padding:20px;font:16px/1.7 system-ui;color:#242536}img,video,audio{max-width:100%}</style></head><body><h1>"+html.escape(str(title))+"</h1>"+body+"</body></html>"

def viewer(course, modules):
    data=json.dumps({"course":course,"modules":modules},ensure_ascii=False).replace("<","\\u003c")
    return """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>CourseVault Offline</title><style>
body{margin:0;background:#10131e;color:#eceefb;font:15px/1.6 system-ui}header{padding:22px 30px;background:#1a1e30;border-bottom:1px solid #353a55;font-weight:800;letter-spacing:.12em;color:#b7adff}
.layout{display:grid;grid-template-columns:310px 1fr;min-height:90vh}aside{padding:25px;background:#191e2d;border-right:1px solid #363c52;overflow:auto}main{padding:45px;min-width:0}h1{font-size:35px}h3{color:#a99fff;font-size:12px;letter-spacing:.12em;text-transform:uppercase;margin-top:26px}
button{display:block;width:100%;text-align:left;background:transparent;border:0;color:#e2e3ef;padding:12px;border-radius:9px;cursor:pointer;font:inherit}button:hover,button.active{background:#363153}
iframe{width:100%;height:75vh;border:0;background:white;border-radius:12px}a{color:#c6bdff}input{width:100%;padding:12px;color:white;background:#111523;border:1px solid #484d65;border-radius:9px}
.card{padding:24px;background:#202538;border:1px solid #3b4057;border-radius:14px}video,audio{max-width:100%}
@media(max-width:740px){.layout{grid-template-columns:1fr}aside{max-height:300px}main{padding:20px}}
</style></head><body><header>✦ COURSEVAULT / OFFLINE</header><div class="layout"><aside><h2 id="course"></h2><input id="filter" placeholder="Search lessons and files"><div id="nav"></div></aside><main><h1 id="title"></h1><p id="kind"></p><div id="body" class="card">Select a lesson or file from the sidebar. This archive works offline; external activities may not.</div></main></div>
<script id="data" type="application/json">""" + data + """</script><script>
const model=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);
$('course').textContent=model.course;$('title').textContent=model.course;
function show(item,button){document.querySelectorAll('button.active').forEach(x=>x.classList.remove('active'));button.classList.add('active');$('title').textContent=item.title;$('kind').textContent=item.type;const area=$('body');area.replaceChildren();
if(item.path){if(item.type==='Page'||item.type==='Assignment'||item.type==='Discussion'||item.type==='Quiz'){const f=document.createElement('iframe');f.src=item.path;f.title=item.title;area.append(f)}
else{const a=document.createElement('a');a.href=item.path;a.textContent='Open '+item.title;a.target='_blank';area.append(a);
if(/\.(mp4|webm|ogg|mp3|wav|m4a)$/i.test(item.path)){const media=document.createElement(/\.(mp3|wav|m4a)$/i.test(item.path)?'audio':'video');media.src=item.path;media.controls=true;area.append(media)}
if(/\.pdf$/i.test(item.path)){const f=document.createElement('iframe');f.src=item.path;f.title=item.title;area.append(f)}}}
else{area.textContent='This resource is listed in Canvas but is not available in the offline archive. Review export-report.json for details.'}}
function render(){const nav=$('nav'),filter=$('filter').value.toLowerCase();nav.replaceChildren();for(const section of model.modules){const items=section.items.filter(x=>x.title.toLowerCase().includes(filter));if(!items.length)continue;const h=document.createElement('h3');h.textContent=section.title;nav.append(h);for(const item of items){const b=document.createElement('button');b.textContent=item.title;b.onclick=()=>show(item,b);nav.append(b)}}}
$('filter').oninput=render;render();
</script></body></html>"""

def download(url, destination, origin, token, cancel=None):
    current=url
    with httpx.Client(follow_redirects=False,timeout=120) as client:
        for attempt in range(8):
            p=urlparse(current)
            if p.scheme!="https":raise ValueError("Non-HTTPS resource")
            headers={}
            if token and p.netloc==urlparse(origin).netloc:headers["Authorization"]="Bearer "+token
            with client.stream("GET",current,headers=headers) as response:
                if response.status_code in (301,302,303,307,308):
                    current=urljoin(current,response.headers["location"]);continue
                response.raise_for_status()
                if "text/html" in response.headers.get("content-type",""):
                    raise ValueError("Resource returned HTML, not a downloadable file")
                total=0
                with destination.open("wb") as file:
                    for chunk in response.iter_bytes(chunk_size=1024*1024):
                        if cancel and cancel.is_set():raise RuntimeError("Cancelled")
                        total+=len(chunk)
                        if total>2*1024**3:raise ValueError("Resource exceeds 2 GiB limit")
                        file.write(chunk)
                return total
    raise ValueError("Too many redirects")

def archive(session, course, inventory, output, notify=lambda _:None, cancel=None):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    report={"course":course.get("name"),"downloaded":[],"skipped":[],"errors":list(inventory.get("errors",[]))}
    with tempfile.TemporaryDirectory(prefix="coursevault-offline-") as folder:
        root=Path(folder);(root/"pages").mkdir();(root/"assets").mkdir()
        files={};url_map={};sources={}
        for f in inventory.get("files",[]):
            if f.get("locked") or f.get("locked_for_user"):continue
            url=f.get("url")
            if url and urlparse(url).scheme=="https":
                relative="assets/"+str(f.get("id"))+"-"+name(f.get("display_name") or f.get("filename"))
                sources[url]=relative;files[str(f.get("id"))]=relative
                for route in (f"/courses/{course['id']}/files/{f.get('id')}/download",f"/courses/{course['id']}/files/{f.get('id')}"):
                    url_map[session.origin+route]=relative
        for page in inventory.get("pages",[]):
            soup=BeautifulSoup(page.get("body") or "","html.parser")
            for tag in soup.select("img[src],video[src],audio[src],source[src],a[href],video[poster]"):
                for attr in ("src","href","poster"):
                    raw=tag.get(attr)
                    if not raw:continue
                    url=urljoin(session.origin+"/",raw)
                    if urlparse(url).scheme!="https":continue
                    ext=Path(urlparse(url).path).suffix.lower()
                    if ext in EXTS and urlparse(url).netloc==urlparse(session.origin).netloc:
                        sources.setdefault(url,"assets/embedded-"+str(len(sources)+1)+ext)
        for index,(url,relative) in enumerate(list(sources.items())[:2500]):
            if cancel and cancel.is_set():raise RuntimeError("Cancelled")
            notify(f"Downloading {index+1}/{min(len(sources),2500)}: {Path(relative).name}")
            try:
                size=download(url,root/relative,session.origin,session.access_token,cancel)
                url_map[url]=relative;report["downloaded"].append({"name":relative,"bytes":size})
            except Exception as exc:
                (root/relative).unlink(missing_ok=True)
                report["skipped"].append({"url":url,"reason":str(exc)})
        modules=[];page_paths={}
        for i,page in enumerate(inventory.get("pages",[])):
            slug=str(page.get("url") or i)
            page_paths[slug]="pages/"+str(i+1).zfill(3)+"-"+name(page.get("title") or slug)+".html"
        for page in inventory.get("pages",[]):
            soup=BeautifulSoup(page.get("body") or "","html.parser")
            for tag in soup.select("script,form,object,embed,base"):tag.decompose()
            for tag in soup.select("*"):
                for attribute in list(tag.attrs):
                    if attribute.lower().startswith("on"):del tag.attrs[attribute]
                for attr in ("src","href","poster","data-src"):
                    raw=tag.get(attr)
                    if not raw:continue
                    full=urljoin(session.origin+"/",raw)
                    if full in url_map:tag[attr]="../"+url_map[full]
                    elif tag.name=="iframe":
                        p=soup.new_tag("p");p.string="Embedded media unavailable offline: "+urlparse(full).hostname
                        report["skipped"].append({"url":full,"reason":"Embedded player has no supported downloadable source"})
                        tag.replace_with(p);break
                    elif full.startswith("https://") and attr=="href":tag[attr]=full
            (root/page_paths[str(page.get("url"))]).write_text(page_html(page.get("title"),str(soup)),encoding="utf-8")
        for module in inventory.get("modules",[]):
            section={"title":module.get("name","Module"),"items":[]}
            for item in module.get("items",[]):
                kind=item.get("type","Item");target=""
                if kind=="Page":target=page_paths.get(str(item.get("page_url")),"")
                if kind=="File":
                    candidate=files.get(str(item.get("content_id")),"")
                    target=candidate if candidate and (root/candidate).exists() else ""
                section["items"].append({"type":kind,"title":item.get("title") or kind,"path":target})
            modules.append(section)
        for kind,key in (("Page","pages"),("File","files"),("Assignment","assignments"),("Discussion","discussions"),("Quiz","quizzes")):
            section={"title":key.title(),"items":[]}
            for item in inventory.get(key,[]):
                target=""
                if kind=="Page":target=page_paths.get(str(item.get("url")),"")
                if kind=="File":
                    candidate=files.get(str(item.get("id")),"")
                    target=candidate if candidate and (root/candidate).exists() else ""
                if kind in ("Assignment","Discussion","Quiz"):
                    target="pages/"+kind.lower()+"-"+str(item.get("id"))+".html"
                    body=item.get("description") or item.get("message") or ""
                    (root/target).write_text(page_html(item.get("name") or item.get("title"),body),encoding="utf-8")
                section["items"].append({"type":kind,"title":item.get("title") or item.get("name") or item.get("display_name") or kind,"path":target})
            modules.append(section)
        (root/"index.html").write_text(viewer(course.get("name","Canvas course"),modules),encoding="utf-8")
        (root/"course.json").write_text(json.dumps(inventory,ensure_ascii=False,indent=2),encoding="utf-8")
        (root/"export-report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        partial=output.with_suffix(".zip.partial")
        try:
            with zipfile.ZipFile(partial,"w",zipfile.ZIP_DEFLATED,allowZip64=True) as zipped:
                for file in root.rglob("*"):
                    if cancel and cancel.is_set():raise RuntimeError("Cancelled")
                    if file.is_file():zipped.write(file,file.relative_to(root))
            partial.replace(output)
        finally:partial.unlink(missing_ok=True)
    return report
