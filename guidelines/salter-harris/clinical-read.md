# Independent clinical read: salter-harris@1963.1

Reader: Claude (independent of the author). Read-only: nothing else in the pack was changed.
Method: entry.json, cases.json, review.md, manifest.json and evidence.md read in full. Every outcome, table row and
caveat was compared with the OCR text of the source. The OCR was spot-checked against the page images (PDF 20-21,
journal p.606-607: the Type IV close, Type V and Fig. 22-24 legends). The OCR is clean enough on the classification
text that no cited fact depended on an unreadable passage. The SHA-256 matches the manifest. The DOI resolves in
Crossref to "Injuries Involving the Epiphyseal Plate", JBJS Am 45(3), pp. 587-622, April 1963.

## Verdict

Source fidelity is good. All five type definitions, all five prognosis statements and all ten caveats match the
paper, and I found no fabricated fact. The pack is not ready to ship as written, for three reasons:

1. The recommendation field mixes 1963 orthopaedic management with prognosis (For Hassan 3).
2. The Type V recommendation drops a hedge the paper makes.
3. The prognosis words are the paper's 1963 words, delivered with no age modifier and no currency caveat.

Fixing 1 and 2 is a rewording of the recommendation text. Fix 3 is one or two caveats.

## For Hassan item 1 (review.md item 3): 1963 treatment lines in a radiology report

Numbering note: the brief calls this "item 1". In review.md it is item 3. Item 1 there is the missing Rang type VI.

My view: only the prognosis (plus imaging follow-up) should reach the report. The reduction route and the
three-weeks non-weight-bearing line should stay in the reference view as dated source material.

- **Role.** A radiology report recommends imaging, follow-up imaging and referral. Reduction technique and weight-bearing
  advice are decisions for the treating orthopaedic team. They depend on things the radiologist does not hold:
  neurovascular status, soft-tissue state, the child's age, displacement measured in context and local pathways.
  Writing "avoid weight-bearing for three weeks" or "open reduction is always necessary" into a report oversteps
  that role.
- **Currency.** The lines are 1963 and several are absolute in a way current practice is not.
  - "Open reduction is always necessary unless undisplaced" for Type IV is a 1963 absolute. Current practice
    commonly uses closed reduction with percutaneous fixation for some displaced injuries, and the choice depends
    on site and displacement. This is from my own knowledge, not a document on disk.
  - The Type V three-week rule is explicitly "in the hope of preventing", not an evidence-based protocol.
  - "Reduction is not difficult" (Type I) and "relatively easy" (Type II) are not actionable. They also become wrong
    if the patient presents late: the paper itself says reduction gets harder each day and after about ten days
    should not be forced.
- **Provenance.** The paper's own aim was prognosis: "knowledge of the prognosis ... is of considerable importance".
  The prognosis and the conditions it depends on are what survives the 60 years, and they are the part that is
  imaging-relevant (is the plate realigned, is the epiphyseal circulation intact).

What I would do instead:

- Split the field. The recommendation becomes prognosis only, in the paper's words. The existing `reference.tbl.management`
  stays as historical reference, labelled "1963 treatment lines, not for the report".
- Keep the conditional prognostic phrasing, which is imaging-assessable:
  - Type III: "good if the blood supply to the separated portion is intact".
  - Type IV: "bad unless the plate is completely realigned".
  - Type V: "decidedly poor, the worst of the types; premature cessation of growth almost inevitable".
- Promote the only radiology-actionable recommendation in the paper into the recommendation slot. It is currently
  buried in `reference.def.followup`. The paper says follow-up is needed for a minimum of one year. At six months, radiograph
  the injured bone and the opposite normal side. If little growth has occurred in the normal bone, wait a further six
  months. Present this as the source's follow-up scheme, attributed, not as a mandate.
- Optional: the source also says two views at right angles are essential, and that comparison views of the opposite
  limb are prudent if in doubt. That is a radiological statement and could sit in pitfalls.

## Findings

### Important

**I1. The Type V recommendation drops the paper's hedge.**
- Source: "Weight-bearing must be avoided for three weeks *in the hope of preventing* the almost inevitable premature
  cessation of growth."
- Pack (entry and `type.row4`): "Avoid weight-bearing for three weeks; premature cessation of growth is almost
  inevitable."
- The pack's wording breaks the link. A reader gets two unrelated statements. It can also read as an unconditional
  order, or as if non-weight-bearing is part of the cause.
