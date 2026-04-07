#!/usr/bin/env python3
"""
AI回饋工具 - 阻塞版本
完全抑制stderr輸出，包括libpng警告
"""

import sys
import os
import subprocess

def main():
    # 建構命令
    script_path = os.path.join(os.path.dirname(__file__), 'ai_feedback_tool_simple.py')
    cmd = [sys.executable, script_path] + sys.argv[1:]
    
    # 正常情況下保持安靜；如果子程序失敗，再把真實錯誤印出來
    result = subprocess.run(
        cmd,
        stderr=subprocess.PIPE,
        text=True,
        encoding='utf-8',
        errors='replace',
    )

    if result.returncode != 0:
        if result.stderr:
            sys.stderr.write(result.stderr)
        else:
            sys.stderr.write("ai_feedback_tool_simple.py 執行失敗，但沒有返回可見錯誤資訊。\n")
    
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
