# ✦ CourseVault

A modern **local web application** for exporting your accessible Canvas course materials to ZIP.

## Run CourseVault

**Python 3.10+** is required. Open Terminal in this repository:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
coursevault
```

On Windows, activate with `.venv\\Scripts\\activate` instead.

Your regular browser opens automatically at **http://127.0.0.1:8765**. If it doesn't, open that address manually. **No Playwright Chromium browser installation is required for the web interface.**

### Connect to Canvas

1. Sign in to your institution's Canvas in your normal browser.
2. Open **Account → Settings → New Access Token**, if your institution enables API tokens.
3. Create a token for your own account. Paste it into CourseVault, then click **Connect to Canvas**.
4. Choose a course and click **Export selected course**.
5. When ready, click **Download ZIP**.

Never share your Canvas token, screenshots of the token, or the resulting archive with unauthorized people. If your institution disables API tokens, a hosted OAuth integration requires an approved Canvas developer key.

## What is exported

- Course metadata, modules and module items
- HTML pages, assignments, discussions and quiz metadata
- Available downloadable Canvas files and directly linked Canvas-hosted media
- Offline index and `export-report.json` listing unsupported/skipped resources

**Limitations:** Third-party embedded videos (Vimeo, Panopto, Canvas Studio, etc.) are not automatically downloaded. Some signed external file URLs are skipped in token mode to protect credentials. Very large files are buffered in memory and may require improvements. Content still depends on your Canvas permissions.

## Privacy and architecture

The app binds to **127.0.0.1 only**, so it is not publicly hosted. Your token is held in the local Python server's memory, never saved to disk. The browser stores only an HttpOnly session cookie. ZIP exports are temporarily saved in the operating system's temporary folder and may remain there until cleanup; avoid shared computers.

This is a **development build**, not a security-reviewed multi-user hosted service. Do not deploy the local server to a public internet address without replacing the authentication/session model, enforcing stronger CSRF protections, rate limiting, HTTPS and export lifecycle cleanup.

## Tests

```bash
python -m pip install -e '.[test]'
pytest -q
```

The older desktop app remains available with `pip install -e '.[desktop]'` followed by `coursevault-desktop`, but the browser interface is now the default.

## Roadmap

- Test against an actual authorized Bauman College Canvas account
- Stream large files and handle signed external downloads safely
- Support offline linked assets and provider-authorized video formats
- Implement Canvas OAuth for a hosted multi-user deployment
- Add automatic cleanup and stronger production-grade session controls
