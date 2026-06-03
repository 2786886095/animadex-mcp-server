"""
AnimaDex — Web UI + MCP Server on Hugging Face Spaces.
"""

import asyncio
import json
import os
import re
from typing import Any

import httpx
from urllib.parse import quote as _url_enc
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

BASE_URL = os.environ.get("ANIMADEX_API_BASE", "https://animadex.net")
API_TIMEOUT = int(os.environ.get("ANIMADEX_API_TIMEOUT", "30"))
USER_AGENT = "animadex-mcp/1"
EXPORT_TOKEN = os.environ.get("ANIMADEX_TOKEN", "IPpCh4IE4iMAVaeuREs4WqiXynSti60pWAxpcd-nXRQ")
TRANSLATOR = os.environ.get("ANIMADEX_TRANSLATOR", "google")
AI_TRANSLATE_URL = os.environ.get("ANIMADEX_AI_TRANSLATE_URL", "")
AI_TRANSLATE_MODEL = os.environ.get("ANIMADEX_AI_MODEL", "qwen2.5:7b")
AI_API_KEY = os.environ.get("ANIMADEX_AI_API_KEY", "")

_client = httpx.Client(base_url=BASE_URL, headers={"User-Agent": USER_AGENT}, timeout=httpx.Timeout(API_TIMEOUT, connect=3), verify=False)

server = FastMCP("AnimaDex", instructions="Query animadex.net characters, artists and series data",
                 transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False))


def _get(path: str, **params) -> dict:
    try:
        r = _client.get(path, params=params)
        r.raise_for_status()
        return r.json()
    except Exception as e:
        print(f"[api] Request failed: {e}")
        raise


# ── Full character name index ──────────────────────────────────────────
# Populated on startup by fetching the export manifest + index.

CHAR_INDEX: dict[str, str] = {}
CHAR_SLUGS: dict[str, list[str]] = {}
_TRANS_CACHE: dict[str, str] = {}
LOCAL_DB = None
LOCAL_READY = False
API_CACHE: dict[str, dict] = {}
import hashlib as _hl



def _init_local_db():
    """Download full CSV and build SQLite DB for offline search."""
    global LOCAL_DB, LOCAL_READY
    import sqlite3, csv, io, time
    db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "animadex.db")
    os.makedirs(os.path.dirname(db_path), exist_ok=True)

    if os.path.exists(db_path) and (time.time() - os.path.getmtime(db_path)) < 86400:
        try:
            LOCAL_DB = sqlite3.connect(db_path, check_same_thread=False)
            LOCAL_DB.execute("SELECT COUNT(*) FROM characters")
            print(f"[local] Using cached DB ({os.path.getsize(db_path)//1024} KB)")
            LOCAL_READY = True
            return
        except:
            pass

    print("[local] Downloading character database...")
    try:
        h = {"X-Export-Token": EXPORT_TOKEN}
        r = _client.get("/api/export/manifest", headers=h, timeout=30)
        if r.status_code != 200:
            return
        man = r.json()
        csv_url = man.get("csv", {}).get("characters", "")
        if not csv_url:
            return

        r2 = _client.get(csv_url, timeout=120)
        if r2.status_code != 200:
            return

        reader = csv.DictReader(io.StringIO(r2.text))
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("""CREATE TABLE IF NOT EXISTS characters (
            slug TEXT PRIMARY KEY, name TEXT, trigger TEXT, tags TEXT,
            copyright TEXT, copyright_name TEXT, count INTEGER DEFAULT 0,
            thumb_url TEXT, img_url TEXT
        )""")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_name ON characters(name)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trig ON characters(trigger)")

        count = 0
        for row in reader:
            slug = row.get("character") or row.get("slug") or ""
            if not slug:
                continue
            trigger = row.get("trigger", "")
            # Generate thumb_url from trigger
            from urllib.parse import quote
            trigger_enc = quote(trigger, safe='()')
            thumb_url = f"https://blobs.animadex.net/Outputs/thumbs/{trigger_enc}.webp"
            conn.execute("INSERT OR REPLACE INTO characters (slug,name,trigger,tags,copyright,copyright_name,count,thumb_url,img_url) VALUES (?,?,?,?,?,?,?,?,?)",
                (slug, row.get("name", slug.replace("_"," ").title()), trigger,
                 row.get("tags",""), row.get("copyright",""), row.get("copyright_name",""),
                 int(row.get("count",0)), thumb_url, ""))
            count += 1
            if count % 5000 == 0:
                conn.commit()
                print(f"[local] ... {count}")
        conn.commit()
        print(f"[local] Loaded {count} characters")
        LOCAL_DB = conn
        LOCAL_READY = True
    except Exception as e:
        print(f"[local] DB build failed: {e}")
        if os.path.exists(db_path):
            os.remove(db_path)


