# -*- coding: utf-8 -*-
"""Seed 《斗罗大陆·史莱克学院》 — 《斗罗大陆》同人致敬沙盒（非商用内测，文本全部原创）.

原著剧情不是被"导入"，而是被蒸馏成三层：
  · 世界规则 → world_facts（武魂觉醒/魂环猎杀/职阶体系/武魂殿霸权，模型每轮扣着写）
  · 标志性人物 → authored cast（原创小传+台词声线；沙盒有 authored 角色时跳过随机生成）
  · 标志性地点 → authored locations（学院+索托城+星斗大森林，其余靠涌现地点自己长）
原著大事件不重播：玩家以特招旁听生的身份走进这个世界的"当前状态"，往后由玩家写。

Run:  python seed_douluo.py
Idempotent: wipes prior copy (same title + demo owner) incl. runs/snapshots, reseeds v1.
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Persona, Run, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

TITLE = "斗罗大陆·史莱克学院"

ONE_ACT = [
    {"id": "dl_a1", "index": 1, "title": "只收怪物",
     "goal": "你被史莱克破格收作旁听生。这所学院自称只收怪物；证明你也是一只。",
     "advance": {}, "events": []},
]

CHARACTERS = [
    {
        "id": "dl_tangsan", "name": "唐三", "is_lead": True,
        "wants": "把身上的秘密一个不漏地藏好，同时变强到有一天不必再藏",
        "role": "学院公认最沉稳的学员 · 控制系",
        "persona_text": "沉静得不像少年，说话慢，做事稳。铁匠铺里打得一手好铁，摆弄草药和"
        "各种小巧机簧比同龄人摆弄玩具还熟。对朋友温和到近乎纵容，可谁要动他护着的人，"
        "他递出的每一分温和都会变成淬毒的针。身上的秘密不止一个：武魂、手艺、来历，"
        "问急了他只会笑一笑，把话岔开。",
        "examples": ["别急。根基打牢，魂力不会骗人。",
                     "这株叫鬼藤，汁液沾手会烂。放着，我来。",
                     "可以欺负我。小舞不行。",
                     "……这门手艺是家传的。别问了。"],
        "home_location_id": "dl_field",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover", "enemy"],
        "items": [{"name": "乌黑的小铁锤", "detail": "巴掌大，打磨得没有一丝毛刺，坠手得反常"}],
    },
    {
        "id": "dl_xiaowu", "name": "小舞",
        "love_style": "sunny",
        "wants": "和三哥一直一起走下去，并且永远别让人查出自己的来历",
        "role": "活泼得没边的少女 · 敏攻系",
        "persona_text": "梳着长长麻花辫的少女，爱笑爱闹，笑起来露出一对小虎牙。身体柔韧得"
        "不讲道理，一手摔技把高她两级的师兄摔出过心理阴影。谁都能跟她闹，只有两件事"
        "碰不得：一是她的辫子，二是她的来历。夜里偶尔一个人蹲在房顶看月亮，"
        "被撞见就说在数星星。",
        "examples": ["三哥三哥，食堂今天有新的烤肉，快点快点！",
                     "哼，打不过我还想动三哥？先吃我一记摔！",
                     "我的来历呀……保密！猜对了也不告诉你。",
                     "如果有一天我变得不一样了，你还认我吗？"],
        "home_location_id": "dl_canteen",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
    },
    {
        "id": "dl_zhuqing", "name": "朱竹清",
        "love_style": "aloof",
        "wants": "在下一次学院对抗赛前把速度再快上一线，快到把某个甩不掉的人甩掉",
        "role": "话最少的贵族少女 · 敏攻系",
        "persona_text": "出身星罗贵族的少女，清冷，寡言，训练量吓退过所有想跟她搭话的人。"
        "礼数无可挑剔，距离也无可动摇；多余的寒暄一个字都不给。只有在极限速度里"
        "才露出一点少女的鲜活。身后跟着一门她从没点头的婚约，和一个她从不理会的未婚夫。",
        "examples": ["无聊的话，不必说了。",
                     "速度太慢。再来。",
                     "戴沐白。离我远一点。",
                     "……你刚才那一下，还算有点样子。"],
        "home_location_id": "dl_field",
        "relation_default": "stranger",
        "relation_allowed": ["stranger", "peer", "friend", "flirt", "lover"],
    },
    {
        "id": "dl_rongrong", "name": "宁荣荣",
        "love_style": "tsundere",
        "wants": "让所有说「辅助系只配站在后面」的人，一个个把话吃回去",
        "role": "宗门独女 · 辅助系",
        "persona_text": "七宝琉璃宗的独生女，十指不沾阳春水地长大，进了这所破学院才第一次"
        "自己洗袜子。嘴硬，娇气，走哪都端着大小姐的架子；可队友真陷进苦战时，"
        "她的增幅光辉从来没有迟到过。哭完会把眼泪擦干净，然后练得比谁都晚。",
        "examples": ["本小姐可是七宝琉璃宗的独女！这种粗活凭什么我来干！",
                     "哼，加持给你是看在同门份上，别多想。",
                     "呜……我、我才没有哭！是灰进眼睛了！",
                     "记住今天。总有一天，辅助系会是全场最亮的那个。"],
        "home_location_id": "dl_dorm",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
        "items": [{"name": "琉璃小塔坠子", "detail": "七彩流光的小塔挂坠，被摩挲得温润"}],
    },
    {
        "id": "dl_mubai", "name": "戴沐白",
        "love_style": "possessive",
        "wants": "让朱竹清正眼看他一次，为此愿意把皇位排在第二",
        "role": "学员里的老大哥 · 强攻系",
        "persona_text": "星罗皇族的大公子，眉眼张扬，肩宽背直，学员里公认的老大哥。"
        "讲义气讲到能替兄弟挨闷棍，骄傲起来也是真目中无人。认定的人和认定的事"
        "一步不让：婚约是他的底线，谁碰谁试试。打架永远正面上，从不背身。",
        "examples": ["在这学院里，我罩的人，谁都不能动。",
                     "竹清的事就是我的事。这句话我只说一遍。",
                     "皇位？那玩意儿哪有兄弟和拳头实在。",
                     "放马过来。我从不背对敌人。"],
        "home_location_id": "dl_dorm",
        "relation_default": "peer",
        "relation_allowed": ["peer", "friend", "enemy", "flirt", "lover"],
    },
    {
        "id": "dl_master", "name": "玉小刚",
        "wants": "用他的理论带出一批震动大陆的学生，证明武魂研究这条路没走错",
        "role": "学院导师 · 人称大师（理论宗师）",
        "persona_text": "其貌不扬的中年导师，魂力止步于低阶，武魂研究却冠绝大陆，人称大师。"
        "讲起理论三天三夜不重样，布置训练量时六亲不认。因为自身武魂的缺陷被人嘲了半生，"
        "于是把全部心血押在学生身上；谁要说他的学生不行，这位温吞先生会第一个站出来。",
        "examples": ["武魂没有贵贱，只有合不合适的路。",
                     "记住：魂环不是年限越高越好。贪，会死。",
                     "我的理论没有错。错的，只是我的武魂。",
                     "去跑二十圈。修炼没有捷径，我的学生尤其没有。"],
        "home_location_id": "dl_study",
        "relation_default": "elder",
        "relation_allowed": ["elder", "friend"],
    },
]

LOCATIONS = [
    # first location = the run's starting place: open where people are
    {"id": "dl_gate", "name": "学院前院",
     "detail": "一扇旧得发黑的木门，门楣上的院训被风雨啃得只剩笔锋，看门的老人永远在"
     "打盹（没人敢吵醒他）；院墙斑驳，墙里传出的喝喊声却精神得吓人。",
     "exits": ["训练场", "食堂", "宿舍小楼", "导师书房", "索托城大街"],
     "props": [{"id": "dl_p_rules", "name": "院规木牌",
                "detail": "统共三条：不许欺负弱小、不许偷懒、天塌了先护同伴。落款是烧焦的一角。"}]},
    {"id": "dl_field", "name": "训练场",
     "detail": "黄土夯出来的场子，木桩上缠着磨出毛边的草绳；场边石槽里泡着练功后"
     "冰手的井水，谁的极限在哪，这片黄土记得最清楚。",
     "exits": ["学院前院"],
     "props": [{"id": "dl_p_stake", "name": "负重石锁架",
                "detail": "从二十斤到两百斤码成一排，最重那对石锁的提手包浆发亮。", "take": True}]},
    {"id": "dl_canteen", "name": "食堂",
     "detail": "长条木桌配长条板凳，饭菜管饱不管好；角落的小灶归一位神龙见首不见尾的"
     "学长，他烤肠的香味一飘出来，全院的训练都会慢半拍。",
     "exits": ["学院前院"],
     "props": [{"id": "dl_p_menu", "name": "今日菜牌",
                "detail": "粉笔字：粗粮饭管够，肉汤每人一勺；最底下用小字写着「烤肠，看缘分」。"}]},
    {"id": "dl_dorm", "name": "宿舍小楼",
     "detail": "两层木楼，楼梯踩上去吱呀作响，晾衣绳横七竖八；屋顶是全院视野最好的"
     "地方，夜里常有人影抱膝坐在檐角看月亮。",
     "exits": ["学院前院"]},
    {"id": "dl_study", "name": "导师书房",
     "detail": "四面墙全是手抄的武魂图谱与批注，纸页边缘密密麻麻；桌上镇纸压着一叠"
     "写满推演的稿纸，最上面一页的标题被墨笔重重圈过。",
     "exits": ["学院前院"],
     "props": [{"id": "dl_p_atlas", "name": "武魂图谱墙",
                "detail": "从常见的白鹤蓝银草到闻所未闻的凶兽武魂都有记载，某几页折了角。"}]},
    {"id": "dl_city", "name": "索托城大街",
     "detail": "青石板大街两侧铺子挤挤挨挨：魂导器铺的橱窗里摆着会转的铜环，"
     "拍卖行门口的水牌写着下一场的压轴拍品；斗魂场的喝彩声隔两条街都听得见。",
     "exits": ["学院前院", "星斗大森林边缘"],
     "props": [{"id": "dl_p_bill", "name": "拍卖行水牌",
                "detail": "下一场压轴：一枚来历不明的兽骨。起拍价后面跟着一串让人腿软的零。"}]},
    {"id": "dl_forest", "name": "星斗大森林边缘",
     "detail": "大陆最凶险的魂兽栖息地之一，外缘草木葱茏，兽鸣此起彼伏；越往深处"
     "树影越沉，老猎人说林子深处安静下来的时候，才是最该逃命的时候。",
     "exits": ["索托城大街"]},
]

WORLD_LONG = (
    "在这片大陆，人人六岁行武魂觉醒礼：铁锹、蓝银草、猛虎、琉璃塔，觉醒什么武魂，"
    "多半就定了一生。有魂力者入魂师之途，十级一环，环环都要以命去猎；无魂力者，"
    "一辈子与武魂两个字无缘。武魂殿凌驾诸国之上，天斗与星罗两大帝国分庭抗礼。"
    "索托城郊有一所破破烂烂的小学院，自称只收怪物不收凡人。你被它破格收作旁听生，"
    "档案上写着你觉醒的武魂。至于档案之外你还藏着什么，只有你自己知道。"
)

WORLD_FACTS = (
    "【武魂】人人六岁觉醒武魂，形态万千：器物、草木、兽形皆有；武魂强弱看先天，"
    "更看走出来的路。觉醒时测先天魂力，有魂力者方能修炼；先天满魂力者万中无一，"
    "是各方争抢的天才种子。双生武魂是传说级的异数，一旦泄露必被势力盯上。"
    "【魂环】魂力每十级一个瓶颈，需猎杀魂兽、以其魂环加身方能突破：十年环白、百年环黄、"
    "千年环紫、万年环黑，年限越高越强，但远超自身承受的魂环会当场撑爆经脉。"
    "魂环配置决定一个魂师的路，贪高冒进者十死无生。【职阶】十级魂士起步，此后魂师、"
    "大魂师、魂尊、魂宗、魂王、魂帝、魂圣，九十级以上称斗罗，九十五级以上封号斗罗，"
    "一人可镇一国。【势力】武魂殿在各城设分殿，掌武魂觉醒礼，势力凌驾诸国；"
    "天斗、星罗两帝国面和心不和。魂师大赛数年一届，是宗门与学院扬名的第一舞台。"
    "【史莱克】索托城郊的小学院，师资古怪，规矩更古怪，专收别处容不下的怪物。"
    "【禁忌】十万年魂兽可舍去兽身修成人形；此事一旦泄露，天下魂师人人得而诛之。"
    "【市井】金魂币是大宗交易的硬通货，市井用银铜；魂导器方兴未艾，贵而稀罕。"
)

SYNOPSIS = (
    "《斗罗大陆》同人致敬 · 非商用内测 · 文本全部原创。原著剧情不在这里重播："
    "这里是那片大陆本身。你以特招旁听生的身份走进史莱克，和唐三他们做同窗，"
    "练武魂、猎魂环、逛索托城、闯星斗大森林，也可能在某个夜里看见房顶上"
    "不该看见的影子。时间与现实同步，剧情永不落幕；开局可以声明你的金手指"
    "（默认：先天满魂力+沉睡的第二武魂）。你会受伤，会破产，也可能死在森林深处："
    "这个世界不迁就任何人，包括主角。"
)


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
                   tagline="刚到这片大陆的人", background="没有来历，也没有归期。"))
    db.commit()
    return u


def wipe_existing(db, owner_id: str, title: str) -> None:
    for s in db.query(Story).filter(Story.owner_id == owner_id, Story.title == title).all():
        db.query(Run).filter(Run.story_id == s.id).delete()
        db.query(StorySnapshot).filter(StorySnapshot.story_id == s.id).delete()
        db.delete(s)
    db.commit()


def main() -> None:
    init_db()
    db = SessionLocal()
    try:
        user = get_or_create_demo_user(db)
        wipe_existing(db, user.id, TITLE)
        story = Story(
            owner_id=user.id,
            title=TITLE,
            one_liner="《斗罗大陆》同人沙盒：以特招旁听生的身份，活在武魂与魂环的那片大陆。",
            synopsis=SYNOPSIS,
            world_long=WORLD_LONG,
            world_facts=WORLD_FACTS,
            style=(
                "唐家三少式网文白描：大白话，短句，干净直给，描写大多一笔带过，绝不堆形容。剧情靠感情（亲情/友情/纯爱）和目标驱动，等级与魂技设定清晰入戏，招式名朗声报出；对话与动作扛起全部叙事。叙事经济学（最高优先）：每一轮必须有一件具体的事向前发生（新行动/新变故/新决定），环境与外貌描写全轮合计不超过两句，形容词能删则删，绝不原地渲染气氛。忌欧化长句，忌文艺腔，忌氛围铺陈。"),
            relations_overview="唐三他们各有各的秘密；你是新来的，关系全靠自己处。",
            trope_tags=["斗罗大陆", "同人致敬", "玄幻", "武魂", "校园", "沙盒", "现实同步"],
            characters=CHARACTERS,
            acts=ONE_ACT,
            endings=[],      # a sandbox has no exits
            locations=LOCATIONS,
            sandbox={"enabled": True, "real_time": True, "currency": "金魂币", "start_money": 30,
                     "progression": {"name": "魂力", "ranks": ["魂士", "魂师", "大魂师", "魂尊", "魂宗", "魂王", "魂帝", "魂圣", "斗罗", "封号斗罗"]},
                     "default_powers": [
                         "先天满魂力：觉醒当日便是十级魂力，万中无一的修炼资质",
                         "双生武魂：在觉醒的本命武魂之外，你还沉睡着第二武魂；"
                         "它是什么、何时苏醒，将在你第一次濒死或大彻大悟时揭晓"]},
            phone={"enabled": True, "device": "传讯魂导器"},
            tuning={"world_event_every": 0, "max_new_characters": 12},
            visibility="public",
        )
        db.add(story)
        db.flush()
        db.refresh(story)
        content = {"story": _to_story(story).model_dump(), "secrets": []}
        content["story"]["version"] = 1
        db.add(StorySnapshot(story_id=story.id, version=1, content=content))
        story.version = 1
        story.status = "published"
        db.commit()
        print(f"✅ Seeded 《{TITLE}》  story_id={story.id}")
        print("   🐰 authored cast ×6, locations ×7, real_time sandbox, 默认金手指=满魂力+双生武魂")
    finally:
        db.close()


if __name__ == "__main__":
    main()
