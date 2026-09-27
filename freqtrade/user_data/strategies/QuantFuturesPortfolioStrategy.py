"""Dry-run execution bridge for independently generated daily contract plans.

This strategy deliberately rejects live mode. Historical evaluation belongs to
the point-in-time replay, not a backtest that reuses today's external plan.
"""
import json
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path

from freqtrade.persistence import Trade
from freqtrade.strategy import IStrategy, stoploss_from_absolute


class QuantFuturesPortfolioStrategy(IStrategy):
    INTERFACE_VERSION=3
    timeframe="5m"
    can_short=False
    startup_candle_count=2
    process_only_new_candles=False
    minimal_roi={}
    stoploss=-.66
    use_custom_stoploss=True
    position_adjustment_enable=True
    max_entry_position_adjustment=0
    use_exit_signal=True
    exit_profit_only=False

    @property
    def protections(self):
        return [{"method":"CooldownPeriod","stop_duration_candles":864}]

    def bot_start(self,**kwargs):
        if self.config.get("dry_run") is not True or self.config.get("trading_mode")!="futures" or self.config.get("margin_mode")!="isolated":
            raise ValueError("Quant v3 is restricted to isolated futures dry-run")
        if str(self.config.get("runmode","")).lower().find("backtest")>=0:
            raise ValueError("A current external plan must not be reused in historical backtesting")
        self.plan={};self.targets={};self.complete_quotes=False;self.equity=0;self.gross=0;self.used_margin=0
        self.state_path=Path(self.config["quant_plan_path"]).with_name("freqtrade_risk_state.json")
        self.risk=json.loads(self.state_path.read_text()) if self.state_path.exists() else {"peak":self.config.get("dry_run_wallet",10000),"pause_until":0}

    def _fresh(self,now):
        at=int(now.timestamp()*1000)
        return bool(self.plan.get("complete") and self.plan.get("version") in {"contracts-v3.1","contracts-v3.2"} and
                    0<=at-self.plan.get("created_at",0)<=180000 and at<=self.plan.get("valid_until",0))

    def _target(self,pair,now):
        return self.targets.get(pair) if self._fresh(now) else None

    def bot_loop_start(self,current_time,**kwargs):
        try:
            plan=json.loads(Path(self.config["quant_plan_path"]).read_text())
            targets={t["pair"]:t for t in plan["targets"]}
            if len(targets)!=len(plan["targets"]) or len(targets)>10:raise ValueError("Invalid target count")
            for t in targets.values():
                if not 1<=t["leverage"]<=3 or not 0<=t["weight"]<=.35:raise ValueError("Invalid risk bounds")
                if not all(isfinite(t[k]) and t[k]>0 for k in ("atr","stop_price")):raise ValueError("Invalid stop")
                if not 0<t["entry_zone"][0]<=t["entry_zone"][1]:raise ValueError("Invalid entry zone")
            if sum(t["weight"]/t["leverage"] for t in targets.values())>.650001:raise ValueError("Margin exceeded")
            if sum(t["weight"] for t in targets.values())>1.800001:raise ValueError("Exposure exceeded")
            self.plan,self.targets=plan,targets
        except (OSError,ValueError,KeyError,TypeError):
            self.plan={};self.targets={}
        self.equity=float(self.wallets.get_total_stake_amount());self.gross=0;self.used_margin=0;self.complete_quotes=True
        for trade in Trade.get_open_trades():
            frame,_=self.dp.get_analyzed_dataframe(trade.pair,self.timeframe)
            if frame.empty or (current_time-frame.iloc[-1]["date"].to_pydatetime()).total_seconds()>600:
                self.complete_quotes=False;continue
            rate=float(frame.iloc[-1]["close"])
            self.equity+=trade.calc_profit(rate).profit_abs
            self.gross+=trade.amount*rate;self.used_margin+=trade.stake_amount
        now=int(current_time.timestamp()*1000)
        if self.complete_quotes:
            if self.risk["pause_until"] and now>=self.risk["pause_until"]:
                self.risk={"peak":self.equity,"pause_until":0}
            self.risk["peak"]=max(self.risk["peak"],self.equity)
            if self.equity<.55*self.risk["peak"] and not self.risk["pause_until"]:
                self.risk["pause_until"]=now+28*86400000
            temporary=self.state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.risk,allow_nan=False));temporary.replace(self.state_path)

    def populate_indicators(self,dataframe,metadata):return dataframe

    def populate_entry_trend(self,dataframe,metadata):
        dataframe["enter_long"]=0
        t=self._target(metadata["pair"],datetime.now(timezone.utc))
        if t and len(dataframe):
            dataframe.loc[dataframe.index[-1],"enter_long"]=1
            dataframe.loc[dataframe.index[-1],"enter_tag"]=self.plan["signal_id"]
        return dataframe

    def populate_exit_trend(self,dataframe,metadata):
        dataframe["exit_long"]=0
        return dataframe

    def leverage(self,pair,current_time,current_rate,proposed_leverage,max_leverage,entry_tag,side,**kwargs):
        t=self._target(pair,current_time)
        return min(3,max_leverage,t["leverage"]) if t else 1

    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        t=self._target(pair,current_time)
        if not t or not self.complete_quotes:return 0
        amount=min(t["weight"]*self.equity/leverage,max_stake,.65*self.equity-self.used_margin,
                   (1.8*self.equity-self.gross)/leverage)*.995
        return amount if amount>=max(min_stake or 0,0) else 0

    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        t=self._target(pair,current_time)
        if not t or side!="long" or not self.complete_quotes or self.equity<=0:return False
        if int(current_time.timestamp()*1000)<self.risk["pause_until"]:return False
        if any(trade.pair==pair or trade.has_open_orders for trade in Trade.get_open_trades()):return False
        return (t["entry_zone"][0]<=rate<=t["entry_zone"][1] and 0<(rate-t["stop_price"])/rate<.8/t["leverage"]
                and amount*rate<=.35*self.equity and self.gross+amount*rate<=1.8*self.equity
                and self.used_margin+amount*rate/t["leverage"]<=.65*self.equity)

    def custom_stoploss(self,pair,trade,current_time,current_rate,current_profit,after_fill=False,**kwargs):
        t=self._target(pair,current_time)
        saved=trade.get_custom_data(key="quant_stop",default={})
        atr=t["atr"] if t else saved.get("atr",trade.open_rate*.055)
        high=max(current_rate,trade.max_rate or trade.open_rate,saved.get("high",0))
        stop=max(saved.get("stop",trade.open_rate*.78),t["stop_price"] if t else 0,high-5*atr)
        trade.set_custom_data(key="quant_stop",value={"atr":atr,"high":high,"stop":stop})
        return stoploss_from_absolute(min(stop,current_rate*.999),current_rate,is_short=False,leverage=trade.leverage)

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if int(current_time.timestamp()*1000)<self.risk["pause_until"]:return "portfolio_drawdown"
        saved=trade.get_custom_data(key="quant_stop",default={})
        if current_rate<=saved.get("stop",0):return "quant_price_stop"
        if self._fresh(current_time) and pair not in self.targets:return "trend_or_rank_exit"
        return None

    def adjust_trade_position(self,trade,current_time,current_rate,current_profit,min_stake,max_stake,**kwargs):
        if trade.has_open_orders or not self.complete_quotes:return None
        t=self._target(trade.pair,current_time)
        if not t:return None
        # Freqtrade partial exits use original stake/amount units, not current notional.
        excess=trade.amount*current_rate-t["weight"]*self.equity
        if excess>.03*self.equity:
            reduce_stake=excess/(trade.amount*current_rate)*trade.stake_amount
            if reduce_stake>=max(min_stake or 0,0):return -min(reduce_stake,trade.stake_amount),"target_reduce"
        return None

    def check_entry_timeout(self,pair,trade,order,current_time,**kwargs):
        return not self._fresh(current_time)
