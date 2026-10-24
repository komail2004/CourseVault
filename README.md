# ✦ CourseVault

**Your learning, beautifully preserved.** A local-first Canvas course archive application for macOS and Windows.

## Current implementation

- Polished dark PySide6 desktop interface with course selection, status messages and export cancellation.
- Browser-based Canvas authentication (including institution SSO/MFA where supported). Passwords are entered into Canvas, not CourseVault.
- Persistent local Canvas session and HTTPS server validation.
- Paginated Canvas API discovery for active courses, modules and module items, lesson pages, files, assignments, discussions and quiz metadata.
- HTML lesson snapshots, JSON metadata, authorized downloadable files, offline index and detailed export report.
- Atomic ZIP creation: incomplete archives are not kept after cancellation.
- Backend unit tests and GitHub Actions test workflow.
- Experimental macOS/Windows build workflow.

## Run from source

Install Python 3.10 or newer, then:

```bash
python -m venv .venv
# macOS: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e .
python -m playwright install chromium
coursevault
```

Click **Connect to Canvas** to sign in on the official Bauman College Canvas website, select a course, then choose **Export selected course**. Your archive contains `index.html`, `course.json`, lesson pages, files and `export-report.json`.

Run tests with:

```bash
pip install pytest
pytest -q
```

## Security

Your Canvas password is not stored by CourseVault. The browser session is saved in `~/.coursevault/session.json`, which contains sensitive authentication cookies; keep it private and delete it to sign out locally. Export only course materials you are authorized to retain. The application does not circumvent DRM or access restrictions.

## Known limitations and testing status

**Not yet verified with a live Bauman College account.** Canvas instances may vary in their authentication and file delivery setup. External embedded videos (Canvas Studio, Vimeo, Panopto, Kaltura, etc.) are detected and listed as skipped, not downloaded. There is no DRM bypass. Signed external file URLs may or may not work depending on provider behavior. Individual file downloads are currently buffered in memory rather than streamed; very large files may exhaust memory. External images and interactive content in HTML lessons may require internet access. The packaging workflow is experimental; Playwright Chromium may require a separate installation on the target computer.

The earlier `canvas.py` and `export.py` files are prototype modules retained for reference; the production UI now uses `backend.py`.

## Next steps

- Validate real Canvas login and API responses with a permitted test account.
- Stream large downloads and add file-size/disk-space controls.
- Support offline image assets and links.
- Integrate provider-approved downloadable video formats.
- Verify standalone macOS and Windows builds and browser packaging.