- The tbl.management row for V keeps the hedge, so the entry and the reference disagree.
- Resolved if item 1 is adopted; otherwise restore "in the hope of preventing".

**I2. Treatment lines are in the recommendation field (see the For Hassan item 1 section above).**
- Affects the recommendation text of all five outcomes: "Reduction is not difficult", "relatively easy to obtain and
  maintain", "Accurate reduction is essential ... open operation may be necessary", "Perfect reduction ... open
  reduction always necessary", and the three-week rule.

**I3. The prognosis words carry no age modifier in the report-bearing fields.**
- The paper lists age at injury as a prognostic factor: the younger the child, the more serious any disturbance, and
  "even a serious injury incurred during the last year of growth will not produce a significant deformity". This is
  PDF 22, journal p.609.
- The pack holds this only in `reference.def.factors` and `pit.estimate`, not in any outcome caveat.
- A Type IV with "bad" prognosis in a 15-year-old and in a 4-year-old are very different statements. Skeletal
  maturity is exactly what a radiologist sees on the film.
- Fix: add one caveat to every outcome, "prognosis is an estimate; age and remaining growth modify it (paper's
  own wording)".
- The same gap applies to scope. The paper only addresses open physes, and the card does not say that growth
  prognosis is moot if the physis is closed. See I4.

**I4. Scope is carried only as a reference pitfall, not as an input or outcome caveat (For Hassan item 2: agree with the finding, disagree it is sufficient).**
- The source says nothing numeric about age, and I agree the pack must not invent a bound.
- Two scope points that the source does state could be surfaced in the outcome. First, the classification is of
  injuries to the growing plate (a "child"). Second, traction epiphyses (for example the medial epicondyle of the
  humerus) "do not contribute to longitudinal growth", so the growth prognosis does not transfer to avulsion injuries
  there.
- The aliases "physeal fracture" and "growth plate fracture", and the region "elbow", will let this card fire on a
  medial epicondyle avulsion. At minimum a caveat should say so.

**I5. The 1963 prognosis words are not flagged as 1963.**
- `status: current` and the unhedged words "excellent" (I, II) and "good" (III) are the paper's.
- Later literature reports significant growth disturbance after Type I/II injuries at some sites. The distal femur
  and the distal tibia are examples. A radiologist reporting "excellent" for a distal femoral Type II could mislead.
- This is from my own knowledge, not a source on disk. Per the house rule I am not substituting a secondary source.
  I am flagging that the card needs a modern-source cross-check, and Hassan should supply the citation (a distal
  femoral physeal fracture outcome series would be the obvious one).
- Minimum fix: caveat "paper's 1963 prognosis, site-independent; growth-disturbance risk varies by site".
  Relabel `status` if the library has a way to say "historical classification, still in use".

**I6. Golden cases: coverage is thin, and nothing tests the unmatched paths.**
- Cases 1-5 are a 1:1 mirror of the table, which only tests that the table is wired. That is acceptable for a
  tier-1 lookup, but they test no text.
- Missing cases:
  - "VI" or any out-of-enum value, expected `null` with `needed: [sh_type]`. If the engine rejects non-enum values,
    this should be asserted.
  - A combined dictation such as "III/IV" (typical of ankle triplane/Tillaux). No outcome exists, and the card should
    ask the radiologist to choose, not pick one.
  - Arabic numerals ("SH type 2"). `how_stated` promises them, but no case verifies it.
  - The `absent` / `not_assessable` states, if the engine lets a user supply them. review.md says none exist.
- Rated Important mainly for the Type VI / combined gap, which is the most likely real-world dictation failure.

### Minor

**M1. Type III "separated epiphysis" vs source "separated portion of the epiphysis".** The pack's outcome text says
"the separated epiphysis". Type III is a partial-epiphysis fracture, so "epiphysis" suggests the whole epiphysis.
`tbl.types` has the correct wording. Align the outcome text.

**M2. `tbl.management` Type IV omits "delayed reduction is preferable to leaving the fragment displaced".** The
source states this for Types III and IV together (journal p.611); the pack attaches it to III only. Harmless if
management is demoted.

**M3. Type V caveats omit that the lower tibial epiphysis is the commonest site of Type V (usually from a varus force
at the ankle) and that the true nature may not be suspected until premature closure is established.** Both are in
the source (the lower tibial epiphysis site discussion in the later, site-by-site section; page not pinned). The second would strengthen `pit.v`.

