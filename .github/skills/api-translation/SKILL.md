---
name: api-translation
description: 'Implement dynamic API-level translation (i18n) for FastAPI response payloads using custom dictionary mappings. Use when adding multi-language support to endpoints or translating fixed database enum values.'
---

# API-Level Translation Mapping

## When to Use
- You need to translate API response fields dynamically based on the user's language (`Accept-Language` header).
- You are returning categorical or fixed values from the database (e.g., "Passed", "Failed", "1st Year").
- *Note:* Do NOT use this for dynamic user-generated content (like Admin Announcements), which should use Schema-Level multi-language fields instead.

## Procedure
1. **Inject Locale Dependency**: 
   Ensure the endpoint uses the locale dependency: `locale: str = Depends(get_locale)`.
2. **Iterate and Map**:
   When mapping database query results to Pydantic response models, do not pass the raw database strings directly to the output if they require translation.
3. **Format Keys Safely**:
   - For simple enums (like status): combine a prefix with the normalized value, e.g., `f"status_{raw_status.lower()}"`.
   - For complex strings (like semester names): normalize the string into a valid key format (lowercase, replace spaces/dots with underscores).
4. **Apply Translation with Fallback**:
   Pass the mapped key and the `locale` to the translation function (e.g., `t(status_key, locale)`).
   Always ensure there is a fallback to the original raw database string in case a specific translation key is missing from the dictionaries.

## Quality Criteria
- **Canonical DB Storage**: The database continues to store only the raw English/canonical values.
- **API Boundary Only**: Translations occur strictly at the API response layer, preserving backend reporting and logic scripts.
- **Fail-safe**: The translation lookup correctly handles missing keys by falling back gracefully without causing 500 errors.