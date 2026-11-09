# 官机云平台

多用户 QQ 官方机器人托管平台（公益项目）：用户注册账号 → 绑定自己的官方机器人（AppID/AppSecret）→ 平台云端运行实例 → 所有功能在网页端配置。

对标 blo.jwapp.cn 的核心链路，**v1 不含插件市场**，功能为内置插件式（见下）。

## 功能总览

**平台侧**：注册/登录、机器人绑定（官方 OAuth 校验 + Fernet 加密存储）、实例启停/重启、实例自检（群内角色/消息范围/主动推送开关诊断）、审计日志。

**机器人侧（每实例独立配置，页面热生效）**：
- **插件市场**：预设插件包一键安装/卸载——防广告基础包、防刷屏、新人进群通知、进群欢迎、AI 对话、每日签到、娱乐套件、举报通道、入群审批；装完可在各页签继续自定义
- **群管自动化（规则引擎）**：自定义"触发 → 动作"规则，支持分群（指定群/所有群）+ 实例总开关；触发：关键词（包含/正则）、链接/拉群引流、刷屏、新人进群；动作：撤回、回复、禁言、踢出、拉黑、通知管理群、记录
- **群管理工具**（网页直连官方接口）：禁言状态/手动禁言/解禁、踢人、群黑名单、成员浏览、自动审批策略
- **管理指令**（带管理员名单权限）：`/禁言` `/解禁` `/踢人` `/拉黑` `/禁言列表` `/我的ID`
- 基础指令：`/帮助` `/状态` `/签到`
- 关键词自动回复（多关键词、文本/图片、仅@或全量触发）
- AI 对话（OpenAI 兼容接口，用户自带 key；GLM/DeepSeek/OpenAI 均可；每人每日限次）
- 欢迎新人、入群审批（事件通知 + 页面审批 + 关键词自动通过）、定时推送（cron）、签到与活跃统计、举报通道、抽签/骰子/抽奖
- 撤回自纠错（机器人是群管理员时可撤回普通成员消息，2 分钟内）
- **插件热加载**：往 `app/runtime/plugins/` 放新的 `.py` 插件文件即自动识别（目录 mtime 变化触发重载），`POST /api/instances/plugins/reload` 可强制重扫

## 快速开始（本机开发）

```bash
# 后端（Python 3.11+）
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt     # Windows
.venv/bin/pip install -r requirements.txt          # Linux/Mac
cp .env.example .env                                # 修改 SECRET_KEY

# 前端
cd frontend && npm install && npm run build && cd ..

# 启动（同一进程服务 API + 前端 + 机器人运行时）
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

浏览器访问 http://127.0.0.1:8000 。开发时前端热更新：`cd frontend && npm run dev`（代理到 8000）。

默认 SQLite（`data/app.db`），无需任何数据库环境。

## 部署（云服务器 / NAS，Docker）

```bash
docker compose up -d --build
```

包含 PostgreSQL + 应用，自动重启。访问 `http://服务器IP:8000`。
建议：设置强 `SECRET_KEY`；注册完自己的账号后设 `OPEN_REGISTRATION=false` 重新启动以关闭公开注册。

## 联调真实机器人

1. 开放平台创建机器人，拿 AppID/AppSecret 绑定到平台
2. 机器人拉进测试群，群主在群设置开启「获取群内全部消息」（监控/关键词全量触发需要）
3. 需要撤回/禁言/审批：群主把机器人设为群管理员
4. 在实例页「概览/自检」填群 openid 点自检，按提示修复配置
5. 踢人/群成员列表接口官方为**内邀制**，是否可用以实际调用返回为准

## 架构

```
app/
├── main.py            FastAPI 入口（Web + 运行时同进程）
├── config.py          环境配置
├── models.py          全部数据表（user_id + bot_instance_id 两级隔离）
├── security.py        bcrypt / JWT / Fernet 加密
├── api/               REST 接口（auth / instances / features）
├── qq/                官方 v2 协议层
│   ├── client.py      Token 管理 + 全部业务 API（发消息/撤回/禁言/审批/黑名单…）
│   └── gateway.py     WebSocket 网关（心跳/Identify/Resume/自动重连）
└── runtime/
    ├── supervisor.py  实例生命周期（启动/停止/配置热重载）
    ├── runner.py      单实例运行器（连接 + 事件分发 + cron 调度）
    ├── context.py     实例上下文（限频、每日额度、事件去重、错误归类）
    └── plugins/       commands / keywords / ai_chat / welcome / moderation / approval / stats
frontend/              Vue3 + Element Plus 管理台
```

## 官方能力边界（2026-10 文档核对）

- ✅ 撤回（管理员可撤普通成员消息，2 分钟内）、成员级禁言（≤30天）、入群审批（人工+自动策略）、群黑名单
- 🎫 内邀制：群成员列表、批量踢人（接口存在，需白名单权限，错误码 11253）
- ❌ 无接口：开启/关闭全员禁言（只能查询）
- 主动消息：每群每日 1000 条封顶，未认证 30 条/分钟；群被动回复窗口 5 分钟/5 次
- 内容安全：发送内容平台自动审查，命中直接拒发（1100100 族错误码）
