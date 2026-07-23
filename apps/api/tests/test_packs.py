# -*- coding: utf-8 -*-
"""💎 平台币 P1 影子系统 (Yi 拍板 Roblox 三阶段): 月石钱包/创作者收费包/购买台账。
红线执法: grants 白名单消毒 (收费包永远写不了任意 state)、门票拦截、70% 分成、
下架不没收已购资格。"""
import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./test_e2e.db")
os.environ.setdefault("JWT_SECRET", "test")

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, engine  # noqa: E402
from app.main import app  # noqa: E402

SANDBOX = {
    "title": "收费沙盒", "visibility": "public",
    "characters": [{"id": "c1", "name": "甲", "is_lead": True}],
    "acts": [{"index": 1, "title": "一"}],
    "locations": [{"id": "l1", "name": "起点", "detail": "空"}],
    "sandbox": {"enabled": True, "start_money": 100},
}


def _two_users():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    c = TestClient(app)
    c.post("/api/v1/auth/signup", json={"email": "author@x.com", "password": "password1",
                                        "dob": "1990-01-01", "accepted_tos": True})
    sid = c.post("/api/v1/stories", json=SANDBOX).json()["id"]
    c.post(f"/api/v1/stories/{sid}/publish")
    author_cookies = dict(c.cookies)
    c.cookies.clear()
    c.post("/api/v1/auth/signup", json={"email": "player@x.com", "password": "password1",
                                        "dob": "1990-01-01", "accepted_tos": True})
    return c, sid, author_cookies


def _as_author(c, cookies):
    c.cookies.clear()
    for k, v in cookies.items():
        c.cookies.set(k, v)


def test_wallet_pack_buy_and_grants_flow():
    c, sid, author = _two_users()
    player = dict(c.cookies)
    # 玩家钱包: 首访赠 200, 再访不重复赠
    w = c.get("/api/v1/wallet").json()
    assert w == {"balance": 200, "currency": "月石"}
    assert c.get("/api/v1/wallet").json()["balance"] == 200
    # 作者建包 (grants 白名单消毒: 野键被丢弃)
    _as_author(c, author)
    p = c.post(f"/api/v1/stories/{sid}/packs", json={
        "name": "开拓者礼包", "desc": "多一条金手指", "price": 80,
        "grants": {"start_money_bonus": 50, "powers": ["夜视"],
                   "items": [{"name": "干粮", "detail": "三天的量"}],
                   "evil_key": "state_injection"}}).json()
    assert p["price"] == 80 and "evil_key" not in p["grants"]
    pid = p["id"]
    # 玩家购买: 余额扣减 + 重复购买 409
    _as_author(c, player)
    out = c.post(f"/api/v1/packs/{pid}/buy")
    assert out.status_code == 200 and out.json()["balance"] == 120
    assert c.post(f"/api/v1/packs/{pid}/buy").status_code == 409
    # 发货: 新档吃到 加钱/金手指/物件
    pid2 = c.post("/api/v1/personas", json={"name": "我"}).json()["id"]
    run = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pid2}).json()
    st = run["state"]
    assert any("夜视" in p for p in (st.get("powers") or []))
    assert any(i.get("name") == "干粮" for i in st.get("inventory") or [])
    assert st.get("money") == 150                       # 100 开局 + 50 礼包
    # 分成看板: 70%
    _as_author(c, author)
    e = c.get(f"/api/v1/stories/{sid}/earnings").json()
    assert e["sales"] == 1 and e["total_share"] == 56    # 80*70%


def test_access_gate_and_owner_privileges():
    c, sid, author = _two_users()
    player = dict(c.cookies)
    _as_author(c, author)
    g = c.post(f"/api/v1/stories/{sid}/packs", json={
        "name": "门票", "price": 60, "grants": {"access": True}}).json()
    # 作者不用买: 自动全拥有 + 开档不被门票拦
    assert c.post(f"/api/v1/packs/{g['id']}/buy").status_code == 400
    pa = c.post("/api/v1/personas", json={"name": "作者"}).json()["id"]
    assert c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pa}).status_code == 201
    # 玩家没票 → 403; 买票 → 放行
    _as_author(c, player)
    pp = c.post("/api/v1/personas", json={"name": "我"}).json()["id"]
    blocked = c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pp})
    assert blocked.status_code == 403 and "通行包" in blocked.json()["detail"]
    assert c.post(f"/api/v1/packs/{g['id']}/buy").status_code == 200
    assert c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pp}).status_code == 201
    # 下架不没收: 门票下架后已购玩家照进
    _as_author(c, author)
    c.delete(f"/api/v1/packs/{g['id']}")
    _as_author(c, player)
    assert c.post("/api/v1/runs", json={"story_id": sid, "persona_id": pp}).status_code == 201
    # 余额不足拒买
    _as_author(c, author)
    big = c.post(f"/api/v1/stories/{sid}/packs", json={"name": "天价", "price": 9999}).json()
    _as_author(c, player)
    r = c.post(f"/api/v1/packs/{big['id']}/buy")
    assert r.status_code == 400 and "月石不够" in r.json()["detail"]
