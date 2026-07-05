# -*- coding: utf-8 -*-
"""Seed "Grandmaster of Demonic Cultivation · The Soul-Guiding Lantern" — the
ENGLISH edition of the WangXian BL showcase (language="en").

Same original case as the Chinese edition (all prose here is our own writing,
translated by us; fan homage, non-commercial closed beta). Art is REUSED from
the zh edition: avatar_url preset to copied files (mdz_* → mdze_*), no regen.

Run:  python seed_mdzs_en.py   (idempotent; publishes public v1)
"""

import os

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///./dev.db")
os.environ.setdefault("JWT_SECRET", "dev")

from datetime import datetime  # noqa: E402

from app.db import SessionLocal, init_db  # noqa: E402
from app.models import Fragment, Persona, Run, Secret, Story, StorySnapshot, User  # noqa: E402
from app.routers.stories import _to_secret, _to_story  # noqa: E402
from app.security import hash_password  # noqa: E402

TITLE = "Grandmaster of Demonic Cultivation · The Soul-Guiding Lantern"
DEMO_EMAIL = "demo@linguisplay.app"
DEMO_PW = "demo12345"

CHARACTERS = [
    {
        "id": "mdze_wwx", "name": "Wei Wuxian", "role": "the Yiling Patriarch, returned from death",
        "is_lead": False, "playable": True,
        "avatar_url": "/scene/avatar/mdze_wwx.jpg",
        "persona_text": "Grins first, thinks later — the best tease in the cultivation world. "
        "But every third joke, something thirteen years deep flickers behind his eyes, "
        "gone before anyone can catch it.",
        "background": "Reborn in a borrowed body not long ago. Wherever he goes, a certain "
        "cold-faced Hanguang-jun goes too.",
        "items": [{"name": "Chenqing", "detail": "a black bamboo flute, its red tassel worn bright"}],
    },
    {
        "id": "mdze_lwj", "name": "Lan Wangji", "role": "Hanguang-jun, Second Young Master of Gusu Lan",
        "is_lead": True,
        "avatar_url": "/scene/avatar/mdze_lwj.jpg",
        "persona_text": "Forehead ribbon immaculate, white robes spotless, a day's worth of words "
        "countable on ten fingers. The cold is real — but he's the first to notice anyone's "
        "wound, and the one who silently pays for everyone's wine. Teased past his limit, "
        "his ears go red while his face doesn't move at all.",
        "background": "The world knows Hanguang-jun appears wherever the chaos is. No one knows "
        "how he spent the last thirteen years.",
        "eq_style": "speaks in single words; all care lands as action; never takes a joke's bait "
        "but remembers every line of it; falls silent when a truth is touched",
        "agenda": "This time, stay within arm's reach of him. But some words must wait until "
        "he says them first",
        "relation_default": "flirt",
        "relation_allowed": ["peer", "friend", "flirt", "lover"],
        "examples": [
            "Mn.",
            "No need. …Take it.",
            "Wei Ying.",
            "Ridiculous. …But if it makes you happy.",
            "The night is cold. Put this on.",
        ],
        "bio_layers": [
            {"closeness_min": 12, "text": "His quiet room burns one cold incense, year round. "
             "Sizhui says the blend hasn't changed in thirteen years."},
            {"closeness_min": 25, "text": "He carries old discipline-whip scars he lets no one "
             "see. A healer was allowed in exactly once."},
            {"closeness_min": 40, "text": "Alcohol is forbidden in the Cloud Recesses. Under "
             "the floor of his room, a whole row of Emperor's Smile lies buried."},
        ],
        "schedule": [
            {"from_act": 1, "location_id": "mdze_inn"},
            {"from_act": 2, "location_id": "mdze_path"},
            {"from_act": 3, "location_id": "mdze_shrine"},
            {"from_act": 4, "location_id": "mdze_jingshi"},
        ],
        "ties": [{"char_id": "mdze_szh", "stance": 2, "label": "the child he raised"},
                 {"char_id": "mdze_jl", "stance": 1, "label": "an old friend's nephew"},
                 {"char_id": "mdze_wn", "stance": 1, "label": "tolerated, for one person's sake"}],
    },
    {
        "id": "mdze_szh", "name": "Lan Sizhui", "role": "Gusu Lan junior, gentle and proper",
        "avatar_url": "/scene/avatar/mdze_szh.jpg",
        "persona_text": "Sixteen or seventeen, bows by the book, thinks three seconds before "
        "every sentence. Feels an unexplainable closeness to Wei Wuxian that he can't name.",
        "eq_style": "flawless manners, sharp eyes, sees through things and says nothing; "
        "forgets his rules only when worried",
        "agenda": "Solve the sleepwalker case — and quietly watch Hanguang-jun and Senior Wei. "
        "Everyone can see it. Except, apparently, the two of them",
        "examples": ["Senior Wei, your tea.", "Hanguang-jun, he… he has always… no. Forgive me, I misspoke."],
        "home_location_id": "mdze_inn",
        "schedule": [{"from_act": 1, "location_id": "mdze_inn"},
                     {"from_act": 2, "location_id": "mdze_path"},
                     {"from_act": 3, "location_id": "mdze_shrine"}],
        "ties": [{"char_id": "mdze_lwj", "stance": 2, "label": "the man who raised him"},
                 {"char_id": "mdze_wn", "stance": 2, "label": "a debt he can't speak of"},
                 {"char_id": "mdze_jl", "stance": 1, "label": "bickering peers"}],
    },
    {
        "id": "mdze_jl", "name": "Jin Ling", "role": "young master of Lanling Jin, all bark",
        "appears_from_act": 2,
        "avatar_url": "/scene/avatar/mdze_jl.jpg",
        "persona_text": "Gold brocade, spirit dog Fairy at his heel. Opens every sentence with "
        "a barb, detonates when poked somewhere soft, then shoves something nice at you "
        "sideways while pretending he didn't.",
        "eq_style": "tsundere to the bone; the only way he knows to care is loudly",
        "agenda": "Prove he can handle a case without his uncle — and keep an eye on this "
        "suspicious Wei fellow",
        "examples": ["Who asked you?! …Hey. That's for you. Since you didn't slow us down.", "Fairy — bite him!"],
        "home_location_id": "mdze_path",
        "ties": [{"char_id": "mdze_szh", "stance": 1, "label": "bickering friendship"}],
    },
    {
        "id": "mdze_wn", "name": "Wen Ning", "role": "the Ghost General, keeping to the shadows",
        "appears_from_act": 3,
        "avatar_url": "/scene/avatar/mdze_wn.jpg",
        "persona_text": "Pale, quiet, speaks like he's afraid of breaking something. Strong "
        "enough to tear down a mountain, too soft to argue with anyone. Only shows himself "
        "when Wei Wuxian is in danger.",
        "eq_style": "stammers; kindness he couldn't hide if he tried; thanked, he panics",
        "agenda": "Follow the young master from far enough away not to trouble him. There is "
        "one secret about Sizhui he promised never to tell",
        "examples": ["Young master… I, I'm fine.", "I'm sorry — I frightened you. I'll go now."],
        "home_location_id": "mdze_path",
        "ties": [{"char_id": "mdze_szh", "stance": 2, "label": "the child he watched grow"}],
    },
]

