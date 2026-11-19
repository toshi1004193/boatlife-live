"""
オリジナル展示データ(一周・まわり足・直線のタイム)を、各レース場の公式サイトから取ってくる部品

展示航走(レース前の試し走り)で、レース場が独自に測っているタイムです。
  ・一周   … 1周の速さ(桐生は「半周」)。全体の速さの目安
  ・まわり足 … ターンの速さ。ターン回りの足の良さ
  ・直線   … 直線の速さ。伸び足の良さ
どれも「小さいほど速い」。公式の直前情報(boatrace.jp)には載っていないので、場ごとのサイトから取ります。
公表している場だけ対応しています(下の SOURCES)。公表していない場は、公式の展示タイムだけを表示します。

使い方(確認用。boatrace フォルダで実行):
    python tenji.py 20261113 08 1     → 常滑(08)1Rのオリジナル展示データを取って表示
"""

import datetime
import re
import sys
import urllib.error
import urllib.request
from html import unescape

UA = {"User-Agent": "Mozilla/5.0 (boatrace-study-tool)"}
WAIT_SECONDS = 2          # 同じ場のサイトに続けて取りに行くとき、1回ごとに待つ秒数

# 場コード → (取りに行くURL, 形式)。{d}=日付8けた、{r}=レース番号、{rr}=レース番号2けた
# 2026年11月に、実際に取れることを確かめた場だけ。
_GROUP = "https://{host}/modules/yosou/group-cyokuzen.php?day={{d}}&race={{r}}&kind=2"
SOURCES = {
    "01": ("https://www.kiryu-kyotei.com/modules/yosou/cyokuzen.php?day={d}&race={r}", "html"),
    "02": ("https://www.boatrace-toda.jp/xml/kaisai/{d}/race_table_original_{rr}.xml", "toda"),
    # 平和島・丸亀は「競技情報」のページ(日付がなく、その日の分しか見られない)。2026/11/19 に追加
    "04": ("https://www.heiwajima.gr.jp/asp/kyogi/04/pc/yoso05{rr}.htm", "kyogi"),
    "06": (_GROUP.format(host="www.boatrace-hamanako.jp"), "html"),
    "08": (_GROUP.format(host="www.boatrace-tokoname.jp"), "html"),
    "09": ("https://www.boatrace-tsu.com/modules/yosou/group-tenji.php?day={d}&race={r}&kind=1", "html"),
    "10": (_GROUP.format(host="www.boatrace-mikuni.jp"), "html"),
    "11": ("https://www.boatrace-biwako.jp/modules/yosou/cyokuzen.php?day={d}&race={r}&if=0&kind=2", "html"),
    "13": (_GROUP.format(host="www.boatrace-amagasaki.jp"), "html"),
    "14": (_GROUP.format(host="www.n14.jp"), "html"),
    "15": ("https://www.marugameboat.jp/asp/kyogi/15/pc/yoso05{rr}.htm", "kyogi"),
    "19": (_GROUP.format(host="www.boatrace-shimonoseki.jp"), "html"),
    "20": (_GROUP.format(host="www.wmb.jp"), "html"),
    "21": (_GROUP.format(host="www.boatrace-ashiya.com"), "html"),
    "23": (_GROUP.format(host="www.boatrace-karatsu.jp"), "html"),
}

ITEMS = ("一周", "まわり足", "直線")        # 表示する順。桐生は「一周」の代わりに「半周」
_LABELS = {"一周": "一周", "半周": "一周", "まわり足": "まわり足", "回り足": "まわり足", "直線": "直線"}
# ありえない値(読み取りまちがい)を捨てるための範囲(秒)
_RANGE = {"一周": (15.0, 45.0), "まわり足": (3.0, 14.0), "直線": (4.0, 11.0)}

_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_TD = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_TAG = re.compile(r"<[^>]+>")
_EXHIBIT = re.compile(r"^\d\.\d\d$")


def supported(jcd: str) -> bool:
    return jcd in SOURCES


def _text(cell: str) -> str:
    return re.sub(r"\s+", " ", unescape(_TAG.sub(" ", cell))).strip()


def _num(text: str, item: str) -> float | None:
    try:
        v = float(text)
    except ValueError:
        return None
    lo, hi = _RANGE[item]
    return v if lo <= v <= hi else None


