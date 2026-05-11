# Translation API 语言支持对比

> 更新时间：2026-05-11

## 各 Provider 语言支持

### 对比表

| 语言 | 代码 | 阿里云 Qwen | OpenAI Realtime | OpenAI Translate | 豆包 Doubao |
|------|------|:-----------:|:---------------:|:----------------:|:-----------:|
| 中文 | zh | S2S/S2T | S2S/S2T | S2S/S2T | S2S/S2T |
| 英语 | en | S2S/S2T | S2S/S2T | S2S/S2T | S2S/S2T |
| 日语 | ja | S2S/S2T | S2S/S2T | — | S2S/S2T* |
| 韩语 | ko | S2S/S2T | S2S/S2T | — | — |
| 法语 | fr | S2S/S2T | S2S/S2T | S2S/S2T | S2S/S2T* |
| 德语 | de | S2S/S2T | S2S/S2T | — | S2S/S2T* |
| 西班牙语 | es | S2S/S2T | S2S/S2T | S2S/S2T | S2S/S2T* |
| 意大利语 | it | S2S/S2T | S2S/S2T | — | — |
| 葡萄牙语 | pt | S2S/S2T | S2S/S2T | S2S/S2T | S2S/S2T* |
| 俄语 | ru | S2S/S2T | S2S/S2T | — | — |
| 粤语 | yue | —* | S2S/S2T | — | — |
| 阿拉伯语 | ar | — | — | S2S/S2T | — |
| 印尼语 | id | — | — | S2S/S2T | S2S/S2T* |
| 斯瓦希里语 | sw | — | — | S2S/S2T | — |

\* 阿里云 Qwen 的粤语仅在特定音色下可用，当前已注释掉
\* 豆包 Doubao 约束：source/target 之一必须是 zh 或 en

### 总结

| Provider | UI 显示数量 | 后端全量 | S2S | S2T | 价格 |
|----------|:-----------:|:--------:|:---:|:---:|------|
| 阿里云 Qwen | 10 | 18+6方言 | Yes | Yes | ¥ 计费 |
| OpenAI Realtime | 11 | 11 | Yes | Yes | $ 计费 |
| **OpenAI Translate** | **12** | **58** | **Yes** | **Yes** | **$0.034/分钟** |
| 豆包 Doubao | 8 | 8 | Yes | Yes | ¥ 计费 |

## OpenAI Translate 完整语言列表（58 种）

后端实际支持但 UI 暂未展示的语言（按字母排序）：

```
南非荷兰语(af), 阿塞拜疆语(az), 白俄罗斯语(be), 保加利亚语(bg),
波斯尼亚语(bs), 加泰罗尼亚语(ca), 捷克语(cs), 威尔士语(cy),
丹麦语(da), 希腊语(el), 爱沙尼亚语(et), 波斯语(fa), 芬兰语(fi),
加利西亚语(gl), 希伯来语(he), 印地语(hi), 克罗地亚语(hr),
匈牙利语(hu), 亚美尼亚语(hy), 冰岛语(is), 意第绪语(iw),
哈萨克语(kk), 卡纳达语(kn), 立陶宛语(lt), 拉脱维亚语(lv),
毛利语(mi), 马其顿语(mk), 马拉地语(mr), 马来语(ms), 尼泊尔语(ne),
荷兰语(nl), 挪威语(no), 波兰语(pl), 罗马尼亚语(ro), 斯洛伐克语(sk),
斯洛文尼亚语(sl), 塞尔维亚语(sr), 瑞典语(sv), 斯瓦希里语(sw),
泰米尔语(ta), 泰语(th), 他加禄语(tl), 土耳其语(tr), 乌克兰语(uk),
乌尔都语(ur), 越南语(vi)
```

## 不支持的语言

以下语言经实测 OpenAI Translate 不支持（2026-05-11）：

- **乌兹别克语 (uz)** — 返回 `invalid_value` 错误
