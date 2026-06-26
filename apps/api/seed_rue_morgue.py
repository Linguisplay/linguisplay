"""Seed 《莫格街凶案》— an interactive adaptation of Edgar Allan Poe's "The Murders in
the Rue Morgue" (public domain). You play the analyst Dupin; pull the truth out of the
defensive prefect, the rattled witness, and finally the sailor. Gated, hard-progression.

Run:  python seed_rue_morgue.py   (idempotent; publishes public v1)
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Fragment, Persona, Run, Secret, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_secret, _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

TITLE = "莫格街凶案"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    {"id": "prefect", "name": "警长G", "role": "巴黎警务局长", "is_lead": True,
     "persona_text": "自负、循规蹈矩的警务局长。已经逮捕了银行职员勒邦结案，对你这种'空想推理'半是轻蔑半是好奇。"
     "你越问得刁钻，他越忍不住把现场细节抖出来。",
     "background": "掌握全部官方勘验记录，却看不懂它们意味着什么。"},
    {"id": "dupin", "name": "迪潘", "role": "分析者", "is_lead": False,
     "persona_text": "离群索居的分析天才，靠纯粹的推理还原真相。冷静、克制、句句切中要害。",
     "background": "（建议你扮演的角色：本案的破局者。）"},
    {"id": "witness", "name": "缪塞", "role": "邻居·面包师", "is_lead": False,
     "persona_text": "住在莫格街的面包师，案发那晚和众人一起冲上楼。惊魂未定，反复说他听见了两个声音——"
     "一个是法语，另一个……他说不上来是什么话。",
     "background": "听见过那个'谁也听不懂'的声音。"},
    {"id": "sailor", "name": "那个水手", "role": "马耳他船员", "is_lead": False,
     # only surfaces once Dupin baits him out (act 3)
     "appears_from_act": 3,
     "persona_text": "皮肤黝黑的马耳他船员，神色惊惶。一旦被点破，他会颤抖着说出那个没人敢信的真相。",
     "background": "他从婆罗洲带回的'东西'，闯了大祸。"},
]

ACTS = [
    {"id": "a1", "index": 1, "title": "锁闭的房间", "goal": "勘验现场——弄清凶手如何进出这间从里面反锁的屋子",
     "advance": {"required_fragment_ids": ["fr_window"]},
     "events": [
        {"id": "e_scene", "what_happens": "莱斯巴拉叶夫人母女惨死在四楼。房门从内反锁，窗户紧闭，钱却没丢。",
         "who_character_ids": ["prefect"]},
     ]},
    {"id": "a2", "index": 2, "title": "听不懂的声音", "goal": "查清众人听到的那个怪声到底是什么",
     "advance": {"required_fragment_ids": ["fr_voice"]},
     "events": [
        {"id": "e_voices", "what_happens": "所有证人都说听见两个声音：一个粗哑的法语，另一个尖利刺耳——"
         "可每个人猜的语言都不一样。", "who_character_ids": ["witness"]},
     ]},
    {"id": "a3", "index": 3, "title": "登报引凶", "goal": "查明真凶，把那个躲起来的人引出来",
     "events": [
        {"id": "e_ad", "what_happens": "你在报上登了一则'寻获走失猩猩'的启事——只为引一个人现身。",
         "who_character_ids": ["dupin"]},
     ]},
]

# (title, character_id, sensitivity, known_by, [(fragment_id, layer, content, retrieval_key, unlock)])
SECRETS = [
    ("反锁的窗户", "prefect", "medium", ["prefect"], [
        ("fr_window", 1, "门确实从里面反锁了，可窗户不是。靠床那扇窗的钉子断成了两截，断口锈死、看不出来——"
         "窗子能被推上、自动落回'看似锁着'的位置。凶手就是从这里进出的，根本不必开门。",
         "窗 窗户 钉子 怎么进 怎么出 密室 反锁 门",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
    ]),
    ("谁也听不懂的声音", "witness", "medium", ["witness"], [
        ("fr_voice", 1, "粗哑的那个是法语，在骂人。可另一个尖声……法国人说是西班牙语，荷兰人说是法语，"
         "英国人说是德语——没有一个人，能说出哪怕一个词。仿佛那根本不是人在说话。",
         "声音 尖叫 语言 听不懂 两个声音 谁的声音 说什么",
         {"affinity_min": 0, "act_min": 2, "asks_min": 1}),
    ]),
    ("非人的痕迹", "prefect", "medium", ["prefect", "witness"], [
        ("fr_hair", 1, "女儿被硬塞进烟囱，要倒着塞进去得有惊人的力气；母亲几乎被一刀断颈。死者手里还攥着几根"
         "粗硬的茶褐色毛发——那不是人的头发。窗台外沿有一道宽得不寻常的抓痕。",
         "毛发 头发 力气 力量 烟囱 抓痕 伤口 脖子 不是人",
         {"affinity_min": 6, "act_min": 2, "asks_min": 1}),
    ]),
    ("真凶", "sailor", "heavy", ["sailor"], [
        ("fr_ape", 1, "水手脸色惨白：那是一头从婆罗洲带回的猩猩。那晚它挣脱了，攥着他的剃刀，学着他刮脸的样子"
         "翻窗闯了进去——它没有恶意，可它有一身蛮力，和一把刀。",
         "猩猩 猴子 动物 婆罗洲 剃刀 真凶 是什么 凶手是谁",
         {"affinity_min": 10, "act_min": 3, "asks_min": 2}),
        ("fr_sailor", 2, "他追上了楼，趴在窗外，眼睁睁看着惨剧发生却吓得动弹不得。事后他逃了，任由无辜的勒邦"
         "被关进牢里——直到这则启事把他逼了出来。他愿意作证：勒邦是清白的。",
         "水手 证词 自白 招供 勒邦 清白 你看见了什么 为什么不报案",
         {"affinity_min": 14, "act_min": 3, "asks_min": 2}),
    ]),
]

ENDINGS = [
    {"id": "end_true", "kind": "true", "title": "真相大白",
     "text": "启事钓出了那个水手。当他颤抖着说出'猩猩'二字，所有不可能都豁然贯通——反锁的房间、听不懂的"
             "尖声、非人的蛮力。无辜的勒邦当夜获释。理性，照亮了这桩看似无解的血案。",
     "condition": {"affinity_min": 14, "act_min": 0, "required_fragment_ids": ["fr_ape", "fr_sailor"]}},
    {"id": "end_normal", "kind": "normal", "title": "悬案",
     "text": "线索散落一地，却始终没能拼成一幅完整的图。警方维持原判，莫格街的惨案成了卷宗里又一桩'无法解释'。",
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
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True))
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
            one_liner="母女惨死在反锁的四楼，凶手却像凭空消失。你是迪潘——用纯粹的推理，还原真相。",
            synopsis="巴黎莫格街，一桩不可能的命案：房间从内反锁，凶手无影无踪，证人听见一个谁也听不懂的"
            "声音。警方草草抓人结案，唯有你看出这桩血案背后藏着一个常理之外的真相。",
            world_long="十九世纪的巴黎。莱斯巴拉叶夫人母女惨死在莫格街一栋公寓的四楼，门窗紧闭、钱财未失。"
            "全城哗然，警方束手，只逮了个替罪的银行职员。",
            relations_overview="你（迪潘）与自负的警长各执一词；唯一的活口，是一个躲起来的水手。",
            trope_tags=["推理", "悬疑", "密室", "古典"],
            characters=CHARACTERS, acts=ACTS, endings=ENDINGS, visibility="public",
        )
        db.add(story)
        db.flush()

        for title, char_id, sens, known_by, frags in SECRETS:
            sec = Secret(story_id=story.id, character_id=char_id, title=title, sensitivity=sens)
            sec.fragments = [
                Fragment(id=fid, layer=l, content=c, retrieval_key=r,
                         known_by_character_ids=known_by, unlock=u)
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