def parse_html(html: str) -> dict | None:
    """
    場のサイトの表から、艇ごとのタイムを取り出す。
    表の見出しに出てくる順(一周/半周・まわり足・直線)に、展示タイムのすぐ後ろの列から読む。
    戻り値: {"項目": {"一周": "一周" or "半周", ...}, "艇": {"1": {"一周": 36.47, "まわり足": 5.30, "直線": 7.07}, ...}}
    """
    start = html.find("<thead")
    if start < 0:
        return None
    end = html.find("</table>", start)
    table = html[start:end if end > 0 else None]
    head = _text(table[:table.find("</thead>")])
    found = sorted((head.find(w), w) for w in _LABELS if w in head)
    if not found:
        return None
    names = [w for _, w in found]                       # 見出しの順(例: ["半周", "まわり足", "直線"])
    boats = {}
    for row in _TR.findall(table[table.find("</thead>"):]):
        cells = [_text(c) for c in _TD.findall(row)]
        if not cells or cells[0] not in ("1", "2", "3", "4", "5", "6"):
            continue
        # 展示タイム(6.xx の形)を探し、その後ろの列を見出しの順に読む
        at = next((i for i, c in enumerate(cells[1:], 1) if _EXHIBIT.match(c) and 5.5 <= float(c) <= 8.0), None)
        if at is None:
            continue
        times = {}
        for name, cell in zip(names, cells[at + 1:at + 1 + len(names)]):
            item = _LABELS[name]
            times[item] = _num(cell, item)
        boats[cells[0]] = times
    if len(boats) < 5 or all(v is None for b in boats.values() for v in b.values()):
        return None
    return {"項目": {_LABELS[n]: n for n in names}, "艇": boats}


def parse_toda(xml: str) -> dict | None:
    """戸田の XML(<record><teiban>1</teiban>…<rnd>一周</rnd><cnr>まわり足</cnr><str>直線</str>)。"""
    boats = {}
    for rec in re.findall(r"<record>(.*?)</record>", xml, re.S):
        get = lambda tag: (re.search(rf"<{tag}>([^<]*)</{tag}>", rec) or [None, ""])[1].strip()
        lane = get("teiban")
        if lane in ("1", "2", "3", "4", "5", "6"):
            boats[lane] = {"一周": _num(get("rnd"), "一周"), "まわり足": _num(get("cnr"), "まわり足"),
                           "直線": _num(get("str"), "直線")}
    if len(boats) < 5 or all(v is None for b in boats.values() for v in b.values()):
        return None
    return {"項目": {"一周": "一周", "まわり足": "まわり足", "直線": "直線"}, "艇": boats}


_TWO = re.compile(r"^\d{1,2}\.\d\d$")


def parse_kyogi(html: str) -> dict | None:
    """
    平和島・丸亀などの「競技情報」のページ。展示タイムと一周の間に体重などの列がある場もあるので、
    展示タイムより後ろで最初に出てくる「小数2けた」の値から、見出しの順に3つ読む。
    3つとも小数2けたでなければ(「-」で計れなかったなど)、その艇は空にする(ずれて読まないように)。
    ページの JS 版(cf/functions/api/live.js の parseKyogi)と同じ読み方。
    """
    at = html.find("まわり足")
    if at < 0:
        return None
    table = html[html.rfind("<table", 0, at):html.find("</table>", at)]
    he = table.find("</thead>")
    if he < 0:
        return None
    head = _text(table[:he])
    names = [w for _, w in sorted((head.find(w), w) for w in _LABELS if w in head)]
    if len(names) != 3:
        return None
    boats = {}
    for body in table[he:].split("<tbody")[1:]:
        tr = _TR.search(body)
        if not tr:
            continue
        cells = [_text(c) for c in _TD.findall(tr.group(1))]
        if not cells or cells[0] not in ("1", "2", "3", "4", "5", "6"):
            continue
        ex = next((i for i, c in enumerate(cells[1:], 1) if _EXHIBIT.match(c) and 5.5 <= float(c) <= 8.0), None)
        if ex is None:
            continue
        rest = cells[ex + 1:]
        first = next((i for i, c in enumerate(rest) if _TWO.match(c)), None)
        three = rest[first:first + 3] if first is not None else []
        ok = len(three) == 3 and all(_TWO.match(c) for c in three)
        boats[cells[0]] = {_LABELS[n]: (_num(three[j], _LABELS[n]) if ok else None) for j, n in enumerate(names)}
    if len(boats) < 5 or all(v is None for b in boats.values() for v in b.values()):
        return None
    return {"項目": {_LABELS[n]: n for n in names}, "艇": boats}


def fetch_original(date: str, jcd: str, rno: int) -> dict | None:
    """そのレースのオリジナル展示データ。対応していない場・まだ出ていないときは None。"""
    if jcd not in SOURCES:
        return None
    url, kind = SOURCES[jcd]
    if kind == "kyogi" and date != f"{datetime.date.today():%Y%m%d}":
        return None                   # 日付のないページなので、今日の分しか取れない
    url = url.format(d=date, r=rno, rr=f"{rno:02d}")
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            body = res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:             # まだ展示前(戸田は展示が終わるまでファイルがない)
            return None
        raise
    if kind == "toda":
        return parse_toda(body)
    return parse_kyogi(body) if kind == "kyogi" else parse_html(body)


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    print(fetch_original(sys.argv[1], sys.argv[2], int(sys.argv[3])))
