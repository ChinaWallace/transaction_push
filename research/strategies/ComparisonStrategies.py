"""Frozen research candidates. No class in this file may run a trading bot.

All enter/exit signals are closed-bar signals, filled by Freqtrade on the next
5m bar. Informative bars use Freqtrade's timestamp-shifting merge helper.
"""
from datetime import timedelta
from pathlib import Path
import sys

import numpy as np
import talib.abstract as ta
from freqtrade.strategy import IStrategy, merge_informative_pair, stoploss_from_absolute
from freqtrade.persistence import Trade

VENDOR=Path(__file__).resolve().parents[1]/"vendor/NostalgiaForInfinity"
sys.path.insert(0,str(VENDOR))
from NostalgiaForInfinityX8 import NostalgiaForInfinityX8
from NostalgiaForInfinityX7 import NostalgiaForInfinityX7


class ResearchBudget:
    """Same maximum budget, not identical utilization: 1x, long-only, 70% wallet."""
    can_short=False
    def __init__(self,config):
        mode=getattr(config.get("runmode"),"value",config.get("runmode"))
        if mode not in {"backtest","util_exchange","plot"}:
            raise ValueError("These strategies are offline research only")
        if not config.get("dry_run",False):raise ValueError("Research requires dry_run=true")
        super().__init__(config)
        self.can_short=False
        for field in ("futures_mode_leverage","futures_mode_leverage_rebuy_mode","futures_mode_leverage_grind_mode"):
            if hasattr(self,field):setattr(self,field,1.0)

    def leverage(self,**kwargs):return 1.0

    def budget_per_pair(self):
        # Freqtrade's total stake amount includes tradable_balance_ratio (70%).
        return self.wallets.get_total_stake_amount()/3

    def custom_stake_amount(self,pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs):
        if side!="long":return 0
        amount=super().custom_stake_amount(pair,current_time,current_rate,proposed_stake,min_stake,max_stake,leverage,entry_tag,side,**kwargs)
        return min(amount,self.budget_per_pair(),max_stake)

    def confirm_trade_entry(self,pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs):
        if side!="long":return False
        return super().confirm_trade_entry(pair,order_type,amount,rate,time_in_force,current_time,entry_tag,side,**kwargs)


class NFIResearchBudget(ResearchBudget):
    """Keep upstream signals/exits/DCA, but cap positive adjustments to the budget."""
    hold_support_enabled=False
    def populate_entry_trend(self,dataframe,metadata):
        dataframe=super().populate_entry_trend(dataframe,metadata)
        dataframe["enter_short"]=0
        return dataframe

    def adjust_trade_position(self,trade,current_time,current_rate,current_profit,min_stake,max_stake,
                              current_entry_rate,current_exit_rate,current_entry_profit,current_exit_profit,**kwargs):
        result=super().adjust_trade_position(trade,current_time,current_rate,current_profit,min_stake,max_stake,
                                             current_entry_rate,current_exit_rate,current_entry_profit,current_exit_profit,**kwargs)
        if result is None:return None
        amount,tag=result if isinstance(result,tuple) else (result,None)
        if amount is None or amount<=0:return result
        allowed=max(0,min(max_stake,self.budget_per_pair()-trade.stake_amount))
        amount=min(amount,allowed)
        if amount<=0 or min_stake and amount<min_stake:return None
        return (amount,tag) if tag is not None else amount


class NFI8Long1x(NFIResearchBudget,NostalgiaForInfinityX8):pass
class NFI7Long1x(NFIResearchBudget,NostalgiaForInfinityX7):pass


