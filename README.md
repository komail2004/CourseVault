# ✦ CourseVault

**Your courses, beautifully preserved.** A local-first Python desktop application for macOS and Windows.

## Features

- Premium dark PySide6 desktop interface
- Official Canvas browser login (your password is not captured)
- Browse your enrolled courses
- Discover modules, pages, files and assignments via Canvas API
- Export HTML lessons, course metadata, available Canvas-hosted files and an offline index to ZIP
- Report skipped or unsupported media

## Getting started

Install Python 3.10+:

```bash
python -m venv .venv
# macOS: source .venv/bin/activate
# Windows: .venv\Scripts\activate
pip install -e .
python -m playwright install chromium
coursevault
```

Sign in to Bauman College Canvas in the browser window, select a course, and choose **Export selected course**.

## Repository structure

```
src/coursevault/
  app.py       PySide6 interface
  canvas.py    Browser session and Canvas API
  export.py    Course inventory and ZIP exporter
tests/         Unit tests
```

## Important limitations

This is an **early unverified v0.1**, not a fully tested downloader. External video embeds (Vimeo, Canvas Studio, Panopto, Kaltura), signed external storage URLs, and protected streams are not downloaded. The initial exporter also limits individual files to 250 MB. Unsupported content is listed in the export report. Live Canvas login and course export still require testing.

The browser profile is stored locally in `~/.coursevault/browser` and may retain your authenticated Canvas session. Protect this directory on shared computers. Only archive content you are permitted to download and retain.

## Next steps

- Test live Canvas sign-in and API access
- Add safe streaming downloads for signed Canvas file URLs
- Implement progress, cancellation and resume
- Add authorized video-provider download integrations
- Build and test macOS and Windows packages
