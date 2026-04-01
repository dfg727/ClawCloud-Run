"""
自动续期总入口
- 调用 ClawCloud 自动登录
- 调用 Koyeb 自动登录
"""

import sys
import os

# 将当前目录添加到 sys.path 以便导入 scripts 目录下的模块
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from clawcloud_run import ClawCloudAutoLogin
from koyeb_run import KoyebAutoLogin

def run_all():
    print("\n" + "="*50)
    print("🚀 开始执行所有自动续期任务")
    print("="*50 + "\n")
    
    # 执行 ClawCloud
    print("\n🔹 [1/2] 开始 ClawCloud 任务")
    try:
        ClawCloudAutoLogin().run()
    except Exception as e:
        print(f"❌ ClawCloud 任务执行失败: {e}")
        
    # 执行 Koyeb
    print("\n🔹 [2/2] 开始 Koyeb 任务")
    try:
        KoyebAutoLogin().run()
    except Exception as e:
        print(f"❌ Koyeb 任务执行失败: {e}")
        
    print("\n" + "="*50)
    print("✨ 所有任务执行完毕")
    print("="*50 + "\n")

if __name__ == "__main__":
    run_all()
