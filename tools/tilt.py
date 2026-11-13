"""
直前情報(展示タイム・チルト)を取ってくる部品

チルトは、モーターの取り付け角度です。
  ・0や-0.5 … ふつう(スタート後の出足・回りやすさ重視)
  ・+0.5以上 … 「チルトを跳ねる」と言い、直線の伸び(スピード)重視。外の艇がまくりを狙う合図になりやすい
展示航走(レース前の試し走り)が終わると、公式サイトの「直前情報」に載ります。

使い方(確認用。boatrace フォルダで実行):
    python tilt.py 20261031 24 1     → 大村(24)1Rの直前情報を取って表示
"""

import json
import re
import sys
import urllib.request
from html import unescape
from pathlib import Path

BASE = Path(__file__).parent
BEFORE_DIR = BASE / "data" / "before"
URL = "https://www.boatrace.jp/owpc/pc/race/beforeinfo?rno={rno}&jcd={jcd}&hd={date}"
TILT_JUMP = 0.5          # これ以上を「チルト跳ね」とする

# 艇ごとのかたまり: 艇番 … 体重 … 展示タイム … チルト
BOAT_BLOCK = re.compile(
    r'is-boatColor([1-6]) is-fs14".*?<td rowspan="2">[^<]*</td>\s*'
    r'<td rowspan="4">([^<]*)</td>\s*<td rowspan="4">([^<]*)</td>', re.S)
# スタート展示: 上の行から1コース・2コース…の順に、艇番とST(例 .13 / F.06)が並ぶ
START_ROW = re.compile(r'table1_boatImage1Number is-type\d">([1-6])</span>.*?table1_boatImage1Time[^>]*>([^<]*)<', re.S)


def _num(text: str) -> float | None:
    text = unescape(text).strip()
    try:
        return float(text)
    except ValueError:
        return None


def parse_before(html: str) -> dict | None:
    """
    直前情報のページから、艇ごとの展示タイム・チルトと、水面の風を取り出す。
    戻り値: {"艇": {"1": {"展示": 6.85, "チルト": 0.5, "進入": 1, "ST": ".13"}, ...}, "風": {"風速": 3, "アイコン": 13, ...}}
    まだ展示が終わっていない(展示タイムが空)なら None。
    """
    from wind import parse_wind
    boats = {}
    for lane, ex, tilt in BOAT_BLOCK.findall(html):
        boats[lane] = {"展示": _num(ex), "チルト": _num(tilt)}
    if len(boats) < 5 or all(b["展示"] is None for b in boats.values()):
        return None
    start = html.find("スタート展示")
    if start >= 0:
        for course, (lane, st) in enumerate(START_ROW.findall(html[start:html.find("</table>", start)]), 1):
            if lane in boats:
                boats[lane]["進入"] = course
                boats[lane]["ST"] = unescape(st).strip() or None
    return {"艇": boats, "風": parse_wind(html)}


def fetch_before(date: str, jcd: str, rno: int) -> dict | None:
    req = urllib.request.Request(URL.format(rno=rno, jcd=jcd, date=date),
                                 headers={"User-Agent": "Mozilla/5.0 (boatrace-study-tool)"})
    with urllib.request.urlopen(req, timeout=20) as res:
        return parse_before(res.read().decode("utf-8", errors="replace"))


def before_path(date: str) -> Path:
    return BEFORE_DIR / f"before_{date}.json"


def load_day(date: str) -> dict:
    p = before_path(date)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_day(date: str, data: dict):
    BEFORE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = before_path(date).with_suffix(".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    tmp.replace(before_path(date))


def tilt_jumps(before: dict | None) -> list[tuple[int, float]]:
    """チルトを跳ねている艇の [(艇番, チルト), ...]"""
    if not before or not before.get("艇"):
        return []
    return sorted((int(k), v["チルト"]) for k, v in before["艇"].items()
                  if v.get("チルト") is not None and v["チルト"] >= TILT_JUMP)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    info = fetch_before(sys.argv[1], sys.argv[2], int(sys.argv[3]))
    print(info, "チルト跳ね:", tilt_jumps(info))
