# QUALITY_RULES.md

Part of **OCR Architecture v1.0 (Frozen)**.

This document is the implementation guide for the OCR Preprocessing Layer
(`modules/invoice_scan/preprocess/`). It defines *what* the layer analyses,
*how* it decides what to do, and *what guarantees* it must uphold — so that
implementation never has to guess or assume. It does not contain code, and
it does not redesign anything already frozen in OCR Architecture v1.0.

---

## 1. Purpose

Preprocessing exists to raise **saved-data accuracy**, not OCR accuracy for
its own sake. A store owner's invoice photo is frequently imperfect — tilted,
dim, slightly blurred, shadowed from a phone held at an angle — and Gemini's
extraction quality degrades with those imperfections. Correcting what can be
corrected *before* the image reaches Gemini gives the model the best
available input on the only attempt it gets.

Preprocessing happens **before** Gemini, not after, because OCR is a
single-shot operation in this architecture (see Section 9) — there is no
second pass to retry with a different image, so any correction has to
happen upstream of the one call that exists.

Preprocessing must **never reduce** OCR accuracy. Every operation in this
layer is a hypothesis that a specific correction will help a specific
measured problem (e.g. sharpening only when blur is measured as poor). It
is not applied speculatively, and if a step cannot be completed safely, the
rule is to fall back rather than risk making the image worse (Section 8).

The **original uploaded image is always preserved** and is what the user
sees in the Review stage and anywhere else the invoice is displayed. The
processed image exists only internally, as Gemini's input. This keeps the
user's trust in what they uploaded intact, and keeps preprocessing an
implementation detail rather than a user-facing behavior change.

---

## 2. Image Quality Metrics

Each metric below is something the analysis stage measures about the
uploaded image. None of these are implemented by this document — it defines
what each metric means and why it matters, not how it is computed.

| Metric | What it measures | Why it matters for OCR |
|---|---|---|
| **Blur** | How sharp or soft the edges and text strokes in the image are. | Blurred characters are the single most direct cause of Gemini misreading digits, batch numbers, and medicine names. |
| **Brightness** | Overall light level of the image. | Too dark and text disappears into shadow; too bright (overexposed) and text washes out against glare — both starve Gemini of legible contrast. |
| **Contrast** | The difference between light and dark areas of the image. | Low contrast (e.g. a faded printout, or a photo washed out by flash) makes text edges hard to distinguish from the background. |
| **Noise** | Random speckling or grain in the image, often from low-light phone photos. | Noise can be mistaken for stray marks or character fragments, and can mask fine details like decimal points or small batch codes. |
| **Rotation** | How far the invoice is tilted from perfectly upright. | Even moderate tilt can cause a model to misalign which row a value belongs to, especially in a densely packed table. |
| **Perspective** | Whether the invoice was photographed at an angle rather than straight-on (keystoning). | Perspective distortion warps column alignment across a table, which is exactly the failure mode this architecture's OCR prompt already warns against (row-shifting errors). |
| **Resolution** | The pixel dimensions of the image relative to how much text it contains. | Below a certain resolution, fine print (batch numbers, expiry dates) becomes physically too small to resolve, regardless of how sharp or well-lit it is. |
| **Shadow** | Uneven lighting across the image, typically from a hand, phone, or overhead light casting a partial shadow on the invoice. | A shadow across part of an invoice can make one region of the same document effectively darker and lower-contrast than the rest, causing inconsistent extraction quality within a single invoice. |
| **Invoice Detection** | Whether the photographed content plausibly resembles an invoice/bill at all (as opposed to, e.g., a photo of something else entirely). | Lets the pipeline recognize an obviously wrong upload before spending a Gemini call on it, rather than only discovering the mismatch after extraction returns nothing usable. |
| **Table Detection** *(future reserved)* | Whether a tabular structure (rows/columns of items) is present in the image. | Not evaluated in Phase 1. Reserved for when a future detector can identify table boundaries as part of enabling Column/ROI detection (Section 10). Recording it as a concept now means the Rule Engine and QualityReport already have a defined place for it later. |

