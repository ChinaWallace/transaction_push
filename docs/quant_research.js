/* Isolated, read-only research panel. Values from artifacts use textContent. */
(()=>{
const q=id=>document.getElementById(id),num=(v,n=2)=>Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:n,minimumFractionDigits:n}):'—';
const descriptions={
  MTF72h:'4h趋势 + 1h确认 + 15m触发；15m/1h退出，1h ATR追踪，最长72h。研究复刻，不含全池排名。',
  MTFNoTime:'与MTF72h完全相同，只取消72小时期限。',
  MTFHourlyExit:'保留多周期入场，仅1h跌破EMA50退出，另有1h ATR止损；无持仓期限。',
  MTFFourHourExit:'保留多周期入场，4h跌破EMA50退出，4h ATR止损、25%基础保护；无期限。',
  Donchian20:'4h收盘突破此前20根最高价且高于EMA50入场；跌破此前10根低点或4h ATR追踪退出。',
  Donchian55:'4h收盘突破此前55根最高价且高于EMA50入场；跌破此前10根低点或4h ATR追踪退出；无72h期限。',
  EMA4h:'4h EMA20高于EMA50且收盘高于EMA200入场；收盘失守EMA50或4h ATR追踪退出。',
  ADXBreakout1h:'1h突破20根高点、ADX>25、收盘高于EMA200入场；失守EMA50或ATR追踪退出。',
  BollingerReversion15m:'4h大趋势向上时，15m跌破布林下轨且RSI<30入场；回到EMA20或止损退出。',
  RSI2Pullback1h:'1h高于EMA200时，RSI2<10入场；RSI2>70或止损退出。',
  BuyHold1x:'期初买入三币各约23.33%，持有至回测结束；30%现金。没有动态70%再平衡，价格上涨后名义占比可超过70%。',
  NFI8Long1x:'NFI X8原生5m、多周期保护和自定义退出；约束仅做多1x、单币预算。保留上游99%基础止损和加减仓逻辑。',
  NFI7Long1x:'NFI X7原生5m、多周期保护和自定义退出；约束仅做多1x、单币预算。保留上游99%基础止损和加减仓逻辑。'
};
const reasons={fast:'15m结构 / 1h趋势退出',hourly:'1h失守EMA50','4h':'4h失守EMA50',channel:'4h跌破10根低点',mean:'回归15m均线',rsi:'RSI2回升',mtf:'多周期确认入场',donchian:'4h通道突破入场',ema:'4h趋势入场',adx:'1h强势突破',bollinger:'15m超卖回归',rsi2:'1h超卖回踩',hold:'期初持有基准',trailing_stop_loss:'ATR追踪止损',stop_loss:'保护止损',force_exit:'回测终点结算（非策略信号）',time_exit_72h:'72小时期限'};
let result,detail,offset=0,revision=0;
function cells(id,values){const tr=document.createElement('tr'),body=q(id),heads=body.closest('table').querySelectorAll('th');values.forEach((v,i)=>{const td=document.createElement('td');td.textContent=v;td.dataset.label=heads[i]?.textContent??'';tr.append(td)});body.append(tr);return tr}
async function get(url){const r=await fetch('/api/quant/'+url);if(!r.ok)throw Error('回测结果读取失败：'+r.status);return r.json()}
function rows(){return result.rows.filter(r=>r.window===q('research-window').value)}
function list(){const available=rows(),previous=q('research-strategy').value;q('research-rows').replaceChildren();q('research-strategy').replaceChildren();for(const r of available){const m=r.mark_metrics;const tr=cells('research-rows',[r.strategy,num(m.return_pct)+'%',num(m.sampled_mark_drawdown_pct)+'%',r.total_trades,num(m.average_marked_exposure_pct)+'%',num(m.holding_max_hours,1)+'小时',m.reconciled?'通过':'存在差异']);tr.tabIndex=0;tr.style.cursor='pointer';const choose=()=>{q('research-strategy').value=r.strategy;loadDetail()};tr.addEventListener('click',choose);tr.addEventListener('keydown',e=>{if(e.key==='Enter')choose()});const o=document.createElement('option');o.value=r.strategy;o.textContent=r.strategy;q('research-strategy').append(o)}q('research-strategy').value=available.some(r=>r.strategy===previous)?previous:available.some(r=>r.strategy===result.selection.primary)?result.selection.primary:available[0]?.strategy;loadDetail()}
function curve(points,target='research-curve'){const svg=q(target);svg.replaceChildren();if(!points.length)return;svg.setAttribute('viewBox','0 0 1000 180');const lo=Math.min(10000,...points.map(p=>p.equity)),hi=Math.max(10000,...points.map(p=>p.equity)),span=Math.max(points.at(-1).timestamp-points[0].timestamp,1),range=Math.max(hi-lo,1);const path=document.createElementNS('http://www.w3.org/2000/svg','path');path.setAttribute('d',points.map((p,i)=>(i?'L':'M')+(12+976*(p.timestamp-points[0].timestamp)/span)+' '+(155-130*(p.equity-lo)/range)).join(' '));path.setAttribute('stroke','#73dac0');path.setAttribute('stroke-width','2');path.setAttribute('fill','none');svg.append(path);const label=document.createElementNS('http://www.w3.org/2000/svg','text');label.setAttribute('x','12');label.setAttribute('y','178');label.setAttribute('fill','#9fadc1');label.textContent='盯市权益 USDT · '+num(lo)+' – '+num(hi)+' · 绘图抽样，回撤按全部5m数据计算';svg.append(label)}
function orders(){if(!detail)return;q('research-orders').replaceChildren();const filter=q('research-pair').value,items=detail.orders.filter(o=>filter==='all'||o.pair.startsWith(filter+'/'));for(const o of items){cells('research-orders',[new Date(o.timestamp).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}),o.pair.split('/')[0],o.side==='buy'?'买入':'卖出',num(o.price,4),num(o.amount,5),num(o.fee,4),reasons[o.reason]??o.reason??reasons[o.trade_exit_reason]??o.trade_exit_reason])}q('research-count').textContent=`全部成交第 ${detail.total_orders?offset+1:0}–${offset+detail.orders.length} / ${detail.total_orders} 条；当前页币种筛选显示 ${items.length} 条`;q('research-prev').disabled=offset===0;q('research-next').disabled=offset+detail.orders.length>=detail.total_orders;if(!items.length)cells('research-orders',['该区间/本页无匹配成交','—','—','—','—','—','没有成交不代表策略通过验证'])}
async function loadDetail(reset=true){const rev=++revision;if(reset)offset=0;const strategy=q('research-strategy').value;detail=null;q('research-orders').replaceChildren();q('research-curve').replaceChildren();q('research-count').textContent='正在加载所选区间和策略…';q('research-metrics').textContent='';q('research-prev').disabled=true;q('research-next').disabled=true;q('research-rule').textContent=descriptions[strategy]??strategy;try{const r=await get('research/detail?'+new URLSearchParams({window:q('research-window').value,strategy,offset,limit:100}));if(rev!==revision)return;detail=r;curve(r.curve);orders();const m=r.metrics;q('research-metrics').textContent=`最终权益 ${num(m.final_equity)} USDT · 手续费及滑点预留 ${num(m.fee_cost_usdt)} · 资金费净收入 ${num(m.funding_net_income_usdt)} · `+Object.entries(m.pnl_by_pair).map(([p,v])=>p.split('/')[0]+' 净贡献 '+num(v)+' USDT').join(' / ')}catch(e){if(rev===revision)q('research-metrics').textContent=e.message}}
q('research-window').addEventListener('change',list);q('research-strategy').addEventListener('change',()=>loadDetail());q('research-pair').addEventListener('change',orders);q('research-prev').addEventListener('click',()=>{offset=Math.max(0,offset-100);loadDetail(false)});q('research-next').addEventListener('click',()=>{offset+=100;loadDetail(false)});
get('research').then(r=>{result=r;q('research-status').textContent=`已完成 ${r.rows.length} 组比较。筛选段选定 ${r.selection.primary}，留出段用于检验而非改选赢家；NFI X7/X8在留出段没有成交。72h与无期限版本本轮结果相同，提前退出和频繁交易成本更值得调整。研究未自动替换当前模拟策略。`;list()}).catch(e=>q('research-status').textContent=e.message);
let stopResults;
const stopNames={Legacy:'原追踪2.5/3ATR',Wide:'宽追踪4/5ATR',Fixed:'固定初始3.5ATR',ClosedTrail:'闭合周期延迟追踪',Structure:'结构低点止损'};
function stopRows(){if(!stopResults)return;q('stop-rows').replaceChildren();const matches=stopResults.rows.filter(r=>r.window===q('stop-window').value);for(const r of matches){const m=r.mark_metrics,policy=r.strategy.replace(/^(D55|E4|A1|M4)/,'');const tr=cells('stop-rows',[r.strategy,stopNames[policy]??policy,num(m.return_pct)+'%',num(m.sampled_mark_drawdown_pct)+'%',r.total_trades,num(m.holding_max_hours,1)+'小时']);tr.tabIndex=0;tr.style.cursor='pointer';tr.addEventListener('click',()=>selectStop(r.strategy));tr.addEventListener('keydown',e=>{if(e.key==='Enter')selectStop(r.strategy)})}if(!matches.length)cells('stop-rows',['此区间尚未完成分析','—','—','—','—','—'])}
async function stops(){try{stopResults=await get('research/stops');q('stop-research-status').textContent=`已完成 ${stopResults.completed_backtests} 份回测，${stopResults.rows.length} 份已计算含浮亏回撤。${stopResults.selection?'筛选已冻结，只用开发段、筛选段及筛选段双倍费用选型。':'等待预设筛选数据齐全，暂不选赢家。'} 实盘关闭，当前模拟规则未替换。`;q('stop-retained').replaceChildren();const statuses={awaiting_challenge:'等待历史压力复核',historical_gates_failed:'历史压力未通过',historical_gates_passed:'历史门槛通过，待前向验证'};for(const r of stopResults.registry?.entries??[]){const p=document.createElement('p');p.textContent=`保留 ${r.strategy}：${statuses[r.status]??r.status}${r.missing.length?'；待跑 '+r.missing.join(' / '):''}${r.failed.length?'；未通过 '+r.failed.join(' / '):''}`;q('stop-retained').append(p)}stopRows()}catch(e){q('stop-research-status').textContent=e.message}}
let stopStrategy,stopOffset=0,stopRevision=0;
function selectStop(strategy){stopStrategy=strategy;stopOffset=0;loadStopDetail()}
async function loadStopDetail(){
  const rev=++stopRevision;
  q('stop-detail-title').textContent=stopStrategy+' · '+q('stop-window').selectedOptions[0].textContent;
  q('stop-count').textContent='正在读取成交…';q('stop-orders').replaceChildren();q('stop-prev').disabled=true;q('stop-next').disabled=true;
  try{
    const d=await get('research/detail?'+new URLSearchParams({study:'v6',window:q('stop-window').value,strategy:stopStrategy,offset:stopOffset,limit:100}));
    if(rev!==stopRevision)return;
    curve(d.curve,'stop-curve');
    const m=d.metrics;
    q('stop-detail-metrics').textContent=`权益 ${num(m.final_equity)} USDT · 费用 ${num(m.fee_cost_usdt)} · 资金费净收入 ${num(m.funding_net_income_usdt)} · `+Object.entries(m.pnl_by_pair).map(([p,v])=>p.split('/')[0]+' 净贡献 '+num(v)+' USDT').join(' / ');
    for(const o of d.orders)cells('stop-orders',[new Date(o.timestamp).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}),o.pair.split('/')[0],o.side==='buy'?'买入':'卖出',num(o.price,4),num(o.amount,5),num(o.fee,4),o.reason==='closed_bar_gap_stop'?'闭合K线止损已跌破':reasons[o.reason]??o.reason??reasons[o.trade_exit_reason]??o.trade_exit_reason]);
    q('stop-count').textContent=`第 ${d.total_orders?stopOffset+1:0}–${stopOffset+d.orders.length} / ${d.total_orders} 条成交`;
    q('stop-prev').disabled=stopOffset===0;q('stop-next').disabled=stopOffset+d.orders.length>=d.total_orders;
  }catch(e){if(rev===stopRevision)q('stop-count').textContent=e.message}
}
q('stop-prev').addEventListener('click',()=>{stopOffset=Math.max(0,stopOffset-100);loadStopDetail()});
q('stop-next').addEventListener('click',()=>{stopOffset+=100;loadStopDetail()});
q('stop-window').addEventListener('change',()=>{stopRows();const candidates=stopResults?.rows.filter(r=>r.window===q('stop-window').value)??[];if(candidates.length)selectStop(candidates.some(r=>r.strategy===stopStrategy)?stopStrategy:candidates[0].strategy)});stops();setInterval(stops,30000);
async function forward(){
  try{
    const result=await get('research/forward');
    q('forward-accounts').replaceChildren();q('forward-trades').replaceChildren();
    q('forward-status').textContent=result.started_ms?`自 ${new Date(result.started_ms).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})} 起记录新行情。${result.status_stale?'状态已过期，请检查模拟服务。':'实盘关闭。'}`:'独立模拟尚未启动。';
    const states={observing:'运行中 · 等待/执行信号',warming_or_data_stale:'预热中或数据过期',market_data_degraded:'行情/盘口异常 · 查看失败记录',stopped:'已停止',fault_new_entries_blocked:'异常 · 已禁止新开仓'};
    const dt=s=>s?new Date(s.replace(' ','T')+'Z').toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}):'持有中';
    for(const a of result.accounts){
      cells('forward-accounts',[a.strategy,(result.status_stale?'状态过期':states[a.state]??a.state)+(a.market_events?.failed_entry_attempts?' · 盘口/建单失败 '+a.market_events.failed_entry_attempts+' 次':''),num(a.estimated_liquidation_equity),num(a.observed_drawdown_pct)+'%',a.open_positions,a.closed_trades,num(a.closed_profit_usdt)+' USDT']);
      for(const t of a.recent_trades)cells('forward-trades',[a.strategy+' / '+t.pair.split('/')[0],dt(t.open_date),num(t.open_rate,4),num(t.stop_loss,4),dt(t.close_date),num(t.close_rate,4),num(t.close_profit_abs),`${reasons[t.enter_tag]??t.enter_tag??'—'} / ${reasons[t.exit_reason]??t.exit_reason??'持有中'}`]);
    }
    if(!result.accounts.some(a=>a.recent_trades.length))cells('forward-trades',['尚无实时模拟成交','—','—','—','—','—','—','请结合信号、盘口失败及数据状态判断']);
  }catch(e){q('forward-status').textContent=e.message}
}
forward();setInterval(forward,15000);
const holdingNames={TriHold:'三币底仓持有（新版控制）',TriEnhance:'三币底仓＋慢退出增强',BroadHold:'16币等权底仓持有',BroadEnhance:'16币等权底仓＋增强',AnchorHold:'三币50%＋扩展币20%持有',AnchorEnhance:'三币50%＋扩展币20%增强',CoreHold70:'70%底仓持续持有',Enhance20:'底仓＋20%趋势增强',Enhance40:'底仓＋40%趋势增强',Enhance70:'底仓＋70%趋势增强',Enhance40Slow:'底仓＋40%慢退出增强',CrossNotional70:'全仓2x · 70%名义仓位持有',CrossMargin70:'全仓2x · 70%保证金持有',CrossFlex:'全仓2x · 风险上升减仓',CrossFlexAdd:'全仓2x · 浮盈加仓＋风险减仓',DriftHold:'持有不减仓（加仓对照）',CapTotal70:'持续压回70%总权重',CapTotal70Single25:'持续压回25%单币 / 70%总权重',ProfitAdd50:'浮盈额度50%顺势加仓',ProfitAdd100:'浮盈额度100%顺势加仓',HoldMargin2x:'逐仓2x持有/强平后重入 · 70%保证金',HoldNotional2x:'逐仓2x持有/强平后重入 · 70%名义仓位',D55Margin2x:'逐仓2x突破/强平后可重入 · 70%保证金',D55Notional2x:'逐仓2x突破/强平后可重入 · 70%名义仓位',HoldMargin2xNoReentry:'逐仓2x持有/强平后停止 · 70%保证金',HoldNotional2xNoReentry:'逐仓2x持有/强平后停止 · 70%名义仓位',HoldEqual:'三币等权一直持有',HoldZecSlice:'23.33% ZEC持有，其余现金',HoldZec70:'70% ZEC集中持有（仓位不同）',M4HoldEntry:'多周期入场后持有',A1HoldEntry:'1h突破入场后持有',D55HoldEntry:'4h突破入场后持有',M4SlowHold:'多周期入场＋慢退出',A1SlowHold:'1h突破＋慢退出',D55SlowHold:'4h突破＋慢退出',M4Structure:'原多周期＋结构止损',A1Fixed:'原1h突破＋固定ATR',D55ClosedTrail:'原4h突破＋延迟追踪'};
let holdingResults,holdingStrategy,holdingStudy='v7',holdingOffset=0,holdingRevision=0;
function holdingRows(){
  if(!holdingResults)return;
  q('holding-rows').replaceChildren();
  const selected=holdingResults.rows.filter(r=>r.window===q('holding-window').value&&(q('holding-family').value==='all'||r.study===q('holding-family').value)).sort((a,b)=>Number(a.mark_metrics.return_is_hypothetical_after_breach??false)-Number(b.mark_metrics.return_is_hypothetical_after_breach??false)||b.mark_metrics.return_pct-a.mark_metrics.return_pct);
  for(const r of selected){
    const m=r.mark_metrics,v=r.versus_equal_hold;
    const tr=cells('holding-rows',[holdingNames[r.strategy]??r.strategy,num(m.return_pct)+'%',num(m.sampled_mark_drawdown_pct)+'%',v?(v.return_gap_pp>=0?'+':'')+num(v.return_gap_pp)+'个百分点'+(v.allocation_differs?(r.study==='v12'?'（增强后敞口不同）':'（投入/杠杆不同）'):''):'待基准',r.study==='v12'?(r.versus_three_coin_enhance_pp>=0?'+':'')+num(r.versus_three_coin_enhance_pp)+'个百分点':'—',num(m.average_marked_exposure_pct)+'%',r.total_trades,m.return_is_hypothetical_after_breach?'保证金越界 · 收益仅为假设':(Math.max(m.sampled_mark_drawdown_pct,m.joint_low_stress_drawdown_pct??0)>50?'收盘/压力回撤超过50%':'收盘/压力回撤≤50%')+(['v10','v11','v12'].includes(r.study)?(m.unresolved_core_risk?.length?' / 底仓剩余风险未解决':' / 未触发保证金边界'):'')]);
    tr.tabIndex=0;tr.style.cursor='pointer';if(r.strategy==='HoldEqual')tr.style.color='#f1ce83';
    const choose=()=>{holdingStrategy=r.strategy;holdingStudy=r.study??'v7';holdingOffset=0;holdingDetail()};tr.addEventListener('click',choose);tr.addEventListener('keydown',e=>{if(e.key==='Enter')choose()});
  }
  if(!selected.length)cells('holding-rows',['此研究在该区间暂无结果','—','—','—','—','—','—','—']);
}
function expandedUniverse(){
  const universe=holdingResults.expansion_universe_freeze, fundamentals=holdingResults.expansion_fundamental_sources;
  q('expansion-universe').replaceChildren();
  if(!universe){q('expansion-universe-note').textContent='扩展候选资料尚未准备';return}
  q('expansion-universe-note').textContent=`冻结候选 ${universe.symbols.length} 币，新增 ${universe.added_symbols.length} 币；公开行情快照 ${new Date(universe.captured_at).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false})}（不是实时行情）。当前名单有事后选择/幸存偏差；研究分组不代表已经验证适合长期投资。TON结算中，TRX低于本轮成交门槛，未纳入。`;
  for(const row of universe.rows){
    const coin=row.symbol.replace('USDT',''), f=fundamentals?.candidates?.find(x=>x.symbol===coin);
    const tr=cells('expansion-universe',[coin,({first_pass:'优先研究',conditional:'条件候选',comparison:'对照候选'})[f?.research_group]??'用户指定底仓',num(row.quote_volume_24h/1e6)+' 百万USDT',f?.use_case??'原三币对照，保留用户指定底仓',f?f.token_value_capture+' 风险：'+f.risks_and_reasons_to_exclude.join('；'):'本轮未重新评级，不代表无风险','']);
    tr.children[3].className='wrap';tr.children[4].className='wrap';
    for(const source of (f?.sources??[]).slice(0,2)){if(!source.url.startsWith('https://'))continue;const a=document.createElement('a');a.href=source.url;a.textContent=source.title;a.target='_blank';a.rel='noopener noreferrer';tr.lastElementChild.append(a,document.createElement('br'))}
  }
  const choice=holdingResults.expansion_selection,status=holdingResults.expansion_status;
  q('expansion-selection').textContent=choice?`多币扩展完成：${holdingResults.v12_runs} 组；当前研究首选 ${holdingNames[choice.selected]??'暂无通过方案'}。通过风险门槛后，按最差完整窗口的账户净收益排序；候选 ${choice.candidates.map(x=>holdingNames[x]??x).join(' / ')||'暂无'}。跑赢对应持有不等于跑赢三币增强，请查看两列超额。尚未替换当前模拟。`:status?.state==='failed'?`多币回测失败 · 已完成 ${status.completed}/${status.expected} 组 · ${status.error_type}: ${status.error}。失败未作为完整结果参与选型。`:`多币扩展研究准备中${status?' · 已完成 '+status.completed+'/'+status.expected+' 组':''}；不把未完成的结果当作结论。`;
}
async function holding(){
  try{
    holdingResults=await get('research/holding');
    q('holding-status').textContent=`已完成 ${holdingResults.completed_backtests} 组持有研究、${holdingResults.v8_runs??0} 组加仓/减仓回放、${holdingResults.v9_runs??0} 组逐仓对照、${holdingResults.v10_runs??0} 组全仓研究、${holdingResults.v11_runs??0} 组三币底仓/增强、${holdingResults.v12_runs??0} 组多币扩展研究。各方案扣除费用及实际资金费；初始预算相同不等于平均敞口相同，点击查看成交和曲线。`;
    const selectedOverlay=holdingResults.overlay_selection;
    q('overlay-selection').textContent=selectedOverlay?(selectedOverlay.selected?'v11历史筛选候选：'+(holdingNames[selectedOverlay.selected]??selectedOverlay.selected)+'。同时通过各区间回撤与全区间超额/压力检查，仍需新行情前向验证。':'新轮已完成；暂无增强方案同时通过全部预设门槛，保留持有基准。'):'';
    expandedUniverse();
    holdingRows();
    if(!holdingStrategy&&q('holding-family').value==='v11'&&holdingResults.rows.some(r=>r.study==='v11'&&r.window===q('holding-window').value)){holdingStrategy=selectedOverlay?.selected??'CoreHold70';holdingStudy='v11';holdingDetail()}
    if(!holdingStrategy&&q('holding-family').value==='v12'&&holdingResults.rows.some(r=>r.study==='v12'&&r.window===q('holding-window').value)){holdingStrategy=holdingResults.expansion_selection?.selected??'TriHold';holdingStudy='v12';holdingOffset=0;holdingDetail()}
    if(!holdingStrategy&&q('holding-family').value==='v10'&&holdingResults.rows.some(r=>r.study==='v10'&&r.window===q('holding-window').value&&r.strategy==='CrossFlexAdd')){holdingStrategy='CrossFlexAdd';holdingStudy='v10';holdingDetail()}
  }catch(e){q('holding-status').textContent=e.message}
}
async function holdingDetail(){
  const rev=++holdingRevision;
  q('holding-rule').textContent=(holdingNames[holdingStrategy]??holdingStrategy)+' · '+q('holding-window').selectedOptions[0].textContent;
  q('holding-orders').replaceChildren();q('holding-risk').replaceChildren();q('holding-risk-summary').textContent='';q('holding-monthly').replaceChildren();q('holding-monthly-panel').hidden=true;q('holding-prev').disabled=true;q('holding-next').disabled=true;q('holding-count').textContent='正在加载成交…';
  try{
    const d=await get('research/detail?'+new URLSearchParams({study:holdingStudy,window:q('holding-window').value,strategy:holdingStrategy,offset:holdingOffset,limit:100}));
    if(rev!==holdingRevision)return;
    curve(d.curve,'holding-curve');const m=d.metrics;if(holdingStudy==='v9')q('holding-rule').textContent+=' · 逐仓模型强平 '+(m.exit_counts?.liquidation??0)+' 次 · '+(holdingStrategy.endsWith('NoReentry')?'强平后该币永久停止买入':'强平后允许重新入场')+' · 未计强平罚金';
    if(['v10','v11','v12'].includes(holdingStudy)){
      q('holding-risk-summary').textContent=`加仓 ${m.add_fills} 次 · 风险减仓 ${m.risk_reduction_rounds} 轮 · 5m共同低点压力回撤 ${num(m.joint_low_stress_drawdown_pct)}% · 最小压力维持保证金余量 ${num(m.minimum_joint_low_maintenance_buffer_usdt)} USDT · ${m.risk_model_passed?'本样本未触发模型保证金边界':'存在保证金越界，后续收益仅为假设，不能用于排名'}。${Math.max(m.sampled_mark_drawdown_pct,m.joint_low_stress_drawdown_pct??0)>50?'超过50%研究回撤容忍，暂不通过。':'通过该样本回撤检查，不代表未来保障。'}`;
      for(const r of d.risk_reductions??[])cells('holding-risk',[new Date(r.timestamp).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}),r.reason==='before_reduce'?'减仓前':'减仓后',num(r.equity),num(r.effective_leverage,3)+'x',num(r.all_zero_cash_floor),Object.entries(r.conditional_liquidation_prices).map(([s,v])=>s.replace('USDT','')+' '+(v===null?'无正值':num(v,4))).join(' / ')]);
      if(!d.risk_reductions?.length)cells('holding-risk',['此区间未触发风险减仓','—','—','—','—','查看成交及权益曲线']);
    }
    if(['v11','v12'].includes(holdingStudy)){q('holding-monthly-panel').hidden=false;for(const r of d.monthly_returns??[])cells('holding-monthly',[r.month,num(r.return_pct)+'%',num(r.core_contribution_pp)+'个百分点',num(r.overlay_contribution_pp)+'个百分点',num(r.final_equity)]);q('holding-risk-summary').textContent+=` 底仓数量全程保留；增强退出 ${m.overlay_exit_rounds} 轮，盈利月份 ${m.positive_months}/${m.observed_months}，最差月 ${num(m.worst_month_pct)}%。`;}
    q('holding-metrics').textContent=`权益 ${num(m.final_equity)} USDT · 费用 ${num(m.fee_cost_usdt)} · 资金费净收入 ${num(m.funding_net_income_usdt)} · `+Object.entries(m.pnl_by_pair).map(([p,v])=>p.split('/')[0]+' 净贡献 '+num(v)+' USDT').join(' / ');
    for(const o of d.orders)cells('holding-orders',[new Date(o.timestamp).toLocaleString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false}),o.pair.split('/')[0],(o.side==='buy'?'买入':'卖出')+(o.sleeve==='core'?' · 底仓':o.sleeve==='overlay'?' · 增强仓':''),num(o.price,4),num(o.amount,5),num(o.fee,4),({overlay_profit_breakout:'增强仓：盈利＋4h突破',overlay_trend_exit:'增强仓：连续两根4h弱势退出',overlay_account_risk:'先退出增强仓降低全仓风险',cross_reduce_to_cash_floor:'全仓有效杠杆>1.6，部分减仓至0.9',cross_profit_breakout_add:'4h突破＋盈利，按全仓余量加仓',liquidation:'模型强平退出（未含强平罚金）',same_hold_seed:'同基准初始买入',sample_end:'样本结束平仓',profit_breakout_add:'4h突破＋浮盈顺势加仓',policy_weight_cap:'维持权重上限减仓',two_4h_below_ema200:'连续两根4h失守EMA200'})[o.reason]??reasons[o.reason]??o.reason??reasons[o.trade_exit_reason]??o.trade_exit_reason]);
    if(['v11','v12'].includes(holdingStudy))q('holding-metrics').textContent+=` · 底仓净贡献 ${num(m.core_pnl_usdt)} / 增强净贡献 ${num(m.overlay_pnl_usdt)} USDT · 最高总敞口 ${num(m.max_marked_exposure_pct)}% / 最高单币敞口 ${num(m.max_single_marked_weight_pct)}%（占当时账户权益）`;
    if(holdingStudy==='v12')q('holding-metrics').textContent+=` · 初始实际底仓 ${m.initial_core_symbols.length} 币 / ${num(m.initial_core_notional_usdt)} USDT`;
    q('holding-count').textContent=`第 ${d.total_orders?holdingOffset+1:0}–${holdingOffset+d.orders.length} / ${d.total_orders} 条成交`;
    q('holding-prev').disabled=holdingOffset===0;q('holding-next').disabled=holdingOffset+d.orders.length>=d.total_orders;
  }catch(e){if(rev===holdingRevision)q('holding-count').textContent=e.message}
}
function resetHolding(){holdingRows();holdingStrategy=null;holdingOffset=0;++holdingRevision;q('holding-risk').replaceChildren();q('holding-risk-summary').textContent='';q('holding-monthly').replaceChildren();q('holding-monthly-panel').hidden=true;q('holding-curve').replaceChildren();q('holding-orders').replaceChildren();q('holding-rule').textContent='点击当前区间方案查看明细';q('holding-metrics').textContent='';q('holding-count').textContent='';q('holding-prev').disabled=true;q('holding-next').disabled=true}
q('holding-window').addEventListener('change',resetHolding);q('holding-family').addEventListener('change',resetHolding);
q('holding-prev').addEventListener('click',()=>{holdingOffset=Math.max(0,holdingOffset-100);holdingDetail()});q('holding-next').addEventListener('click',()=>{holdingOffset+=100;holdingDetail()});
holding();setInterval(holding,30000);
})();
