"""AI 对话的实时上下文：注入当前时间，按需抓取天气/汇率等开放接口数据。

设计原则：
- 每次回答都注入当前时间（修复模型不知道今天几号的问题）
- 只有问题命中意图时才调外部接口（天气/汇率），失败静默跳过，不影响正常回答
- 全部使用免 Key 的开放接口，带内存缓存避免刷接口
"""

import datetime as dt
import random

import httpx

TZ_CN = dt.timezone(dt.timedelta(hours=8))
WEEKDAY_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# Open-Meteo 天气代码 → 中文
WEATHER_CODES = {
    0: "晴", 1: "基本晴", 2: "多云", 3: "阴",
    45: "雾", 48: "雾凇",
    51: "毛毛雨", 53: "毛毛雨", 55: "毛毛雨",
    56: "冻毛毛雨", 57: "冻毛毛雨",
    61: "小雨", 63: "中雨", 65: "大雨",
    66: "冻雨", 67: "冻雨",
    71: "小雪", 73: "中雪", 75: "大雪", 77: "雪粒",
    80: "阵雨", 81: "阵雨", 82: "强阵雨",
    85: "阵雪", 86: "阵雪",
    95: "雷阵雨", 96: "雷阵雨伴冰雹", 99: "雷阵雨伴冰雹",
}

_WEATHER_WORDS = ("天气", "气温", "温度", "下雨", "下雪", "穿什么", "热不热", "冷不冷")
_RATE_WORDS = ("汇率", "美元", "美金", "欧元", "日元", "港币", "外汇", "人民币兑")
_FILLERS = (
    "怎么样", "如何", "什么样", "最新", "最近", "今天", "明天", "后天", "现在", "当前",
    "请问", "查询", "查一下", "查查", "一下", "报告", "预报", "情况", "了", "吗", "呢", "吧",
    "的", "啊", "嘛", "我", "在", "你", "看", "说", " tell", "？", "?", "，", ",", "。", " ",
)

_geo_cache: dict[str, tuple[float, float, str]] = {}
_weather_cache: dict[str, tuple[dt.datetime, str]] = {}
_rate_cache: list = [None, None]  # [取回时间, 文本]


def _now_cn() -> dt.datetime:
    return dt.datetime.now(TZ_CN)


def time_block() -> str:
    n = _now_cn()
    return f"当前时间：{n:%Y-%m-%d %H:%M} {WEEKDAY_CN[n.weekday()]}（北京时间）"


def _detect_weather_city(question: str) -> str | None:
    """从问题里抠城市名：取天气关键词前的片段，去修饰词。"""
    for w in _WEATHER_WORDS:
        idx = question.find(w)
        if idx <= 0:
            continue
        cand = question[:idx]
        for f in _FILLERS:
            cand = cand.replace(f, "")
        cand = cand.strip(" 　")
        if cand and len(cand) <= 10:
            return cand
    return None


async def _geocode(city: str) -> tuple[float, float, str] | None:
    if city in _geo_cache:
        return _geo_cache[city]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": city, "count": 1, "language": "zh", "format": "json"},
            )
            results = (resp.json().get("results") or [])
            if not results:
                return None
            r = results[0]
            info = (r["latitude"], r["longitude"], r.get("name", city))
            _geo_cache[city] = info
            return info
    except Exception:  # noqa: BLE001
        return None


async def weather_block(question: str) -> str | None:
    city = _detect_weather_city(question)
    if not city:
        return None
    cached = _weather_cache.get(city)
    if cached and (dt.datetime.now() - cached[0]).total_seconds() < 1800:
        return cached[1]
    geo = await _geocode(city)
    if not geo:
        return None
    lat, lon, name = geo
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": lat, "longitude": lon,
                    "current": "temperature_2m,weather_code,wind_speed_10m,relative_humidity_2m",
                    "daily": "temperature_2m_max,temperature_2m_min",
                    "timezone": "Asia/Shanghai", "forecast_days": 1,
                },
            )
            data = resp.json()
        cur = data.get("current", {})
        daily = data.get("daily", {})
        desc = WEATHER_CODES.get(cur.get("weather_code"), "未知")
        tmin = (daily.get("temperature_2m_min") or ["?"])[0]
        tmax = (daily.get("temperature_2m_max") or ["?"])[0]
        text = (
            f"【实时天气】{name}：当前 {cur.get('temperature_2m', '?')}°C，{desc}，"
            f"湿度 {cur.get('relative_humidity_2m', '?')}%，风速 {cur.get('wind_speed_10m', '?')}km/h，"
            f"今日 {tmin}~{tmax}°C。"
        )
        _weather_cache[city] = (dt.datetime.now(), text)
        return text
    except Exception:  # noqa: BLE001
        return None


