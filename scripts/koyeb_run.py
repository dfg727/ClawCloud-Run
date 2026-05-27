"""
Koyeb 自动登录脚本 (GitHub 认证版)
- 登录页面: https://app.koyeb.com/auth/signin
- 服务列表页: https://app.koyeb.com/services        
- 使用 base.py 提供的 GitHub 登录、2FA 处理及 Cookie 自动保存
"""

import os
import sys
import time
from playwright.sync_api import sync_playwright
from base import BaseAutoLogin
from generate_sign import generate_sign

# ==================== 配置 ====================
PROXY_DSN = os.environ.get("PROXY_DSN", "").strip()
KOYEB_SIGNIN_URL = "https://app.koyeb.com/auth/signin"
KOYEB_SERVICES_URL = "https://app.koyeb.com/services"

# ============================================================
#  Webhook 重试链接生成
# ============================================================
_HOOK_BASE = "https://aa.94sub.qzz.io/hook"
_HOOK_ACCESS_KEY = "123"
_HOOK_USER = "dfg727"
_HOOK_REPO = "ClawCloud-Run"
_HOOK_WORKFLOW = "keep-alive-renew.yml"


def build_retry_url() -> str:
    """生成带签名的 Webhook 重试链接"""
    ts, sign = generate_sign()
    param = f"{ts}|{sign}|{_HOOK_USER}|{_HOOK_REPO}|{_HOOK_WORKFLOW}"
    return f"{_HOOK_BASE}?access_key={_HOOK_ACCESS_KEY}&param={param}"

class KoyebAutoLogin(BaseAutoLogin):
    def __init__(self):
        super().__init__("koyeb")
        
    def keepalive(self, page):
        self.log("开始保活任务...", "STEP")
        page.goto(KOYEB_SERVICES_URL, timeout=60*1000)
        page.wait_for_load_state('networkidle', timeout=60*1000)
        self.shot(page, "services")
        
        self.log(f"准备进入服务详情页", "STEP")
        # 修正选择器：CSS 中的 @ 需要转义，r'...' 原始字符串中只需要一个反斜杠
        # 另外增加一个通用的 a[href^="/services/"] 作为回退，提高鲁棒性
        service_sels = [
            r'div.grid a.items-center', 
            'a[href^="/services/93"].items-center'
        ]
        if self.click(page, service_sels, "进入服务详情"):
            page.wait_for_load_state('networkidle')
            time.sleep(3)
            self.log(f"准备访问公网地址", "STEP")
            public_sels = ['div.items-start a.truncate', 'a[href*=".koyeb.app"]']
            self.click(page, public_sels, "访问公网地址")
            time.sleep(5)
            self.shot(page, "final")
        else:
            self.log("未找到服务详情页", "ERROR")

    def notify(self, ok, err=""):
        msg = f"<b>🤖 {self.service_name} 自动任务</b>\n\n<b>状态:</b> {'✅ 成功' if ok else '❌ 失败'}\n<b>时间:</b> {time.strftime('%Y-%m-%d %H:%M:%S')}"
        if err: msg += f"\n<b>错误:</b> {err}"
        msg += "\n\n<b>日志摘录:</b>\n" + "\n".join(self.logs[-5:])
        if not ok:
            msg += f"\n\n🔁 重试链接: {build_retry_url()}"
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
                self.log(f"等待 GitHub 登录页加载完成", "STEP")
                if 'github.com/login' in page.url or 'github.com/session' in page.url:
                    if not self.login_github(page):
                        self.notify(False, "GitHub 登录失败"); return
                
                # 处理 OAuth 授权
                self.log(f"准备处理 OAuth 授权", "STEP")
                if 'github.com/login/oauth/authorize' in page.url:
                    self.click(page, 'button[name="authorize"]', "OAuth 授权")
                
                # 等待进入 Koyeb 控制台
                self.log(f"等待进入 Koyeb 控制台", "STEP")
                page.wait_for_url(lambda u: 'koyeb.com' in u and 'signin' not in u, timeout=60000)
                self.log("成功进入 Koyeb", "SUCCESS")
                self.shot(page, "登录成功")
                
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
