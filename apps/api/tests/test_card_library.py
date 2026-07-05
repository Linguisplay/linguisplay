"""📚 角色卡库: characters that live outside any story, imported into 剧本 as copies.

Covers: CRUD + ownership isolation, the import-copy contract (source_card_id and
examples must survive story save + publish — the pydantic silently-drops-unknown-keys
gotcha), avatar upload validation, and enrich (monkeypatched, never a live call).
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


def _fresh_client():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    return TestClient(app)


def _signup(c, email):
    c.post("/api/v1/auth/signup",
           json={"email": email, "password": "password1",
                 "dob": "1990-01-01", "accepted_tos": True})


CARD = {"name": "沈砚", "role": "旧书店老板", "persona_text": "话少，记性好得吓人",
        "eq_style": "关心都藏在做的事里", "agenda": "找一本三十年前失窃的书",
        "examples": ["书比人诚实。", "……你上次说到一半的那件事，后来呢。"],
        "background": "在南方小城开了十五年店", "knowledge": "", "items": [],
        "bio_layers": [{"closeness_min": 20, "text": "店是替一个人守的"}],
        "visibility": "private"}


def test_card_crud_and_isolation():
    with _fresh_client() as c:
        _signup(c, "a@x.com")
        # a card needs a name
        assert c.post("/api/v1/cards", json={**CARD, "name": " "}).status_code == 400
        card = c.post("/api/v1/cards", json=CARD).json()
        cid = card["id"]
        assert card["name"] == "沈砚" and card["examples"][0] == "书比人诚实。"
        assert card["bio_layers"][0]["closeness_min"] == 20
        # list + get + patch
        assert len(c.get("/api/v1/cards").json()) == 1
        upd = c.patch(f"/api/v1/cards/{cid}", json={**CARD, "role": "古籍修复师"}).json()
        assert upd["role"] == "古籍修复师"
        # another user sees nothing and touches nothing (same DB, separate cookie jar)
        with TestClient(app) as other:
            _signup(other, "b@x.com")
            assert other.get("/api/v1/cards").json() == []
            assert other.get(f"/api/v1/cards/{cid}").status_code == 404
            assert other.delete(f"/api/v1/cards/{cid}").status_code == 404
        # delete for real
        assert c.delete(f"/api/v1/cards/{cid}").status_code == 204
        assert c.get("/api/v1/cards").json() == []


def test_imported_character_survives_save_and_publish():
    with _fresh_client() as c:
        _signup(c, "a@x.com")
        card = c.post("/api/v1/cards", json=CARD).json()
        # the studio's import = a COPY into story.characters with provenance
        imported = {"id": "c_imp1", "name": card["name"], "role": card["role"],
                    "is_lead": True, "persona_text": card["persona_text"],
                    "eq_style": card["eq_style"], "agenda": card["agenda"],
                    "examples": card["examples"], "bio_layers": card["bio_layers"],
                    "source_card_id": card["id"]}
        story = c.post("/api/v1/stories",
                       json={"title": "书店", "visibility": "public",
                             "characters": [imported]}).json()
        sid = story["id"]
        got = c.get(f"/api/v1/stories/{sid}").json()["characters"][0]
        assert got["source_card_id"] == card["id"]          # provenance survived
        assert got["examples"] == card["examples"]          # voice lines survived
        c.post(f"/api/v1/stories/{sid}/publish")
        # editing the CARD afterwards must not touch the story (copy semantics)
        c.patch(f"/api/v1/cards/{card['id']}", json={**CARD, "persona_text": "全变了"})
        still = c.get(f"/api/v1/stories/{sid}").json()["characters"][0]
        assert still["persona_text"] == "话少，记性好得吓人"


def test_square_lists_public_only_and_strangers_can_read_them():
    with _fresh_client() as c:
        _signup(c, "a@x.com")
        pub = c.post("/api/v1/cards", json={**CARD, "visibility": "public"}).json()
        priv = c.post("/api/v1/cards", json={**CARD, "name": "私藏", }).json()
        with TestClient(app) as other:
            _signup(other, "b@x.com")
            sq = other.get("/api/v1/cards/square").json()
            assert [x["id"] for x in sq] == [pub["id"]]          # private stays home
            assert sq[0]["author"] and sq[0]["mine"] is False
            # a public card is readable (copy source), a private one is not
            assert other.get(f"/api/v1/cards/{pub['id']}").status_code == 200
            assert other.get(f"/api/v1/cards/{priv['id']}").status_code == 404
            # …but never editable by a stranger
            assert other.patch(f"/api/v1/cards/{pub['id']}", json=CARD).status_code == 404
            assert other.delete(f"/api/v1/cards/{pub['id']}").status_code == 404
        # the owner sees mine=True on their own square entry
        assert c.get("/api/v1/cards/square").json()[0]["mine"] is True


def test_avatar_upload_validates_and_enrich_is_stubbed(monkeypatch):
    with _fresh_client() as c:
        _signup(c, "a@x.com")
        cid = c.post("/api/v1/cards", json=CARD).json()["id"]
        # not an image → 415
        r = c.post(f"/api/v1/cards/{cid}/avatar",
                   files={"file": ("x.jpg", b"not an image", "image/jpeg")})
        assert r.status_code == 415
        # a real (tiny) png header passes and writes the id-keyed url
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
        r2 = c.post(f"/api/v1/cards/{cid}/avatar",
                    files={"file": ("x.png", png, "image/png")})
        assert r2.status_code == 200
        assert r2.json()["avatar_url"] == f"/scene/avatar/{cid}.jpg"
        # enrich never calls a live model in tests
        monkeypatch.setattr("app.engine.qwen.generate_knowledge",
                            lambda name, profile, world="": "KNOW_BLOCK")
        card = c.post(f"/api/v1/cards/{cid}/enrich").json()
        assert card["knowledge"] == "KNOW_BLOCK"
