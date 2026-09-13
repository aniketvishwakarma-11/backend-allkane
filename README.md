# Take-home task — Backend and Platform

Thanks for taking the time. This should take **about five hours. Please stop at five.** We would much rather see honest and unfinished than polished and overworked, and we will ask you about what you left undone.

There are two parts. Part 1 is working in code we wrote. Part 2 is building a small piece yourself. Leave about an hour for Part 2.

## What this is

A cut-down API for a health platform. A member uploads a lab report, the service stores the readings and computes a health score out of 1000 across five pillars.

It works. It is also not safe to put in front of real patients, and the score it returns is not always trustworthy.

This mini-service is in FastAPI to keep setup light. Our production backend is Django and DRF. We are testing how you reason about unfamiliar code, which is the real day-one job.

## Setup

```bash
pip install fastapi uvicorn pyjwt
uvicorn main:app --reload
```

Open http://127.0.0.1:8000/docs. Log in as `asha` / `asha123` or `ravi` / `ravi123` to get a token.

---

## Part 1. Find what is wrong, fix it, and lock it down

**1. Find what is wrong and fix it.**

There are security problems and at least one correctness problem in the scoring. We are not telling you how many. Fix what you find, and leave what you cannot fix. A clear note about a bug you spotted but ran out of time on scores better with us than a silent gap.

**2. Write tests that lock the score.**

The score is the product. If someone refactors the engine next year, a test should fail before a patient sees a wrong number. Add tests that would catch that. Use `pytest`.

---

## Part 2. Build a small piece

Real lab reports do not agree with each other. The same marker comes back under a different name depending on which lab produced the report, so the value is right but the engine does not recognise it and silently treats the marker as missing.

Write a normalization helper that maps incoming marker names to the canonical names the engine expects, and wire it into the readings path so that scoring works correctly whichever alias arrives.

Handle at least these:

| Incoming name | Canonical name |
|---|---|
| `glucose_fasting` | `fasting_glucose` |
| `FBS` | `fasting_glucose` |
| `A1c` | `hba1c` |
| `HbA1C` | `hba1c` |
| `trigs` | `triglycerides` |

An **unknown marker name must be ignored safely.** It should not crash the request, and it should not corrupt the score.

Add tests for the helper, including the unknown-name case.

This part should take about an hour. Honest and unfinished is fine here too, and we would rather see a clean partial helper with tests than a complete one with none.

---

## Scope

We are not looking for a rewrite. Do not swap frameworks, add a database, or build a front end. Beyond the fixes in Part 1 and the helper and wiring we asked for in Part 2, leave the shape of the service alone.

## Write up what you found

In `FINDINGS.md`, for each issue you fixed: what it was, why it matters, what you changed. Two or three sentences each is plenty. Add a short note on how you built the normalization helper and why you structured it the way you did.

If you used AI tools at any point, say where. That is completely fine and we would rather know.

## What we are looking for

- Whether you can read unfamiliar code and spot what is wrong with it.
- Whether you think about who is allowed to see what, not just whether the endpoint returns 200.
- Whether the code you write yourself is clean and tested.
- Whether your commits tell a story. **Push as you go, in small commits.** One commit at the end tells us nothing, and we do look.
- Clear writing.

## How to submit

Push to a **public GitHub repository** and send us the link. Real commit history, please — that matters to us as much as the final state.

Any questions at all, just email. Asking is not a mark against you.
