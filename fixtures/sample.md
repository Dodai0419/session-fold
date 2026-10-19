# Rate limit incident

## Cause

The /orders endpoint returned 429 for every request after the deploy. RATE_WINDOW was set to the string 60s in production. The middleware multiplied it by 1000, which gave NaN, so every request opened a window that was already full.

## Fix

The middleware now parses the duration with parseDuration before using it. The first test run failed because the import was missing. After adding the import all 42 tests passed.

- Parse durations explicitly instead of relying on string coercion in arithmetic.
- Add a test that loads the production env file.