**M4. Caveats for Types II and III share one sentence ("blood supply particularly vulnerable in the head of the
femur and the head of the radius").** The source introduces it as an example under "Types I, II and III". It is not
attached to Type I because Type I already carries the cartilage-covered-epiphysis point. Faithful and intentional;
noting that the femoral-head example is mostly relevant to Type I (slipped epiphysis) in the paper's own discussion.

**M5. `manifest.json` retrieved date is 2026-10-13, which is after today (2026-10-12).** Looks like a typo.

**M6. Source "Fig. 13 / 19 / 22 / 25 / 28" figure numbers in locator sections.** Checked, correct.

**M7. Page-locator drift.** Type V's text begins at the foot of PDF 20 (j606) and its caveats are on PDF 21. The
locator says "page 21" and the section says j606-608. This is a harmless page-span artefact, as review.md says.
Type IV starts at the foot of PDF 19. The same applies to Type IV's "page 20".

**M8. `applies_to.modality: XR` only.** True to the 1963 paper. Dictation of SH type on CT or MRI is common today
(triplane, physeal bars). No harm, but modality gating will hide the card on cross-sectional reports. Hassan's call.

## Table, outcome and caveat check (all against the source, text and page images)

| item | pack | verdict |
|---|---|---|
| Type I definition | complete separation, no fracture; growth cells stay with epiphysis | matches |
| Type I prognosis | excellent unless epiphysis entirely cartilage-covered (upper femur); blood supply frequently damaged, premature closure | matches |
| Type I caveats | shearing/avulsion; birth and early childhood (thick plate); scurvy, rickets, osteomyelitis, endocrine; wide displacement uncommon, periosteum intact | match |
| Type II definition | line along the plate, out through the metaphysis; Thurston Holland sign | matches |
| Type II prognosis, caveats | excellent if circulation intact "as it nearly always is"; commonest; usually over ten; periosteum torn convex side, intact concave side with the fragment | match |
| Type III definition | intra-articular; joint surface to the weak zone, along the plate to its periphery | matches |
| Type III prognosis, caveats | good if blood supply to the separated portion intact; uncommon, upper or lower tibia, intra-articular shearing | match (M1 wording) |
| Type IV definition | intra-articular; through epiphysis, full plate, part of metaphysis; lateral condyle of humerus | matches |
| Type IV prognosis | bad unless plate completely realigned; open reduction always necessary unless undisplaced; union across plate gives local premature closure | matches (but see I2) |
| Type V definition | very severe crushing force through epiphysis to one area of the plate | matches |
| Type V prognosis, caveats | decidedly poor, worst; relatively uncommon; one-plane joints (ankle, knee); abduction/adduction; displacement unusual, first film little indication, may be dismissed as a sprain | match, except the hedge (I1) |
| reference.sum.2, .sum.3, def.arrest, def.followup, def.factors | all match; "approximately 10 per cent" and the one-year minimum confirmed | match |
| pit.scope | pressure vs traction epiphyses, no age limit | matches (needs I4 uplift) |
| tbl.management I-V | all rows match, including "overreduction cannot occur" (II) and K-wires "for a few weeks" (IV) | match |

All 11 Gate 5 low-Jev flags in evidence.md are page-span artefacts, as review.md says. I confirmed each against the page
text, including the blood-supply caveats on journal p.608 and the Type II line spanning PDF 16-17.

## Golden cases

Cases 1-5 map I to V to the right outcomes. Cases 6-7 correctly ask for the type. See I6 for gaps. No case is
clinically wrong.

## Other For Hassan items

| item | view |
|---|---|
| 1 (type VI absent) | Agree. Add the Rang type VI (perichondral ring injury) as a note only if a source is supplied; do not cite it from memory. The golden case for an out-of-enum or "VI" dictation is the real fix (I6). |
| 2 (no eligibility input) | Agree there is no source-backed age bound and none should be invented. Disagree that a reference pitfall is enough. Carry the scope in the outcome caveats (I3, I4). |
| 3 (treatment lines) | Disagree with keeping them in the recommendation. Reduce to prognosis, and promote the follow-up scheme (see the section above). |
| 4 (prognosis words as stated) | Agree. The words are faithful and the absence of per-type percentages is correct; the paper gives only the overall ~10%. Add the currency caveat (I5). |
| 5 (region list) | Agree it is a library choice. It is sensible: the paper discusses shoulder, elbow, wrist, hand (Fig. 31, proximal phalanx), hip (upper femur), knee and ankle. Worth a note that the elbow includes traction epiphyses where the card does not apply (I4). |
| 6 (DOI) | Agree. Crossref confirms the title, volume, issue and pages. |
