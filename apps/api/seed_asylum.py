# -*- coding: utf-8 -*-
"""Seed 《寂声疗养院》 — asylum-escape survival horror SANDBOX (致敬《逃生》一路的
精神病院题材，人物与设定均为原创). 无尽长夜：巡夜人循声而猎，身体会真的死，
秘密一层层撬，世界随玩家生长。Deletes any prior copy, recreates, publishes public."""

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

TITLE = "寂声疗养院"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

SANDBOX = {
    "enabled": True,
    "real_time": True,
    # 疗养院的硬通货是香烟——病人之间、病人和护工之间，都认这个
    "currency": "香烟",
    "start_money": 6,
    "progression": {
        "name": "夜行造诣",
        "ranks": ["生面孔", "摸黑客", "夜行者", "通楼人", "掌钥者", "无声者"],
    },
}

# 🦇 铁松是账本，不是氛围：引擎跟踪他的位置与警觉，噪音/光把他招来，
# 抓到按阶梯付账（请回→打伤→濒死）。文案只负责演，规则由程序执行。
THREAT = {
    "char_id": "ay_tie",
    "senses": ["sound", "light"],
    "patrol": ["loc_corridor", "loc_ward", "loc_shower", "loc_station"],
    "cannot_enter": ["loc_power"],   # 检修井他钻不进去——也想不到有人敢钻
    "return_to": "loc_ward",
    "ladder": ["return", "hurt", "dying"],
    "cues": {
        "far": [
            "很远的地方，一扇铁门被轻轻带上。声音顺着走廊爬了很久，才散。",
            "楼体深处传来一声闷响，像什么很沉的东西，放上了推车。",
        ],
        "near": [
            "隔壁传来极轻的、布料蹭过墙面的声音。然后，是三秒钟完完整整的静。",
            "门外那格应急灯暗了一瞬——有什么很大的东西从灯下走过，没有脚步声。",
            "钥匙没有响。但你就是知道，那一圈缠了布的钥匙，刚从门外过去。",
        ],
        "here": [
            "白围裙的下摆先进的门。他站在光照不到的那一半，像一件立着的家具。",
            "消毒水底下那股旧棉被的味道忽然浓了——他就在这个房间里。",
            "他停在门口，头微微偏着，像在听。听你。",
        ],
    },
}

# ⚠️ 楼的警觉：奔跑、砸撬、喊叫、直照的手电都在喂它；爆表=被「收治」成14床
PRESSURE = {
    "name": "楼的警觉",
    "hint": "这栋楼靠声音记账。你每弄出一次动静，它就多记你一笔。",
    "ending_id": "end_committed",
    "levels": [
        {"at": 30, "note": "巡夜的脚步在这一层停留得比平时久了。"},
        {"at": 60, "note": "走廊尽头的应急灯下，多了一把椅子。有人整夜坐在那里。"},
        {"at": 85, "note": "广播响了两声，没有说话。全楼都在听你。"},
    ],
}

ENDINGS = [
    {"id": "end_committed", "kind": "bad", "trigger": "pressure", "title": "14床",
     "text": "没有审讯，没有争执。两个白大褂在文书上写下你的名字时，语气温和得像在安排住宿。"
     "「记者同志，你需要休息。」13床旁边那张空床，原来一直是留给你的。"
     "从今夜起，你的每一句话，都是病历上的一行症状。"},
]