---

## 3. Quality Levels

Each metric that drives a preprocessing decision is expressed as a
human-readable category, not a raw number, wherever the Rule Engine
(Section 4) needs to reason about it. These are conceptual categories only —
they name the levels a metric can fall into, not the numeric boundaries
between them. Where a boundary must be defined, it belongs in
`config/settings.py` as a named threshold constant (per OCR Architecture
v1.0's Rule Engine principle: "no hardcoded thresholds"), not in this
document.

**Blur**
- Excellent
- Good
- Acceptable
- Poor
- Critical

**Brightness**
- Very Dark
- Dark
- Normal
- Bright
- Overexposed

**Contrast**
- Low
- Normal
- High

**Noise**
- Low
- Medium
- High

**Rotation**
- Straight
- Slight
- Moderate
- Severe

**Perspective**
- None Detected
- Detected

**Resolution**
- Too Low
- Acceptable
- High

**Shadow**
- None Detected
- Partial
- Significant

**Invoice Detection**
- Likely Invoice
- Uncertain
- Unlikely Invoice

---

## 4. Rule Engine

The Rule Engine's only job is to **decide**. It never edits pixels, never
calls an image-processing library, and never touches Gemini. It reads the
quality levels produced by analysis (Section 3) and outputs a list of which
preprocessing operations should run. The operations themselves are executed
elsewhere (Section 5).

More than one rule may fire for a single image — an invoice can be tilted
*and* dim *and* noisy at the same time, and the Rule Engine's output is the
full set of corrections that apply, not a single choice.

**Decision matrix (illustrative — exact conditions live in the Rule Engine
implementation, sourced from `config/settings.py` thresholds):**

| Condition | Action |
|---|---|
| Blur is Poor or Critical | → Sharpen |
| Brightness is Dark or Very Dark | → Brightness Enhancement |
| Brightness is Bright or Overexposed | → Brightness Enhancement (reduce) |
| Contrast is Low | → Contrast Enhancement |
| Noise is Medium or High | → Denoise |
| Rotation is Moderate or Severe | → Auto Rotation |
| Perspective is Detected | → Perspective Correction |
| Shadow is Significant | → (flagged; no automatic correction defined in Phase 1 — see Section 10) |

If no condition is met, the Rule Engine's output is simply empty, and no
Layer A operation runs — the image passes through unmodified except for
whatever format normalization already happens today (e.g. PDF-to-PIL
conversion).

---

## 5. Execution Order

When the Rule Engine's decisions call for one or more operations, they run
in this fixed order. This order is frozen — it is not decided per-image or
reordered based on which conditions fired.

1. **Quality Analysis** — every metric in Section 2 is measured once,
   against the image as originally uploaded.
2. **Rule Engine** — decides which of steps 3–7 should run, based on step 1's
   output.
3. **Perspective Correction** — corrects keystoning/skew from an angled
   photo.
4. **Auto Rotation** — straightens remaining tilt after perspective
   correction.
5. **Brightness / Contrast** — tonal correction.
6. **Noise Removal** — denoising.
7. **Sharpening** — edge/detail enhancement.

**Why this order:** each step is chosen to run before the steps most likely
to depend on its result being correct first, and never after a step whose
output it would immediately undo or degrade:

- **Analysis before any correction** so every downstream decision is based
  on the untouched original, not on an image already altered by an earlier
  guess.
- **Geometry before tone** (perspective, then rotation, ahead of
  brightness/contrast/noise/sharpen): geometric corrections resample and
  redraw the whole image, which would blur or distort any tonal correction
  applied earlier — doing geometry first means tonal work always happens on
  the image's final shape.
- **Perspective before rotation**: correcting keystoning can itself
  introduce or change apparent tilt, so straightening should happen only
  once perspective is already resolved.
- **Noise removal before sharpening, not after**: sharpening amplifies
  edges, and applying it before denoising would sharpen the noise itself
  into more prominent artifacts.

---

## 6. Applied Steps

Every preprocessing operation actually performed on a given image is
recorded as metadata, so the QualityReport (Section 7) can show exactly
what happened to that specific image — not just what the Rule Engine was
capable of deciding.

**Example — some steps applied:**
```
Applied Steps:
- Brightness
- Noise Removal
- Sharpen
```

**Example — nothing needed:**
```
Applied Steps:
- No preprocessing required
```

This is metadata only. It does not feed back into the Rule Engine and does
not change the Execution Order for the current image — it is a record of
what already happened, produced after Section 5 completes.

---

## 7. Quality Report

The QualityReport is the single artifact that carries everything
preprocessing learned and did about one image, downstream to wherever it's
needed next (Review session today; a future Confidence Engine, per Section
10). It contains:

- **Quality Metrics** — the measurements and categories from Sections 2–3,
  as actually measured for this image.
- **Applied Steps** — the record from Section 6 of which operations ran.
- **Processing Warnings** — any non-fatal issues encountered during
  preprocessing (see Section 8) that didn't stop the pipeline but are worth
  surfacing.
- **Processing Time** — how long preprocessing took for this image.

It also contains a **reserved, optional Spatial section** — present in the
data model, but deliberately unpopulated in Phase 1. It exists as a single
generic slot for future detectors (Table Detection, Column Detection, ROI
Detection) to write structured region data into later, without requiring a
new top-level field per detector and without changing the shape any current
consumer already relies on. No implementation of what goes into this
section is defined here.

---

## 8. Failure Rules

Preprocessing is **enhancement only** — it is never allowed to be the reason
OCR does not run.

- If **any individual preprocessing step fails**, the pipeline returns the
  previous valid image in the chain (i.e., the image as it stood immediately
  before that step), not a null or broken result, and continues.
- If **preprocessing fails completely** (nothing in the chain could be
  applied), the pipeline returns the **original uploaded image, exactly as
  it was received** — the same image Gemini would have received if
  preprocessing didn't exist at all.
- **OCR must never stop, error, or be skipped because preprocessing
  failed.** Worst case for any given image is identical to today's
  behavior: Gemini receives the unmodified upload.

---

## 9. Success Criteria

These are the architectural goals this layer must satisfy. They are the bar
against which "did this implementation stay frozen" is judged:

- ✓ OCR behavior remains unchanged if preprocessing is disabled.
- ✓ The original uploaded image is never modified.
- ✓ Gemini still receives exactly one image per invoice.
- ✓ Gemini is still called exactly once per invoice (never retried, never
  split into multiple requests).
- ✓ The existing OCR pipeline (Upload → OCR → Review → Save) remains fully
  compatible — no signature changes beyond the one additive
  `quality_report` field.
- ✓ No database writes occur anywhere in this layer.
- ✓ No UI changes are required by this layer on its own (the existing
  Invoice Scan / Review / Save screens are unaffected).

---

## 10. Future Extension Points

Documented here for context only — **none of the following are
implemented, designed, or specified by this document**, and this document
does not anticipate their internal design:

- **Table Detection** — populates the reserved Spatial section (Section 7)
  with detected table boundaries.
- **Column Detection** — populates the same reserved Spatial section with
  per-column regions, likely depending on Table Detection existing first.
- **ROI (Region of Interest) Detection** — populates the same reserved
  section with other named regions of interest beyond tables/columns.
- **Confidence Engine** — a future consumer of QualityReport (via the
  additive `quality_report` field already threaded through OCR output and
  the Review session) that will use quality metrics to decide which
  extracted fields are trustworthy enough to skip manual review.
- **Validation Engine** — a future module, separate from today's per-row
  field validation in `review_service.py`, referenced only as a roadmap
  name at this stage.
- **Medicine Intelligence** — a future module, referenced only as a
  roadmap name at this stage.

`QUALITY_RULES.md` defines preprocessing only. These future modules will
consume preprocessing's output (directly, or via QualityReport) once each
is designed independently, in its own implementation phase — this document
does not define, imply, or reserve anything beyond what Sections 1–9
already describe.
