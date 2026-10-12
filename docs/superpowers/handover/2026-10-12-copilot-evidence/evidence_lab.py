"""Evidence lab: can Jev alone judge every claim (with branch context)? Two wordings, 24 claims, real sources."""
import asyncio, json, os, sys
from rapid_reports_ai.hybrid_stack.copilot import jev as J
D='/private/tmp/claude-501/-Users-hassan-Code-rapid-reports-ai-backend/fd51e277-f516-44fa-9745-b9c03394630b/scratchpad/evlab/'
src=json.load(open(D+'sources.json'))
def text(*keys): return "\n\n".join(f"[{c['url']}]\n{c['text']}" for k in keys for c in src[k]['chunks'])
FL=text('Fleischner|Solid nodule','Fleischner|Subsolid nodule'); ESE=text('ESE adrenal incidentaloma|Imaging assessment'); BO=text('Bosniak|Classes')
F="In Fleischner 2017, "; E="In ESE adrenal incidentaloma 2023, "
C=[ # (id, source, kind, truth, claim)
("F1",FL,"exact",1,F+"for solid nodules: when 6–8 mm, one follow-up CT at 6–12 months, with a second scan at 18–24 months for selected cases."),
("F2",FL,"exact",1,F+"for subsolid nodules: follow-up at 6–12 months and then periodic surveillance for up to 5 years."),
("F3",FL,"exact",1,F+"for solid or subsolid nodules: when smaller than 6 mm in a low-risk patient, no follow-up is generally recommended."),
("F4",FL,"reworded",1,F+"for solid nodules: when larger than 8 mm, consider CT at 3 months, PET-CT or tissue sampling."),
("F5",FL,"reworded",1,F+"for nodules under 6 mm in a high-risk patient: an optional CT at 12 months."),
("F6",FL,"reworded",1,F+"for transient subsolid nodules: the follow-up CT interval is 12 months rather than 3 months."),
("F7",FL,"wrong_number",0,F+"for solid nodules: when 6–8 mm, one follow-up CT at 3–6 months."),
("F8",FL,"wrong_number",0,F+"for subsolid nodules: periodic surveillance for up to 2 years."),
("F9",FL,"wrong_branch",0,F+"for subsolid nodules: when 6–8 mm, one follow-up CT at 6–12 months, with a second scan at 18–24 months for selected cases."),
("F10",FL,"wrong_branch",0,F+"for solid nodules: follow-up at 6–12 months and then periodic surveillance for up to 5 years."),
("F11",FL,"wrong_guideline",0,"In Bosniak 2019, for solid nodules: when 6–8 mm, one follow-up CT at 6–12 months."),
("F12",FL,"not_stated",0,F+"for perifissural nodules larger than 10 mm: CT at 3 months."),
("F13",FL,"wrong_branch",0,F+"for nodules under 6 mm in a low-risk patient: an optional CT at 12 months."),
("E1",ESE,"exact",1,E+"for imaging assessment: homogeneous lesions with ≤10 HU on unenhanced CT are benign and do not require any additional imaging, independent of size."),
("E2",ESE,"reworded",1,E+"for homogeneous tumours under 4 cm with 11 to 20 HU: immediate additional imaging is recommended."),
("E3",ESE,"reworded",1,E+"for lesions over 4 cm that are inhomogeneous or have HU above 20: surgery is usually the management of choice."),
("E4",ESE,"wrong_number",0,E+"for imaging assessment: homogeneous lesions with ≤20 HU on unenhanced CT are benign and need no further imaging."),
("E5",ESE,"wrong_guideline",0,E+"follow-up at 3 to 6 months after the initial imaging, continuing for 1 to 2 years regardless of imaging features."),
("E6",ESE,"wrong_edition",0,E+"for indeterminate lesions: interval imaging at 6 to 12 months is preferred over immediate additional imaging."),
("B1",BO,"not_stated",0,"In Bosniak 2019, for class IIF: follow-up imaging at 6 months, 12 months, then annually for 5 years."),
("B2",BO,"reworded",1,"In Bosniak 2019: the update incorporates MRI and establishes definitions for previously vague imaging terms."),
("R1",FL,"rule_true",1,F+"rule for solid nodules: under 6 mm in low-risk patients no routine follow-up; 6–8 mm CT at 6–12 months then 18–24 months in selected cases; over 8 mm CT at 3 months, PET-CT or tissue sampling."),
("R2",FL,"rule_wrong_number",0,F+"rule for solid nodules: under 6 mm in low-risk patients no routine follow-up; 6–8 mm CT at 3–6 months; over 8 mm CT at 3 months, PET-CT or tissue sampling."),
("R3",FL,"rule_wrong_branch",0,F+"rule for subsolid nodules: under 6 mm no follow-up; 6–8 mm one CT at 6–12 months and a second at 18–24 months; over 8 mm CT at 3 months, PET-CT or tissue sampling."),
]
W={"A_current":"The SOURCE states this, with the same values: {c}",
   "B_strict":("The SOURCE states this for exactly the guideline, edition and category named, with the same values "
               "(a statement the SOURCE makes only about a different category, edition or guideline does not count): {c}")}
async def main(run):
    rows=[]
    for cid,s,kind,truth,claim in C:
        qs={w:{"type":"noul","instructions":t.format(c=claim)} for w,t in W.items()}
        got=await J._ask_windowed(s,qs)
        rows.append({"id":cid,"kind":kind,"truth":truth,**{w:round(got[w],3) for w in W},"claim":claim})
    json.dump(rows,open(D+f"run{run}_{os.getpid()}.json","w"),indent=1)
    for r in rows: print(f"{r['id']:4} {r['kind']:18} T={r['truth']}  A={r['A_current']:.2f}  B={r['B_strict']:.2f}")
    for w in W:
        trues=[r[w] for r in rows if r['truth']]; falses=[r[w] for r in rows if not r['truth']]
        bar=max(falses)+0.01
        print(f"{w}: max false={max(falses):.2f}  min true={min(trues):.2f}  recall at zero-false bar ({bar:.2f}): {sum(t>=bar for t in trues)}/{len(trues)}")
        for b in (0.5,0.6,0.7,0.8): print(f"   @{b}: true {sum(t>=b for t in trues)}/{len(trues)}, false yes {sum(f>=b for f in falses)}/{len(falses)}")
asyncio.run(main(sys.argv[1]))