async def rates_block(question: str) -> str | None:
    if not any(w in question for w in _RATE_WORDS):
        return None
    if _rate_cache[0] and (dt.datetime.now() - _rate_cache[0]).total_seconds() < 3600:
        return _rate_cache[1]
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get("https://open.er-api.com/v6/latest/USD")
            rates = resp.json().get("rates", {})
        text = (
            f"【实时汇率】1 美元 ≈ {rates.get('CNY', '?')} 人民币，"
            f"1 欧元 ≈ {rates.get('EUR', '?')} 美元，"
            f"100 日元 ≈ {round(rates.get('CNY', 0) / max(rates.get('JPY', 1), 1) * 100, 2)} 人民币。"
        )
        _rate_cache[0] = dt.datetime.now()
        _rate_cache[1] = text
        return text
    except Exception:  # noqa: BLE001
        return None


async def gather(question: str) -> list[str]:
    """组装实时上下文块列表。时间必有，其余按意图。"""
    blocks = [time_block()]
    for fetch in (weather_block(question), rates_block(question)):
        block = await fetch
        if block:
            blocks.append(block)
    # 诗句优先于点歌（"来首诗"不是点歌）
    poem = await poem_block(question)
    if poem:
        blocks.append(poem)
    else:
        music = await music_block(question)
        if music:
            blocks.append(music)
    video = await video_block(question)
    if video:
        blocks.append(video)
    return blocks


HONESTY_LINE = (
    "你的训练数据有截止时间，不知道今天之后发生的事。涉及新闻、股价、赛事结果等无法实时获取的"
    "信息时，如实告诉用户你拿不到最新数据，绝不要把训练数据里的旧事件当成现在的事情。"
    "【实时上下文】里提供的数据才是当前的。"
)


# ---------- 娱乐：点歌 / B站视频 / 诗句 ----------

_MUSIC_TRIGGERS = ("点歌", "来一首", "来首", "放一首", "放首", "播放", "听歌", "想听", "点一首", "唱歌", "音乐", "歌曲")
_MUSIC_STRIP = ("给我", "一首", "个", "吧", "啊", "呗", "好吗", "可以吗", "想听", "？", "?", "，", "。", " ")
_VIDEO_WORDS = ("视频", "影视", "电影", "电视剧", "动漫", "番剧", "B站", "b站", "哔哩哔哩")
_POEM_WORDS = ("来句诗", "来首诗", "读首诗", "读诗", "诗句", "作诗", "念首诗")
_POEM_CACHE: list = [None, None]  # [日期, 文本] 诗句每天换一首
_HOT_LIST_CACHE: list = [None, None]  # [取回时间, [(id, name, artist), ...]]
_POPULAR_CACHE: list = [None, None]
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Referer": "https://music.163.com"}
_UA_BILI = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


async def _netease_get(url: str, params: dict):
    async with httpx.AsyncClient(timeout=7) as client:
        resp = await client.get(url, params=params, headers=_UA)
        resp.raise_for_status()
        return resp.json()


async def _hot_songs() -> list[tuple[str, str, int]]:
    if _HOT_LIST_CACHE[0] and (dt.datetime.now() - _HOT_LIST_CACHE[0]).total_seconds() < 3600:
        return _HOT_LIST_CACHE[1]
    data = await _netease_get("https://music.163.com/api/playlist/detail", {"id": "3778678"})
    tracks = (data.get("result") or {}).get("tracks") or []
    songs = [(t.get("name", ""), (t.get("artists") or [{}])[0].get("name", ""), t.get("id", 0)) for t in tracks[:50]]
    if songs:
        _HOT_LIST_CACHE[0] = dt.datetime.now()
        _HOT_LIST_CACHE[1] = songs
    return songs


