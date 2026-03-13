"""
OpenClaw 设置界面 — CustomTkinter 现代 UI

分四个标签页：
1. AI 平台 — 引导式配置 + 额度总览
2. 语音设置 — STT/TTS 配置
3. 平台接入 — 企业 IM 桥接（未来扩展）
4. 系统 — 开机启动、端口、主题
"""
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Optional

from loguru import logger

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False


def _safe_import_router():
    try:
        # 确保项目根目录在 path 中
        root = str(Path(__file__).parent.parent.parent)
        if root not in sys.path:
            sys.path.insert(0, root)
        from src.router.config import RouterConfig
        from src.router.router import AIRouter
        return RouterConfig, AIRouter
    except Exception as e:
        logger.warning(f"路由器导入失败: {e}")
        return None, None


class SettingsWindow:
    """设置主窗口"""

    def __init__(self, router=None):
        if not CTK_AVAILABLE:
            logger.error("customtkinter 未安装，设置界面不可用")
            return

        RouterConfig, _ = _safe_import_router()
        self.cfg = RouterConfig() if RouterConfig else None
        self.router = router
        self._window: Optional[ctk.CTk] = None
        self._test_results = {}

    def show(self):
        """打开或聚焦设置窗口"""
        if self._window and self._window.winfo_exists():
            self._window.lift()
            self._window.focus()
            return
        self._build_window()

    def _build_window(self):
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self._window = ctk.CTk()
        self._window.title("OpenClaw 设置")
        self._window.geometry("820x620")
        self._window.resizable(False, False)

        # 左侧导航栏
        nav = ctk.CTkFrame(self._window, width=180, corner_radius=0)
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)

        ctk.CTkLabel(nav, text="🦞 OpenClaw", font=("", 16, "bold"),
                     text_color="#a78bfa").pack(pady=(20, 4))
        ctk.CTkLabel(nav, text="设置中心", font=("", 11),
                     text_color="gray").pack(pady=(0, 20))

        # 右侧内容区
        content = ctk.CTkFrame(self._window, corner_radius=0)
        content.pack(side="right", fill="both", expand=True)

        # 页面容器
        self._pages = {}
        self._current_page = None

        pages_config = [
            ("🤖  AI 平台", self._build_ai_page),
            ("🎙️  语音设置", self._build_voice_page),
            ("💬  平台接入", self._build_bridge_page),
            ("⚙️  系统设置", self._build_system_page),
        ]

        nav_btns = []
        for label, builder in pages_config:
            btn = ctk.CTkButton(
                nav, text=label, anchor="w",
                width=160, height=40,
                fg_color="transparent",
                hover_color=("#3b3b4f", "#3b3b4f"),
                font=("", 13),
                command=lambda b=builder, lb=label, nb=nav_btns: self._switch_page(b, lb, nb),
            )
            btn.pack(pady=2, padx=10)
            nav_btns.append(btn)
            page = ctk.CTkScrollableFrame(content)
            self._pages[label] = page
            builder(page)

        # 默认显示第一页
        self._switch_page(pages_config[0][1], pages_config[0][0], nav_btns)

        # 底部按钮
        bottom = ctk.CTkFrame(content, height=50, corner_radius=0)
        bottom.pack(side="bottom", fill="x")
        ctk.CTkButton(bottom, text="保存设置", width=120, height=32,
                      command=self._save_all).pack(side="right", padx=16, pady=8)
        ctk.CTkButton(bottom, text="重新加载", width=100, height=32,
                      fg_color="transparent", border_width=1,
                      command=self._reload).pack(side="right", padx=4, pady=8)

        self._window.mainloop()

    def _switch_page(self, builder, label, nav_btns):
        for page in self._pages.values():
            page.pack_forget()
        self._pages[label].pack(fill="both", expand=True, padx=8, pady=8)
        self._current_page = label

    # ──────────────────────────────────────────────────
    # AI 平台页
    # ──────────────────────────────────────────────────

    def _build_ai_page(self, frame: "ctk.CTkScrollableFrame"):
        self._ai_widgets = {}

        ctk.CTkLabel(frame, text="🤖 AI 大脑配置",
                     font=("", 18, "bold")).pack(anchor="w", pady=(12, 4))
        ctk.CTkLabel(frame, text="选择并配置你的 AI 服务商，系统会自动在多个平台间智能切换",
                     font=("", 12), text_color="gray").pack(anchor="w", pady=(0, 16))

        if not self.cfg:
            ctk.CTkLabel(frame, text="⚠️ 配置加载失败", text_color="red").pack()
            return

        # 调度模式
        mode_frame = self._section(frame, "调度策略")
        self._routing_var = ctk.StringVar(value=self.cfg.routing_mode)
        for mode_id, mode_name, desc in [
            ("cost_saving", "省钱优先", "先用免费额度，永久免费做兜底，绝不花钱"),
            ("quality_first", "质量优先", "优先高质量模型，免费的做备用"),
            ("speed_first", "速度优先", "多路竞速，取最快的响应"),
        ]:
            row = ctk.CTkFrame(mode_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkRadioButton(row, text=mode_name, variable=self._routing_var,
                               value=mode_id, font=("", 13)).pack(side="left")
            ctk.CTkLabel(row, text=f"  — {desc}", font=("", 11),
                         text_color="gray").pack(side="left")

        # 各平台配置
        providers = self.cfg.all_providers_meta()
        for meta in providers:
            self._build_provider_card(frame, meta)

    def _build_provider_card(self, frame, meta: dict):
        pid = meta["id"]
        tier = meta.get("tier", "paid")
        tier_colors = {
            "free_unlimited": "#22c55e",
            "quota": "#f59e0b",
            "custom": "#06b6d4",
            "paid": "#6b7280",
        }
        tier_labels = {
            "free_unlimited": "永久免费", "quota": "有赠送额度",
            "custom": "自定义", "paid": "付费",
        }

        card = ctk.CTkFrame(frame, corner_radius=12, border_width=1,
                            border_color=tier_colors.get(tier, "#444"))
        card.pack(fill="x", pady=6, padx=4)

        # 标题行
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=14, pady=(12, 0))

        ctk.CTkLabel(header, text=meta.get("name", pid),
                     font=("", 14, "bold")).pack(side="left")
        tag = meta.get("tag", "")
        if tag:
            ctk.CTkLabel(header, text=f"  {tag}",
                         font=("", 11), text_color=tier_colors.get(tier, "gray")).pack(side="left")

        # 启用开关
        enabled_var = ctk.BooleanVar(value=self.cfg.is_provider_enabled(pid))
        self._ai_widgets.setdefault(pid, {})["enabled"] = enabled_var
        ctk.CTkSwitch(header, text="", variable=enabled_var,
                      width=46, height=24).pack(side="right")

        # 描述
        ctk.CTkLabel(card, text=meta.get("free_info", meta.get("description", "")),
                     font=("", 11), text_color="gray",
                     wraplength=560, justify="left").pack(anchor="w", padx=14, pady=(4, 8))

        # API Key 输入行
        key_row = ctk.CTkFrame(card, fg_color="transparent")
        key_row.pack(fill="x", padx=14, pady=(0, 8))

        ctk.CTkLabel(key_row, text="API Key:", width=80, anchor="w").pack(side="left")
        current_key = self.cfg.get_provider_key(pid) or ""
        display_key = current_key[:8] + "..." if len(current_key) > 8 else current_key
        key_entry = ctk.CTkEntry(key_row, width=300, placeholder_text=meta.get("key_placeholder", ""),
                                  show="")
        if current_key:
            key_entry.insert(0, current_key)
        key_entry.pack(side="left", padx=(0, 8))
        self._ai_widgets[pid]["key_entry"] = key_entry

        # 按钮组
        btn_frame = ctk.CTkFrame(key_row, fg_color="transparent")
        btn_frame.pack(side="left")

        register_url = meta.get("register_url", "")
        apikey_url = meta.get("apikey_url", "")
        if register_url:
            ctk.CTkButton(btn_frame, text="去注册", width=70, height=28,
                          fg_color="#6366f1",
                          command=lambda u=register_url: webbrowser.open(u)).pack(side="left", padx=2)
        if apikey_url:
            ctk.CTkButton(btn_frame, text="获取 Key", width=80, height=28,
                          fg_color="transparent", border_width=1,
                          command=lambda u=apikey_url: webbrowser.open(u)).pack(side="left", padx=2)

        # 测试按钮 + 状态
        status_var = ctk.StringVar(value="")
        self._ai_widgets[pid]["status_var"] = status_var
        status_label = ctk.CTkLabel(card, textvariable=status_var,
                                    font=("", 11), text_color="#22c55e")
        status_label.pack(anchor="w", padx=14, pady=(0, 6))

        test_btn = ctk.CTkButton(
            card, text="🔍 测试连接", width=100, height=28,
            fg_color="transparent", border_width=1,
            command=lambda p=pid, sv=status_var, ke=key_entry: self._test_provider(p, sv, ke),
        )
        test_btn.pack(anchor="w", padx=14, pady=(0, 10))

    # ──────────────────────────────────────────────────
    # 语音设置页
    # ──────────────────────────────────────────────────

    def _build_voice_page(self, frame):
        ctk.CTkLabel(frame, text="🎙️ 语音设置",
                     font=("", 18, "bold")).pack(anchor="w", pady=(12, 16))

        if not self.cfg:
            ctk.CTkLabel(frame, text="配置加载失败").pack()
            return

        # STT 设置
        stt_frame = self._section(frame, "语音识别（STT）— 说话转文字")
        ctk.CTkLabel(stt_frame, text="识别模型:", anchor="w").grid(row=0, column=0, sticky="w", pady=6)
        self._stt_model_var = ctk.StringVar(value=self.cfg.stt_model)
        model_menu = ctk.CTkOptionMenu(
            stt_frame,
            values=["tiny（最快，略差）", "base（均衡推荐）", "small（较好）", "medium（最准，慢）"],
            variable=self._stt_model_var, width=200,
        )
        model_menu.grid(row=0, column=1, padx=8, pady=6, sticky="w")

        ctk.CTkLabel(stt_frame, text="识别语言:", anchor="w").grid(row=1, column=0, sticky="w", pady=6)
        self._stt_lang_var = ctk.StringVar(value={"zh": "中文", "en": "英文", "auto": "自动"}.get(self.cfg.stt_language, "中文"))
        ctk.CTkOptionMenu(stt_frame, values=["中文", "英文", "自动检测"],
                          variable=self._stt_lang_var, width=150).grid(row=1, column=1, padx=8, sticky="w")

        ctk.CTkLabel(stt_frame, text="💡 首次使用会自动下载模型文件",
                     font=("", 11), text_color="gray").grid(row=2, column=0, columnspan=3, sticky="w", pady=4)

        # TTS 设置
        tts_frame = self._section(frame, "语音合成（TTS）— 文字转声音")
        ctk.CTkLabel(tts_frame, text="发音人:", anchor="w").grid(row=0, column=0, sticky="w", pady=6)

        voices = [
            "晓晓（女声·温柔）", "云希（男声·年轻）", "云健（男声·浑厚）",
            "晓伊（女声·活泼）", "云扬（男声·播音）", "晓涵（女声·恬静）",
            "晓梦（女声·甜美）",
        ]
        voice_ids = [
            "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "zh-CN-YunjianNeural",
            "zh-CN-XiaoyiNeural", "zh-CN-YunyangNeural", "zh-CN-XiaohanNeural",
            "zh-CN-XiaomengNeural",
        ]
        current_voice = self.cfg.tts_voice
        current_idx = voice_ids.index(current_voice) if current_voice in voice_ids else 0
        self._tts_voice_var = ctk.StringVar(value=voices[current_idx])
        self._tts_voice_ids = dict(zip(voices, voice_ids))
        ctk.CTkOptionMenu(tts_frame, values=voices,
                          variable=self._tts_voice_var, width=200).grid(row=0, column=1, padx=8, sticky="w")

        ctk.CTkButton(tts_frame, text="▶ 试听", width=70, height=28,
                      command=self._preview_tts).grid(row=0, column=2, padx=4)

        ctk.CTkLabel(tts_frame, text="当前使用 Edge TTS（微软免费），无需 API Key",
                     font=("", 11), text_color="#22c55e").grid(row=1, column=0, columnspan=3, sticky="w", pady=4)

    # ──────────────────────────────────────────────────
    # 平台接入页
    # ──────────────────────────────────────────────────

    def _build_bridge_page(self, frame):
        ctk.CTkLabel(frame, text="💬 企业IM 桥接",
                     font=("", 18, "bold")).pack(anchor="w", pady=(12, 4))
        ctk.CTkLabel(frame,
                     text="OpenClaw AI 回复时，同步推送到企业群。只需填写 Webhook URL，5分钟完成配置",
                     font=("", 12), text_color="gray",
                     wraplength=560, justify="left").pack(anchor="w", pady=(0, 8))

        # 使用指南
        guide_frame = ctk.CTkFrame(frame, fg_color="#1a2035", corner_radius=8)
        guide_frame.pack(fill="x", pady=(0, 12), padx=4)
        ctk.CTkLabel(guide_frame,
                     text="📋 配置步骤：群设置 → 添加机器人 → 自定义机器人 → 复制 Webhook URL → 填入下方",
                     font=("", 11), text_color="#a78bfa").pack(anchor="w", padx=12, pady=8)

        self._bridge_widgets = {}

        platforms_config = [
            {
                "id": "feishu",
                "name": "🐦 飞书",
                "doc_url": "https://open.feishu.cn/document/client-docs/bot-5/add-custom-bot",
                "placeholder": "https://open.feishu.cn/open-apis/bot/v2/hook/xxxx",
                "has_secret": True,
                "secret_label": "签名密钥（可选）",
                "config_section": "bridge.feishu",
            },
            {
                "id": "wecom",
                "name": "💼 企业微信",
                "doc_url": "https://developer.work.weixin.qq.com/document/path/91770",
                "placeholder": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx",
                "has_secret": False,
                "config_section": "bridge.wecom",
            },
            {
                "id": "dingtalk",
                "name": "📌 钉钉",
                "doc_url": "https://open.dingtalk.com/document/robots/custom-robot-access",
                "placeholder": "https://oapi.dingtalk.com/robot/send?access_token=xxxx",
                "has_secret": True,
                "secret_label": "加签密钥（可选）",
                "config_section": "bridge.dingtalk",
            },
        ]

        for pcfg in platforms_config:
            self._build_bridge_card(frame, pcfg)

        ctk.CTkLabel(frame,
                     text="✅ 配置好后，每次 AI 回复都会同步发送到对应的群\n"
                          "💡 QQ 和微信个人版（非企业微信）受限于协议，需要额外工具，暂不支持",
                     font=("", 11), text_color="#6b7280",
                     justify="left").pack(anchor="w", padx=8, pady=12)

    def _build_bridge_card(self, frame, pcfg: dict):
        pid = pcfg["id"]
        current_url = ""
        current_secret = ""
        if self.cfg and self.cfg._cfg.has_section(pcfg["config_section"]):
            current_url = self.cfg._cfg.get(pcfg["config_section"], "webhook_url", fallback="")
            current_secret = self.cfg._cfg.get(pcfg["config_section"], "secret", fallback="")

        card = ctk.CTkFrame(frame, corner_radius=12, border_width=1,
                            border_color="#22c55e" if current_url else "#333")
        card.pack(fill="x", pady=6, padx=4)

        # 标题行
        hrow = ctk.CTkFrame(card, fg_color="transparent")
        hrow.pack(fill="x", padx=14, pady=(10, 4))
        ctk.CTkLabel(hrow, text=pcfg["name"], font=("", 14, "bold")).pack(side="left")
        if current_url:
            ctk.CTkLabel(hrow, text="✅ 已配置", font=("", 11),
                         text_color="#22c55e").pack(side="left", padx=8)

        ctk.CTkButton(hrow, text="查看文档", width=80, height=26,
                      fg_color="transparent", border_width=1,
                      command=lambda u=pcfg["doc_url"]: webbrowser.open(u)).pack(side="right")

        # Webhook URL
        url_row = ctk.CTkFrame(card, fg_color="transparent")
        url_row.pack(fill="x", padx=14, pady=2)
        ctk.CTkLabel(url_row, text="Webhook URL:", width=110, anchor="w").pack(side="left")
        url_entry = ctk.CTkEntry(url_row, width=360, placeholder_text=pcfg["placeholder"])
        if current_url:
            url_entry.insert(0, current_url)
        url_entry.pack(side="left", padx=(0, 8))

        secret_entry = None
        if pcfg.get("has_secret"):
            sec_row = ctk.CTkFrame(card, fg_color="transparent")
            sec_row.pack(fill="x", padx=14, pady=2)
            ctk.CTkLabel(sec_row, text=pcfg.get("secret_label", "密钥:"),
                         width=110, anchor="w").pack(side="left")
            secret_entry = ctk.CTkEntry(sec_row, width=240, placeholder_text="可选，留空则不验证签名", show="*")
            if current_secret:
                secret_entry.insert(0, current_secret)
            secret_entry.pack(side="left")

        self._bridge_widgets[pid] = {
            "url_entry": url_entry,
            "secret_entry": secret_entry,
            "config_section": pcfg["config_section"],
        }

        # 测试按钮
        test_status = ctk.StringVar(value="")
        btn_row = ctk.CTkFrame(card, fg_color="transparent")
        btn_row.pack(fill="x", padx=14, pady=(4, 10))
        ctk.CTkButton(btn_row, text="🔍 测试连接", width=100, height=28,
                      fg_color="transparent", border_width=1,
                      command=lambda p=pid, s=test_status, ue=url_entry, se=secret_entry:
                              self._test_bridge(p, s, ue, se)).pack(side="left")
        ctk.CTkLabel(btn_row, textvariable=test_status, font=("", 11),
                     text_color="#22c55e").pack(side="left", padx=8)

    def _test_bridge(self, pid: str, status_var, url_entry, secret_entry=None):
        url = url_entry.get().strip()
        if not url:
            status_var.set("⚠️ 请先填写 Webhook URL")
            return
        secret = secret_entry.get().strip() if secret_entry else ""
        status_var.set("🔍 测试中...")

        def _run():
            try:
                if pid == "feishu":
                    from src.bridge.feishu import FeishuBridge
                    result = FeishuBridge.test_webhook(url)
                elif pid == "wecom":
                    from src.bridge.wecom import WeComBridge
                    result = WeComBridge.test_webhook(url)
                elif pid == "dingtalk":
                    from src.bridge.dingtalk import DingTalkBridge
                    result = DingTalkBridge.test_webhook(url, secret)
                else:
                    result = "不支持的平台"
                status_var.set(f"{'✅' if '成功' in result else '❌'} {result}")
            except Exception as e:
                status_var.set(f"❌ {str(e)[:40]}")

        threading.Thread(target=_run, daemon=True).start()

    # ──────────────────────────────────────────────────
    # 系统设置页
    # ──────────────────────────────────────────────────

    def _build_system_page(self, frame):
        ctk.CTkLabel(frame, text="⚙️ 系统设置",
                     font=("", 18, "bold")).pack(anchor="w", pady=(12, 16))

        if not self.cfg:
            return

        sys_frame = self._section(frame, "启动选项")

        self._autostart_var = ctk.BooleanVar(value=self.cfg.autostart)
        ctk.CTkCheckBox(sys_frame, text="开机时自动启动 OpenClaw",
                        variable=self._autostart_var).pack(anchor="w", pady=6)

        self._tray_var = ctk.BooleanVar(value=self.cfg.minimize_to_tray)
        ctk.CTkCheckBox(sys_frame, text="关闭窗口时最小化到系统托盘（不退出）",
                        variable=self._tray_var).pack(anchor="w", pady=6)

        # 端口设置
        port_frame = self._section(frame, "网络端口")
        ctk.CTkLabel(port_frame, text="HTTPS 端口 (完整版):", anchor="w", width=160).grid(row=0, column=0, sticky="w", pady=6)
        self._https_port_entry = ctk.CTkEntry(port_frame, width=100)
        self._https_port_entry.insert(0, str(self.cfg.https_port))
        self._https_port_entry.grid(row=0, column=1, padx=8, sticky="w")

        ctk.CTkLabel(port_frame, text="HTTP 端口 (扫码版):", anchor="w", width=160).grid(row=1, column=0, sticky="w", pady=6)
        self._http_port_entry = ctk.CTkEntry(port_frame, width=100)
        self._http_port_entry.insert(0, str(self.cfg.http_port))
        self._http_port_entry.grid(row=1, column=1, padx=8, sticky="w")

        ctk.CTkLabel(port_frame, text="修改端口后需要重启服务", font=("", 11),
                     text_color="gray").grid(row=2, column=0, columnspan=2, sticky="w", pady=4)

        # 主题
        theme_frame = self._section(frame, "外观")
        self._theme_var = ctk.StringVar(value="深色模式" if self.cfg.ui_theme == "dark" else "浅色模式")
        ctk.CTkOptionMenu(theme_frame, values=["深色模式", "浅色模式"],
                          variable=self._theme_var,
                          command=self._change_theme, width=140).pack(anchor="w", pady=6)

        # 技能包管理
        skills_frame = self._section(frame, "技能包")
        ctk.CTkLabel(skills_frame,
                     text="已安装技能包 — 提供天气、汇率、房贷、菜谱等实用功能",
                     font=("", 12), text_color="gray").pack(anchor="w", pady=4)
        ctk.CTkButton(skills_frame, text="📦 管理技能包", width=140,
                      command=lambda: webbrowser.open(
                          f"http://localhost:{self.cfg.http_port}/app")).pack(anchor="w", pady=6)

    # ──────────────────────────────────────────────────
    # 动作方法
    # ──────────────────────────────────────────────────

    def _test_provider(self, pid: str, status_var, key_entry):
        """异步测试 API Key 是否有效"""
        key = key_entry.get().strip()
        if not key:
            status_var.set("⚠️ 请先填写 API Key")
            return
        status_var.set("🔍 测试中...")

        def _run():
            import asyncio
            try:
                RouterConfig, AIRouter = _safe_import_router()
                if not RouterConfig:
                    status_var.set("❌ 路由器加载失败")
                    return
                cfg = RouterConfig()
                cfg.set_provider_key(pid, key)
                meta = cfg.get_provider_meta(pid)
                base_url = cfg.get_provider_url(pid)
                model = cfg.get_provider_model(pid)

                import httpx
                async def _test():
                    async with httpx.AsyncClient(timeout=10.0) as client:
                        r = await client.post(
                            f"{base_url}/chat/completions",
                            json={"model": model,
                                  "messages": [{"role": "user", "content": "hi"}],
                                  "max_tokens": 5},
                            headers={"Authorization": f"Bearer {key}",
                                     "Content-Type": "application/json"},
                        )
                        return r.status_code

                code = asyncio.run(_test())
                if code == 200:
                    status_var.set("✅ 连接成功！API Key 有效")
                elif code == 401:
                    status_var.set("❌ API Key 无效，请重新获取")
                elif code == 429:
                    status_var.set("⚠️ 连接成功，但当前已限速")
                else:
                    status_var.set(f"⚠️ HTTP {code}，请检查设置")
            except Exception as e:
                status_var.set(f"❌ 连接失败: {str(e)[:40]}")

        threading.Thread(target=_run, daemon=True).start()

    def _preview_tts(self):
        """试听当前发音人"""
        voice_name = self._tts_voice_var.get()
        voice_id = self._tts_voice_ids.get(voice_name, "zh-CN-XiaoxiaoNeural")

        def _run():
            try:
                import asyncio, edge_tts, tempfile, subprocess
                async def _synth():
                    comm = edge_tts.Communicate("你好，我是 OpenClaw AI 语音助手，很高兴为你服务。", voice=voice_id)
                    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                        tmpfile = f.name
                    await comm.save(tmpfile)
                    subprocess.Popen(["start", "", tmpfile], shell=True)
                asyncio.run(_synth())
            except Exception as e:
                logger.warning(f"TTS 试听失败: {e}")

        threading.Thread(target=_run, daemon=True).start()

    def _change_theme(self, theme: str):
        mode = "dark" if theme == "深色模式" else "light"
        ctk.set_appearance_mode(mode)

    def _save_all(self):
        """保存所有设置"""
        if not self.cfg:
            return
        try:
            # 调度模式
            self.cfg.routing_mode = self._routing_var.get()

            # API Keys
            for pid, widgets in self._ai_widgets.items():
                if "key_entry" in widgets:
                    key = widgets["key_entry"].get().strip()
                    if key:
                        self.cfg.set_provider_key(pid, key)
                if "enabled" in widgets:
                    self.cfg.set_provider_enabled(pid, widgets["enabled"].get())

            # STT
            model_map = {"tiny（最快，略差）": "tiny", "base（均衡推荐）": "base",
                         "small（较好）": "small", "medium（最准，慢）": "medium"}
            self.cfg.stt_model = model_map.get(self._stt_model_var.get(), "base")

            # TTS
            voice_id = self._tts_voice_ids.get(self._tts_voice_var.get(), "zh-CN-XiaoxiaoNeural")
            self.cfg.tts_voice = voice_id

            # 系统
            self.cfg.autostart = self._autostart_var.get()
            if self.cfg.autostart:
                _set_autostart(True)
            else:
                _set_autostart(False)

            # IM 桥接
            if hasattr(self, "_bridge_widgets"):
                for pid, widgets in self._bridge_widgets.items():
                    url = widgets["url_entry"].get().strip()
                    section = widgets["config_section"]
                    if url:
                        if not self.cfg._cfg.has_section(section):
                            self.cfg._cfg.add_section(section)
                        self.cfg._cfg[section]["webhook_url"] = url
                        if widgets.get("secret_entry"):
                            secret = widgets["secret_entry"].get().strip()
                            self.cfg._cfg[section]["secret"] = secret

            self.cfg.save()
            logger.info("✅ 设置已保存")

            # 重新加载路由器
            if self.router:
                self.router.reload_states()

            # 提示
            import tkinter.messagebox as mb
            mb.showinfo("保存成功", "设置已保存！部分更改（如端口、STT模型）需要重启服务后生效。")
        except Exception as e:
            logger.error(f"保存失败: {e}")
            import tkinter.messagebox as mb
            mb.showerror("保存失败", str(e))

    def _reload(self):
        if self.cfg:
            self.cfg.reload()
            self._window.destroy()
            self._window = None
            self.show()

    # ── 工具 ──────────────────────────────────────────
    def _section(self, parent, title: str) -> "ctk.CTkFrame":
        """创建分组框"""
        ctk.CTkLabel(parent, text=title, font=("", 13, "bold"),
                     text_color="#a78bfa").pack(anchor="w", pady=(16, 4))
        frame = ctk.CTkFrame(parent, corner_radius=10)
        frame.pack(fill="x", padx=4, pady=(0, 8))
        inner = ctk.CTkFrame(frame, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=8)
        return inner


def _set_autostart(enable: bool):
    """Windows 注册表开机自启"""
    try:
        import winreg
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "OpenClawAI"
        exe_path = str(Path(sys.executable).parent / "openclaw.exe")
        if not Path(exe_path).exists():
            exe_path = f'"{sys.executable}" "{Path(__file__).parent.parent.parent / "launcher.py"}"'

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0,
                            winreg.KEY_SET_VALUE) as key:
            if enable:
                winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, exe_path)
                logger.info(f"✅ 开机自启已设置: {exe_path}")
            else:
                try:
                    winreg.DeleteValue(key, app_name)
                    logger.info("✅ 开机自启已取消")
                except FileNotFoundError:
                    pass
    except Exception as e:
        logger.warning(f"设置开机自启失败: {e}")


def open_settings(router=None):
    """从任意线程打开设置窗口（线程安全）"""
    if not CTK_AVAILABLE:
        logger.warning("CustomTkinter 未安装，无法打开设置界面")
        return
    win = SettingsWindow(router=router)
    win.show()
