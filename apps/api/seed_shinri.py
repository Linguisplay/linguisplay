"""Seed 《心理测验》— an interactive adaptation of Edogawa Ranpo's "The Psychological
Test" (心理試験, public domain). You play the detective Akechi Kogoro: the word-association
test 'cleared' the real killer, so you must spring a subtler trap. Gated, hard-progression.

Run:  python seed_shinri.py   (idempotent; publishes public v1)
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Fragment, Persona, Run, Secret, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_secret, _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

TITLE = "心理测验"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    {"id": "kenji", "name": "笔录检事", "role": "检事", "is_lead": True,
     "persona_text": "一板一眼的检事，亲自主持了那场心理测验。他对结果困惑不已——测验竟把头号疑犯'洗清'了。"
     "你越问，他越愿意把案情和测验数据摊给你看。",
     "background": "掌握命案卷宗与那份测验记录。"},
    {"id": "akechi", "name": "明智小五郎", "role": "侦探", "is_lead": False,
     "persona_text": "头发蓬乱、看似散漫的年轻侦探，最擅长读人心。",
     "background": "（建议你扮演的角色：识破完美伪装的人。）"},
    {"id": "fukiya", "name": "蕗屋清一郎", "role": "苦学生", "is_lead": False,
     "persona_text": "聪明、镇定得可怕的苦学生。说话滴水不漏，对答从容。你几乎抓不到他任何破绽——"
     "他准备得太充分了。只有提到某个不该提的细节时，他才会有一瞬间的失态。",
     "background": "为筹学费而杀人，并自信能瞒过所有人。真相只在被精准戳中时才会裂开。"},
    {"id": "saito", "name": "斋藤勇", "role": "同学", "is_lead": False,
     "persona_text": "老实、胆小的学生，被当成头号嫌疑而惊慌失措，拼命辩白自己的清白。",
     "background": "因为欠债、又在案发前后去过现场，成了替罪的最佳人选。"},
]

ACTS = [
    {"id": "a1", "index": 1, "title": "老妇之死", "goal": "了解命案经过，弄清为什么斋藤成了头号嫌疑",
     "advance": {"required_fragment_ids": ["fr_motive"]},
     "events": [
        {"id": "e_murder", "what_happens": "放高利贷的老太婆被勒死在家中，钱被取走。胆小的斋藤因欠债、又在"
         "案发前去过，被锁定为头号嫌疑。", "who_character_ids": ["kenji"]},
     ]},
    {"id": "a2", "index": 2, "title": "心理测验", "goal": "搞清楚为什么心理测验反而'证明'了蕗屋清白",
     "advance": {"required_fragment_ids": ["fr_test"]},
     "events": [
        {"id": "e_test", "what_happens": "检事用词语联想做了心理测验。斋屋面对危险词语对答如流、反应时间也无可"
         "挑剔——测验结果，竟像是替蕗屋背书。", "who_character_ids": ["kenji"]},
     ]},
    {"id": "a3", "index": 3, "title": "金屏风", "goal": "用一个细节，让滴水不漏的蕗屋自己露出马脚",
     "events": [
        {"id": "e_screen", "what_happens": "你不动声色地，把话题引向了死者房间里那道金屏风。",
         "who_character_ids": ["akechi"]},
     ]},
]

# (title, character_id, sensitivity, known_by, [(fragment_id, layer, content, retrieval_key, unlock)])
SECRETS = [
    ("动机：学费", "kenji", "light", ["kenji"], [
        ("fr_motive", 1, "死者是放贷的老太婆，附近不少苦学生都欠她钱。这就把嫌疑从斋藤一个人，扩到了所有"
         "为钱所困、又有胆识的人身上——比如，那个一向缺钱念书的蕗屋。",
         "动机 为什么 钱 学费 欠债 谁有嫌疑 苦学生 高利贷",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
    ]),
    ("斋藤的嫌疑", "saito", "light", ["saito"], [
        ("fr_suspect", 1, "斋藤结结巴巴地辩白：他确实欠钱、案发前也去过，可他真没下手。他越解释越慌，"
         "可慌张本身，并不等于有罪。",
         "斋藤 嫌疑 冤枉 你做的吗 辩解 害怕 去过现场",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
    ]),
    ("测不出的破绽", "kenji", "medium", ["kenji"], [
        ("fr_test", 1, "检事百思不解：蕗屋对'刀''血''钱'这些危险词的反应，平稳得异乎寻常，反倒是无关词偶有迟疑。"
         "——一个清白的人不会如此从容。他不是没有破绽，他是把破绽'练'没了。完美本身，就是最大的破绽。",
         "测验 联想 反应 太完美 破绽 准备 异常 为什么测不出",
         {"affinity_min": 6, "act_min": 2, "asks_min": 2}),
    ]),
    ("金屏风的疑点", "fukiya", "heavy", ["fukiya"], [
        ("fr_screen", 1, "你像是随口一提那道金屏风。蕗屋几乎没有迟疑地接了话——他说出了屏风上图案的细节，"
         "一个只有进过那间屋子、亲眼见过的人才会知道的细节。话一出口，他的脸色就变了。",
         "金屏风 屏风 房间 细节 你怎么知道 见过 图案",
         {"affinity_min": 10, "act_min": 3, "asks_min": 2}),
        ("fr_confess", 2, "伪装碎了。蕗屋苦笑着承认了一切：他为筹学费而动手，又把一切都预演过无数遍——唯独算漏了"
         "你会用一道屏风，把他亲手筑起的'完美'变成铁证。斋藤，是清白的。",
         "自白 认罪 招了 承认 真相 是你做的 斋藤清白",
         {"affinity_min": 16, "act_min": 3, "asks_min": 3}),
    ]),
]

ENDINGS = [
    {"id": "end_true", "kind": "true", "title": "完美即破绽",
     "text": "你始终没有逼问，只递出一道金屏风。蕗屋脱口而出的那个细节，出卖了他自己——他准备得越完美，"
             "落网时就越彻底。他认罪了，斋藤当庭获释。读心者，胜过了一切测谎的仪器。",
     "condition": {"affinity_min": 16, "act_min": 0, "required_fragment_ids": ["fr_screen", "fr_confess"]}},
    {"id": "end_normal", "kind": "normal", "title": "证据不足",
     "text": "蕗屋自始至终滴水不漏，测验也'还了他清白'。没有铁证，案子悬而未决——而你知道，真正的凶手，"
             "正从容地走出了这扇门。",
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
            one_liner="心理测验把真凶'洗清'了。你是明智小五郎——用一道金屏风，让完美的伪装自己崩塌。",
            synopsis="放贷的老太婆被杀，胆小的斋藤成了替罪羊。真凶蕗屋把一切预演到完美，连心理测验都骗了过去。"
            "唯有你看穿：那份滴水不漏的从容，本身就是破绽。",
            world_long="大正年间的东京。放高利贷的老太婆被勒死家中，钱财被取走。一名苦学生因欠债被当成头号"
            "嫌疑，而真正动手的人，正打算用一场'完美'的表演全身而退。",
            relations_overview="你（明智）与主持测验的检事推敲案情；蕗屋镇定自若，斋藤惊慌辩白。",
            trope_tags=["推理", "悬疑", "心理", "本格"],
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
