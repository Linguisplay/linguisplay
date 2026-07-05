# -*- coding: utf-8 -*-
"""Seed 《婚约之下》— 女性向 showcase：先婚后爱 · 白月光传闻的逆转 · 十年暗恋的铁证。

对标恋与深空式体验：约定/来电/情书/金色瞬间/误会压力表全系统吃满。
钩子母题取自女频短篇方法论（白月光触发链、年限承重、真相一次性砸），但把
「心死离场」的定局改成玩家手里的选择：留下、或体面地走，两头都算达成。

Run:  python seed_marriage.py   (idempotent; publishes public v1)
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Fragment, Persona, Run, Secret, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_secret, _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

TITLE = "婚约之下"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    {
        "id": "lin", "name": "林晚", "role": "插画师，这纸婚约的另一半",
        "is_lead": False, "playable": True,
        "persona_text": "二十六岁，自由插画师。为了替病中的爷爷了却心愿，签下了这纸各取所需的婚约。"
        "嘴上说只是合作，画笔却诚实——不高兴的时候，画里的天全是灰的。",
        "background": "带着一只旧速写本嫁进顾宅。条款上写：一年为期，互不打扰。",
        "items": [{"name": "旧速写本", "detail": "画满了街景和陌生人，最后几页夹着爷爷的照片"}],
    },
    {
        "id": "gu", "name": "顾之衍", "role": "顾氏继承人，你的「合约丈夫」",
        "is_lead": True,
        "persona_text": "三十岁，顾氏下一任掌舵人。西装永远一丝不苟，说话像在念条款，"
        "冷、稳、分寸感强到近乎疏离。但他记得你不吃香菜，记得你画画到几点，"
        "记得的方式是把这些都写进「安排」里，绝口不提。",
        "background": "外界都说这桩婚事是两家联姻的生意。没人知道提议的人是谁。",
        "eq_style": "嘴硬心软，关心全部藏在安排里；被戳破时会移开视线，用条款打岔",
        "agenda": "把十年前欠下的那把伞，一点点还回去——但绝不能让她觉得这婚约是施舍",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover", "enemy"],
        "examples": [
            "条款第七条，晚归要报备。……我是说，路上黑。",
            "不是为你。顺路。",
            "画完这张就睡。台灯我让陈妈换了，之前那盏伤眼。",
            "苏医生的事，与你无关。……抱歉，这句收回。",
        ],
        "bio_layers": [
            {"closeness_min": 12, "text": "他十六岁那年淋过一场很大的雨。他说那天之后，就没再怕过冷。"},
            {"closeness_min": 25, "text": "他大学四年打了三份工，没动过家里一分钱。没人知道他在跟谁较劲。"},
            {"closeness_min": 40, "text": "他书房抽屉里锁着一支旧铅笔，笔杆上有牙印。不是他的。"},
        ],
        "schedule": [
            {"from_act": 1, "location_id": "loc_dining", "slots": ["晨"]},
            {"from_act": 1, "location_id": "loc_study", "slots": ["夜"]},
        ],  # 午间无排班 = 在公司，不知去向——打电话、发消息的时段
        "ties": [{"char_id": "yao", "stance": 2, "label": "捧在手心的妹妹"},
                 {"char_id": "chen", "stance": 2, "label": "看着他长大的人"},
                 {"char_id": "su", "stance": 1, "label": "托付了要紧事的老同学"}],
    },
    {
        "id": "chen", "name": "陈妈", "role": "顾宅老管家",
        "persona_text": "在顾家三十年，看着之衍长大。话不多，眼里全是有数。"
        "对你格外照顾，炖汤总多留一盅，像是替谁在补偿什么。",
        "eq_style": "把疼人做进一日三餐里；说到旧事就叹气，欲言又止",
        "agenda": "少爷的心事她看了十年，不能说破——但盼着有人替他说破",
        "examples": ["汤在灶上温着，画完了记得喝。", "少爷那个人啊……唉，你多担待。"],
        "home_location_id": "loc_hall",
        "ties": [{"char_id": "gu", "stance": 2, "label": "半个娘"}],
    },
    {
        "id": "yao", "name": "顾之瑶", "role": "顾之衍的妹妹，大学生，术后休养中",
        "appears_from_act": 2,
        "persona_text": "十九岁，心脏手术后回家休养。人小鬼大，嘴甜，是这栋房子里唯一的活气。"
        "第一天就管你叫嫂子，叫得理直气壮。",
        "eq_style": "情绪全写在脸上；一撮合你俩就眼睛发亮",
        "agenda": "哥哥的心事她早看穿了——制造独处机会，撮合到底",
        "examples": ["嫂子！我哥是不是又跟你念条款了？别理他，他紧张才那样。", "你们聊你们聊，我先撤～"],
        "home_location_id": "loc_garden",
        "ties": [{"char_id": "gu", "stance": 2, "label": "最崇拜的哥哥"},
                 {"char_id": "su", "stance": 2, "label": "救过我的苏医生"}],
    },
    {
        "id": "su", "name": "苏晚晴", "role": "心外科医生，传闻里的「白月光」",
        "appears_from_act": 3,
        "persona_text": "三十岁，之衍的大学同学。利落、坦荡、看人极准。"
        "媒体拍到她和之衍多次同行，传闻甚嚣尘上——她从不辩解，只是笑。",
        "eq_style": "医生式的直接，先看病灶再开口；对误会她的人反而更温和",
        "agenda": "守住之衍托付的事，直到他自己肯开口；但看不下去时，会推一把",
        "examples": ["我和之衍的事，你该问他。不过——你想听真话的话，坐。", "误会我可以，别误会他熬的那些夜。"],
        "home_location_id": "loc_cafe",
        "ties": [{"char_id": "gu", "stance": 1, "label": "老同学，受人之托"},
                 {"char_id": "yao", "stance": 2, "label": "我的病人"}],
    },
]

LOCATIONS = [
    {"id": "loc_hall", "name": "顾宅客厅", "detail": "挑高的客厅，水晶灯常年只开一半。"
     "长沙发中间隔着一只从不挪动的靠枕，像一条无形的分界线。",
     "exits": ["餐厅", "玫瑰园", "书房", "老宅阁楼", "半山咖啡馆"]},
    {"id": "loc_dining", "name": "餐厅", "detail": "长桌可坐十二人，但每天只摆两副碗筷，"
     "隔着最远的对角。你的那侧永远有一碟不加香菜的小菜。",
     "exits": ["顾宅客厅"]},
    {"id": "loc_study", "name": "书房", "detail": "整面墙的书，办公桌一尘不染。"
     "只有书桌最下层的抽屉上着锁，钥匙孔擦得发亮——常开，却不许人碰。",
     "exits": ["顾宅客厅"],
     "props": [{"name": "上锁的抽屉", "detail": "锁着。钥匙孔周围的漆磨掉了一圈，主人常开它。"}]},
    {"id": "loc_garden", "name": "玫瑰园", "detail": "后院的玫瑰开得没什么章法，"
     "一看就不是园丁的手笔。廊下有把藤椅，扶手磨得发白。",
     "exits": ["顾宅客厅"]},
    {"id": "loc_attic", "name": "老宅阁楼", "detail": "积灰的旧家具蒙着白布，"
     "只有靠窗那只樟木箱干干净净——有人常来擦它。",
     "exits": ["顾宅客厅"],
     "unlock": {"required_fragment_ids": ["fr_chenma1"]},
     "props": [{"name": "樟木箱", "detail": "没有上锁，箱盖内侧贴着一张泛黄的画展门票。",
                "fragment_id": "fr_origin3"}]},
    {"id": "loc_cafe", "name": "半山咖啡馆", "detail": "医院对面的咖啡馆，苏晚晴的固定座位在窗边。"
     "桌上常年放着两份糖——她不吃糖。",
     "exits": ["顾宅客厅"],
     "unlock": {"act_min": 3}},
]

ACTS = [
    {"id": "a1", "index": 1, "title": "契约之始", "time": {"day": 1, "slot": "夜"},
     "goal": "新婚第一夜。摸清这位「合约丈夫」的脾气，弄明白这桩婚事到底是谁的主意",
     "advance": {"required_fragment_ids": ["fr_origin1"]},
     "events": [
         {"id": "e_wed", "what_happens": "婚礼刚散场。顾之衍解开领结，把一份《婚内协议》推到你面前：「十二条，都看清楚。」",
          "who_character_ids": ["gu"]},
         {"id": "e_soup", "what_happens": "陈妈端来一盅汤，轻声说：夫人慢用——这称呼让空气僵了一瞬。",
          "who_character_ids": ["chen"]},
     ]},
    {"id": "a2", "index": 2, "title": "同一屋檐", "time": {"day": 2, "slot": "晨"},
     "goal": "之瑶出院回家了。在这栋房子里找到你的位置——顺便弄清她住院的事为什么没人提",
     "advance": {"required_fragment_ids": ["fr_su1"]},
     "events": [
         {"id": "e_yao_home", "what_happens": "顾之瑶抱着抱枕溜进来，脆生生喊了句「嫂子」，被顾之衍瞪了一眼也不改口。",
          "who_character_ids": ["yao"]},
         {"id": "e_night_lamp", "what_happens": "深夜你起来倒水，发现你画室的台灯被换成了护眼的那种，没人承认。",
          "who_character_ids": []},
     ]},
    {"id": "a3", "index": 3, "title": "白月光传闻", "time": {"day": 3},
     "goal": "财经版拍到他和苏晚晴深夜同出医院。去半山咖啡馆，当面弄清楚她到底是谁",
     "advance": {"required_fragment_ids": ["fr_su2"]},
     "events": [
         {"id": "e_paparazzi", "what_happens": "推送弹出来：《顾少婚后密会白月光？》配图里他给苏晚晴撑着伞。",
          "who_character_ids": []},
         {"id": "e_su_invite", "what_happens": "苏晚晴托之瑶带话：半山咖啡馆，她请你喝一杯，「有些话医生只说一遍」。",
          "who_character_ids": ["yao"]},
     ]},
    {"id": "a4", "index": 4, "title": "阁楼旧箱", "time": {"day": 4},
     "goal": "陈妈说漏了嘴：少爷有只不许人碰的旧箱子，搬去了阁楼。去找到它",
     "advance": {"required_fragment_ids": ["fr_origin3"]},
     "events": [
         {"id": "e_chen_slip", "what_happens": "陈妈擦着相框叹气：那孩子守着那只箱子十年了，搬家都亲自抱着。",
          "who_character_ids": ["chen"]},
     ]},
    {"id": "a5", "index": 5, "title": "周年宴", "time": {"day": 5, "slot": "夜"},
     "goal": "顾家设宴，向所有人介绍「顾太太」。今晚过后，这纸婚约是什么，由你说了算",
     "choice": {
         "prompt": "掌声里，顾之衍向你伸出手，全场的目光都落过来。他的耳根是红的。",
         "options": [
             {"id": "stay", "label": "把手放进他掌心", "flag": "chose_stay",
              "character_id": "gu", "closeness_delta": 4, "romance_delta": 6},
             {"id": "leave", "label": "微笑欠身，转身离场——条款到此为止", "flag": "chose_leave"},
         ]},
     "events": [
         {"id": "e_banquet", "what_happens": "水晶灯全亮了，这是你嫁进来后第一次见客厅亮成这样。",
          "who_character_ids": ["gu"]},
     ]},
]

# (title, character_id, sensitivity, known_by, [(fragment_id, layer, content, retrieval_key, unlock, cover)])
SECRETS = [
    ("婚约的真正起因", "gu", "medium", ["gu"], [
        ("fr_origin1", 1,
         "这桩「联姻」不是两家长辈的主意。是顾之衍主动提的——条件全由他让，顾家把最要紧的一块业务"
         "让给了你爷爷的老厂做担保。生意上，这是笔谁看都亏的买卖。",
         "婚约 联姻 谁提的 主意 为什么娶 条款 生意 亏",
         {"affinity_min": 10, "act_min": 1, "asks_min": 2},
         "两家联姻，各取所需罢了。条款上写得清清楚楚。"),
        ("fr_origin2", 2,
         "十年前的那场暴雨，公交站台，穿校服的女孩把伞塞给了一个浑身湿透、刚从葬礼回来的少年，"
         "自己跑进了雨里。少年后来找了那把伞的主人很多年。伞柄上刻着一个「晚」字。",
         "十年前 下雨 雨天 伞 高中 认识我 见过 以前 少年",
         {"affinity_min": 18, "act_min": 2, "asks_min": 3},
         "我们结婚前素不相识。"),
        ("fr_origin3", 3,
         "樟木箱里：一把旧伞，伞柄刻着「晚」；你第一次画展的门票，一共十七张，每一场都有；"
         "还有一沓匿名认购记录——你以为卖出去的第一批画，买主全是同一个人。箱底压着一行字："
         "「等她不需要这些的时候，再告诉她。」",
         "箱子 樟木箱 阁楼 旧物 画展 门票 匿名 买画 资助",
         {"location_id": "loc_attic", "act_min": 4},
         None),
    ]),
    ("苏晚晴的来意", "su", "medium", ["su", "gu"], [
        ("fr_su1", 1,
         "苏晚晴不是什么白月光。她是顾之瑶的主治医生——之瑶的心脏手术，主刀的就是她。"
         "顾之衍频繁见她，见的是妹妹的主治医生。",
         "苏晚晴 白月光 关系 医生 医院 之瑶 手术 传闻 密会",
         {"affinity_min": 8, "act_min": 2, "asks_min": 2},
         "我和之衍很熟，熟到什么程度……你猜。"),
        ("fr_su2", 2,
         "之瑶的手术风险极高，国内只有两个团队敢接。顾之衍瞒着所有人飞了四个城市把人请齐，"
         "又不想让新婚的你背上「冲喜」的闲话——所以连你也瞒。深夜出入医院的照片，拍的全是这件事。",
         "手术 瞒着 隐瞒 为什么不说 医院照片 深夜 奔走 冲喜",
         {"affinity_min": 15, "act_min": 3, "asks_min": 2},
         None),
    ]),
    ("陈妈守着的旧事", "chen", "light", ["chen"], [
        ("fr_chenma1", 1,
         "少爷有只谁也不许碰的旧箱子，从旧宅搬来那天他亲自抱上的阁楼。三十年了，陈妈只见他"
         "对两样东西上过心：那只箱子，和你搬进来那天他亲手换的那盏台灯。",
         "箱子 阁楼 旧物 秘密 少爷 台灯 上心",
         {"affinity_min": 8, "act_min": 2, "asks_min": 2},
         None),
    ]),
    ("之瑶的小算盘", "yao", "light", ["yao", "su"], [
        ("fr_yao1", 1,
         "之瑶早就看穿了：哥哥书房里锁着的抽屉，她小时候偷开过——里面是一把旧伞和一支带牙印的铅笔。"
         "她管这叫「哥哥的十年」。所以你进门第一天她就喊嫂子，喊得一点都不亏心。",
         "之瑶 撮合 嫂子 抽屉 知道什么 小算盘 故意",
         {"affinity_min": 12, "act_min": 2, "asks_min": 1},
         None),
    ]),
]

ENDINGS = [
    {"id": "end_true", "kind": "true", "title": "十年之后，倾盖如故",
     "text": "他握住你的手，掌心烫得不像他。「条款作废。」他说，「从今天起，只有一条：顾之衍，"
             "婚内爱上林晚，此后年年岁岁，愿赌服输。」水晶灯太亮，你终于看清他耳根红了十年。",
     "condition": {"affinity_min": 24, "act_min": 0,
                   "required_fragment_ids": ["fr_origin3"],
                   "required_flags": {"chose_stay": True}}},
    {"id": "end_normal", "kind": "normal", "title": "体面地离开",
     "text": "你在掌声里欠身退场，礼服下摆扫过门槛，没有回头。条款履行完毕，谁也不欠谁。"
             "车开出顾宅时你打开速写本，最后一页不知何时被人画了一把伞——笔触很生疏，像是练了很多遍。",
     "condition": {"act_min": 0, "required_flags": {"chose_leave": True}}},
    {"id": "end_cold", "kind": "bad", "title": "形同陌路", "trigger": "pressure",
     "text": "误会没有解开的那一天，只有懒得再解释的那一天。同一屋檐下，两份早餐越摆越远，"
             "后来干脆错开了时间。条款还剩两百多天，你们谁都没再数。",
     "condition": {}},
]

PRESSURE = {"name": "误会", "hint": "误会与隔阂在加深——问出口，比猜下去便宜得多",
            "ending_id": "end_cold",
            "levels": [{"at": 40, "note": "餐桌上的沉默越来越长，陈妈的汤都劝不动了。"},
                       {"at": 70, "note": "他开始睡在书房。台灯亮到后半夜，谁也不去敲门。"}]}


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
            owner_id=user.id, title=TITLE, language="zh",
            one_liner="条款十二条的契约婚姻。可他记得你不吃香菜，记得你画画到几点。",
            synopsis="为了爷爷的心愿，你嫁给了素不相识的顾氏继承人。婚内协议十二条，互不打扰。"
            "可这栋房子处处不对劲：不许碰的旧箱子、换了的台灯、传闻里的白月光。"
            "越靠近他，越接近一个藏了十年的真相——这桩「生意」，从头到尾只有一个人在装。",
            world_long="现代都市，顾氏老宅。新婚第一夜开始的同居生活：客厅、餐厅、书房、"
            "玫瑰园、老宅阁楼。空气里都是没说出口的话。",
            world_facts="顾宅共五处可去：客厅居中，通餐厅/书房/玫瑰园/阁楼；半山咖啡馆在城里医院对面。"
            "《婚内协议》共十二条，第七条：晚归须报备。林晚随身带一只旧速写本。",
            relations_overview="林晚（你）与顾之衍是契约夫妻；陈妈照顾全家；之瑶是之衍胞妹、苏晚晴的病人；"
            "苏晚晴与之衍是大学同学，外界传为白月光。",
            trope_tags=["女性向", "先婚后爱", "都市", "甜宠", "误会流"],
            characters=CHARACTERS, acts=ACTS, endings=ENDINGS, locations=LOCATIONS,
            pressure=PRESSURE, phone={"enabled": True, "device": "手机"},
            tuning={"golden_chance": 6, "rom_taper_den": 100},
            visibility="public",
        )
        db.add(story)
        db.flush()

        for title, char_id, sens, known_by, frags in SECRETS:
            sec = Secret(story_id=story.id, character_id=char_id, title=title, sensitivity=sens)
            sec.fragments = [
                Fragment(id=fid, layer=l, content=c, retrieval_key=r,
                         known_by_character_ids=known_by, unlock=u, cover=cov)
                for (fid, l, c, r, u, cov) in frags
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
