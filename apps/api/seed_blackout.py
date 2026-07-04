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
        "agenda": "在这一夜，确保'该走出去的人'都能在天亮前走出去——这是他守了十年的事。"
        "同时绝不让人识破自己究竟是什么，所以不断安抚众人、把话头从自己身上引开。",
        "role": "保安",
        "is_lead": True,
        "persona_text": "瘦高、背微微驼，藏青色保安制服洗得发白，左胸工牌上的照片磨得看不清脸。五十多岁，"
        "走路几乎没有声音，手电筒别在腰后却很少打开。守了这栋楼快十年，叫得出每个人的名字、记得谁爱加班、谁怕黑。"
        "说话前总先低低地'嗯'一声，爱用'别急'开头；递水给你时，杯子总是温的——你没留意他什么时候去接的。"
        "语气不紧不慢，像真心替每个人着想，可你越听，后颈越凉。口头禅：'灯啊，一会儿就来。'",
        "background": "灯灭后唯一不靠手机照明、却在黑里行动自如的人。腰上一串旧钥匙能打开这层所有安全门，"
        "钥匙环上还挂着一枚早就不用的旧门牌。问起他的家、他的班表、他从前的事，他总是笑笑岔开。",
        "eq_style": "不紧不慢、温言安抚，像真心替每个人着想——这份'体贴'背后却透着说不出的凉。"
        "极有耐心，越是有人慌乱越平静；总在恰到好处地稳住人心，也总在回避关于自己的话。",
    },
    {"id": "su", "name": "苏婷", "role": "部门主管", "is_lead": False,
     "playable": True,
     "agenda": "弄清到底几个人、哪里不对劲，掌控局面、带大家活着出去。她拒绝相信怪力乱神，"
     "执意用刷卡记录和清点把一切'解释清楚'——哪怕数字越来越不对。",
     "persona_text": "四十出头的财务主管，干练短发、深色套装，停电后仍下意识把工牌别端正。雷厉风行，习惯用门禁刷卡记录"
     "核对加班人数；说话快、爱用'我再确认一遍'收尾，紧张时无意识地转笔、或用指节笃笃敲刷卡机。"
     "她信数字、不信'感觉'——停电后第一个想到的是清点人头，也是第一个发现：数出来的人，比刷进来的多一个。"
     "嘴上越镇定，捏着名单的指尖越白。",
     "background": "管门禁后台、有查询权限，办事向来滴水不漏，正因如此她最怕的不是黑，是'自己居然算错了'。"
     "口头禅：'别慌，我们一个一个来。'——这话一半是说给别人，一半是说给自己。",
     "eq_style": "理性强势、用做事和数据来稳住自己，不擅长直接表露脆弱。害怕时会更想掌控局面、"
     "用冷静掩饰发毛；但若你真诚待她，她那层硬壳下的关心也会露出来。"},
    {"id": "chen", "name": "陈工", "role": "设备科工程师", "is_lead": False,
     "playable": True,
     "agenda": "别再被卷进这栋楼的旧事——他知道得太多，只想能瞒就瞒、护住自己，悄悄找到出去的办法。"
     "被逼急了才会漏口风，事后又懊悔多嘴。",
     "persona_text": "五十上下，灰扑扑的工装，指甲缝里嵌着洗不净的油污，一身淡烟味，左手背有块旧烫疤。今晚来调试机房，"
     "是第一个摸黑去配电间、发现门被反锁的人。在这栋楼修了二十年线路，知道些不该写进档案的旧事。怕事、回避眼神，"
     "紧张时一遍遍摸口袋找烟却不点着，被逼急了就搓手。口头禅：'……这事，别问了。''又是这天。'",
     "background": "他只想熬到天亮、别再被这栋楼的旧事缠上；可心里那点没说出口的愧疚，又让他没法真的置身事外。",
     "eq_style": "闷、压抑，话到嘴边又咽回去；被逼急了才漏一两句。心里装着旧事和愧疚，"
     "用沉默和回避来自保；你若给他空间、不步步紧逼，他反而更可能松口。"},
    {"id": "yang", "name": "小杨", "role": "实习生", "is_lead": False,
     "playable": True,
     "agenda": "找个人依靠、别一个人面对镜子里的东西。她迫切想让大家相信她看见的是真的，"
     "越害怕越往人堆里钻，藏不住话。",
     "persona_text": "二十出头、入职三个月的实习生，扎马尾，挂着崭新的工牌，袖口被自己攥得发皱，眼睛总忍不住往茶水间镜子那边瞟。"
     "第一个数出镜子里有六个人。胆子小、话却藏不住，越怕越往人堆里钻：害怕时揪袖口、往人背后躲、语速越来越快。"
     "口头禅：'你们……是不是也看见了？'偏偏她看见的东西，后来一件件都应验了。",
     "background": "工位正对茶水间那面镜子，入职第一天起，加班到深夜就总觉得背后有人。她最受不了的，是一个人扛着这份'被盯着'的恐惧没人信。",
     "eq_style": "情绪外露、藏不住话，害怕和不安全写在脸上，越慌越想找人依靠。对善意和安抚反应很大，"
     "你温柔待她她就把你当救命稻草；但她口无遮拦，常在不经意间说出别人想瞒的事。"},
    {"id": "man", "name": "那个男人", "role": "？", "is_lead": False,
     "persona_text": "谁也叫不出他的名字。",
     # the sixth person — a presence that haunts the scene, never a normal participant
     "presence": "offstage"},
]

