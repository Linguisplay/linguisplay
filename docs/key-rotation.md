# 🔑 Key 轮换 runbook

三把 key 曾在明文对话/聊天里出现过，都应轮换。控制台部分只有你能做（要登你的账号），
换好后把新 key 发我或自己按第 2 步换上，全程服务不中断（旧 key 在新 key 生效前先别删）。

## 1. 去各控制台生成新 key（你来）

| Key | 控制台 | 用途 | 影响面 |
|---|---|---|---|
| `DEEPSEEK_API_KEY` | platform.deepseek.com → API Keys | 全部对话/旁白/判定 | 换错即全站哑火，优先级最高 |
| `DASHSCOPE_API_KEY` | dashscope.console.aliyun.com | 万相出图 + 智能增强合成 | 出图/增强失败，对话不受影响 |
| `TAVILY_API_KEY` | app.tavily.com | 智能增强的联网搜索 | 缺失时自动降级为模型自产知识 |

建新 key 后先【不要删旧的】。

## 2. 换 key（我可代做，或你自己跑）

```bash
ssh persona
vi /opt/linguisplay/apps/api/.env        # 替换对应行
systemctl restart linguisplay
curl -s localhost:8100/api/v1/health      # {"status":"ok"}
# 线上冒烟一轮对话确认 DeepSeek 新 key 可用，然后再回控制台删旧 key
```

本地开发同步改 `apps/api/.env`（gitignored）。`deploy/.env.production` 是模板，也要同步，
它同样 gitignored，绝不入库。

## 3. 完成后

- 回各控制台删除旧 key
- 在本文件底部记一行轮换日期
- 顺手检查用量报警（DeepSeek/DashScope 都支持用量提醒，建议设月度上限）

## 轮换记录

- （待首轮：2026-07-__ 由 Yi 执行控制台部分）
