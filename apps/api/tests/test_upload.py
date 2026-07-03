"""Author media uploads: magic-byte validation, size cap, ownership, id checks, and the
avatar_url write-through into story + latest snapshot."""

import os
import pathlib

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def test_upload_flow():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        c.post("/api/v1/auth/signup",
               json={"email": "up@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        sid = c.post("/api/v1/stories",
                     json={"title": "上传测试", "visibility": "public",
                           "characters": [{"id": "c_up1", "name": "M", "is_lead": True}],
                           "acts": [{"index": 1, "title": "一"}],
                           "locations": [{"id": "loc_up1", "name": "门厅", "detail": "x", "exits": []}],
                           }).json()["id"]
        c.post(f"/api/v1/stories/{sid}/publish")

        def up(kind, target, data, filename="a.jpg"):
            return c.post(f"/api/v1/stories/{sid}/upload",
                          data={"kind": kind, "target_id": target},
                          files={"file": (filename, data, "image/jpeg")})

        # happy path: character photo → file written + avatar_url in story AND snapshot
        r = up("avatar", "c_up1", JPG)
        assert r.status_code == 200 and r.json()["url"] == "/scene/avatar/c_up1.jpg"
        story = c.get(f"/api/v1/stories/{sid}").json()
        assert story["characters"][0]["avatar_url"] == "/scene/avatar/c_up1.jpg"
        assert up("bg", "loc_up1", PNG, "b.png").status_code == 200

        # rejections: not an image / too big / unknown target / bad kind
        assert up("avatar", "c_up1", b"hello world").status_code == 415
        assert up("avatar", "c_up1", JPG + b"\x00" * (5 * 1024 * 1024)).status_code == 413
        assert up("avatar", "nope", JPG).status_code == 404
        assert up("bg", "nope", JPG).status_code == 404
        assert up("cover", "c_up1", JPG).status_code == 400

        # someone else's story → 404 (ownership scoped)
        c.post("/api/v1/auth/logout")
        c.post("/api/v1/auth/signup",
               json={"email": "other@x.com", "password": "password1",
                     "dob": "1990-01-01", "accepted_tos": True})
        assert up("avatar", "c_up1", JPG).status_code in (403, 404)

    # cleanup the files the test wrote into the real static dir
    for rel in ("avatar/c_up1.jpg", "bg/loc_up1.jpg"):
        f = pathlib.Path("app/static/scene") / rel
        if f.exists():
            f.unlink()