LOCATIONS = [
    {"id": "mdze_inn", "name": "Foothill Inn", "detail": "The innkeeper has fitted three bolts "
     "to the door and set an upturned bowl of rice on the counter. Everyone in the common "
     "room talks in whispers, and stops entirely at the word 'lantern'.",
     "exits": ["Mountain Road"]},
    {"id": "mdze_path", "name": "Mountain Road", "detail": "Flagstones black with night dew. "
     "Along the verge, rows of burnt-out paper lantern skeletons. The higher you climb, "
     "the fewer the crickets.",
     "exits": ["Foothill Inn", "Old Musicians' Shrine", "The Jingshi"]},
    {"id": "mdze_shrine", "name": "Old Musicians' Shrine", "detail": "A half-collapsed shrine "
     "to the god of music. From its beam hangs one white lantern in unsettling good repair. "
     "In the altar dust, two old flutes lie side by side — one long, one short.",
     "exits": ["Mountain Road"],
     "unlock": {"required_fragment_ids": ["mdze_case2"]},
     "props": [{"name": "soul-guiding lantern", "detail": "The lantern paper is covered in "
                "small dense writing, like a letter that was never sent.",
                "fragment_id": "mdze_case3"}]},
    {"id": "mdze_jingshi", "name": "The Jingshi", "detail": "Lan Wangji's quiet room, faint "
     "with cold incense. The qin table is spotless. Only an old wooden box in the corner "
     "sits oddly close to the bed.",
     "exits": ["Mountain Road"],
     "unlock": {"act_min": 4},
     "props": [{"name": "old wooden box", "detail": "Unlocked. Inside the lid, one character "
                "is carved — 羡 — cut deep, as if traced over many, many times.",
                "fragment_id": "mdze_thirteen3"}]},
]

