"""Command line helper for TW Stock Tracker.

Examples:
  python cli.py serve                 # start web + scheduler on http://127.0.0.1:8000
  python cli.py add 2330 --note 台積電
  python cli.py add 6488
  python cli.py list
  python cli.py update                # daily prices + institutional + margin + alerts
  python cli.py backfill 2330 --months 12
  python cli.py flows --days 20
  python cli.py quote
  python cli.py alerts
  python cli.py notify-test
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

if sys.platform == "win32":  # make Chinese output work in cmd/PowerShell
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s", datefmt="%H:%M:%S")
logging.getLogger("httpx").setLevel(logging.WARNING)


def _dump(obj) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="TW Stock Tracker CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("serve", help="run the web server (with scheduler)")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--reload", action="store_true")

    a = sub.add_parser("add", help="add a code to the watchlist and backfill history")
    a.add_argument("code")
    a.add_argument("--note")
    a.add_argument("--no-backfill", action="store_true")

    r = sub.add_parser("remove", help="remove a code from the watchlist")
    r.add_argument("code")

    sub.add_parser("list", help="show watchlist overview")
    sub.add_parser("update", help="run daily prices + institutional + margin + alert evaluation")

    b = sub.add_parser("backfill", help="backfill daily history for a code")
    b.add_argument("code")
    b.add_argument("--months", type=int)

    f = sub.add_parser("flows", help="backfill institutional + margin history for the watchlist")
    f.add_argument("--days", type=int, default=20)

    mk = sub.add_parser("market", help="fetch whole-market data for breadth / sector analysis")
    mk.add_argument("--days", type=int, default=1, help="backfill this many business days (default: latest only)")

    sc = sub.add_parser("screen", help="run the multi-factor stock screener on the latest market day")
    sc.add_argument("--preset", default="balanced", help="balanced | momentum | chips | contrarian")
    sc.add_argument("--top", type=int, default=20)
    sc.add_argument("--min-turnover", type=float, default=50_000_000)
    sc.add_argument("--notify", action="store_true")

    sub.add_parser("quote", help="poll realtime quotes once")
    sub.add_parser("alerts", help="evaluate daily alert rules now")
    sub.add_parser("notify-test", help="send a test notification to all configured channels")

    args = p.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn

        uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)
        return 0

    from app import scheduler as sched
    from app.db import init_db, session_scope
    from app.models import WatchlistItem
    from app.services import alerts
    from app.services import market_data as md
    from app.services.notifier import notifier

    init_db()

    if args.cmd == "add":
        code = args.code.upper()
        with session_scope() as db:
            stock = md.ensure_stock(db, code)
            exists = db.query(WatchlistItem).filter_by(code=code).first()
            if exists:
                print(f"{code} already in watchlist")
            else:
                db.add(WatchlistItem(code=code, note=args.note))
                print(f"added {code} {stock.name} ({stock.market})")
        if not args.no_backfill:
            with session_scope() as db:
                n = md.backfill_daily(db, code)
                md.update_daily_prices(db, {code})
                flows = md.backfill_flows(db, days=20, check_codes={code})
            _dump({"daily_rows": n, **flows})
        return 0

    if args.cmd == "remove":
        with session_scope() as db:
            item = db.query(WatchlistItem).filter_by(code=args.code.upper()).first()
            if not item:
                print("not in watchlist")
                return 1
            db.delete(item)
        print("removed")
        return 0

    if args.cmd == "list":
        with session_scope() as db:
            rows = md.watchlist_overview(db)
        if not rows:
            print("watchlist is empty")
            return 0
        def cell(v, fmt_spec=""):
            return "-" if v is None else format(v, fmt_spec)

        print(f"{'code':<8}{'name':<10}{'mkt':<6}{'price':>10}{'chg%':>8}{'vol(lots)':>10}{'foreign':>10}{'trust':>8}{'margin':>10}")
        for r in rows:
            name = (r["name"] or "")[:8]
            print(
                f"{r['code']:<8}{name:<10}{r['market'] or '':<6}"
                f"{cell(r['price']):>10}"
                f"{cell(r['change_pct'], '+.2f'):>8}"
                f"{cell(r['volume_lots']):>10}"
                f"{cell(r['foreign_net_lots']):>10}"
                f"{cell(r['trust_net_lots']):>8}"
                f"{cell(r['margin_balance']):>10}"
            )
        return 0

    if args.cmd == "update":
        _dump(sched.run_job("full_daily"))
        return 0

    if args.cmd == "backfill":
        with session_scope() as db:
            n = md.backfill_daily(db, args.code, args.months)
        print(f"backfilled {n} rows")
        return 0

    if args.cmd == "flows":
        with session_scope() as db:
            _dump(md.backfill_flows(db, days=args.days))
        return 0

    if args.cmd == "market":
        from app.services import breadth

        with session_scope() as db:
            if args.days > 1:
                _dump(breadth.backfill_market(db, days=args.days))
            else:
                _dump(breadth.update_market_day(db))
            b = breadth.compute_breadth(db)
        if b.get("available"):
            a = b["markets"]["ALL"]
            print(f"{b['date']}  上漲 {a['advance']}  下跌 {a['decline']}  平盤 {a['flat']}  漲停 {a['limit_up']}  跌停 {a['limit_down']}  上漲比例 {a['adv_ratio']}%  中位數 {a['median_pct']}%  加權 {b['index_pct']}%")
            for s in b["sectors"][:5]:
                print(f"  強勢 {s['name']:<10} {s['avg_pct']:+.2f}%  ({s['advance']}/{s['count']})")
            for s in b["sectors"][-5:]:
                print(f"  弱勢 {s['name']:<10} {s['avg_pct']:+.2f}%  ({s['advance']}/{s['count']})")
        return 0

    if args.cmd == "screen":
        from app.services import screener

        with session_scope() as db:
            r = screener.run_screener(db, preset=args.preset, min_turnover=args.min_turnover, top=args.top, notify=args.notify)
        print(f"{r['date']}  {r.get('label', r['preset'])}  universe={r['universe']}")
        for x in r["results"]:
            fx = x["factors"]
            print(f"{x['rank']:>3}. {x['code']:<6} {(fx.get('name') or '')[:6]:<7} {fx.get('sector_name') or '':<8} {x['score']:5.1f}  {fx.get('pct') if fx.get('pct') is not None else '-':>6}%  {' / '.join(x['tags'])}")
        return 0

    if args.cmd == "quote":
        with session_scope() as db:
            quotes = md.update_realtime(db)
            events = alerts.evaluate_intraday(db, quotes)
        for q in quotes:
            print(f"{q['code']:<8}{q['name'] or '':<10}{q['price']!s:>10}{(q['change_pct'] or 0):>+8.2f}%  {q['trade_date']} {q['trade_time']}")
        print(f"{len(events)} alert(s) fired")
        return 0

    if args.cmd == "alerts":
        with session_scope() as db:
            events = alerts.evaluate_daily(db)
        for e in events:
            print(e.message)
        print(f"{len(events)} alert(s) fired")
        return 0

    if args.cmd == "notify-test":
        _dump(notifier.send("TW Stock Tracker", "測試通知 / test notification"))
        return 0

    return 1


if __name__ == "__main__":
    sys.exit(main())
