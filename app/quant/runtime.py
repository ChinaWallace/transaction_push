"""Single-writer, public-data-only paper service; never places exchange orders."""
import asyncio
import fcntl
import logging
import os
import time
from contextlib import contextmanager

from app.advisory.engine import iso
from .service import DATA, OUTPUT, FuturesLedger, atomic_json, read, scan
from app.core.runtime_config import get_runtime_settings

LOG=logging.getLogger("quant.paper")


@contextmanager
def writer_lock(output=OUTPUT):
    output.mkdir(parents=True,exist_ok=True)
    with (output/"cycle.lock").open("a") as handle:
        try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:raise RuntimeError("Another paper cycle is running; no duplicate execution") from None
        try:yield
        finally:fcntl.flock(handle,fcntl.LOCK_UN)


def cycle(full=True,directory=DATA,output=OUTPUT,capital=None):
    capital=capital or get_runtime_settings().quant_initial_capital
    from .market import collect,collect_quotes,collect_funding
    with writer_lock(output):
        ledger=FuturesLedger(output/"paper.sqlite3",capital)
        collection=collect(directory) if full else collect_quotes(directory)
        report=scan(directory,output,capital)
        now=int(time.time()*1000)
        try:funding=collect_funding(ledger.status(),now)
        except Exception as exc:funding={};collection["funding_error"]=str(exc)
        paper=ledger.step(report,now,funding)
        atomic_json(output/"paper_latest.json",paper)
        return {"collection":collection,"paper":paper}


def runtime_status(output=None):
    path=(output or OUTPUT)/"runtime.json"
    status=read(path) if path.exists() else {"state":"stopped","automatic":False}
    age=time.time()-status.get("heartbeat_unix",0)
    if status.get("state") not in {"stopped","starting"} and time.time()>status.get("next_cycle_unix",status.get("heartbeat_unix",0))+max(180,status.get("interval_seconds",60)*3):
        status["state"]="unresponsive";status["automatic"]=False
    status["configuration"]=get_runtime_settings().public_status()
    return status


class PaperWorker:
    def __init__(self,interval=60,refresh=300,background_collection=False,directory=None,output=None,capital=None):
        if not 10<=interval<=3600 or refresh<interval:raise ValueError("Invalid observation/refresh interval")
        self.interval=interval;self.refresh=refresh;self.stop_event=asyncio.Event()
        self.background_collection=background_collection
        self.directory=directory;self.output=output;self.capital=capital
        self.state={"state":"starting","automatic":True,"pid":os.getpid(),"interval_seconds":interval,
                    "full_refresh_seconds":refresh,"started_at":iso(int(time.time()*1000)),"cycles_completed":0,
                    "consecutive_errors":0,"live":False}

    def save(self,**fields):
        self.state.update(fields,heartbeat_unix=time.time())
        atomic_json((self.output or OUTPUT)/"runtime.json",self.state)

    async def collect_loop(self):
        from .market import collect
        while not self.stop_event.is_set():
            self.save(collector_state="collecting")
            try:
                result=await asyncio.to_thread(collect,self.directory or DATA,self.output or OUTPUT,self.stop_event)
                self.save(collector_state="running",last_collection=result,collector_error=None,
                          last_collection_at=iso(int(time.time()*1000)))
            except Exception as exc:
                self.save(collector_state="error",collector_error=str(exc))
            # Schedule at the next 15m boundary, with a small close-publication grace.
            boundary=(int(time.time())//900+1)*900+3
            delay=max(1,min(self.refresh,boundary-time.time()))
            try:await asyncio.wait_for(self.stop_event.wait(),timeout=delay)
            except TimeoutError:pass

    async def run(self):
        collector=asyncio.create_task(self.collect_loop()) if self.background_collection else None
        next_full=0
        try:
            while not self.stop_event.is_set():
                started=time.monotonic();full=not self.background_collection and started>=next_full
                self.save(state="collecting",cycle_started_at=iso(int(time.time()*1000)))
                try:
                    result=(await asyncio.to_thread(cycle,full,self.directory or DATA,self.output or OUTPUT,self.capital)
                            if self.directory is not None or self.output is not None else await asyncio.to_thread(cycle,full))
                    if full:next_full=time.monotonic()+self.refresh
                    paper=result["paper"]
                    healthy=paper["valuation_complete"] and paper["status"]!="incomplete_research"
                    self.save(state="running" if healthy else "degraded",last_success_at=paper["at"],
                              last_cycle_status=paper["status"],cycles_completed=self.state["cycles_completed"]+1,
                              consecutive_errors=0,last_error=None,collection=result["collection"],
                              last_cycle_seconds=round(time.monotonic()-started,2))
                    LOG.info("paper cycle status=%s positions=%s equity=%.2f full=%s",paper["status"],len(paper["positions"]),paper["equity"],full)
                except Exception as exc:
                    self.save(state="error",last_error=str(exc),consecutive_errors=self.state["consecutive_errors"]+1)
                    LOG.exception("Paper cycle failed; no substitute prices or fabricated fills")
                delay=max(1,self.interval-(time.monotonic()-started))
                if self.state["consecutive_errors"]:
                    delay=max(delay,min(self.refresh,self.interval*2**min(3,self.state["consecutive_errors"]-1)))
                self.save(next_cycle_at=iso(int((time.time()+delay)*1000)),next_cycle_unix=time.time()+delay)
                try:await asyncio.wait_for(self.stop_event.wait(),timeout=delay)
                except TimeoutError:pass
        finally:
            self.stop_event.set()
            if collector:await collector
            self.save(state="stopped",automatic=False)
