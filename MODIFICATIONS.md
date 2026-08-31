# Modified version: attribution and change record

## Origin and authorship

**TranslateAdvanced was created by Héctor J. Benítez Corredera** (`hxebolax`, <xebolax@gmail.com>). The official upstream source is <https://github.com/hxebolax/TranslateAdvanced>.

This repository is a modified community fork maintained by **Axel (`wmietek8`)**. It is not an official upstream release. Axel authored the changes listed below, developed after upstream version `2024.09.19`. Existing notices and translator credits remain intact.

## Scope of Axel's work since upstream 2024.09.19

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
