# Gate 5: Jev evidence for sins@2010.1

| field | claim | source | Jev | |
|---|---|---|---|---|
| sins_band | SINS total bands: 0 to 6 (stability); 7 to 12 (indeterminate, possibly impending, instability); 13 to 18 (instability) | S1 p4 | 0.64 |  |
| sins_outcome.row0 | SINS 0 to 6: the paper's 'stability' band.: when sins_band is 0 to 6 (stability) | S1 p4 | 0.69 |  |
| sins_outcome.row1 | SINS 7 to 12: 'indeterminate (possibly impending) instability'. → Patients with SINS 7 to 18 warrant surgical consultation.: when sins_band is 7 to 12 (indeterminate, possibly impending, instability) | S1 p4 | 0.74 |  |
| sins_outcome.row2 | SINS 13 to 18: the paper's 'instability' band. → Patients with SINS 7 to 18 warrant surgical consultation.: when sins_band is 13 to 18 (instability) | S1 p4 | 0.72 |  |
| outcome.b0_6 | SINS 0 to 6: the paper's 'stability' band. | S1 p4 | 0.74 |  |
| outcome.b0_6.caveat0 | This card does not compute SINS: the six components are not scored here, and the total is taken as dictated. | S1 p4 | 0.09 | **check** |
| outcome.b0_6.caveat1 | The paper states surgical consultation only for 7 to 18 and gives no management for this band. | S1 p4 | 0.34 | **check** |
| outcome.b0_6.caveat2 | The authors present SINS as one component of the work-up, not a decision rule; neurological deficit or high-grade cord compression indicate surgery regardless of score. | S1 p4 | 0.08 | **check** |
| outcome.b7_12 | SINS 7 to 12: 'indeterminate (possibly impending) instability'. → Patients with SINS 7 to 18 warrant surgical consultation. | S1 p4 | 0.70 |  |
| outcome.b7_12.caveat0 | This card does not compute SINS: the six components are not scored here, and the total is taken as dictated. | S1 p4 | 0.09 | **check** |
| outcome.b7_12.caveat1 | The authors present SINS as one component of the work-up, not a decision rule; neurological deficit or high-grade cord compression indicate surgery regardless of score. | S1 p4 | 0.08 | **check** |
| outcome.b13_18 | SINS 13 to 18: the paper's 'instability' band. → Patients with SINS 7 to 18 warrant surgical consultation. | S1 p4 | 0.49 | **check** |
| outcome.b13_18.caveat0 | This card does not compute SINS: the six components are not scored here, and the total is taken as dictated. | S1 p4 | 0.09 | **check** |
| outcome.b13_18.caveat1 | The authors present SINS as one component of the work-up, not a decision rule; neurological deficit or high-grade cord compression indicate surgery regardless of score. | S1 p4 | 0.08 | **check** |
| outcome.b13_18.caveat2 | At a total of 14 the paper is inconsistent: case 1 (14) is read as indeterminate instability, case 2 (14) as unstable. This pack follows the band text. Library addition: quote the number as well as the label. | S1 p4 | 0.68 |  |
| reference.sum.1 | Six components (location, pain, bone lesion quality, alignment, vertebral body collapse, posterolateral involvement) are scored and summed to give 0 to 18 for a neoplastic spinal lesion. | S1 p4 | 0.69 |  |
| reference.sum.2 | Bands: 0 to 6 stability; 7 to 12 indeterminate (possibly impending) instability; 13 to 18 instability. Scores of 7 to 18 warrant surgical consultation. | S1 p4 | 0.74 |  |
| reference.def.pain | Pain: pain with movement, upright posture or loading of the spine, and/or relieved by recumbency, 3; occasional pain that is not mechanical 1; pain-free lesion 0. | S1 p4 | 0.84 |  |
| reference.def.bone | Bone lesion quality: lytic 2; mixed lytic/blastic 1; blastic 0. The authors note CT is the best modality for defining this. | S1 p4 | 0.53 |  |
| reference.def.alignment | Radiographic alignment of the motion segments affected by tumour: subluxation or translation 4; de novo kyphosis or scoliosis 2; normal 0. De novo deformity needs prior imaging or upright versus supine comparison. | S1 p4 | 0.92 |  |
| reference.def.collapse | Vertebral body collapse: more than 50% collapse 3; less than 50% collapse 2; no collapse but more than 50% of the body involved 1; none of these 0. | S1 p4 | 0.66 |  |
| reference.def.total | Total SINS is the sum of the six component scores; the text gives a range of 0 to 18. | S1 p4 | 0.72 |  |
| reference.tab.bands | Total SINS band and what the source attaches to it: Total score | Source label | Surgical consultation | S1 p4 | 0.56 |  |
| reference.tab.cases | The paper's worked cases: Case | Components (location, pain, bone, alignment, collapse, posterolateral) | Total | Source reading | S1 p4 | 0.40 | **check** |
| reference.pit.band1318 | At a total of 14 the paper is inconsistent: the band text labels 13 to 18 instability and case 2 (14) is unstable, but case 1 (also 14) is read as indeterminate instability. Both 14s sit in the 13 to 18 band; this pack follows the band text. | S1 p4 | 0.41 | **check** |
| reference.pit.collapse | Vertebral body collapse of exactly 50% is not defined (more than 50% scores 3, less than 50% scores 2). Table 6 scores 'none of the above' as 0 while the text scores 0 only for no body involvement, so involvement of 50% or less without collapse is not explicitly scored. | S1 p4 | 0.48 | **check** |
| reference.pit.alignment | De novo deformity needs knowledge of prior imaging or upright versus supine radiographs; alignment is judged between the motion segments affected by tumour. | S1 p4 | 0.86 |  |
| reference.pit.blastic | The Bone Lesion Quality text says blastic lesions score 1 and lytic 2 with no mixed category; Tables 4 and 8 give blastic 0, mixed 1, lytic 2. The pack follows the tables. | S1 p4 | 0.13 | **check** |
| reference.pit.integer | SINS totals are whole numbers, but the schema has no integer constraint on the input, so a fractional total such as 6.5 would band into 7 to 12. Dictate and read only whole totals. | S1 p4 | 0.04 | **check** |
| reference.sum.3 | The authors stress SINS is one component of the work-up. Surgery is indicated regardless of score with neurological deficit or high-grade cord compression; modifying factors it omits must also be weighed. | S1 p8 | 0.80 |  |
| reference.sum.4 | Each lesion or region is scored separately; scores are not summed across lesions. The authors call for further validation and reliability testing of the score. | S1 p8 | 0.84 |  |
| reference.tab.components | SINS component scores: Component | Finding | Score | S1 p8 | 0.44 | **check** |
| reference.pit.min | The scoring paragraph gives a minimum of 0; the Discussion says a minimum of 2. Component tables allow 0 for every component, so 0 is possible. | S1 p8 | 0.18 | **check** |
| reference.pit.multi | Not summed across lesions: each lesion or region is scored separately. The score gives no global spinal score and does not predict interaction between multiple lesions. | S1 p8 | 0.82 |  |
| reference.pit.notalone | Not a decision rule on its own. With neurological deficit or high-grade cord compression surgery is indicated regardless of score; histology, prognosis, health, neurology and patient choice also bear on treatment. | S1 p8 | 0.61 |  |
| reference.pit.unscored | Not scored: contiguous multilevel and noncontiguous disease, prior laminectomy or surgery, prior radiation, diffuse bony involvement or poor bone quality, body weight and activity level. The authors say these are qualifiers. | S1 p8 | 0.72 |  |
| reference.pit.status | Authors describe content validity from a Delphi consensus and say further validation and reliability testing are needed. | S1 p8 | 0.47 | **check** |
| reference.sum.5 | NICE NG234 (2023) says to consider a validated spinal stability scoring system such as SINS alongside clinical assessment, and to use scoring only within a full clinical assessment. It gives no SINS score thresholds. | S2 pNone | 0.56 |  |
| reference.sum.6 | NG234 also says to consider multiplanar viewing or 3-plane reconstruction of recent or new CT in spinal metastases or MSCC to assess spinal stability and plan vertebroplasty, kyphoplasty or spinal surgery. | S2 pNone | 0.43 | **check** |
| reference.pit.ng234 | NG234 recommends SINS only as a 'consider' option alongside clinical assessment and attaches no action to a score band. Its surgery recommendations are also 'consider' options within a multidisciplinary treatment plan (1.11.1, 1.11.7), unlike the paper's 'indicated regardless of score'. The 7 to 18 surgical consultation line is the paper's, not NICE's. | S2 pNone | 0.26 | **check** |
| reference.def.location | Spine location: junctional (occiput to C2, C7 to T2, T11 to L1, L5 to S1) 3; mobile (C3 to C6, L2 to L4) 2; semi-rigid (T3 to T10) 1; rigid (S2 to S5) 0. | S1 p3 | 0.84 |  |
| reference.pit.rigid | Rigid segments are S2 to S5 in Table 2 but S2 to S4 in its footnote. | S1 p3 | 0.62 |  |
| reference.def.posterior | Posterolateral involvement (facet, pedicle or costovertebral joint fracture or replacement by tumour): bilateral 3; unilateral 1; none 0. | S1 p5 | 0.89 |  |
| reference.def.instability | Authors' working definition: loss of spinal integrity from a neoplastic process, associated with movement-related pain, symptomatic or progressive deformity and/or neural compromise under physiologic loads. | S1 p6 | 0.66 |  |

44 facts; 18 below 0.5: read each against the source in review.md.
