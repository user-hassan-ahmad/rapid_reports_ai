from rapid_reports_ai.hybrid_stack.copilot import tnm as N


def test_sites_closed_list_excludes_non_tnm():
    s = N.sites()
    assert "Lung" in s and "Kidney" in s and "Gastrointestinal Stromal Tumour (GIST)" in s
    assert not ({"Brain & Spinal Cord", "Hodgkin Lymphoma", "Non-Hodgkin Lymphomas", "Bone & Soft Tissues"} & set(s))


def test_keys_round_trip():
    k = N.key_for("Colon and Rectum")
    assert k == "tnm-colon-and-rectum@9" and N.is_tnm(k) and N.site_for(k) == "Colon and Rectum"
    assert N.site_for("fleischner@2017") is None and N.site_for("tnm-nowhere@9") is None


def test_entry_has_axes_with_x_first_and_is_verified():
    e = N.entry("Lung")
    b = e.content.branches[0]
    assert e.status == "verified" and e.version == "9" and b.state == "checked"
    opts = {i.id: i.options for i in b.inputs}
    assert opts["T"][0] == "TX" and "T1mi" in opts["T"] and opts["N"][0] == "NX" and opts["M"][0] == "MX"
    assert "histology" not in opts
    assert "T2b:" in b.rule and "Minimally invasive adenocarcinoma" in b.rule


def test_variant_site_asks_histology():
    opts = {i.id: i.options for i in N.entry("Oesophagus").content.branches[0].inputs}
    assert opts["histology"] == ["Squamous cell carcinoma", "Adenocarcinoma"]


def test_stage_lookup_against_the_rebuilt_tables():
    # Known UICC TNM 9 stages; the three v2.0 failures first.
    cases = [("Lung", "T2b", "N1", "M0", "Stage IIB"), ("Kidney", "T3a", "N1", "M0", "Stage III"),
             ("Colon and Rectum", "T4b", "N2b", "M0", "Stage IIIC"), ("Lung", "TX", "N0", "M0", "Occult carcinoma"),
             ("Lung", "T4", "N3", "M0", "Stage IIIC"), ("Lung", "TX", "NX", "M1c1", "Stage IVB"),
             ("Colon and Rectum", "T3", "N0", "M0", "Stage IIA"), ("Pancreas", "T2", "N0", "M0", "Stage IB"),
             ("Stomach", "T3", "N2", "M0", "Stage III")]
    for site, t, n, m, want in cases:
        assert N.stage(site, "", t, n, m) == want, (site, t, n, m)
    assert N.stage("Lung", "", "TX", "N1", "M0") is None            # X matches only a listed X or "Any"
    assert N.stage("Oesophagus", "Adenocarcinoma", "T1", "N1", "M0") == "Stage IIA"
    assert N.stage("Oesophagus", "Squamous cell carcinoma", "T1", "N1", "M0") == "Stage I"
    assert N.stage("Oesophagus", "", "T1", "N1", "M0") is None      # histology needed
    assert N.stage("Prostate", "", "T2", "N0", "M0") is None        # no verified table


def test_proposal_built_in_code():
    p = N.proposal("Lung", {"T": "T2b", "N": "N1", "M": "M0"})
    assert p.classification == "cT2b N1 M0, Stage IIB (UICC TNM 9th)"
    assert p.line == "Staging (UICC TNM 9th): cT2b N1 M0, Stage IIB."
    assert N.proposal("Prostate", {"T": "T2", "N": "N0", "M": "M0"}).line == "Staging (UICC TNM 9th): cT2 N0 M0."
    assert N.proposal("Lung", {"T": "T2b", "N": "N1"}) is None       # every axis must be answered
    assert N.proposal("Oesophagus", {"T": "T1", "N": "N1", "M": "M0"}) is None   # and histology where tables vary
    assert N.proposal("Oesophagus", {"T": "T1", "N": "N1", "M": "M0", "histology": "Adenocarcinoma"}).line.endswith("Stage IIA.")


def test_material_for_ask():
    assert "AUTHORITATIVE TNM REFERENCE" in N.material("Lung")
