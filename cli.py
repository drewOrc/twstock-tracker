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

    a = sub.add_parser("add", help="add a code to a watchlist and backfill history")
    a.add_argument("code")
    a.add_argument("--note")
    a.add_argument("--list", dest="list_name", help="watchlist name (created if missing; default: the default list)")
    a.add_argument("--no-backfill", action="store_true")

    r = sub.add_parser("remove", help="remove a code from a watchlist (all user lists when --list omitted)")
    r.add_argument("code")
    r.add_argument("--list", dest="list_name")

    ls = sub.add_parser("list", help="show watchlist overview")
    ls.add_argument("--list", dest="list_name", help="only this watchlist")

    sub.add_parser("lists", help="show all watchlists with counts")
    sub.add_parser("sync-lists", help="rebuild the system watchlists (CRM, screener, alerts)")

    us = sub.add_parser("users", help="manage local accounts")
    usub = us.add_subparsers(dest="ucmd", required=True)
    uc = usub.add_parser("create", help="create a user (prompts for the password when --password is omitted)")
    uc.add_argument("username")
    uc.add_argument("--password")
    uc.add_argument("--admin", action="store_true")
    uc.add_argument("--name", dest="display_name")
    uc.add_argument("--line", dest="line_user_id")
    uc.add_argument("--email")
    up = usub.add_parser("passwd", help="set a user's password (logs them out everywhere)")
    up.add_argument("username")
    up.add_argument("--password")
    usub.add_parser("list", help="list users")
    ud = usub.add_parser("disable", help="disable a user")
    ud.add_argument("username")
    ue = usub.add_parser("enable", help="re-enable a user")
    ue.add_argument("username")
    kn_p = sub.add_parser("knowledge", help="shared knowledge layer (companies, edges, briefs, financials)")
    ksub = kn_p.add_subparsers(dest="kcmd", required=True)
    ki = ksub.add_parser("import-crm", help="copy the CRM's companies/edges/briefs/financials/actual metrics into knowledge_* (read-only on the source)")
    ki.add_argument("--source", default=None, help="path to stockcrm.db (default: ../stockcrm/data/stockcrm.db)")
    ksub.add_parser("stats", help="row counts of the knowledge tables")
    kf = ksub.add_parser("fetch", help="fetch official facts from TWSE/TPEx open data into the knowledge tables")
    kf.add_argument("what", choices=["monthly", "quarterly", "shares", "all"])
    ksub.add_parser("registry", help="who writes which table in the shared database")
    ksub.add_parser("sync", help="create graph nodes for every tracked TW stock")
    ksub.add_parser("highlights", help="write monthly-revenue highlights from the latest MOPS data")
    ksub.add_parser("todo", help="what the knowledge layer still lacks (profiles, highlights, edges)")
    kx = ksub.add_parser("extract", help="run the LLM extractor once (proposals only)")
    kx.add_argument("--limit", type=int, default=None)
    kx.add_argument("--company", default=None, help="one company id, e.g. TW:2330")
    kps = ksub.add_parser("propose-seed", help="queue a curated JSON seed (companies, profiles, edges) as proposals for review")
    kps.add_argument("file")
    kpa = ksub.add_parser("approve", help="approve pending proposals as the admin (all, or --kind / --ids)")
    kpa.add_argument("--kind", default=None)
    kpa.add_argument("--ids", default=None, help="comma separated")
    kh = ksub.add_parser("holdings", help="load / refresh ETF constituents as holding edges")
    kh.add_argument("fund", help="TW:0050, TW:00981A (fetched from MoneyDJ) or any id with --file")
    kh.add_argument("--file", default=None, help="JSON {as_of, source, fund_name, rows:[{company_id|code|name, name, weight_pct}]}")
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
    from app.services import alerts
    from app.services import market_data as md
    from app.services import watchlists as wls
    from app.services.notifier import notifier

    init_db()

    if args.cmd == "users":
        import getpass

        from app.models import User
        from app.services import auth

        with session_scope() as db:
            if args.ucmd == "list":
                for u in auth.list_users(db):
                    print(f"{u.id:>3}  {u.username:<16} {u.role:<7} {u.display_name or '':<12} line={'yes' if u.line_user_id else 'no':<4} email={u.email or '-':<24} {'DISABLED' if u.disabled else ''}")
                return 0
            if args.ucmd == "create":
                pw = args.password or getpass.getpass("password (min 8 chars): ")
                u = auth.create_user(db, args.username, pw, "admin" if args.admin else "member", args.display_name, args.line_user_id, args.email)
                print(f"created {u.username} ({u.role}) id={u.id}")
                return 0
            u = db.query(User).filter_by(username=args.username.lower()).first()
            if not u:
                print("no such user")
                return 1
            if args.ucmd == "passwd":
                auth.set_password(db, u, args.password or getpass.getpass("new password: "))
                print("password updated; all sessions revoked")
            elif args.ucmd in ("disable", "enable"):
                u.disabled = args.ucmd == "disable"
                db.commit()
                print(f"{u.username} {'disabled' if u.disabled else 'enabled'}")
        return 0

    if args.cmd == "knowledge":
        from pathlib import Path

        from app.config import BASE_DIR
        from app.services import knowledge as kn

        with session_scope() as db:
            if args.kcmd == "import-crm":
                src = Path(args.source) if args.source else BASE_DIR.parent / "stockcrm" / "data" / "stockcrm.db"
                _dump(kn.import_from_crm(db, src))
            elif args.kcmd == "stats":
                _dump(kn.stats(db))
            elif args.kcmd in ("sync", "highlights"):
                _dump(sched.run_job("knowledge_sync" if args.kcmd == "sync" else "knowledge_highlights"))
            elif args.kcmd == "holdings":
                import json as _json
                from datetime import date as _date

                from app.services import etf_holdings
                fid = args.fund.upper() if ":" in args.fund else f"TW:{args.fund.upper()}"
                if args.file:
                    spec = _json.loads(Path(args.file).read_text(encoding="utf-8"))
                    _dump(etf_holdings.apply_holdings(db, fid, spec["rows"], _date.fromisoformat(spec["as_of"]), spec["source"], spec.get("fund_name"), spec.get("prune", True)))
                else:
                    _dump(etf_holdings.refresh_tw_funds(db, [fid]))
            elif args.kcmd == "propose-seed":
                import json as _json

                from app.services import knowledge_proposals as kp
                _dump(kp.propose_seed(db, _json.loads(Path(args.file).read_text(encoding="utf-8"))))
            elif args.kcmd == "approve":
                from app.services import auth as _auth
                from app.services import knowledge_proposals as kp
                admin = _auth.ensure_admin(db)
                if args.ids:
                    ids = [int(x) for x in args.ids.split(",") if x.strip()]
                else:
                    ids = [r["id"] for r in kp.list_proposals(db, "pending", args.kind, None, 10000)]
                _dump(kp.decide_many(db, ids, True, admin))
            elif args.kcmd == "extract":
                from app.models import Company
                from app.services import extractor
                if args.company:
                    c = db.get(Company, args.company.upper())
                    _dump(extractor.extract_company(db, c) if c else {"error": "unknown company"})
                else:
                    _dump(extractor.run(db, args.limit))
            elif args.kcmd == "todo":
                from app.services import knowledge_jobs

                _dump(knowledge_jobs.todo(db))
            elif args.kcmd == "fetch":
                jobs = ["mops_monthly", "mops_quarterly", "mops_shares"] if args.what == "all" else [f"mops_{args.what}"]
                for j in jobs:
                    _dump({j: sched.run_job(j)})
            elif args.kcmd == "registry":
                from app.models import SchemaRegistry

                for r in db.query(SchemaRegistry).order_by(SchemaRegistry.layer, SchemaRegistry.table_name):
                    print(f"{r.layer:<10} {r.owner:<7} {r.table_name:<28} {r.note or ''}")
        return 0

    # watchlist commands act as the (first) admin account
    from app.services import auth as _auth

    with session_scope() as db:
        admin_id = _auth.ensure_admin(db).id

    def resolve_list(db, name: str | None, create: bool = False):
        if not name:
            return None
        for w in wls.list_watchlists(db, admin_id):
            if w["name"] == name:
                return w["id"]
        if create:
            return wls.create_watchlist(db, admin_id, name).id
        print(f"no watchlist named {name!r}")
        sys.exit(1)

    if args.cmd == "add":
        with session_scope() as db:
            lid = resolve_list(db, args.list_name, create=True)
            r = wls.add_code(db, admin_id, args.code, [lid] if lid else None, args.note)
            print(f"{'added' if r['added_to'] else 'already in list:'} {r['code']} {r['name']} ({r['market']}) lists={r['lists']}")
        if not args.no_backfill and r["is_new"]:
            with session_scope() as db:
                n = md.backfill_daily(db, r["code"])
                md.update_daily_prices(db, {r["code"]})
                flows = md.backfill_flows(db, days=20, check_codes={r["code"]})
            _dump({"daily_rows": n, **flows})
        return 0

    if args.cmd == "remove":
        with session_scope() as db:
            lid = resolve_list(db, args.list_name)
            r = wls.remove_code(db, admin_id, args.code, lid)
        print("removed" if r["removed"] else "not in watchlist", f"remaining lists={r['lists']}", "(unsubscribed, alert rules removed)" if r["unsubscribed"] else "")
        return 0

    if args.cmd == "lists":
        with session_scope() as db:
            for w in wls.list_watchlists(db, admin_id):
                print(f"{w['id']:>3}  {w['name']:<10} {w['count']:>4} 檔  {'(系統: ' + w['system_key'] + ')' if w['system_key'] else ''}")
        return 0

    if args.cmd == "sync-lists":
        with session_scope() as db:
            _dump(wls.sync_system_lists(db))
        return 0

    if args.cmd == "list":
        with session_scope() as db:
            rows = md.watchlist_overview(db, resolve_list(db, args.list_name), user_id=admin_id)
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