def _local_search(q, mode="characters", page=1, page_size=36):
    """Search local SQLite database."""
    global LOCAL_DB
    if LOCAL_DB is None:
        return {"total": 0, "results": []}
    try:
        cur = LOCAL_DB.cursor()
        like = f"%{q.lower()}%"
        cur.execute("SELECT slug,name,trigger,tags,copyright_name,count,thumb_url,img_url FROM characters WHERE LOWER(name) LIKE ? OR LOWER(trigger) LIKE ? OR LOWER(copyright_name) LIKE ? ORDER BY count DESC LIMIT ? OFFSET ?",
            (like, like, like, page_size, (page-1)*page_size))
        rows = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM characters WHERE LOWER(name) LIKE ? OR LOWER(trigger) LIKE ? OR LOWER(copyright_name) LIKE ?", (like, like, like))
        total = cur.fetchone()[0]
        results = []
        for r in rows:
            tags_list = [t.strip() for t in (r[3] or "").split(",") if t.strip()]
            results.append({"slug":r[0],"name":r[1],"trigger":r[2],"tags":tags_list,"copyright_name":r[4] or "","count":r[5] or 0,"thumb_url":r[6] or "","img_url":r[7] or "","rating":{"up":0,"down":0},"fav_count":0})
        return {"total":total,"results":results,"page":page,"page_size":page_size,"pages":max(1,(total+page_size-1)//page_size)}
    except Exception as e:
        return {"total":0,"results":[],"error":str(e)}


def _build_index():

    global BASE_URL
    # Check if Chinese users need a mirror
    if os.environ.get("ANIMADEX_MIRROR"):
        BASE_URL = os.environ["ANIMADEX_MIRROR"]
        _client.base_url = BASE_URL
    """Fetch ALL character names and build a searchable index.
    Tries export index first, then falls back to the API character list."""
    try:
        h = {"X-Export-Token": EXPORT_TOKEN}
        r = _client.get("/api/export/manifest", headers=h, timeout=30)
        if r.status_code == 200:
            man = r.json()
            idx_url = man.get("index_url")
            if idx_url:
                idx_r = _client.get(idx_url, timeout=60)
                if idx_r.status_code == 200:
                    _populate_from_idx(idx_r.json())
                    return
        print("[index] Export manifest unavailable, falling back to API...")
    except Exception as e:
        print(f"[index] Export failed ({e}), falling back to API...")

    try:
        _populate_from_api()
    except Exception as e:
        print(f"[index] API fallback failed: {e}")


def _populate_from_idx(idx: dict):
    chars = idx.get("chars", {})
    for slug in chars:
        name = slug.replace("_", " ").replace("(", "").replace(")", "").title()
        CHAR_INDEX[slug] = name
        key = name.lower()
        CHAR_SLUGS.setdefault(key, []).append(slug)
        parts = slug.replace("_", " ").replace("(", " ").replace(")", " ").split()
        for p in parts:
            if len(p) > 3:
                CHAR_SLUGS.setdefault(p.lower(), []).append(slug)
    print(f"[index] Loaded {len(CHAR_INDEX)} characters from export index")


def _populate_from_api(max_pages: int = 50):
    """Fetch characters from the regular search API (paginated).
    Fetches up to max_pages (default 50 = ~1800 chars) as fallback."""
    page, total_pages = 1, None
    while page <= max_pages:
        data = _get("/api/characters/search", q="", page=page, sort="count")
        results = data.get("results", [])
        if not results:
            break
        if total_pages is None:
            total_pages = min(data.get("pages", 1), max_pages)

        for r in results:
            slug, name = r["slug"], r["name"]
            CHAR_INDEX[slug] = name
            CHAR_SLUGS.setdefault(name.lower(), []).append(slug)
            for p in slug.replace("_", " ").replace("(", " ").replace(")", " ").split():
                if len(p) > 2:
                    CHAR_SLUGS.setdefault(p.lower(), []).append(slug)

        if page >= total_pages:
            break
        page += 1

    print(f"[index] Loaded {len(CHAR_INDEX)} characters via API ({page} pages)")


def _cn_to_en_via_api(text: str) -> str:
    """Translate Chinese to English. Supports Google and AI backends."""
    if TRANSLATOR == "ai" and AI_TRANSLATE_URL:
        return _ai_translate(text)
    # Default: Google Translate (verify=False for Python 3.14 SSL compat)
    try:
        url = f"https://translate.googleapis.com/translate_a/single?client=gtx&sl=zh-CN&tl=en&dt=t&q={_url_enc(text)}"
        with httpx.Client(verify=False, timeout=5, headers={"User-Agent": USER_AGENT}) as _gc:
            r = _gc.get(url)
            if r.status_code == 200:
                parts = r.json()
                result = ""
                for p in parts[0]:
                    if p[0]:
                        result += p[0]
                return result.strip()
    except Exception:
        pass
    return text


def _ai_translate(text: str) -> str:
    """Translate via AI endpoint (Ollama / OpenAI-compatible)."""
    try:
        _nl = "\n"
        prompt = f'Translate this Chinese anime/game character name to English. Return ONLY the English name, nothing else:{_nl}{text}'
        payload = {"model": AI_TRANSLATE_MODEL, "prompt": prompt, "stream": False}
        r = _client.post(AI_TRANSLATE_URL, json=payload, timeout=30)
        if r.status_code == 200:
            data = r.json()
            result = data.get("response", "") or data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if result:
                result = result.strip()
                _TRANS_CACHE[text] = result
                return result
    except Exception:
        pass
    _TRANS_CACHE[text] = text
    return text

def _ai_translate_with_config(text: str, cfg: dict) -> str:
    """Translate using API config from frontend settings. Cached."""
    if text in _TRANS_CACHE:
        return _TRANS_CACHE[text]
    try:
        url = cfg.get("url", "https://api.deepseek.com/v1/chat/completions")
        model = cfg.get("model", "deepseek-chat")
        key = cfg.get("key", "")
        h = {"Content-Type": "application/json"}
        if key:
            h["Authorization"] = f"Bearer {key}"
        import httpx
        r = httpx.post(url, json={"model": model, "messages": [{"role": "user", "content": f"Translate this Chinese anime/game character name to English. Return ONLY the English name: {text}"}], "stream": False}, headers=h, timeout=10)
        if r.status_code == 200:
            result = r.json().get("choices", [{}])[0].get("message", {}).get("content", "")
            if result:
                result = result.strip()
                _TRANS_CACHE[text] = result
                return result
    except Exception:
        pass
    _TRANS_CACHE[text] = text
    return text


def _match_chinese(query: str, api_config: dict | None = None) -> str | None:
    """Find English name for Chinese query. Fast paths first, then AI."""
    q = query.strip().lower()

    # 1. CN_MAP exact (instant)
    if q in CN_MAP:
        return CN_MAP[q]

    # 2. CN_MAP partial (instant)
    for cn, en in CN_MAP.items():
        if cn in q or q in cn:
            return en

    # 3. Already ASCII → no translation needed
    if all(ord(c) < 128 for c in q):
        return None

    # 4. AI translation (slow, cached after first use)
    if api_config:
        result = _ai_translate_with_config(query, api_config)
        if result and result != q:
            return result.lower()

    # 5. Google Translate fallback
    translated = _cn_to_en_via_api(q)
    if translated and translated != q and translated.strip():
        return translated.strip().lower()

    return None


def cn_search(query: str, mode: str = "characters", page: int = 1, sort: str = "count", api_config: dict | None = None) -> dict:
    """Search with Chinese name support. Uses local DB when possible."""
    translated = _match_chinese(query, api_config)
    search_q = translated if translated else query
    if mode == "characters" and LOCAL_READY:
        try:
            data = _local_search(search_q, mode, page)
            data["translated"] = translated if translated and translated != query else None
            if data["total"] > 0:
                # Check if results have thumbnails
                has_thumbs = any(r.get("thumb_url") for r in data.get("results", []))
                if has_thumbs:
                    return data
                # No thumbnails in local DB, try API for richer data
        except:
            pass
    try:
        data = _get(f"/api/{mode}/search", q=search_q, page=page, sort=sort)
        data["translated"] = translated if translated and translated != query else None
        return data
    except Exception as e:
        return {"error": str(e), "results": [], "total": 0}


# ── Chinese name mapping (popular characters) ──────────────────────────
CN_MAP = {
    "雷电将军": "raiden shogun", "雷神": "raiden shogun", "将军": "raiden shogun", "雷电": "raiden shogun",
    "钟离": "zhongli", "岩神": "zhongli", "岩王帝君": "zhongli", "摩拉克斯": "zhongli",
    "温迪": "venti", "风神": "venti", "巴巴托斯": "venti",
    "纳西妲": "nahida", "草神": "nahida", "小吉祥草王": "nahida",
    "芙宁娜": "furina", "水神": "furina", "芙芙": "furina",
    "胡桃": "hu tao", "胡堂主": "hu tao",
    "甘雨": "ganyu",
    "刻晴": "keqing", "阿晴": "keqing",
    "神里绫华": "ayaka", "绫华": "ayaka",
    "宵宫": "yoimiya",
    "八重神子": "yae miko", "神子": "yae miko",
    "万叶": "kazuha", "枫原万叶": "kazuha",
    "夜兰": "yelan",
    "神里绫人": "ayato",
    "黄泉": "acheron",
    "流萤": "firefly", "萨姆": "firefly",
    "镜流": "jingliu",
    "卡芙卡": "kafka",
    "银狼": "silver wolf",
    "花火": "sparkle",
    "黑天鹅": "black swan",
    "知更鸟": "robin",
    "博丽灵梦": "hakurei reimu",
    "雾雨魔理沙": "kirisame marisa",
    "十六夜咲夜": "izayoi sakuya",
    "蕾米莉亚": "remilia scarlet",
    "八云紫": "yakumo yukari",
    "魂妖梦": "konpaku youmu",
    "琪露诺": "cirno",
    "爱丽丝": "alice margatroid",
    "帕秋莉": "patchouli knowledge",
    "藤原妹红": "fujiwara no mokou",
    "初音未来": "hatsune miku",
    "阿尔托莉雅": "artoria pendragon",
    "鹿目圆": "kaname madoka",
    "晓美焰": "akemi homura",
    "御坂美琴": "misaka mikoto",
    "亚丝娜": "asuna",
    "五河琴里": "kotori itsuka",
    "时崎狂三": "kurumi tokisaki",
    "可莉": "klee",
    "七七": "qiqi",
    "琴": "jean",
    "莫娜": "mona",
    "迪卢克": "diluc",
    "魈": "xiao",
    "申鹤": "shenhe",
    "荒泷一斗": "araki itto",
    "久岐忍": "kuki shinobu",
    "流浪者": "wanderer",
    "散兵": "wanderer",
    "艾尔海森": "alhaitham",
    "娜维娅": "navia",
    "克洛琳德": "clorinde",
    "希格雯": "sigewinne",
    "莱欧斯利": "wriothesley",
    "那维莱特": "neuvillette",
    "纳维莱特": "neuvillette",
    "妮露": "nilou",
    "赛诺": "cyno",
    "提纳里": "tighnari",
    "达达利亚": "tartaglia",
    "公子": "tartaglia",
    "香菱": "xiangling",
    "行秋": "xingqiu",
    "菲谢尔": "fischl",
    "班尼特": "bennett",
    "重云": "chongyun",
    "凝光": "ningguang",
    "北斗": "beidou",
    "烟绯": "yanfei",
    "罗莎莉亚": "rosaria",
    "凯亚": "kaeya",
    "丽莎": "lisa",
    "安柏": "amber",
    "芭芭拉": "barbara",
    "砂糖": "sucrose",
    "迪奥娜": "diona",
    "诺艾尔": "noelle",
    "雷泽": "razor",
    "优菈": "eula",
    "阿贝多": "albedo",
    "珊瑚宫心海": "kokomi",
    "心海": "kokomi",
    "托马": "thoma",
    "早柚": "sayu",
    "五郎": "gorou",
    "云堇": "yun jin",
    "九条裟罗": "kujou sara",
    "珐露珊": "faruzan",
    "鹿野院平藏": "shikanoin heizou",
    "绮良良": "kirara",
    "琳妮特": "lynette",
    "林尼": "lyney",
    "菲米尼": "freminet",
    "莱依拉": "layla",
    "卡维": "kaveh",
    "白术": "baizhu",
    "坎蒂丝": "candace",
    "多莉": "dori",
    "柯莱": "collei",
    "瑶瑶": "yaoyao",
    "刃": "blade",
    "布洛妮娅": "bronya",
    "希儿": "seele",
    "丹恒": "dan heng",
    "三月七": "march 7th",
    "姬子": "himeko",
    "瓦尔特": "welt",
    "白露": "bailu",
    "停云": "tingyun",
    "驭空": "yukong",
    "素裳": "sushang",
    "青雀": "qingque",
    "景元": "jing yuan",
    "彦卿": "yanqing",
    "罗刹": "luocha",
    "符玄": "fu xuan",
    "玲可": "lynx",
    "桂乃芬": "guinaifen",
    "托帕": "topaz",
    "账账": "numby",
    "银枝": "argenti",
    "藿藿": "huohuo",
    "寒鸦": "hanya",
    "雪衣": "xueyi",
    "真理医生": "dr ratio",
    "砂金": "aventurine",
    "星期日": "sunday",
    "波提欧": "boothill",
    "翡翠": "jade",
    "云璃": "yunli",
    "椒丘": "jiaqiu",
    "飞霄": "feixiao",
    "灵砂": "lingsha",
    "乱破": "rappa",
    "忘归人": "fugue",
    "遐蝶": "castorice",
    "阿格莱雅": "aglaea",
    "缇宝": "tribbie",
    "万敌": "mydei",
    "白厄": "phainon",
    "那刻夏": "anaxa",
    "琪亚娜": "kiana",
    "雷电芽衣": "raiden mei",
    "八重樱": "yae sakura",
    "布洛妮娅扎伊切克": "bronya zaychik",
    "德丽莎": "theresa",
    "符华": "fu hua",
    "丽塔": "rita rossweisse",
    "幽兰黛尔": "durandal",
    "爱莉希雅": "elysia",
    "识之律者": "herrscher of sentience",
    "博丽灵梦": "hakurei reimu",
    "雾雨魔理沙": "kirisame marisa",
    "十六夜咲夜": "izayoi sakuya",
    "蕾米莉亚": "remilia scarlet",
    "芙兰朵露": "flandre scarlet",
    "八云紫": "yakumo yukari",
    "八云蓝": "yakumo ran",
    "魂魄妖梦": "konpaku youmu",
    "西行寺幽幽子": "saigyouji yuyuko",
    "射命丸文": "shameimaru aya",
    "东风谷早苗": "kochiya sanae",
    "古明地觉": "komeiji satori",
    "古明地恋": "komeiji koishi",
    "琪露诺": "cirno",
    "红美铃": "hong meiling",
    "铃仙": "reisen udongein inaba",
    "因幡帝": "inaba tewi",
    "藤原妹红": "fujiwara no mokou",
    "蓬莱山辉夜": "houraisan kaguya",
    "比那名居天子": "hinanawi tenshi",
    "圣白莲": "byakuren hijiri",
    "伊吹萃香": "ibuki suika",
    "茨木华扇": "ibaraki kasen",
    "橙": "chen",
    "初音未来": "hatsune miku",
    "镜音铃": "kagamine rin",
    "镜音连": "kagamine len",
    "巡音流歌": "megurine luka",
    "阿尔托莉雅": "artoria pendragon",
    "吾王": "artoria pendragon",
    "吉尔伽美什": "gilgamesh",
    "金闪闪": "gilgamesh",
    "远坂凛": "tosaka rin",
    "间桐樱": "matou sakura",
    "卫宫士郎": "emiya shirou",
    "卫宫": "emiya",
    "贞德": "jeanne d'arc",
    "尼禄": "nero",
    "玉藻前": "tamamo no mae",
    "斯卡哈": "scathach",
    "库丘林": "cu chulainn",
    "梅林": "merlin",
    "摩根": "morgan",
    "伊莉雅": "illyasviel",
    "鹿目圆": "kaname madoka",
    "晓美焰": "akemi homura",
    "美树沙耶香": "miki sayaka",
    "巴麻美": "tomoe mami",
    "佐仓杏子": "sakura kyoko",
    "御坂美琴": "misaka mikoto",
    "亚丝娜": "asuna",
    "五河琴里": "kotori itsuka",
    "时崎狂三": "kurumi tokisaki",
    "企业": "enterprise",
    "欧根亲王": "prinz eugen",
    "俾斯麦": "bismarck",
    "贝尔法斯特": "belfast",
    "吹雪": "fubuki",
    "岛风": "shimakaze",
    "大和": "yamato",
    "武藏": "musashi",
    "雪风": "yukikaze",
    "时雨": "shigure",
    "阿米娅": "amiya",
    "德克萨斯": "texas",
    "能天使": "exusiai",
    "银灰": "silverash",
    "艾雅法拉": "eyjafjalla",
    "塞雷娅": "saria",
    "推进之王": "siege",
    "星熊": "hoshiguma",
    "夜莺": "nightingale",
    "闪灵": "shining",
    "斯卡蒂": "skadi",
    "凯尔希": "kal'tsit",
    "漂泊者": "rover",
    "秧秧": "yangyang",
    "忌炎": "jiyan",
    "吟霖": "yinlin",
    "今汐": "jinhsi",
    "长离": "changli",
    "折枝": "zhezhi",
    "守岸人": "shorekeeper",
    "椿": "camellya",
    "安比": "anby",
    "妮可": "nicole",
    "猫又": "nekomiya mana",
    "朱鸢": "zhu yuan",
    "艾莲": "ellen joe",
    "露西": "lucy",
    "丽娜": "rina",
    "白子": "shiroko",
    "星野": "hoshino",
    "日奈": "hina",

    # Series / games (for series search)
    "原神": "genshin impact",
    "崩坏星穹铁道": "honkai star rail",
    "崩坏3": "honkai impact 3rd",
    "崩坏": "honkai",
    "东方": "touhou",
    "东方project": "touhou",
    "绝区零": "zenless zone zero",
    "鸣潮": "wuthering waves",
    "碧蓝航线": "azur lane",
    "明日方舟": "arknights",
    "蔚蓝档案": "blue archive",
    "少女前线": "girls frontline",
    "公主连结": "princess connect",
    "赛马娘": "umamusume",
    "偶像大师": "idolmaster",
    "命运冠位指定": "fate",
    "fgo": "fate",
    "舰队collection": "kantai collection",
    "舰队收藏": "kantai collection",
    "战舰少女": "warship girls",
    "胜利女神": "nikke",
    "nikkke": "nikke",
    "宝可梦": "pokemon",
    "pokemon": "pokemon",
    "鬼灭之刃": "demon slayer",
    "咒术回战": "jujutsu kaisen",
    "进击的巨人": "attack on titan",
    "eva": "evangelion",
    "新世纪福音战士": "evangelion",
    "火影忍者": "naruto",
    "海贼王": "one piece",
    "死神": "bleach",
    "龙珠": "dragon ball",
    "最终幻想": "final fantasy",
    "塞尔达": "zelda",
    "miku": "hatsune miku",
    # Series name variants (for series/copyright mode)
    "星穹铁道": "star rail", "星铁": "star rail",
    "原神": "genshin impact",
    "崩坏3": "honkai impact 3rd",
    "崩坏三": "honkai impact 3rd",
    "绝区零": "zenless zone zero",
    "zzz": "zenless zone zero",
    "明日方舟": "arknights",
    "碧蓝航线": "azur lane",
    "蔚蓝档案": "blue archive",
    "少女前线": "girls frontline",
    "东方project": "touhou",
    "舰c": "kantai collection",
    "舰娘": "kantai collection",
    "fgo": "fate grand order",
    "赛马娘": "umamusume",
    "偶像大师": "idolmaster",
    "宝可梦": "pokemon",
    "鬼灭": "demon slayer",
    "火影": "naruto",
    "海贼": "one piece",
    "龙珠": "dragon ball",
}



# ── MCP Tools ──────────────────────────────────────────────────────────

@server.tool(name="search-characters",
             description="搜索角色，返回名称、触发词(trigger/prompt)、标签等")
def search_characters(query: str = "", page: int = 1, sort: str = "count") -> str:
    eng = _match_chinese(query)
    if eng:
        query = eng
    data = _get("/api/characters/search", q=query, page=page, sort=sort)
    results = data.get("results", [])
    if not results:
        return "未找到匹配的角色。"
    lines = [f"共 {data['total']:,} 个角色，当前第 {page}/{data['pages']} 页\n"]
    for r in results:
        lines.append(
            f"  • **{r['name']}** ({r['copyright_name']})\n"
            f"    触发词: `{r['trigger']}`\n"
            f"    图片数: {r['count']:,}  "
            f"标签: {', '.join(r['tags'][:8])}{'...' if len(r['tags']) > 8 else ''}\n"
        )
    return "\n".join(lines)


@server.tool(name="get-character",
             description="获取单个角色的详细信息，包括完整触发词、标签、关联LoRA等")
def get_character(slug: str) -> str:
    data = _get("/api/characters/search", q=slug, page=1)
    for r in data.get("results", []):
        if r["slug"] == slug:
            lines = [
                f"## {r['name']}\n",
                f"**系列：** {r['copyright_name']}\n",
                f"**🎯 Prompt Trigger：**\n```\n{r['trigger']}\n```\n",
                f"**🏷️ 标签：** {', '.join(r['tags'])}\n\n",
                f"**📊 图片数：** {r['count']:,}\n",
            ]
            if r.get("loras"):
                lines.append("\n**🧩 关联 LoRA：**\n")
                for lora in r["loras"]:
                    lines.append(f"  • [{lora['name']}]({lora['url']})\n")
            return "\n".join(lines)
    return f"未找到 slug 为 '{slug}' 的角色。"


@server.tool(name="search-artists", description="搜索画师，返回名称和触发词")
def search_artists(query: str = "", page: int = 1) -> str:
    data = _get("/api/artists/search", q=query, page=page)
    results = data.get("results", [])
    if not results:
        return "未找到匹配的画师。"
    lines = [f"共 {data['total']:,} 个画师，第 {page}/{data['pages']} 页\n"]
    for r in results:
        lines.append(f"  • **{r['name']}** — trigger: `{r['trigger']}` — {r['count']:,} 图\n")
    return "\n".join(lines)


@server.tool(name="search-copyrights", description="搜索系列/版权")
def search_copyrights(query: str = "", page: int = 1) -> str:
    data = _get("/api/copyrights/search", q=query, page=page)
    results = data.get("results", [])
    if not results:
        return "未找到匹配的系列。"
    lines = [f"共 {data['total']:,} 个系列，第 {page}/{data['pages']} 页\n"]
    for r in results:
        lines.append(f"  • **{r['name']}** — {r['count']} 个角色\n")
    return "\n".join(lines)


@server.tool(name="get-character-facets", description="获取角色筛选条件")
def get_character_facets() -> str:
    data = _get("/api/characters/facets")
    facets = data.get("facets", {})
    lines = [f"共 {data['total']:,} 个角色，可用筛选条件：\n"]
    for name, values in facets.items():
        lines.append(f"\n**{name}：**\n")
        for v in values.get("values", [])[:10]:
            lines.append(f"  • {v['label']} ({v['count']})")
    return "\n".join(lines)


# ── Web UI ──────────────────────────────────────────────────────────────

HTML_PAGE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AnimaDex · 角色提示词搜索 v2.1</title><meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate"><meta http-equiv="Pragma" content="no-cache"><meta http-equiv="Expires" content="0">
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;background:#0d0d1a;color:#e0e0e0;min-height:100vh}
  .container{max-width:1400px;margin:0 auto;padding:20px 16px 90px}
  header{display:flex;align-items:center;gap:12px;margin-bottom:16px;flex-wrap:wrap}
  header h1{font-size:26px;font-weight:700;background:linear-gradient(135deg,#a78bfa,#ec4899);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
  header small{color:#888;font-size:13px}
  .search-bar{display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap}
  .search-bar input{flex:1;min-width:180px;padding:11px 16px;border-radius:10px;border:1px solid #333;background:#1a1a2e;color:#e0e0e0;font-size:15px;outline:none;transition:border .2s}
  .search-bar input:focus{border-color:#a78bfa}
  .search-bar select{padding:0 12px;border-radius:10px;border:1px solid #333;background:#1a1a2e;color:#e0e0e0;font-size:13px;outline:none}
  .search-bar button{padding:11px 24px;border-radius:10px;border:none;background:linear-gradient(135deg,#a78bfa,#ec4899);color:#fff;font-size:15px;font-weight:600;cursor:pointer;transition:transform .15s}
  .search-bar button:hover{transform:translateY(-1px)}
  .stats{color:#888;font-size:13px}
  .stats .trans{color:#f0c060}
  .toolbar{display:flex;align-items:center;gap:12px;margin-bottom:12px;flex-wrap:wrap;font-size:13px}
  .col-picker{display:flex;gap:3px;align-items:center;margin-left:auto}
  .col-picker span{color:#666;font-size:11px;margin-right:2px}
  .col-btn{padding:3px 8px;border-radius:5px;border:1px solid #333;background:transparent;color:#888;font-size:11px;cursor:pointer;transition:all .2s}
  .col-btn:hover{border-color:#666;color:#ccc}
  .col-btn.on{background:#a78bfa22;border-color:#a78bfa;color:#a78bfa}
  #results{display:grid;gap:16px;grid-template-columns:repeat(var(--cols,4),1fr)}
  .card{background:#1a1a2e;border:2px solid transparent;border-radius:12px;overflow:hidden;transition:all .2s;position:relative;cursor:pointer}
  .card:hover{border-color:#a78bfa55}
  .card.selected{border-color:#a78bfa;background:#1e1a32}
  .card .check{position:absolute;top:10px;right:10px;z-index:10;width:28px;height:28px;border-radius:50%;border:2px solid rgba(255,255,255,.3);background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;font-size:15px;color:transparent;transition:all .2s;pointer-events:none}
  .card.selected .check{background:#a78bfa;border-color:#a78bfa;color:#fff}
  .card:not(.selected) .check{opacity:0}
  .card:hover .check{opacity:1}
  .card-img-wrap{width:100%;aspect-ratio:1;overflow:hidden;background:#0d0d1a}
  .card-img{width:100%;height:100%;object-fit:contain;display:block;transition:transform .3s}
  .card:hover .card-img{transform:scale(1.04)}
  .card-body{padding:12px 14px}
  .card-name{font-size:15px;font-weight:600;color:#fff;margin-bottom:2px}
  .card-copyright{color:#a78bfa;font-size:11px;margin-bottom:6px}
  .card-meta{font-size:11px;color:#888;margin-bottom:6px}
  .card-copy-row{display:flex;gap:4px;flex-wrap:wrap;margin-top:6px}
  .card-copy-btn{flex:1;min-width:60px;padding:5px 6px;border-radius:5px;border:1px solid #333;background:transparent;color:#999;font-size:10px;cursor:pointer;transition:all .2s;text-align:center}
  .card-copy-btn:hover{border-color:#a78bfa;color:#a78bfa;background:#a78bfa11}
  .card-copy-btn.copied{background:#4ade80;border-color:#4ade80;color:#000}
  .card-copy-btn.prim{background:#a78bfa22;border-color:#a78bfa44;color:#a78bfa}
  .card-copy-btn.prim:hover{background:#a78bfa44}
  .card-tags{display:flex;flex-wrap:wrap;gap:2px;margin-top:5px}
  .card-tag{font-size:9px;padding:2px 5px;border-radius:3px;background:#252540;color:#999}
  #loadingScreen{display:none;position:fixed;inset:0;z-index:998;background:rgba(13,13,26,.85);backdrop-filter:blur(6px);flex-direction:column;align-items:center;justify-content:center}
  #loadingScreen.show{display:flex}
  #loadingScreen .spinner{width:48px;height:48px;border:4px solid #333;border-top-color:#a78bfa;border-radius:50%;animation:spin .8s linear infinite}
  #loadingScreen p{color:#888;margin-top:16px;font-size:15px}
  @keyframes spin{to{transform:rotate(360deg)}}
  .sel-bar{position:fixed;bottom:0;left:0;right:0;z-index:100;background:#1a1a2e;border-top:1px solid #2a2a3e;padding:12px 20px;display:none;align-items:center;justify-content:space-between;gap:12px;backdrop-filter:blur(12px)}
  .sel-bar.show{display:flex}
  .sel-count{color:#a78bfa;font-weight:600;font-size:14px}
  .sel-actions{display:flex;gap:8px}
  .sel-btn{padding:8px 16px;border-radius:8px;border:none;background:linear-gradient(135deg,#a78bfa,#ec4899);color:#fff;font-size:13px;font-weight:600;cursor:pointer;transition:transform .15s}
  .sel-btn:hover{transform:translateY(-1px)}
  .sel-btn.sec{background:transparent;color:#888;border:1px solid #444}
  .sel-btn.sec:hover{border-color:#f06060;color:#f06060}
  .sel-btn.copied{background:#4ade80!important;border-color:#4ade80!important;color:#000}
  .detail-overlay{display:none;position:fixed;inset:0;z-index:999;background:rgba(0,0,0,.7);backdrop-filter:blur(4px);justify-content:center;align-items:center;padding:20px}
  .detail-overlay.open{display:flex}
  .detail-panel{background:#1a1a2e;border:1px solid #3a3a50;border-radius:16px;max-width:640px;width:100%;max-height:90vh;overflow-y:auto;animation:pop .2s ease}
  @keyframes pop{from{transform:scale(.95);opacity:0}to{transform:scale(1);opacity:1}}
  .detail-img{width:100%;aspect-ratio:1;object-fit:contain;background:#0d0d1a;display:block;cursor:zoom-in}
  .detail-body{padding:16px 20px}
  .detail-box{background:#0d0d1a;border:1px solid #3a3a50;border-radius:10px;padding:14px 16px;margin-bottom:12px}
  .detail-label{font-size:12px;color:#888;margin-bottom:6px}
  .detail-text{font-family:monospace;font-size:14px;color:#f0c060;word-break:break-all;line-height:1.6}
  .detail-text.tags{color:#aaa;font-size:13px}
  .detail-copy-row{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
  .detail-copy-btn{flex:1;text-align:center;padding:6px 14px;border-radius:6px;border:1px solid #a78bfa;background:transparent;color:#a78bfa;font-size:12px;cursor:pointer;transition:all .2s;white-space:nowrap}
  .detail-copy-btn:hover{background:#a78bfa;color:#fff}
  .detail-copy-btn.copied{background:#4ade80;border-color:#4ade80;color:#000}
  .detail-info{font-size:13px;line-height:1.8;color:#ccc}
  .detail-info a{color:#60c0f0;text-decoration:none}
  .detail-info a:hover{text-decoration:underline}
  .detail-close{display:block;width:100%;padding:12px;border:none;border-top:1px solid #2a2a3e;background:transparent;color:#888;font-size:14px;cursor:pointer}
  .detail-close:hover{background:#2a2a3e}
  .error{color:#f06060;display:flex;flex-direction:column;align-items:center;justify-content:center;min-height:50vh;text-align:center;padding:40px;grid-column:1/-1}
  .error small{color:#888;margin-top:8px;font-size:13px}.error .hint{color:#aaa;font-size:13px;margin-top:4px}
  .pager button{padding:8px 14px;border-radius:8px;border:1px solid #333;background:#1a1a2e;color:#aaa;font-size:13px;cursor:pointer;transition:all .2s}.pager button:hover{border-color:#a78bfa;color:#a78bfa}.pager button.on{background:#a78bfa22;border-color:#a78bfa;color:#a78bfa;font-weight:600}@media(max-width:900px){#results{grid-template-columns:repeat(var(--cols,2),1fr)!important}.container{padding:16px 12px 90px}}@media(max-width:500px){#results{grid-template-columns:1fr!important;gap:10px}.container{padding:12px 8px 90px}.search-bar input{font-size:16px}.card-copy-btn{font-size:11px;padding:6px 8px}.col-picker{display:none}}
</style>
</head>
<body>
<div id="loadingScreen"><div class="spinner"></div><p>搜索中…</p></div>
<div class="container">
  <header style="position:relative"><div style="flex:1"><h1>✦ AnimaDex</h1><small>支持中文/英文名 · 点击多选 · 批量复制</small></div><button onclick="showSettings()" style="background:none;border:1px solid #444;color:#888;border-radius:8px;padding:6px 12px;cursor:pointer;font-size:13px" title="API 信息">⚙️</button></header>
  <div class="search-bar">
    <input id="q" type="text" placeholder="角色名 / 系列名 / 画师名…" autofocus>
    <select id="mode"><option value="characters">角色</option><option value="artists">画师</option><option value="copyrights">系列</option></select>
    <button onclick="search()">搜索</button>
  </div>
  <div id="pagenav" style="display:none;gap:6px;margin-bottom:8px;align-items:center"></div>
  <div class="toolbar"><div id="stats" class="stats"></div><div class="col-picker"><span>每行</span><button class="col-btn" data-c="1">1</button><button class="col-btn" data-c="2">2</button><button class="col-btn on" data-c="3">3</button><button class="col-btn" data-c="4">4</button><button class="col-btn" data-c="5">5</button><button class="col-btn" data-c="0">自动</button></div></div>
  <div id="results"></div>
</div>
<div class="sel-bar" id="selBar">
  <div class="sel-count">已选 <span id="selCount">0</span> 个角色</div>
  <div class="sel-actions">
    <button class="sel-btn" id="selCopy" onclick="copySel('trigger')">📋 提示词</button>
    <button class="sel-btn" id="selCopyTags" onclick="copySel('tags')">🏷️ 标签</button>
    <button class="sel-btn" id="selCopyAll" onclick="copySel('all')">📋 全部</button>
    <button class="sel-btn sec" onclick="clearSelection()">清除</button>
  </div>
</div>
<script>
var isLocal=location.hostname==='127.0.0.1'||location.hostname==='localhost';


var overlay,selected={},resultsData=[],_cols=4,curPage=1,curMode='characters',curQ='',totalPages=0;(function(){var bs=document.querySelectorAll(".col-btn");bs.forEach(function(b){b.addEventListener("click",function(){bs.forEach(function(x){x.classList.remove("on")});b.classList.add("on");var c=parseInt(b.dataset.c);if(c>0){_cols=c;document.getElementById("results").style.setProperty("--cols",c)}else{_cols=0;document.getElementById("results").style.setProperty("--cols","auto-fill");document.getElementById("results").style.gridTemplateColumns="repeat(auto-fill,minmax(240px,1fr))"}})})})();
function search(){
  var q=document.getElementById('q').value.trim(),mode=document.getElementById('mode').value;
  curQ=q;curMode=mode;curPage=1;if(q) window.history.replaceState({},'',window.location.pathname+'?q='+encodeURIComponent(q)+'&mode='+mode);
  var el=document.getElementById('results'),st=document.getElementById('stats');
  if(!q){el.innerHTML='<div class="error">请输入搜索关键词</div>';st.textContent='';return}
  document.getElementById('loadingScreen').classList.add('show');st.textContent='';selected={};updateSelBar();el.innerHTML='';
  curQ=q;curMode=mode;curPage=1;fetch('/api/search?q='+encodeURIComponent(q)+'&mode='+mode+'&page=1&sort=count'+getAiParams())
    .then(function(r){return r.json()})
    .then(function(d){
      document.getElementById('loadingScreen').classList.remove('show');
      if(d.error){el.innerHTML='<div class="error">请求失败: '+d.error+'</div>';return}
      resultsData=d.results||[];var s='';
      if(d.translated){s+='<span class="trans">🌐 '+d.translated+'</span>';if(/[一-鿿]/.test(q))s+=' <span style="color:#888;font-size:12px">(建议直接英文名更准确)</span>'}
      totalPages=d.pages||1;if(d.total>0)s+=(s?' · ':'')+'共 '+d.total+' 个结果 · 第 '+d.page+'/'+totalPages+' 页';
      if(!resultsData.length){st.innerHTML=s;el.innerHTML='<div class="error">😕 未找到 &quot;'+q+'&quot; 的结果'+(/[一-鿿]/.test(q)?'<br><small>💡 试试英文名搜索，如: raiden shogun, hu tao, genshin impact</small>':'')+'</div>';return}
      st.innerHTML=s;showPageNav(d);
      el.innerHTML=resultsData.map(function(r,i){
        var img=(r.thumb_url||'').replace(/%3A/g,'_').replace(/%2F/g,'_'),trigger=(r.trigger||'').replace(/"/g,'&quot;');
        var tags=(r.tags||[]).map(function(t){return '<span class="card-tag">'+t+'</span>'}).join('');
        return '<div class="card" data-idx="'+i+'"><div class="check">✓</div><div class="card-img-wrap" onclick="toggleSel('+i+')">'+(img?'<img class="card-img" src="'+(isLocal?'/api/image?url='+img+'':img)+'" alt="" loading="lazy">':'<div style="color:#333;display:flex;align-items:center;justify-content:center;height:100%;font-size:12px">无图</div>')+'</div><div class="card-body"><div class="card-name">'+r.name+'</div><div class="card-copyright">'+(r.copyright_name||'')+'</div><div class="card-meta">📊 '+(r.count||0).toLocaleString()+' 张图片</div><div class="card-copy-row"><button class="card-copy-btn prim" onclick="event.stopPropagation();copyOne(\''+r.slug+'\',\'trigger\',this)" title="角色标签/触发词">🎯 角色</button><button class="card-copy-btn" onclick="event.stopPropagation();copyOne(\''+r.slug+'\',\'tags\',this)" title="特征标签">🏷️ 特征</button><button class="card-copy-btn" onclick="event.stopPropagation();copyOne(\''+r.slug+'\',\'all\',this)" title="全部">📋 全部</button></div>'+(tags?'<div class="card-tags">'+tags+'</div>':'')+'</div></div>'
      }).join('');
    }).catch(function(e){document.getElementById('loadingScreen').classList.remove('show');el.innerHTML='<div class="error">请求失败: '+e.message+'</div>'});
}
function toggleSel(i){var c=document.querySelector('.card[data-idx="'+i+'"]');if(!c)return;if(selected[i]){delete selected[i];c.classList.remove('selected')}else{selected[i]=true;c.classList.add('selected')}updateSelBar()}
function clearSelection(){selected={};document.querySelectorAll('.card.selected').forEach(function(c){c.classList.remove('selected')});updateSelBar()}
function updateSelBar(){var c=Object.keys(selected).length;document.getElementById('selCount').textContent=c;document.getElementById('selBar').classList.toggle('show',c>0);document.getElementById('selCopy').textContent='📋 提示词 ('+c+')';document.getElementById('selCopyTags').textContent='🏷️ 标签 ('+c+')';document.getElementById('selCopyAll').textContent='📋 全部 ('+c+')'}
function copySel(t){var is=Object.keys(selected).sort(function(a,b){return a-b}),items=[];is.forEach(function(i){var r=resultsData[i];if(!r)return;if(t==='trigger')items.push(r.name+': '+r.trigger);else if(t==='tags')items.push(r.name+': '+(r.tags||[]).join(', '));else items.push(r.name+': '+r.trigger+', '+(r.tags||[]).join(', '))});if(!items.length)return;var id=t==='trigger'?'selCopy':t==='tags'?'selCopyTags':'selCopyAll';cf(items.join('\n\n'),id)}
function copyOne(slug,t,btn){var r=resultsData.find(function(x){return x.slug===slug});if(!r)return;var text='';if(t==='trigger')text=r.trigger||'';else if(t==='tags')text=(r.tags||[]).join(', ');else text=(r.trigger||'')+', '+(r.tags||[]).join(', ');var o=btn.textContent;navigator.clipboard.writeText(text).then(function(){btn.textContent='✅';btn.classList.add('copied');setTimeout(function(){btn.textContent=o;btn.classList.remove('copied')},1500)}).catch(function(){prompt('复制失败:',text)})}
function cf(text,id){var btn=document.getElementById(id);if(!btn)return;var o=btn.textContent;navigator.clipboard.writeText(text).then(function(){btn.textContent='✅ 已复制';btn.classList.add('copied');setTimeout(function(){btn.textContent=o;btn.classList.remove('copied')},2000)}).catch(function(){prompt('复制失败:',text)})}

function showPageNav(d){
  var n=document.getElementById('pagenav');
  if(!n||!d||d.pages<=1){if(n)n.style.display='none';return}
  n.style.display='flex';
  var p=d.page||1,t=d.pages||1,h='';
  h+='<button onclick="searchPage('+(p-1)+')" '+(p<=1?'disabled':'')+' style="padding:6px 12px;border-radius:6px;border:1px solid #333;background:#1a1a2e;color:#888;font-size:12px;cursor:pointer">◀ 上一页</button>';
  h+='<span style="color:#aaa;font-size:12px;padding:0 4px">第</span>';
  h+='<input id="pageJump" type="number" min="1" max="'+t+'" value="'+p+'" style="width:48px;padding:4px 6px;border-radius:6px;border:1px solid #333;background:#0d0d1a;color:#a78bfa;font-size:13px;text-align:center;outline:none" onkeydown="if(event.key===\'Enter\')searchPage(parseInt(this.value))">';
  h+='<span style="color:#aaa;font-size:12px;padding:0 2px">/ '+t+'</span>';
  h+='<button onclick="var v=parseInt(document.getElementById(\'pageJump\').value);if(v>=1&&v<='+t+')searchPage(v)" style="padding:4px 10px;border-radius:6px;border:1px solid #a78bfa;background:transparent;color:#a78bfa;font-size:11px;cursor:pointer">GO</button>';
  h+='<button onclick="searchPage('+(p+1)+')" '+(p>=t?'disabled':'')+' style="padding:6px 12px;border-radius:6px;border:1px solid #333;background:#1a1a2e;color:#888;font-size:12px;cursor:pointer">下一页 ▶</button>';
  n.innerHTML=h;
}
function searchPage(p){
  if(p<1)return;
  curPage=p;selected={};updateSelBar();
  document.getElementById('loadingScreen').classList.add('show');
  document.getElementById('results').innerHTML='';
  fetch('/api/search?q='+encodeURIComponent(curQ)+'&mode='+curMode+'&page='+p+'&sort=count'+getAiParams())
    .then(function(r){return r.json()})
    .then(function(d){
      document.getElementById('loadingScreen').classList.remove('show');
      if(d.error)return;
      resultsData=d.results||[];
      var s='';
      if(d.translated){s+='<span class="trans">🌐 '+d.translated+'</span>';if(/[一-鿿]/.test(curQ))s+=' <span style="color:#888;font-size:12px">(建议直接英文名更准确)</span>';}
      if(d.total>0)s+=(s?' · ':'')+'共 '+d.total+' 个结果 · 第 '+d.page+'/'+(d.pages||1)+' 页';
      document.getElementById('stats').innerHTML=s;
      document.getElementById('results').innerHTML=resultsData.map(function(r,i){
        var img=(r.thumb_url||'').replace(/%3A/g,'_').replace(/%2F/g,'_'),trigger=(r.trigger||'').replace(/"/g,'&quot;');
        var tags=(r.tags||[]).map(function(t){return '<span class="card-tag">'+t+'</span>'}).join('');
        return '<div class="card" data-idx="'+i+'"><div class="check">✓</div><div class="card-img-wrap" onclick="toggleSel('+i+')">'+(img?'<img class="card-img" src="'+(isLocal?'/api/image?url='+img+'':img)+'" alt="" loading="lazy">':'<div style="color:#333;display:flex;align-items:center;justify-content:center;height:100%;font-size:12px">无图</div>')+'</div><div class="card-body"><div class="card-name">'+r.name+'</div><div class="card-copyright">'+(r.copyright_name||'')+'</div><div class="card-meta">📊 '+(r.count||0).toLocaleString()+' 张图片</div><div class="card-copy-row"><button class="card-copy-btn prim" onclick="event.stopPropagation();copyOne(\''+r.slug+'\',\'trigger\',this)" title="角色标签/触发词">🎯 角色</button><button class="card-copy-btn" onclick="event.stopPropagation();copyOne(\''+r.slug+'\',\'tags\',this)" title="特征标签">🏷️ 特征</button><button class="card-copy-btn" onclick="event.stopPropagation();copyOne(\''+r.slug+'\',\'all\',this)" title="全部">📋 全部</button></div>'+(tags?'<div class="card-tags">'+tags+'</div>':'')+'</div></div>';
      }).join('');
      showPageNav(d);
      window.scrollTo(0,0);
    });
}
function goSeries(n){window.location.href="/?q="+encodeURIComponent(n)}
function showSettings(){
  var ls=window.localStorage;
  function g(k,d){return ls.getItem('ad_'+k)||d}
  var o=document.createElement('div');
  o.className='detail-overlay open';
  o.onclick=function(e){if(e.target===o)o.remove()};
  var mcpSseUrl=window.location.origin+'/sse';
  var mcpStreamUrl=window.location.origin+'/mcp';
  o.innerHTML='<div class="detail-panel" style="max-width:520px"><div class="detail-body">'
  +'<h3 style="margin-bottom:16px">⚙️ 设置</h3>'
  +'<div style="background:#0d0d1a;border-radius:8px;padding:12px;margin-bottom:12px;font-size:13px">'
  +'<div style="color:#888;margin-bottom:4px">🔌 MCP SSE</div><code style="color:#f0c060;word-break:break-all;font-size:12px">'+mcpSseUrl+'</code>'
  +'<div style="color:#888;margin-top:10px;margin-bottom:4px">📡 MCP Streamable HTTP</div><code style="color:#60c0f0;word-break:break-all;font-size:12px">'+mcpStreamUrl+'</code>'
  +'</div>'
  +'<div style="margin-bottom:12px"><div style="color:#888;font-size:13px;margin-bottom:4px">🌐 翻译方式</div>'
  +'<select id="ai_sel" style="width:100%;padding:8px 12px;border-radius:8px;border:1px solid #333;background:#0d0d1a;color:#e0e0e0;font-size:13px;outline:none"'+(!isLocal?' disabled':'')+'>'
  +'<option value="google"'+(g('mode','')===''?' selected':'')+'>Google 翻译（默认）</option>'
  +(isLocal?'<option value="ai"'+(g('mode','')==='ai'?' selected':'')+'>AI 翻译</option>':'')
  +'</select>'
  +(!isLocal?'<div style="color:#888;font-size:11px;margin-top:4px">在线版仅支持 Google 翻译</div>':'')
  +'</div>'
  +(isLocal?(
    '<div id="ai_config" style="display:'+(g('mode','')==='ai'?'block':'none')+'">'
    +'<div style="margin-bottom:10px"><div style="color:#888;font-size:13px;margin-bottom:4px">🔗 API 地址</div>'
    +'<input id="ai_url" value="'+g('url','https://api.deepseek.com')+'" style="width:100%;padding:8px 12px;border-radius:8px;border:1px solid #333;background:#0d0d1a;color:#e0e0e0;font-size:13px;outline:none"></div>'
    +'<div style="margin-bottom:10px"><div style="color:#888;font-size:13px;margin-bottom:4px">🔑 API Key</div>'
    +'<input id="ai_key" type="password" value="'+g('key','')+'" style="width:100%;padding:8px 12px;border-radius:8px;border:1px solid #333;background:#0d0d1a;color:#e0e0e0;font-size:13px;outline:none"></div>'
    +'<div style="margin-bottom:10px"><div style="color:#888;font-size:13px;margin-bottom:4px">📦 模型</div>'
    +'<select id="ai_model" style="width:100%;padding:8px 12px;border-radius:8px;border:1px solid #333;background:#0d0d1a;color:#e0e0e0;font-size:13px;outline:none">'
    +(g('model','')?'<option value="'+g('model','')+'" selected>'+g('model','')+'</option>':'<option value="">点击「检测模型」获取列表</option>')
    +'</select></div>'
    +'<div style="display:flex;gap:6px;margin-top:6px">'
    +'<button onclick="detectModels()" style="flex:1;padding:8px;border-radius:8px;border:1px solid #a78bfa;background:transparent;color:#a78bfa;font-size:13px;cursor:pointer">🔄 检测模型</button>'
    +'<button onclick="testAiConn()" style="flex:1;padding:8px;border-radius:8px;border:1px solid #666;background:transparent;color:#888;font-size:13px;cursor:pointer">🔌 测试连接</button>'
    +'</div>'
    +'<div id="ai_test_result" style="font-size:12px;margin-top:6px"></div>'
    +'</div>'
    +'<button onclick="saveAiSettings()" style="width:100%;padding:10px;background:linear-gradient(135deg,#a78bfa,#ec4899);color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:600;cursor:pointer;margin-top:12px">💾 保存</button>'
  ):'')
  +'</div><button class="detail-close" onclick="closeSettings()" style="display:block;width:100%;padding:12px;border:none;border-top:1px solid #2a2a3e;background:transparent;color:#888;font-size:14px;cursor:pointer">关闭 ✕</button></div>';
  document.body.appendChild(o);
  var sel=document.getElementById('ai_sel');
  if(sel) sel.onchange=function(){
    document.getElementById('ai_config').style.display=this.value==='ai'?'block':'none';
  };
}
function closeSettings(){
  var o=document.querySelector('.detail-overlay.open');
  if(o)o.remove();
}
function getAiParams(){
  var ls=window.localStorage;
  if(ls.getItem('ad_mode')!=='ai')return'';
  return'&ai_url='+encodeURIComponent(ls.getItem('ad_url')||'https://api.deepseek.com')
    +'&ai_key='+encodeURIComponent(ls.getItem('ad_key')||'')
    +'&ai_model='+encodeURIComponent(ls.getItem('ai_model')||'deepseek-chat');
}function getModelVal(){
  var sel=document.getElementById('ai_model');
  return sel.value;
}
function normUrl(u){
  if(!u)return u;
  if(u.includes('/chat/completions')||u.includes('/api/generate')) return u;
  if(u.includes('deepseek')||u.includes('openai')||u.includes('groq')) return u.replace(/\/?$/,'')+'/v1/chat/completions';
  if(u.includes('localhost:11434')||u.includes('127.0.0.1:11434')) return u.replace(/\/?$/,'')+'/api/generate';
  return u.replace(/\/?$/,'')+'/v1/chat/completions';
}
function modelsUrl(u){
  if(u.includes('localhost:11434')||u.includes('127.0.0.1:11434')) return u.replace(/\/?$/,'')+'/api/tags';
  return u.replace(/\/?$/,'').replace('/v1/chat/completions','').replace('/api/generate','')+'/v1/models';
}
function testAiConn(){
  var el=document.getElementById('ai_test_result');
  var url=normUrl(document.getElementById('ai_url').value);
  document.getElementById('ai_url').value=url;
  el.innerHTML='测试中...';el.style.color='#888';
  var key=document.getElementById('ai_key').value;
  fetch(url,{method:'POST',headers:{'Content-Type':'application/json','Authorization':key?'Bearer '+key:''},body:JSON.stringify({model:'deepseek-chat',messages:[{role:'user',content:'hi'}],stream:false})})
    .then(function(r){if(r.ok){el.innerHTML='✅ 连接成功!';el.style.color='#4ade80'}else{el.innerHTML='❌ HTTP '+r.status;el.style.color='#f06060'}})
    .catch(function(e){el.innerHTML='❌ 失败: '+e.message;el.style.color='#f06060'});
}
function detectModels(){
  var el=document.getElementById('ai_test_result');
  var url=modelsUrl(document.getElementById('ai_url').value);
  var key=document.getElementById('ai_key').value;
  el.innerHTML='检测中...';el.style.color='#888';
  var h={};
  if(key) h['Authorization']='Bearer '+key;
  fetch(url,{headers:h})
    .then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json()})
    .then(function(d){
      var models=(d.data||d.models||[]).map(function(m){return m.id||m.name}).filter(Boolean);
      if(!models.length){el.innerHTML='❌ 未获取到模型';el.style.color='#f06060';return}
      var sel=document.getElementById('ai_model');
      sel.innerHTML='';
      models.forEach(function(m){
        var o=document.createElement('option');
        o.value=m;o.textContent=m;sel.appendChild(o);
      });
      // Auto-select first model and save
      sel.selectedIndex=0;
      el.innerHTML='✅ 已选择 '+models[0]+'（已自动保存）';el.style.color='#4ade80';
      // Auto-save
      var ls=window.localStorage;
      ls.setItem('ad_model',sel.value);
      ls.setItem('ad_url',normUrl(document.getElementById('ai_url').value));
      ls.setItem('ad_key',document.getElementById('ai_key').value);
    })
    .catch(function(e){el.innerHTML='❌ 检测失败: '+e.message;el.style.color='#f06060'});
}
function saveAiSettings(){
  try{
    var ls=window.localStorage;
    ls.setItem('ad_mode',document.getElementById('ai_sel').value);
    ls.setItem('ad_url',normUrl(document.getElementById('ai_url').value));
    ls.setItem('ad_key',document.getElementById('ai_key').value);
    ls.setItem('ad_model',getModelVal());
    closeSettings();
    setTimeout(function(){if(document.getElementById('q').value) search()},100);
  }catch(e){alert('保存失败: '+e.message);}
}

function openDetail(slug){
  if(!overlay){overlay=document.createElement('div');overlay.className='detail-overlay';overlay.onclick=function(e){if(e.target===overlay)closeDetail()};document.body.appendChild(overlay)}
  overlay.innerHTML='<div class="detail-panel"><div style="display:flex;align-items:center;justify-content:center;padding:60px;color:#666">加载中…</div></div>';overlay.classList.add('open');
  fetch('/api/character?slug='+encodeURIComponent(slug)).then(function(r){return r.json()}).then(function(ch){
    if(ch.error){overlay.innerHTML='<div class="detail-panel"><div class="error">'+ch.error+'</div><button class="detail-close" onclick="closeDetail()">关闭 ✕</button></div>';return}
    var tags=(ch.tags||[]).join(', '),trigger=ch.trigger||'',img=ch.img_url||ch.thumb_url||'',loras=ch.loras||[],html='';
    html+=img?'<img class="detail-img" src="'+(isLocal?'/api/image?url='+img+'':img)+'" alt="" onclick="window.open(this.src)">':'';
    html+='<div class="detail-body"><div class="detail-box"><div class="detail-label">🎯 角色标签 (Trigger)</div><div class="detail-text" id="dt-'+slug+'">'+trigger+'</div><div class="detail-copy-row"><button class="detail-copy-btn" onclick="dc(\'dt-'+slug+'\',this)">📋 复制</button></div></div>';
    html+='<div class="detail-box"><div class="detail-label">🏷️ 特征标签 (Tags)</div><div class="detail-text tags" id="dtg-'+slug+'">'+tags+'</div><div class="detail-copy-row"><button class="detail-copy-btn" onclick="dc(\'dtg-'+slug+'\',this)">📋 复制</button></div></div>';
    html+='<div class="detail-box"><div class="detail-label">📋 全部</div><div class="detail-text" style="display:none" id="df-'+slug+'">'+(trigger+', '+tags).replace(/</g,'&lt;')+'</div><div class="detail-copy-row"><button class="detail-copy-btn" onclick="dc(\'df-'+slug+'\',this)">📋 复制全部</button></div></div>';
    html+='<div class="detail-info"><div><b>角色：</b>'+ch.name+'</div><div><b>系列：</b>'+(ch.copyright_name||'')+'</div><div><b>图片数：</b>'+(ch.count||0).toLocaleString()+'</div><div><b>评分：</b>👍 '+(ch.rating?.up||0)+' / 👎 '+(ch.rating?.down||0)+'</div><div><b>收藏：</b>'+(ch.fav_count||0)+'</div>'+(ch.url?'<div><a href="'+ch.url+'" target="_blank">🔗 Danbooru</a></div>':'');
    if(loras.length){html+='<div style="margin-top:8px"><b>🧩 LoRA：</b></div>';loras.forEach(function(l){html+='<div>• <a href="'+l.url+'" target="_blank">'+l.name+'</a></div>'})}
    html+='</div></div><button class="detail-close" onclick="closeDetail()">关闭 ✕</button>';
    overlay.innerHTML=html;
  }).catch(function(e){overlay.innerHTML='<div class="detail-panel"><div class="error">加载失败: '+e.message+'</div><button class="detail-close" onclick="closeDetail()">关闭 ✕</button></div>'})
}
function closeDetail(){if(overlay)overlay.classList.remove('open')}
function dc(id,btn){var el=document.getElementById(id);if(!el)return;var t=el.textContent.trim(),o=btn.textContent;navigator.clipboard.writeText(t).then(function(){btn.textContent='✅ 已复制';btn.classList.add('copied');setTimeout(function(){btn.textContent=o;btn.classList.remove('copied')},2000)}).catch(function(){prompt('复制失败:',t)})}
document.addEventListener('keydown',function(e){if(e.key==='Escape'){closeDetail();clearSelection()}})
document.getElementById('q').addEventListener('keydown',function(e){if(e.key==='Enter')search()})
var qp=new URLSearchParams(location.search);if(qp.get('q')){document.getElementById('q').value=qp.get('q');if(qp.get('mode'))document.getElementById('mode').value=qp.get('mode');search()}
</script>
</body>
</html>"""


CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(os.path.join(CACHE_DIR, "thumbs"), exist_ok=True)

ANIMADEX_DATA = os.environ.get("ANIMADEX_DATA", "F:/AI/picture/animadex-data")

async def api_image(request):
    url = request.query_params.get("url", "")
    if not url:
        return JSONResponse({"error": "url required"}, status_code=400)
    from hashlib import md5
    from pathlib import Path
    import mimetypes
    ext = ".webp"
    if ".png" in url:
        ext = ".png"
    cache_path = Path(CACHE_DIR) / "thumbs" / (md5(url.encode()).hexdigest() + ext)
    if cache_path.exists():
        from starlette.responses import FileResponse
        return FileResponse(str(cache_path), media_type="image/webp")
    # Check animadex-data (characters, artists, copyrights)
    from urllib.parse import unquote
    fname = unquote(url.rsplit("/", 1)[-1].split("?")[0])
    fname2 = fname.replace(":", "_").replace("%3A", "_")
    for sub in ("characters", "artists", "copyrights"):
        for fn in (fname, fname2):
            if fn == fname2 and fn == fname:
                continue
            ad_path = Path(ANIMADEX_DATA) / sub / "thumbs" / fn
            if ad_path.exists():
                from starlette.responses import FileResponse
                return FileResponse(str(ad_path), media_type="image/webp")
    try:
        r = _client.get(url, timeout=30)
        if r.status_code == 200:
            cache_path.write_bytes(r.content)
            from starlette.responses import Response
            return Response(content=r.content, media_type=r.headers.get("content-type", "image/webp"))
    except Exception:
        pass
    # Redirect to CDN, try _ version for : in names
    from starlette.responses import RedirectResponse
    alt = url.replace("%3A", "_")
    return RedirectResponse(alt if alt != url else url)

# ── App assembly ────────────────────────────────────────────────────────

from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route, Mount

async def index(request):
    return HTMLResponse(HTML_PAGE)

async def api_search(request):
    q = request.query_params.get("q", "")
    mode = request.query_params.get("mode", "characters")
    page = int(request.query_params.get("page", "1"))
    sort = request.query_params.get("sort", "count")
    # Frontend AI config
    ai_url = request.query_params.get("ai_url", "")
    ai_key = request.query_params.get("ai_key", "")
    ai_model = request.query_params.get("ai_model", "")
    api_config = {"url": ai_url, "key": ai_key, "model": ai_model} if ai_url else None
    try:
        data = cn_search(q, mode, page, sort, api_config)
        return JSONResponse(data)
    except Exception as e:
        return JSONResponse({"error": str(e), "results": [], "total": 0}, status_code=500)

async def api_character(request):
    """Get character detail by slug — server-side proxy to avoid CORS."""
    slug = request.query_params.get("slug", "")
    if not slug:
        return JSONResponse({"error": "slug required"}, status_code=400)
    try:
        data = _get("/api/characters/search", q=slug, page=1)
        for r in data.get("results", []):
            if r["slug"] == slug:
                return JSONResponse(r)
        return JSONResponse({"error": "not found"}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

mcp_sse_app = server.sse_app()
mcp_streamable_http_app = server.streamable_http_app()

app = Starlette(routes=[
    Route("/", endpoint=index),
    Route("/api/search", endpoint=api_search),
    Route("/api/character", endpoint=api_character),
    Route("/api/image", endpoint=api_image),
    Mount("/mcp", app=mcp_streamable_http_app),
    Mount("/", app=mcp_sse_app),
])

def _precache_thumbs():
    """Background download all 36k+ thumbnails from local DB."""
    import pathlib
    thumb_dir = pathlib.Path(CACHE_DIR) / "thumbs"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    if not LOCAL_DB:
        return
    try:
        cur = LOCAL_DB.cursor()
        cur.execute("SELECT thumb_url FROM characters WHERE thumb_url != '' ORDER BY count DESC")
        rows = cur.fetchall()
        total = len(rows)
        cached = sum(1 for p in thumb_dir.iterdir() if p.suffix == '.webp') if thumb_dir.exists() else 0
        print(f"[cache] {cached}/{total} thumbnails cached, downloading remaining...")
        for i, row in enumerate(rows):
            url = row[0] or ""
            if not url:
                continue
            fname = _hl.md5(url.encode()).hexdigest() + ".webp"
            fpath = thumb_dir / fname
            if fpath.exists():
                continue
            try:
                resp = _client.get(url, timeout=5)
                if resp.status_code == 200:
                    fpath.write_bytes(resp.content)
            except:
                pass
            if (i + 1) % 500 == 0:
                new_c = sum(1 for p in thumb_dir.iterdir() if p.suffix == '.webp')
                print(f"[cache] ... {new_c}/{total} thumbnails")
    except Exception as e:
        print(f"[cache] Error: {e}")


if __name__ == "__main__":
    import uvicorn, time, threading

    print("\n=== AnimaDex Server Starting ===\n")
    _init_local_db()
    _build_index()

    port = int(os.environ.get("PORT", 11451))
    threading.Thread(target=_precache_thumbs, daemon=True).start()
    uvicorn.run(app, host="0.0.0.0", port=port)