# 🚪 预定命运：名单上的下一个圈是阿枝。第3夜，太平间的电梯会上来——
# 除非玩家已知道名单（fr_lab1）且赢得她的信任（她才肯听你的话躲起来）。
DOOMS = [
    {"id": "doom_zhi", "day": 3, "char_id": "ay_zhi", "to": "loc_lab",
     "warn_text": "阿枝今晚的童谣只有一句，翻来覆去：「小石子，数到三，数到三就搬新家～」"
     "她冲你笑，笑得像在告别。",
     "text": "后半夜，太平间的电梯上来过一次。再经过淋浴间时，里面静得发白——"
     "喷头还在滴水，第三排地漏边，小石子摆成整整齐齐的一排。阿枝不在了。"
     "没有人提这件事，连温以宁都只是把台面又擦了一遍。",
     "prevented_text": "后半夜，太平间的电梯上来过一次，停了很久。但淋浴间是空的——"
     "阿枝听了你的话，蜷在你说的那个地方，把嘴捂住，一夜没有唱歌。"
     "天亮前她摸回来，往你手里塞了一颗小石子。",
     "prevent": {"fragment_ids": ["fr_lab1"], "closeness_min": 12}},
]

CHARACTERS = [
    # 玩家角色：夜探的自由记者
    {
        "id": "ay_shen",
        "playable": True,
        "name": "沈默",
        "items": [{"name": "录音笔",
                   "detail": "巴掌大的旧录音笔，电量过半。你进来就是为了让它装满东西再出去。"},
                  {"name": "旧手电",
                   "detail": "光圈发黄的手电。光能照亮路，也能把你自己照给别人看。"}],
        "agenda": "（玩家角色）拿到疗养院深夜转运病人的证据，活着出去。"
        "现在门锁死了，手机没信号，这栋楼成了你的整个世界。",
        "eq_style": "（玩家角色，通常不由AI驱动）胆子在笔杆上，不在腿上。怕，但更怕空手回去。",
        "role": "自由记者（夜探）",
        "is_lead": False,
        "persona_text": "跑社会线的自由记者。收到匿名线报说寂声疗养院深夜往山里运人，"
        "翻墙进来想拍点东西——结果身后的铁门自己合上了。",
        "background": "线人只给了一句话：三楼病房区，找一个住了十一年还清醒的人。"
        "别用手电直照走廊尽头，巡夜的那个大个子，怕光更恨光。",
    },
    # 主线人物：清醒装疯的老病人
    {
        "id": "ay_lu",
        "name": "陆九秋",
        "is_lead": True,
        "home_location_id": "loc_ward",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend"],
        "ties": [{"char_id": "ay_zhi", "stance": 2, "label": "护着她像护妹妹"},
                 {"char_id": "ay_wen", "stance": 1, "label": "十一年里唯一没打过他的白大褂"},
                 {"char_id": "ay_tie", "stance": -2, "label": "躲了十一年的人"}],
        "bio_layers": [
            {"closeness_min": 0, "text": "三楼住得最久的病人，十一年。别人疯得吵，他疯得安静——"
             "总在窗边下一盘没有对手的棋。"},
            {"closeness_min": 18, "text": "他的病历上写着'偏执型'，可他记得这栋楼每一把锁的位置，"
             "记得每个消失病人的床号。疯子记不住这些。"},
            {"closeness_min": 40, "text": "十一年前他不是被送进来的，是被'请'进来的。他知道自己为什么"
             "出不去——因为外面有人需要他永远是个疯子。"},
        ],
        "agenda": "等一个能把话带出去的人，等了十一年。他要先确认你不是院方钓他的饵。",
        "eq_style": "装疯装了十一年，情绪全收在棋子底下。他试探人从不发问，只把话说一半，"
        "看你接哪一半。认了你，声音会低下来，快而准，像下快棋。",
        "role": "三楼老病人 / 十一年",
        "persona_text": "瘦，白发剃得极短，指节上全是老茧。说话轻，眼神不轻。"
        "在外人面前会突然对空气说话——那是演的，演给摄像头看。",
        "examples": ["别看镜头。走廊第三格灯下面那个，看得见你。",
                     "十一年了。你是第一个问我名字、不问我病的。",
                     "想活得久就记住：这栋楼里，安静比跑得快有用。"],
    },
    # 值夜护士：良心未泯的共犯
    {
        "id": "ay_wen",
        "name": "温以宁",
        "home_location_id": "loc_station",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend"],
        "bio_layers": [
            {"closeness_min": 0, "text": "值夜护士，白大褂洗得发灰。给病人扎针时手很稳，"
             "眼睛却从不看床头的名字。"},
            {"closeness_min": 18, "text": "她抽屉里锁着一沓没寄出去的辞职信，最早的一封写于三年前。"},
            {"closeness_min": 40, "text": "夜里搬走的每一个病人，交接单上都要她签字。她签了三年，"
             "每一笔都像签在自己身上。"},
        ],
        "agenda": "熬到天亮、按点交班、什么都别看见——这套她演了三年。你闯进来，"
        "把她演不下去的那部分撞碎了。",
        "eq_style": "职业性的平静，语速稳，句子短。心虚时会去整理已经很整齐的东西。"
        "被戳中良心时先沉默，再用'按规定'开头说话——那是她最后的盾。",
        "role": "值夜护士",
        "persona_text": "二十七八岁，眼下乌青。护士站永远收拾得一尘不染，"
        "像在替什么脏东西打扫。",
        "examples": ["三楼夜里不许开手电。这是为你好。",
                     "我只负责发药。别的事，我下班了。",
                     "……你要是真能把它带出去，别写我的名字。写13床的。"],
    },
    # 疯癫的女病人：童谣里全是线索
    {
        "id": "ay_zhi",
        "name": "阿枝",
        "home_location_id": "loc_shower",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend"],
        "bio_layers": [
            {"closeness_min": 0, "text": "总蹲在淋浴间数地砖的女病人，唱走调的童谣，见人就笑。"},
            {"closeness_min": 15, "text": "她的童谣没有一首是现成的，词都是她自己的——"
             "「铁腰带，冷抽屉，钥匙睡在肚皮上」。听懂的人不多。"},
            {"closeness_min": 35, "text": "她原是院里的清洁工，撞见了不该看的，第二天就成了病人。"
             "疯是她的壳：疯子说什么都没人信，所以疯子什么都敢说。"},
        ],
        "agenda": "用童谣把她看见的一切唱给每一个新面孔听——总有一天有人会听懂。",
        "eq_style": "语调像哄小孩，内容像剃刀。你对她凶，她唱得更大声；你蹲下来跟她平视，"
        "她会突然清醒两秒，用完全正常的声音说一句话，然后继续疯。",
        "role": "女病人 / 前清洁工",
        "persona_text": "三十来岁，头发用皮筋胡乱扎着，手腕上有旧约束带的勒痕。"
        "口袋里全是数来的小石子。",
        "examples": ["白褂子，夜里忙，十三床，搬下床，搬到楼下变冰棒～",
                     "（突然凑近，声音正常）今晚别走楼梯间。（又笑起来）小石子，一二三……",
                     "铁腰带，冷抽屉，钥匙睡在肚皮上～"],
    },
    # 巡夜人：这栋楼的恐怖本体
    {
        "id": "ay_tie",
        "name": "铁松",
        "home_location_id": "loc_corridor",
        "relation_default": "stranger",
        "relation_allowed": ["stranger"],
        "bio_layers": [
            {"closeness_min": 0, "text": "巡夜的护工。两米出头，白围裙上有洗不掉的暗色印子。"
             "走路几乎没有声音——这么大的人，没有声音。"},
        ],
        "agenda": "楼里不许有'不该动的东西'在动。他分辨的方式很简单：光，和声音。"
        "对弄出动静的东西，他会先'请'回病房；再犯，就不请了。",
        "eq_style": "几乎不说话。开口只有短句，气音，像从很深的地方漏出来。"
        "他不追赶，他等——等你自己弄出声音。",
        "role": "巡夜护工",
        "persona_text": "没人知道他的全名。病人背后叫他'铁腰带'——他腰上那一圈钥匙，"
        "走动时却从不作响，因为每一把都用布缠过了。",
        "examples": ["……谁开的灯。", "三楼，睡觉。", "（停在门外，很久，一句）我闻得到电池的味道。"],
    },
    # 幕后：院长，住在楼的最深处
    {
        "id": "ay_he",
        "name": "贺院长",
        "home_location_id": "loc_lab",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer"],
        "bio_layers": [
            {"closeness_min": 0, "text": "院长。楼里人提到他不用名字，只压低声音说'楼下那位'。"},
        ],
        "agenda": "「寂声计划」到了收尾的批次。任何变量都不许走出这道山门——"
        "但比起灭口，他更喜欢'收治'：多一份病历，少一桩麻烦。",
        "eq_style": "温和得过分，句句像医嘱。他不威胁人，他'安排'人。",
        "role": "院长",
        "persona_text": "五十多岁，金丝眼镜，白大褂永远笔挺。嗓音是全楼最柔和的，"
        "广播里响起时，连疯子都会安静。",
        "examples": ["三楼的客人，夜里凉，回病房去吧。给你留了床，13号。",
                     "记者同志，你要的'真相'，我们这里叫'疗程'。"],
    },
]

