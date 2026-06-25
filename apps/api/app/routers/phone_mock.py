"""MOCK implementation of the `phone` domain (小手机) — route skeleton + hardcoded
fake data only, so the frontend can integrate against it ahead of real logic.

IMPORTANT: this is a stand-in. It touches NO database and contains NO business logic.
Every endpoint returns static, schema-shaped sample data (the same for any run_id).
Schemas mirror packages/contract/openapi.yaml's phone domain and are defined locally
here so this file is self-contained (it does not modify app/schemas.py). Replace with
real, engine-driven implementations later.

Mounted in main.py with:  app.include_router(phone_mock.router, prefix=API)
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from ..deps import current_user

# cookieAuth on every route (matches the contract; the frontend already sends the cookie)
router = APIRouter(
    prefix="/runs/{run_id}/phone",
    tags=["phone"],
    dependencies=[Depends(current_user)],
)

# Fixed timestamps so the mock is stable/reproducible (no Date.now()).
_T1 = "2026-06-23T22:14:00Z"
_T2 = "2026-06-23T22:31:00Z"
_T3 = "2026-06-23T23:02:00Z"
_DAY = "2026-06-23"


# ── schemas (local mirror of the contract's phone domain) ──────────────────
class Message(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    # `from` is a Python keyword → store as from_, serialize as "from" (contract key)
    from_: Literal["player", "npc"] = Field(alias="from")
    text: str
    at: str


class MessageThread(BaseModel):
    id: str
    contact_name: str
    messages: list[Message]


class CallEntry(BaseModel):
    id: str
    direction: Literal["in", "out", "missed"]
    contact_name: str
    duration_sec: int
    note: str
    at: str


class MailItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    from_: str = Field(alias="from")
    subject: str
    preview: str
    body: str
    unread: bool
    at: str


class CalendarEvent(BaseModel):
    id: str
    date: str
    title: str
    note: str


class Note(BaseModel):
    id: str
    title: str
    body: str
    updated_at: str


class PayEntry(BaseModel):
    id: str
    from_name: str
    to_name: str
    memo: str
    emoji: str
    amount_hidden: bool = True
    at: str


class BrowserEntry(BaseModel):
    id: str
    day: str
    title: str
    url: str
    snapshot_card: str


class Contact(BaseModel):
    id: str
    name: str
    objective_chips: list[str]
    locked_count: int
    subjective_note: str


class MessageSendIn(BaseModel):
    thread_id: str
    text: str


# ── endpoints (all return static mock data; run_id accepted but ignored) ───
@router.get("/messages", response_model=list[MessageThread])
def get_messages(run_id: str):
    return [
        MessageThread(
            id="thr_1", contact_name="林姐",
            messages=[
                Message(id="m1", **{"from": "npc"}, text="到了吗？我在老地方等你。", at=_T1),
                Message(id="m2", **{"from": "player"}, text="马上，路上有点堵。", at=_T2),
                Message(id="m3", **{"from": "npc"}, text="别急，慢点开。", at=_T3),
            ],
        ),
        MessageThread(
            id="thr_2", contact_name="未知号码",
            messages=[
                Message(id="m4", **{"from": "npc"}, text="你知道得太多了。", at=_T2),
            ],
        ),
    ]


@router.post("/messages", status_code=202)
def send_message(run_id: str, body: MessageSendIn):
    # MOCK: accept and drop. A real reply would come back through the engine.
    return {"status": "accepted", "thread_id": body.thread_id}


@router.get("/calls", response_model=list[CallEntry])
def get_calls(run_id: str):
    return [
        CallEntry(id="c1", direction="missed", contact_name="林姐", duration_sec=0, note="未接", at=_T1),
        CallEntry(id="c2", direction="in", contact_name="林姐", duration_sec=92, note="", at=_T2),
        CallEntry(id="c3", direction="out", contact_name="未知号码", duration_sec=14, note="对方很快挂断", at=_T3),
    ]


@router.get("/mail", response_model=list[MailItem])
def get_mail(run_id: str):
    return [
        MailItem(id="mail1", **{"from": "hr@company.com"}, subject="加班排班通知",
                 preview="本周末值班安排如下…", body="本周末值班安排如下：你被排在周六夜班。", unread=True, at=_T1),
        MailItem(id="mail2", **{"from": "no-reply@bank.com"}, subject="账单提醒",
                 preview="您有一笔待还款…", body="您有一笔待还款，请于月底前处理。", unread=False, at=_T2),
    ]


@router.get("/calendar", response_model=list[CalendarEvent])
def get_calendar(run_id: str):
    return [
        CalendarEvent(id="ev1", date=_DAY, title="夜班 23:00", note="到岗后先去配电间检查"),
        CalendarEvent(id="ev2", date="2026-06-24", title="与林姐午饭", note="她说有事要谈"),
    ]


@router.get("/notes", response_model=list[Note])
def get_notes(run_id: str):
    # "Unlocked cognition only" — in real impl this mirrors the gate. Mock: a couple notes.
    return [
        Note(id="n1", title="今晚的疑点", body="电闸跳了，安全门却是从外面锁的。", updated_at=_T2),
        Note(id="n2", title="关于林姐", body="她似乎在回避某件和去年有关的事。", updated_at=_T3),
    ]


@router.get("/pay", response_model=list[PayEntry])
def get_pay(run_id: str):
    return [
        PayEntry(id="p1", from_name="我", to_name="林姐", memo="还上次的饭钱", emoji="🍜", at=_T1),
        PayEntry(id="p2", from_name="未知", to_name="我", memo="封口", emoji="🤐", at=_T2),
    ]


@router.get("/browser", response_model=list[BrowserEntry])
def get_browser(run_id: str):
    return [
        BrowserEntry(id="b1", day=_DAY, title="本市写字楼停电事故 历史报道", url="https://example.com/news/blackout", snapshot_card="多年前同一栋楼曾发生坠亡事故"),
        BrowserEntry(id="b2", day=_DAY, title="安全门反锁 消防隐患", url="https://example.com/wiki/fire-door", snapshot_card="安全门严禁从外侧上锁"),
        BrowserEntry(id="b3", day="2026-06-22", title="如何查询门禁刷卡记录", url="https://example.com/howto/access-log", snapshot_card="物业后台可导出刷卡名单"),
    ]


@router.get("/contacts", response_model=list[Contact])
def get_contacts(run_id: str):
    return [
        Contact(id="ct1", name="林姐", objective_chips=["财务主管", "常加班", "+2 锁定"],
                locked_count=2, subjective_note="对她总有种说不清的距离感。"),
        Contact(id="ct2", name="老周", objective_chips=["保安", "值夜班", "+3 锁定"],
                locked_count=3, subjective_note="他知道的好像比说出来的多。"),
    ]
