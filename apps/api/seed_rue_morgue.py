"""Seed 《莫格街凶案》— interactive adaptation of Poe's "The Murders in the Rue Morgue"
(public domain). You play the analyst 迪潘: pull the truth out of a defensive prefect, a
rattled baker, and finally a terrified sailor — by earning their trust (好感 = 肯不肯对你交底),
peeling a locked-room impossibility apart layer by layer until a truth beyond common sense
comes to light, and an innocent man walks free.

九龙城寨-caliber vertical slice: deepened characters, 5 acts, layered gated secrets, physical
locations that unlock as you learn of them, per-character relationship (trust, not romance),
hard gates (clue + rapport). Run:  python seed_rue_morgue.py  (idempotent; publishes public v1).
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
    {
        "id": "dupin",
        "name": "迪潘",
        # 玩家扮演的分析者(默认不由AI驱动)。整个故事从他的推理视角展开。
        "playable": True,
        "role": "分析者",
        "is_lead": False,
        "agenda": "（玩家角色）用纯粹的推理还原莫格街命案的真相，洗清被冤枉的勒邦——不放过任何一处'不对劲'。",
        "eq_style": "（玩家角色，通常不由AI驱动）冷静、克制，句句切中要害，读人比谁都准。",
        "persona_text": "深居简出、昼伏夜出的分析天才，爱在拉严的百叶窗后、在黑暗里思考。清瘦，眼神能穿透表象直看到骨头缝里。"
        "他相信混乱的表象底下永远藏着一条可被理性照亮的线。",
        "background": "靠一副能拆开任何谜题的头脑度日。莫格街的血案全城束手，唯独他嗅到——这桩'不可能'背后，藏着一个常理之外、却合乎逻辑的真相。",
    },
    {
        "id": "prefect",
        "name": "警长G",
        # 巴黎警务局长,案子的官方口径持有人。钉在凶案现场坐镇。
        "home_location_id": "loc_scene",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "enemy"],
        "is_lead": True,  # 官方信息的关口:开场就在现场,默认应答者
        "role": "巴黎警务局长",
        "agenda": "守住'银行职员勒邦就是凶手、本案已破'的体面结论，不肯被一个'空想推理的门外汉'打脸——可你越问，他心里越发虚。",
        "eq_style": "端着官架子、爱背手踱步；一被问到软肋就清嗓子、重复官话，"
        "可他是个藏不住话的自负者——你越戳中要害，他越忍不住把现场细节一股脑抖出来。",
        "persona_text": "制服笔挺、金表挂链的警务局长，说话时爱背着手在屋里踱来踱去。循规蹈矩、极自负，"
        "对你这种'纸上谈兵'半是轻蔑半是好奇。口头禅：'这案子，明摆着的。'一心想尽快合上卷宗，"
        "偏偏那些他也解释不了的细节，像鞋里的沙子，硌得他不安。",
        "background": "手里攥着全部官方勘验记录——门窗、伤口、毛发、那笔没被拿走的钱——却读不懂它们到底在说什么。",
    },
    {
        "id": "musset",
        "name": "缪塞",
        # 案发那晚冲上楼的邻居,唯一听清"那个声音"的人。守在莫格街街上。
        "home_location_id": "loc_street",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend"],
        "role": "邻居 · 面包师",
        "is_lead": False,
        "agenda": "把心里那个'谁也听不懂的声音'讲给一个真肯听、真会信的人——好让自己夜里能睡个安稳觉。",
        "eq_style": "老实、絮叨、极易受惊；一提那晚就搓手、压低嗓子。你越耐心、越拿他当回事，他越肯把细节掏给你。",
        "persona_text": "住在莫格街、围裙上还沾着面粉的面包师，手粗、嗓门却压得低。案发那晚他随众人破门冲上四楼，"
        "至今惊魂未定。总反复念叨'我发誓我没听错'。他听见了两个声音——一个在骂人，另一个……他说不上来是什么。",
        "background": "他是众多证人里，唯一能把'那个尖利刺耳的声音'描摹得最细的人——细到叫人脊背发凉。",
    },
    {
        "id": "sailor",
        "name": "那个水手",
        # 真相的关键人物。第四幕被那则登报的启事逼出来,现身迪潘的寓所。
        "home_location_id": "loc_dupin",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "enemy"],
        "appears_from_act": 4,
        "role": "马耳他船员",
        "is_lead": False,
        "agenda": "本想装作与己无关、逃开这桩塌天的祸事；可那则启事把他逼到墙角——招，还是不招，"
        "良心和恐惧在他胸口拉锯。",
        "eq_style": "惊惶、戒备、眼神躲闪，一被点破就攥紧衣角、声音发抖；但良心未泯——"
        "你若真诚待他、或把他逼到退无可退，那个憋了太久的真相才会决堤。",
        "persona_text": "皮肤黝黑的马耳他船员，手上是常年航海磨出的老茧。神色惊惶，一见生人就想躲。"
        "他从婆罗洲带回来的'东西'，闯了一场没人敢信的大祸——而他，眼睁睁看着，却没敢吭声。",
        "background": "那晚的惨剧他从头看到尾，事后却缩着脖子逃了，任无辜的勒邦替他坐牢——"
        "直到报上那则启事，像一只手，把他从黑暗里揪了出来。",
    },
]

ACTS = [
    {"id": "a1", "index": 1, "title": "锁闭的房间",
     "goal": "勘验现场——弄清凶手到底怎样进出这间从里面反锁的四楼卧室",
     # 硬门:先撬开"密室怎么进出"这层,并跟警长G打出点交道(他肯对你交底)
     "advance": {"required_fragment_ids": ["fr_window"], "affinity_min": 4},
     "events": [
        {"id": "e_scene", "what_happens": "莱斯巴拉叶夫人母女惨死在莫格街一栋公寓的四楼。房门从内反锁，窗户紧闭，一袋金币却原封未动地扔在地上。警长G背着手站在血迹旁，一口咬定案子已破。", "who_character_ids": ["prefect"]},
     ]},
    {"id": "a2", "index": 2, "title": "谁也听不懂的声音",
     "goal": "找到街坊里的证人——问清众人破门那晚，究竟听见了什么样的声音",
     "advance": {"required_fragment_ids": ["fr_voice2"], "affinity_min": 8},
     "events": [
        {"id": "e_voices", "what_happens": "破门冲上楼的人都咬定听见两个声音：一个粗哑地在骂法语，另一个尖利刺耳——可荷兰人说那是法语、法国人说是西班牙语、英国人说是德语，没有一个人能说出哪怕一个词。", "who_character_ids": ["musset"]},
     ]},
    {"id": "a3", "index": 3, "title": "不是人干的",
     "goal": "把现场的痕迹拼起来——那股力气、那几根毛发、那道抓痕，指向一个骇人的结论",
     "advance": {"required_fragment_ids": ["fr_beast2"], "affinity_min": 12},
     "events": [
        {"id": "e_traces", "what_happens": "女儿的尸体被硬生生倒塞进烟囱，要有惊人的力气才做得到；母亲几乎被一刀断了颈。死者手里攥着几根粗硬的茶褐色毛发——那不是人的。窗台外沿，有一道宽得不像话的抓痕。", "who_character_ids": ["prefect", "musset"]},
     ]},
    {"id": "a4", "index": 4, "title": "登报引凶",
     "goal": "顺着推断在报上登一则启事，把那个躲起来的人引出来——再从他口中撬出真相",
     "advance": {"required_fragment_ids": ["fr_ape"], "affinity_min": 15},
     "events": [
        {"id": "e_ad", "what_happens": "你回到寓所，在报上登了一则'寻获走失猩猩、请失主认领'的启事——只为引一个人现身。没过多久，楼梯上响起犹疑的脚步声：一个皮肤黝黑的水手，站在了你门口。", "who_character_ids": ["sailor"]},
     ]},
    {"id": "a5", "index": 5, "title": "真相大白",
     "goal": "让水手把那晚的一切说全——放出无辜的勒邦，给这桩血案一个说得通的了结",
     "events": [
        {"id": "e_confess", "what_happens": "水手瘫在椅子上，把那晚的始末从头讲了。你手里，终于攥齐了能让勒邦重见天日的全部真相。", "who_character_ids": ["sailor"]},
     ]},
]

# 具体地点——玩家所在的空间锚点。地点要有人亲口点出地名,才会出现在可去的路上。
LOCATIONS = [
    {"id": "loc_scene", "name": "莫格街四楼·凶案现场",
     "detail": "一间从里面反锁过的四楼卧室，家具翻倒、抽屉被翻得七零八落，可一袋金币还扔在地板上。"
     "壁炉的烟囱口有被硬塞过东西的痕迹，靠床那扇窗紧闭着，窗台上凝着暗色的血。空气里是铁锈味和陈年的霉味。",
     "exits": ["莫格街街上", "迪潘的寓所"]},
    {"id": "loc_street", "name": "莫格街街上",
     "detail": "案发公寓楼下一条逼仄的老街，青石板被无数只脚磨得发亮。街坊聚在门廊下低声议论，"
     "拐角面包铺飘出的暖香，压不住众人脸上那层没散尽的惊惶。",
     "exits": ["莫格街四楼·凶案现场"],
     # 警长G提到"去街上问问听见怪声的邻居"(fr_witness 里点了名),这条街才出现在你可去的路上
     "unlock": {"required_fragment_ids": ["fr_witness"]}},
    {"id": "loc_dupin", "name": "迪潘的寓所",
     "detail": "白日里也拉严了百叶窗的昏暗房间，书堆得到处都是，只留一圈烛光。你在这里把线索一条条摆开、"
     "推演、写下那则登报的启事。安静得能听见自己思路转动的声音。",
     "exits": ["莫格街四楼·凶案现场"],
     # 认定'凶手不是人'之后,你才会退回寓所静心推演、登报引凶——这地方这时才在流程上打开
     "unlock": {"required_fragment_ids": ["fr_beast2"]}},
]

# (title, character_id, sensitivity, known_by, [(fragment_id, layer, content, retrieval_key, unlock)])
# 检索关键词收紧成"真正在问这件事"的问法,避免泛词误触发;大真相分层,越深门槛越高。
SECRETS = [
    ("密室之谜", "prefect", "medium", ["prefect"], [
        ("fr_window", 1,
         "警长G哼了一声，还是说了：门是从里头闩死的，没错。可靠床那扇窗——你仔细看，钉窗的那根钉子，"
         "早断成了两截，断口锈死，看着却像好端端钉着。窗子能被推上去、再自己落回'看似锁着'的位置。"
         "凶手根本不必开门——他是从这扇窗进、又从这扇窗出的。",
         "怎么进 怎么出 密室 反锁 窗户 那扇窗 门是不是锁的 怎么进出的",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
    ]),
    ("街坊的证词", "prefect", "light", ["prefect"], [
        ("fr_witness", 1,
         "警长G不耐烦地摆摆手：证人？街上一大把。你要真想听那些没用的，去莫格街楼下问那个面包师，"
         "叫缪塞的——破门那晚他冲在头里，逢人就念叨他听见了什么怪声，吵得人耳朵疼。",
         "证人 目击 谁听见了 街坊 邻居 还有谁在场 谁破的门",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
    ]),
    ("谁也听不懂的声音", "musset", "medium", ["musset"], [
        ("fr_voice1", 1,
         "缪塞搓着手，压低了嗓子：楼上是两个声音在吵。一个粗哑，是在骂法语，这个我敢赌咒。可另一个……"
         "又尖又利，忽高忽低，不像在说话，倒像……我形容不上来，先生，我这辈子没听过那种声儿。",
         "声音 什么声音 听见什么 两个声音 尖叫 楼上吵什么",
         {"affinity_min": 2, "act_min": 2, "asks_min": 1}),
        ("fr_voice2", 2,
         "缪塞的脸白了几分：怪就怪在这儿。那晚在场的，法国人、荷兰人、西班牙人、英国人都有——"
         "可谁都咬定那尖声是'别国的话'：法国人说是西班牙语，荷兰人说是法语，英国人说是德语……"
         "偏偏没有一个人，能从里头听出哪怕一个词来。您说，天底下哪有这样的语言？",
         "什么语言 哪国话 到底说的什么 听懂了吗 是不是人 谁的声音",
         {"affinity_min": 6, "act_min": 2, "asks_min": 2}),
    ]),
    ("非人之力", "prefect", "medium", ["prefect", "musset"], [
        ("fr_beast1", 1,
         "验尸的细节警长G本不想提，可还是被你问出了口：那姑娘是被倒着、硬塞进烟囱里去的——几个壮汉合力"
         "才把她拽下来。老太太几乎被一刀断了脖子。死者手心里，还攥着几撮粗硬的、茶褐色的毛发。",
         "伤口 尸体 烟囱 力气 毛发 头发 怎么死的 验尸",
         {"affinity_min": 6, "act_min": 3, "asks_min": 1}),
        ("fr_beast2", 2,
         "把这些摆到一处，那个念头就压不住了：那毛发不是人的。倒塞进烟囱、一刀断颈、徒手翻上四楼——"
         "没有哪个人有这样的力气和身手。窗台外沿那道宽得反常的抓痕，也不是人的手能抓出来的。"
         "凶手，根本就不是一个人。",
         "不是人 是什么 什么东西 到底谁干的 这些说明什么 你怎么想",
         {"affinity_min": 10, "act_min": 3, "asks_min": 2}),
    ]),
    ("真凶", "sailor", "heavy", ["sailor"], [
        ("fr_ape", 1,
         "水手脸色惨白，嘴唇抖了半天：那是一头……一头从婆罗洲带回来的猩猩。那晚它挣脱了绳子，抓着我的剃刀，"
         "学我平日刮脸的样子，攀着避雷针就翻了进去。它没安坏心，先生——可它有一身蛮力，手里还攥着一把刀。",
         "凶手是什么 是什么东西 猩猩 猴子 动物 真凶是谁 到底是什么",
         {"affinity_min": 12, "act_min": 4, "asks_min": 2}),
        ("fr_sailor", 2,
         "他把脸埋进手里：我追上了楼，趴在窗外，眼睁睁看着那畜生……我吓瘫了，一步也动不了。事后我逃了，"
         "任由那个姓勒邦的替我进了牢——我不是人，先生。可我愿意作证，把这些一字不落写下来：勒邦是清白的。",
         "你看见了什么 为什么不报案 勒邦 清白 作证 招供 自白 你当时在做什么",
         {"affinity_min": 15, "act_min": 4, "asks_min": 2}),
    ]),
]

ENDINGS = [
    {"id": "end_true", "kind": "true", "title": "真相大白",
     "text": "那则启事，终究把水手钓了出来。当他抖着嘴唇吐出'猩猩'二字，所有的'不可能'豁然贯通——"
             "反锁的房间、谁也听不懂的尖声、非人的蛮力，原来都指向同一个常理之外、却合乎逻辑的真相。"
             "无辜的勒邦当夜获释。莫格街的黑暗里，理性点亮了唯一的那盏灯。",
     "condition": {"affinity_min": 16, "act_min": 0, "required_fragment_ids": ["fr_ape", "fr_sailor"]}},
    {"id": "end_normal", "kind": "normal", "title": "悬案",
     "text": "线索散落一地，却始终没能拼成一幅完整的图。警方维持原判，莫格街的血案，成了卷宗深处又一桩"
             "'无法解释'——而牢里那个人，还在等一个也许永远不会来的清白。",
     "condition": {"affinity_min": 0, "act_min": 0}},
    {"id": "end_bad", "kind": "bad", "title": "冤沉狱底",
     "text": "你到底没能把那个躲在暗处的人引出来，或是把他逼得死死噤了声。真凶连同真相一起沉进了黑暗，"
             "替罪的勒邦在狱中一天天枯下去。理性这一回，输给了恐惧与沉默。",
     "condition": {"affinity_min": 0, "act_min": 0}},
    {"id": "end_death", "kind": "death", "title": "打草惊蛇",
     "text": "你太急了，在最不该逼的时候把那头畜生、或那个走投无路的水手逼到了绝境。剃刀的寒光比真相先到——"
             "你带着满脑子已经拼好的推理，倒在了离答案只差一步的地方。",
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
                   tagline="靠推理破局的分析者", background="旁人眼中的怪人，混乱里唯一看得见那条线的人。"))
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
            one_liner="母女惨死在反锁的四楼，凶手却像凭空消失。你是迪潘——用纯粹的推理，从一个个不肯开口的人嘴里，撬出常理之外的真相。",
            synopsis="十九世纪的巴黎，莫格街，一桩不可能的命案：房间从内反锁，凶手无影无踪，证人听见一个"
            "谁也听不懂的声音，钱财却分文未取。警方草草抓了个替罪的银行职员结案，唯有你看出，这桩血案"
            "背后藏着一个常理之外、却合乎逻辑的真相。你得先赢得警长、面包师、水手的信任，才能让他们把"
            "各自那块拼图交到你手上——一层层揭开，直到无辜者重见天日。",
            world_long="十九世纪的巴黎。莱斯巴拉叶夫人母女惨死在莫格街一栋公寓的四楼，门窗紧闭、钱财未失，"
            "全城哗然。警务局长草草逮了个替罪的银行职员勒邦，把案子合上了卷。可门是从里头反锁的、"
            "凶手无影无踪、破门的众人听见一个谁也听不懂的尖声——太多细节，连警方自己都解释不了。",
            relations_overview="你（迪潘）是本案的破局者，须靠推理与耐心，赢得各方信任、逐层撬出真相："
            "自负的警长G握着官方勘验、却看不懂它们（凶案现场）；面包师缪塞是唯一听清那怪声的证人（莫格街街上）；"
            "而真相的关键，是一个躲起来的马耳他水手——他要到第四幕，被你登报引出，才现身你的寓所。",
            world_facts=(
                "【地点】故事发生在十九世纪巴黎的莫格街一带：楼上是从内反锁的四楼凶案现场，楼下是逼仄的老街，"
                "还有迪潘白日也拉严百叶窗的昏暗寓所。\n"
                "【关键事实·不可违背】① 房门确实从内反锁；② 凶手真正的进出口是靠床那扇'钉子断裂、看似锁着'的窗；"
                "③ 破门众人听见两个声音，一个是粗哑法语在骂人，另一个尖利刺耳、谁都听不出是哪国话；④ 死者钱财未失；"
                "⑤ 女儿被倒塞进烟囱、母亲几乎断颈，死者手中攥有非人的茶褐色毛发；⑥ 真凶是一头从婆罗洲带回、"
                "挣脱后攥着水手剃刀翻窗闯入的猩猩；⑦ 银行职员勒邦是被冤枉的。\n"
                "【在场的人】现场是警长G；街上是面包师缪塞；水手第四幕才被登报引出、现身迪潘的寓所——在那之前他不在场，"
                "不要让他提前出现。迪潘是玩家扮演的角色。\n"
                "【基调】古典推理、冷峻克制；这不是靠打斗、而是靠观察、提问与推理破局的故事。"
            ),
            trope_tags=["推理", "悬疑", "密室", "古典", "本格"],
            characters=CHARACTERS, acts=ACTS, endings=ENDINGS, locations=LOCATIONS,
            visibility="public",
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
        print(f"OK seeded 《{TITLE}》 story_id={story.id}")
        print(f"   主角=迪潘(分析者)。acts={len(ACTS)} secrets={len(SECRETS)} fragments={n_frag} locations={len(LOCATIONS)}. published v1, public.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
