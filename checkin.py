#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
2026 GLaDOS 自动签到 (排版修复终极版 - 补全信息+全行空行+话术统一)
"""

import requests
import json
import os
import sys
import time
from datetime import datetime

# 修复 Windows Unicode 输出问题
if sys.platform.startswith('win'):
    sys.stdout.reconfigure(encoding='utf-8')

# ================= 配置 =================

DOMAINS = [
    "https://glados.cloud",
    "https://railgun.info",
    "https://glados.rocks",
    "https://glados.network",
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Content-Type': 'application/json;charset=UTF-8',
    'Accept': 'application/json, text/plain, */*',
}

# ================= 工具函数 =================

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{ts}] {msg}")

def extract_cookie(raw: str):
    if not raw: return None
    raw = raw.strip()
    if 'koa:sess=' in raw or 'koa:sess.sig=' in raw:
        return raw
    if raw.startswith('{'):
        try:
            return 'koa.sess=' + json.loads(raw).get('token')
        except: pass
    if raw.count('.') == 2 and '=' not in raw and len(raw) > 50:
        return 'koa:sess=' + raw
    return raw

def get_cookies():
    raw = os.environ.get("GLADOS_COOKIE", "")
    if not raw:
        log("❌ 未配置 GLADOS_COOKIE")
        return []
    sep = '\n' if '\n' in raw else '&'
    return [extract_cookie(c) for c in raw.split(sep) if c.strip()]

# ================= 核心逻辑 =================

class GLaDOS:
    def __init__(self, cookie):
        self.cookie = cookie
        self.domain = DOMAINS[0]
        self.email = "?"
        self.left_days = "?"
        self.points = "0"
        self.points_change = "?"
        self.exchange_info = ""
        
    def req(self, method, path, data=None):
        for d in DOMAINS:
            try:
                url = f"{d}{path}"
                h = HEADERS.copy()
                h['Cookie'] = self.cookie
                h['Origin'] = d
                h['Referer'] = f"{d}/console/checkin"
                
                if method == 'GET':
                    resp = requests.get(url, headers=h, timeout=10)
                else:
                    resp = requests.post(url, headers=h, json=data, timeout=10)
                
                if resp.status_code == 200:
                    self.domain = d
                    return resp.json()
            except Exception as e:
                log(f"⚠️ {d} 请求失败: {e}")
                continue
        return None

    def get_status(self):
        res = self.req('GET', '/api/user/status')
        if res and 'data' in res:
            d = res['data']
            self.email = d.get('email', 'Unknown')
            self.left_days = str(d.get('leftDays', '?')).split('.')[0]
            return True
        return False

    def get_points(self):
        res = self.req('GET', '/api/user/points')
        if res and 'points' in res:
            self.points = str(res.get('points', '0')).split('.')[0]
            history = res.get('history', [])
            if history:
                last = history[0]
                change = str(last.get('change', '0')).split('.')[0]
                if not change.startswith('-'): change = '+' + change
                self.points_change = change
            
            plans = res.get('plans', {})
            pts = int(self.points)
            exchange_lines = []
            sorted_plans = sorted(plans.items(), key=lambda x: x[1]['points'])
            
            for plan_id, plan_data in sorted_plans:
                need = plan_data['points']
                days = plan_data['days']
                status = "✅" if pts >= need else "❌"
                desc = "(可兑换)" if pts >= need else f"(差{need-pts}分)"
                exchange_lines.append(f"{status} {need}分→{days}天 {desc}")
            
            self.exchange_info = "\n".join(exchange_lines)
            return True
        return False

    def checkin(self):
        return self.req('POST', '/api/user/checkin', {'token': 'glados.cloud'})

    def exchange(self, plan):
        return self.req('POST', '/api/user/exchange', {'planType': plan})

# ================= 推送函数 =================

def telegram_push(token, chat_id, title, content):
    if not token or not chat_id: return
    try:
        import re
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        # 标题与第一个用户名之间空一行
        text = f"<b>{title}</b>\n\n{content}"
        # 彻底移除所有残留的 HTML 标签（保留粗体）
        text = re.sub(r"<(?!\/?(b)\b)[^>]+>", "", text)
        
        data = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        requests.post(url, json=data, timeout=5)
        log("✅ Telegram 推送成功")
    except Exception as e:
        log(f"❌ Telegram 推送失败: {e}")

# ================= 主程序 =================

def main():
    log("🚀 GLaDOS Checkin Starting...")
    cookies = get_cookies()
    if not cookies: sys.exit(1)
    
    target_plan = os.environ.get("GLADOS_EXCHANGE_PLAN", "plan500")
    plan_requirements = {"plan100": 100, "plan200": 200, "plan500": 500}
    need_pts = plan_requirements.get(target_plan, 500)
    
    results = []
    success_cnt = 0
    
    for cookie in cookies:
        g = GLaDOS(cookie)
        checkin_res = g.checkin()
        g.get_status()
        g.get_points()
        
        # 话术处理：如果已经签到过，统一输出长话术
        raw_msg = checkin_res.get('message', 'Failure') if checkin_res else "Network Error"
        if "observation logged" in raw_msg:
            msg = "Today's observation logged. Return tomorrow for more points."
        else:
            msg = raw_msg

        current_pts = int(g.points)
        exchange_msg = f"积分不足 ({current_pts}/{need_pts})"
        if current_pts >= need_pts:
            ex_res = g.exchange(target_plan)
            exchange_msg = ex_res.get('message', '提交失败')
            g.get_status()
            g.get_points()

        success_cnt += 1
        
        # 全行空行排版
        user_result = (
            f"👤 {g.email}\n\n"
            f"当前积分: {g.points} ({g.points_change})\n\n"
            f"剩余天数: {g.left_days} 天\n\n"
            f"签到结果: {msg}\n\n"
            f"自动兑换: {exchange_msg}\n\n"
            f"🎁 兑换选项:\n\n"
            f"{g.exchange_info}"
        )
        results.append(user_result)

    tg_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    tg_chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    
    if tg_token and tg_chat_id:
        title = f"GLaDOS签到: 成功{success_cnt}/{len(cookies)}"
        cur_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        content = "\n\n".join(results) + f"\n\n策略: {target_plan} | 时间: {cur_time}"
        telegram_push(tg_token, tg_chat_id, title, content)

if __name__ == '__main__':
    main()
