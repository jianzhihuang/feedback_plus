#!/usr/bin/env python3
"""
AI反馈工具 - 简化版
支持CLI和GUI模式，GUI支持图片上传和粘贴
"""

import sys
import os

# GUI模式下重定向底层stderr文件描述符，彻底抑制libpng C库警告
_original_stderr_fd = None
if '--gui' in sys.argv:
    try:
        # 保存原始stderr文件描述符
        _original_stderr_fd = os.dup(2)
        # 打开null设备
        if os.name == 'nt':  # Windows
            _devnull = os.open('nul', os.O_WRONLY)
        else:  # Linux/Mac
            _devnull = os.open('/dev/null', os.O_WRONLY)
        # 将stderr文件描述符重定向到null设备
        os.dup2(_devnull, 2)
        os.close(_devnull)
    except OSError:
        _original_stderr_fd = None

import argparse
import warnings
from datetime import datetime
from pathlib import Path

# 抑制Python警告
warnings.filterwarnings("ignore")


def restore_stderr():
    """恢复原始stderr，便于输出真实异常"""
    global _original_stderr_fd
    if _original_stderr_fd is not None:
        os.dup2(_original_stderr_fd, 2)
        os.close(_original_stderr_fd)
        _original_stderr_fd = None


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
    收集用户反馈 - GUI模式
    支持文本输入、图片上传、图片粘贴
    
    Args:
        summary: AI工作摘要
        timeout: 超时时间（秒）
    
    Returns:
        反馈列表（图片返回绝对路径）
    """
    try:
        import tkinter as tk
        from tkinter import ttk, scrolledtext, messagebox, filedialog
        import tkinter.font as tkfont

        from PIL import Image, ImageGrab
        
        # 抑制PIL的libpng警告
        import logging
        logging.getLogger('PIL').setLevel(logging.ERROR)
        
    except ImportError:
        return collect_feedback_cli(summary, timeout)
    
    feedback_list = []
    image_counter = 0
    current_dir = os.getcwd()
    
    # 创建feedback子目录用于保存图片
    feedback_dir = os.path.join(current_dir, "feedback")
    if not os.path.exists(feedback_dir):
        os.makedirs(feedback_dir)
    
    root = tk.Tk()
    root.title("AI助手请求用户反馈")
    root.geometry("920x760")
    root.minsize(760, 620)

    def handle_callback_exception(exc_type, exc_value, exc_traceback):
        """让GUI回调异常至少能显示出来，而不是被静默吞掉"""
        import traceback

        restore_stderr()
        traceback.print_exception(exc_type, exc_value, exc_traceback)
        messagebox.showerror("错误", f"GUI 发生未处理异常:\n{exc_value}")

    root.report_callback_exception = handle_callback_exception

    colors = {
        "app_bg": "#EEF3F9",
        "hero_bg": "#183B56",
        "hero_subtle": "#B8CCE0",
        "card_bg": "#FFFFFF",
        "card_border": "#D4DEEA",
        "input_bg": "#F8FBFE",
        "muted_bg": "#F2F6FA",
        "text_primary": "#17324D",
        "text_secondary": "#60758A",
        "accent": "#2E74B5",
        "accent_active": "#245D91",
        "accent_soft": "#DCEBFA",
        "danger": "#C25454",
        "danger_active": "#A64141",
    }

    root.configure(bg=colors["app_bg"])

    available_fonts = {font.lower() for font in tkfont.families(root)}

    def pick_font(*candidates):
        for candidate in candidates:
            if candidate.lower() in available_fonts:
                return candidate
        return "TkDefaultFont"

    base_font_family = pick_font(
        "Segoe UI",
        "Microsoft JhengHei UI",
        "PingFang TC",
        "PingFang SC",
        "Helvetica",
        "Arial",
    )
    title_font = (base_font_family, 18, "bold")
    section_font = (base_font_family, 11, "bold")
    body_font = (base_font_family, 10)
    hint_font = (base_font_family, 9)

    style = ttk.Style(root)
    if "clam" in style.theme_names():
        style.theme_use("clam")

    style.configure("Primary.TButton", font=(base_font_family, 10, "bold"), padding=(16, 10))
    style.map(
        "Primary.TButton",
        foreground=[("active", "#FFFFFF"), ("pressed", "#FFFFFF")],
        background=[("active", colors["accent_active"]), ("pressed", colors["accent_active"])],
        bordercolor=[("active", colors["accent_active"]), ("pressed", colors["accent_active"])],
        lightcolor=[("active", colors["accent_active"]), ("pressed", colors["accent_active"])],
        darkcolor=[("active", colors["accent_active"]), ("pressed", colors["accent_active"])],
    )
    style.configure(
        "Primary.TButton",
        foreground="#FFFFFF",
        background=colors["accent"],
        bordercolor=colors["accent"],
        lightcolor=colors["accent"],
        darkcolor=colors["accent"],
        focusthickness=0,
        focuscolor=colors["accent"],
    )

    style.configure("Secondary.TButton", font=(base_font_family, 10), padding=(16, 10))
    style.map(
        "Secondary.TButton",
        foreground=[("active", colors["text_primary"]), ("pressed", colors["text_primary"])],
        background=[("active", "#E8EFF7"), ("pressed", "#E8EFF7")],
        bordercolor=[("active", colors["card_border"]), ("pressed", colors["card_border"])],
        lightcolor=[("active", "#E8EFF7"), ("pressed", "#E8EFF7")],
        darkcolor=[("active", "#E8EFF7"), ("pressed", "#E8EFF7")],
    )
    style.configure(
        "Secondary.TButton",
        foreground=colors["text_primary"],
        background="#FFFFFF",
        bordercolor=colors["card_border"],
        lightcolor="#FFFFFF",
        darkcolor="#FFFFFF",
        focusthickness=0,
        focuscolor=colors["card_border"],
    )

    style.configure("Danger.TButton", font=(base_font_family, 10), padding=(16, 10))
    style.map(
        "Danger.TButton",
        foreground=[("active", "#FFFFFF"), ("pressed", "#FFFFFF")],
        background=[("active", colors["danger_active"]), ("pressed", colors["danger_active"])],
        bordercolor=[("active", colors["danger_active"]), ("pressed", colors["danger_active"])],
        lightcolor=[("active", colors["danger_active"]), ("pressed", colors["danger_active"])],
        darkcolor=[("active", colors["danger_active"]), ("pressed", colors["danger_active"])],
    )
    style.configure(
        "Danger.TButton",
        foreground="#FFFFFF",
        background=colors["danger"],
        bordercolor=colors["danger"],
        lightcolor=colors["danger"],
        darkcolor=colors["danger"],
        focusthickness=0,
        focuscolor=colors["danger"],
    )

    def center_window():
        """将窗口居中显示"""
        root.update_idletasks()
        width = root.winfo_width()
        height = root.winfo_height()
        x_pos = max((root.winfo_screenwidth() - width) // 2, 20)
        y_pos = max((root.winfo_screenheight() - height) // 2 - 20, 20)
        root.geometry(f"{width}x{height}+{x_pos}+{y_pos}")

    def create_card(parent):
        return tk.Frame(
            parent,
            bg=colors["card_bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=colors["card_border"],
            highlightcolor=colors["card_border"],
        )

    def style_text_widget(widget, readonly=False):
        widget.configure(
            font=body_font,
            bg=colors["input_bg"] if not readonly else colors["muted_bg"],
            fg=colors["text_primary"],
            insertbackground=colors["text_primary"],
            relief="flat",
            bd=0,
            padx=12,
            pady=12,
            highlightthickness=1,
            highlightbackground=colors["card_border"],
            highlightcolor=colors["accent"],
            selectbackground=colors["accent_soft"],
            selectforeground=colors["text_primary"],
        )
    
    def save_image_to_disk(image, source="upload"):
        """保存图片到当前目录并返回绝对路径"""
        nonlocal image_counter
        image_counter += 1
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"feedback_image_{timestamp}_{image_counter}.png"
        filepath = os.path.join(feedback_dir, filename)
        
        try:
            image.save(filepath, "PNG")
            return os.path.abspath(filepath)
        except Exception as e:
            messagebox.showerror("错误", f"保存图片失败: {e}")
            return None

    def build_feedback_payload():
        """组装待提交的反馈列表，避免重复追加文本反馈"""
        payload = list(feedback_list)
        text_content = text_input.get("1.0", tk.END).strip()
        if text_content:
            payload.append({
                "type": "text",
                "content": text_content,
                "timestamp": datetime.now().isoformat()
            })
        return payload

    def update_status(message=None):
        """更新底部状态信息"""
        draft_count = len(build_feedback_payload())
        status_message = message or "等待提交反馈"
        shortcut_label.config(text="快捷键: Ctrl+Enter / Cmd+Enter 提交，Ctrl/Cmd+V 可粘贴图片")
        status_label.config(
            text=f"{status_message}  ·  当前共 {draft_count} 项反馈  ·  图片目录: {feedback_dir}"
        )
    
    def upload_images():
        """上传图片文件"""
        file_paths = filedialog.askopenfilenames(
            title="选择图片文件",
            filetypes=[
                ("图片文件", "*.jpg *.jpeg *.png *.gif *.bmp *.webp"),
                ("所有文件", "*.*")
            ]
        )
        
        for file_path in file_paths:
            try:
                img = Image.open(file_path)
                saved_path = save_image_to_disk(img, "upload")
                if saved_path:
                    feedback_list.append({
                        "type": "image",
                        "content": saved_path,
                        "timestamp": datetime.now().isoformat()
                    })
                    image_listbox.insert(tk.END, f"📎 {os.path.basename(saved_path)}")
                    update_status(f"✅ 已上传: {os.path.basename(saved_path)}")
            except Exception as e:
                messagebox.showerror("错误", f"无法打开图片 {file_path}: {e}")
    
    def paste_image(show_warning=True):
        """从剪贴板粘贴图片"""
        try:
            img = ImageGrab.grabclipboard()
            if img is None:
                if show_warning:
                    messagebox.showwarning("提示", "剪贴板中没有图片！\n请先复制图片后再粘贴。")
                return False
            
            if isinstance(img, Image.Image):
                saved_path = save_image_to_disk(img, "paste")
                if saved_path:
                    feedback_list.append({
                        "type": "image",
                        "content": saved_path,
                        "timestamp": datetime.now().isoformat()
                    })
                    image_listbox.insert(tk.END, f"📋 {os.path.basename(saved_path)}")
                    update_status(f"✅ 已粘贴: {os.path.basename(saved_path)}")
                return True
            else:
                if show_warning:
                    messagebox.showwarning("提示", "剪贴板内容不是图片格式")
                return False
        except Exception as e:
            messagebox.showerror("错误", f"粘贴图片失败: {e}")
            return False
    
    def submit_feedback(event=None):
        """提交反馈"""
        payload = build_feedback_payload()

        if not payload:
            messagebox.showwarning("警告", "请提供反馈内容！")
            return "break" if event else None
        
        if messagebox.askyesno("确认", f"确定提交 {len(payload)} 项反馈给AI吗？"):
            feedback_list[:] = payload
            root.quit()
            root.destroy()
        return "break" if event else None
    
    def cancel_feedback(event=None):
        """取消反馈"""
        if messagebox.askyesno("确认", "确定取消反馈吗？"):
            feedback_list.clear()
            root.quit()
            root.destroy()
        return "break" if event else None
    
    root.protocol("WM_DELETE_WINDOW", cancel_feedback)

    main_frame = tk.Frame(root, bg=colors["app_bg"])
    main_frame.pack(fill="both", expand=True, padx=18, pady=18)

    header_frame = tk.Frame(main_frame, bg=colors["hero_bg"], bd=0, highlightthickness=0)
    header_frame.pack(fill="x", pady=(0, 14))

    title_label = tk.Label(
        header_frame,
        text="🤖 AI助手请求用户反馈",
        font=title_font,
        bg=colors["hero_bg"],
        fg="#FFFFFF",
        anchor="w",
    )
    title_label.pack(fill="x", padx=20, pady=(18, 4))

    subtitle_label = tk.Label(
        header_frame,
        text="把想补充的说明、问题或截图放在这里，确认后会一次提交给 AI。",
        font=body_font,
        bg=colors["hero_bg"],
        fg=colors["hero_subtle"],
        anchor="w",
    )
    subtitle_label.pack(fill="x", padx=20, pady=(0, 18))
    
    # 摘要区域
    if summary:
        summary_frame = create_card(main_frame)
        summary_frame.pack(fill="x", pady=(0, 12))

        tk.Label(
            summary_frame,
            text="📋 AI工作摘要",
            font=section_font,
            bg=colors["card_bg"],
            fg=colors["text_primary"],
            anchor="w",
        ).pack(fill="x", padx=16, pady=(14, 2))
        
        summary_text = scrolledtext.ScrolledText(summary_frame, height=4, wrap=tk.WORD)
        summary_text.pack(fill="x", padx=16, pady=(6, 16))
        style_text_widget(summary_text, readonly=True)
        summary_text.insert("1.0", summary)
        summary_text.config(state="disabled")
    
    content_frame = tk.Frame(main_frame, bg=colors["app_bg"])
    content_frame.pack(fill="both", expand=True)
    content_frame.grid_columnconfigure(0, weight=7)
    content_frame.grid_columnconfigure(1, weight=5)
    content_frame.grid_rowconfigure(0, weight=1)

    # 文本反馈区域
    text_frame = create_card(content_frame)
    text_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

    tk.Label(
        text_frame,
        text="💬 文本反馈",
        font=section_font,
        bg=colors["card_bg"],
        fg=colors["text_primary"],
        anchor="w",
    ).pack(fill="x", padx=16, pady=(14, 2))

    tk.Label(
        text_frame,
        text="可直接描述修改意见、补充信息或下一步需求。",
        font=hint_font,
        bg=colors["card_bg"],
        fg=colors["text_secondary"],
        anchor="w",
    ).pack(fill="x", padx=16)

    text_input = scrolledtext.ScrolledText(text_frame, height=14, wrap=tk.WORD)
    text_input.pack(fill="both", expand=True, padx=16, pady=(8, 16))
    style_text_widget(text_input)

    # 图片反馈区域
    image_frame = create_card(content_frame)
    image_frame.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
    image_frame.grid_rowconfigure(2, weight=1)
    image_frame.grid_columnconfigure(0, weight=1)

    tk.Label(
        image_frame,
        text="📷 图片反馈",
        font=section_font,
        bg=colors["card_bg"],
        fg=colors["text_primary"],
        anchor="w",
    ).grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 2))

    tk.Label(
        image_frame,
        text="支持上传文件，或直接从剪贴板贴上截图。",
        font=hint_font,
        bg=colors["card_bg"],
        fg=colors["text_secondary"],
        anchor="w",
    ).grid(row=1, column=0, sticky="ew", padx=16)

    image_listbox = tk.Listbox(
        image_frame,
        height=12,
        font=body_font,
        bg=colors["input_bg"],
        fg=colors["text_primary"],
        selectbackground=colors["accent"],
        selectforeground="#FFFFFF",
        relief="flat",
        bd=0,
        activestyle="none",
        highlightthickness=1,
        highlightbackground=colors["card_border"],
        highlightcolor=colors["accent"],
    )
    image_listbox.grid(row=2, column=0, sticky="nsew", padx=16, pady=(8, 12))

    image_btn_frame = tk.Frame(image_frame, bg=colors["card_bg"])
    image_btn_frame.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))

    ttk.Button(image_btn_frame, text="📎 上传图片", command=upload_images, style="Secondary.TButton").pack(side="left")
    ttk.Button(
        image_btn_frame,
        text="📋 粘贴图片",
        command=paste_image,
        style="Secondary.TButton",
    ).pack(side="left", padx=(10, 0))

    footer_frame = create_card(main_frame)
    footer_frame.pack(fill="x", pady=(14, 0))

    shortcut_label = tk.Label(
        footer_frame,
        font=hint_font,
        bg=colors["card_bg"],
        fg=colors["text_secondary"],
        anchor="w",
    )
    shortcut_label.pack(fill="x", padx=16, pady=(12, 2))

    status_label = tk.Label(
        footer_frame,
        font=hint_font,
        bg=colors["card_bg"],
        fg=colors["text_primary"],
        anchor="w",
    )
    status_label.pack(fill="x", padx=16, pady=(0, 12))

    btn_frame = tk.Frame(footer_frame, bg=colors["card_bg"])
    btn_frame.pack(fill="x", padx=16, pady=(0, 16))

    ttk.Button(
        btn_frame,
        text="✅ 提交给AI",
        command=submit_feedback,
        style="Primary.TButton",
    ).pack(side="left")
    ttk.Button(
        btn_frame,
        text="❌ 取消",
        command=cancel_feedback,
        style="Danger.TButton",
    ).pack(side="right")
    
    # 绑定快捷键 - 只在剪贴板有图片时才粘贴图片，否则让文本框正常处理
    def smart_paste(event):
        """智能粘贴：检测剪贴板内容类型"""
        try:
            img = ImageGrab.grabclipboard()
            if isinstance(img, Image.Image):
                paste_image(show_warning=False)
                return "break"  # 阻止默认行为
        except:
            pass
        return None  # 让文本框正常处理文本粘贴
    
    for paste_sequence in ("<Control-v>", "<Control-V>", "<Command-v>", "<Command-V>"):
        root.bind_all(paste_sequence, smart_paste)

    for submit_sequence in ("<Control-Return>", "<Control-KP_Enter>", "<Command-Return>", "<Command-KP_Enter>"):
        root.bind_all(submit_sequence, submit_feedback)

    root.bind("<Escape>", cancel_feedback)
    text_input.focus_set()
    center_window()
    update_status()
    
    root.mainloop()
    return feedback_list


def main():
    parser = argparse.ArgumentParser(
        description="AI反馈工具 - 简化版",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用示例:
  # CLI模式
  python ai_feedback_tool_simple.py --cli --summary "完成了代码分析"
  
  # GUI模式（支持图片上传和粘贴）
  python ai_feedback_tool_simple.py --gui --summary "完成了代码分析"
        """
    )
    
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--cli', action='store_true', help='使用命令行模式')
    mode_group.add_argument('--gui', action='store_true', help='使用GUI模式（支持图片）')
    
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
    try:
        main()
    except Exception:
        restore_stderr()
        raise
