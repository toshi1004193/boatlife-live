"""
出走表に出す選手のプロフィール・成績(公式サイトのデータ)を集める部品

  ・公式サイトの出走表ページ(boatrace.jp の racelist)… 毎日取りに行く
      支部・出身地・年齢・体重・F数・L数・平均ST・全国/当地の勝率・2連率・3連率
  ・公式のファン手帳データ(半年ごとに出る fanYYMM.lzh)… 新しいものが出たら取りに行く
      登録期・身長

出走表ページは、1日分(全レース)の中で「まだデータのない選手がいるレース」だけを取りに行きます
(同じ選手が1日に2回走ることが多いので、全156レースより少なくてすみます)。
公式サイトの反応が遅く(1ページ数秒〜10秒)、1日分で数分かかるため、取りに行くのは
公開リポジトリの5分おきのしくみ(live/live_before.py。GitHub の利用時間が無料)。
1回あたりの時間を区切って少しずつ取り、live/racelist_日付.json に保存します。
1時間おきの更新(judge.py)は、それを読んで data/racelist/racelist_日付.json に取り込むだけです。

使い方(確認用。boatrace フォルダで実行):
    python racer_info.py 20261113 4674     → その日のデータで、登番4674の選手を表示
"""

import datetime
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from html import unescape
from pathlib import Path

BASE = Path(__file__).parent
RACELIST_DIR = BASE / "data" / "racelist"
RAW_DIR = BASE / "data" / "raw"
TXT_DIR = BASE / "data" / "txt"
RACELIST_URL = "https://www.boatrace.jp/owpc/pc/race/racelist?rno={rno}&jcd={jcd}&hd={date}"
FAN_URL = "https://www.boatrace.jp/static_extra/pc_static/download/data/kibetsu/fan{yymm}.lzh"
HEADERS = {"User-Agent": "Mozilla/5.0 (boatrace-study-tool)"}
WORKERS = 4            # 公式サイトへ同時に取りに行く数(多くしすぎない)
WAIT_SECONDS = 1       # 1つの流れの中で、続けて取りに行くときに待つ秒数

# 出走表ページの選手1人分(タグを | に置きかえたあとの文字列)
# |4674 / |B1|池田　　剛規|福岡/福岡 |39歳/52.0kg |F0 |L0 |0.15 |5.66 |31.87 |59.34 |5.89 |42.22 |62.22 |
NUM = r"\|\s*([\d.]+|-)\s*"
RACER = re.compile(r"\|\s*(\d{4})\s*/\s*\|\s*([AB][12])\s*\|([^|]+)\|([^|/]+)/([^|]+)\|\s*(\d+)歳/([\d.]+)kg\s*"
                   r"\|\s*F(\d+)\s*\|\s*L(\d+)\s*" + NUM * 7)


def _num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def parse_racelist(html: str) -> dict[str, dict]:
    """出走表ページから、選手ごとのデータを取り出す。{登番: {...}}"""
    text = re.sub(r"<[^>]+>", "|", html)
    text = unescape(text).replace("\r", "")
    text = re.sub(r"\|[\s|]*\|", "|", re.sub(r"[ \t\n]+", " ", text))
    out = {}
    for m in RACER.finditer(text):
        g = [x.strip() for x in m.groups()]
        out[g[0]] = {
            "支部": g[3].replace("　", ""), "出身地": g[4].replace("　", ""),
            "年齢": int(g[5]), "体重": float(g[6]), "F": int(g[7]), "L": int(g[8]),
            "平均ST": _num(g[9]),
            "全国勝率": _num(g[10]), "全国2連率": _num(g[11]), "全国3連率": _num(g[12]),
            "当地勝率": _num(g[13]), "当地2連率": _num(g[14]), "当地3連率": _num(g[15]),
        }
    return out


