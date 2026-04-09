---
description: Enforce custom dictionary-based i18n mapping for FastAPI endpoints.
applyTo: "**app/api/**/*.py**"
---

# API Localization Rules

When creating or modifying FastAPI endpoints returning data to the client, adhere to these project-specific internationalization (i18n) rules:

## No External i18n Libraries
- Do **not** use `fastapi-babel`, `gettext`, or any compilation-based translation tools.
- We use a lightweight custom JSON/dictionary-based mapping approach (typically located in `app/core/i18n.py`).

## Database vs. API Boundary
- **Keep Database Clean:** Ensure that hardcoded domain values (like statuses, grades, generic terms) are queried and saved in English.
- **Translate On the Fly:** Do the translation immediately before generating the Pydantic response model. Never save translated status strings back to the database.

## Implementation Standard
1. **Locale Dependency:** Inject the user's language using `locale: str = Depends(get_locale)` in the router function.
2. **Translation Function:** Use the simple `t(key, locale)` function.
3. **Key Generation:** Formulate translation keys from raw database strings using normalized structures (e.g., converting "First Sem" to `first_sem`, "Passed" to `status_passed`).
4. **Fallback:** Always provide the original English string as a fallback in case the dictionary mapping is missing.