# 沙盒：单幕无尽。目标是玩家自己立的——活下去、挖真相、攒本事、找到出去的路。
ACTS = [
    {"id": "a1", "index": 1, "title": "无尽长夜", "time": {"day": 1, "slot": "夜"},
     "goal": "活下去。弄清这栋楼夜里在做什么，攒够走出去的本事——或者，成为它的一部分",
     "advance": {"required_fragment_ids": [], "affinity_min": 0},
     "events": [
        {"id": "e_lockdown", "what_happens": "你翻进三楼病房区的当口，身后的防火铁门'咔'地自锁。"
         "走廊灯次第熄灭，只剩尽头一格惨白的应急灯。手机没有信号。", "who_character_ids": []},
        {"id": "e_drag", "what_happens": "走廊深处传来拖拽声，像有人拖着一只很沉的袋子走过。"
         "声音停了一下——又继续，慢慢远了。淋浴间方向，有人在小声唱歌。", "who_character_ids": ["ay_zhi"]},
     ]},
]

LOCATIONS = [
    {"id": "loc_ward", "name": "三楼病房区",
     "detail": "长走廊两侧是一间间病房，绿漆铁门，观察窗蒙着雾。应急灯隔一段亮一格，"
     "灯与灯之间是整段整段的黑。消毒水味下面压着一股更旧的味道，像潮了很多年的棉被。",
     "exits": ["三楼走廊", "护士站", "淋浴间"]},
    {"id": "loc_corridor", "name": "三楼走廊",
     "detail": "病房区通向楼梯间的过道，是铁松巡夜的必经之路。他在每扇门外停三秒。"
     "地面有一道长年拖拽留下的浅痕，一直延伸到电梯口。",
     "exits": ["三楼病房区", "护士站"]},
    {"id": "loc_station", "name": "护士站",
     "detail": "一圈矮柜台围出的小隔间，台面擦得能照出人影。排班表钉在软木板上，"
     "药柜上着锁，抽屉最下面一格的锁是新换的。交接窗后面藏着一条送饭的矮道。",
     "exits": ["三楼病房区", "三楼走廊", "档案室"]},
    {"id": "loc_shower", "name": "淋浴间",
     "detail": "白瓷砖从地面贴到顶，缝隙发黄。七八个喷头一字排开，有一个在滴水，"
     "滴了不知道多少年。最里侧的通风口格栅松了一角。阿枝常蹲在第三排地漏边数石子。",
     "exits": ["三楼病房区"],
     "props": [{"id": "p_vent", "name": "通风口格栅",
                "detail": "格栅螺丝锈死了大半，松的那角能塞进一只手。里面有风，风是往下走的。",
                "fragment_id": "fr_route1"}]},
    {"id": "loc_files", "name": "档案室",
     "detail": "顶天立地的铁皮档案柜，标签从'1979'排到今年。空气里全是纸霉味。"
     "最里排的柜子有一整列没有标签，锁孔发亮——常有人开。",
     "exits": ["护士站"],
     "unlock": {"required_fragment_ids": ["fr_ward2"]},
     "props": [{"id": "p_files", "name": "无标签档案柜",
                "detail": "撬开的柜门里是一摞牛皮纸袋，每袋一个床号。13床那袋最厚，"
                "袋口的火漆是今晚新封的。", "fragment_id": "fr_lab1"}]},
    {"id": "loc_morgue", "name": "太平间",
     "detail": "地下一层尽头。铁皮冷柜三排，压缩机嗡嗡响，一格柜门没关严，漏着白气。"
     "值班桌上有登记本和半杯凉透的茶——值班的人刚走，或者，没能走。",
     "exits": ["配电井"],
     "unlock": {"required_fragment_ids": ["fr_key2"]},
     "props": [{"id": "p_belt", "name": "值班室挂钩上的布卷",
                "detail": "一卷缠钥匙用的软布，和一枚没来得及缠上的黄铜钥匙——"
                "齿口很新，柄上錾着'后山'两个字。", "take": True}]},
    {"id": "loc_power", "name": "配电井",
     "detail": "顺着通风管爬下来的检修井，管线密得像藤。总闸箱贴着褪色的红字：断闸前通知楼下。"
     "'楼下'两个字被人用指甲划掉了。",
     "exits": ["太平间", "地下三层"],
     "unlock": {"required_fragment_ids": ["fr_route1"]}},
    {"id": "loc_lab", "name": "地下三层",
     "detail": "这一层不在消防图上。走廊两侧是带观察窗的隔音室，墙面钉满吸音棉，"
     "厚得吞掉你自己的脚步声。尽头手术灯亮着，照着一张空的约束床，束带还是热的。",
     "exits": ["配电井", "后山铁门"],
     "unlock": {"required_fragment_ids": ["fr_lab1"]},
     "props": [{"id": "p_log", "name": "手术灯下的实验日志",
                "detail": "硬壳日志摊在推车上，最新一页的墨迹未干：「寂声计划·第41例。"
                "听觉剥夺满96小时，受试者停止呼救。结论：安静，是可以制造的。」",
                "fragment_id": "fr_lab2"}]},
    {"id": "loc_gate", "name": "后山铁门",
     "detail": "疗养院围墙最深处的一道锈铁门，门外是黑压压的山林和一条下山的土路。"
     "锁是从里面上的——修锁的人，大概也想过要走。",
     "exits": ["地下三层"],
     "unlock": {"required_fragment_ids": ["fr_exit1"]}},
]