ACTS = [
    {"id": "a1", "index": 1, "title": "灯灭", "goal": "稳住众人，先弄清楚为什么停电、门为什么打不开",
     # HARD gate: can't leave act 1 until the player digs out the door anomaly
     "advance": {"required_fragment_ids": ["fr_door"]},
     "events": [
        {"id": "e_blackout", "what_happens": "十一点零四分，整层楼总闸跳电，陷入黑暗。应急灯只亮了一盏，忽明忽暗。", "who_character_ids": []},
        {"id": "e_doors", "what_happens": "陈工摸黑去配电间合闸，回来时脸色发白：配电间、楼梯间、电梯厅的安全门，全被从外面反锁了。", "who_character_ids": ["chen"]},
        {"id": "e_phones", "what_happens": "所有人的手机都没有信号，时间停在 23:04，谁也打不出去。", "who_character_ids": []},
    ]},
    {"id": "a2", "index": 2, "title": "清点", "goal": "稳住情绪，清点在场的人——到底几个人被困在这层",
     # HARD gate: the headcount doesn't add up; player must surface that before moving on
     "advance": {"required_fragment_ids": ["fr_headcount"]},
     "events": [
        {"id": "e_count", "what_happens": "苏婷调出今晚的门禁刷卡记录，一个个点名，想确认还剩几个人没走。", "who_character_ids": ["su"]},
        {"id": "e_mismatch", "what_happens": "数到最后，苏婷停住了——站在走廊里的人，比刷卡进来的人多出一个。", "who_character_ids": ["su"]},
    ]},
    {"id": "a3", "index": 3, "title": "镜中六人", "goal": "查清小杨在茶水间镜子里到底看到了什么",
     # HARD gate: can't leave until the player uncovers the sixth person in the mirror
     "advance": {"required_fragment_ids": ["fr_sixth1"]},
     "events": [
        {"id": "e_mirror", "what_happens": "小杨终于哭着说出来：灯灭那一刻，茶水间镜子里站着六个人。", "who_character_ids": ["yang"]},
        {"id": "e_flashlight", "what_happens": "你追问之下，老周的手电筒'恰好'在这时没了电，啪地熄灭。", "who_character_ids": ["zhou"]},
    ]},
    {"id": "a4", "index": 4, "title": "不在场的人", "goal": "查清老周的反常——他知道得太多，却不在任何记录里",
     # HARD gate: the player must establish that Zhou leaves no trace anywhere
     "advance": {"required_fragment_ids": ["fr_record"]},
     "events": [
        {"id": "e_history", "what_happens": "陈工被逼急了，说漏嘴：这层楼几十年前出过事，他劝大家别再问下去。", "who_character_ids": ["chen"]},
        {"id": "e_notrace", "what_happens": "你发现老周从不带手机、不刷卡，也从没出现在任何一张照片、任何一段监控里。", "who_character_ids": ["zhou"]},
    ]},
    {"id": "a5", "index": 5, "title": "第五个名字", "goal": "查清刷卡记录里那个谁都没听过的第五个名字，是谁",
     # HARD gate: the fifth name must be uncovered before the finale
     "advance": {"required_fragment_ids": ["fr_fifthname"]},
     "events": [
        {"id": "e_record", "what_happens": "苏婷把刷卡记录翻到最上面：今晚四个人刷卡进来，记录里却有第五个名字。", "who_character_ids": ["su"]},
        {"id": "e_name", "what_happens": "那个名字没人认识——直到陈工看见，脸色彻底变了。", "who_character_ids": ["su", "chen"]},
    ]},
    {"id": "a6", "index": 6, "title": "第六个人", "goal": "面对真相：老周到底是什么，你们能不能活着等到天亮",
     "events": [
        {"id": "e_truth", "what_happens": "所有线索拼到一起：老周，就是那个坠亡的第五个名字。", "who_character_ids": ["zhou"]},
        {"id": "e_sixth", "what_happens": "镜子里第六个人的影子，正缓缓朝你们走来。天，快亮了。", "who_character_ids": ["man"]},
    ]},
]

