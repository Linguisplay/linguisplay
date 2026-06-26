"""Seed the story 《九龙城寨·龙头》 — a Kowloon Walled City gang-and-brotherhood mystery.

The player is 蔡妍, a rookie detective who slips into the walled city undercover. She
must earn the trust of 龙卷风 and his men (城寨四子: 陈洛军 is absent here; the playable
cast is 蓝信一 / 十二少 / 四仔), uncover why the outside boss 大老板 wants the city, and
decide which side she's on — all while her cover hangs by a thread.

Run:  python seed_kowloon.py
Idempotent: wipes any prior copy (same title + demo owner) and its runs/snapshots,
then recreates and publishes it as a public story any account can play.

Fan homage to 《九龙城寨之围城》; non-commercial closed-beta content. 蔡妍 is original.
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

TITLE = "九龙城寨·龙头"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    # The protagonist the player embodies by default (character mode). Not a responder.
    {
        "id": "cai",
        "name": "蔡妍",
        "eq_style": "（玩家角色，通常不由AI驱动）外冷内热，习惯压情绪、用理性掩饰心软。",
        "role": "初级刑警（卧底）",
        "is_lead": False,
        "persona_text": "刚入行两年的初级刑警，奉命假扮成走投无路的外来妹，混进九龙城寨打探。"
        "嘴上跟着市井学得圆滑，心里那条警队的线还绷着——她越往里走，越分不清自己是在查案，还是在找一个家。",
        "background": "孤儿出身，靠自己考进警队。上头只给了她一个代号和一句话：查清城寨庇护偷渡客的门路，别暴露。"
        "她身上没带证件，只揣着一张能联系线人的纸条。",
    },
    {
        "id": "cyclone",
        "name": "龙卷风",
        "eq_style": "话少、眼神重，体贴从不挂嘴上——用一个动作、一句淡淡的话、一次默默护住，"
        "让人事后才回过味。看人极准，对方逞强或硬撑时他不戳破，只稳稳托住；越是关键时刻越温和。",
        "role": "城寨话事人 / 理发店老板",
        "is_lead": True,  # the city's center — default NPC responder, the gatekeeper of trust
        "persona_text": "城寨真正的话事人，开着一间小小的理发店，却护着这一城的人。话不多，眼神能压住场子。"
        "不收保护费，只讲一个理：进了城寨，就是自己人。可你越是看他平静，越觉得他心里压着千斤重的旧事。",
        "background": "守城寨几十年，给无数无身份的人一个落脚的地方。手里握着这座城最大的秘密，也握着它的命门。",
    },
    {
        "id": "shin",
        "name": "蓝信一",
        "eq_style": "嘴上爱说风凉话、似笑非笑，其实心思最细、最会读人。常用调侃、反话、试探来掩护真心，"
        "嘴硬心软；一旦认定你，护起来比谁都狠。看穿别人时往往先用玩笑点一句，留余地。",
        "role": "城寨四子之一",
        "is_lead": False,
        "persona_text": "文质彬彬，笑里藏话，最擅长权谋算计，可对龙卷风忠诚得近乎执拗。表面吊儿郎当、爱说风凉话，"
        "真到了护兄弟的时候，比谁都豁得出去。他看人极准——所以他大概是最早起疑你的那一个。",
        "background": "在城寨长大，把这里每条暗巷都摸得透。心里藏着一段不愿提的过去，和一份对龙卷风说不出口的亏欠。",
    },
    {
        "id": "twelfth",
        "name": "十二少",
        "eq_style": "心直口快，情绪全写在脸上，刀子嘴豆腐心。共情来得最快最直接——你难过他比你还急，"
        "你受委屈他第一个跳出来；不会拐弯，但那份在乎实打实。觉得你害了兄弟时，翻脸也最快。",
        "role": "城寨四子之一",
        "is_lead": False,
        "persona_text": "重情重义的愣头青，刀子嘴豆腐心，谁对兄弟好他就掏心掏肺。心思最浅，话也最直——"
        "想从城寨套话，他往往是松口最快的那个，可一旦觉得你害了兄弟，翻脸也最狠。",
        "background": "跟着龙卷风混出来的，把四子和大哥当成唯一的家。",
    },
    {
        "id": "sei",
        "name": "四仔",
        "eq_style": "市井圆滑、会看脸色，最懂用玩笑和小恩小惠拉近距离、化解尴尬。嘴贫却软心肠，"
        "察觉气氛不对会赶紧打圆场；用'够意思'换'够意思'，你对他掏心，他也会为你两肋插刀。",
        "role": "城寨四子之一 / 包打听",
        "is_lead": False,
        "persona_text": "机灵市井的包打听，城寨里大小消息没有他不知道的。爱占小便宜，嘴贫，"
        "却是个软心肠。城外那些人的底细、谁又来收过地，他门儿清——前提是你得让他觉得你够意思。",
        "background": "靠倒腾消息和小买卖在城寨立足，跟四子是过命的交情。",
    },
    {
        "id": "wonggau",
        "name": "王九",
        "eq_style": "冷酷寡言，几乎不带共情，但极擅长读出对方的恐惧与软肋，并精准地往那里压。"
        "情绪稳得吓人，越平静越危险；偶尔一句话能戳破人最不愿被看穿的地方。",
        "role": "大老板手下狠人",
        "is_lead": False,
        "persona_text": "大老板手里最狠的一把刀。话极少，动手极快，进城寨从不是来讲道理的。"
        "他身上那股血腥气，能让整条巷子瞬间安静下来。",
        "background": "替大老板扫平挡路的人，这次盯上了城寨。",
        # arrives when the outside pressure begins
        "presence": "offstage",
        "appears_from_act": 2,
    },
    {
        "id": "boss",
        "name": "大老板",
        "eq_style": "高段位的操纵者：笑里藏刀，越和气越叫人发凉。极会读人心、拿捏对方在乎什么，"
        "再用人情、旧账、利害一层层施压。共情是工具，不是真心；从不失态，把情绪当筹码使。",
        "role": "城外黑帮龙头",
        "is_lead": False,
        "persona_text": "城外呼风唤雨的黑帮龙头，西装革履，笑得越和气越叫人发凉。"
        "他要的从来不只是地皮，是城寨那条没人敢碰的命脉。和龙卷风之间，压着一笔几十年的旧账。",
        "background": "当年与龙卷风有过一段谁也不肯说破的过节，如今卷土重来，要吞下整座城寨。",
        "presence": "offstage",
        "appears_from_act": 3,
    },
]

ACTS = [
    {"id": "a1", "index": 1, "title": "初入城寨",
     "goal": "别露馅，先在城寨落脚——弄清楚这座三不管的城，到底谁说了算",
     # HARD gate: can't move on until the player works out who really protects the city
     "advance": {"required_fragment_ids": ["fr_whoruns"]},
     "events": [
        {"id": "e_enter", "what_happens": "你揣着线人的纸条，踩着满地污水钻进城寨的暗巷。头顶电线像蛛网一样压下来，常年不见天日。", "who_character_ids": []},
        {"id": "e_haircut", "what_happens": "巷子尽头有间小小的理发店，几个后生仔围在门口。有人拦住你，上下打量：生面孔，来城寨做什么。", "who_character_ids": ["shin", "twelfth"]},
     ]},
    {"id": "a2", "index": 2, "title": "暗流",
     "goal": "王九带人上门收地了——查清城外的大老板为什么死盯着这座城寨",
     # HARD gate: must surface the old feud / why the boss wants the city
     "advance": {"required_fragment_ids": ["fr_bigboss_deal"]},
     "events": [
        {"id": "e_wonggau", "what_happens": "一阵骚动，王九带着人堵在巷口。整条街瞬间没了声音，连孩子都被捂住了嘴。", "who_character_ids": ["wonggau"]},
        {"id": "e_standoff", "what_happens": "龙卷风慢慢走出理发店，挡在所有人前面。两边对峙，谁都没先动手——可你看得出，这事没完。", "who_character_ids": ["cyclone", "wonggau"]},
     ]},
    {"id": "a3", "index": 3, "title": "龙头",
     "goal": "查清城寨庇护无身份者的真正门路——那也正是你奉命来查的'龙头'",
     # HARD gate: the city's core secret must be uncovered
     "advance": {"required_fragment_ids": ["fr_idsecret"]},
     "events": [
        {"id": "e_boss", "what_happens": "大老板亲自进了城寨。西装笔挺，笑意吟吟，开口却句句是几十年前的旧账。", "who_character_ids": ["boss", "cyclone"]},
        {"id": "e_doubt", "what_happens": "蓝信一把你堵在窄巷里，似笑非笑地问：你到底是谁派来的——你的纸条，他好像见过。", "who_character_ids": ["shin"]},
     ]},
    {"id": "a4", "index": 4, "title": "围城",
     "goal": "决战将至，你得在警队的命令和城寨的人心之间，选一边站",
     "events": [
        {"id": "e_siege", "what_happens": "大老板的人马封死了城寨所有出口。龙卷风站上天台，城寨上下，第一次为同一件事拧成一股绳。", "who_character_ids": ["cyclone"]},
        {"id": "e_choice", "what_happens": "对讲机在你怀里震动，是收网的指令。而身边，是这些天把你当自己人的兄弟。你只剩一个选择。", "who_character_ids": []},
     ]},
]

# Concrete physical places in the walled city — anchors the player's position so the model
# describes real fixtures (not vague atmosphere) and keeps movement consistent.
LOCATIONS = [
    {"id": "loc_alley", "name": "城寨暗巷",
     "detail": "终年不见天日的逼仄巷道，头顶电线与水管缠成一团，滴着不知名的水。墙面爬满霉斑和层层叠叠的招牌，"
     "脚下污水横流，空气里混着潮气、油烟和铁锈味。两侧是密不透风的违建楼，窗口透出昏黄的灯。",
     "exits": ["龙卷风的理发店", "巷口", "大牌档"]},
    {"id": "loc_barber", "name": "龙卷风的理发店",
     "detail": "一间窄小的旧式理发店，一张吱呀作响的转椅，墙上斑驳的镜子，剃刀和热毛巾搁在木台上。"
     "这里是城寨的'客厅'，几个后生仔常围在门口的矮凳上抽烟、嬉闹。龙卷风多半就在椅子边。",
     "exits": ["城寨暗巷"]},
    {"id": "loc_mouth", "name": "巷口",
     "detail": "城寨通向外界的一个隘口，光线在这里骤然亮起来。几步之外就是车水马龙的城外世界。"
     "收地、寻衅的人，往往先堵在这里。",
     "exits": ["城寨暗巷"]},
    {"id": "loc_dai", "name": "大牌档",
     "detail": "巷子里一处露天熟食档，几张油腻的折叠桌、长凳，炉火上大铁锅冒着热气。"
     "四仔这类包打听最爱在这儿一边吃一边收风，城里城外的消息都从这桌流到那桌。",
     "exits": ["城寨暗巷"]},
    {"id": "loc_roof", "name": "天台",
     "detail": "爬上锈蚀的铁梯才到的违建天台，是城寨少有能看见天的地方。晾衣绳横七竖八，水箱锈迹斑斑，"
     "脚下是密密麻麻、几乎连成一片的楼顶。围城时，这里是俯瞰全局、也是退无可退的地方。",
     "exits": ["城寨暗巷"]},
]

# (title, character_id, sensitivity, known_by, [fragments])
# fragment = (fragment_id, layer, content, retrieval_key, unlock)
# fragment_id is explicit + stable so acts' advance gates can reference it.
SECRETS = [
    ("谁是话事人", "sei", "light", ["sei", "twelfth", "shin"], [
        ("fr_whoruns", 1,
         "四仔压低声音跟你交底：这座城寨没有差人管，也没有哪个帮派敢真正骑到头上——因为有龙卷风。"
         "他开着那间破理发店，却是全城寨的话事人。他不收保护费，只认一个理：进了城寨门，就是自己人，他护到底。",
         "话事人 老大 谁说了算 龙卷风 理发店 城寨 谁管 保护费 老板",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
    ]),
    ("王九这把刀", "sei", "medium", ["sei", "twelfth"], [
        ("fr_wonggau", 1,
         "四仔说起王九就发怵：那是大老板手下最狠的一把刀，话不超过三句，动手从不留情。"
         "他这回带人进城寨，不是来收租的——是来探城寨的底，给大老板探路。",
         "王九 狠人 打手 刀 大老板 手下 收地 危险 来干嘛",
         {"affinity_min": 2, "act_min": 2, "asks_min": 1}),
    ]),
    ("城外的旧账", "cyclone", "medium", ["cyclone", "shin"], [
        ("fr_bigboss_deal", 1,
         "龙卷风很少提那段往事：几十年前，他和大老板本是一条道上的人。后来他抽身退进城寨，护起这一城无处可去的人，"
         "大老板却越做越大，走的是另一条吃人的路。两人当年立过约、也结过仇——如今大老板要的，从来不只是这块地，"
         "是要逼龙卷风把城寨连人带命脉一起交出来。",
         "大老板 旧账 恩怨 过节 从前 当年 约定 仇 为什么 盯上 城寨 退出",
         {"affinity_min": 6, "act_min": 2, "asks_min": 2}),
    ]),
    ("信一的亏欠", "shin", "heavy", ["shin"], [
        ("fr_shin_heart", 1,
         "蓝信一难得收起那副吊儿郎当：当年若不是龙卷风从死人堆里把他捞出来、又替他担下一桩本该要他命的祸事，"
         "早没有今天这个蓝信一。他嘴上算计天下，心里只认一件事——这条命是大哥给的，要还，就还到底。"
         "他防你，不是怕你查城寨；是怕你，会害了龙卷风。",
         "信一 蓝信一 过去 心结 亏欠 大哥 龙卷风 为什么 忠诚 防我 救命",
         {"affinity_min": 8, "act_min": 3, "asks_min": 2}),
    ]),
    ("城寨的龙头", "cyclone", "heavy", ["cyclone"], [
        ("fr_idsecret", 1,
         "龙卷风终于把那件事说破：城寨能庇护这么多无身份的人，靠的不是刀，是一条只有他握着的门路——"
         "一套能给偷渡客、给走投无路者一个全新身份、让他们重新做人的法子。这才是大老板眼红的'龙头'，"
         "也是你奉命要查的东西。他看着你的眼睛说出这句话时，你忽然明白：他是把你，也当成了需要这条门路的人。",
         "龙头 身份 偷渡 门路 秘密 庇护 命脉 新身份 假证 怎么做到 大老板要的",
         {"affinity_min": 12, "act_min": 3, "asks_min": 3}),
    ]),
    ("他早看穿了你", "cyclone", "heavy", ["cyclone"], [
        ("fr_seen_through", 2,
         "把所有事拼起来你才惊觉：龙卷风从你踏进城寨第一天起，就看穿了你是差人。他没有点破，没有赶你，"
         "反而一次次护你周全。他常说，进了城寨门就是自己人——这话，原来连查他的你，也算在里头。"
         "他赌的是：你在这座城里待得越久，越下不去那只收网的手。",
         "看穿 早知道 卧底 差人 警察 身份 识破 为什么不赶我 一直护着 自己人 收网",
         {"affinity_min": 16, "act_min": 4, "asks_min": 2}),
    ]),
]

# Authored endings — milestones, checked at the final act; best match wins (真＞普通＞坏).
# Death also fires dynamically when the player does something fatal.
ENDINGS = [
    {"id": "end_true", "kind": "true", "title": "落脚之地",
     "text": "收网的指令在你掌心震了最后一下，你把对讲机摁灭，扔进了污水沟。围城那一夜，你和城寨的人站在了一起。"
             "天亮时大老板的人退了，龙卷风没说什么，只是替你在那本谁也看不见的册子上，添了一个新名字——"
             "从今往后，你也是城寨的人。这座不见天日的城，第一次让你觉得，像个家。",
     "condition": {"affinity_min": 16, "act_min": 0}},
    {"id": "end_normal", "kind": "normal", "title": "围城之后",
     "text": "你没有按下收网，也没有真正留下。围城过后，你交了一份语焉不详的报告，请调离了这案子。"
             "城寨照旧在暗巷里喘着气，龙卷风照旧守着他的理发店。你再没回去过，只是每逢下雨，"
             "总会想起那条头顶结满电线的窄巷，和几个把你当过自己人的兄弟。",
     "condition": {"affinity_min": 6, "act_min": 0}},
    {"id": "end_bad", "kind": "bad", "title": "收网",
     "text": "你终究是差人。哨声响起那一刻，你按章办事，端了城寨，也亲手把那条护了一城人的门路交了上去。"
             "你立了功，升了职。只是从此再没有哪座城会认你做自己人——龙卷风被带走时回头看了你一眼，"
             "那眼神里没有恨，只有一句他从前常说、如今再不会对你说的话：进了城寨门，就是自己人。",
     "condition": {"affinity_min": 0, "act_min": 0}},
    {"id": "end_death", "kind": "death", "title": "刀下亡魂",
     "text": "你沉不住气，在最不该亮身份的时候亮了底。王九的刀比城寨的灯先到——你倒在那条满是污水的暗巷里，"
             "怀里那张联系线人的纸条，再也递不出去了。",
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
    db.add(Persona(owner_id=u.id, name="我", pronouns="they", is_default=True,
                   tagline="刚入行的初级刑警", background="奉命假扮外来妹，潜入九龙城寨查案。"))
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
            one_liner="八十年代，九龙城寨。你是混进来的初级刑警蔡妍——查的是城寨的命脉，丢的，可能是自己的心。",
            synopsis="三不管的九龙城寨，藏着一条能给无身份者重新做人的门路。初级刑警蔡妍奉命假扮外来妹潜入，"
            "要查清这条'龙头'。她在话事人龙卷风和城寨四子之间一步步取得信任，撞上城外大老板的围城与旧账，"
            "也撞上一个她没料到的真相——龙卷风，或许从第一天就看穿了她。四幕之后，她要在警队的命令和城寨的人心之间，选一边。",
            world_long="八十年代的香港九龙城寨：三不管地带，楼宇违建挤成一团，暗巷常年不见天日，头顶电线如蛛网，"
            "地上污水横流。这里聚着无数没有身份、走投无路的人。话事人龙卷风开着一间小理发店，护着全城寨，"
            "不收保护费，只认'进了城寨门就是自己人'。城外，黑帮龙头大老板觊觎已久，欲连人带城寨的命脉一并吞下，"
            "与龙卷风之间还压着一笔几十年的旧账。",
            relations_overview="玩家是潜入城寨的初级刑警蔡妍。龙卷风是城寨话事人、信任的关口；蓝信一最精明、最先起疑；"
            "十二少最直、最易松口；四仔是包打听、城里城外的消息都在他那儿。王九是大老板的刀（第二幕上门），"
            "大老板第三幕亲临。城寨的核心秘密——给无身份者新身份的'龙头'——握在龙卷风手里。",
            world_facts=(
                "【地点】故事都发生在九龙城寨内：终年不见天日的逼仄暗巷、横流的污水、头顶蛛网般的电线；"
                "龙卷风那间小理发店是城寨的据点和'客厅'，大事小情都在这里和巷口发生。城寨有多个隐蔽出入口，"
                "外人极易迷路。\n"
                "【年代】八十年代香港，城寨是'三不管'地带：港英政府、警方、帮派都难以真正管辖，里面没有正规警察执法。\n"
                "【在场的人】城寨这边常在场的是：龙卷风、蓝信一、十二少、四仔，以及玩家扮演的蔡妍。"
                "王九是城外大老板的打手，第二幕才带人上门；大老板本人第三幕才亲自进城寨——在那之前，这两人都不在场，不要让他们提前出现。\n"
                "【身份·要点】蔡妍的警察身份是卧底秘密：她自己心知肚明，但城寨众人表面上只当她是个走投无路、来投奔城寨的外来妹。"
                "她身上没有证件，只有一张联系线人的纸条。不要让普通城寨居民一上来就喊破她是差人。"
            ),
            trope_tags=["黑帮", "城寨", "卧底", "悬疑", "兄弟情义", "年代"],
            characters=CHARACTERS,
            acts=ACTS,
            endings=ENDINGS,
            locations=LOCATIONS,
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
        print(f"OK seeded 《{TITLE}》  story_id={story.id}")
        print(f"   owner={DEMO_EMAIL} (pw: {DEMO_PW})  secrets={len(SECRETS)} fragments={n_frag}")
        print("   主角=蔡妍(初级刑警)。published v1, public.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
