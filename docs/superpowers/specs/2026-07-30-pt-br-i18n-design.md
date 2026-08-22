# pt-BR Localization Design

## Goal

Add full Brazilian Portuguese localization to the MiroFish frontend. The language selector must expose `Português (Brasil)`, and new browser sessions should open in `pt-BR`.

## Scope

- Add `pt-BR` to the language registry with a Brazilian Portuguese label and LLM response instruction.
- Add a complete `locales/pt-BR.json` file covering every translation key present in the existing baseline locale files.
- Keep existing `zh` and `en` translations unchanged.
- Set `pt-BR` as the default locale only when no locale is stored in `localStorage`.
- Preserve the current language switcher UI and storage behavior.

## Architecture

The current frontend loads locale JSON files with `import.meta.glob('../../../locales/!(languages).json', { eager: true })` and only exposes files whose keys exist in `locales/languages.json`.

The implementation will follow that pattern:

- `locales/languages.json` gains a `pt-BR` entry.
- `locales/pt-BR.json` provides the message tree.
- `frontend/src/i18n/index.js` changes the initial fallback/default locale from `zh` to `pt-BR`.

No new i18n framework or component abstraction is needed.

## Data Flow

1. The app starts and loads all locale JSON files.
2. `availableLocales` includes locale files registered in `languages.json`.
3. If `localStorage.locale` exists, that value remains active.
4. Otherwise the app starts with `pt-BR`.
5. Selecting `Português (Brasil)` updates Vue I18n, `localStorage.locale`, and `document.documentElement.lang`.

## Testing

Add a focused frontend validation script that checks:

- `pt-BR` exists in `languages.json`.
- `pt-BR` has a locale JSON file.
- `pt-BR` has the same key structure as `en`.
- `pt-BR` strings do not retain obvious English source text in common first-screen keys.

Run the validation first while `pt-BR` is missing to confirm it fails, then implement the locale and rerun it successfully. Also run the frontend build.

## Non-Goals

- Do not translate backend source logs or API internals in this change.
- Do not redesign the language switcher.
- Do not remove existing locales or change existing persisted user locale behavior.
