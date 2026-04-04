#!/usr/bin/env python3
"""
AI反馈工具 - 简化版
支持CLI和Web模式，Web支持图片上传和粘贴
"""

import argparse
import warnings
from datetime import datetime

from feedback_web import collect_feedback_web

# 抑制Python警告
warnings.filterwarnings("ignore")


def collect_feedback_cli(summary: str = "", timeout: int = 600):
    """
    收集用户反馈 - CLI模式（简洁版）
    
    特性：
    - 直接输入多行反馈
    - 输入 end 结束
    
    Args:
        summary: AI工作摘要
        timeout: 超时时间（秒）
    
    Returns:
        反馈列表
    """
    # 打印标题
    print(f"\n{'='*60}")
    print("🤖 AI 助手等待用户反馈")
    print(f"{'='*60}")
    
    if summary:
        print(f"\n📋 工作摘要:\n   {summary}\n")
    
    print("💡 提示: 直接输入反馈内容，多行可继续输入，输入 end 结束")
    print(f"{'─'*60}\n")
    
    feedback_list = []
    
    try:
        while True:
            # 先用print显示提示符，确保在所有终端都能看到
            print("👉 ", end='', flush=True)
            user_input = input().rstrip()
            
            # 输入end结束
            if user_input.lower() == 'end':
                break
            
            # 记录反馈
            if user_input:
                feedback_list.append({
                    "type": "text",
                    "content": user_input,
                    "timestamp": datetime.now().isoformat()
                })
    
    except (KeyboardInterrupt, EOFError):
        pass
    
    # 结束显示
    print(f"\n{'='*60}")
    if feedback_list:
        print(f"✅ 已收集 {len(feedback_list)} 条反馈")
    else:
        print("⚠️  未收集到反馈")
    print(f"{'='*60}\n")
    
    return feedback_list


def collect_feedback_gui(summary: str = "", timeout: int = 600):
    """
    收集用户反馈 - Web模式
    支持文本输入、图片上传、图片粘贴

    Args:
        summary: AI工作摘要
        timeout: 超时时间（秒）

    Returns:
        反馈列表（图片返回绝对路径）
    """
    return collect_feedback_web(summary=summary, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(
        description="AI反馈工具 - 简化版",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # CLI模式
  python ai_feedback_tool_simple.py --cli --summary "完成了代码分析"
  
  # Web模式（支持图片上传和粘贴）
  python ai_feedback_tool_simple.py --gui --summary "完成了代码分析"
        """
    )
    
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--cli', action='store_true', help='使用命令行模式')
    mode_group.add_argument('--gui', action='store_true', help='使用Web模式（支持图片）')
    
    parser.add_argument('--summary', '-s', type=str, default='', help='AI工作摘要')
    parser.add_argument('--timeout', '-t', type=int, default=6000, help='超时时间（秒）')
    
    args = parser.parse_args()
    
    # 收集反馈
    if args.gui:
        feedback = collect_feedback_gui(summary=args.summary, timeout=args.timeout)
    else:
        feedback = collect_feedback_cli(summary=args.summary, timeout=args.timeout)
    
    # 输出反馈到stdout供AI终端接收
    if feedback:
        print("\n" + "="*60)
        print("📬 收到用户反馈:")
        print("="*60)
        for item in feedback:
            if item['type'] == 'text':
                print(f"💬 {item['content']}")
            elif item['type'] == 'image':
                print(f"🖼️ 图片: {item['content']}")
        print("="*60 + "\n")
    else:
        print("\n⚠️ 未收到反馈或用户取消\n")
    
    return feedback


if __name__ == "__main__":
    main()
