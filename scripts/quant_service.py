#!/usr/bin/env python3
"""Start/stop/status/logs/once for one local dashboard plus continuous paper worker."""
import argparse
import asyncio
import fcntl
import json
import logging
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
from contextlib import asynccontextmanager
from urllib.request import build_opener,ProxyHandler

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from app.quant.service import OUTPUT,atomic_json,read
from app.core.runtime_config import get_runtime_settings

RUN=OUTPUT/"run"
PID=RUN/"service.json"
LOG=ROOT/"logs/quant/service.log"


def owned_pid():
    if not PID.exists():return None
    data=read(PID);pid=data.get("pid")
    if not isinstance(pid,int) or pid<=1:return None
    command=subprocess.run(["ps","-p",str(pid),"-o","command="],capture_output=True,text=True).stdout
    return pid if str(Path(__file__).resolve())+" serve" in command else None


def main():
    settings=get_runtime_settings()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=["start","stop","restart","start-all","stop-all","status","logs","once","serve","test","backtest","compare","research","holding","growth","leverage","cross","overlay","expanded-data","expanded","optimize-stops","forward-start","forward-stop","forward-status","config","doctor","permissions"],nargs="?",default="start")
    parser.add_argument("--port",type=int,default=settings.quant_port)
    parser.add_argument("--interval",type=int,default=settings.quant_observation_seconds)
    parser.add_argument("--refresh",type=int,default=settings.quant_refresh_seconds)
    parser.add_argument("--research-only",action="store_true",help="仅显示研究看板，禁止模拟写入且不启动行情/模拟工作进程")
    args=parser.parse_args()
    if args.research_only and args.command not in {"start","restart","serve"}:
        parser.error("--research-only only applies to start, restart, or serve")
    if not 10<=args.interval<=900 or not args.interval<=args.refresh<=3600 or not 1024<=args.port<=65535:
        parser.error("invalid port or observation/refresh interval")
    if args.command=="start-all" and owned_pid() is not None and read(PID).get("research_only") is True:
        raise SystemExit("模式冲突：当前运行的是研究只读看板，start-all 不会自动恢复模拟。请先显式执行 ./scripts/quant.sh restart，再执行 ./scripts/quant.sh start-all。")
    RUN.mkdir(parents=True,exist_ok=True)
    if args.command=="holding":
        raise SystemExit(subprocess.call([sys.executable,"scripts/compare_holding_pipeline.py"],cwd=ROOT))
    if args.command=="growth":
        raise SystemExit(subprocess.call([str(ROOT/".venv.freqtrade-quant/bin/python"),"scripts/replay_core_growth.py"],cwd=ROOT))
    if args.command=="cross":
        raise SystemExit(subprocess.call([str(ROOT/".venv.freqtrade-quant/bin/python"),"scripts/replay_cross_margin.py"],cwd=ROOT))
    if args.command=="overlay":
        raise SystemExit(subprocess.call([str(ROOT/".venv.freqtrade-quant/bin/python"),"scripts/replay_core_overlay.py"],cwd=ROOT))
    if args.command in {"expanded-data","expanded"}:
        script="prepare_expanded_core_data.py" if args.command=="expanded-data" else "replay_expanded_core.py"
        raise SystemExit(subprocess.call([str(ROOT/".venv.freqtrade-quant/bin/python"),"scripts/"+script],cwd=ROOT))
    if args.command=="leverage":
        subprocess.run([sys.executable,"scripts/run_leverage_comparison.py"],cwd=ROOT,check=True)
        raise SystemExit(subprocess.call([str(ROOT/".venv.freqtrade-quant/bin/python"),"scripts/analyze_leverage_survival.py"],cwd=ROOT))
    if args.command in {"start-all","stop-all"}:
        commands=["start","forward-start"] if args.command=="start-all" else ["forward-stop","stop"]
        for command in commands:
            subprocess.run([sys.executable,str(Path(__file__).resolve()),command,"--port",str(args.port),
                "--interval",str(args.interval),"--refresh",str(args.refresh)],cwd=ROOT,check=True)
        return
    if args.command.startswith("forward-"):
        raise SystemExit(subprocess.call([sys.executable,"scripts/forward_stop_study.py",args.command.removeprefix("forward-")],cwd=ROOT))
    if args.command=="optimize-stops":
        raise SystemExit(subprocess.call([sys.executable,"scripts/optimize_stop_pipeline.py"],cwd=ROOT))
    if args.command=="research":
        research_python=ROOT/".venv.freqtrade-quant/bin/python"
        if not research_python.exists():
            raise SystemExit("研究环境缺失：uv venv --python 3.11 .venv.freqtrade-quant，然后 uv pip sync --python .venv.freqtrade-quant/bin/python freqtrade/requirements.quant-v3.lock.txt")
        if not (ROOT/"reports/quant_v5/freqtrade_data/manifest.json").exists():
            raise SystemExit("冻结研究数据缺失；按 docs/quant_research.md 的数据准备命令生成后重试")
        if not (ROOT/"reports/quant_v5/selection_freeze.json").exists():
            raise SystemExit("筛选记录缺失；请先按实验协议完成筛选，不能用完整区间结果倒选留出段")
        commands=[
            [sys.executable,"scripts/run_strategy_comparison.py","--window","all"],
            [sys.executable,"scripts/run_strategy_comparison.py","--window","full","--double-cost"],
            [sys.executable,"scripts/run_strategy_comparison.py","--window","holdout","--double-cost","--strategies","Donchian55","Donchian20","EMA4h","MTFHourlyExit","NFI8Long1x"],
            [str(research_python),"scripts/analyze_strategy_comparison.py"],
            [sys.executable,"scripts/report_strategy_comparison.py"],
        ]
        for command in commands:
            subprocess.run(command,cwd=ROOT,check=True)
        print("三币策略回测与盯市报告已更新；查看 /api/quant/dashboard#research；实盘关闭")
        return
    if args.command=="permissions":
        from app.quant.permissions import check_permissions
        result=check_permissions(settings)
        atomic_json(settings.quant_output_dir/"permissions.json",result)
        print(json.dumps(result,ensure_ascii=False,indent=2));return
    if args.command=="doctor":
        from app.quant.diagnostics import diagnose
        print(json.dumps(diagnose(),ensure_ascii=False,indent=2));return
    if args.command=="config":
        print(json.dumps(settings.public_status(),ensure_ascii=False,indent=2));return
    if args.command=="serve":
        import uvicorn
        from app.application import create_app
        with (RUN/"service.lock").open("a") as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise SystemExit("模拟服务已在运行") from None
            settings.quant_observation_seconds=args.interval;settings.quant_refresh_seconds=args.refresh
            settings.app_profile="quant"
            app=create_app(research_only=args.research_only)
            atomic_json(PID,{"pid":os.getpid(),"port":args.port,"interval":args.interval,"refresh":args.refresh,"research_only":args.research_only})
            logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s %(message)s")
            try:uvicorn.run(app,host=settings.quant_host,port=args.port,access_log=False)
            finally:
                if PID.exists() and read(PID).get("pid")==os.getpid():PID.unlink()
        return
    if args.command=="logs":
        LOG.parent.mkdir(parents=True,exist_ok=True);LOG.touch(exist_ok=True)
        os.execvp("tail",["tail","-n","80","-f",str(LOG)])
    if args.command=="status":
        pid=owned_pid();metadata=read(PID) if PID.exists() else {}
        research_only=pid is not None and metadata.get("research_only") is True
        if research_only:
            runtime={"state":"research_only","automatic":False,"research_only":True,
                     "configuration":{**settings.public_status(),"worker_enabled":False}}
        else:
            from app.quant.runtime import runtime_status
            runtime=runtime_status()
        print(json.dumps({"process_running":pid is not None,"research_only":research_only,
            "mode":"research_only" if research_only else "paper" if pid is not None else "stopped",
            "dashboard":f"http://127.0.0.1:{metadata.get('port',args.port)}/api/quant/dashboard",
            "runtime":runtime},ensure_ascii=False,indent=2));return
    if args.command=="once":
        from app.quant.runtime import cycle
        print(json.dumps(cycle(),ensure_ascii=False,indent=2));return
    if args.command in {"test","backtest","compare"}:
        command=([sys.executable,"scripts/compare_quant_policy.py"] if args.command=="compare" else
                 [sys.executable,"scripts/backtest_quant_mtf.py"] if args.command=="backtest" else
                 [sys.executable,"-W","error::ResourceWarning","-m","unittest","tests.test_quant_futures","tests.test_quant_service","tests.test_quant_replay","tests.test_quant_runtime","tests.test_quant_config","tests.test_quant_mtf","tests.test_quant_policy","-v"])
        raise SystemExit(subprocess.call(command,cwd=ROOT))
    if args.command in {"stop","restart"}:
        pid=owned_pid()
        if pid:
            os.kill(pid,signal.SIGTERM)
            for _ in range(90):
                if not owned_pid():break
                time.sleep(.5)
            if owned_pid():raise SystemExit("服务正在等待本轮网络请求结束，请稍后查看 status；未强制中断账户写入")
            print("模拟服务已停止，账户与成交历史保留")
        else:print("没有受此命令管理的运行服务")
        if args.command=="stop":return
    if owned_pid():
        print("服务已运行；使用 ./scripts/quant.sh status 查看状态。切换研究只读/模拟模式请显式使用 restart 并指定所需参数。")
        return
    with socket.socket() as sock:
        if sock.connect_ex(("127.0.0.1",args.port))==0:raise SystemExit(f"端口 {args.port} 已被其他服务使用；请停止旧看板或使用 --port 指定端口")
    LOG.parent.mkdir(parents=True,exist_ok=True)
    with LOG.open("a") as log:
        process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),"serve","--port",str(args.port),"--interval",str(args.interval),"--refresh",str(args.refresh)]+(["--research-only"] if args.research_only else []),cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
    opener=build_opener(ProxyHandler({}))
    for _ in range(40):
        if process.poll() is not None:raise SystemExit(f"服务启动失败，请查看 {LOG}")
        try:
            with opener.open(f"http://127.0.0.1:{args.port}/api/quant/runtime",timeout=.5) as response:
                if response.status==200:
                    mode="研究只读看板（不运行采集/模拟，不写入账户）" if args.research_only else f"每 {args.interval} 秒模拟观察，每 {args.refresh} 秒全池刷新"
                    print(f"已启动：{mode}\nhttp://127.0.0.1:{args.port}/api/quant/dashboard\n日志：{LOG}");return
        except (OSError,ValueError):time.sleep(.25)
    raise SystemExit(f"服务已派生但就绪检查超时，请查看 {LOG}")


if __name__=="__main__":main()
