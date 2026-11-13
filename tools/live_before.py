"""
展示データ(展示タイム・ST・チルト・一周・まわり足・直線)を5分おきに取ってくるプログラム

公開リポジトリ(boatlife-live)で、GitHub が5分おきに実行します(.github/workflows/live.yml)。
非公開リポジトリ(boatlife-src)の publish.py が、このファイルと tilt.py・tenji.py・wind.py を
tools/ にコピーして公開しています。直すときは boatlife-src の live/ と元のファイルを直してください。

やること:
  1. live/races_日付.json(その日のレースと締切時刻)を読む
  2. 締切が近いレース(締切30分前〜締切70分後)のうち、まだ取れていないものだけ取りに行く
       ・公式サイト(boatrace.jp)の直前情報 … 展示タイム・スタート展示(進入・ST)・チルト・風
       ・各レース場のサイト … 一周・まわり足・直線(公表している場だけ。場ごとに並行して取る)
  3. live/before_日付.json に保存する。ページは1分おきにこのファイルを読み、展示航走の表と判定を書きかえる
  4. 選手データ(公式の出走表ページ。出身地・平均ST・F/L・勝率など)を、今日・明日の分で
     まだない選手がいるレースだけ取り、live/racelist_日付.json に保存する(1回3分まで。残りは次の回)
"""

import datetime
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from tenji import WAIT_SECONDS as SITE_WAIT, fetch_original, supported   # noqa: E402
from tilt import fetch_before                                             # noqa: E402
from racer_info import update_racelist                                    # noqa: E402

LIVE_DIR = Path(__file__).resolve().parent.parent / "live"
AHEAD = 30            # 締切まで何分以内のレースから取りに行くか(展示は締切の20〜30分前)
BEHIND = 70           # 締切を過ぎても、何分以内ならまだ取りに行くか
OFFICIAL_WAIT = 3     # 公式サイトに続けて取りに行くとき、1レースごとに待つ秒数
RACELIST_BUDGET = 180 # 選手データ(出走表ページ)を取るのに、1回あたり使ってよい秒数(残りは次の回)


def main():
    now = datetime.datetime.now()
    date = f"{now:%Y%m%d}"
    races_path = LIVE_DIR / f"races_{date}.json"
    if not races_path.exists():
        print(f"今日のレース一覧がありません: {races_path}")
        return
    races = json.loads(races_path.read_text(encoding="utf-8"))
    out_path = LIVE_DIR / f"before_{date}.json"
    saved = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else {}
    before_text = json.dumps(saved, ensure_ascii=False, sort_keys=True)

    def left(r):
        h, m = map(int, r["t"].split(":"))
        return (h * 60 + m) - (now.hour * 60 + now.minute)

    near = [r for r in races if -BEHIND <= left(r) <= AHEAD]

    # 1. 公式の直前情報(展示が終わるまでは「まだ」なので、次の回にまた取りに行く)
    official = [r for r in near if r["k"] not in saved]
    print(f"公式の直前情報: {len(official)} レース")
    for i, r in enumerate(official):
        if i:
            time.sleep(OFFICIAL_WAIT)
        jcd, rno = r["k"].split("-")
        try:
            info = fetch_before(date, jcd, int(rno))
        except Exception as e:
            print(f"  {r['k']}: 取得できませんでした({e})")
            continue
        if info is None:
            print(f"  {r['k']}: まだ展示前です")
            continue
        info["取得"] = f"{datetime.datetime.now():%H:%M}"
        saved[r["k"]] = info
        print(f"  {r['k']}: 取得しました")

    # 2. 各レース場のサイトの一周・まわり足・直線(公式の直前情報が取れたレースだけ)
    todo = {}
    for r in near:
        jcd = r["k"].split("-")[0]
        if r["k"] in saved and "オリジナル" not in saved[r["k"]] and supported(jcd):
            todo.setdefault(jcd, []).append(r)

    def one_venue(rs):
        got = []
        for i, r in enumerate(rs):
            if i:
                time.sleep(SITE_WAIT)
            jcd, rno = r["k"].split("-")
            try:
                got.append((r, fetch_original(date, jcd, int(rno))))
            except Exception as e:
                got.append((r, e))
        return got

    print(f"レース場のサイト: {sum(map(len, todo.values()))} レース({len(todo)} 場)")
    with ThreadPoolExecutor(max_workers=8) as pool:
        for got in pool.map(one_venue, todo.values()):
            for r, info in got:
                if isinstance(info, Exception):
                    print(f"  {r['k']}: 取得できませんでした({info})")
                elif info is None:
                    print(f"  {r['k']}: まだ出ていません")
                else:
                    saved[r["k"]]["オリジナル"] = info
                    print(f"  {r['k']}: 一周・まわり足・直線を取得しました")

    if json.dumps(saved, ensure_ascii=False, sort_keys=True) != before_text:
        LIVE_DIR.mkdir(exist_ok=True)
        out_path.write_text(json.dumps(saved, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"保存しました: {out_path}")
    else:
        print("変更なし")


def racelists():
    """
    選手データ(公式の出走表ページ)を、今日・明日の分で、まだない選手がいるレースだけ取る。
    公式サイトの反応が遅いので、1回あたり RACELIST_BUDGET 秒で区切り、残りは次の回に取る。
    """
    deadline = time.monotonic() + RACELIST_BUDGET
    today = f"{datetime.datetime.now():%Y%m%d}"
    for races_path in sorted(LIVE_DIR.glob("races_*.json")):
        date = races_path.stem.split("_")[1]
        if date < today or time.monotonic() > deadline:
            continue
        races = [(r["k"].split("-")[0], int(r["k"].split("-")[1]), r["r"])
                 for r in json.loads(races_path.read_text(encoding="utf-8")) if r.get("r")]
        try:
            update_racelist(date, races, path=LIVE_DIR / f"racelist_{date}.json", deadline=deadline)
        except Exception as e:
            print(f"選手データが取れませんでした({e})")


if __name__ == "__main__":
    main()
    racelists()
