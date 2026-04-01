"""
Koyeb 自动登录脚本 (GitHub 认证版)
- 登录页面: https://app.koyeb.com/auth/signin
- 服务列表页: https://app.koyeb.com/services        
- 使用 base.py 提供的 GitHub 登录、2FA 处理及 Cookie 自动保存
"""

import os
import time
from playwright.sync_api import sync_playwright
from base import BaseAutoLogin

# ==================== 配置 ====================
PROXY_DSN = os.environ.get("PROXY_DSN", "").strip()
KOYEB_SIGNIN_URL = "https://app.koyeb.com/auth/signin"
KOYEB_SERVICES_URL = "https://app.koyeb.com/services"

class KoyebAutoLogin(BaseAutoLogin):
    def __init__(self):
        super().__init__("koyeb")
        
    def keepalive(self, page):
        self.log("开始保活任务...", "STEP")
        page.goto(KOYEB_SERVICES_URL, timeout=60000)
        page.wait_for_load_state('networkidle', timeout=60000)
        self.shot(page, "services")
        
        self.log(f"准备进入服务详情页", "STEP")
        service_xpath = r'div.\\@container a.items-center'
        if self.click(page, service_xpath, "进入服务详情"):
            page.wait_for_load_state('networkidle')
            time.sleep(3)
            self.log(f"准备访问公网地址", "STEP")
            public_xpath = 'div.items-start a.truncate'
            self.click(page, public_xpath, "访问公网地址")
            time.sleep(5)
            self.shot(page, "final")
        else:
            self.log("未找到服务详情页", "ERROR")

    def notify(self, ok, err=""):
        msg = f"<b>🤖 {self.service_name} 自动任务</b>\n\n<b>状态:</b> {'✅ 成功' if ok else '❌ 失败'}\n<b>时间:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
        if err: msg += f"\n<b>错误:</b> {err}"
        msg += "\n\n<b>日志摘录:</b>\n" + "\n".join(self.logs[-5:])
        self.tg.send(msg)
        if self.shots: self.tg.photo(self.shots[-1], "最后状态")

    def run(self):
        self.log(f"GitHub 用户: {self.username}")
        if not self.username or not self.password:
            self.log("缺少 GH_USERNAME/GH_PASSWORD", "ERROR"); return

        with sync_playwright() as p:
            launch_args = self.get_launch_args(PROXY_DSN)
            browser = p.chromium.launch(**launch_args)
            context = browser.new_context(viewport={'width': 1280, 'height': 800}, user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36')
            page = context.new_page()

            try:
                self.inject_github_session(context)
                
                self.log(f"准备访问Koyeb登录页", "STEP")
                page.goto(KOYEB_SIGNIN_URL)
                page.wait_for_load_state('networkidle')
                self.shot(page, "start")
                
                # 点击 GitHub 登录按钮
                self.log(f"准备点击 GitHub 按钮", "STEP")
                if not self.click(page, ['a:has-text("GitHub")', '[data-method="github"]'], "GitHub 按钮"):
                    self.notify(False, "找不到 GitHub 按钮"); return

                # 等待 GitHub 登录页加载完成
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
                
                self.save_github_session(context)
                self.keepalive(page)
                self.notify(True)
                
            except Exception as e:
                self.log(f"异常: {e}", "ERROR")
                self.notify(False, str(e))
            finally:
                browser.close()

if __name__ == "__main__":
    KoyebAutoLogin().run()