async def _netease_url(song_id: int) -> str | None:
    data = await _netease_get(
        "https://music.163.com/api/song/enhance/player/url", {"ids": f"[{song_id}]", "br": 128000}
    )
    return ((data.get("data") or [{}])[0].get("url")) or None


async def music_block(question: str) -> str | None:
    if not any(t in question for t in _MUSIC_TRIGGERS):
        return None
    # 抠歌名：触发词后面的内容，去掉客气话；空 = 随机来首热歌
    name = ""
    for t in _MUSIC_TRIGGERS:
        idx = question.find(t)
        if idx >= 0:
            rest = question[idx + len(t):]
            for s in _MUSIC_STRIP:
                rest = rest.replace(s, "")
            name = rest.strip()
            break
    try:
        if name:
            data = await _netease_get("https://music.163.com/api/search/get", {"s": name, "type": 1, "limit": 5})
            songs = ((data.get("result") or {}).get("songs")) or []
            if not songs:
                return None
            # 优先挑歌名包含关键词的结果，避免搜"晴天"出翻唱版
            s = next(
                (x for x in songs if name.lower() in (x.get("name") or "").lower()),
                songs[0],
            )
            sid, title, artist = s.get("id", 0), s.get("name", ""), (s.get("artists") or [{}])[0].get("name", "")
        else:
            hot = await _hot_songs()
            if not hot:
                return None
            title, artist, sid = hot[random.randrange(len(hot))]
        url = await _netease_url(sid)
        if not url:
            return None
        label = f"为你找到《{title}》-{artist}" if name else f"随机来一首《{title}》-{artist}"
        return f"【点歌】{label}，试听链接（约20分钟内有效，尽快点开）：{url}。把歌名和链接原样告诉用户，不要改写链接。"
    except Exception:  # noqa: BLE001
        return None


async def video_block(question: str) -> str | None:
    if not any(w in question for w in _VIDEO_WORDS):
        return None
    if _POPULAR_CACHE[0] and (dt.datetime.now() - _POPULAR_CACHE[0]).total_seconds() < 1800:
        items = _POPULAR_CACHE[1]
    else:
        try:
            async with httpx.AsyncClient(timeout=7) as client:
                resp = await client.get(
                    "https://api.bilibili.com/x/web-interface/popular", headers=_UA_BILI
                )
                data = resp.json()
            items = [
                (v.get("title", ""), v.get("owner", {}).get("name", ""), v.get("bvid", ""))
                for v in (data.get("data") or {}).get("list", [])[:5]
            ]
            if items:
                _POPULAR_CACHE[0] = dt.datetime.now()
                _POPULAR_CACHE[1] = items
        except Exception:  # noqa: BLE001
            return None
    if not items:
        return None
    lines = [f"{i+1}. {t[:40]}（UP：{o}）<https://www.bilibili.com/video/{b}>"
             for i, (t, o, b) in enumerate(items)]
    return "【B站当前热门视频】\n" + "\n".join(lines) + "\n把以上列表原样推荐给用户，链接不要改写。"


async def poem_block(question: str) -> str | None:
    if not any(w in question for w in _POEM_WORDS):
        return None
    today = dt.date.today().isoformat()
    if _POEM_CACHE[0] == today:
        return _POEM_CACHE[1]
    try:
        async with httpx.AsyncClient(timeout=6) as client:
            resp = await client.get("https://v1.jinrishici.com/all.json")
            data = resp.json()
        text = f"【今日诗句】“{data.get('content', '')}”——{data.get('author', '')}《{data.get('origin', '')}》"
        _POEM_CACHE[0] = today
        _POEM_CACHE[1] = text
        return text
    except Exception:  # noqa: BLE001
        return None