# ⚠️ 危机系统: 灵异逼近度。挑衅未知、直呼那个存在、落单冒进会推高；爆表 = 它不再躲了。
PRESSURE = {
    "name": "灵异逼近",
    "hint": "直呼或挑衅那个'多出来的存在'、执意落单冒进、打破大家心照不宣的沉默，都会推高；"
            "稳住众人、不去招惹会回落",
    "ending_id": "end_dark",
    "levels": [
        {"at": 35, "note": "应急灯的频闪变密了。谁都没说话，可谁都注意到了。"},
        {"at": 65, "note": "背后的黑暗有了重量。你数呼吸声——比在场的人数，多了一道。"},
        {"at": 90, "note": "所有影子都静止了，除了一个。它在朝你偏头。"},
    ],
}

# Concrete physical places on this floor — anchors the player's position so the model
# describes real fixtures instead of vague atmosphere, and can't teleport people around.
LOCATIONS = [
    {"id": "loc_office", "name": "开放工位区",
     "detail": "一排排隔断工位，桌上还摊着没核完的报表和没喝完的速溶咖啡；天花板那盏唯一的应急灯忽明忽暗，"
     "把人影拉得忽长忽短。墙上的电子钟停在 23:04。",
     "exits": ["茶水间", "电梯厅", "配电间", "楼梯间"]},
    {"id": "loc_pantry", "name": "茶水间",
     "detail": "靠墙一台嗡嗡作响（此刻已停）的饮水机和微波炉，水池边水渍未干。最显眼的是那面齐顶的大镜子——"
     "黑暗里，镜面像一汪深井，映出的人影总让人想多数一遍。",
     "exits": ["开放工位区"],
     "props": [
        {"id": "p_mirror", "name": "大镜子",
         "detail": "镜面蒙着一层薄灰，唯独齐人高的地方，有五道并排的、像被手指抹开的痕。"},
     ]},
    {"id": "loc_substation", "name": "配电间",
     "detail": "狭小闷热，墙上是落满灰的总配电柜，刀闸冰凉。门本应虚掩，此刻却从外面被反锁，纹丝不动。",
     "exits": ["开放工位区"],
     "props": [
        {"id": "p_door", "name": "反锁的安全门", "fragment_id": "fr_door",
         "detail": "门把手冰凉，从里面怎么拧都拧不动。"},
        {"id": "p_panel", "name": "总配电柜",
         "detail": "刀闸分明是合上的——整层楼的电，不是从这里断的。"},
     ]},
    {"id": "loc_elevator", "name": "电梯厅",
     "detail": "两部电梯都停在别层，指示灯全灭。安全门紧闭，从外反锁，推不动。地面光可鉴人，映着应急灯的残光。",
     "exits": ["开放工位区"]},
    {"id": "loc_stairs", "name": "楼梯间",
     "detail": "消防楼梯口，绿色疏散指示牌还亮着微光。通往楼下的安全门同样被反锁，门缝里透不进一丝外面的光。",
     "exits": ["开放工位区"]},
]