COVERS = {}

SECRETS = [
    ("夜里搬走的人", "ay_lu", "medium", ["ay_lu", "ay_wen", "ay_zhi"], [
        ("fr_ward1", 1,
         "陆九秋落下一枚棋子，声音压得极低：这层楼夜里锁死，不是防你们进来，是防里面的人'被看见出去'。"
         "上个月13床还在，如今床铺得比谁都平整。",
         "为什么锁 锁门 搬人 拖拽声 13床 十三床 消失 少了人 夜里 出去的人",
         {"affinity_min": 0, "asks_min": 1}),
        ("fr_ward2", 2,
         "他把棋盘一推：每隔九天，后半夜，太平间的电梯会上来一次。名单是楼下那位亲自画的圈，"
         "白大褂签字，铁腰带动手。你要找证据，别在三楼找——档案室里每个床号一袋，楼下才有'结果'。",
         "电梯 太平间 名单 谁定的 院长 楼下 证据 在哪 结果 九天 档案",
         {"affinity_min": 2, "asks_min": 2}),
    ]),
    ("往下的风", "ay_zhi", "light", ["ay_zhi", "ay_lu"], [
        ("fr_route1", 1,
         "淋浴间最里侧的通风口格栅松了一角，里面的风是往下走的——顺着风管爬下去，"
         "是一口检修配电井。这条路铁松钻不进去，也从来想不到有人敢钻。",
         "通风口 格栅 风管 往下 爬下去 配电 检修 怎么下楼 别的路",
         {"affinity_min": 0, "asks_min": 0, "location_id": "loc_shower"}),
    ]),
    ("钥匙睡在哪", "ay_zhi", "light", ["ay_zhi", "ay_lu"], [
        ("fr_key1", 1,
         "阿枝把童谣唱到第三遍，忽然用正常的声音说：铁腰带的钥匙每一把都缠了布，你听不见的。"
         "但他有一把从不带在身上——太平间值班室，挂钩上，肚皮那么高的地方。（又笑起来）小石子，四五六。",
         "钥匙 铁腰带 童谣 什么意思 肚皮 冷抽屉 怎么拿 挂哪 太平间",
         {"affinity_min": 1, "asks_min": 1}),
        ("fr_key2", 2,
         "她掰着你的手指头，一根一根：去太平间要走冷抽屉的路——护士站交接窗后面那条送饭的矮道，"
         "铁腰带钻不进去，你饿三天也能钻。别碰第三格冷柜，那格'还没睡熟'。",
         "矮道 送饭 怎么下去 太平间怎么走 交接窗 护士站后面 路线 冷柜",
         {"affinity_min": 4, "asks_min": 2}),
    ]),
    ("寂声计划", "ay_wen", "heavy", ["ay_wen", "ay_he"], [
        ("fr_lab1", 1,
         "温以宁盯着那袋13床的档案看了很久，声音发干：这不是疗养院，至少地下三层不是。"
         "他们管那叫'安静疗法'。签字的名单上，下一个圈，画的是阿枝。",
         "寂声 计划 安静疗法 实验 地下 做什么 档案 13床 下一个",
         {"affinity_min": 4, "asks_min": 1}),
        ("fr_lab2", 2,
         "她终于把那句话吐出来：他们在造'安静'——把人关进隔音室，剥夺声音，直到人不再呼救。"
         "41个人。我签了三年的字。你的录音笔要是还有电，现在就按下去，我从头说。",
         "多少人 隔音室 剥夺 招供 亲口说 录下来 从头说 你签的",
         {"affinity_min": 8, "asks_min": 2}),
    ]),
    ("陆九秋是谁", "ay_lu", "heavy", ["ay_lu"], [
        ("fr_lu1", 1,
         "他第一次直视你的眼睛：十一年前我是这里的会计。我把账本寄给了报社，寄出去第三天，"
         "我就成了'偏执型'。当年收信的那个记者，再也没有来。——所以我等的不是救兵，是个还敢来的人。",
         "你是谁 为什么进来 十一年 会计 账本 举报 报社 不是病人 装疯",
         {"affinity_min": 10, "asks_min": 1}),
    ]),
    ("后山的门", "ay_lu", "medium", ["ay_lu", "ay_zhi"], [
        ("fr_exit1", 1,
         "陆九秋在你掌心画了一条线：后山铁门，锁从里面开，配'后山'字样的黄铜钥匙。"
         "但门轴锈了十一年，一推就是整座山都听得见的动静——先去配电井拉总闸，警铃断了电，才轮到门响。"
         "出去之后想不想回来，回来救谁，那是你自己的事了。",
         "出口 后山 铁门 怎么出去 逃出去 断电 总闸 配电 警铃",
         {"affinity_min": 6, "asks_min": 1}),
    ]),
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
                   tagline="夜探的自由记者", background="收到线报，翻墙进了寂声疗养院。"))
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
            one_liner="深夜的精神病院，铁门在你身后锁死。巡夜人循声而猎——活下去，挖出真相，或者成为14床。",
            synopsis="自由记者沈默循着线报夜探寂声疗养院，防火门在身后自锁，手机没有信号。"
            "三楼住着一个装疯十一年的清醒人、一个签了三年名单的值夜护士、一个把真相唱进童谣的女病人，"
            "和一个用布缠住钥匙、循声而猎的巡夜人。地下三层，「寂声计划」正在收最后一批'安静'。"
            "这是一座无尽的楼：夜复一夜，你可以求生、可以深挖、可以经营人心攒出一条路——"
            "但每弄出一次声音，死亡就近一步。",
            world_long="深山里的私立疗养院，始建于七十年代，三面环山一面铁门。夜间全楼锁死，"
            "只留应急灯。地下三层不在任何消防图纸上。这里的恐怖不靠鬼——靠制度、靠共谋、"
            "靠一个把'安静'当成产品来制造的院长，和一栋替他吞声音的楼。",
            relations_overview="玩家是夜探的记者沈默。陆九秋是信任的关口、真相的地图；温以宁握着"
            "「寂声计划」的亲历供述，是良心与共谋之间的活扣；阿枝的童谣藏着钥匙与路线；"
            "铁松是全楼的移动死线，惧声怕光者生、弄响者死；贺院长盘踞在楼的最深处。",
            world_facts=(
                "【地点】故事发生在寂声疗养院内：三楼病房区（起点）、三楼走廊、护士站、淋浴间、"
                "档案室、太平间、配电井、地下三层、后山铁门。夜间断网无信号，全程没有手机可用。\n"
                "【规则·恐怖】铁松循【声音和光】而猎：奔跑、开手电直照、碰倒东西都会招他。"
                "他不奔跑、不喊叫，出现时几乎无声。初犯会被'请'回病房，再犯会被打伤，"
                "屡犯会死——这栋楼里的死亡是真实的。他不是超自然存在——这栋楼里没有鬼，"
                "只有人祸，这一点绝不动摇。\n"
                "【在场的人】常在三楼的是：陆九秋（病房区）、温以宁（护士站）、阿枝（淋浴间），"
                "铁松在三楼走廊间歇巡夜。贺院长深居地下三层，平时只以广播现声——"
                "玩家没下到地下之前，他不会照面。\n"
                "【身份·要点】沈默的记者身份对院方是致命信息：陆九秋、阿枝知道后会守口，"
                "温以宁知道后会挣扎，铁松与贺院长一旦确认，全楼都会来'收治'你。录音笔是证据容器，"
                "也是被搜出来就万事皆休的东西。"
            ),
            trope_tags=["恐怖", "逃生", "精神病院", "悬疑", "生存", "沙盒"],
            style=("贴身的恐怖：恐惧来自声音与光，不来自血浆——脚步声停在门外的三秒，"
                   "比任何嘶吼都可怕。短句，多留白，能不解释就不解释；黑暗里先写听见的，"
                   "再写看见的。忌一惊一乍连发，忌形容词堆叠，忌超自然直给"
                   "（一切恐怖必须可以被解释为人祸）。对白少而钝，疯话要有可破译的芯。"
                   "铁松两条铁律：他的每次现身必须先声后形——先写声音/气味/影子，最后才见形；"
                   "他离开必须留下痕迹——门缝下停了三秒才移开的影子、一股散不掉的旧棉被味。"),
            mature=False,
            characters=CHARACTERS,
            acts=ACTS,
            endings=ENDINGS,
            locations=LOCATIONS,
            sandbox=SANDBOX,
            threat=THREAT,
            pressure=PRESSURE,
            dooms=DOOMS,
            phone={"enabled": False},
            tuning={"max_new_characters": 6, "plan_render": 1},
            visibility="public",
        )
        db.add(story)
        db.flush()

        for title, char_id, sens, known_by, frags in SECRETS:
            sec = Secret(story_id=story.id, character_id=char_id, title=title, sensitivity=sens)
            sec.fragments = [
                Fragment(id=fid, layer=layer, content=content, retrieval_key=rkey,
                         known_by_character_ids=known_by, unlock=unlock,
                         cover=COVERS.get(fid))
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
        print("   主角=沈默(记者)。恐怖沙盒·无尽长夜。published v1, public.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
