# -*- coding: utf-8 -*-
"""Seed 《聊斋·聂小倩》 — the public-domain showcase (Hidden Door's IP play, done with
蒲松龄): a ghost romance where every engine system earns its keep — 小倩 only appears
at NIGHT (slot schedule), the full moon is a hard deadline (clock), 姥姥 watches
(pressure), promises pull you back, and 纸鹤 carry her messages (phone device).

Run:  python seed_nieqian.py
Idempotent: wipes any prior copy (same title + demo owner) and its runs/snapshots.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

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

TITLE = "聊斋·聂小倩"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    {
        "id": "ning",
        "name": "宁采臣",
        "role": "赴金华收账的书生",
        "playable": True,
        "persona_text": "二十出头的穷书生，青衫洗得发白，背一只旧书箧。为人端方，穷得坦荡，"
        "认死理：不义之财一文不取，不该动的心一分不动。夜里读书到三更是常事。",
        "background": "受族叔所托来金华收一笔旧账，盘缠将尽，城中客栈住不起，闻兰若寺荒废可以借宿，"
        "便搬了进来。行囊里有一册账本、半吊铜钱，和一封写了一半的家书。",
        "items": [{"name": "半吊铜钱", "detail": "数得过来的盘缠，掂在手里轻得心慌。"},
                  {"name": "族叔的账本", "detail": "此行的差事，收不回账便回不了乡。"}],
    },
    {
        "id": "qian",
        # 🌙 夜行作息: 白日无处寻她（AWAY），入夜才在荷池畔现身——找到她，本身就是玩法。
        "schedule": [{"from_act": 1, "location_id": "loc_pool", "slots": ["夜"]}],
        "name": "聂小倩",
        "role": "夜里才出现的女子",
        "is_lead": True,
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover", "enemy"],
        "agenda": "奉姥姥之命以色与金迷惑借宿之人、摄其精血——但她夜夜下不去手，只想找一个"
        "既不贪财也不贪色的人，赌一次把实情托付出去的机会。她在试探宁采臣，比他试探她更小心。",
        "eq_style": "外冷内怯，温柔都是试探性的：先递半句，看你的眼色，再决定收回还是给完。"
        "被善意戳中时会怔住，别过脸去；被拒绝反而松一口气。从不大声说话。",
        "persona_text": "十七八岁模样的女子，月白衫子，乌发松松挽着，眉眼极美，美得不像这荒寺里该有的活气。"
        "夜里提一盏小灯从荷池那边过来，脚步一点声息也没有。笑起来先垂眼，说话留三分，"
        "袖中总藏着什么。你若细看，她在月光下几乎没有影子。",
        "background": "自称借居寺侧的乡下女子，父母双亡。问她住处，她只朝白杨树的方向遥遥一指。"
        "夜半会来敲窗，送来一锭金子、一盏温酒——收与不收，是她看人的第一道题。",
        "bio_layers": [
            {"closeness_min": 0, "text": "夜里才见得到的女子，来历不明，说话留三分。"},
            {"closeness_min": 20, "text": "她怕晨光，怕铃声，怕南院那位剑客。递给你的金子，你若不收，她眼里反而有光。"},
            {"closeness_min": 45, "text": "她十八岁那年死的。这寺侧的孤坟一躺就是许多年，连一个烧纸的人都没有。"
                                          "她说：做鬼这些年，头一回有人问她冷不冷。"},
        ],
    },
    {
        "id": "yan",
        # 剑客的作息：晨午在南院打坐练剑，入夜移到大殿镇场——夜里想找他护身，去大殿。
        "schedule": [{"from_act": 1, "location_id": "loc_south", "slots": ["晨", "午"]},
                     {"from_act": 1, "location_id": "loc_hall", "slots": ["夜"]}],
        "ties": [{"char_id": "laolao", "stance": -2, "label": "追杀多年的死仇"},
                 {"char_id": "qian", "stance": -1, "label": "妖物，本该一剑了断"}],
        "name": "燕赤霞",
        "role": "借住南院的剑客",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "elder"],
        "agenda": "追一桩没了结的旧案至此，守着兰若寺等那东西现形。不愿多话，不愿沾人命官司，"
        "但见不得书生白白送死——救不救得下，看这书生自己争不争气。",
        "eq_style": "话糙理正，关心全裹在训斥里：骂你夜里乱走，转身却把辟邪的剑穗塞给你。"
        "从不安慰人，只给办法。你若实心实意，他肯多说一句；你若虚与委蛇，他眼皮都不抬。",
        "persona_text": "四十上下的黑脸汉子，粗布短打，腰背笔直，睡觉也抱着一只两尺长的旧皮剑匣。"
        "白日在南院打坐磨剑，夜里坐在大殿门槛上喝酒，眼睛却一直看着后园的方向。"
        "口头禅：'书生，命比账本值钱。'",
        "background": "自称云游的武人，实则来历不浅。那只从不离身的剑匣，夜里偶尔会自己嗡嗡作响。",
        "bio_layers": [
            {"closeness_min": 0, "text": "借住南院的剑客，寡言，让人不敢亲近。"},
            {"closeness_min": 25, "text": "他不是路过。他在等什么东西现形——等了很久了。"},
        ],
    },
    {
        "id": "lan",
        "name": "兰溪生",
        "role": "同住东厢的商人",
        "home_location_id": "loc_east",
        "relation_default": "peer",
        "agenda": "做完这趟买卖就回乡娶亲。夜里若有美人敲窗，他自问没有拒绝的道理。",
        "eq_style": "自来熟，爱吹嘘，好心也是真好心：会分你半壶酒，也会劝你'读书人别太死板'。",
        "persona_text": "三十来岁的绸缎商人，圆脸常笑，腰间钱袋鼓鼓的，爱显摆一枚新得的玉扳指。"
        "同是借宿人，第一晚就拉着你喝酒，说这寺里'夜里有好事'。",
        "background": "比你早两日住进兰若寺。这两夜他红光满面，又隐隐透着一层灰败，自己浑然不觉。",
    },
    {
        "id": "laolao",
        "name": "姥姥",
        "role": "夜里的声音",
        "presence": "offstage",
        "agenda": "月圆之夜收足生魂精血。谁碍事，就先收谁。",
        "persona_text": "没有人见过她的样子。她在夜风里、在白杨树梢、在小倩骤然僵住的脸上。"
        "有时是一声苍老的轻笑，有时是满园树叶无风自动。",
        "background": "寺侧那株百年白杨的东西。这荒寺方圆的夜，都是她的。",
    },
]

ACTS = [
    {"id": "a1", "index": 1, "title": "借宿兰若",
     "goal": "在荒寺安顿下来，摸清同住的都是什么人",
     "advance": {"required_fragment_ids": ["q_night1"]},
     "events": [
         {"id": "e_qin", "what_happens": "三更天，后园荷池方向飘来一缕极轻的琴声，转瞬又没了。",
          "who_character_ids": []},
     ]},
    {"id": "a2", "index": 2, "title": "夜半敲窗",
     "goal": "弄清那个夜里的女子想要什么——以及她为什么下不去手",
     "advance": {"required_fragment_ids": ["q_coerce1"], "required_event_ids": ["e_lan_dead"]},
     "events": [
         {"id": "e_gold", "what_happens": "窗台上不知何时多了一锭黄澄澄的金子，在月光下泛着不干净的光。",
          "who_character_ids": ["qian"]},
         {"id": "e_lan_dead", "what_happens": "清晨，东厢传来惊叫——兰溪生死在榻上，面色灰败如纸，"
                                              "身上没有半点伤，只脚心一个针眼似的小孔。",
          "who_character_ids": ["lan"]},
     ]},
    {"id": "a3", "index": 3, "title": "孤坟何处",
     "goal": "让小倩把身世和埋骨之处托付给你",
     "advance": {"required_fragment_ids": ["q_bones1"]},
     "events": [
         {"id": "e_wind", "what_happens": "满园的白杨叶无风自动，哗哗地响，像谁在头顶翻一本很旧的书。",
          "who_character_ids": []},
     ]},
    {"id": "a4", "index": 4, "title": "剑匣与古树",
     "goal": "说动燕赤霞出手，弄清姥姥的弱点，趁夜起出白杨树下的骸骨",
     "advance": {"required_fragment_ids": ["y_weak1"], "required_event_ids": ["e_dig"]},
     "events": [
         {"id": "e_box", "what_happens": "南院的剑匣毫无征兆地嗡鸣起来，声震屋瓦——燕赤霞霍然睁眼。",
          "who_character_ids": ["yan"]},
         {"id": "e_dig", "what_happens": "白杨树下，锹头碰到了硬物。一方朽烂的薄棺露了出来，"
                                         "棺中白骨纤细，腕上还套着一只褪色的银镯。",
          "who_character_ids": []},
     ]},
    {"id": "a5", "index": 5, "title": "月圆之夜",
     "goal": "在姥姥收魂之前，护住骸骨，送她走",
     "advance": {},
     "choice": {
        "prompt": "满月升到树梢，整座兰若寺的影子都活了。姥姥的声音从四面八方压下来：把骨头留下。这一刻，你——",
        "options": [
            {"id": "guard", "label": "把骨坛抱进怀里，一步不退",
             "flag": "guarded_bones", "affinity_delta": 3,
             "character_id": "qian", "closeness_delta": 6, "romance_delta": 4},
            {"id": "yield", "label": "把骨坛放到地上，往后退",
             "flag": "yielded_bones", "affinity_delta": -3,
             "character_id": "qian", "closeness_delta": -8},
            {"id": "call", "label": "高声呼喊燕赤霞的名字",
             "flag": "called_yan", "affinity_delta": 1},
        ],
     },
     "events": [
         {"id": "e_moonrise", "what_happens": "月亮升起来了，又圆又白，白杨树的影子在地上张开，像一只手。",
          "who_character_ids": []},
     ]},
]

LOCATIONS = [
    {"id": "loc_hall", "name": "兰若寺大殿",
     "detail": "梁上蛛网垂到佛像肩头，金身剥落大半，唯独一双眼睛还完整，在昏暗里低低看着人。"
     "殿角堆着前人留下的干草铺位，门槛被磨得发亮。夜里，燕赤霞常坐在这条门槛上喝酒。",
     "exits": ["东厢客房", "南院禅房", "后园荷池"],
     "props": [{"id": "p_stele", "name": "断碑", "fragment_id": "t_temple1",
                "detail": "半截石碑斜在殿角，碑文风化过半。"}]},
    {"id": "loc_east", "name": "东厢客房",
     "detail": "两间还算完整的客房，窗纸新糊了一半。你的书箧靠墙放着，桌上一盏油灯。"
     "隔壁住着兰溪生，夜里常有他的鼾声——直到那个清晨。",
     "exits": ["兰若寺大殿"],
     "props": [{"id": "p_window", "name": "窗台",
                "detail": "窗台上一层薄灰，有几个极浅的、不像人脚的印子，朝着荷池的方向。"}]},
    {"id": "loc_south", "name": "南院禅房",
     "detail": "打扫得干干净净的一间禅房，与满寺荒芜格格不入。墙上挂一柄木剑，"
     "床头摆着那只两尺长的旧皮剑匣。院里一块青石，被人当磨剑石用了很久。",
     "exits": ["兰若寺大殿"],
     "props": [{"id": "p_box", "name": "剑匣", "fragment_id": "y_sword1", "event_id": "e_box",
                "detail": "旧皮剑匣，锁扣是黄铜的，摸上去微微发烫。"}]},
    {"id": "loc_pool", "name": "后园荷池",
     "detail": "半池枯荷，月光落在水面碎成一片。池畔一条石凳，凳上常年干净，像总有人来坐。"
     "再往北，一株百年白杨黑压压地立着，把半个园子罩在影子里。",
     "exits": ["兰若寺大殿", "白杨古树"],
     "props": [{"id": "p_shoe", "name": "石凳下的绣鞋", "fragment_id": "q_night2",
                "detail": "一只极旧的绣鞋，样式是许多年前的，鞋面却干干净净。"}]},
    {"id": "loc_tomb", "name": "白杨古树",
     "detail": "树干粗得三人难合抱，树皮皴裂如老人手背。树根间隆起一座矮矮的土坟，没有碑。"
     "站在树下，白日也觉得冷。",
     "exits": ["后园荷池"],
     # 🔒 要先从小倩口中问出埋骨之处，这个地方才会在地图上亮起来
     "unlock": {"required_fragment_ids": ["q_bones1"]},
     "props": [{"id": "p_mound", "name": "无碑的土坟", "fragment_id": "q_bones2",
                "detail": "新土混着旧土——近来有什么东西刨开过又埋上。"}]},
]

# (fragment_id, layer, content, retrieval_key, unlock)
SECRETS = [
    ("夜里的女子是什么", "qian", "heavy", ["qian", "yan"], [
        ("q_night1", 1,
         "她脚不沾尘，月下无影。她不是人——这荒寺夜里提灯走动的，是一缕留在世上的魂。",
         "她是谁 来历 夜里 影子", {"asks_min": 2}),
        ("q_night2", 2,
         "她叫聂小倩，十八岁那年病死，葬在寺侧。这只绣鞋是她生前之物——她夜夜来石凳上坐，"
         "是在看自己活着时的东西。",
         "聂小倩 绣鞋 十八 生前", {"asks_min": 1, "affinity_min": 6}),
    ]),
    ("金子与温酒", "qian", "medium", ["qian"], [
        ("q_test1", 1,
         "夜半送到你窗前的金子不是金子，是罗刹鬼骨；沾了它的人，精血便归了姥姥。"
         "收了金子的人，没有一个活过三夜。你不收，她才敢与你说话。",
         "金子 鬼骨 温酒 试探", {"asks_min": 1, "affinity_min": 4}),
    ]),
    ("姥姥的胁迫", "qian", "heavy", ["qian"], [
        ("q_coerce1", 1,
         "她不是自愿害人。白杨树下的姥姥拿捏着她的骸骨，令她以色与金诱人、摄取精血供养自己；"
         "违命一次，便受一次锥心之刑。兰溪生，就是她昨夜下不去手、姥姥亲自动的手。",
         "姥姥 胁迫 害人 兰溪生 精血", {"asks_min": 2, "affinity_min": 10, "act_min": 2}),
    ]),
    ("埋骨之处", "qian", "heavy", ["qian"], [
        ("q_bones1", 1,
         "她的骸骨就埋在后园那株百年白杨之下，无碑的矮坟里。骨在树下一日，她便受制一日。"
         "'若有人肯为我迁骨，葬于清白之地……我做牛做马，来世相报。'",
         "埋骨 白杨 坟 迁骨 骸骨", {"asks_min": 1, "affinity_min": 16, "act_min": 3}),
        ("q_bones2", 2,
         "坟土近来被翻动过——姥姥起过疑心，已经查验过骨殖还在不在。留给你们的时间，比想的更少。",
         "新土 翻动 查验", {"act_min": 3, "location_id": "loc_tomb"}),
    ]),
    ("兰溪生的死", "yan", "medium", ["yan", "qian"], [
        ("l_death1", 1,
         "那不是暴病。脚心的小孔是摄血的针眼，人死时精血已被抽干——这是妖物养魂的手段。"
         "这寺里三年间这样死了四个人，官府都记作'客死'。",
         "兰溪生 死因 针眼 摄血", {"asks_min": 1, "trigger_event_ids": ["e_lan_dead"]}),
    ]),
    ("剑客的来历", "yan", "medium", ["yan"], [
        ("y_sword1", 1,
         "燕赤霞是斩妖的人。剑匣里那口剑饮过妖血，遇妖气自己会鸣。他追着白杨树里那个东西，"
         "从北地一路追到金华，已经三年。",
         "剑匣 斩妖 来历 飞剑", {"asks_min": 2}),
    ]),
    ("姥姥的弱点", "yan", "heavy", ["yan"], [
        ("y_weak1", 1,
         "那东西的本体是白杨树的根柢，惧剑气、惧晨光。要救那女鬼，须趁月圆它现形之夜，"
         "起出骸骨断它的挟制，再以剑气逼它归根——差一步，都是人财两空。",
         "弱点 根柢 晨光 剑气 月圆", {"asks_min": 1, "affinity_min": 12, "act_min": 3}),
    ]),
    ("兰若寺为何荒废", "yan", "light", [], [
        ("t_temple1", 1,
         "断碑上的字迹拼得出个大概：三十年前寺中僧人一夜之间走空，走前在碑上凿了四个字——"
         "'树下勿留'。香火从此断绝。",
         "荒废 断碑 僧人 树下勿留", {"asks_min": 1}),
    ]),
]

# Authored endings — the true one demands BOTH the deed (迁骨) and the stand (护骨).
ENDINGS = [
    {"id": "end_true", "kind": "true", "title": "魂归故里",
     "text": "天将明，你把那只小小的骨坛缚在书箧上，踏出兰若寺的山门。晨光落在坛上，暖得不像话。"
             "风从背后追上来，绕着你转了一圈——像有人提着裙角，快步跟上了你。"
             "此去乡关八百里，你走一路，她跟一路。到了清白之地，你替她立了碑，碑上头一回刻上她的名字："
             "聂小倩。那夜你梦见她福身一拜，鬓边簪着白杨叶，笑着说：来世相报。",
     "condition": {"affinity_min": 20, "act_min": 0,
                   "required_fragment_ids": ["q_bones1"],
                   "required_flags": {"guarded_bones": True}}},
    {"id": "end_normal", "kind": "normal", "title": "一别两宽",
     "text": "你收好行囊，趁天亮离开了兰若寺。账收回来了，命也保住了。只是此后每逢月白之夜，"
             "你总会想起荷池边那条干净的石凳，和那个说话留三分的女子。你没回去过。听说那寺后来塌了。",
     "condition": {"affinity_min": 8, "act_min": 0}},
    {"id": "end_bad", "kind": "bad", "title": "树下勿留",
     "text": "你终究没能把她从那株树底下带走。离寺那日她没有出现，只有满园白杨叶哗哗地响。"
             "多年后你重过金华，寺已塌尽，唯独那株白杨愈发粗壮，枝叶油绿得反常。"
             "树下多了一座新坟，也没有碑。",
     "condition": {"affinity_min": 0, "act_min": 0}},
    # ⚠️ 姥姥的注视爆表（trigger:"pressure"）：你成了下一个兰溪生。
    {"id": "end_drain", "kind": "death", "trigger": "pressure", "title": "针眼",
     "text": "夜里你做了个极暖的梦，梦里有人握着你的脚踝，轻轻地、轻轻地叹了口气。"
             "清晨的兰若寺很安静。东厢的榻上躺着一个面色灰败的书生，脚心一个针眼似的小孔。"
             "账本摊在桌上，最后一笔没有记完。",
     "condition": {"affinity_min": 0, "act_min": 0}},
    # ⏳ 月圆之夜期限（trigger:"clock"）：拖过第四天，姥姥收魂，一切都晚了。
    {"id": "end_moon", "kind": "bad", "trigger": "clock", "title": "月满则亏",
     "text": "第四夜，月亮圆得像一面镜子。你还没来得及做完该做的事，后园的琴声就断了。"
             "从那晚起，兰若寺的夜里再没有提灯的女子。白杨树梢上，苍老的笑声心满意足。"
             "你在她常坐的石凳上放了一盏温酒，酒凉透了，也没有人来。",
     "condition": {"affinity_min": 0, "act_min": 0}},
]

# ⚠️ 危机系统: 姥姥的注视——荒寺的夜里，你的一举一动都有东西在看。
PRESSURE = {
    "name": "姥姥的注视",
    "hint": "收下夜里送来的金子、独自靠近白杨、当众揭破小倩、鲁莽招惹夜里的东西，都会推高；"
            "白日行事、与燕赤霞同行、谨言慎行会回落",
    "ending_id": "end_drain",
    "levels": [
        {"at": 35, "note": "后园的白杨叶响了一阵，明明没有风。"},
        {"at": 65, "note": "夜里你听见极轻的脚步绕着东厢走了一圈，又一圈。"},
        {"at": 90, "note": "你窗台的灰上，多了几个不像人脚的印子——朝里。"},
    ],
}

# ⏳ 时间流动: 第4天就是月圆之夜——迁骨救人，必须赶在它之前。
CLOCK = {"deadline_day": 4, "deadline_text": "月圆之夜", "deadline_ending_id": "end_moon"}

# 📱 纸鹤传书: 小倩折的纸鹤会扑到你窗前——聊斋味的"消息"。
PHONE = {"device": "纸鹤"}


def get_or_create_demo_user(db) -> User:
    u = db.query(User).filter(User.email == DEMO_EMAIL).first()
    if u:
        return u
    from datetime import datetime
    u = User(email=DEMO_EMAIL, password_hash=hash_password(DEMO_PW),
             dob=datetime(1990, 1, 1), accepted_tos=True, display_name="Demo 作者")
    db.add(u)
    db.commit()
    db.refresh(u)
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True,
                   tagline="夜宿荒寺的过客"))
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
            owner_id=user.id,
            title=TITLE,
            one_liner="荒寺借宿的第一夜，有女子提灯敲窗，送来金子与温酒。她无影，而你没钱。",
            synopsis="穷书生宁采臣借宿荒废的兰若寺，夜里遇见提灯的女子聂小倩。她奉命害你，却夜夜下不去手。"
            "金子不能收，温酒不能喝，南院的剑客话里有话，同住的商人一夜暴毙。月圆之夜步步逼近——"
            "要救她，你得让她把最深的秘密托付给你：她的骨，埋在哪里。取材蒲松龄《聊斋志异·聂小倩》。",
            world_long="明末，金华城外的兰若寺。寺庙荒废三十年，殿塔壮丽却蓬蒿没人，僧人一夜走空，只留断碑一句"
            "'树下勿留'。书生宁采臣为收账借宿于此，同住的还有南院剑客燕赤霞、东厢商人兰溪生。"
            "入夜后寺中另有一番人事：荷池畔有提灯的女子，白杨树上有苍老的声音。",
            relations_overview="宁采臣（玩家）与聂小倩是这个故事的心弦：她奉命害他，他见她是人。"
            "燕赤霞是唯一能与姥姥抗衡的力量，但他先要看清这书生值不值得帮。姥姥从不露面，却无处不在。",
            world_facts=(
                "【空间】兰若寺：大殿居中，东厢客房（宁采臣与兰溪生住处）、南院禅房（燕赤霞住处）、"
                "后园荷池由大殿相通；荷池再往北是那株百年白杨与无碑矮坟（去过的人极少）。\n"
                "【昼夜铁律】聂小倩只在夜里出现，白日绝不现身，谁也找不到她；燕赤霞白日在南院，入夜守在大殿。\n"
                "【物件】燕赤霞的剑匣从不离身，遇妖气自鸣；夜里出现在窗台的金子碰不得；"
                "宁采臣身上只有半吊铜钱和一册账本——他是真穷。\n"
                "【禁忌】这个世界的鬼魅妖物是真实存在的，寺中人对'夜里的动静'讳莫如深。"
            ),
            trope_tags=["聊斋", "人鬼恋", "古风", "志怪", "救赎"],
            characters=CHARACTERS,
            acts=ACTS,
            endings=ENDINGS,
            locations=LOCATIONS,
            pressure=PRESSURE,
            clock=CLOCK,
            phone=PHONE,
            visibility="public",
        )
        db.add(story)
        db.flush()

        for title, char_id, sens, known_by, frags in SECRETS:
            sec = Secret(story_id=story.id, character_id=char_id, title=title, sensitivity=sens)
            sec.fragments = [
                Fragment(id=fid, layer=layer, content=content, retrieval_key=rkey,
                         known_by_character_ids=known_by, unlock=unlock)
                for (fid, layer, content, rkey, unlock) in frags
            ]
            db.add(sec)
        db.flush()
        db.refresh(story)

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
        print("   主角=宁采臣。published v1, public.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