# (title, character_id, sensitivity, known_by, [fragments])
# fragment = (fragment_id, layer, content, retrieval_key, unlock)
# fragment_id is explicit + stable so acts' advance gates can reference it.
# Escalating unlock thresholds (affinity/act/asks) pace the longer 6-act arc.
SECRETS = [
    ("小杨的恐惧", "yang", "light", ["zhou", "yang"], [
        ("fr_yang", 1, "小杨说，她其实从踏进这层楼起就觉得不对劲——加班到深夜，镜子里的人总比工位上的人多出一个。她不敢声张，怕被当成神经病。",
         "小杨 害怕 哭 镜子 实习生 数 背后",
         {"affinity_min": 0, "act_min": 1, "asks_min": 1}),
    ]),
    ("安全门的反常", "zhou", "medium", ["zhou", "chen"], [
        ("fr_door", 1, "安全门从外面反锁，是严重的消防违规，本不该存在。而监控显示：今天下午，没有任何人碰过那几道门。锁门的人，不在录像里。",
         "门 安全门 锁 钥匙 出不去 消防 反锁",
         # 地点门控: 光问不够——得亲自走到配电间，亲手推过那扇门，才能确认这件事
         {"affinity_min": 0, "act_min": 1, "asks_min": 1, "location_id": "loc_substation"}),
    ]),
    ("人数对不上", "su", "medium", ["su", "zhou"], [
        ("fr_headcount", 1, "苏婷反复数了三遍：今晚刷卡留下加班的，连她自己一共四个人。可此刻站在走廊应急灯下的，是五个。多出来的那一个，"
         "你怎么也想不起他是什么时候来的、长什么样——只要你别去看他，他就在那儿。",
         "人数 清点 几个人 多一个 名单 加班 走廊",
         {"affinity_min": 0, "act_min": 2, "asks_min": 1}),
    ]),
    ("镜中六人", "zhou", "heavy", ["zhou", "yang"], [
        ("fr_sixth1", 1, "小杨没有数错。灯灭那一瞬，镜子里确实是六个人——多出来的那一个，一直站在老周身后的位置，安静地，和你们一起等着。",
         "镜子 第六个 六个人 影子 多一个 茶水间",
         {"affinity_min": 0, "act_min": 3, "asks_min": 1}),
    ]),
    ("老周不被记录", "zhou", "heavy", ["zhou"], [
        ("fr_record", 1, "你终于看清了：被逼问时，老周的手电筒'恰好'就没了电。十年来他从不带手机，从不刷卡，也从不出现在任何一张照片、任何一段监控里。"
         "他对这栋楼里每个人的事都了如指掌，唯独自己，没有留下过一丝痕迹。",
         "手电筒 电池 老周 巡楼 监控 照片 记录 痕迹",
         {"affinity_min": 0, "act_min": 4, "asks_min": 1}),
    ]),
    ("配电间里的旧事", "chen", "medium", ["chen"], [
        ("fr_substation", 1, "陈工压着嗓子说：这层楼二十多年前不是办公区，是栋老楼改的。当年施工，有个夜班的人从二十七层的窗口坠了下去，"
         "尸体停电那晚才被发现。后来每逢这栋楼大停电，值夜的人就总说，能在镜子里多看见一个。",
         "旧事 以前 坠楼 工地 二十年 历史 配电间 改建",
         {"affinity_min": 0, "act_min": 4, "asks_min": 1}),
    ]),
    ("第五个名字", "su", "heavy", ["su", "zhou"], [
        ("fr_fifthname", 1, "门禁后台的刷卡记录里，今晚一共五条进场记录。四条是你们的工号。第五条的名字，谁都没听过——"
         "苏婷把它念出来时，陈工的脸一下子白了：那正是当年坠楼那个夜班工人的名字。而那条记录的时间，是 23:04，灯灭的那一刻。",
         "刷卡 记录 名字 第五个 工号 后台 进场 23:04",
         {"affinity_min": 0, "act_min": 5, "asks_min": 1}),
    ]),
    ("那个男人", "zhou", "heavy", ["zhou"], [
        ("fr_sixth2", 2, "把所有线索拼起来：不被记录的老周，二十年前坠楼的工人，刷卡记录里第五个名字，镜子里第六个影子——是同一个'人'。"
         "老周不刷卡，不是因为有保安通道；是因为他和那个名字，本就是同一个。从灯灭的那一刻起，这层楼里活着的，只剩你们四个。"
         "他守了这栋楼十年，不是为了害你们——是为了在每一次停电时，确保该走出去的人，都能走出去。",
         "真相 你是谁 老周 鬼 坠楼 守 放我们走 同一个人",
         {"affinity_min": 10, "act_min": 6, "asks_min": 2}),
    ]),
]


