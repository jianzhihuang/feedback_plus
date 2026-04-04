#!/usr/bin/env python3
"""
AI反馈工具 - 阻塞版本
完全抑制stderr输出，包括libpng警告
"""

import sys
import os
import subprocess

def main():
    # 构建命令
    script_path = os.path.join(os.path.dirname(__file__), 'ai_feedback_tool_simple.py')
    cmd = [sys.executable, script_path] + sys.argv[1:]
    
    # 正常情况下保持安静；如果子进程失败，再把真实错误打印出来
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
            sys.stderr.write("ai_feedback_tool_simple.py 执行失败，但没有返回可见错误信息。\n")
    
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