ACTS = [
    {"id": "a1", "index": 1, "title": "The Sleepwalkers", "time": {"day": 1, "slot": "夜"},
     "goal": "Townsfolk keep sleepwalking up the mountain, white lanterns in hand. Start at "
             "the inn: find out where that lantern comes from",
     "advance": {"required_fragment_ids": ["mdze_case1"]},
     "events": [
         {"id": "mdze_e_sleepwalk", "what_happens": "Commotion in the common room: the peddler "
          "they carried home at noon is standing bolt upright again — a white lantern in his "
          "hand that no one saw him take.", "who_character_ids": []},
         {"id": "mdze_e_tea", "what_happens": "Lan Wangji sets a cup of hot tea in front of "
          "you, and without a flicker of expression moves the wine jar you'd been reaching "
          "for half a foot further away.", "who_character_ids": ["mdze_lwj"]},
     ]},
    {"id": "a2", "index": 2, "title": "Up the Mountain", "time": {"day": 2, "slot": "夜"},
     "goal": "Follow the sleepwalkers' trail up the road. Learn the story of the two "
             "musicians of the old shrine",
     "advance": {"required_fragment_ids": ["mdze_case2"]},
     "events": [
         {"id": "mdze_e_jl", "what_happens": "Jin Ling bursts out of a side path with Fairy, "
          "claiming to be 'just passing through' — while clutching the same paper talismans "
          "you carry.", "who_character_ids": ["mdze_jl"]},
         {"id": "mdze_e_shadow", "what_happens": "Far behind the group trails a shadow whose "
          "footsteps are too light for the living. Fairy growls at the dark, then goes "
          "strangely quiet.", "who_character_ids": []},
     ]},
    {"id": "a3", "index": 3, "title": "The Old Shrine", "time": {"day": 2, "slot": "夜"},
     "goal": "Enter the shrine. The lantern on the beam is covered in writing — read it",
     "advance": {"required_fragment_ids": ["mdze_case3"]},
     "events": [
         {"id": "mdze_e_duet", "what_happens": "No wind moves in the shrine, yet the two old "
          "flutes on the altar sound half a note together — like someone starting a phrase, "
          "waiting for someone else to answer it.", "who_character_ids": ["mdze_lwj"]},
     ]},
    {"id": "a4", "index": 4, "title": "Thirteen Years", "time": {"day": 3, "slot": "夜"},
     "goal": "The lantern guides 'the one who never came back'. But suddenly you need to know "
             "something else: how he spent the thirteen years you were dead",
     "advance": {"required_fragment_ids": ["mdze_thirteen3"]},
     "events": [
         {"id": "mdze_e_guqin", "what_happens": "Qin music from the Jingshi, all night long. "
          "The same melody, over and over. Only you would recognize it as Inquiry — the song "
          "that asks the dead a question.", "who_character_ids": ["mdze_lwj"]},
     ]},
    {"id": "a5", "index": 5, "title": "Who the Lantern Waits For", "time": {"day": 4, "slot": "夜"},
     "goal": "The obsession is resolved; the lantern should go out. It doesn't. It hangs "
             "between the two of you, waiting for a sentence",
     "choice": {
         "prompt": "The lantern light falls on Lan Wangji's face. He looks at you. The wind "
                   "lifts the ends of his forehead ribbon, and he does not look away.",
         "options": [
             {"id": "speak", "label": "\"Lan Zhan. Thirteen years of Inquiry — the one you "
              "kept asking for is standing right here.\"",
              "flag": "chose_speak", "character_id": "mdze_lwj",
              "closeness_delta": 4, "romance_delta": 6},
             {"id": "tease", "label": "Laugh it off: \"Hanguang-jun, I think the lantern "
              "fancies you.\"", "flag": "chose_tease"},
         ]},
     "events": [
         {"id": "mdze_e_lantern", "what_happens": "Down the whole mountainside, the burnt-out "
          "lantern skeletons rise upright and light themselves without fire — a river of "
          "lamps, seeing someone off.", "who_character_ids": ["mdze_lwj"]},
     ]},
]

