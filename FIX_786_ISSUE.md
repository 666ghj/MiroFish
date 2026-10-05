# Fix: Browser Tab Title and Meta Description Not Localized (Issue #786)

## The Problem

**Upstream issue:** [666ghj/MiroFish#786](https://github.com/666ghj/MiroFish/issues/786)  
**Labels:** `enhancement`, `good first issue`

### Symptom

No matter which language the user selects, the browser tab always shows:

```
MiroFish - 预测万物
```

And the page meta description is always:

```
MiroFish - 社交媒体舆论模拟系统
```

Even when the UI switches to English or any other supported language.

---

### Root Cause

`frontend/index.html` hardcodes the Chinese values directly in the HTML:

```html
<!-- frontend/index.html -->
<meta name="description" content="MiroFish - 社交媒体舆论模拟系统" />
<title>MiroFish - 预测万物</title>
```

Every locale file (`locales/en.json`, `locales/zh.json`, etc.) already defines the correct translated values under a `meta` key:

```json
// locales/en.json
{
  "meta": {
    "title": "MiroFish - Predict Everything",
    "description": "MiroFish - Social Media Opinion Simulation System"
  }
}
```

```json
// locales/zh.json
{
  "meta": {
    "title": "MiroFish - 预测万物",
    "description": "MiroFish - 社交媒体舆论模拟系统"
  }
}
```

But nothing in the codebase ever reads these keys and applies them to the document. The `<script setup>` block in `frontend/src/App.vue` was empty (just a comment), and there was no code anywhere that called `t('meta.title')` or touched `document.title`.

A secondary issue: `index.html` sets `html[lang]` once via an inline script on page load, but it never updates when the user switches language mid-session.

---

## The Fix

**File changed:** `frontend/src/App.vue`

Added a `watchEffect` in `<script setup>` that reads the translation keys via `useI18n()` and writes them to the document reactively:

```vue
<script setup>
import { watchEffect } from 'vue'
import { useI18n } from 'vue-i18n'

const { t, locale } = useI18n()

watchEffect(() => {
  document.title = t('meta.title')
  document.querySelector('meta[name="description"]')
    ?.setAttribute('content', t('meta.description'))
  document.documentElement.lang = locale.value
})
</script>
```

### Why This Works

| Aspect | Detail |
|---|---|
| **Reactive** | `locale` is a reactive ref from vue-i18n. `watchEffect` explicitly tracks `locale.value`, so it re-runs automatically on every language switch. |
| **No new dependencies** | `vue-i18n` (v11) and `vue` are already installed and initialized in `main.js`. |
| **Root component** | `App.vue` is always mounted, so the effect runs for every page/route. |
| **Bonus fix** | `document.documentElement.lang` is also updated reactively, keeping the HTML `lang` attribute in sync after the user changes language (previously only set once at load). |

### Before vs. After

| Condition | Before | After |
|---|---|---|
| App loads in English | Tab: `MiroFish - 预测万物` | Tab: `MiroFish - Predict Everything` |
| User switches to Chinese | Tab: still `MiroFish - 预测万物` | Tab: `MiroFish - 预测万物` |
| User switches back to English | Tab: still `MiroFish - 预测万物` | Tab: `MiroFish - Predict Everything` |
| `html[lang]` attribute | Stays `zh` after language switch | Updates to `en`/`zh` dynamically |

---

## Files Modified

| File | Change |
|---|---|
| `frontend/src/App.vue` | Added `<script setup>` with `watchEffect` to apply `meta.title`, `meta.description`, and `html[lang]` from active locale |

`frontend/index.html` was intentionally **not changed** — the hardcoded Chinese fallback values there serve as the pre-Vue-mount default (no flash of wrong content before the app hydrates). Vue overwrites them immediately on mount.

---

## How to Test

1. Install dependencies and start the dev server:
   ```bash
   cd frontend
   npm install
   npm run dev
   ```

2. Open the app in a browser and check the browser tab — it should show:
   - `MiroFish - Predict Everything` if locale is `en`
   - `MiroFish - 预测万物` if locale is `zh`

3. Switch the language in the UI — the tab title, meta description, and `<html lang>` attribute should all update immediately without a page reload.

4. Reload the page — the correct locale title should persist (locale is saved to `localStorage`).

---

## Pull Request

**PR:** [varun-projects/MiroFish#1](https://github.com/varun-projects/MiroFish/pull/1)  
**Branch:** `fix/786-localize-page-metadata`
