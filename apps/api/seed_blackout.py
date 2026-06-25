"""Seed the demo story 《二十七层的停电》 with layered, gated secrets.

Run:  python seed_blackout.py
Idempotent: wipes any prior copy (same title + demo owner) and its runs/snapshots,
then recreates and publishes it as a public story any account can play.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import (  # noqa: E402
    Fragment,
    Persona,
    Run,
    Secret,
    Story,
    StorySnapshot,
    User,
)
from app.routers.stories import _to_secret, _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

TITLE = "二十七层的停电"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    {
        "id": "zhou",
        "name": "老周",
        "role": "保安",
        "is_lead": True,
        "persona_text": "值夜班的老保安，五十多岁，守了这栋楼快十年，叫得出每个人的名字。"
        "说话不紧不慢，总在安抚大家——可你越听，背后越凉。",
        "background": "灯灭后唯一不靠手机照明的人。手里有一串能打开所有安全门的钥匙。",
    },
    {"id": "su", "name": "苏婷", "role": "部门主管", "is_lead": False,
     "persona_text": "雷厉风行的财务主管，习惯用门禁刷卡记录核对加班人数。"},
    {"id": "chen", "name": "陈工", "role": "设备科工程师", "is_lead": False,
     "persona_text": "今晚来调试机房，是第一个去配电间、发现门被反锁的人。"},
    {"id": "yang", "name": "小杨", "role": "实习生", "is_lead": False,
     "persona_text": "入职三个月的实习生，第一个数出镜子里有六个人。"},
    {"id": "man", "name": "那个男人", "role": "？", "is_lead": False,
     "persona_text": "谁也叫不出他的名字。",
     # the sixth person — a presence that haunts the scene, never a normal participant
     "presence": "offstage"},
]

ACTS = [
    {"id": "a1", "index": 1, "title": "灯灭", "goal": "稳住众人，先弄清楚为什么停电、门为什么打不开",
     "events": [
        {"id": "e_blackout", "what_happens": "十一点零四分，整层楼总闸跳电，陷入黑暗。", "who_character_ids": []},
        {"id": "e_doors", "what_happens": "陈工发现配电间、楼梯间、电梯厅的安全门全被从外面反锁。", "who_character_ids": ["chen"]},
    ]},
    {"id": "a2", "index": 2, "title": "镜中六人", "goal": "查清小杨在镜子里到底看到了什么，套出老周的反常",
     "events": [
        {"id": "e_mirror", "what_happens": "小杨说灯灭那一刻，茶水间镜子里有六个人。", "who_character_ids": ["yang"]},
        {"id": "e_flashlight", "what_happens": "被追问时，老周的手电筒突然没电熄灭。", "who_character_ids": ["zhou"]},
    ]},
    {"id": "a3", "index": 3, "title": "刷卡记录", "goal": "逼近真相：第五个名字是谁，老周到底是什么",
     "events": [
        {"id": "e_record", "what_happens": "来电后，苏婷去看门禁刷卡记录，发现第五个名字谁都没听过。", "who_character_ids": ["su"]},
        {"id": "e_sixth", "what_happens": "镜子里第六个人的影子，正缓缓朝你们走来。", "who_character_ids": ["man"]},
    ]},
]

# (title, character_id, sensitivity, known_by, [fragments])
# fragment = (layer, content, retrieval_key, unlock)
SECRETS = [
    ("小杨的恐惧", "yang", "light", ["zhou", "yang"], [
        (1, "小杨说，她其实从踏进这层楼起就觉得不对劲——镜子里的人，总比工位上的人多出一个。她不敢声张，怕被当成神经病。",
         "小杨 害怕 哭 镜子 实习生 数",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
    ]),
    ("安全门的反常", "zhou", "medium", ["zhou"], [
        (1, "安全门从外面反锁，是严重的消防违规，本不该存在。而监控显示：今天下午，没有任何人碰过那几道门。锁门的人，不在录像里。",
         "门 安全门 锁 钥匙 出不去 消防",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
    ]),
    ("老周不被记录", "zhou", "medium", ["zhou"], [
        (1, "你注意到了：被逼问时，老周的手电筒'恰好'就没了电。十年来他从不带手机，也从不出现在任何一张照片、任何一段监控里。",
         "手电筒 电池 老周 巡楼 监控 照片 记录",
         {"affinity_min": 12, "act_min": 2, "asks_min": 2}),
    ]),
    ("第六个人", "zhou", "heavy", ["zhou"], [
        (1, "小杨没有数错。灯灭那一瞬，镜子里确实是六个人——多出来的那一个，一直站在老周身后的位置，安静地，和你们一起等着。",
         "镜子 第六个 六个人 影子 多一个",
         {"affinity_min": 15, "act_min": 2, "asks_min": 2}),
        (2, "刷卡记录里的第五个名字，没人听过——那是几十年前在这栋楼坠亡的人。老周不刷卡，不是因为有保安通道；"
         "是因为他和那个名字，本就是同一个'人'。从灯灭的那一刻起，这层楼里活着的，只剩你们四个。",
         "刷卡 记录 名字 第五个 真相 你是谁 老周",
         {"affinity_min": 20, "act_min": 3, "asks_min": 3}),
    ]),
]


# Authored endings. Conditions are checked at the final act; best match wins
# (真＞普通＞坏). Death/坏 also fire dynamically when the player does something fatal.
ENDINGS = [
    {"id": "end_true", "kind": "true", "title": "天亮之后",
     "text": "六点整，市电恢复，安全门'咔'地弹开。走廊里只剩你们四个——和镜子里，那个终于转过身、"
             "对你轻轻点头的影子。你知道了他是谁，也知道了：今晚能走出去，是因为他放你们走。",
     "condition": {"affinity_min": 18, "act_min": 0}},
    {"id": "end_normal", "kind": "normal", "title": "谁也没再提起",
     "text": "灯亮了，门开了，没有人愿意回头看那面镜子。第二天大家照常上班，仿佛什么都没发生过——"
             "只是再没人敢在这层楼加班到十一点以后。",
     "condition": {"affinity_min": 0, "act_min": 0}},
]


def get_or_create_demo_user(db) -> User:
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    u = User(
        email=DEMO_EMAIL,
        password_hash=hash_password(DEMO_PW),
        dob=datetime(1990, 1, 1),
        accepted_tos=True,
        display_name="Demo 作者",
    )
    db.add(u)
    db.commit()
    db.refresh(u)
    # give the demo user a default mask too
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True,
                   tagline="深夜还在加班的人", background="财务部职员，今晚被留下核对季度报表。"))
    db.commit()
    return u


def wipe_existing(db, owner_id: str) -> None:
    for s in db.query(Story).filter(Story.owner_id == owner_id, Story.title == TITLE).all():
        db.query(Run).filter(Run.story_id == s.id).delete()
        db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).delete()
        db.delete(s)  # cascades secrets + fragments
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        wipe_existing(db, user.id)

        story = Story(
            owner_id=user.id,
            title=TITLE,
            one_liner="十一点零四分，二十七层的灯灭了。门从外面锁死，镜子里却有六个人。",
            synopsis="一场深夜加班的停电。五个被困的人，一个数出来的多余身影，和一个叫不出名字的第六人。"
            "你越是追问值夜班的老周，越接近一个不该知道的真相。",
            world_long="某写字楼二十七层，深夜，市政停电。安全门被从外反锁，对外失联约两小时。",
            relations_overview="叙述者与四名同事被困；老周是唯一掌握钥匙、却不在任何记录里的人。",
            trope_tags=["悬疑", "恐怖", "密室", "都市怪谈"],
            characters=CHARACTERS,
            acts=ACTS,
            endings=ENDINGS,
            visibility="public",
        )
        db.add(story)
        db.flush()

        for title, char_id, sens, known_by, frags in SECRETS:
            sec = Secret(story_id=story.id, character_id=char_id, title=title, sensitivity=sens)
            sec.fragments = [
                Fragment(layer=layer, content=content, retrieval_key=rkey,
                         known_by_character_ids=known_by, unlock=unlock)
                for (layer, content, rkey, unlock) in frags
            ]
            db.add(sec)
        db.flush()
        db.refresh(story)

        # publish: freeze v1 snapshot
        content = {
            "story": _to_story(story).model_dump(),
            "secrets": [_to_secret(s).model_dump() for s in story.secrets],
        }
        content["story"]["version"] = 1
        db.add(StorySnapshot(story_id=story.id, version=1, content=content))
        story.version = 1
        story.status = "published"
        db.commit()

        n_frag = sum(len(f) for *_, f in SECRETS)
        print(f"✅ Seeded 《{TITLE}》  story_id={story.id}")
        print(f"   owner={DEMO_EMAIL} (pw: {DEMO_PW})  secrets={len(SECRETS)} fragments={n_frag}")
        print("   published v1, public. Any logged-in account can start a run against it.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