# (title, character_id, sensitivity, known_by, [(fid, layer, content, retrieval_key, unlock, cover)])
SECRETS = [
    ("Where the lantern comes from", "mdze_szh", "light", ["mdze_szh", "mdze_lwj"], [
        ("mdze_case1", 1,
         "No one in town could have made the sleepwalkers' white lantern: the paper is "
         "thirty-year-old ledger stock, and the paste is cut with incense ash used only in "
         "rites for the dead. The old folk say one lantern exactly like it used to hang in "
         "the ruined musicians' shrine halfway up the mountain.",
         "lantern white lantern where from origin sleepwalk shrine come",
         {"affinity_min": 0, "act_min": 1, "asks_min": 2},
         "Just a common haunting. Burn the lanterns and it's done."),
        ("mdze_case2", 2,
         "Thirty years ago two musicians lived in the shrine: Pei Lang, who played the flute, "
         "and A-Ying, who played the qin. Their pact: lantern lit means waiting, lantern out "
         "means parted. Pei Lang went down for supplies and met a flash flood. A-Ying kept "
         "the lantern lit for seven years, feeding the oil until the day she died. The town "
         "sealed the shrine and never spoke of it again.",
         "musicians pei lang a-ying story pact thirty years waited lovers died",
         {"affinity_min": 8, "act_min": 2, "asks_min": 2},
         None),
        ("mdze_case3", 3,
         "The small writing on the lantern paper is A-Ying's: 'I don't blame the flood, or "
         "the long road. I blame myself — brave enough to light a lantern, never brave "
         "enough to say that waiting for you meant wanting a whole life beside you.' The "
         "lantern never guided anyone home. It searches, for everyone who swallowed the "
         "words, for the one who never came back.",
         "lantern paper writing read letter what does it say obsession",
         {"location_id": "mdze_shrine", "act_min": 3},
         None),
    ]),
    ("Lan Wangji's thirteen years", "mdze_lwj", "heavy", ["mdze_lwj", "mdze_szh"], [
        ("mdze_thirteen1", 1,
         "Sizhui once let it slip: Hanguang-jun was gravely wounded and spent three full "
         "years in seclusion, seeing no one — not even the Sect Leader. Those three years "
         "count exactly from the fall of the Burial Mounds.",
         "thirteen years three years seclusion wounded past how did you live",
         {"affinity_min": 10, "act_min": 2, "asks_min": 2},
         "Hanguang-jun's affairs are not for outsiders to ask."),
        ("mdze_thirteen2", 2,
         "Thirteen years of Inquiry. Every year, every rumor of a restless spirit anywhere "
         "in the world, he went and played the question. It was always the same name. "
         "Thirteen years without a single answer — because the one he was asking for never "
         "became a ghost at all. He came back.",
         "inquiry who were you asking for looking for me why wait",
         {"affinity_min": 18, "act_min": 4, "asks_min": 3},
         None),
        ("mdze_thirteen3", 3,
         "Inside the old wooden box: half a burnt red flute tassel, and a sheet of paper "
         "written over and crossed out, again and again. It holds nothing but the opening "
         "fingering of Inquiry, with one small note beside it: 'If there is ever an answer — "
         "what to say first.' Thirteen years, and he had rehearsed even the first sentence.",
         "wooden box jingshi what's inside open hiding",
         {"location_id": "mdze_jingshi", "act_min": 4},
         None),
    ]),
    ("The shadow in the dark", "mdze_wn", "light", ["mdze_wn", "mdze_szh"], [
        ("mdze_wn1", 1,
         "The shadow trailing the group at night is Wen Ning. He never went far. Afraid of "
         "frightening people, he stays out of sight — quietly snapping in half whatever "
         "crawls onto the road before it ever reaches you.",
         "shadow following behind who footsteps dark",
         {"affinity_min": 0, "act_min": 2, "asks_min": 1},
         None),
    ]),
]

