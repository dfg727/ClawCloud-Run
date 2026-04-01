"""
ClawCloud 自动登录脚本
- 自动检测区域跳转（如 ap-southeast-1.console.claw.cloud）
- 使用 base.py 提供的 GitHub 登录、2FA 处理及 Cookie 自动保存
"""

import os
import random
import re
import sys
import time
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright
from base import BaseAutoLogin

# ==================== 配置 ====================
PROXY_DSN = os.environ.get("PROXY_DSN", "").strip()
LOGIN_ENTRY_URL = "https://us-east-1.run.claw.cloud/login"
SIGNIN_URL = f"{LOGIN_ENTRY_URL}/signin"

class ClawCloudAutoLogin(BaseAutoLogin):
    def __init__(self):
        super().__init__("clawcloud")
        self.detected_region = 'us-east-1'
        self.region_base_url = 'https://us-east-1.run.claw.cloud'
        
    def detect_region(self, url):
        try:
            parsed = urlparse(url)
            host = parsed.netloc
            if host.endswith('.console.claw.cloud'):
                region = host.replace('.console.claw.cloud', '')
                if region and region != 'console':
                    self.detected_region = region
                    self.region_base_url = f"https://{host}"
                    self.log(f"检测到区域: {region}", "SUCCESS")
                    return region
            if 'console.run.claw.cloud' in host or 'claw.cloud' in host:
                path = parsed.path
                region_match = re.search(r'/(?:region|r)/([a-z]+-[a-z]+-\d+)', path)
                if region_match:
                    region = region_match.group(1)
                    self.detected_region = region
                    self.region_base_url = f"https://{region}.console.claw.cloud"
                    self.log(f"从路径检测到区域: {region}", "SUCCESS")
                    return region
            self.region_base_url = f"{parsed.scheme}://{parsed.netloc}"
            return None
        except Exception as e:
            self.log(f"区域检测异常: {e}", "WARN")
            return None

    def oauth(self, page):
        if 'github.com/login/oauth/authorize' in page.url:
            self.log("处理 OAuth...", "STEP")
            self.shot(page, "oauth")
            self.click(page, ['button[name="authorize"]', 'button:has-text("Authorize")'], "授权")
            time.sleep(3)
            page.wait_for_load_state('networkidle', timeout=30000)

    def wait_redirect(self, page, wait=60):
        self.log("等待重定向...", "STEP")
        for i in range(wait):
            url = page.url
            if 'claw.cloud' in url and 'signin' not in url.lower():
                self.log("重定向成功！", "SUCCESS")
                self.detect_region(url)
                return True
            if 'github.com/login/oauth/authorize' in url:
                self.oauth(page)
            time.sleep(1)
        self.log("重定向超时", "ERROR")
        return False

    def keepalive(self, page):
        self.log("保活...", "STEP")
        base_url = self.region_base_url or LOGIN_ENTRY_URL
        pages_to_visit = [(f"{base_url}/", "控制台"), (f"{base_url}/apps", "应用")]
        for url, name in pages_to_visit:
            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state('networkidle', timeout=15000)
                self.log(f"已访问: {name} ({url})", "SUCCESS")
                if 'claw.cloud' in page.url: self.detect_region(page.url)
                time.sleep(2)
            except Exception as e:
                self.log(f"访问 {name} 失败: {e}", "WARN")
        self.shot(page, "完成")

    def notify(self, ok, err=""):
        region_info = f"\n<b>区域:</b> {self.detected_region or '默认'}" if self.detected_region else ""
        msg = f"<b>🤖 {self.service_name} 自动登录</b>\n\n<b>状态:</b> {'✅ 成功' if ok else '❌ 失败'}\n<b>用户:</b> {self.username}{region_info}\n<b>时间:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
        if err: msg += f"\n<b>错误:</b> {err}"
        msg += "\n\n<b>日志:</b>\n" + "\n".join(self.logs[-6:])
        self.tg.send(msg)
        if self.shots: self.tg.photo(self.shots[-1], "完成")

    def run(self):
        self.log(f"用户名: {self.username}")
        if not self.username or not self.password:
            self.log("缺少凭据", "ERROR"); self.notify(False, "凭据未配置"); return

        with sync_playwright() as p:
            launch_args = self.get_launch_args(PROXY_DSN)
            browser = p.chromium.launch(**launch_args)
            context = browser.new_context(viewport={'width': 1920, 'height': 1080}, user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')
            page = context.new_page()

            try:
                self.inject_github_session(context)
                self.log("步骤1: 打开 ClawCloud 登录页", "STEP")
                page.goto(SIGNIN_URL, timeout=60000)
                page.wait_for_load_state('networkidle', timeout=60000)
                time.sleep(2)
                self.shot(page, "clawcloud")
                
                self.log("步骤2: 点击 GitHub", "STEP")
                if not self.click(page, ['button:has-text("GitHub")', 'a:has-text("GitHub")', '[data-provider="github"]'], "GitHub"):
                    self.notify(False, "找不到 GitHub 按钮"); return
                
                time.sleep(3)
                page.wait_for_load_state('networkidle', timeout=120000)
                url = page.url

                if 'signin' not in url.lower() and 'claw.cloud' in url and 'github.com' not in url:
                    self.log("已自动登录！", "SUCCESS")
                    self.detect_region(url)
                else:
                    self.log("步骤3: GitHub 认证", "STEP")
                    if 'github.com/login' in url or 'github.com/session' in url:
                        if not self.login_github(page):
                            self.notify(False, "GitHub 登录失败"); return
                    elif 'github.com/login/oauth/authorize' in url:
                        self.log("Cookie 有效", "SUCCESS")
                        self.oauth(page)
                    
                    if not self.wait_redirect(page):
                        self.notify(False, "重定向失败"); return

                self.keepalive(page)
                self.save_github_session(context)
                self.notify(True)
                
            except Exception as e:
                self.log(f"异常: {e}", "ERROR")
                self.notify(False, str(e))
            finally:
                browser.close()

if __name__ == "__main__":
    ClawCloudAutoLogin().run()
