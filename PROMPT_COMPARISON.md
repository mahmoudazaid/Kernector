# Prompt comparison note

Compared the five interview-prep prompt variants for Kernector.

## Techniques

| Key | Name | Technique |
|-----|------|-----------|
| `role_qa` | Role Q&A Generator | Zero-shot + role prompting |
| `star_coach` | STAR Answer Coach | Few-shot |
| `ask_interviewer` | Questions for the Interviewer | Chain-of-Thought |
| `jd_analyser` | JD Analyser & Study Plan | Structured output |
| `pitch_polisher` | Elevator Pitch Polisher | Constraint + critique |

## Default

**Default:** Role Q&A Generator (`role_qa`)

**Why:** Clearest live demo — user pastes a job title + seniority and gets usable interview questions in one shot. Other modes need longer or different inputs (full JD, draft STAR answer, pitch).

| Variant | Best when | Trade-off |
|---------|-----------|-----------|
| Role Q&A | First demo / quick prep | Less tailored than a full JD |
| STAR Coach | Practising behavioural answers | Needs a real draft answer |
| Ask Interviewer | End-of-interview questions | Needs company + role |
| JD Analyser | Deep prep from a posting | Longer input and output |
| Pitch Polisher | Opening self-intro | Narrow use case |

Other variants remain selectable in Single mode. Compare mode runs all five on the same input — useful for technique contrast, but each prompt expects a different input shape, so prefer Single for real prep.

## Guard test (non-interview input)

**Input:** `Preheat oven to 180C. Mix flour and eggs. Bake for 25 minutes.`

**Expected:** Every variant returns `## Not Interview Prep` (names it as a recipe, asks for the right interview input) — not fake interview questions.

## Sample inputs used

- Role Q&A: `Junior Data Analyst`
- STAR Coach: behavioural question + weak draft answer
- Ask Interviewer: `Company: Spotify` / `Role: Senior Backend Engineer`
- JD Analyser: pasted job description excerpt
- Pitch Polisher: short vague elevator pitch + target role