ENDINGS = [
    {"id": "mdze_end_true", "kind": "true", "title": "The Inquiry Is Answered",
     "text": "The lantern goes out the moment you finish speaking. In the dark, Lan Wangji's "
             "voice is close against your ear, steady enough to frighten you: 'The first "
             "sentence. I rehearsed it for thirteen years.' A pause — a lifetime pressed "
             "into two words. 'Stay close.' Down the mountain, the river of lamps lights "
             "up length by length: for two musicians, and for the two of you, walking the "
             "rest of the road that never got finished.",
     "condition": {"affinity_min": 24, "act_min": 0,
                   "required_fragment_ids": ["mdze_thirteen3"],
                   "required_flags": {"chose_speak": True}}},
    {"id": "mdze_end_normal", "kind": "normal", "title": "Down the Mountain, Side by Side",
     "text": "The lantern dims slowly under your joke, like a sigh. Neither of you speaks on "
             "the way down, but your shoulders ride closer than they did coming up. At the "
             "foot of the mountain Lan Wangji stops and presses something into your hand — "
             "the half-burnt red tassel. He says nothing. You think: someone is going to say "
             "it out loud, sooner or later.",
     "condition": {"act_min": 0, "required_flags": {"chose_tease": True}}},
    {"id": "mdze_end_rumor", "kind": "bad", "title": "The Rumor Spreads", "trigger": "pressure",
     "text": "'The Yiling Patriarch has returned' burns through the town faster than any "
             "lantern. The looks change; sect messenger-cranes arrive one after another. You "
             "pack by night, flute at your belt — and find a figure in white standing in the "
             "doorway, sword in his arms, blocking the only road. He still says nothing. But "
             "this time, he has no intention of letting you leave alone.",
     "condition": {}},
]

PRESSURE = {"name": "Rumors", "hint": "Word of the Yiling Patriarch is fermenting in town — "
            "the louder you play, the faster it burns",
            "ending_id": "mdze_end_rumor",
            "levels": [{"at": 40, "note": "At the tea stall, someone lowers their voice: that "
                        "flute melody… sounded like the Burial Mounds, back then."},
                       {"at": 70, "note": "The innkeeper's face has changed — suddenly there "
                        "are no rooms. Outside, sect men are copying down a portrait."}]}


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
            owner_id=user.id, title=TITLE, language="en",
            one_liner="Thirteen years of Inquiry. Tonight, the lantern guides 'the one who never came back'.",
            synopsis="Townsfolk keep sleepwalking up the mountain with white lanterns in "
            "hand. Play as Wei Wuxian, night-hunting beside Lan Wangji, unraveling the "
            "soul-guiding lantern — the obsession of two musicians who never said the "
            "words. The deeper the case goes, the clearer it becomes whose swallowed "
            "words the lantern is really looking for. (Fan homage · original case · "
            "god mode available for shippers)",
            world_long="A cultivation world; the small town below the Cloud Recesses. Deep "
            "night, white lanterns, sleepwalkers. An inn, a mountain road, a half-collapsed "
            "musicians' shrine — and, up the mountain, a quiet room whose cold incense has "
            "not changed in thirteen years.",
            world_facts="Four places: Foothill Inn (start) connects to Mountain Road; the "
            "road leads to the Old Musicians' Shrine and the Jingshi. The shrine can only "
            "be found after learning the musicians' story; the Jingshi opens in act 4. "
            "Wei Wuxian carries the flute Chenqing. The sleepwalkers' white lanterns and "
            "the shrine lantern share one origin.",
            relations_overview="Wei Wuxian (you) and Lan Wangji, mutually understood and "
            "mutually unspoken; Lan Sizhui was raised by Lan Wangji and feels an unexplained "
            "closeness to Wei Wuxian; Jin Ling is all bark; Wen Ning guards from the shadows.",
            trope_tags=["BL", "yaoi", "danmei", "xianxia", "mystery", "mutual pining", "fan work"],
            characters=CHARACTERS, acts=ACTS, endings=ENDINGS, locations=LOCATIONS,
            pressure=PRESSURE, phone={"enabled": True, "device": "message talisman"},
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
        print(f"OK seeded <{TITLE}> story_id={story.id} secrets={len(SECRETS)} fragments={n_frag}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
