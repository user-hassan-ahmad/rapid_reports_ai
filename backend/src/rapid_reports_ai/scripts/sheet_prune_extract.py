import json, re, sys
S=sys.argv[1]
CASES=["ct_head_cerebellar_haemorrhage","ct_head_out_of_volume_and_companion_contradiction","ctpa_acute_pe_rv_strain","ct_ap_diverticulitis_abscess","ct_tap_acute_abdomen_gda_bleed"]
def section(s, name):
    i=s.find("## "+name)
    if i<0: return ""
    j=s.find("\n## ", i+4); return s[i:len(s) if j<0 else j]
def bullets(block):
    return [re.sub(r"\s+"," ",b).strip() for b in re.findall(r"^\s*- (.+)$", block, re.M)]
def split_clauses(neg):
    body=neg.rstrip(".")
    m=re.match(r"^(No|There is no)\s+(.*)$", body)
    if not m: return [neg]
    head, rest = m.groups()
    # keep 'to suggest ...' tail with the whole negative (it scopes the list)
    tail=""
    t=re.search(r"\s+(to suggest|in the|within the|on|at)\s.*$", rest)
    if t and t.group(1)=="to suggest": tail=rest[t.start():]; rest=rest[:t.start()]
    parts=[p.strip() for p in re.split(r",\s*(?:or\s+)?|\s+or\s+", rest) if p.strip()]
    if len(parts)<2: return [neg]
    return [f"{head} {p}{tail}." for p in parts]
out=[]
for c in json.load(open(f"{S}/recon/labelled.json")):
    if c["name"] not in CASES: continue
    s=c["sheet"]; items=[]
    lane=section(s,"Clinical Lane")
    d=lane[lane.find("Differentials in scope"):lane.find("Clinical history modifiers")] if "Differentials in scope" in lane else ""
    for b in bullets(d):
        if b.startswith("**") and b.endswith(":**"): continue
        t=re.sub(r"\*\*","",b).strip()
        if len(t)>3: items.append(("differential", t))
    cur=None
    for line in section(s,"Style Exemplars").splitlines():
        m=re.match(r"^- (.+)$", line)
        if m:
            if cur: items.append(("style_exemplar", cur))
            cur=re.sub(r"\*\*","",m.group(1)).strip()
        elif re.match(r"^\s+- (.+)$", line) and cur:
            cur+=" " + re.sub(r"\*\*","",line.strip()[2:]).strip()
    if cur: items.append(("style_exemplar", cur))
    imp=section(s,"Impression Exemplars")
    variants=[re.sub(r"\*\*","",b) for b in bullets(imp) if re.match(r"\*\*[A-Za-z ]*exemplar", b)]
    items.append(("impression_variant_choice", json.dumps(variants)))
    rec=imp[imp.find("Recommendation scope"):] if "Recommendation scope" in imp else ""
    for b in bullets(rec):
        m=re.match(r"(IMAGING|REFERRAL|MDT|TISSUE|CORRELATION):\s*(.*)", b)
        if m:
            for part in re.split(r";\s*", m.group(2)):
                if len(part)>8: items.append(("recommendation", f"{m.group(1)}: {part.strip()}"))
    for b in bullets(section(s,"Conditional Suppression Rules")): items.append(("suppression_rule", b))
    for b in bullets(section(s,"Measurement Conventions")): items.append(("measurement", re.sub(r"\*\*","",b)))
    for it in c["items"]:
        if it["type"]=="mandatory_negative":
            items.append(("_negative_to_split", it["text"]))
    out.append({"name":c["name"],"scan_type":c["scan_type"],"clinical_history":c["clinical_history"],"findings":c["findings"],
                "items":[{"type":t,"text":x} for t,x in items]})
json.dump(out, open(f"{S}/prune/items.json","w"), indent=1)
from collections import Counter
for c in out: print(c["name"][:40], dict(Counter(i["type"] for i in c["items"])), len(c["items"]))
print("total", sum(len(c["items"]) for c in out))