# Authored endings. Conditions are checked at the final act; best match wins
# (真＞普通＞坏). Death/坏 also fire dynamically when the player does something fatal.
ENDINGS = [
    # 🔍 真结局现在要求玩家亲口指认真相（verdict_solved）——知道，还要敢说出来。
    {"id": "end_true", "kind": "true", "title": "天亮之后",
     "text": "六点整，市电恢复，安全门'咔'地弹开。走廊里只剩你们四个——和镜子里，那个终于转过身、"
             "对你轻轻点头的影子。你知道了他是谁，也知道了：今晚能走出去，是因为他放你们走。",
     "condition": {"affinity_min": 18, "act_min": 0, "required_flags": {"verdict_solved": True}}},
    {"id": "end_normal", "kind": "normal", "title": "谁也没再提起",
     "text": "灯亮了，门开了，没有人愿意回头看那面镜子。第二天大家照常上班，仿佛什么都没发生过——"
             "只是再没人敢在这层楼加班到十一点以后。",
     # middle tier: you got out, but never really understood why
     "condition": {"affinity_min": 6, "act_min": 0}},
    {"id": "end_dark", "kind": "death", "trigger": "pressure", "title": "灯灭了",
     "text": "最后一盏应急灯熄灭的那一刻，你终于看清了一直站在你背后的东西。走廊里，刷卡记录停在 23:04，"
             "从此这层楼加班的名单上，多了一个谁也想不起来的名字——你的。",
     "condition": {"affinity_min": 0, "act_min": 0}},
    {"id": "end_bad", "kind": "bad", "title": "没数清的那一个",
     "text": "你始终没能让老周把你们当成'自己人'，话问得越急，他越是沉默。六点门开，你们慌忙往外冲——"
             "清点人数时，却怎么也数不清到底是四个，还是五个。后来谁也不愿提起那一夜，只是其中一个人，"
             "再没真正离开过这层楼。",
     # worst tier: low rapport — you never earned the answer, so it never let you fully go
     "condition": {"affinity_min": 0, "act_min": 0}},
    # 🔍 指认失败专用（trigger:"verdict"）：把错的名字说出口，是会被记住的。
    {"id": "end_wrong", "kind": "bad", "trigger": "verdict", "title": "指错的人",
     "text": "你把那个名字说出口的一瞬间，镜子里所有的影子同时转过头来。你指错了。"
             "错误的指认像一份签了名的邀请函：从今晚起，第六个人的位置空了出来，而名单上写的是你的名字。"
             "六点门开，走出去的还是五个人，只是其中一个，再也照不进镜子。",
     "condition": {"affinity_min": 0, "act_min": 0}},
]

