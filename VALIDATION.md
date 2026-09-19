# TranslateAdvanced 2026.3: verification and limits

Checks performed on Windows on 2026-09-19. This describes observed results, not a promise that a remote translation service will never change or mistranslate a sentence.

## Automated regression tests

- Python 3.13.15 with native wxPython 4.3.1 / wxWidgets 3.3.3: **346 passed, 144 subtests passed**, no skips or failures.
- Python 3.11: **345 passed, 1 skipped, 144 subtests passed**. The skipped test requires native wxPython, which is exercised by the Python 3.13 run.
- Tests exercise real command, manager and provider implementations. NVDA, network and Win32 boundaries are substituted where required; unit tests do not touch a user's real clipboard or credentials.
- Coverage includes primary/alternate direction, explicit source-language routing, selected-provider routing for short/long/GUI input, strict errors, busy-state cleanup, cancellation, newer and same-text recopies, delayed rendering, native clipboard handle ownership and rollback, model selection, API responses, OAuth/SSE completion and commentary, redirects/TLS, auth-session shutdown races, request/output budgets, UI preferences, and Polish localization.
- Regression fixes were developed with failing tests before their production changes. Tests retain the existing catalog and attribution checks.

Reproduction:

```sh
uv run --no-project --python 3.13 --with pytest --with polib --with wxPython python -B -m pytest tests -q
uv run --no-project --python 3.11 --with pytest --with polib python -B -m pytest tests -q
```

## Real services and Windows clipboard

The recorded native runs executed the actual clipboard command, translation manager, provider HTTPS, wx main loop and Win32 clipboard. Only NVDA's surrounding host/speech boundary was substituted. The tests confirmed that the exact text passed to speech had already reached the real clipboard.

**Eight cases passed:** Polish to English and English to Polish, both short and long, through both DeepL API Pro and OpenAI ChatGPT OAuth. The long samples contained 40 numbered paragraphs, with 4,469 and 4,349 input characters. Number/order of paragraph markers and newline counts were checked; a plausible-looking but shortened output was not accepted.

Observed total times in that run (network/account/model dependent):

- DeepL short: 0.622 / 0.390 seconds; long: 1.031 / 0.691 seconds.
- OpenAI OAuth short: 2.002 / 1.474 seconds; long: 24.911 / 32.938 seconds.

A separate process tried to acquire the clipboard during every final translation write and was correctly excluded in all eight cases. Every final run verified restoration of all original supported clipboard formats. These live probes are opt-in: do not run them while another user is copying or pasting. Test code retains a private recovery file if restoration cannot be verified, and does not overwrite a newer user copy. No recovery data is included in the source repository or release archive.

Further observed checks:

- After those write tests, the final native reentrancy guard was added. `live_native_readonly.py` then confirmed actual Windows same-HWND reopen behavior, rejection of nested reads, continued exclusion of a second process, an unchanged sequence while locked, and successful guard reuse. This final delta was checked without reading or changing clipboard data; the full write tests were not rerun after that guard-only change.
- The final independent review of the OpenAI/OAuth scope found no blockers. Native reentrancy and DeepL localization fixes passed a further independent scoped review. Legacy Google/Microsoft integration fixes were separately checked against their reproduced failures and the full test suite.
- Real OAuth inference with explicit `gpt-6-astra` and the default-selected `gpt-5.6-luna`, in both language directions.
- Earlier long repeated-line tests, followed by the distinct numbered-paragraph tests above.
- Hidden native wx OpenAI dialog construction and accessible control names, without reloading the running NVDA instance.
- Official Codex initialize/account/model discovery and a real isolated login start/cancel cycle, with process cleanup.
- OAuth translation tests used an isolated access-only copy; they did not copy or rotate the personal Codex refresh token. The original auth file was compared after testing and remained unchanged.

The test machine had Codex CLI 0.155.0. The add-on does not require precisely that version; upstream protocol changes can still break the experimental transport.

## What was not proven

- **No real paid OpenAI API-key inference:** no OpenAI API key was configured for this task. API request/response/error/redirect behavior was tested with deterministic substitutes and loopback HTTP, not represented as a real paid API success.
- **No complete first-time browser login by the user:** starting/cancelling the official login flow and inference with existing isolated access are not a substitute for completing a new browser login.
- **No gesture/voice test inside the running NVDA process:** native clipboard and wx behavior were real, but speech was captured at the NVDA boundary, not judged by listening. The installed, running add-on was not replaced or restarted. Installing the new package and restarting NVDA remain necessary.
- No claim of exhaustive linguistic accuracy or a universal best translation model. `auto` is a practical preference over available models; explicit models never silently fall back.
- Legacy providers other than the tested DeepL API and OpenAI paths were covered by routing regression tests, not live account tests for every vendor.

## Transport and packaging checks

OpenAI key mode uses the public Responses API. ChatGPT mode uses the official Codex app-server for login/account/model management, but inference uses an **experimental, undocumented ChatGPT/Codex endpoint**. No agent thread/turn is started for clipboard text and no model-controlled tools are enabled. This is not advertised as a stable public third-party OAuth API.

Static analysis is compared against the original fork baseline. The repository has existing lint findings and NVDA-injected translation names; it is not described as globally lint-clean. Newly flagged process launch and cleanup patterns are independently reviewed rather than suppressed wholesale.

`tests/audit_addon.py` audits the built archive: ZIP integrity, matching version and Python sources, compilation, Polish catalog, PL/EN help, original author/GPL, absence of auth/config/test/cache files, and absence of explicitly supplied private credential values. Build and release hashes are published with the release, not invented here.

Live reports and raw private diagnostics remain local. This document deliberately contains no API keys, auth tokens, personal clipboard contents or recovery files.
