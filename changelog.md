* Corregido la devolución de idiomas en configuración.

• 
Ahora siempre devolverá idiomas de código ISO 639-1 en la función obtenerLenguaje del manager de configuración.

* Solucionado Issue #13

• 
Importación del módulo html: Se ha añadido import html para utilizar la función html.unescape(), la cual desescapa todas las entidades HTML, incluidas las numéricas como &#39;.
• 
Eliminación de código innecesario: Se han eliminado los métodos _load_html_entities y unescape, ya que ahora se utiliza html.unescape() en los módulos de Google web.
## 2026.2 — modified community fork

- Added compatibility with NVDA 2026.1.1 AMD64 and its 64-bit Python 3.13 runtime.
- Replaced the incompatible legacy 32-bit `wx.media` component with a compatible implementation.
- Updated bundled compatibility code and translation-service integrations.
- Added and refreshed add-on localizations, including Polish.
- Fixed clipboard translation so it uses the same configured engine as simultaneous translation.
- When alternate-language mode is enabled, clipboard translation goes directly to the alternate target language without sending a preliminary language-detection request to Google.
- Successful clipboard translations are spoken and immediately replace the clipboard contents.
- Cache entries now include the selected translation engine to prevent results leaking between engines.
- Added compatibility fallbacks for translation initialization and short translation responses.

This is a modified version maintained by Axel (`wmietek8`), based on the
original work by Héctor J. Benítez Corredera. It is not an official upstream
release. See `MODIFICATIONS.md` for attribution and licensing details.
