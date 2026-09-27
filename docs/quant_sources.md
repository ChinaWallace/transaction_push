# v3 研究来源与数据依据

下列资料用于比较方法与独立实现规则，没有直接复制第三方策略源码，也没有采用作者宣传收益作为项目收益。

| 来源 | 使用方式 / 不能照搬的原因 |
|---|---|
| [Freqtrade strategies](https://github.com/freqtrade/freqtrade-strategies) | 示例策略和测试思路，不是可直接实盘的收益认证 |
| [Globe Research bittrends](https://github.com/Globe-Research/bittrends) / [原论文](https://www.monash.edu/__data/assets/pdf_file/0011/3744821/Trend-following-Strategies-for-Crypto-Investors.pdf) | 趋势跟随和跨币组合研究，保留失败的复现实验 |
| [Donchian Quest Research](https://www.tradingview.com/script/YPQwKNF8-Donchian-Quest-Research/) | 通道突破、ATR 风险管理；不以作者单标的结果推断组合表现 |
| [Donchian + ATR trail](https://es.tradingview.com/script/NeEiwmDq-Donchian-Breakout-with-ATR-Trailing-Stop-Trend-Following/) | 初始止损与追踪止损分开、去掉固定止盈截断 |
| [Momentum and liquidity](https://arxiv.org/html/1904.00890v1) | 动量必须结合成交量；论文的历史市值资格和交易成本假设需要另行验证 |
| [Crypto momentum implementation](https://github.com/matiasjarnal/crypto-momentum-strategy) | 多窗口动量、波动预算、市场状态；固定币池与参数筛选的宣传结果不作为证据 |
| [Binance public-data](https://github.com/binance/binance-public-data) | 官方日线/资金费归档，抽样核对连接器历史 |
| [Funding history API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History) | 实际事件时间、费率和结算标记价格，按游标分页 |
| [CoinGecko coins/markets](https://docs.coingecko.com/reference/coins-markets) | 明确 ID 查询市值与更新时间；未知身份不自动按 ticker 绑定 |
| [Freqtrade callbacks](https://www.freqtrade.io/en/stable/strategy-callbacks/) / [stoploss](https://www.freqtrade.io/en/stable/stoploss/) / [leverage](https://www.freqtrade.io/en/stable/leverage/) | 执行桥接以安装版本 2026.8 源码和测试为准，杠杆止损按框架定义换算 |
| [SK Hynix on Binance](https://academy.binance.com/ka-GE/articles/how-to-trade-sk-hynix-skhy-on-binance) | 核实 SKHY ADR 与 SKHYNIX 韩国股票合约的区别 |

本次补充的明确身份映射：

| 合约基资产 | CoinGecko ID | 币安官方身份依据 |
|---|---|---|
| NIL | nillion | [Nillion](https://www.binance.com/en/support/announcement/detail/6ddc69d48ff34b26b906f492e0794e22) |
| ONE | harmony | [Harmony](https://www.binance.com/en/support/announcement/detail/1127f937c5fe49acb976d4a2dd272d27)；避免与 ONEchain 同名混淆 |
| SAGA | saga-2 | [Saga](https://www.binance.com/en/support/announcement/detail/bbacdc0772cc4e839d8faeb71e90e56c) |
| MUBARAK | mubarak | [Mubarak](https://www.binance.com/en/support/announcement/detail/6e3391cffa774b2a9711e8597a618edb) |
| AKE | akedo | [Akedo](https://www.binance.com/en/support/announcement/detail/f7b86984a0d34f4fbfc3204fa93ae344) |
| MET | meteora | [Meteora](https://www.binance.com/zh-CN/support/announcement/detail/1122eaa3253440cbbb27dedc31f87b22) |
| RAYSOL | raydium | [Raydium 标的及地址](https://www.binance.com/es-LA/support/announcement/detail/43f5771df16344a8b5ce26f67d21fc0d) |

BR 的资料存在 ticker 表述冲突，暂不自动绑定。股票/ADR/ETF 的估值需要另建经过身份核验的数据源，不能借用同 ticker 的加密资产市值。
