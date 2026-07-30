# Prompt comparison note

Compared all Story-analysis variants on the discount-code checkout story.

**Default:** Story Review (`story-review`)

**Why:** Clearest, most scannable structure for a live demo (Summary / Gaps / Risks / Open Questions).
Role-Based Panel was deeper but longer. Test-First best for QA readiness.

Other variants remain selectable in Single and Compare modes.

## Non-story test case

**Input:** `Preheat oven to 180C. Mix flour and eggs. Bake for 25 minutes.`

**Expected:** Every variant returns `## Not a User Story` (names it as a recipe, asks for a real user story) — not AC gaps or a "too vague" analysis.
