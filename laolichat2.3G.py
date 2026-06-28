#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
腕上聊 · 全功能聊天客户端（漏洞修复版）
修复项：
- 私聊按钮重复 pack 崩溃
- IP 封禁无退出机制
- 自身设备信息超时处理
- 命令行窗口关闭回调
- 图片上传预检大小
- 深色模式、命令行、在线用户移至菜单栏
"""

import sys
import os
import importlib
import subprocess
import threading
import time
import json
import random
import queue
from datetime import datetime, timezone, timedelta

# ========== 依赖检测 ==========
def check_and_install_dependencies():
    required = {'requests': 'requests', 'tkinter': 'tkinter'}
    missing = []
    for lib, pip_name in required.items():
        try:
            importlib.import_module(lib)
        except ImportError:
            missing.append(pip_name)
    if not missing:
        return
    print("检测到缺少以下依赖库：")
    for m in missing:
        print(f"  - {m}")
    choice = input("是否自动安装？(y/n): ").strip().lower()
    if choice == 'y':
        for package in missing:
            print(f"正在安装 {package} ...")
            try:
                subprocess.check_call([sys.executable, "-m", "pip", "install", package])
            except subprocess.CalledProcessError:
                print(f"安装 {package} 失败，请手动：pip install {package}")
                sys.exit(1)
        print("依赖安装完成，请重新启动程序。")
        sys.exit(0)
    else:
        print("请手动安装后再运行：")
        for package in missing:
            print(f"  pip install {package}")
        sys.exit(1)

check_and_install_dependencies()

import requests
import tkinter as tk
from tkinter import ttk, scrolledtext, filedialog, messagebox, simpledialog

# ========== 后端核心 ==========
class ChatCore:
    BASE_URL = "http://8.148.213.26/"

    def __init__(self):
        self.userId = self._gen_uid()
        self.username = ""
        self.session = requests.Session()
        self.incoming_queue = queue.Queue()
        self.running = True
        self.last_group_time = None
        self.last_private_times = {}
        self.private_target = None

    @staticmethod
    def _gen_uid():
        return f"{int(time.time() * 1000)}-{random.randint(1000,9999)}"

    def set_username(self, name):
        self.username = name

    def heartbeat(self):
        if not self.username: return
        try:
            resp = self.session.post(f"{self.BASE_URL}server.php?action=heartbeat",
                                     data={"userId": self.userId, "username": self.username,
                                           "device": "Python-GUI", "battery": "100%⚡"}, timeout=3)
            res = resp.json()
            if not res.get("success"):
                if res.get("error") == "IP_BANNED":
                    self.incoming_queue.put(("ip_banned", "您的IP已被封禁，程序将退出"))
                    self.running = False
                else:
                    self.incoming_queue.put(("error", res.get("message", "心跳失败")))
        except Exception as e:
            self.incoming_queue.put(("error", f"心跳异常：{e}"))

    def fetch_group(self):
        try:
            resp = self.session.post(f"{self.BASE_URL}server.php?action=fetch",
                                     data={"userId": self.userId, "username": self.username}, timeout=5)
            res = resp.json()
            if res.get("success"):
                msgs = res.get("messages", [])
                for m in msgs:
                    t = m.get("time", "")
                    if self.last_group_time is None or t > self.last_group_time:
                        self.incoming_queue.put(("group", m))
                        if self.last_group_time is None or t > self.last_group_time:
                            self.last_group_time = t
        except Exception as e:
            print(f"[网络] 拉取群聊失败: {e}")

    def fetch_private(self, target):
        try:
            resp = self.session.post(f"{self.BASE_URL}server.php?action=fetch_private",
                                     data={"userId": self.userId, "username": self.username, "target": target}, timeout=5)
            res = resp.json()
            if res.get("success"):
                msgs = res.get("messages", [])
                last = self.last_private_times.get(target)
                for m in msgs:
                    t = m.get("time", "")
                    if last is None or t > last:
                        self.incoming_queue.put(("private", m))
                        self.last_private_times[target] = t
        except Exception as e:
            print(f"[网络] 拉取私聊失败: {e}")

    def send_message(self, message, target=None, is_image=False):
        action = "send" if target is None else "send_private"
        data = {"userId": self.userId, "username": self.username, "message": message}
        if target: data["target"] = target
        if is_image: data["is_image"] = 1
        try:
            resp = self.session.post(f"{self.BASE_URL}server.php?action={action}", data=data, timeout=5)
            res = resp.json()
            return res.get("success", False), res.get("error", "")
        except Exception as e:
            return False, str(e)

    def get_online(self):
        try:
            resp = self.session.post(f"{self.BASE_URL}server.php?action=online",
                                     data={"userId": self.userId, "username": self.username}, timeout=3)
            res = resp.json()
            return res.get("users", {}) if res.get("success") else None
        except:
            return None

    def ai_chat(self, prompt):
        try:
            resp = self.session.post(f"{self.BASE_URL}ai.php",
                                     json={"prompt": prompt, "username": self.username}, timeout=10)
            data = resp.json()
            return data.get("reply", "(无回复)")
        except Exception as e:
            return f"AI请求失败：{e}"

    def upload_image(self, file_path):
        if not os.path.isfile(file_path): return None, "文件不存在"
        size = os.path.getsize(file_path)
        if size > 10 * 1024 * 1024:
            return None, "文件超过10MB限制"
        try:
            with open(file_path, 'rb') as f:
                files = {'image': f}
                resp = self.session.post(f"{self.BASE_URL}upload.php", files=files, timeout=15)
            r = resp.json()
            return (r.get("url"), None) if r.get("success") else (None, r.get("error", "上传失败"))
        except Exception as e:
            return None, str(e)

    def _heartbeat_loop(self):
        while self.running:
            self.heartbeat()
            time.sleep(1.5)

    def _fetch_loop(self):
        while self.running:
            self.fetch_group()
            if self.private_target:
                self.fetch_private(self.private_target)
            time.sleep(2.0)

    def start_background(self):
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        threading.Thread(target=self._fetch_loop, daemon=True).start()

# ========== 图形界面 ==========
class ChatApp:
    THEMES = {
        "light": {
            "bg_main": "#f8fafc",
            "bg_toolbar": "#e2e8f0",
            "bg_input": "#f1f5f9",
            "bg_side": "#f8fafc",
            "fg_normal": "#0f172a",
            "fg_accent": "#2563eb",
            "entry_bg": "white",
            "entry_fg": "black",
            "chat_bg": "white",
            "chat_fg": "black",
            "listbox_bg": "white",
            "listbox_fg": "black",
            "btn_primary_bg": "#2563eb",
            "btn_primary_fg": "white",
            "btn_func_bg": "#dbeafe",
            "btn_func_fg": "black",
            "btn_danger_bg": "#dc2626",
            "btn_danger_fg": "white",
            "btn_cmd_bg": "#475569",
            "btn_cmd_fg": "white",
        },
        "dark": {
            "bg_main": "#1e293b",
            "bg_toolbar": "#0f172a",
            "bg_input": "#1e293b",
            "bg_side": "#334155",
            "fg_normal": "#f1f5f9",
            "fg_accent": "#60a5fa",
            "entry_bg": "#334155",
            "entry_fg": "#f1f5f9",
            "chat_bg": "#0f172a",
            "chat_fg": "#f1f5f9",
            "listbox_bg": "#334155",
            "listbox_fg": "#f1f5f9",
            "btn_primary_bg": "#3b82f6",
            "btn_primary_fg": "white",
            "btn_func_bg": "#2563eb",
            "btn_func_fg": "white",
            "btn_danger_bg": "#b91c1c",
            "btn_danger_fg": "white",
            "btn_cmd_bg": "#64748b",
            "btn_cmd_fg": "white",
        }
    }

    def __init__(self, root):
        self.root = root
        self.root.title("腕上聊客户端v2.2G")
        self.root.geometry("800x600")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.core = ChatCore()
        self.theme = "light"
        self.widgets_to_theme = []
        self.online_detail_win = None
        self.self_info_refresh_fail_count = 0
        self.show_login()

    def apply_theme(self):
        colors = self.THEMES[self.theme]
        for widget, props in self.widgets_to_theme:
            try:
                if 'bg' in props: widget.configure(bg=colors[props['bg']])
                if 'fg' in props: widget.configure(fg=colors[props['fg']])
                if 'insertbackground' in props: widget.configure(insertbackground=colors[props['insertbackground']])
            except: pass

    def register_theme_widget(self, widget, bg_key=None, fg_key=None, insertbackground_key=None):
        props = {}
        if bg_key: props['bg'] = bg_key
        if fg_key: props['fg'] = fg_key
        if insertbackground_key: props['insertbackground'] = insertbackground_key
        self.widgets_to_theme.append((widget, props))

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.apply_theme()
        # 更新菜单项文字（深色模式为第0项）
        if hasattr(self, 'settings_menu'):
            new_label = "☀️ 浅色模式" if self.theme == "dark" else "🌙 深色模式"
            self.settings_menu.entryconfig(0, label=new_label)
        if self.online_detail_win:
            try:
                self.online_detail_win.destroy()
            except:
                pass
            self.open_online_detail()

    def show_login(self):
        self.login_frame = tk.Frame(self.root, bg=self.THEMES[self.theme]["bg_main"])
        self.login_frame.pack(fill=tk.BOTH, expand=True)

        tk.Label(self.login_frame, text="⌚ 腕上聊", font=("微软雅黑", 24, "bold"),
                 bg=self.THEMES[self.theme]["bg_main"], fg=self.THEMES[self.theme]["fg_accent"]).pack(pady=20)

        info_text = (
            "✨ 功能说明：\n"
            "• 群聊大厅：实时接收&发送消息\n"
            "• 私密对话：双击右侧在线用户发起\n"
            "• AI 助手：点击「AI助手」提问\n"
            "• 图片功能暂时无法使用\n"
            "• 命令行模式：菜单栏「设置」中打开\n"
            "• 此为测试版本  请勿二次发布\n"
        )
        tk.Label(self.login_frame, text=info_text, font=("微软雅黑", 10),
                 bg=self.THEMES[self.theme]["bg_main"], fg=self.THEMES[self.theme]["fg_normal"],
                 justify=tk.LEFT).pack(pady=10)

        tk.Label(self.login_frame, text="输入昵称进入聊天", font=("微软雅黑", 12),
                 bg=self.THEMES[self.theme]["bg_main"], fg=self.THEMES[self.theme]["fg_normal"]).pack()
        self.name_entry = tk.Entry(self.login_frame, font=("微软雅黑", 14), width=20)
        self.name_entry.pack(pady=10)
        self.name_entry.bind("<Return>", lambda e: self.do_login())
        tk.Button(self.login_frame, text="进入", command=self.do_login,
                  font=("微软雅黑", 12), bg=self.THEMES[self.theme]["btn_primary_bg"],
                  fg=self.THEMES[self.theme]["btn_primary_fg"], width=10).pack(pady=10)

        tk.Label(self.login_frame, text="http://8.148.213.26/", font=("微软雅黑", 9, "underline"),
                 bg=self.THEMES[self.theme]["bg_main"], fg="#6b7280", cursor="hand2").pack(pady=5)

    def do_login(self):
        name = self.name_entry.get().strip()
        if not (1 <= len(name) <= 10):
            messagebox.showwarning("昵称无效", "昵称需1-10个字符")
            return
        if not (name.isalnum() or all('\u4e00' <= c <= '\u9fff' or c.isalnum() or c == '_' for c in name)):
            messagebox.showwarning("昵称无效", "昵称只能包含中英文、数字")
            return
        forbidden = ["狼小嗷", "老李", "系统"]
        if any(w in name for w in forbidden):
            messagebox.showwarning("昵称违规", f"昵称不能包含{forbidden}")
            return
        self.core.set_username(name)
        self.login_frame.destroy()
        self.build_gui()
        self.core.start_background()
        self.poll_messages()

    def build_gui(self):
        colors = self.THEMES[self.theme]

        # ----- 菜单栏 -----
        menubar = tk.Menu(self.root)
        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="🌙 深色模式", command=self.toggle_theme)
        settings_menu.add_command(label="⌨ 命令行模式", command=self.open_terminal)
        settings_menu.add_command(label="👥 在线用户", command=self.open_online_detail)   # 新增在线用户菜单项
        menubar.add_cascade(label="设置", menu=settings_menu)
        self.root.config(menu=menubar)
        self.settings_menu = settings_menu  # 保存引用以便更新菜单项

        # 顶部工具栏（不再包含在线按钮和主题/命令行按钮）
        toolbar = tk.Frame(self.root, bd=1, relief=tk.RAISED)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        self.register_theme_widget(toolbar, bg_key="bg_toolbar")

        self.user_label = tk.Label(toolbar, text=f"👤 {self.core.username}", font=("微软雅黑", 10, "bold"))
        self.user_label.pack(side=tk.LEFT, padx=10, pady=4)
        self.register_theme_widget(self.user_label, bg_key="bg_toolbar", fg_key="fg_normal")

        self.info_label = tk.Label(toolbar, text="正在获取设备信息...", font=("微软雅黑", 9))
        self.info_label.pack(side=tk.LEFT, padx=10)
        self.register_theme_widget(self.info_label, bg_key="bg_toolbar", fg_key="fg_normal")

        self.mode_label = tk.Label(toolbar, text="📢 群聊模式", font=("微软雅黑", 10), fg="#0e7334")
        self.mode_label.pack(side=tk.LEFT, padx=10)
        self.register_theme_widget(self.mode_label, bg_key="bg_toolbar")

        # 退出私聊按钮（初始隐藏）
        self.priv_exit_btn = tk.Button(toolbar, text="🔓 退出私聊", command=self.exit_private,
                                       font=("微软雅黑", 9))

        # 主区域
        main_pane = tk.PanedWindow(self.root, orient=tk.HORIZONTAL, sashrelief=tk.RAISED, sashwidth=5)
        main_pane.pack(fill=tk.BOTH, expand=True)

        left_frame = tk.Frame(main_pane)
        main_pane.add(left_frame, stretch="always")

        self.chat_display = scrolledtext.ScrolledText(left_frame, state='disabled',
                                                      font=("微软雅黑", 10), wrap=tk.WORD)
        self.chat_display.pack(fill=tk.BOTH, expand=True)
        self.register_theme_widget(self.chat_display, bg_key="chat_bg", fg_key="chat_fg")

        right_frame = tk.Frame(main_pane, width=180)
        main_pane.add(right_frame, stretch="never")
        self.register_theme_widget(right_frame, bg_key="bg_side")

        self.online_label = tk.Label(right_frame, text="👥 在线用户", font=("微软雅黑", 10, "bold"))
        self.online_label.pack(pady=5)
        self.register_theme_widget(self.online_label, bg_key="bg_side", fg_key="fg_normal")

        self.user_listbox = tk.Listbox(right_frame, font=("微软雅黑", 9), selectmode=tk.SINGLE)
        self.user_listbox.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.user_listbox.bind("<Double-Button-1>", self.start_private_from_list)
        self.register_theme_widget(self.user_listbox, bg_key="listbox_bg", fg_key="listbox_fg")

        bottom_frame = tk.Frame(self.root)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=5)
        self.register_theme_widget(bottom_frame, bg_key="bg_input")

        self.input_field = tk.Entry(bottom_frame, font=("微软雅黑", 11))
        self.input_field.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(5, 2))
        self.input_field.bind("<Return>", self.send_message_event)
        self.input_field.focus_set()
        self.register_theme_widget(self.input_field, bg_key="entry_bg", fg_key="entry_fg", insertbackground_key="entry_fg")

        send_btn = tk.Button(bottom_frame, text="发送", command=self.send_message_event,
                             font=("微软雅黑", 10), width=6)
        send_btn.pack(side=tk.LEFT, padx=2)
        self.register_theme_widget(send_btn, bg_key="btn_primary_bg", fg_key="btn_primary_fg")

        func_frame = tk.Frame(self.root)
        func_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=5, pady=(0,5))
        self.register_theme_widget(func_frame, bg_key="bg_input")

        for text, cmd in [("AI助手", self.ai_dialog), ("🖼️ 上传图片", self.upload_image),
                          ("🔄 刷新在线", self.refresh_online_users)]:
            btn = tk.Button(func_frame, text=text, command=cmd, font=("微软雅黑", 9))
            btn.pack(side=tk.LEFT, padx=2)
            self.register_theme_widget(btn, bg_key="btn_func_bg", fg_key="btn_func_fg")

        self.schedule_online_update()
        self.apply_theme()

    def open_online_detail(self):
        if self.online_detail_win and self.online_detail_win.winfo_exists():
            self.online_detail_win.destroy()
        self.online_detail_win = tk.Toplevel(self.root)
        self.online_detail_win.title("在线用户详情")
        self.online_detail_win.geometry("600x400")
        self.online_detail_win.protocol("WM_DELETE_WINDOW", self.on_close_detail)

        columns = ("昵称", "等级", "设备", "电量", "位置", "IP")
        self.online_tree = ttk.Treeview(self.online_detail_win, columns=columns, show="headings", selectmode="browse")
        for col in columns:
            self.online_tree.heading(col, text=col)
            self.online_tree.column(col, width=100, anchor="center")
        self.online_tree.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)
        self.online_tree.bind("<Double-1>", self.start_private_from_detail)

        self.update_online_detail()
        self.refresh_detail_loop()

    def on_close_detail(self):
        if self.online_detail_win:
            self.online_detail_win.destroy()
            self.online_detail_win = None

    def refresh_detail_loop(self):
        if self.online_detail_win and self.online_detail_win.winfo_exists():
            self.update_online_detail()
            self.online_detail_win.after(5000, self.refresh_detail_loop)

    def update_online_detail(self):
        users = self.core.get_online()
        if not users:
            return
        for item in self.online_tree.get_children():
            self.online_tree.delete(item)
        for name, info in users.items():
            device = info.get('device', '')
            battery = info.get('battery', '')
            prov = info.get('prov', '')
            city = info.get('city', '')
            ip = info.get('ip', '')
            level_title = info.get('levelTitle', '')
            location = f"{prov}{city}" if prov or city else ''
            self.online_tree.insert("", tk.END, values=(name, level_title, device, battery, location, ip))

    def start_private_from_detail(self, event):
        selected = self.online_tree.selection()
        if not selected:
            return
        item = self.online_tree.item(selected[0])
        target = item['values'][0]
        if target == self.core.username:
            messagebox.showinfo("提示", "不能和自己私聊")
            return
        self._enter_private(target)

    def start_private_from_list(self, event):
        selection = self.user_listbox.curselection()
        if selection:
            target = self.user_listbox.get(selection[0])
            if target == self.core.username:
                messagebox.showinfo("提示", "不能和自己私聊")
                return
            self._enter_private(target)

    def _enter_private(self, target):
        self.core.private_target = target
        self.mode_label.config(text=f"🔒 私聊 {target}", fg="#b91c1c")
        # 确保按钮隐藏后再显示，避免重复pack
        if self.priv_exit_btn.winfo_ismapped():
            self.priv_exit_btn.pack_forget()
        # 直接pack到右侧，不再依赖在线按钮
        self.priv_exit_btn.pack(side=tk.RIGHT, padx=5)
        self._insert_message(f"--- 进入与 {target} 的私聊 ---\n")

    def exit_private(self):
        self.core.private_target = None
        self.mode_label.config(text="📢 群聊模式", fg="#0e7334")
        self.priv_exit_btn.pack_forget()
        self._insert_message("--- 返回群聊模式 ---\n")

    def send_message_event(self, event=None):
        msg = self.input_field.get().strip()
        if not msg: return
        target = self.core.private_target
        success, err = self.core.send_message(msg, target=target)
        if success:
            if target is None:
                tz = timezone(timedelta(hours=8))
                self.core.last_group_time = datetime.now(tz).isoformat()
            prefix = f"🔒 [我 → {target}]" if target else f"📢 [我]"
            self._insert_message(f"{prefix}: {msg}\n")
            self.input_field.delete(0, tk.END)
        else:
            messagebox.showerror("发送失败", err or "未知错误")

    def ai_dialog(self):
        prompt = simpledialog.askstring("AI 提问", "请输入问题：", parent=self.root)
        if prompt:
            reply = self.core.ai_chat(prompt)
            self._insert_message(f"🤖 狼小嗷：{reply}\n")

    def upload_image(self):
        file_path = filedialog.askopenfilename(filetypes=[("图片文件", "*.jpg *.jpeg *.png *.gif *.webp")])
        if not file_path: return
        url, err = self.core.upload_image(file_path)
        if url:
            img_msg = f"[图片]{url}"
            success, err = self.core.send_message(img_msg, target=self.core.private_target, is_image=True)
            if success:
                self._insert_message(f"🖼️ [图片已发送] {url}\n")
            else:
                messagebox.showerror("发送失败", err or "未知错误")
        else:
            messagebox.showerror("上传失败", err)

    def refresh_online_users(self):
        users = self.core.get_online()
        if users is None:
            return
        self.user_listbox.delete(0, tk.END)
        found_self = False
        for name, info in users.items():
            if name == self.core.username:
                found_self = True
                device = info.get('device', '未知')
                battery = info.get('battery', '未知')
                prov = info.get('prov', '')
                city = info.get('city', '')
                ip = info.get('ip', '')
                level_title = info.get('levelTitle', '')
                location = f"{prov}{city}" if prov or city else ''
                parts = []
                if device: parts.append(f"📱{device}")
                if battery: parts.append(f"🔋{battery}")
                if level_title: parts.append(f"🏅{level_title}")
                if location: parts.append(f"🌐{location}")
                if ip: parts.append(f"IP:{ip}")
                info_text = " | ".join(parts) if parts else "在线"
                self.info_label.config(text=info_text)
                self.self_info_refresh_fail_count = 0
            self.user_listbox.insert(tk.END, name)

        if not found_self:
            self.self_info_refresh_fail_count += 1
            if self.self_info_refresh_fail_count >= 10:
                self.info_label.config(text="⚠️ 无法获取自身信息")

    def schedule_online_update(self):
        self.refresh_online_users()
        self.root.after(5000, self.schedule_online_update)

    def _insert_message(self, text):
        self.chat_display.configure(state='normal')
        self.chat_display.insert(tk.END, text)
        self.chat_display.see(tk.END)
        self.chat_display.configure(state='disabled')

    def poll_messages(self):
        try:
            while True:
                typ, data = self.core.incoming_queue.get_nowait()
                if typ == "group":
                    user = data.get("username", "?")
                    content = data.get("message", "")
                    self._insert_message(f"📢 [{user}]: {content}\n")
                elif typ == "private":
                    user = data.get("username", "?")
                    content = data.get("message", "")
                    if user == self.core.username:
                        self._insert_message(f"🔒 [我 → {self.core.private_target or '?'}]: {content}\n")
                    else:
                        self._insert_message(f"🔒 [{user} → 我]: {content}\n")
                elif typ == "ip_banned":
                    messagebox.showwarning("封禁通知", data)
                    self.root.quit()
                    return
                elif typ == "error":
                    self._insert_message(f"⚠️ {data}\n")
        except queue.Empty:
            pass
        self.root.after(200, self.poll_messages)

    def open_terminal(self):
        term = tk.Toplevel(self.root)
        term.title("命令行模式")
        term.geometry("600x400")
        term.protocol("WM_DELETE_WINDOW", lambda: term.destroy())
        output = scrolledtext.ScrolledText(term, state='disabled', bg="black", fg="white",
                                           font=("Consolas", 10))
        output.pack(fill=tk.BOTH, expand=True)
        def term_print(text):
            output.configure(state='normal')
            output.insert(tk.END, text + "\n")
            output.see(tk.END)
            output.configure(state='disabled')
        entry = tk.Entry(term, bg="#1e293b", fg="white", insertbackground="white", font=("Consolas", 11))
        entry.pack(fill=tk.X, padx=5, pady=5)

        def handle_command(event=None):
            cmd = entry.get().strip()
            entry.delete(0, tk.END)
            if not cmd: return
            term_print(f">>> {cmd}")
            if cmd in ("/exit", "/quit"):
                term.destroy()
                return
            if cmd == "/help":
                term_print("/online  /ai <问题>  /upload <路径>  /msg <昵称> <内容>  /chat <昵称>  /exit_private  /exit")
            elif cmd == "/online":
                users = self.core.get_online()
                if users:
                    for name, info in users.items():
                        term_print(f"  {name} [{info.get('device','')}]")
                else:
                    term_print("获取在线用户失败")
            elif cmd.startswith("/ai "):
                reply = self.core.ai_chat(cmd[4:].strip())
                term_print(f"狼小嗷：{reply}")
            elif cmd.startswith("/msg "):
                parts = cmd[5:].split(maxsplit=1)
                if len(parts) < 2:
                    term_print("用法：/msg <昵称> <内容>")
                else:
                    target, text = parts
                    succ, err = self.core.send_message(text, target=target)
                    term_print("已发送" if succ else f"失败：{err}")
            elif cmd.startswith("/chat "):
                target = cmd[6:].strip()
                if target:
                    self._enter_private(target)
                    term_print(f"已进入与 {target} 的私聊（主界面同步切换）")
                else:
                    term_print("用法：/chat <昵称>")
            elif cmd == "/exit_private":
                self.core.private_target = None
                self.mode_label.config(text="📢 群聊模式", fg="#0e7334")
                self.priv_exit_btn.pack_forget()
                term_print("已退出私聊")
            elif cmd.startswith("/upload "):
                path = cmd[8:].strip()
                url, err = self.core.upload_image(path)
                if url:
                    term_print(f"上传成功：{url}")
                else:
                    term_print(f"上传失败：{err}")
            else:
                target = self.core.private_target
                succ, err = self.core.send_message(cmd, target=target)
                term_print("消息已发送" if succ else f"发送失败：{err}")

        entry.bind("<Return>", handle_command)
        term_print("命令行模式已启动，输入 /help 查看命令，/exit 退出窗口。")
        entry.focus_set()

    def on_close(self):
        self.core.running = False
        if self.online_detail_win:
            self.online_detail_win.destroy()
        self.root.destroy()


# ========== 纯命令行模式 ==========
def run_cli_mode():
    core = ChatCore()
    core.start_background()
    core.set_username(input("请输入昵称: ").strip())
    print("已启动，输入 /help 查看命令。")
    def print_new_messages():
        while not core.incoming_queue.empty():
            typ, data = core.incoming_queue.get_nowait()
            if typ == "group": print(f"\n[群] {data.get('username')}: {data.get('message')}")
            elif typ == "private": print(f"\n[私] {data.get('username')}: {data.get('message')}")
            elif typ == "ip_banned":
                print("\n您的IP已被封禁，程序退出。")
                core.running = False
            elif typ == "error": print(f"\n! {data}")
    try:
        while core.running:
            print_new_messages()
            try:
                cmd = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not cmd: continue
            if cmd in ("/exit", "/quit"): break
            if cmd == "/help":
                print("/online  /ai <问题>  /upload <路径>  /msg <昵称> <内容>  /chat <昵称>  /exit_private  /exit")
            elif cmd == "/online":
                users = core.get_online()
                if users:
                    for name, info in users.items(): print(f"  {name} [{info.get('device','')}]")
                else: print("获取在线用户失败")
            elif cmd.startswith("/ai "):
                print(f"狼小嗷：{core.ai_chat(cmd[4:])}")
            elif cmd.startswith("/msg "):
                parts = cmd[5:].split(maxsplit=1)
                if len(parts) < 2: print("用法：/msg <昵称> <内容>")
                else:
                    succ, err = core.send_message(parts[1], target=parts[0])
                    print("已发送" if succ else f"失败：{err}")
            elif cmd.startswith("/chat "):
                target = cmd[6:].strip()
                if target:
                    core.private_target = target
                    print(f"已进入与 {target} 的私聊模式。")
                else: print("用法：/chat <昵称>")
            elif cmd == "/exit_private":
                core.private_target = None
                print("已退出私聊模式。")
            elif cmd.startswith("/upload "):
                path = cmd[8:].strip()
                url, err = core.upload_image(path)
                if url:
                    print(f"上传成功：{url}")
                    img_msg = f"[图片]{url}"
                    succ, err = core.send_message(img_msg, target=core.private_target, is_image=True)
                    print("图片已发送" if succ else f"发送图片失败：{err}")
                else: print(f"上传失败：{err}")
            else:
                target = core.private_target
                succ, err = core.send_message(cmd, target=target)
                print("消息已发送" if succ else f"发送失败：{err}")
    finally:
        core.running = False
        print("已退出。")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] in ("-c", "--cli"):
        run_cli_mode()
    else:
        root = tk.Tk()
        app = ChatApp(root)
        root.mainloop()