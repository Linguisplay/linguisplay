"""🃏 万物铸卡: what a run birthed (emergent characters/places) and its 名场面 mint into
a permanent per-story collection when an ending fires; a character card can be carried
into an NG+ run as an old acquaintance."""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.engine import runtime  # noqa: E402
from app.main import app  # noqa: E402


def test_mint_cards_pure():
    content = {"story": {"id": "s", "characters": [
        {"id": "a", "name": "甲", "is_lead": True},
        {"id": "gen_1", "name": "老周", "role": "巡逻班长", "persona_text": "鬓角花白。",
         "generated": True},
    ], "locations": [
        {"id": "hall", "name": "门厅", "detail": "x", "exits": []},
        {"id": "loc_gen_1", "name": "地下酒窖", "detail": "潮气扑面", "generated": True},
    ], "acts": [{"index": 1, "title": "一"}]}, "secrets": []}
    st = runtime.default_state()
    st["rel_log"] = {"a": [{"act": 2, "kind": "rel_up", "text": "你们成了「朋友」。"},
                           {"act": 1, "kind": "meet", "text": "初次见面。"}]}
    cards = runtime.mint_cards(content, st)
    kinds = {c["kind"] for c in cards}
    assert kinds == {"character", "place", "moment"}
    ch = next(c for c in cards if c["kind"] == "character")
    assert ch["name"] == "老周" and ch["payload"]["role"] == "巡逻班长"
    assert all(c["kind"] != "moment" or "朋友" in c["text"] for c in cards
               if c["kind"] == "moment")           # meet entries don't mint


def test_cards_accumulate_and_carry_over_http():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "cards@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        story = c.post("/api/v1/stories", json={
            "title": "Cards", "visibility": "public",
            "characters": [{"id": "c1", "name": "阿元", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}],
            "endings": [{"id": "e1", "kind": "normal", "title": "落幕"}],
        }).json()
        sid = story["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        persona = c.post("/api/v1/personas", json={"name": "Ash", "pronouns": "they"}).json()

        # carrying is locked before any ending exists
        assert c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"],
                                            "carry_card_id": "char:x"}).status_code == 403

        # a run whose scene minted a relationship moment reaches the ending
        run = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"]}).json()
        c.post(f"/api/v1/runs/{run['id']}/play", json={"input": "谢谢你陪我聊这些，真的",
                                                       "channel": "say"})
        c.post(f"/api/v1/runs/{run['id']}/play", json={"input": "你好", "channel": "say"})
        m = c.get(f"/api/v1/stories/{sid}/meta").json()
        assert m["ng_plus"] is True
        # the collection may hold moment cards from rel_log (meet excluded); shape holds
        assert isinstance(m["cards"], list)
        # a nonexistent card is refused even with NG+ unlocked
        assert c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"],
                                            "carry_card_id": "char:nope"}).status_code == 400


def test_carry_injects_the_old_acquaintance():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    from app.db import SessionLocal
    from app.models import StoryMeta
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "carry@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        story = c.post("/api/v1/stories", json={
            "title": "Carry", "visibility": "public",
            "characters": [{"id": "c1", "name": "阿元", "is_lead": True}],
            "acts": [{"index": 1, "title": "一"}],
            "endings": [{"id": "e1", "kind": "normal", "title": "落幕"}],
        }).json()
        sid = story["id"]
        c.post(f"/api/v1/stories/{sid}/publish")
        persona = c.post("/api/v1/personas", json={"name": "Ash", "pronouns": "they"}).json()
        run = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"]}).json()
        c.post(f"/api/v1/runs/{run['id']}/play", json={"input": "你好", "channel": "say"})

        # plant a minted character card directly in the meta (the minting path is covered above)
        db = SessionLocal()
        meta = db.query(StoryMeta).first()
        meta.cards = [{"id": "char:gen_9", "kind": "character", "name": "老周",
                       "text": "鬓角花白", "payload": {"name": "老周", "role": "旧识班长",
                                                       "persona_text": "鬓角花白。"}}]
        db.commit(); db.close()

        run2 = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": persona["id"],
                                            "carry_card_id": "char:gen_9"}).json()
        names = [x["name"] for x in run2["cast"]]
        assert "老周" in names                       # the old acquaintance is in the cast
