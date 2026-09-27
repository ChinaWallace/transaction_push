from copy import deepcopy
from dataclasses import asdict, replace
import tempfile
import unittest
from unittest.mock import patch

from app.advisory.engine import Candle, DAY, analyze, features, iso, plan, policy_for
from app.advisory.backtest import History, run_portfolio
from app.advisory.portfolio import Portfolio
from app.advisory.paper import PaperLedger, paper_cycle
from app.advisory.market import MarketDataError
from tests.test_market_advisory import START, candles

STEP = DAY//6
NOW = START+301*DAY


def signal(symbol="ZECUSDT", now=NOW, price=100, score=90):
    return {"symbol": symbol, "selection_score": score, "signal_time": iso(now-1),
            "execution_quote_volume": 30_000_000,
            "short_term": {"action": "buy_candidate", "entry_zone": [price*.95, price*1.05],
                           "stop_loss": price*.9, "take_profit_reference": price*1.3,
                           "account_risk_budget_pct": .75, "setup": "continuation",
                           "trailing_stop_reference": 0, "max_holding_bars": 42}}


def bar(open_=100, high=105, low=95, close=100, now=NOW):
    return Candle(now, open_, high, low, close, 1000, now+STEP-1, 30_000_000)


class PortfolioTests(unittest.TestCase):
    def test_shared_cash_and_entry_caps(self):
        book = Portfolio(policy_for("active"))
        rows = [signal(s) for s in ("BTCUSDT", "ETHUSDT", "ZECUSDT", "SOLUSDT", "LINKUSDT")]
        book.on_open(NOW, rows, {r["symbol"]:100 for r in rows})
        self.assertGreaterEqual(book.cash, 0)
        self.assertLessEqual(len(book.positions), 4)
        self.assertLessEqual(book.exposure()/book.equity(), .6+1e-10)
        self.assertLessEqual(book.open_risk()/book.equity(), .03+1e-10)
        self.assertTrue(all(p["quantity"]*100/book.equity() <= .2+1e-10 for p in book.positions.values()))
        book.liquidate(NOW+STEP-1)
        self.assertAlmostEqual(book.cash-book.initial_cash, sum(t["pnl_usdt"] for t in book.trades))
        self.assertLess(book.cash, book.initial_cash)

    def test_lower_rank_candidate_survives_top_cooldown(self):
        book = Portfolio(policy_for("active", max_positions=1))
        rows = [signal(s, score=100-i) for i,s in enumerate(("AAUSDT","BBUSDT","CCUSDT"))]
        book.cooldown = {"AAUSDT":NOW+DAY, "BBUSDT":NOW+DAY}
        book.on_open(NOW, rows, {r["symbol"]:100 for r in rows})
        self.assertEqual(list(book.positions), ["CCUSDT"])

    def test_stop_has_priority_over_target_and_gap_uses_open(self):
        book = Portfolio(policy_for("active"))
        book.on_open(NOW, [signal()], {"ZECUSDT":100})
        book.on_close(NOW+STEP-1, {"ZECUSDT":bar(high=140,low=80)})
        self.assertEqual(book.events[-1]["reason"], "stop")
        self.assertAlmostEqual(book.events[-1]["price"], 90*(1-book.slip))
        second = Portfolio(policy_for("active"))
        second.on_open(NOW,[signal()],{"ZECUSDT":100})
        second.on_open(NOW+STEP,[],{"ZECUSDT":80})
        self.assertEqual(second.events[-1]["reason"],"gap_stop")
        self.assertAlmostEqual(second.events[-1]["price"],80*(1-second.slip))

    def test_only_one_winner_add_and_no_same_signal_add(self):
        book = Portfolio(policy_for("active"))
        book.on_open(NOW, [signal()], {"ZECUSDT":100})
        book.on_open(NOW+STEP, [signal(now=NOW+STEP,price=98)], {"ZECUSDT":98})
        self.assertEqual(len(book.events),1)
        for i in (2,3):
            book.on_open(NOW+i*STEP,[signal(now=NOW+i*STEP,price=113)],{"ZECUSDT":113})
        self.assertEqual(book.positions["ZECUSDT"]["adds"],1)
        self.assertEqual(book.positions["ZECUSDT"]["opened_at"],NOW)
        self.assertGreaterEqual(book.positions["ZECUSDT"]["stop"],90)

    def test_partial_once_then_trailing_exit(self):
        book = Portfolio(policy_for("active"))
        book.on_open(NOW, [signal()], {"ZECUSDT":100})
        original = book.positions["ZECUSDT"]["quantity"]
        book.on_close(NOW+STEP-1, {"ZECUSDT":bar(high=135,low=95,close=132)})
        self.assertAlmostEqual(book.positions["ZECUSDT"]["quantity"],original*2/3)
        book.on_open(NOW+STEP,[signal(now=NOW+STEP,price=132)],{"ZECUSDT":132})
        book.on_close(NOW+2*STEP-1,{"ZECUSDT":bar(open_=132,high=136,low=110,close=120,now=NOW+STEP)})
        self.assertEqual(sum(e["reason"]=="partial_take_profit" for e in book.events),1)
        self.assertGreater(book.positions["ZECUSDT"]["stop"],100)
        book.on_open(NOW+2*STEP,[],{"ZECUSDT":90})
        self.assertFalse(book.positions)

    def test_future_signal_rejected_and_missing_position_quote_freezes_entries(self):
        book = Portfolio(policy_for("active"))
        future = signal(now=NOW+1)
        with self.assertRaisesRegex(ValueError,"precede"):
            book.on_open(NOW,[future],{"ZECUSDT":100})
        book.on_open(NOW,[signal()],{"ZECUSDT":100})
        book.on_open(NOW+STEP,[signal("ETHUSDT",now=NOW+STEP)],{"ETHUSDT":100})
        self.assertNotIn("ETHUSDT",book.positions)
        self.assertEqual(book.rejections[-1]["reason"],"incomplete_valuation")

    def test_time_exit_and_drawdown_pause(self):
        book = Portfolio(policy_for("active"))
        book.on_open(NOW,[signal()],{"ZECUSDT":100})
        book.on_open(NOW+42*STEP,[],{"ZECUSDT":100})
        self.assertEqual(book.events[-1]["reason"],"time_exit")
        book.cash=8000
        book.record_equity(NOW+43*STEP)
        book.on_open(NOW+44*STEP,[signal(now=NOW+44*STEP)],{"ZECUSDT":100})
        self.assertFalse(book.positions)
        self.assertEqual(book.rejections[-1]["reason"],"portfolio_drawdown_cooldown")