class ComparisonBase(ResearchBudget,IStrategy):
    INTERFACE_VERSION=3
    timeframe="5m"
    startup_candle_count=240
    process_only_new_candles=True
    position_adjustment_enable=False
    minimal_roi={}
    stoploss=-.10
    use_custom_stoploss=True
    trailing_stop=False
    use_exit_signal=True
    exit_profit_only=False
    ignore_roi_if_entry_signal=False
    max_hours=0
    entry_family="mtf"
    exit_family="fast"
    atr_frame="1h"
    channel=20

    def informative_pairs(self):
        return [(p,tf) for p in self.dp.current_whitelist() for tf in ("15m","1h","4h")]

    def populate_indicators(self,dataframe,metadata):
        for tf in ("15m","1h","4h"):
            frame=self.dp.get_pair_dataframe(pair=metadata["pair"],timeframe=tf).copy()
            for n in (20,50,200):frame[f"ema{n}"]=ta.EMA(frame,timeperiod=n)
            frame["ema20_rising"]=frame.ema20>frame.ema20.shift(3)
            frame["atr"]=ta.ATR(frame,timeperiod=14)
            frame["rsi"]=ta.RSI(frame,timeperiod=14)
            frame["rsi2"]=ta.RSI(frame,timeperiod=2)
            frame["adx"]=ta.ADX(frame,timeperiod=14)
            frame["upper"]=frame.close.rolling(20).mean()+2*frame.close.rolling(20).std(ddof=0)
            frame["lower"]=frame.close.rolling(20).mean()-2*frame.close.rolling(20).std(ddof=0)
            for n in (10,20,55):
                frame[f"high{n}"]=frame.high.rolling(n).max().shift(1)
                frame[f"low{n}"]=frame.low.rolling(n).min().shift(1)
            frame["volume_ratio"]=frame.volume/frame.volume.shift(1).rolling(20).median()
            frame["previous_close"]=frame.close.shift(1)
            dataframe=merge_informative_pair(dataframe,frame,self.timeframe,tf,ffill=True)
        return dataframe

    def populate_entry_trend(self,d,metadata):
        d["enter_long"]=0
        f=self.entry_family
        if f=="mtf":
            trend=(d.close_4h>d.ema20_4h)&(d.ema20_4h>d.ema50_4h)&d.ema20_rising_4h.astype(bool)
            confirm=(d.close_1h>d.ema20_1h)&(d.ema20_1h>d.ema50_1h)&d.ema20_rising_1h.astype(bool)
            breakout=(d.close_15m>d.high20_15m)&(d.volume_ratio_15m>=1.2)
            reclaim=(d.low_15m<=d.ema20_15m)&(d.close_15m>d.ema20_15m)&(d.close_15m>d.previous_close_15m)&(d.volume_ratio_15m>=.8)
            enter=trend&confirm&(breakout|reclaim)
        elif f=="donchian":enter=(d.close_4h>d[f"high{self.channel}_4h"])&(d.close_4h>d.ema50_4h)
        elif f=="ema":enter=(d.ema20_4h>d.ema50_4h)&(d.close_4h>d.ema200_4h)
        elif f=="adx":enter=(d.close_1h>d.high20_1h)&(d.adx_1h>25)&(d.close_1h>d.ema200_1h)
        elif f=="bollinger":enter=(d.close_15m<d.lower_15m)&(d.rsi_15m<30)&(d.close_4h>d.ema200_4h)
        elif f=="rsi2":enter=(d.rsi2_1h<10)&(d.close_1h>d.ema200_1h)
        elif f=="hold":enter=d.volume>0
        else:raise ValueError("Unknown research family")
        # Act once per freshly closed signal bar, not once every repeated 5m row.
        signal_tf="15m" if f in {"mtf","bollinger"} else "1h" if f in {"adx","rsi2"} else "4h"
        changed=d[f"date_{signal_tf}"]!=d[f"date_{signal_tf}"].shift(1)
        d.loc[enter&changed&(d.volume>0),["enter_long","enter_tag"]]=(1,f)
        return d

    def populate_exit_trend(self,d,metadata):
        d["exit_long"]=0
        f=self.exit_family
        if f=="fast":exit=(d.close_1h<d.ema50_1h)|(d.close_15m<d.low10_15m)
        elif f=="hourly":exit=d.close_1h<d.ema50_1h
        elif f=="4h":exit=d.close_4h<d.ema50_4h
        elif f=="channel":exit=d.close_4h<d.low10_4h
        elif f=="mean":exit=d.close_15m>d.ema20_15m
        elif f=="rsi":exit=d.rsi2_1h>70
        elif f=="hold":exit=d.volume<0
        else:raise ValueError("Unknown exit family")
        d.loc[exit,["exit_long","exit_tag"]]=(1,f)
        return d

    def custom_exit(self,pair,trade,current_time,current_rate,current_profit,**kwargs):
        if self.max_hours and current_time-trade.open_date_utc>=timedelta(hours=self.max_hours):return "time_exit_72h"
        return None

    def custom_stoploss(self,pair,trade,current_time,current_rate,current_profit,after_fill,**kwargs):
        if self.entry_family=="hold":return None
        frame,_=self.dp.get_analyzed_dataframe(pair,self.timeframe)
        if frame.empty:return None
        atr=frame.iloc[-1]["atr_"+self.atr_frame]
        if not np.isfinite(atr) or atr<=0:return None
        distance=(2.5 if after_fill else 3)*atr
        stop=current_rate-distance
        return stoploss_from_absolute(stop,current_rate,is_short=False,leverage=1.0)


class MTF72h(ComparisonBase):max_hours=72
class MTFNoTime(ComparisonBase):pass
class MTFHourlyExit(ComparisonBase):exit_family="hourly"
class MTFFourHourExit(ComparisonBase):exit_family="4h";atr_frame="4h";stoploss=-.25
class Donchian20(ComparisonBase):entry_family="donchian";exit_family="channel";atr_frame="4h";stoploss=-.25
class Donchian55(Donchian20):channel=55
class EMA4h(ComparisonBase):entry_family="ema";exit_family="4h";atr_frame="4h";stoploss=-.25
class ADXBreakout1h(ComparisonBase):entry_family="adx";exit_family="hourly"
class BollingerReversion15m(ComparisonBase):entry_family="bollinger";exit_family="mean";stoploss=-.08
class RSI2Pullback1h(ComparisonBase):entry_family="rsi2";exit_family="rsi";stoploss=-.08
class BuyHold1x(ComparisonBase):entry_family="hold";exit_family="hold";stoploss=-.99;use_custom_stoploss=False
