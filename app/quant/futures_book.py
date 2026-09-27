"""Isolated-margin long-only paper account; funding is a first-class cash flow."""

from math import isfinite

from app.advisory.engine import DAY, iso


class FuturesBook:
    def __init__(self,cash=10000,fee_bps=5,slippage_bps=5):
        if not isfinite(cash) or cash<=0:raise ValueError("Invalid starting equity")
        if not all(isfinite(x) and 0<=x<=100 for x in (fee_bps,slippage_bps)):raise ValueError("Invalid trading cost")
        self.initial_cash=self.wallet=float(cash)
        self.fee=fee_bps/10000;self.slip=slippage_bps/10000
        self.positions={};self.marks={};self.events=[];self.curve=[];self.processed_funding=set()
        self.peak=self.risk_peak=cash;self.pause_until=0;self.last_plan=None
        self.cooldown={};self.closed=[];self.last_stop_signal={}
        self.high_watermarks={};self.last_time=0
        self.funding_cursor={};self.funding_debts=[]
        self.active_plan={};self.entry_attempted=set();self.cancelled_entries={};self.last_decisions=[]

    def equity(self):
        return self.wallet+sum(p["quantity"]*(self.marks[s]-p["entry"]) for s,p in self.positions.items())

    def margin(self):
        return sum(p["margin"] for p in self.positions.values())

    def gross(self):
        return sum(p["quantity"]*self.marks[s] for s,p in self.positions.items())

    def close(self,s,quantity,raw,now,reason):
        p=self.positions[s];quantity=min(quantity,p["quantity"])
        fill=raw*(1-self.slip);fee=quantity*fill*self.fee
        pnl=quantity*(fill-p["entry"])-fee
        fraction=quantity/p["quantity"]
        p["margin"]*=1-fraction;p["quantity"]-=quantity;p["pnl"]+=pnl
        self.wallet+=pnl
        self.events.append({"time":iso(now),"symbol":s,"side":"sell","quantity":quantity,"price":fill,
                            "fee":fee,"pnl":pnl,"reason":reason,"entry_price":p["entry"],
                            "opened_at":p["opened_at"],"stop_price":p["stop"],"strategy":p.get("strategy","contracts-v3.1")})
        if p["quantity"]<1e-10:
            self.closed.append({"symbol":s,"entry_time":iso(p["opened_at"]),"exit_time":iso(now),"pnl":p["pnl"],"reason":reason})
            del self.positions[s]
            if reason in {"stop","gap_stop","liquidation"}:self.cooldown[s]=now+p.get("cooldown_ms",3*DAY)

    def add(self,target,bid,ask,now):
        s=target["symbol"];lev=target["leverage"]
        policy=self.active_plan.get("policy",{})
        core=target.get("holding_policy")=="core"
        if core and (lev!=1 or s not in policy.get("preferred_symbols",[])):
            raise ValueError("Core positions require an authorized preferred symbol and 1x")
        cap=policy.get("core_single_weight",.25) if core else policy.get("satellite_single_weight",.35)
        margin_limit=self.active_plan.get("margin_limit",.65)
        if not 1<=lev<=3:raise ValueError("Leverage exceeds authorization")
        if not isfinite(target["weight"]) or not 0<=target["weight"]<=(.7 if core else .35):raise ValueError("Invalid target weight")
        stop=target["stop_price"]
        no_stop=core and target.get("stop_mode")=="none"
        if not all(isfinite(x) and x>0 for x in (bid,ask)) or not isfinite(stop) or not stop<bid<=ask:
            return
        if stop<=0 and not (no_stop and stop==0):return
        if not no_stop and (ask-stop)/ask>.8/lev:return
        fill=ask*(1+self.slip);eq=self.equity()
        p=self.positions.get(s)
        if p and p["leverage"]!=lev:return
        existing=p["quantity"]*bid if p else 0
        desired=max(0,target["weight"]*eq-existing)
        # Margin reserved, but wallet is not reduced by buying notional as in spot.
        # Fees and spread loss are deducted from the equity used by these caps.
        equity_drag=fill-bid+fill*self.fee
        remaining_margin=(margin_limit*eq-self.margin())/(fill/lev+margin_limit*equity_drag)
        gross_cap=(1.8*eq-self.gross())/(bid+1.8*equity_drag)
        single_cap=(cap*eq-existing)/(bid+cap*equity_drag)
        qty=max(0,min(desired/bid,remaining_margin,gross_cap,single_cap))
        if core:
            core_cap=policy["core_total_weight"]
            core_gross=sum(v["quantity"]*self.marks[k] for k,v in self.positions.items() if v.get("holding_policy")=="core")
            qty=max(0,min(qty,(core_cap*eq-core_gross)/(bid+core_cap*equity_drag)))
        if self.active_plan.get("execution_policy") in {"daily_rebalance_intraday_entry","multiframe_rotation"}:
            if not p and len(self.positions)>=self.active_plan.get("max_positions",10):return
            # Recheck stop risk at the actual fill, including fees and spread loss.
            reference=self.marks[s]
            conservative_drag=max(0,fill-reference)+fill*self.fee
            current_risk=sum(v["quantity"]*max(0,self.marks[k]-v["stop"]) for k,v in self.positions.items() if v.get("holding_policy")!="core")
            risk_quantity=(.25*eq-current_risk)/(max(0,max(reference,fill)-stop)+.25*conservative_drag)
            if core:risk_quantity=float("inf")
            marked_existing=p["quantity"]*reference if p else 0
            if self.active_plan.get("strategy_schema")==4 and not core:
                limit=self.active_plan.get("position_risk_budget",.025)
                held_risk=(p["quantity"]*max(0,reference-p["stop"])) if p else 0
                single_risk=(limit*eq-held_risk)/(max(0,max(reference,fill)-stop)+limit*conservative_drag)
                qty=max(0,min(qty,single_risk))
            qty=max(0,min(qty,risk_quantity,(1.8*eq-self.gross())/(reference+1.8*conservative_drag),
                          (cap*eq-marked_existing)/(reference+cap*conservative_drag),
                          (margin_limit*eq-self.margin())/(fill/lev+margin_limit*conservative_drag)))
        if qty*bid<10:return
        fee=qty*fill*self.fee;self.wallet-=fee
        if p:
            p["entry"]=(p["entry"]*p["quantity"]+qty*fill)/(p["quantity"]+qty)
            p["quantity"]+=qty;p["margin"]+=qty*fill/lev;p["pnl"]-=fee;p["stop"]=max(p["stop"],stop)
        else:
            self.positions[s]={"quantity":qty,"entry":fill,"leverage":lev,"margin":qty*fill/lev,
                               "stop":stop,"opened_at":now,"pnl":-fee,"funding":0}
            self.high_watermarks[s]=fill
        self.positions[s]["strategy"]=self.active_plan.get("version","contracts-v3.1")
        self.positions[s]["holding_policy"]="core" if core else "satellite"
        self.positions[s]["stop_mode"]=target.get("stop_mode","atr")
        self.positions[s]["drawdown_exempt"]=core and self.active_plan.get("core_drawdown_exempt",False)
        self.positions[s]["core_stop_distance"]=policy.get("core_stop_distance") if core else None
        if core:
            self.positions[s]["stop"]=0 if no_stop else self.positions[s]["entry"]*(1-policy["core_stop_distance"])
            self.positions[s].pop("trailing_atr",None)
        self.positions[s]["cooldown_ms"]=self.active_plan.get("cooldown_ms",3*DAY)
        self.positions[s]["trailing_multiplier"]=self.active_plan.get("trailing_atr_multiplier",5)
        if not core and self.active_plan.get("execution_policy") in {"daily_rebalance_intraday_entry","multiframe_rotation"}:
            self.positions[s]["trailing_atr"]=target.get("atr",float("inf"))
        self.events.append({"time":iso(now),"symbol":s,"side":"buy","quantity":qty,"price":fill,"fee":fee,
                            "leverage":lev,"reason":"target_rebalance","stop_price":stop,
                            "score":target.get("score"),"target_weight":target["weight"],
                            "strategy":self.active_plan.get("version","contracts-v3.1"),
                            "holding_policy":"core" if core else "satellite","stop_mode":target.get("stop_mode","atr"),
                            "policy_revision":self.active_plan.get("policy_revision"),
                            "signal_evidence":self.active_plan.get("signal_evidence",{}).get(s)})

    def funding(self,s,now,rate,mark):
        key=f"{s}:{now}"
        if key in self.processed_funding:return
        if not all(isfinite(x) for x in (rate,mark)) or mark<=0:raise ValueError("Invalid funding event")
        self.processed_funding.add(key)
        p=self.positions.get(s)
        if not p:return
        payment=p["quantity"]*mark*rate
        self.wallet-=payment;p["pnl"]-=payment;p["funding"]+=payment
        self.events.append({"time":iso(now),"symbol":s,"side":"funding","rate":rate,"mark":mark,"payment":payment})

    def observe(self,now,quotes):
        if now<self.last_time:raise ValueError("Cannot replay older observations into a forward account")
        self.last_time=now
        for s,q in quotes.items():
            if not all(isfinite(q[k]) and q[k]>0 for k in ("bid","ask","mark")) or q["bid"]>q["ask"]:
                raise ValueError("Invalid quote")
            self.marks[s]=q["mark"]
            if s in self.positions:self.high_watermarks[s]=max(self.high_watermarks.get(s,0),q["mark"])
        for s,p in list(self.positions.items()):
            if s in quotes and "trailing_atr" in p:
                p["stop"]=max(p["stop"],self.high_watermarks.get(s,0)-p.get("trailing_multiplier",5)*p["trailing_atr"])
            if s in quotes and self.marks[s]<=p["stop"]:
                self.close(s,p["quantity"],quotes[s]["bid"],now,"gap_stop")
        eq=self.equity();self.peak=max(self.peak,eq)
        if self.pause_until and now>=self.pause_until:self.risk_peak=eq;self.pause_until=0
        self.risk_peak=max(self.risk_peak,eq)
        if eq<self.risk_peak*.55 and not self.pause_until:self.pause_until=now+28*DAY
        if now<self.pause_until:
            for s,p in list(self.positions.items()):
                if s in quotes and not p.get("drawdown_exempt",False):self.close(s,p["quantity"],quotes[s]["bid"],now,"portfolio_drawdown_exit")

    def apply(self,plan,quotes,now,signal_id,complete=True):
        mtf=plan.get("execution_policy")=="multiframe_rotation"
        if plan.get("policy"):
            self._sync_holding_policy(plan,quotes,now,allow_promotion=complete)
        if mtf:
            for s,p in self.positions.items():
                update=plan.get("protective_updates",{}).get(s)
                if update and p.get("strategy")==plan.get("version") and p.get("holding_policy")!="core":
                    p["trailing_atr"]=update["atr"]
                    p["trailing_multiplier"]=3
                    p["stop"]=max(p["stop"],update.get("stop_price",p["stop"]))
        self.observe(now,quotes)
        self.last_decisions=[]
        intraday=plan.get("execution_policy") in {"daily_rebalance_intraday_entry","multiframe_rotation"}
        # Faster strategy exits are protective: funding gaps must not prevent exits.
        if mtf:
            for s,p in list(self.positions.items()):
                if s not in quotes or p.get("strategy")!=plan.get("version") or p.get("holding_policy")=="core":continue
                reason=plan.get("exit_signals",{}).get(s)
                max_hold=plan.get("max_hold_ms",72*3_600_000)
                if max_hold and now-p["opened_at"]>=max_hold:
                    reason="time_exit_72h" if max_hold==72*3_600_000 else "holding_time_exit"
                if reason:
                    self.close(s,p["quantity"],quotes[s]["bid"],now,reason)
                    self.cooldown[s]=now+plan.get("cooldown_ms",3_600_000)
                    self.cancelled_entries[s]=reason
        if set(self.positions)-set(quotes):return "missing_position_quote"
        if not complete:return "incomplete_research"
        if plan.get("policy"):self._enforce_policy_caps(plan,quotes,now)
        if not intraday and {t["symbol"] for t in plan["targets"]}-set(quotes):return "missing_target_quote"
        if self.last_plan==signal_id:
            if intraday:
                if mtf:self.active_plan=plan
                return self._pending_entries(plan,quotes,now)
            return "duplicate_signal"
        if intraday:
            self.active_plan=plan;self.entry_attempted=set();self.cancelled_entries={}
        if mtf:
            # Explicitly close legacy strategy lots before adopting different ATR units.
            # Retain wallet, ledger, costs and events; never relabel old fills as v4.
            for s,p in list(self.positions.items()):
                if p.get("strategy")!=plan.get("version"):
                    self.close(s,p["quantity"],quotes[s]["bid"],now,"strategy_migration_exit")
        targets={t["symbol"]:t for t in plan["targets"]}
        if now<self.pause_until:targets={}
        eq=self.equity()
        for s,p in list(self.positions.items()):
            if p.get("holding_policy")=="core" and s in plan.get("policy",{}).get("preferred_symbols",[]):continue
            if plan.get("retain_until_exit") and now>=self.pause_until:continue
            t=targets.get(s)
            if t:
                if intraday:p["trailing_atr"]=t.get("atr",float("inf"))
                trail=self.high_watermarks.get(s,0)-plan.get("trailing_atr_multiplier",5)*t.get("atr",float("inf"))
                p["stop"]=max(p["stop"],t["stop_price"],trail)
                if self.marks[s]<=p["stop"]:
                    self.close(s,p["quantity"],quotes[s]["bid"],now,"gap_stop");continue
            difference=p["quantity"]*self.marks[s]-(t["weight"]*eq if t else 0)
            if difference>.03*eq or t is None:
                self.close(s,difference/self.marks[s],quotes[s]["bid"],now,"trend_or_rank_exit" if intraday and t is None else "rebalance_reduce")
        if intraday:
            self.last_plan=signal_id
            self._pending_entries(plan,quotes,now)
            return "applied"
        for s,t in targets.items():
            if s not in quotes or now<self.cooldown.get(s,0):continue
            if not t["entry_zone"][0]<=quotes[s]["ask"]<=t["entry_zone"][1]:continue
            existing=self.positions.get(s,{"quantity":0})["quantity"]*self.marks[s]
            if t["weight"]*self.equity()-existing>.03*self.equity():self.add(t,quotes[s]["bid"],quotes[s]["ask"],now)
        self.last_plan=signal_id
        return "applied"

    def _pending_entries(self,plan,quotes,now):
        filled=False;self.last_decisions=[]
        for t in self.active_plan.get("targets",[]):
            s=t["symbol"];q=quotes.get(s);reason=None
            if now>=self.active_plan.get("signal_expires_at",float("inf")):
                self.cancelled_entries[s]="signal_expired"
            if s not in self.entry_attempted and q and q["mark"]<=t["stop_price"]:
                self.cancelled_entries[s]="plan_stop_breached"
            if s not in self.entry_attempted and s in plan.get("invalidated_symbols",[]):
                self.cancelled_entries[s]="entry_filter_invalidated"
            if s in self.entry_attempted:reason="already_filled_cycle" if plan.get("strategy_schema")==4 else "already_filled_today"
            elif s in self.positions and self.positions[s].get("holding_policy")=="core":reason="core_hold_no_auto_add"
            elif s in self.cancelled_entries:reason=self.cancelled_entries[s]
            elif now<self.pause_until and t.get("holding_policy")!="core":reason="drawdown_pause"
            elif now<self.cooldown.get(s,0):reason="stop_cooldown"
            elif not q:reason="missing_quote"
            elif s not in plan.get("entry_allowed_symbols",[x["symbol"] for x in plan["targets"]]):reason="entry_filter_failed"
            elif not t["entry_zone"][0]<=q["ask"]<=t["entry_zone"][1]:reason="outside_entry_zone"
            elif q["bid"]<=t["stop_price"]:reason="below_stop"
            else:
                existing=self.positions.get(s,{"quantity":0})["quantity"]*self.marks[s]
                if s in self.positions and t["weight"]*self.equity()-existing<=.03*self.equity():
                    reason="at_target";self.entry_attempted.add(s)
                else:
                    before=len(self.events);self.add(t,q["bid"],q["ask"],now)
                    if len(self.events)>before:
                        reason="filled";filled=True;self.entry_attempted.add(s)
                    else:reason="risk_budget_or_min_notional"
            self.last_decisions.append({"symbol":s,"status":reason,"time":iso(now),
                                        "ask":q["ask"] if q else None,"entry_zone":t["entry_zone"]})
        # Later fills pay fees from the same equity used by earlier position caps.
        # Reconcile the whole basket before publishing this atomic paper cycle.
        if plan.get("policy"):self._enforce_policy_caps(plan,quotes,now)
        return "pending_entry_filled" if filled else "monitoring"

    def _sync_holding_policy(self,plan,quotes,now,allow_promotion=True):
        policy=plan["policy"]
        for s,p in list(self.positions.items()):
            if s not in quotes:continue
            preferred=s in policy["preferred_symbols"]
            if preferred and not allow_promotion:continue
            if preferred and p["leverage"]!=1:
                self.close(s,p["quantity"],quotes[s]["bid"],now,"core_leverage_migration_exit")
                continue
            core=s in policy["preferred_symbols"] and p["leverage"]==1
            mode=policy["core_stop_mode"] if core else "atr"
            holding="core" if core else "satellite"
            old=(p.get("holding_policy","satellite"),p.get("stop_mode","atr"),p.get("core_stop_distance"))
            new=(holding,mode,policy["core_stop_distance"] if core else None)
            p["drawdown_exempt"]=core and plan.get("core_drawdown_exempt",False)
            if old==new:continue
            p.update(holding_policy=holding,stop_mode=mode,core_stop_distance=new[2])
            if core:
                p["stop"]=0 if mode=="none" else p["entry"]*(1-policy["core_stop_distance"])
                p.pop("trailing_atr",None)
            elif old[0]=="core":p["stop"]=max(p["stop"],quotes[s]["mark"]*.9)
            self.events.append({"time":iso(now),"symbol":s,"side":"policy","reason":"holding_policy_change",
                                "from":old[0],"to":holding,"stop_mode":mode,"stop_price":p["stop"]})

    def _enforce_policy_caps(self,plan,quotes,now):
        policy=plan["policy"]
        core_gross=sum(p["quantity"]*self.marks[s] for s,p in self.positions.items() if p.get("holding_policy")=="core")
        core_scale=min(1,policy["core_total_weight"]*self.equity()/core_gross) if core_gross else 1
        for s,p in list(self.positions.items()):
            if s not in quotes:continue
            core=p.get("holding_policy")=="core"
            # Entry limits still apply in add(); appreciation is not a sell signal.
            if core and policy.get("core_allow_weight_drift",False):continue
            cap=policy["core_single_weight"] if core else policy["satellite_single_weight"]
            mark=self.marks[s];notional=p["quantity"]*mark
            allowed=min(cap*self.equity(),notional*core_scale if core else notional)
            if notional-allowed>1:
                # Leave a small cost buffer so the fill fee does not push it back over the cap.
                quantity=min(p["quantity"],(notional-allowed+1)/mark)
                self.close(s,quantity,quotes[s]["bid"],now,"policy_weight_cap")

    def record(self,now):
        self.curve.append({"time":iso(now),"equity":self.equity(),"wallet":self.wallet,
                           "gross_pct":self.gross()/self.equity()*100 if self.equity()>0 else 0,
                           "margin":self.margin(),"positions":len(self.positions)})

    def dump(self):
        return {k:(sorted(v) if isinstance(v,set) else v) for k,v in self.__dict__.items()}

    @classmethod
    def restore(cls,value):
        book=cls(value["initial_cash"]);book.__dict__.update(value);book.processed_funding=set(value["processed_funding"])
        book.entry_attempted=set(value.get("entry_attempted",[]))
        return book