class RuleTests(unittest.TestCase):
    def test_active_continuation_and_overextension(self):
        f=features(candles(growth=.001))
        f.update(close=110,ema20=108,ema50=100,ema20_rising=True,return7_pct=3,
                 previous_close=109,volume_ratio=.9,extension_atr=1,atr=2,last_low=109.5,
                 low5=106,prior_high20=115,prior_high60=116,high20=116)
        p=plan("short_term",f,{**f,"rs30_btc_pct":20},20,"normal",85,NOW,policy_for("active"))
        self.assertEqual((p["action"],p["setup"]),("buy_candidate","continuation"))
        self.assertEqual(p["account_risk_budget_pct"],.375)
        f["extension_atr"]=6
        self.assertEqual(plan("short_term",f,f,20,"normal",85,NOW,policy_for("active"))["action"],"wait_pullback")

    def test_live_replay_parity_and_future_suffix_invariance(self):
        asof=START+340*DAY
        snapshot={"as_of":asof,"symbols":{}}
        for s,g in (("BTCUSDT",.0002),("ZECUSDT",.001)):
            snapshot["symbols"][s]={"1d":candles(340,growth=g),"4h":candles(2040,STEP,growth=g/6)}
        history=History(snapshot)
        now=START+330*DAY
        rows,_=history.signals(now,policy_for("active"),"short_term",["ZECUSDT"])
        z=snapshot["symbols"]["ZECUSDT"]
        live=analyze("ZEC",z["1d"],z["4h"],snapshot["symbols"]["BTCUSDT"]["1d"],now,policy_for("active"))
        self.assertEqual(rows[0]["short_term"],live["short_term"])
        self.assertEqual(rows[0]["long_term"],live["long_term"])
        changed=deepcopy(snapshot)
        for intervals in changed["symbols"].values():
            for interval,bars in intervals.items():
                intervals[interval]=[replace(b,open=b.open*2,high=b.high*2,low=b.low*2,close=b.close*2) if b.open_time>=now else b for b in bars]
        self.assertEqual(rows,History(changed).signals(now,policy_for("active"),"short_term",["ZECUSDT"])[0])


