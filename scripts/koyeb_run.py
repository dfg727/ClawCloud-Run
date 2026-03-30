"""
Koyeb 自动登录脚本 (GitHub 认证版)
- 登录页面: https://app.koyeb.com/auth/signin
- 服务列表页: https://app.koyeb.com/services        
- 参考 clawcloud.py 实现 GitHub 登录、2FA 处理及 Cookie 自动保存
"""

import base64
import os
import random
import re
import sys
import time
from urllib.parse import urlparse

import requests
from playwright.sync_api import sync_playwright

# ==================== 配置 ====================
PROXY_DSN = os.environ.get("PROXY_DSN", "").strip()
KOYEB_SIGNIN_URL = "https://app.koyeb.com/auth/signin"
KOYEB_SERVICES_URL = "https://app.koyeb.com/services"

DEVICE_VERIFY_WAIT = 30  
TWO_FACTOR_WAIT = int(os.environ.get("TWO_FACTOR_WAIT", "120"))

class Telegram:
    """Telegram 通知"""
    def __init__(self):
        self.token = os.environ.get('TG_BOT_TOKEN')
        self.chat_id = os.environ.get('TG_CHAT_ID')
        self.ok = bool(self.token and self.chat_id)
    
    def send(self, msg):
        if not self.ok: return
        try:
            requests.post(f"https://api.telegram.org/bot{self.token}/sendMessage",
                        data={"chat_id": self.chat_id, "text": msg, "parse_mode": "HTML"}, timeout=30)
        except: pass
    
    def photo(self, path, caption=""):
        if not self.ok or not os.path.exists(path): return
        try:
            with open(path, 'rb') as f:
                requests.post(f"https://api.telegram.org/bot{self.token}/sendPhoto",
                            data={"chat_id": self.chat_id, "caption": caption[:1024]},
                            files={"photo": f}, timeout=60)
        except: pass
    
    def flush_updates(self):
        if not self.ok: return 0
        try:
            r = requests.get(f"https://api.telegram.org/bot{self.token}/getUpdates", params={"timeout": 0}, timeout=10)
            data = r.json()
            if data.get("ok") and data.get("result"):
                return data["result"][-1]["update_id"] + 1
        except: pass
        return 0
    
    def wait_code(self, timeout=120):
        if not self.ok: return None
        offset = self.flush_updates()
        deadline = time.time() + timeout
        pattern = re.compile(r"^/code\s+(\d{6,8})$")
        while time.time() < deadline:
            try:
                r = requests.get(f"https://api.telegram.org/bot{self.token}/getUpdates",
                               params={"timeout": 20, "offset": offset}, timeout=30)
                data = r.json()
                if not data.get("ok"):
                    time.sleep(2); continue
                for upd in data.get("result", []):
                    offset = upd["update_id"] + 1
                    msg = upd.get("message") or {}
                    chat = msg.get("chat") or {}
                    if str(chat.get("id")) != str(self.chat_id): continue
                    text = (msg.get("text") or "").strip()
                    m = pattern.match(text)
                    if m: return m.group(1)
            except: pass
            time.sleep(2)
        return None

class SecretUpdater:
    """GitHub Secret 更新器"""
    def __init__(self):
        self.token = os.environ.get('REPO_TOKEN')
        self.repo = os.environ.get('GITHUB_REPOSITORY')
        self.ok = bool(self.token and self.repo)
    
    def update(self, name, value):
        if not self.ok: return False
        try:
            from nacl import encoding, public
            headers = {"Authorization": f"token {self.token}", "Accept": "application/vnd.github.v3+json"}
            r = requests.get(f"https://api.github.com/repos/{self.repo}/actions/secrets/public-key", headers=headers, timeout=30)
            if r.status_code != 200: return False
            key_data = r.json()
            pk = public.PublicKey(key_data['key'].encode(), encoding.Base64Encoder())
            encrypted = public.SealedBox(pk).encrypt(value.encode())
            r = requests.put(f"https://api.github.com/repos/{self.repo}/actions/secrets/{name}",
                           headers=headers, json={"encrypted_value": base64.b64encode(encrypted).decode(), "key_id": key_data['key_id']}, timeout=30)
            return r.status_code in [201, 204]
        except: return False

