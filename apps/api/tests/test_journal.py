"""The dossier (线索档案+结局图鉴): unlocked truths readable in full, locked bodies never
leave the server, untouched secrets stay invisible (count only), ending gallery shows
achieved titles vs ？？？ slots."""

from app.engine import runtime

STORY = {
    "story": {
        "id": "s",
        "characters": [{"id": "c1", "name": "老周", "is_lead": True}],
        "acts": [{"index": 1, "title": "一"}],
        "endings": [
            {"id": "e1", "kind": "true", "title": "天亮之后", "condition": {}},
            {"id": "e2", "kind": "bad", "title": "谁也没再提起", "condition": {}},
        ],
    },
    "secrets": [
        {"id": "s1", "character_id": "c1", "title": "安全门的反常",
         "fragments": [
             {"id": "f1", "content": "BODY_OPEN", "retrieval_key": "k"},
             {"id": "f2", "content": "BODY_SHUT", "retrieval_key": "k2"},
         ]},
        {"id": "s2", "character_id": "c1", "title": "第六个人",
         "fragments": [{"id": "f3", "content": "BODY_VIRGIN", "retrieval_key": "k3"}]},
    ],
}


def test_journal_shape_and_no_leaks():
    st = {**runtime.default_state(),
          "unlocked_fragment_ids": ["f1"], "achieved_endings": ["e1"],
          "choices": {"act2": "a"}}
    jd = runtime.journal(STORY, st)
    blob = str(jd)
    # unlocked truth readable in full; locked layer only as a count; untouched secret invisible
    sec = jd["secrets"][0]
    assert len(jd["secrets"]) == 1
    assert (sec["title"], sec["character"], sec["unlocked"], sec["locked_count"]) == \
        ("安全门的反常", "老周", ["BODY_OPEN"], 1)
    # 🃏 confrontation affordances ride along: fragment ids of KNOWN text only + owner
    assert sec["frags"] == [{"id": "f1", "text": "BODY_OPEN"}] and sec["character_id"] == "c1"
    assert "BODY_SHUT" not in blob and "BODY_VIRGIN" not in blob
    assert "第六个人" not in blob                 # untouched secret's TITLE hidden too
    assert jd["secrets_untouched"] == 1
    # ending gallery: achieved carries its title, the other is a ？？？ slot (title None)
    assert {"kind": "true", "achieved": True, "title": "天亮之后"} in jd["endings"]
    assert {"kind": "bad", "achieved": False, "title": None} in jd["endings"]
    assert jd["choices"] == {"act2": "a"}


def test_journal_fresh_run_is_empty_but_counts():
    jd = runtime.journal(STORY, runtime.default_state())
    assert jd["secrets"] == [] and jd["secrets_untouched"] == 2
    assert all(not e["achieved"] for e in jd["endings"])
