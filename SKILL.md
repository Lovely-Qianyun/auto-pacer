---
name: auto-pacer
description: 通过用户自己的 Zepp Life（原小米运动）账号把步数写入云端，使已关联的微信运动/支付宝运动同步更新。当用户想刷运动步数时使用。只提交一次并在命令行汇报，不推送、不轮询、不定时。
metadata:
  version: 1.0.0
---

# auto-pacer：Zepp Life 刷步数（同步微信运动/支付宝运动）

**本目录即工具本体**，记为 SKILL_DIR，包含：
- `main.py` 入口脚本（按脚本自身位置定位，可从任意工作目录执行）
- `util/` 接口封装：`account_api.py`（认证/令牌）、`data_api.py`（设备与提交）、`config_store.py`（配置读写）、`aes_help.py`（平台协议加密）、`timeutil.py`
- `assets/fake_band_payload` 抓包模板（提交数据样本，勿手改）
- `references/troubleshooting.md` 故障排查（按需读）；`references/architecture.md` 实现原理（一般无需读）
- 运行依赖仅三个（requests / pytz / pycryptodome，安装命令见第 2 步）；配置与令牌在**用户主目录** `~/.auto-pacer.json`（见下），**不在本目录**

配置位置（首次使用向导负责创建/更新）：用户主目录下 `.auto-pacer.json`，即 Windows `%USERPROFILE%\.auto-pacer.json`。

## 执行流程

### 1. 检查配置（未配置 → 引导输入）
1. 用文件工具读取主目录 `.auto-pacer.json`，检查是否已有 `user` 和 `pwd` 字段。
2. 已配置 → 跳过向导，直接进入第 3 步。
3. 未配置 → 对话收集，然后**用文件工具读→改→写回**该 JSON（文件可能已被 main.py 写入令牌字段，必须完整保留；必填 `user`/`pwd`，用户给了步数目标就把换算结果一并写入 `min_step`/`max_step`）：
   - 账号：Zepp Life（原小米运动）登录手机号或邮箱 —— **不是小米账号**
   - 密码：Zepp Life 登录密码 —— 不要向用户复述，也不要写入任何汇报性文件
   - 步数目标（可选，规则见下表）；默认范围 MIN=18000、MAX=25000

**步数解析规则**（向导把用户口语换算成整数后使用）：

| 用户说法 | 换算 | 示例 |
|---|---|---|
| 单个数字 | 即目标值 | "刷 2 万" / "刷 20000" / "20000 步" |
| "X万" / "Xw"（X 可含小数） | X × 10000 取整 | 1.5万 → 15000 |
| 区间（"~" / "-" / "到"分隔两个数） | 两值即 min/max | "1.5~2.5 万" → 15000~25000 |

- 单个目标值 → `min=max=该值`；区间 → 按区间
- 校验：换算后必须在 **1 ~ 90000** 内（代码硬上限）；用户要求超过时，先说明最多 90000
- **写文件即持久**：换算结果写入 `min_step`/`max_step` 后会被后续运行沿用；用户没给目标就保留文件现值，文件无这两个字段则按默认 18000 ~ 25000 随机

### 2. 安装依赖（仅首次或 ImportError 时）
```powershell
python -m pip install requests pytz pycryptodome
```

### 3. 运行
```powershell
python <SKILL_DIR>\main.py
```
- 运行参数全部来自 `~/.auto-pacer.json`，不读任何环境变量；目标步数已在向导第 1 步写入文件，直接运行即可
- 用户中途改目标或想恢复随机范围：让向导直接改文件中的 `min_step`/`max_step`（删掉这两个字段即回默认 18000 ~ 25000）
- 检查 `$LASTEXITCODE`：0 = 成功；1 = 失败（main.py 打印"执行完成: 成功/失败"）
- 配置或网络问题排查可先跑 `python <SKILL_DIR>\main.py --dry-run`（只加载配置并打印计划，不发任何请求）

### 4. 汇报结果
向用户说明：登录方式（信任窗口复用 / getUserInfo 校验 / 令牌续期 / 账号密码全量登录）、随机到的步数、提交结果、成功/失败数。
失败时的排查方向见 `references/troubleshooting.md`，不要编造原因。

## 安全与隐私

- `~/.auto-pacer.json`（含账号密码与令牌）为唯一敏感文件，勿外传、勿提交
- 展示账号时脱敏（如 138****8888），全程绝不输出密码
- 本 skill 不做任何推送/定时，运行一次刷一次；生成的是非真实行走记录，仅用于用户自己的运动数据