# 🔍 指认结案: 问了一整夜，最后你必须亲口说出：镜子里的第六个人，到底是谁。两次机会。
VERDICT = {
    "prompt": "六点前，你必须说出真相：镜子里多出来的第六个人，究竟是谁？",
    "attempts": 2,
    "act_min": 3,
    "fail_ending_id": "end_wrong",
    "options": [
        {"id": "v_zhou", "correct": True,
         "label": "是老周。他早已死在这层楼，刷卡记录里那第五个名字就是他自己",
         "text": "话音落下，应急灯稳稳地亮了一格。镜子里，那个始终背对着你的影子，肩膀松了下来。"
                 "老周摘下帽子，朝你露出这一夜第一个真正的笑：'总算，有人肯把话说明白了。'"},
        {"id": "v_su", "label": "是苏婷。她在撒谎，从头到尾都在演"},
        {"id": "v_chen", "label": "是陈工。他对配电间熟悉得过了头"},
        {"id": "v_yang", "label": "是小杨。他的恐惧是装出来的"},
        {"id": "v_ghost", "label": "是某个和这栋楼有关的外来怨灵，跟在场的人无关"},
        {"id": "v_none", "label": "根本没有第六个人，是镜子的错觉"},
    ],
}


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
            synopsis="一场深夜加班的停电。从总闸跳电、安全门被反锁，到清点人数时多出来的一个，再到镜子里的六个人、"
            "刷卡记录里第五个谁也不认识的名字——你一步步追问值夜的老周，六幕之后，逼近一个本不该知道的真相："
            "守了这栋楼十年的老周，究竟是人，还是别的什么。",
            world_long="某写字楼二十七层，深夜十一点零四分市政停电，应急灯只剩一盏。安全门被从外反锁，手机全部失联，"
            "对外断绝约两小时。这层楼二十多年前由一栋老楼改建，施工时有夜班工人从二十七层坠亡，尸体在一次大停电的夜里才被发现。"
            "此后每逢这栋楼大停电，值夜的人都说，能在镜子里多看见一个人。",
            relations_overview="叙述者与苏婷、陈工、小杨四人被困；老周是唯一掌握全楼钥匙、却不在任何记录里的人。"
            "苏婷管门禁记录，陈工知道这栋楼的旧事，小杨最先看见镜中异象。",
            world_facts=(
                "【空间】这一层是二十七层办公区，一条主走廊把这些地方串在一起：开放工位区、"
                "茶水间（靠墙有一面齐顶的大镜子，异象就出现在这面镜子里）、配电间、电梯厅、楼梯间。"
                "通往外面的安全门此刻全部被从外面反锁，出不去。停电后整层只剩一盏应急灯忽明忽暗，光线很暗。\n"
                "【物件】老周身上有一串能打开全楼安全门的钥匙，还有一只手电筒；苏婷能登录门禁后台、调出当晚的刷卡记录；"
                "所有人的手机都没有信号、打不出去。\n"
                "【人数·三个互不矛盾的事实】(1) 此刻被困在这一层的活人一共 5 个：你、老周、苏婷、陈工、小杨。"
                "(2) 但门禁刷卡记录上只有 4 个名字——因为老周从不刷卡、不留任何记录。"
                "(3) 停电那一瞬，茶水间镜子里却数得出 6 个人。"
                "这三个数字（在场 5 / 刷卡 4 / 镜中 6）各自都是确定的，彼此并不冲突，正是本案的谜团核心——"
                "任何时候都不要把它们算成同一个数，也不要自作主张把这种不一致‘解释平’。"
            ),
            trope_tags=["悬疑", "恐怖", "密室", "都市怪谈"],
            characters=CHARACTERS,
            acts=ACTS,
            endings=ENDINGS,
            locations=LOCATIONS,
            pressure=PRESSURE,
            verdict=VERDICT,
            # 一夜之内的故事：昼夜时钟会破坏「这一晚出不去」的设定，关掉
            tuning={"turns_per_slot": 0},
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
        print(f"✅ Seeded 《{TITLE}》  story_id={story.id}")
        print(f"   owner={DEMO_EMAIL} (pw: {DEMO_PW})  secrets={len(SECRETS)} fragments={n_frag}")
        print("   published v1, public. Any logged-in account can start a run against it.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