class PaperTests(unittest.TestCase):
    def report(self, now=NOW, price=100):
        row=signal(now=now,price=price)
        row.update(last_price=price,bid_price=price-.01,ask_price=price+.01,quote_time=iso(now),quote_valid=True,four_hour_close_time=iso(NOW-1),
                   execution_quote_volume={"short_term":30_000_000})
        row["short_term"]["valid_until"]=iso(NOW+STEP)
        return {"status":"ok","policy":asdict(policy_for("active")),"published_at":iso(now),"ranking":[row]}

    def test_restart_idempotency_and_quote_exit(self):
        with tempfile.TemporaryDirectory() as root:
            path=root+"/paper.sqlite3"
            ledger=PaperLedger(path)
            first=ledger.step(self.report(),now=NOW)
            self.assertEqual(len(first["new_events"]),1)
            second=PaperLedger(path).step(self.report(),now=NOW)
            self.assertEqual(second["new_events"],[])
            third=ledger.step(self.report(NOW+1000,101),now=NOW+1000)
            self.assertEqual(third["new_events"],[])
            exit_=ledger.step(self.report(NOW+2000,80),now=NOW+2000)
            self.assertEqual(exit_["new_events"][0]["reason"],"observed_stop")
            self.assertEqual(exit_["trade_count"],1)
            self.assertFalse(exit_["positions"])

    def test_stale_quote_cannot_buy_and_stale_delivery_fails(self):
        with tempfile.TemporaryDirectory() as root:
            ledger=PaperLedger(root+"/paper.sqlite3")
            report=self.report()
            report["ranking"][0]["quote_time"]=iso(NOW-180000)
            self.assertFalse(ledger.step(report,now=NOW)["positions"])
            with self.assertRaisesRegex(ValueError,"stale"):
                ledger.step(report,now=NOW+180000)

    def test_scan_failure_still_exits_at_bid_with_fresh_quote(self):
        with tempfile.TemporaryDirectory() as root:
            ledger=PaperLedger(root+"/paper.sqlite3")
            first=ledger.step(self.report(),now=NOW)
            self.assertAlmostEqual(first["new_events"][0]["price"],100.01*1.0005)
            ticker={"lastPrice":"85","bidPrice":"80","askPrice":"81","closeTime":NOW+1000}
            with patch("app.advisory.service.advisory_service.report",side_effect=MarketDataError("HTTP 429")), patch("app.advisory.paper.time.time",return_value=(NOW+1000)/1000), patch("app.advisory.market.BinancePublicClient.get",return_value=ticker):
                report,result=paper_cycle(ledger=ledger)
            self.assertEqual(report["status"],"degraded")
            self.assertFalse(result["positions"])
            self.assertEqual(result["new_events"][0]["reason"],"observed_stop")
            self.assertAlmostEqual(result["new_events"][0]["price"],80*.9995)


if __name__ == "__main__":
    unittest.main()
