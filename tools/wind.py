"""
風(向かい風・追い風・横風と風速)と、それによる有利・不利を判定する部品

【風の向きの調べ方】(2026/11/3 に確かめた)
  公式サイトの直前情報には、風向きのアイコン(is-wind1〜16)と会場の向き(is-direction1〜16)がある。
  アイコンの番号は「コース図の上で風が吹いていく向き」で、
    5〜7 あたり = 1マークに向かって吹く風 = 追い風
    13〜15 あたり = 1マークから吹いてくる風 = 向かい風
  レース結果(Kファイル)の方角(北西など)からは、次の式で同じ番号に直せる:
    アイコン番号 ≒ 方角の番号(北=1、北北東=2 … 時計回り) + 会場の向き + 8 (16で一周)

【有利・不利】2026年8〜10月・約1万4千レースの結果から:
  無風に近い(1m以下)        1号艇1着56% まくり27% 差し12%
  向かい風 4〜5m              1号艇1着52% まくり35% 差し 9%  → まくり有利
  追い風   4〜5m              1号艇1着53% まくり28% 差し14%  → 差し有利
  追い風   6m以上             1号艇1着44% まくり30% 差し20%  → イン不利・差し有利
  横風     5m以下             ほぼ無風と同じ                  → イン有利(影響小さめ)
"""

import re
from html import unescape

# 会場の向き(公式サイトの is-directionN)。場コード → 番号
VENUE_DIRECTION = {
    "01": 14, "02": 16, "03": 4, "04": 5, "05": 9, "06": 13, "07": 11, "08": 9, "09": 8, "10": 14,
    "11": 13, "12": 13, "13": 10, "14": 15, "15": 7, "16": 13, "17": 11, "18": 7, "19": 11, "20": 10,
    "21": 1, "22": 2, "23": 12, "24": 3,
}
COMPASS = ["北", "北北東", "北東", "東北東", "東", "東南東", "南東", "南南東",
           "南", "南南西", "南西", "西南西", "西", "西北西", "北西", "北北西"]

STRONG = 4          # これ以上は「強め」として目立たせる
VERY_STRONG = 6     # これ以上は「強風」


def wind_kind(icon: int) -> str:
    """コース図の上の向き(1〜16)から、追い風・向かい風・横風を決める。"""
    if 4 <= icon <= 8:
        return "追い風"
    if 12 <= icon <= 16:
        return "向かい風"
    return "横風"


def icon_from_compass(compass: str, venue: str) -> int | None:
    """Kファイルの方角(北西など)を、コース図の上の向き(1〜16)に直す。"""
    if compass not in COMPASS or venue not in VENUE_DIRECTION:
        return None
    c = COMPASS.index(compass) + 1
    return (c + VENUE_DIRECTION[venue] + 8 - 1) % 16 + 1


def effect(kind: str, speed: int) -> tuple[str, str]:
    """
    風による有利・不利のひとことと、その根拠(過去3か月の実績)。
    戻り値: (ひとこと, 根拠)
    """
    if speed <= 1:
        return "イン有利(風の影響なし)", "無風に近いとき 1号艇1着56%"
    if kind == "向かい風":
        if speed >= STRONG:
            return "まくり有利", "向かい風4m以上 まくり35%(無風27%)"
        return "ややまくり有利", "向かい風2〜3m まくり31%(無風27%)"
    if kind == "追い風":
        if speed >= VERY_STRONG:
            return "イン不利・差し有利", "追い風6m以上 1号艇1着44% 差し20%"
        if speed >= STRONG:
            return "差し有利", "追い風4〜5m 差し14%(無風12%)"
        return "イン有利(差しに注意)", "追い風2〜3m 1号艇1着56% 差し15%"
    if speed >= VERY_STRONG:
        return "荒れやすい", "横風6m以上 1号艇1着41%(レース数は少なめ)"
    return "イン有利(影響小さめ)", "横風5m以下 1号艇1着56〜57%"


def describe(kind: str, speed: int, source: str) -> dict:
    """画面に出す風の情報をまとめる。"""
    eff, basis = effect(kind, speed)
    level = "very" if speed >= VERY_STRONG else "strong" if speed >= STRONG else "calm"
    return {"向き": kind if speed > 0 else "無風", "風速": speed, "強さ": level,
            "有利": eff, "根拠": basis, "出どころ": source}


# ===== 公式サイトの直前情報から =====

def parse_wind(html: str) -> dict | None:
    """直前情報のページから、風速(m)・風向きのアイコン番号・波の高さ(cm)・時刻を取り出す。"""
    sp = re.search(r"風速</span>\s*<span[^>]*>(\d+)m", html)
    icon = re.search(r'is-windDirection">\s*<p class="weather1_bodyUnitImage is-wind(\d+)"', html)
    wave = re.search(r"波高</span>\s*<span[^>]*>(\d+)cm", html)
    when = re.search(r"水面気象情報\s*(\d{1,2}:\d{2})", unescape(html))
    if not sp:
        return None
    return {"風速": int(sp.group(1)), "アイコン": int(icon.group(1)) if icon else None,
            "波": int(wave.group(1)) if wave else None, "時刻": when.group(1) if when else ""}


def from_before(w: dict | None) -> dict | None:
    if not w or w.get("アイコン") is None:
        return None
    kind = wind_kind(w["アイコン"])
    src = f"直前情報{(' ' + w['時刻'] + '時点') if w.get('時刻') else ''}"
    return describe(kind, w["風速"], src)


# ===== レース結果(Kファイル)から(過去のレース用) =====

HEAD = re.compile(r"^\s+(\d{1,2})R\s.*H\d+m\s+\S+\s+風\s+(\S+)\s+(\d+)m")
VSTART = re.compile(r"^(\d{2})KBGN")


def winds_from_results(date: str) -> dict:
    """その日のレース結果から、レースごとの風を取り出す。{"24-1": 風の情報}"""
    from bangumi import RAW_DIR, TXT_DIR, extract
    txt = TXT_DIR / f"K{date[2:]}.TXT"
    if not txt.exists():
        lzh = RAW_DIR / f"k{date[2:]}.lzh"
        if not lzh.exists():
            return {}
        txt = extract(lzh)
    out, v = {}, None
    for line in txt.read_text(encoding="cp932", errors="replace").replace("　", " ").splitlines():
        if m := VSTART.match(line):
            v = m.group(1)
        elif m := HEAD.match(line):
            speed = int(m.group(3))
            icon = icon_from_compass(m.group(2), v)
            if icon is not None or speed == 0:
                out[f"{v}-{int(m.group(1))}"] = describe(wind_kind(icon or 1), speed, "レース結果(レース時の風)")
    return out
