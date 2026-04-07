#!/usr/bin/env python3
"""
AI回饋工具 - 簡化版
支援CLI和Web模式，Web支援圖片上傳和貼上
"""

import argparse
import warnings
from datetime import datetime

from feedback_web import collect_feedback_web

# 抑制Python警告
warnings.filterwarnings("ignore")


def collect_feedback_cli(summary: str = "", timeout: int = 600):
    """
    收集使用者回饋 - CLI模式（簡潔版）
    
    特性：
    - 直接輸入多行回饋
    - 輸入 end 結束
    
    Args:
        summary: AI工作摘要
        timeout: 超時時間（秒）
    
    Returns:
        回饋清單
    """
    # 列印標題
    print(f"\n{'='*60}")
    print("🤖 AI 助手等待使用者回饋")
    print(f"{'='*60}")
    
    if summary:
        print(f"\n📋 工作摘要:\n   {summary}\n")
    
    print("💡 提示: 直接輸入回饋內容，多行可繼續輸入，輸入 end 結束")
    print(f"{'─'*60}\n")
    
    feedback_list = []
    
    try:
        while True:
            # 先用print顯示提示符，確保在所有終端都能看到
            print("👉 ", end='', flush=True)
            user_input = input().rstrip()
            
            # 輸入end結束
            if user_input.lower() == 'end':
                break
            
            # 記錄回饋
            if user_input:
                feedback_list.append({
                    "type": "text",
                    "content": user_input,
                    "timestamp": datetime.now().isoformat()
                })
    
    except (KeyboardInterrupt, EOFError):
        pass
    
    # 結束顯示
    print(f"\n{'='*60}")
    if feedback_list:
        print(f"✅ 已收集 {len(feedback_list)} 條回饋")
    else:
        print("⚠️  未收集到回饋")
    print(f"{'='*60}\n")
    
    return feedback_list


def collect_feedback_gui(summary: str = "", timeout: int = 600):
    """
    收集使用者回饋 - Web模式
    支援文字輸入、圖片上傳、圖片貼上

    Args:
        summary: AI工作摘要
        timeout: 超時時間（秒）

    Returns:
        回饋清單（圖片回傳絕對路徑）
    """
    return collect_feedback_web(summary=summary, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(
        description="AI回饋工具 - 簡化版",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # CLI模式
  python ai_feedback_tool_simple.py --cli --summary "完成了程式碼分析"
  
  # Web模式（支援圖片上傳和貼上）
  python ai_feedback_tool_simple.py --gui --summary "完成了程式碼分析"
        """
    )
    
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--cli', action='store_true', help='使用命令列模式')
    mode_group.add_argument('--gui', action='store_true', help='使用Web模式（支援圖片）')
    
    parser.add_argument('--summary', '-s', type=str, default='', help='AI工作摘要')
    parser.add_argument('--timeout', '-t', type=int, default=99999, help='超時時間（秒），0 代表無限制')
    
    args = parser.parse_args()
    
    # 收集回饋
    if args.gui:
        feedback = collect_feedback_gui(summary=args.summary, timeout=args.timeout)
    else:
        feedback = collect_feedback_cli(summary=args.summary, timeout=args.timeout)
    
    # 輸出回饋到stdout供AI終端接收
    if feedback:
        print("\n" + "="*60)
        print("📬 收到使用者回饋:")
        print("="*60)
        for item in feedback:
            if item['type'] == 'text':
                print(f"💬 {item['content']}")
            elif item['type'] == 'image':
                print(f"🖼️ 圖片: {item['content']}")
        print("="*60 + "\n")
    else:
        print("\n⚠️ 未收到回饋或使用者取消\n")
    
    return feedback


if __name__ == "__main__":
    main()
