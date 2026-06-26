"""Seed 《末班车上的陌生人》— a slow-burn drama with layered gated secrets.

Run:  python seed_lasttrain.py   (idempotent; publishes public v1)
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Fragment, Persona, Run, Secret, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_secret, _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

TITLE = "末班车上的陌生人"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    {
        "id": "jiang",
        "name": "江野",
        "role": "乘客",
        "is_lead": True,
        "persona_text": "三十出头的男人，每晚都坐这趟末班车。寡言、疏离，习惯靠窗坐，"
        "戴着耳机却常常没在听。对人客气而有距离，可你总觉得他像在等什么人。"
        "起初冷淡，熟了之后会露出一点温度。",
        "background": "总是坐到终点站，又坐回来。",
    },
    {"id": "zhang", "name": "老张", "role": "末班车司机", "is_lead": False,
     "persona_text": "开了二十年末班车的老司机，记得每一张老面孔。"},
]

ACTS = [
    {"id": "a1", "index": 1, "title": "相遇", "goal": "找个话头，和靠窗的江野搭上话",
     # HARD gate: can't leave act 1 until you find out he rides the loop, never getting off
     "advance": {"required_fragment_ids": ["fr_terminus"]},
     "events": [
        {"id": "e_meet", "what_happens": "末班车空荡荡，你和江野是车厢里仅有的两个人，灯光昏黄。", "who_character_ids": ["jiang"]},
    ]},
    {"id": "a2", "index": 2, "title": "熟悉", "goal": "弄清楚他为什么夜夜都坐这趟车、到站却不下车",
     # HARD gate: can't leave act 2 until you learn why he can't bear to go home
     "advance": {"required_fragment_ids": ["fr_home"]},
     "events": [
        {"id": "e_again", "what_happens": "一连几个深夜，你们都在同一节车厢遇见。他开始会对你点头。", "who_character_ids": ["jiang"]},
        {"id": "e_terminus", "what_happens": "你发现到了终点站，江野没有下车，而是安静地坐着等车折返。", "who_character_ids": ["jiang"]},
    ]},
    {"id": "a3", "index": 3, "title": "真相", "goal": "走进他心里，听他说出那个一直在等的人",
     "events": [
        {"id": "e_rain", "what_happens": "又是一个雨夜，车厢里只剩你们。江野望着窗外，很久没有说话。", "who_character_ids": ["jiang"]},
        {"id": "e_truth", "what_happens": "他终于开口，讲起那个曾经也坐在这趟车上的人。", "who_character_ids": ["jiang"]},
    ]},
]

# (title, character_id, sensitivity, known_by, [(fragment_id, layer, content, retrieval_key, unlock)])
# fragment_id is explicit + stable so acts' advance gates can reference it.
SECRETS = [
    ("终点站的秘密", "jiang", "light", ["jiang", "zhang"], [
        ("fr_terminus", 1, "其实江野并不是要去哪儿。他每晚都坐到终点站，然后又坐回来——这趟末班车的来回，才是他真正的目的地。",
         "末班车 终点站 不下车 回家 坐到 折返 去哪",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
    ]),
    ("不敢回的家", "jiang", "medium", ["jiang"], [
        ("fr_home", 1, "他说，他睡不着。回到那个一个人的房子，灯一关，安静得让人发慌。坐在晃动的车厢里，反而能眯一会儿——好像还有人陪着。",
         "睡不着 失眠 家里 一个人 空 房子 为什么 晚上",
         {"affinity_min": 12, "act_min": 2, "asks_min": 2}),
    ]),
    ("那个一起坐车的人", "jiang", "heavy", ["jiang"], [
        ("fr_person1", 1, "他承认，以前他不是一个人坐这趟车的。有个人，总坐在他旁边靠窗的位置，陪他从终点坐到起点，一路说着白天的事。",
         "那个人 以前 旁边 靠窗 陪 一起 谁",
         {"affinity_min": 15, "act_min": 2, "asks_min": 2}),
        ("fr_person2", 2, "一年前的这几天，那个人走了，再没回来。江野没法接受空着的那个座位，于是每晚都来坐这趟车——只要还坐着，就好像对方只是去了趟洗手间，马上就会回来坐下。他不是在等车，他是在等一个永远不会再上车的人。",
         "一年前 走了 去世 离开 忌日 失去 等 真相 放不下",
         {"affinity_min": 20, "act_min": 3, "asks_min": 3}),
    ]),
]


ENDINGS = [
    {"id": "end_true", "kind": "true", "title": "陪你坐到天亮",
     "text": "雨停了。江野第一次没有戴上耳机，他说：'谢谢你，这一程有人陪。'到了终点，他站起身，"
             "这一次，他朝车门走去——他说，他想试试，回那个空房子，把灯打开。",
     "condition": {"affinity_min": 18, "act_min": 0}},
    {"id": "end_normal", "kind": "normal", "title": "末班车照常开",
     "text": "到站了，江野照例没有下车。你下车时回头看了一眼，他还坐在靠窗的位置，望着窗外的雨，"
             "像在等一个迟到很久的人。末班车第二天还会开，他大概也还会在。",
     "condition": {"affinity_min": 0, "act_min": 0}},
]


def get_or_create_demo_user(db) -> User:
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    u = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PW),
             dob=datetime(1990, 1, 1), accepted_tos=True, display_name="Demo 作者")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True,
                   tagline="加班到深夜的人", background="每晚赶最后一班地铁回家。"))
    db.commit()
    return u


def wipe_existing(db, owner_id: str) -> None:
    for s in db.query(Story).filter(Story.owner_id == owner_id, Story.title == TITLE).all():
        db.query(Run).filter(Run.story_id == s.id).delete()
        db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).delete()
        db.delete(s)
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        wipe_existing(db, user.id)

        story = Story(
            owner_id=user.id, title=TITLE,
            one_liner="每晚的末班车上，都坐着同一个寡言的男人。他到底要去哪儿？",
            synopsis="深夜的末班车，空荡的车厢，只有你和靠窗的江野。一晚又一晚的相遇里，"
            "你慢慢发现：他从不在终点下车。你越是靠近，越接近一个关于等待与失去的秘密。",
            world_long="某城市地铁末班车，深夜，雨季。车厢空旷，只有零星乘客。",
            relations_overview="你与江野因末班车反复相遇；司机老张知道他天天如此。",
            trope_tags=["言情", "治愈", "慢热", "都市"],
            characters=CHARACTERS, acts=ACTS, endings=ENDINGS, visibility="public",
        )
        db.add(story)
        db.flush()

        for title, char_id, sens, known_by, frags in SECRETS:
            sec = Secret(story_id=story.id, character_id=char_id, title=title, sensitivity=sens)
            sec.fragments = [
                Fragment(id=fid, layer=l, content=c, retrieval_key=r, known_by_character_ids=known_by, unlock=u)
                for (fid, l, c, r, u) in frags
            ]
            db.add(sec)
        db.flush()
        db.refresh(story)

        content = {"story": _to_story(story).model_dump(),
                   "secrets": [_to_secret(s).model_dump() for s in story.secrets]}
        content["story"]["version"] = 1
        db.add(StorySnapshot(story_id=story.id, version=1, content=content))
        story.version = 1
        story.status = "published"
        db.commit()

        n_frag = sum(len(f) for *_, f in SECRETS)
        print(f"OK seeded 《{TITLE}》 story_id={story.id} secrets={len(SECRETS)} fragments={n_frag}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