def fetch_racelist(date: str, jcd: str, rno: int) -> dict[str, dict] | None:
    """1レース分の出走表ページを取る。まだ出ていなければ None。"""
    req = urllib.request.Request(RACELIST_URL.format(rno=rno, jcd=jcd, date=date), headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            html = res.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    return parse_racelist(html) or None


def racelist_path(date: str) -> Path:
    return RACELIST_DIR / f"racelist_{date}.json"


def load_racelist(date: str, path: Path | None = None) -> dict:
    p = path or racelist_path(date)
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_racelist(date: str, data: dict, path: Path | None = None):
    p = path or racelist_path(date)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


LIVE_URL = "https://raw.githubusercontent.com/toshi1004193/boatlife-live/main/live/racelist_{date}.json"


def merge_live_racelist(date: str) -> int:
    """公開リポジトリで取った選手データを、data/racelist に取り込む。足した人数を返す。"""
    try:
        req = urllib.request.Request(LIVE_URL.format(date=date), headers=HEADERS)
        with urllib.request.urlopen(req, timeout=20) as res:
            live = json.loads(res.read().decode("utf-8"))
    except Exception as e:
        print(f"  ※ 公開側の選手データが読めませんでした({e})")
        return 0
    data = load_racelist(date)
    new = {k: v for k, v in live.items() if k not in data}
    if new:
        data.update(new)
        save_racelist(date, data)
        _rl_cache.pop(date, None)
    print(f"選手データを取り込みました({len(new)} 人)")
    return len(new)


def update_racelist(date: str, races: list[tuple[str, int, list[str]]],
                    path: Path | None = None, deadline: float | None = None) -> dict:
    """
    その日のレース [(場コード, R, [登番×6])] のうち、まだデータのない選手がいるレースだけ取りに行く。
    場ごとにまとめ、WORKERS 本の流れで並行して取る。deadline(time.monotonic() の値)を過ぎたら、
    残りは次の回に回す。戻り値: {登番: {...}}
    """
    data = load_racelist(date, path)
    todo, covered = {}, set(data)
    for jcd, rno, regs in sorted(races):
        if set(regs) - covered:
            todo.setdefault(jcd, []).append(rno)
            covered |= set(regs)          # このレースを取れば、この6人はそろう(同じ選手の別レースは取らない)
    if not todo:
        return data
    print(f"選手データ(公式の出走表ページ)を {sum(map(len, todo.values()))} レース分取ります")

    def one_venue(item):
        jcd, rnos = item
        got = {}
        for i, rno in enumerate(rnos):
            if deadline and time.monotonic() > deadline:
                break
            if i:
                time.sleep(WAIT_SECONDS)
            try:
                got.update(fetch_racelist(date, jcd, rno) or {})
            except Exception as e:
                print(f"  ※ {jcd}場{rno}R の出走表ページが取れませんでした({e})")
        return got

    before = len(data)
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for got in pool.map(one_venue, todo.items()):
            data.update(got)
    if len(data) > before:
        save_racelist(date, data, path)
    print(f"  選手データ: {len(data) - before} 人分を取りました(合計 {len(data)} 人)")
    return data


# ---- ファン手帳(登録期・身長) ----
# 1人1行・416バイトの固定長(Shift-JIS)。使う欄の位置:
#   0-4 登番 / 51-54 身長(cm) / 195-198 養成期(=登録期)
FAN_RECORD = 416


def _fan_candidates(today: datetime.date) -> list[str]:
    """新しい順に、ありうるファン手帳の年月(4月版・10月版)。"""
    out = []
    for y in (today.year, today.year - 1):
        for m in (10, 4):
            if datetime.date(y, m, 1) <= today:
                out.append(f"{y % 100:02d}{m:02d}")
    return out


def _fan_txt(yymm: str) -> Path | None:
    """ファン手帳を(なければダウンロードして)解凍し、テキストの場所を返す。公開前なら None。"""
    for p in TXT_DIR.glob("*"):
        if p.name.lower() == f"fan{yymm}.txt" and p.stat().st_size > 0:
            return p
    lzh = RAW_DIR / f"fan{yymm}.lzh"
    if not lzh.exists():
        try:
            req = urllib.request.Request(FAN_URL.format(yymm=yymm), headers=HEADERS)
            with urllib.request.urlopen(req, timeout=30) as res:
                body = res.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            raise
        if not body.startswith(b"\x00") and b"-lh" not in body[:10]:
            return None                    # LZHではない(公開前のエラーページなど)
        RAW_DIR.mkdir(parents=True, exist_ok=True)
        lzh.write_bytes(body)
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    tar = shutil.which("bsdtar") or "tar"
    subprocess.run([tar, "-xf", str(lzh), "-C", str(TXT_DIR)], check=True)
    for p in TXT_DIR.glob("*"):
        if p.name.lower() == f"fan{yymm}.txt":
            return p
    return None


_fan_cache: dict | None = None


def fan_data(date: str) -> dict[str, dict]:
    """{登番: {"期": 32, "身長": 163}}。いちばん新しいファン手帳を使う。取れなければ空。"""
    global _fan_cache
    if _fan_cache is not None:
        return _fan_cache
    _fan_cache = {}
    today = datetime.datetime.strptime(date, "%Y%m%d").date()
    for yymm in _fan_candidates(today):
        try:
            txt = _fan_txt(yymm)
        except Exception as e:
            print(f"  ※ ファン手帳 fan{yymm} が読めませんでした({e})")
            continue
        if not txt:
            continue
        for rec in txt.read_bytes().splitlines():       # 改行が CRLF でも LF でも読めるように
            if len(rec) != FAN_RECORD:
                continue
            try:
                _fan_cache[rec[0:4].decode()] = {"期": int(rec[195:198]), "身長": int(rec[51:54])}
            except ValueError:
                continue
        break
    return _fan_cache


def racer_profile(date: str, reg_no: str) -> dict:
    """その選手の表示用データ(出走表ページ + ファン手帳)。取れていない項目は入らない。"""
    return {**fan_data(date).get(reg_no, {}), **load_racelist_cached(date).get(reg_no, {})}


_rl_cache: dict = {}


def load_racelist_cached(date: str) -> dict:
    if date not in _rl_cache:
        _rl_cache[date] = load_racelist(date)
    return _rl_cache[date]


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    print(racer_profile(sys.argv[1], sys.argv[2]))
