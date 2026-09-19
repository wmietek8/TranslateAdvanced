# Modified version: attribution and change record

## Origin and authorship

**TranslateAdvanced was created by Héctor J. Benítez Corredera** (`hxebolax`, <xebolax@gmail.com>). The official upstream source is <https://github.com/hxebolax/TranslateAdvanced>.

This repository is a modified community fork maintained by **Axel (`wmietek8`)**. It is not an official upstream release. Axel authored the changes listed below, developed after upstream version `2024.09.19`. Existing notices and translator credits remain intact.

## Changes shipped in 2026.3

- Restored bidirectional clipboard translation using the existing primary/alternate language settings. DeepL API provides its own detected source language; the original text is translated a second time only when direction switching requires it. No Google request occurs for DeepL or OpenAI translation.
- Replaced the blocking clipboard command with a cancellable worker and main-thread clipboard/speech delivery. The command can be used while live translation is enabled. Clipboard generation checks protect newer copies; a successful result is copied before being spoken.
- Removed the old long-text detour through Google. Clipboard, file and translation-window requests use the selected provider. The shared path limits input to 24,000 characters; unsupported automatic-direction providers report a clear limitation instead of silently contacting another provider.
- Modernized the existing OpenAI provider (index 9), preserving existing API-key configuration. Added public Responses API, per-authentication model choices, live model discovery, strict output validation, refusal/incomplete/error handling, and model-aware cache keys. Explicit model IDs are never silently replaced after errors.
- Added isolated managed ChatGPT OAuth via the official Codex app-server. Translation uses an **experimental undocumented ChatGPT/Codex HTTPS transport**, without starting agent turns or enabling model-controlled tools. This is not presented as a supported public third-party OAuth API. Codex is installed separately; no Codex binaries or account credentials are redistributed in the add-on.
- Added a keyboard-accessible OpenAI dialog with separate API/ChatGPT preferences, login/cancel/status/logout and asynchronous model discovery. Account actions are explicit and independent of cancelling preference edits.
- Removed legacy Google modules' process-wide disabling of TLS verification. Authenticated requests verify HTTPS, protect credentials from redirects and avoid exposing server error bodies or tokens.
- Added Polish/English usage guides, safe opt-in live-service/native-Windows smoke scripts, and regression/security tests. Original attribution and GPL v2 are preserved. Model recommendations follow OpenAI's published positioning, not an invented translation benchmark.

See `USER_GUIDE_PL.md`, `USER_GUIDE_EN.md` and `VALIDATION.md` for usage, known limits and exactly which tests were performed. Historical 2026.2 details below describe the previous release, not the new bidirectional behavior.

## Changes shipped in 2026.2 (historical)


### NVDA 2026 and 64-bit compatibility

- Ported the add-on to **NVDA 2026.1.1 AMD64**, running Python 3.13 on 64-bit Windows.
- Replaced the incompatible Python 3.11/32-bit `wx.media` binary path with a new Windows MCI-based compatibility implementation.
- Added media loading, playback, pause, stop, seeking, volume, speed, timing and wx event support required by the add-on.
- Updated Python code and translatable strings for the current NVDA runtime.

### Translation and localization infrastructure

- Added a local gettext compatibility layer that selects the NVDA/system language and falls back safely to English.
- Added module-level and built-in translation initialization needed by the current add-on runtime.
- Added a complete Polish catalog and refreshed German and English catalogs.
- Preserved existing upstream translator credits in unchanged catalogs.
- Expanded the language update metadata to include Arabic and German and refreshed language revisions.
- Corrected PO metadata and newline consistency so all catalogs compile with standard GNU `msgfmt`.

### DeepL and translation engines

- Reworked DeepL Free and Pro support around the current official JSON API and `DeepL-Auth-Key` authorization.
- Added normalized source/target language handling, request timeouts, formatting preservation and safer error reporting that does not expose API keys.
- Updated usage reporting for current DeepL account fields.
- Added context and post-processing for short game, chat and interface messages where machine translation commonly changes meaning.
- Updated compatibility and localization handling in the Google alternative, Microsoft and OpenAI backends.

### Translation behavior and cache correctness

- Added a shared short-message correction layer for common game/UI mistranslations, whitespace preservation and selected English-to-Polish phrases.
- Isolated translation cache entries by application, target language **and translation engine**, preventing results from one engine being reused by another.
- Updated cache deletion to remove both the current engine-specific cache and legacy cache names.

### Clipboard workflow

- Fixed clipboard translation so it uses the **same engine selected for simultaneous translation**, rather than always calling Google Free.
- With alternate-language mode enabled, clipboard text goes directly to the alternate target language through the selected engine; there is no preliminary request to Google's language detector.
- Successful clipboard translations are spoken by NVDA and immediately replace the clipboard contents, ready to paste.
- Translation state and configured target language are restored safely after the command completes.

### Tests and reproducible builds

- Added regression tests for selected-engine routing, absence of a Google detector request, spoken output and clipboard replacement.
- Updated project metadata to version `2026.2` and recorded compatibility with NVDA `2026.1.1` AMD64.
- Restored a clean SCons build using standard GNU gettext tooling.
- Added generated-artifact exclusions so caches, bytecode and release packages are not committed as source.

At the time this release was prepared, the source comparison comprised 11 changed or new Python modules, about 940 added Python lines, a 1,983-line Polish PO catalog, refreshed German and English catalogs, and supporting tests and documentation.

## License

The original project and this modified version are distributed under the **GNU General Public License, version 2**. The complete license is in `COPYING.txt`. Source code for this distributed modified version is available in this repository.

No warranty is provided. Under GPL v2, recipients may use, study, modify and redistribute this version under the same license terms. Original copyright notices must remain intact.
