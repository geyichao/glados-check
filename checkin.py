#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GLaDOS 自动签到
- 实时输出请求进度
- 显示签到接口原始消息
- 无 Telegram 配置也输出完整结果
- 今日已签到计入成功
"""

import json
import os
import sys
from datetime import datetime

import requests


# 修复 Windows Unicode 输出问题
if sys.platform.startswith("win") and hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


# ================= 配置 =================

DOMAINS = [
    "https://glados.cloud",
    "https://railgun.info",
    "https://glados.rocks",
    "https://glados.network",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Content-Type": "application/json;charset=UTF-8",
    "Accept": "application/json, text/plain, */*",
}

PLAN_REQUIREMENTS = {
    "plan100": 100,
    "plan200": 200,
    "plan500": 500,
}


# ================= 工具函数 =================

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def to_int(value, default=None):
    try:
        return int(float(str(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def extract_cookie(raw):
    if not raw:
        return None

    raw = raw.strip()

    if "koa:sess=" in raw or "koa:sess.sig=" in raw:
        return raw

    if raw.startswith("{"):
        try:
            obj = json.loads(raw)
            token = obj.get("token") if isinstance(obj, dict) else None
            if isinstance(token, str) and token.strip():
                return "koa:sess=" + token.strip()
        except (ValueError, TypeError):
            pass

    if raw.count(".") == 2 and "=" not in raw and len(raw) > 50:
        return "koa:sess=" + raw

    return raw


def get_cookies():
    raw = os.environ.get("GLADOS_COOKIE", "").strip()

    if not raw:
        log("❌ 未配置 GLADOS_COOKIE")
        return []

    sep = "\n" if "\n" in raw else "&"
    cookies = []

    for item in raw.split(sep):
        if not item.strip():
            continue

        cookie = extract_cookie(item)
        if cookie:
            cookies.append(cookie)

    return cookies


def checkin_succeeded(result):
    """按接口成功码或明确的成功/今日已签到消息判断。"""
    if not isinstance(result, dict):
        return False

    code = result.get("code")
    message = str(result.get("message") or "").strip().lower()

    return (
        code in (0, "0")
        or message.startswith("checkin!")
        or message.startswith("checkin successful")
        or message.startswith("today's observation logged")
        or message.startswith("today’s observation logged")
        or message.startswith("already checked in")
        or message.startswith("you have already checked in")
    )


# ================= 核心逻辑 =================

class GLaDOS:
    def __init__(self, cookie):
        self.cookie = cookie
        self.domain = DOMAINS[0]
        self.email = "未知账号"
        self.left_days = "?"
        self.points = None
        self.points_change = "?"
        self.exchange_info = "暂未获取到兑换选项"

    def req(self, method, path, data=None):
        # 优先使用上一次请求成功的域名
        domains = [self.domain] + [
            domain for domain in DOMAINS if domain != self.domain
        ]

        for domain in domains:
            url = f"{domain}{path}"

            headers = HEADERS.copy()
            headers["Cookie"] = self.cookie
            headers["Origin"] = domain
            headers["Referer"] = f"{domain}/console/checkin"

            log(f"🌐 {method} {url}")

            try:
                response = requests.request(
                    method,
                    url,
                    headers=headers,
                    json=data,
                    timeout=10,
                )
            except requests.RequestException as exc:
                log(
                    f"⚠️ {domain} 请求异常："
                    f"{type(exc).__name__}，尝试下一个域名"
                )
                continue

            log(f"📡 HTTP 状态码：{response.status_code}")

            if response.status_code != 200:
                continue

            try:
                result = response.json()
            except ValueError:
                log("⚠️ 返回内容不是有效 JSON，尝试下一个域名")
                continue

            if not isinstance(result, dict):
                log("⚠️ 返回 JSON 格式不符合预期，尝试下一个域名")
                continue

            self.domain = domain
            return result

        log(f"❌ 所有域名均未返回有效响应：{path}")
        return None

    def get_status(self):
        result = self.req("GET", "/api/user/status")

        if not isinstance(result, dict):
            log("⚠️ 账号状态查询失败")
            return False

        data = result.get("data")

        if not isinstance(data, dict):
            log(
                f"⚠️ 账号状态查询失败："
                f"{result.get('message', '未返回有效账号数据')}"
            )
            return False

        self.email = data.get("email") or "未知账号"
        days = to_int(data.get("leftDays"))
        self.left_days = str(days) if days is not None else "?"

        log(f"👤 账号：{self.email}，剩余：{self.left_days} 天")
        return True

    def get_points(self):
        result = self.req("GET", "/api/user/points")

        if not isinstance(result, dict) or "points" not in result:
            message = (
                result.get("message", "未返回积分数据")
                if isinstance(result, dict)
                else "未获取到有效响应"
            )
            log(f"⚠️ 积分查询失败：{message}")
            return False

        points = to_int(result.get("points"))

        if points is None:
            log("⚠️ 积分数据无法解析")
            return False

        self.points = points
        self.points_change = "?"

        history = result.get("history") or []

        if isinstance(history, list) and history:
            last = history[0]

            if isinstance(last, dict):
                change = to_int(last.get("change"))

                if change is not None:
                    self.points_change = f"{change:+d}"

        plans = result.get("plans") or {}
        valid_plans = []

        if isinstance(plans, dict):
            for plan_data in plans.values():
                if not isinstance(plan_data, dict):
                    continue

                need = to_int(plan_data.get("points"))
                days = to_int(plan_data.get("days"))

                if need is not None and days is not None:
                    valid_plans.append((need, days))

        exchange_lines = []

        for need, days in sorted(valid_plans):
            enough = self.points >= need
            icon = "✅" if enough else "❌"
            desc = "(可兑换)" if enough else f"(差{need - self.points}分)"
            exchange_lines.append(f"{icon} {need}分→{days}天 {desc}")

        self.exchange_info = (
            "\n".join(exchange_lines) or "暂未获取到兑换选项"
        )

        log(
            f"💰 当前积分：{self.points}，"
            f"最近一次变动：{self.points_change}"
        )
        return True

    def checkin(self):
        return self.req(
            "POST",
            "/api/user/checkin",
            {"token": "glados.cloud"},
        )

    def exchange(self, plan):
        return self.req(
            "POST",
            "/api/user/exchange",
            {"planType": plan},
        )


# ================= 推送函数 =================

def telegram_push(token, chat_id, title, content):
    if not token or not chat_id:
        return False

    # 使用纯文本，避免接口消息中的特殊字符破坏 HTML 格式
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    text = f"{title}\n\n{content}"

    # 分段发送，避免超过单条消息长度限制
    chunks = [
        text[index:index + 3500]
        for index in range(0, len(text), 3500)
    ]

    try:
        for chunk in chunks:
            response = requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": chunk,
                },
                timeout=10,
            )

            if response.status_code != 200:
                log(f"❌ Telegram 推送失败：HTTP {response.status_code}")
                return False

            result = response.json()

            if not isinstance(result, dict) or result.get("ok") is not True:
                log("❌ Telegram 推送失败：接口未确认发送成功")
                return False

        log("✅ Telegram 推送成功")
        return True

    except (requests.RequestException, ValueError) as exc:
        # 不输出包含机器人 Token 的请求 URL
        log(f"❌ Telegram 推送异常：{type(exc).__name__}")
        return False


# ================= 主程序 =================

def main():
    log("🚀 GLaDOS Checkin Starting...")

    cookies = get_cookies()

    if not cookies:
        return 1

    log(f"📋 共读取到 {len(cookies)} 个账号")

    target_plan = os.environ.get(
        "GLADOS_EXCHANGE_PLAN", "plan500"
    ).strip()

    if target_plan not in PLAN_REQUIREMENTS:
        log(f"❌ 不支持的兑换方案：{target_plan}")
        log("可选方案：plan100、plan200、plan500")
        return 1

    need_pts = PLAN_REQUIREMENTS[target_plan]
    log(f"🎁 自动兑换策略：{target_plan}，需要 {need_pts} 积分")

    results = []
    success_cnt = 0

    for index, cookie in enumerate(cookies, start=1):
        log("=" * 55)
        log(f"👤 开始处理账号 {index}/{len(cookies)}")

        g = GLaDOS(cookie)

        # ---------- 签到 ----------
        log("⏳ 正在提交签到请求...")
        checkin_result = g.checkin()

        if isinstance(checkin_result, dict):
            raw_message = str(
                checkin_result.get("message") or "接口未返回消息"
            )
            code = checkin_result.get("code", "未提供")

            log(f"📩 签到接口返回：code={code}")
            log(f"📩 原始消息：{raw_message}")
        else:
            raw_message = "未获取到有效响应，无法确认签到结果"
            log(f"❌ {raw_message}")

        if checkin_succeeded(checkin_result):
            success_cnt += 1
            checkin_label = "✅ 今日签到已完成"
        else:
            checkin_label = "❌ 未确认签到成功"

        log(checkin_label)

        # ---------- 查询账号信息 ----------
        log("⏳ 正在查询账号状态...")
        g.get_status()

        log("⏳ 正在查询积分...")
        points_ok = g.get_points()

        # ---------- 自动兑换 ----------
        if not points_ok or g.points is None:
            exchange_message = "未获取到有效积分，跳过自动兑换"

        elif g.points < need_pts:
            exchange_message = f"积分不足 ({g.points}/{need_pts})"

        else:
            log(f"🎁 积分满足要求，正在兑换：{target_plan}")
            exchange_result = g.exchange(target_plan)

            if isinstance(exchange_result, dict):
                exchange_message = str(
                    exchange_result.get("message") or "接口未返回兑换消息"
                )
                exchange_code = exchange_result.get("code", "未提供")

                log(
                    f"📩 兑换接口返回：code={exchange_code}，"
                    f"message={exchange_message}"
                )

                # 兑换请求后重新查询余额和剩余天数
                g.get_status()
                g.get_points()
            else:
                exchange_message = "未获取到兑换响应，兑换结果待确认"

        # ---------- 输出账号结果 ----------
        display_points = g.points if g.points is not None else "?"

        user_result = (
            f"👤 账号 {index}：{g.email}\n\n"
            f"当前积分: {display_points}\n\n"
            f"最近一次积分变动: {g.points_change}\n\n"
            f"剩余天数: {g.left_days} 天\n\n"
            f"签到结果: {checkin_label}\n\n"
            f"接口消息: {raw_message}\n\n"
            f"自动兑换: {exchange_message}\n\n"
            f"🎁 兑换选项:\n\n"
            f"{g.exchange_info}"
        )

        results.append(user_result)

        # 无论是否配置 Telegram，都打印完整结果
        log(
            f"\n{'=' * 55}\n"
            f"{user_result}\n"
            f"{'=' * 55}"
        )

    # ---------- 最终汇总 ----------
    total = len(cookies)
    unconfirmed_cnt = total - success_cnt

    title = f"GLaDOS签到: 成功{success_cnt}/{total}"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    log(f"📊 {title}")
    log(
        f"✅ 今日已签到：{success_cnt} 个；"
        f"❓ 未确认成功：{unconfirmed_cnt} 个"
    )

    # ---------- Telegram 推送 ----------
    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if tg_token and tg_chat_id:
        content = (
            "\n\n".join(results)
            + f"\n\n策略: {target_plan} | 时间: {current_time}"
        )
        telegram_push(tg_token, tg_chat_id, title, content)
    else:
        log("ℹ️ 未配置 Telegram，结果已输出到运行日志")

    log("🏁 运行结束")

    # 有账号未确认成功时，让 Actions 标记为失败，方便发现问题
    return 0 if success_cnt == total else 1


if __name__ == "__main__":
    sys.exit(main())