class KoyebAutoLogin:
    def __init__(self):
        self.username = os.environ.get('GH_USERNAME')
        self.password = os.environ.get('GH_PASSWORD')
        self.gh_session = os.environ.get('GH_SESSION_KOYEB', '').strip()
        self.tg = Telegram()
        self.secret = SecretUpdater()
        self.logs = []
        self.shots = []
        self.n = 0
        
    def log(self, msg, level="INFO"):
        icons = {"INFO": "ℹ️", "SUCCESS": "✅", "ERROR": "❌", "WARN": "⚠️", "STEP": "🔹"}
        line = f"{icons.get(level, '•')} {msg}"
        print(line)
        self.logs.append(line)
    
    def shot(self, page, name):
        self.n += 1
        os.makedirs("screenshots", exist_ok=True)
        f = f"screenshots/{self.n:02d}_{name}.png"
        try:
            page.screenshot(path=f)
            self.shots.append(f)
        except: pass
        return f

    def click(self, page, sels, desc=""):
        if isinstance(sels, str): sels = [sels]
        for s in sels:
            try:
                el = page.locator(s).first
                if el.is_visible(timeout=3000):
                    time.sleep(random.uniform(0.5, 1.5))
                    el.hover()
                    time.sleep(random.uniform(0.2, 0.5))
                    el.click()
                    self.log(f"已点击: {desc}", "SUCCESS")
                    return True
            except: pass
        return False

    def wait_device(self, page):
        self.log(f"需要设备验证，等待 {DEVICE_VERIFY_WAIT} 秒...", "WARN")
        self.shot(page, "设备验证")
        self.tg.send("⚠️ <b>需要设备验证</b>\n\n请在邮箱或 GitHub App 批准。")
        for i in range(DEVICE_VERIFY_WAIT):
            time.sleep(1)
            if "verified-device" not in page.url and "device-verification" not in page.url:
                self.log("设备验证通过！", "SUCCESS")
                return True
            try:
                page.reload(timeout=10000)
                page.wait_for_load_state('networkidle', timeout=10000)
            except: pass
        return False

    def wait_two_factor_mobile(self, page):
        self.log(f"需要 GitHub Mobile 验证，等待 {TWO_FACTOR_WAIT} 秒...", "WARN")
        shot = self.shot(page, "2fa_mobile")
        self.tg.send(f"⚠️ <b>GitHub Mobile 验证</b>\n等待时间：{TWO_FACTOR_WAIT}s")
        if shot: self.tg.photo(shot, "2FA 数字")
        for i in range(TWO_FACTOR_WAIT):
            time.sleep(1)
            if "github.com/sessions/two-factor/" not in page.url:
                self.log("两步验证通过！", "SUCCESS")
                return True
            if "github.com/login" in page.url: return False
            if i % 30 == 0 and i != 0:
                try: page.reload(timeout=30000); page.wait_for_load_state('domcontentloaded')
                except: pass
        return False

    def handle_2fa_code_input(self, page):
        self.log("需要输入验证码", "WARN")
        shot = self.shot(page, "2fa_code")
        self.tg.send(f"🔐 <b>需要验证码登录</b>\n请发送：<code>/code 123456</code>\n等待：{TWO_FACTOR_WAIT}s")
        if shot: self.tg.photo(shot, "2FA 页面")
        code = self.tg.wait_code(timeout=TWO_FACTOR_WAIT)
        if not code: return False
        self.log("收到验证码，填入中...", "SUCCESS")
        selectors = ['input[autocomplete="one-time-code"]', 'input[name="app_otp"]', 'input#app_totp']
        for sel in selectors:
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=2000):
                    el.type(code, delay=100)
                    page.keyboard.press("Enter")
                    time.sleep(3)
                    return "github.com/sessions/two-factor/" not in page.url
            except: pass
        return False

    def login_github(self, page):
        self.log("登录 GitHub...", "STEP")
        try:
            page.fill('input[name="login"]', self.username)
            page.fill('input[name="password"]', self.password)
            page.click('input[type="submit"]')
            time.sleep(3)
            page.wait_for_load_state('networkidle', timeout=30000)
            
            if 'verified-device' in page.url or 'device-verification' in page.url:
                if not self.wait_device(page): return False
            
            if 'two-factor' in page.url:
                if 'two-factor/mobile' in page.url:
                    if not self.wait_two_factor_mobile(page): return False
                else:
                    if not self.handle_2fa_code_input(page): return False
            return True
        except Exception as e:
            self.log(f"GitHub 登录异常: {e}", "ERROR")
            return False

    def save_cookie(self, context):
        try:
            for c in context.cookies():
                if c['name'] == 'user_session' and 'github' in c.get('domain', ''):
                    val = c['value']
                    if self.secret.update('GH_SESSION_KOYEB', val):
                        self.log("GH_SESSION_KOYEB 已自动更新", "SUCCESS")
                        self.tg.send("🔑 <b>Cookie 已自动更新</b>")
                    else:
                        self.tg.send(f"🔑 <b>新 Cookie</b>\n<tg-spoiler>{val}</tg-spoiler>")
                    return True
        except: pass
        return False

    def keepalive(self, page):
        self.log("保活任务...", "STEP")
        page.goto(KOYEB_SERVICES_URL, timeout=60000)
        page.wait_for_load_state('networkidle', timeout=60000)
        self.shot(page, "services")
        service_xpath = '//*[@id="root"]/div[2]/div[2]/main/div/div[3]/div/div[2]/div/div[1]/div[1]/a'
        if self.click(page, service_xpath, "进入服务详情"):
            page.wait_for_load_state('networkidle')
            time.sleep(3)
            public_xpath = '//*[@id="root"]/div[2]/div[2]/main/div/div[1]/div[1]/div/div[2]/a'
            self.click(page, public_xpath, "访问公网地址")
            time.sleep(5)
            self.shot(page, "final")

    def notify(self, ok, err=""):
        msg = f"<b>🤖 Koyeb 自动任务</b>\n\n<b>状态:</b> {'✅ 成功' if ok else '❌ 失败'}\n<b>时间:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
        if err: msg += f"\n<b>错误:</b> {err}"
        msg += "\n\n<b>日志摘录:</b>\n" + "\n".join(self.logs[-5:])
        self.tg.send(msg)
        if self.shots: self.tg.photo(self.shots[-1], "最后状态")

    def run(self):
        self.log(f"GitHub 用户: {self.username}")
        if not self.username or not self.password:
            self.log("缺少 GH_USERNAME/GH_PASSWORD", "ERROR"); return

        with sync_playwright() as p:
            launch_args = {"headless": True, "args": ['--no-sandbox', '--disable-blink-features=AutomationControlled']}
            if PROXY_DSN:
                try:
                    u = urlparse(PROXY_DSN)
                    launch_args["proxy"] = {"server": f"{u.scheme}://{u.hostname}:{u.port}"}
                    if u.username: launch_args["proxy"]["username"] = u.username; launch_args["proxy"]["password"] = u.password
                except: pass

            browser = p.chromium.launch(**launch_args)
            context = browser.new_context(viewport={'width': 1280, 'height': 800}, user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')
            page = context.new_page()

            try:
                if self.gh_session:
                    context.add_cookies([{'name': 'user_session', 'value': self.gh_session, 'domain': 'github.com', 'path': '/'}, {'name': 'logged_in', 'value': 'yes', 'domain': 'github.com', 'path': '/'}])
                
                page.goto(KOYEB_SIGNIN_URL)
                page.wait_for_load_state('networkidle')
                self.shot(page, "start")
                
                # 点击 GitHub 登录
                if not self.click(page, ['a:has-text("GitHub")', '[data-method="github"]'], "GitHub 按钮"):
                    self.notify(False, "找不到 GitHub 按钮"); return

                time.sleep(3)
                if 'github.com/login' in page.url or 'github.com/session' in page.url:
                    if not self.login_github(page):
                        self.notify(False, "GitHub 登录失败"); return
                
                # 处理 OAuth 授权
                if 'github.com/login/oauth/authorize' in page.url:
                    self.click(page, 'button[name="authorize"]', "OAuth 授权")
                
                # 等待进入 Koyeb 控制台
                page.wait_for_url(lambda u: 'koyeb.com/services' in u or 'koyeb.com/' in u, timeout=60000)
                self.log("成功进入 Koyeb", "SUCCESS")
                
                self.save_cookie(context)
                self.keepalive(page)
                self.notify(True)
                
            except Exception as e:
                self.log(f"异常: {e}", "ERROR")
                self.notify(False, str(e))
            finally:
                browser.close()

if __name__ == "__main__":
    KoyebAutoLogin().run()
