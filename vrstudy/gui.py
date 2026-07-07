from __future__ import annotations

from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import shutil
from time import monotonic
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

if os.name == "nt":
    import msvcrt
else:
    import fcntl

import matplotlib
matplotlib.use("TkAgg")
matplotlib.rcParams["font.family"] = ["Malgun Gothic", "Segoe UI", "Arial"]
matplotlib.rcParams["axes.unicode_minus"] = False
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

from . import __version__
from .calculator import (
    CycleInput,
    cycle_no_from_week,
    cycle_snapshots,
    cycle_dates,
    cycle_input_available_date,
    delete_profile_records,
    display_cycle_rows,
    find_close_price,
    latest_contribution_amount,
    latest_buy_limit_config,
    latest_buy_limit_start_week_no,
    latest_g_config,
    latest_g_start_cycle_no,
    latest_cycle_snapshot,
    next_input_cycle,
    order_basis_for_next_cycle,
    order_level_values,
    profile_cycle_status,
    recalculate_cycle_results_from,
    rename_profile_snapshots,
    save_cycle_result,
    snapshot_for_cycle,
    update_market_prices,
)
from .core import parse_buy_limit_config, parse_g_config
from .db import DEFAULT_DB_PATH, connect, init_db
from .infinite import (
    create_infinite_profile,
    DEFAULT_SETTING_NAME as INFINITE_DEFAULT_SETTING,
    delete_infinite_profile_records,
    ensure_infinite_profile,
    ensure_infinite_profile_storage,
    INFINITE_SYMBOLS,
    InfiniteSetting,
    generate_infinite_rows,
    infinite_order_plan,
    infinite_rows,
    infinite_status_view,
    latest_input_date,
    latest_fx_rate,
    list_infinite_profile_names,
    load_infinite_setting,
    next_us_trading_day,
    order_basis_row,
    previous_us_trading_day,
    rename_infinite_profile_records,
    save_infinite_execution,
    save_infinite_setting,
)
from .kiwoom_api import (
    default_us_stock_exchange_code,
    delete_profile_token,
    ensure_access_token,
    KiwoomApiError,
    issue_access_token,
    kiwoom_token_cache_path,
    rename_profile_token,
    request_us_buy_order,
    request_us_ledger_balance,
    request_us_period_order_history,
    resolve_us_stock_exchange_code,
    request_us_sell_order,
    save_profile_token,
)
from .kiwoom_credentials import (
    KiwoomCredentials,
    delete_kiwoom_credentials,
    kiwoom_credentials_path,
    load_kiwoom_credentials,
    rename_kiwoom_credentials,
    save_kiwoom_credentials,
)
from .paths import app_data_dir
from .profiles import (
    DEFAULT_PROFILE_NAME,
    Profile,
    create_profile,
    delete_profile,
    default_profiles_dir,
    ensure_default_profile,
    list_profiles,
    load_profile,
    rename_profile,
    save_profile,
    update_profile,
)
from .telegram import (
    TelegramSettings,
    load_telegram_settings,
    save_telegram_settings,
    send_telegram_message,
)


class AppLockError(RuntimeError):
    pass


def acquire_single_instance_lock(lock_path: Path):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.seek(0)
        handle.truncate()
        handle.write(str(os.getpid()).encode("ascii"))
        handle.flush()
        return handle
    except OSError as exc:
        handle.close()
        raise AppLockError("VR Study가 이미 실행 중입니다. 기존 창을 확인해 주세요.") from exc


def release_single_instance_lock(handle) -> None:
    if handle is None:
        return
    try:
        handle.seek(0)
        if os.name == "nt":
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass
    try:
        handle.close()
    except OSError:
        pass


class VrStudyApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"VR Study v{__version__} - Strategy Orders")
        self.geometry("1680x940")
        self.minsize(1420, 820)
        try:
            self.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        self._closing = False
        self._startup_loading = True
        self._lock_handle = None
        self.con = None
        self.startup_window: tk.Toplevel | None = None
        self.startup_started_at = monotonic()
        self.startup_progress_var: tk.IntVar | None = None
        self.startup_message_var: tk.StringVar | None = None
        self.startup_percent_var: tk.StringVar | None = None
        self.create_startup_progress()
        self.update_startup_progress(1, "앱 시작 준비 중...")
        try:
            self.update_startup_progress(8, "중복 실행 확인 중...")
            self._lock_handle = acquire_single_instance_lock(app_data_dir() / "vrstudy.lock")
        except AppLockError as exc:
            self.close_startup_progress()
            messagebox.showwarning("VR Study", str(exc))
            self.destroy()
            raise SystemExit(0) from exc

        self.update_startup_progress(14, "데이터 경로 확인 중...")
        self.db_path = DEFAULT_DB_PATH
        self.profiles_dir = default_profiles_dir()
        try:
            self.update_startup_progress(22, "프로필 저장소 정리 중...")
            self._migrate_flat_vr_profiles()
            self.update_startup_progress(34, "DB 연결 중...")
            self.con = connect(self.db_path)
            self.update_startup_progress(46, "DB 스키마 확인 중...")
            init_db(self.con, self.db_path, self.profiles_dir)
            self.update_startup_progress(56, "무한매수법 저장소 확인 중...")
            ensure_infinite_profile_storage(self.con)
        except Exception as exc:
            self.close_startup_progress()
            release_single_instance_lock(self._lock_handle)
            self._lock_handle = None
            messagebox.showerror("VR Study", f"앱 시작 중 문제가 발생했습니다.\n\n{exc}")
            self.destroy()
            raise
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_startup_progress(62, "기본 프로필 확인 중...")
        ensure_default_profile(self.profiles_dir)
        ensure_infinite_profile(self.con, INFINITE_DEFAULT_SETTING)

        self.update_startup_progress(68, "화면 상태 준비 중...")
        self.profile_var = tk.StringVar(value=DEFAULT_PROFILE_NAME)
        self.infinite_profile_var = tk.StringVar(value=INFINITE_DEFAULT_SETTING)
        self.status_var = tk.StringVar(value="준비됨")
        self.today_var = tk.StringVar(value=f"오늘: {date.today()}")
        self.cycle_status_var = tk.StringVar(value="")
        self.profile_fields: dict[str, tk.StringVar] = {}
        self.cycle_fields: dict[str, tk.StringVar] = {}
        self.view_fields: dict[str, tk.StringVar] = {}
        self.infinite_fields: dict[str, tk.StringVar] = {}
        self.infinite_input_fields: dict[str, tk.StringVar] = {}
        self.kiwoom_api_fields: dict[str, dict[str, tk.StringVar]] = {}
        self.kiwoom_api_status_vars: dict[str, tk.StringVar] = {}
        self.kiwoom_balance_status_vars: dict[str, tk.StringVar] = {}
        self.kiwoom_balance_result_widgets: dict[str, tk.Text] = {}
        self.kiwoom_execution_preview_fields: dict[str, tk.StringVar] = {}
        self.kiwoom_execution_preview_status_var = tk.StringVar(value="")
        self.kiwoom_execution_preview_result: dict | None = None
        self.kiwoom_vr_period_fields: dict[str, tk.StringVar] = {}
        self.kiwoom_vr_period_status_var = tk.StringVar(value="")
        self.kiwoom_vr_period_result: dict | None = None
        self.kiwoom_vr_fill_period_var = tk.StringVar(value="대상 주문구간: -")
        self.kiwoom_vr_fill_status_var = tk.StringVar(value="")
        self.kiwoom_vr_fill_tree: ttk.Treeview | None = None
        self.kiwoom_vr_fill_summary_tree: ttk.Treeview | None = None
        self.kiwoom_vr_fill_result: dict | None = None
        self.telegram_fields: dict[str, tk.StringVar] = {}
        self.telegram_option_vars: dict[str, tk.BooleanVar] = {}
        self.telegram_status_var = tk.StringVar(value="")
        self.save_infinite_execution_button: ttk.Button | None = None
        self.profile_display_to_name: dict[str, str] = {}
        self.infinite_display_to_name: dict[str, str] = {}
        self.infinite_rows_tree: ttk.Treeview | None = None
        self.infinite_status_tree: ttk.Treeview | None = None
        self.infinite_order_tree: ttk.Treeview | None = None
        self.infinite_order_info_var = tk.StringVar(value="")
        self.infinite_order_api_status_var = tk.StringVar(value="")
        self.infinite_order_execute_button: ttk.Button | None = None
        self.infinite_order_execute_after_input_button: ttk.Button | None = None
        self.vr_order_execute_button: ttk.Button | None = None
        self.vr_order_api_status_var = tk.StringVar(value="")
        self.dashboard_overview_tree: ttk.Treeview | None = None
        self.dashboard_due_frame: ttk.LabelFrame | None = None
        self.dashboard_due_tree: ttk.Treeview | None = None
        self.dashboard_vr_summary_tree: ttk.Treeview | None = None
        self.dashboard_infinite_summary_tree: ttk.Treeview | None = None
        self.dashboard_vr_tree: ttk.Treeview | None = None
        self.dashboard_infinite_tree: ttk.Treeview | None = None
        self.dashboard_chart_axes: dict[str, object] = {}
        self.dashboard_chart_canvases: dict[str, FigureCanvasTkAgg] = {}
        self.dashboard_scroll_canvas: tk.Canvas | None = None
        self.dashboard_graph_container: ttk.Frame | None = None
        self.dashboard_graph_toggle_button: ttk.Button | None = None
        self.dashboard_tables_container: ttk.Frame | None = None
        self.dashboard_graphs_visible = False
        self.dashboard_selected_vr_name = ""
        self.dashboard_selected_infinite_name = ""
        self.strategy_tabs: ttk.Notebook | None = None
        self.dashboard_tab: ttk.Frame | None = None
        self.vr_tab: ttk.Frame | None = None
        self.infinite_tab: ttk.Frame | None = None
        self.pause_vr_button: ttk.Button | None = None
        self.pause_infinite_button: ttk.Button | None = None
        self.save_cycle_button: ttk.Button | None = None
        self.raw_tree: ttk.Treeview | None = None
        self.editing_saved_cycle = False

        self.update_startup_progress(76, "화면 스타일 적용 중...")
        self._configure_style()
        self.update_startup_progress(84, "화면 구성 중...")
        self._build()
        self.update_startup_progress(92, "VR 프로필 불러오는 중...")
        self.reload_profiles()
        self.update_startup_progress(97, "무한매수법 프로필 불러오는 중...")
        self.reload_infinite_profiles()
        self.update_startup_progress(98, "대시보드 마무리 중...")
        self._startup_loading = False
        self.refresh_due_badges()
        self.refresh_dashboard()
        self.update_startup_progress(99, "가격 업데이트 중...")
        self.auto_update_prices(startup=True)
        self.update_startup_progress(99, "화면 표시 준비 중...")
        self.show_main_window()
        self.update_startup_progress(100, "시작 완료")
        self.close_startup_progress()

    def create_startup_progress(self) -> None:
        self.startup_progress_var = tk.IntVar(value=1)
        self.startup_message_var = tk.StringVar(value="앱 시작 준비 중...")
        self.startup_percent_var = tk.StringVar(value="1%")

        window = tk.Toplevel()
        window.title("VR Study 시작")
        window.resizable(False, False)
        window.protocol("WM_DELETE_WINDOW", lambda: None)
        try:
            window.attributes("-topmost", True)
        except tk.TclError:
            pass
        self.startup_window = window

        frame = ttk.Frame(window, padding=22)
        frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frame,
            text=f"VR Study v{__version__}",
            font=("Malgun Gothic", 14, "bold"),
        ).pack(anchor=tk.W)
        ttk.Label(frame, textvariable=self.startup_message_var).pack(
            anchor=tk.W, pady=(12, 6)
        )
        ttk.Progressbar(
            frame,
            variable=self.startup_progress_var,
            maximum=100,
            length=360,
            mode="determinate",
        ).pack(fill=tk.X)
        ttk.Label(frame, textvariable=self.startup_percent_var).pack(
            anchor=tk.E, pady=(6, 0)
        )

        window.update_idletasks()
        width = window.winfo_reqwidth()
        height = window.winfo_reqheight()
        screen_width = window.winfo_screenwidth()
        screen_height = window.winfo_screenheight()
        x = max(0, int((screen_width - width) / 2))
        y = max(0, int((screen_height - height) / 2))
        window.geometry(f"{width}x{height}+{x}+{y}")
        window.lift()
        try:
            window.focus_force()
        except tk.TclError:
            pass
        window.update()

    def update_startup_progress(self, percent: int, message: str) -> None:
        if self.startup_window is None:
            return
        percent = max(1, min(100, int(percent)))
        if self.startup_progress_var is not None:
            self.startup_progress_var.set(percent)
        if self.startup_message_var is not None:
            self.startup_message_var.set(message)
        if self.startup_percent_var is not None:
            self.startup_percent_var.set(f"{percent}%")
        try:
            self.startup_window.update_idletasks()
            self.startup_window.update()
        except tk.TclError:
            pass

    def close_startup_progress(self) -> None:
        window = self.startup_window
        self.startup_window = None
        if window is None:
            return
        while monotonic() - self.startup_started_at < 0.45:
            try:
                window.update_idletasks()
                window.update()
            except tk.TclError:
                break
        try:
            window.destroy()
        except tk.TclError:
            pass

    def show_main_window(self) -> None:
        try:
            self.attributes("-alpha", 1.0)
        except tk.TclError:
            pass
        self.deiconify()
        self.maximize_on_startup()
        self.lift()
        try:
            self.attributes("-topmost", True)
            self.after(700, lambda: self.attributes("-topmost", False))
        except tk.TclError:
            pass
        try:
            self.focus_force()
        except tk.TclError:
            pass
        try:
            self.update_idletasks()
            self.update()
        except tk.TclError:
            pass

    def _migrate_flat_vr_profiles(self) -> None:
        profiles_root = Path(self.db_path).parent / "profiles"
        if not profiles_root.exists():
            return
        self.profiles_dir.mkdir(parents=True, exist_ok=True)
        for source in profiles_root.glob("*.json"):
            target = self.profiles_dir / source.name
            if not target.exists():
                shutil.move(str(source), str(target))
            else:
                source.unlink()

    def _configure_style(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TButton", padding=(10, 6))
        style.configure("Header.TLabel", font=("Segoe UI", 15, "bold"))
        style.configure("Hint.TLabel", foreground="#555")
        style.configure("Footer.TLabel", foreground="#555")

    def maximize_on_startup(self) -> None:
        try:
            self.state("zoomed")
        except tk.TclError:
            try:
                self.attributes("-zoomed", True)
            except tk.TclError:
                pass

    def _build(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill=tk.BOTH, expand=True)

        top = ttk.Frame(root)
        top.pack(fill=tk.X)
        ttk.Label(top, text=f"VR Study v{__version__}", style="Header.TLabel").pack(side=tk.LEFT)
        ttk.Label(top, textvariable=self.today_var).pack(side=tk.LEFT, padx=(16, 0))
        ttk.Label(top, textvariable=self.status_var).pack(side=tk.RIGHT)

        self.strategy_tabs = ttk.Notebook(root)
        self.strategy_tabs.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        dashboard_tab = ttk.Frame(self.strategy_tabs, padding=14)
        vr_tab = ttk.Frame(self.strategy_tabs, padding=14)
        infinite_tab = ttk.Frame(self.strategy_tabs, padding=14)
        telegram_tab = ttk.Frame(self.strategy_tabs, padding=14)
        self.dashboard_tab = dashboard_tab
        self.vr_tab = vr_tab
        self.infinite_tab = infinite_tab
        self.strategy_tabs.add(dashboard_tab, text="대시보드")
        self.strategy_tabs.add(vr_tab, text="VR")
        self.strategy_tabs.add(infinite_tab, text="무한매수법")
        self.strategy_tabs.add(telegram_tab, text="텔레그램")

        self._build_dashboard_tab(dashboard_tab)
        self._build_vr_tab(vr_tab)
        self._build_infinite_method_tab(infinite_tab)
        self._build_telegram_tab(telegram_tab)

        bottom = ttk.Frame(root, padding=(0, 8, 0, 0))
        bottom.pack(fill=tk.X)
        ttk.Label(bottom, text=f"v{__version__}", style="Footer.TLabel").pack(side=tk.LEFT)
        ttk.Button(
            bottom,
            text="\ub370\uc774\ud130 \ud3f4\ub354",
            command=self.open_data_folder,
        ).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Button(
            bottom,
            text="\ubc31\uc5c5 \ud3f4\ub354",
            command=self.open_backup_folder,
        ).pack(side=tk.LEFT, padx=(6, 0))
        ttk.Label(
            bottom,
            text="\uc790\ub3d9 \ubc31\uc5c5 / \uc21c\ucc28 \ud328\uce58 \uc900\ube44\ub428",
            style="Footer.TLabel",
        ).pack(side=tk.RIGHT)

    def _build_dashboard_tab(self, parent: ttk.Frame) -> None:
        content = self.create_dashboard_scroll_area(parent)
        content.columnconfigure(0, weight=1, uniform="dashboard_columns")
        content.columnconfigure(1, weight=1, uniform="dashboard_columns")
        content.rowconfigure(0, weight=1)
        content.rowconfigure(1, weight=1)
        content.rowconfigure(2, weight=0)
        content.rowconfigure(3, weight=0)
        content.rowconfigure(4, weight=1)

        overview_frame = ttk.LabelFrame(content, text="요약 메인화면", padding=8)
        due_frame = ttk.LabelFrame(content, text="\ub300\uae30 / \ubbf8\uc791\uc131 (0\uac1c)", padding=8)
        self.dashboard_due_frame = due_frame
        overview_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        due_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        self.dashboard_overview_tree = self.create_dashboard_summary_tree(overview_frame, height=9)
        self.dashboard_due_tree = self.create_dashboard_due_tree(due_frame, height=9)

        vr_summary_frame = ttk.LabelFrame(content, text="VR 상세", padding=8)
        infinite_summary_frame = ttk.LabelFrame(content, text="무한매수법 상세", padding=8)
        vr_summary_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(12, 0))
        infinite_summary_frame.grid(
            row=1, column=1, sticky="nsew", padx=(6, 0), pady=(12, 0)
        )

        self.dashboard_vr_summary_tree = self.create_dashboard_summary_tree(vr_summary_frame)
        self.dashboard_infinite_summary_tree = self.create_dashboard_summary_tree(
            infinite_summary_frame
        )

        graph_bar = ttk.Frame(content)
        graph_bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.dashboard_graph_toggle_button = ttk.Button(
            graph_bar,
            text="\uadf8\ub798\ud504 \ud3bc\uce58\uae30",
            command=self.toggle_dashboard_graphs,
        )
        self.dashboard_graph_toggle_button.pack(side=tk.LEFT)

        chart_groups = ttk.Frame(content)
        chart_groups.columnconfigure(0, weight=1, uniform="dashboard_columns")
        chart_groups.columnconfigure(1, weight=1, uniform="dashboard_columns")
        chart_groups.rowconfigure(0, weight=1)
        self.dashboard_graph_container = chart_groups
        vr_charts = ttk.LabelFrame(chart_groups, text="VR 그래프 분석", padding=6)
        infinite_charts = ttk.LabelFrame(chart_groups, text="무한매수법 그래프 분석", padding=6)
        vr_charts.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        infinite_charts.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        vr_chart_row = ttk.PanedWindow(vr_charts, orient=tk.HORIZONTAL)
        vr_chart_row.pack(fill=tk.BOTH, expand=True)
        self.add_dashboard_chart(vr_chart_row, "vr_band", "밴드와 자산")
        self.add_dashboard_chart(vr_chart_row, "vr_profit", "원금/계좌총액/손익")

        infinite_chart_row = ttk.PanedWindow(infinite_charts, orient=tk.HORIZONTAL)
        infinite_chart_row.pack(fill=tk.BOTH, expand=True)
        self.add_dashboard_chart(infinite_chart_row, "infinite_asset", "원금 대비 자산")
        self.add_dashboard_chart(infinite_chart_row, "infinite_profit", "누적수익/입출금")

        tables = ttk.Frame(content)
        tables.columnconfigure(0, weight=1, uniform="dashboard_columns")
        tables.columnconfigure(1, weight=1, uniform="dashboard_columns")
        tables.rowconfigure(0, weight=1)
        self.dashboard_tables_container = tables
        tables.grid(row=4, column=0, columnspan=2, sticky="nsew", pady=(12, 0))
        vr_frame = ttk.LabelFrame(tables, text="VR", padding=10)
        infinite_frame = ttk.LabelFrame(tables, text="무한매수법", padding=10)
        vr_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        infinite_frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        vr_columns = (
            "profile",
            "principal",
            "account_total",
            "profit",
            "return_rate",
            "last_done",
            "missing",
        )
        self.dashboard_vr_tree = ttk.Treeview(
            vr_frame, columns=vr_columns, show="headings", height=13
        )
        vr_headings = {
            "profile": "프로필",
            "principal": "원금",
            "account_total": "계좌총액",
            "profit": "수익금",
            "return_rate": "수익률",
            "last_done": "완료주차",
            "missing": "미입력",
        }
        self.configure_dashboard_tree(self.dashboard_vr_tree, vr_columns, vr_headings)
        self.dashboard_vr_tree.pack(fill=tk.BOTH, expand=True)
        self.dashboard_vr_tree.bind("<Double-1>", self.select_dashboard_vr_profile)

        infinite_columns = (
            "profile",
            "principal",
            "cumulative_amount",
            "cumulative_value",
            "return_rate",
            "avg_price",
            "missing",
        )
        self.dashboard_infinite_tree = ttk.Treeview(
            infinite_frame, columns=infinite_columns, show="headings", height=13
        )
        infinite_headings = {
            "profile": "프로필",
            "principal": "기준원금",
            "cumulative_amount": "누적매수액",
            "cumulative_value": "평가금",
            "return_rate": "수익률",
            "avg_price": "평단",
            "missing": "미입력",
        }
        self.configure_dashboard_tree(
            self.dashboard_infinite_tree, infinite_columns, infinite_headings
        )
        self.dashboard_infinite_tree.pack(fill=tk.BOTH, expand=True)
        self.dashboard_infinite_tree.bind("<Double-1>", self.select_dashboard_infinite_profile)

    def create_dashboard_scroll_area(self, parent: ttk.Frame) -> ttk.Frame:
        canvas = tk.Canvas(parent, highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=canvas.yview)
        content = ttk.Frame(canvas)
        window_id = canvas.create_window((0, 0), window=content, anchor=tk.NW)

        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.dashboard_scroll_canvas = canvas

        def update_scrollregion(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def match_width(event) -> None:
            canvas.itemconfigure(window_id, width=event.width, height=event.height)

        def on_mousewheel(event) -> None:
            canvas.yview_scroll(-int(event.delta / 120), "units")

        def bind_mousewheel(_event=None) -> None:
            canvas.bind_all("<MouseWheel>", on_mousewheel)

        def unbind_mousewheel(_event=None) -> None:
            canvas.unbind_all("<MouseWheel>")

        content.bind("<Configure>", update_scrollregion)
        canvas.bind("<Configure>", match_width)
        canvas.bind("<Enter>", bind_mousewheel)
        canvas.bind("<Leave>", unbind_mousewheel)
        parent.bind("<Enter>", bind_mousewheel)
        parent.bind("<Leave>", unbind_mousewheel)
        content.bind("<Enter>", bind_mousewheel)
        content.bind("<Leave>", unbind_mousewheel)
        return content

    def toggle_dashboard_graphs(self) -> None:
        if self.dashboard_graph_container is None:
            return
        self.dashboard_graphs_visible = not self.dashboard_graphs_visible
        content = self.dashboard_graph_container.master
        if self.dashboard_graphs_visible:
            content.rowconfigure(3, weight=1)
            self.dashboard_graph_container.grid(
                row=3, column=0, columnspan=2, sticky="nsew", pady=(8, 0)
            )
            if self.dashboard_graph_toggle_button is not None:
                self.dashboard_graph_toggle_button.configure(
                    text="\uadf8\ub798\ud504 \uc811\uae30"
                )
            for canvas in self.dashboard_chart_canvases.values():
                canvas.draw_idle()
        else:
            content.rowconfigure(3, weight=0)
            self.dashboard_graph_container.grid_forget()
            if self.dashboard_graph_toggle_button is not None:
                self.dashboard_graph_toggle_button.configure(
                    text="\uadf8\ub798\ud504 \ud3bc\uce58\uae30"
                )
        self.update_dashboard_scrollregion()

    def update_dashboard_scrollregion(self) -> None:
        if self.dashboard_scroll_canvas is None:
            return
        self.update_idletasks()
        self.dashboard_scroll_canvas.configure(
            scrollregion=self.dashboard_scroll_canvas.bbox("all")
        )

    def open_folder(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if os.name == "nt":
                os.startfile(path)
            else:
                raise RuntimeError(f"Open this folder manually: {path}")
        except Exception as exc:
            self.show_error(exc)

    def open_data_folder(self) -> None:
        self.open_folder(Path(self.db_path).parent)

    def open_backup_folder(self) -> None:
        self.open_folder(Path(self.db_path).parent / "backups")

    def create_dashboard_summary_tree(self, parent: ttk.Frame, height: int = 7) -> ttk.Treeview:
        tree = ttk.Treeview(parent, columns=("field", "value"), show="headings", height=height)
        tree.heading("field", text="항목")
        tree.heading("value", text="값")
        tree.column("field", width=180, anchor=tk.W)
        tree.column("value", width=260, anchor=tk.E)
        tree.tag_configure("separator", foreground="#777")
        tree.tag_configure(
            "summary_primary",
            foreground="#174A6F",
            font=("Segoe UI", 9, "bold"),
        )
        tree.tag_configure(
            "summary_profit_positive",
            foreground="#1F7A3A",
            font=("Segoe UI", 9, "bold"),
        )
        tree.tag_configure(
            "summary_profit_negative",
            foreground="#B42318",
            font=("Segoe UI", 9, "bold"),
        )
        tree.pack(fill=tk.BOTH, expand=True)
        return tree

    def create_dashboard_due_tree(self, parent: ttk.Frame, height: int = 7) -> ttk.Treeview:
        columns = ("strategy", "profile", "issue")
        tree = ttk.Treeview(parent, columns=columns, show="headings", height=height)
        headings = {
            "strategy": "구분",
            "profile": "프로필",
            "issue": "내용",
        }
        for column in columns:
            tree.heading(column, text=headings[column])
            tree.column(column, width=110, anchor=tk.W)
        tree.column("profile", width=180, anchor=tk.W)
        tree.column("issue", width=360, anchor=tk.W)
        tree.tag_configure("due", foreground="#9A3412")
        tree.tag_configure("empty", foreground="#777")
        tree.pack(fill=tk.BOTH, expand=True)
        tree.bind("<Double-1>", self.open_dashboard_due_item)
        return tree

    def add_dashboard_chart(
        self, parent: ttk.PanedWindow, key: str, title: str
    ) -> None:
        frame = ttk.LabelFrame(parent, text=title, padding=4)
        figure = Figure(figsize=(5.1, 2.4), dpi=100)
        axis = figure.add_subplot(111)
        canvas = FigureCanvasTkAgg(figure, master=frame)
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
        parent.add(frame, weight=1)
        self.dashboard_chart_axes[key] = axis
        self.dashboard_chart_canvases[key] = canvas

    @staticmethod
    def configure_dashboard_tree(
        tree: ttk.Treeview, columns: tuple[str, ...], headings: dict[str, str]
    ) -> None:
        for column in columns:
            tree.heading(column, text=headings[column])
            width = 105
            anchor = tk.E
            if column == "profile":
                width = 160
                anchor = tk.W
            elif column in {"last_done", "missing"}:
                width = 72
                anchor = tk.CENTER
            tree.column(column, width=width, anchor=anchor)

    def _build_vr_tab(self, parent: ttk.Frame) -> None:
        profile_bar = ttk.Frame(parent, padding=(0, 0, 0, 8))
        profile_bar.pack(fill=tk.X)
        ttk.Label(profile_bar, text="프로필").pack(side=tk.LEFT)
        self.profile_combo = ttk.Combobox(
            profile_bar, textvariable=self.profile_var, width=28, state="readonly"
        )
        self.profile_combo.pack(side=tk.LEFT, padx=(8, 8))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_profile_to_form())
        ttk.Button(profile_bar, text="새 프로필", command=self.create_profile_dialog).pack(side=tk.LEFT, padx=3)
        ttk.Button(profile_bar, text="이름 변경", command=self.rename_profile_dialog).pack(side=tk.LEFT, padx=3)
        ttk.Button(profile_bar, text="삭제", command=self.delete_profile_dialog).pack(side=tk.LEFT, padx=3)
        ttk.Button(profile_bar, text="새로고침", command=self.reload_profiles).pack(side=tk.LEFT, padx=3)
        ttk.Button(profile_bar, text="현재조회", command=self.goto_current_vr_row).pack(side=tk.LEFT, padx=3)
        self.pause_vr_button = ttk.Button(
            profile_bar, text="산출 중단", command=self.toggle_vr_calculation_paused
        )
        self.pause_vr_button.pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Label(profile_bar, textvariable=self.cycle_status_var).pack(side=tk.RIGHT)

        main = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, padding=(0, 0, 12, 0), width=430)
        right = ttk.Frame(main, padding=(0, 0, 0, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        right.rowconfigure(2, weight=1)
        main.add(left, weight=0)
        main.add(right, weight=1)

        tabs = ttk.Notebook(left)
        tabs.pack(fill=tk.BOTH, expand=True)

        settings_tab = ttk.Frame(tabs, padding=8)
        cycle_tab = ttk.Frame(tabs, padding=8)
        order_tab = ttk.Frame(tabs, padding=8)
        api_tab = ttk.Frame(tabs, padding=8)
        fill_tab = ttk.Frame(tabs, padding=8)
        tabs.add(settings_tab, text="프로필 설정")
        tabs.add(cycle_tab, text="주차 결과 입력")
        tabs.add(order_tab, text="매수/매도점 옵션")
        tabs.add(api_tab, text="API 키")
        tabs.add(fill_tab, text="체결내역")

        self._build_settings(settings_tab)
        self._build_cycle_input(cycle_tab)
        self._build_order_options(order_tab)
        self._build_kiwoom_api_settings(api_tab, "vr")
        self._build_vr_fill_history(fill_tab)
        self._build_cycle_rows(right, grid_row=0)
        self._build_summary(right, grid_row=1)
        self._build_order_table(right, grid_row=2)

        self.after_idle(lambda: main.sashpos(0, 430))

    def _build_infinite_method_tab(self, parent: ttk.Frame) -> None:
        profile_bar = ttk.Frame(parent, padding=(0, 0, 0, 8))
        profile_bar.pack(fill=tk.X)
        ttk.Label(profile_bar, text="프로필").pack(side=tk.LEFT)
        self.infinite_profile_combo = ttk.Combobox(
            profile_bar, textvariable=self.infinite_profile_var, width=28, state="readonly"
        )
        self.infinite_profile_combo.pack(side=tk.LEFT, padx=(8, 8))
        self.infinite_profile_combo.bind("<<ComboboxSelected>>", lambda _event: self.load_infinite_to_form())
        ttk.Button(profile_bar, text="새 프로필", command=self.create_infinite_profile_dialog).pack(side=tk.LEFT, padx=3)
        ttk.Button(profile_bar, text="이름 변경", command=self.rename_infinite_profile_dialog).pack(side=tk.LEFT, padx=3)
        ttk.Button(profile_bar, text="삭제", command=self.delete_infinite_profile_dialog).pack(side=tk.LEFT, padx=3)
        ttk.Button(profile_bar, text="새로고침", command=self.reload_infinite_profiles).pack(side=tk.LEFT, padx=3)
        ttk.Button(profile_bar, text="현재조회", command=self.goto_current_infinite_row).pack(side=tk.LEFT, padx=3)
        self.pause_infinite_button = ttk.Button(
            profile_bar, text="산출 중단", command=self.toggle_infinite_calculation_paused
        )
        self.pause_infinite_button.pack(side=tk.RIGHT, padx=(8, 0))

        main = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main, width=430)
        right = ttk.Frame(main)
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        main.add(left, weight=0)
        main.add(right, weight=1)

        tabs = ttk.Notebook(left)
        tabs.pack(fill=tk.BOTH, expand=True)

        settings_tab = ttk.Frame(tabs, padding=8)
        execution_tab = ttk.Frame(tabs, padding=8)
        api_tab = ttk.Frame(tabs, padding=8)
        tabs.add(settings_tab, text="\ud504\ub85c\ud544 \uc124\uc815")
        tabs.add(execution_tab, text="\uccb4\uacb0 \uc785\ub825")
        tabs.add(api_tab, text="API 키")

        settings = ttk.LabelFrame(settings_tab, text="프로필 설정", padding=10)
        settings.pack(fill=tk.X)
        fields = [
            ("account_number", "계좌번호", ""),
            ("symbol", "종목", "TQQQ"),
            ("start_date", "차수 시작일", "2026-05-27"),
            ("initial_principal", "차수 시작원금", "150000"),
            ("initial_cumulative_amount", "초기 누적매수액", "0"),
            ("initial_cumulative_qty", "초기 누적개수", "0"),
            ("target_rate", "수익기준율", "10%"),
            ("split_count", "분할 수", "40"),
            ("fee_rate", "수수료", "0.044%"),
            ("mode", "방식", "기본"),
        ]
        for row, (key, label, default) in enumerate(fields):
            ttk.Label(settings, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar(value=default)
            self.infinite_fields[key] = var
            if key == "symbol":
                entry = ttk.Combobox(
                    settings,
                    textvariable=var,
                    values=INFINITE_SYMBOLS,
                    state="readonly",
                    width=18,
                )
            elif key == "mode":
                entry = ttk.Combobox(
                    settings,
                    textvariable=var,
                    values=("기본", "반복리"),
                    state="readonly",
                    width=18,
                )
            else:
                entry = ttk.Entry(settings, textvariable=var, width=20)
            entry.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        settings.columnconfigure(1, weight=1)
        ttk.Button(settings, text="설정 저장/재계산", command=self.save_infinite_settings).grid(
            row=len(fields), column=0, columnspan=2, sticky=tk.EW, pady=(10, 0)
        )

        execution = ttk.LabelFrame(execution_tab, text="전일 체결 결과 입력", padding=10)
        execution.pack(fill=tk.X)
        input_fields = [
            ("trade_date", "입력일", ""),
            ("avg_price", "평균단가", ""),
            ("buy_qty", "매수개수", "0"),
            ("sell_qty", "매도개수", "0"),
            ("cash_flow_amount", "입출금액", "0"),
        ]
        for row, (key, label, default) in enumerate(input_fields):
            label_text = f"{label} (+입금, -출금)" if key == "cash_flow_amount" else label
            ttk.Label(execution, text=label_text).grid(row=row, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar(value=default)
            self.infinite_input_fields[key] = var
            if key == "trade_date":
                var.trace_add(
                    "write",
                    lambda *_args: self.after_idle(self.update_infinite_execution_guard),
                )
            ttk.Entry(execution, textvariable=var, width=20).grid(
                row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2
            )
        execution.columnconfigure(1, weight=1)
        self.save_infinite_execution_button = ttk.Button(
            execution,
            text="체결 저장하고 다음날 주문표 보기",
            command=self.save_infinite_execution,
        )
        self.save_infinite_execution_button.grid(
            row=len(input_fields), column=0, columnspan=2, sticky=tk.EW, pady=(10, 0)
        )
        self.save_infinite_execution_button.configure(
            text="체결 저장하고 금일 주문표 보기"
        )
        ttk.Button(execution, text="새로고침", command=self.refresh_infinite_tab).grid(
            row=len(input_fields) + 1, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0)
        )

        self._build_kiwoom_api_settings(api_tab, "infinite")

        status_frame = ttk.LabelFrame(settings_tab, text="오늘 상태뷰", padding=10)
        status_frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        self.infinite_status_tree = ttk.Treeview(
            status_frame, columns=("field", "value"), show="headings", height=17
        )
        self.infinite_status_tree.heading("field", text="항목")
        self.infinite_status_tree.heading("value", text="값")
        self.infinite_status_tree.column("field", width=100, minwidth=70, anchor=tk.W, stretch=False)
        self.infinite_status_tree.column("value", width=180, minwidth=80, anchor=tk.E, stretch=True)
        self.infinite_status_tree.bind("<Configure>", self.resize_infinite_status_columns)
        self.infinite_status_tree.grid(row=0, column=0, sticky="nsew")
        status_frame.rowconfigure(0, weight=1)
        status_frame.columnconfigure(0, weight=1)

        rows_frame = ttk.LabelFrame(right, text="일별 로우데이터", padding=10)
        rows_frame.grid(row=0, column=0, sticky="nsew")
        columns = (
            "no",
            "trade_date",
            "weekday",
            "close_price",
            "avg_price",
            "buy_qty",
            "sell_qty",
            "principal_before_withdrawal",
            "cash_flow_amount",
            "principal_after_withdrawal",
            "cumulative_qty",
            "t_value",
            "star_price",
            "return_rate",
            "fee",
            "stop_loss",
            "trade_amount",
            "cumulative_amount",
        )
        self.infinite_rows_tree = ttk.Treeview(rows_frame, columns=columns, show="headings", height=12)
        headings = {
            "no": "NO",
            "trade_date": "일자",
            "weekday": "요일",
            "close_price": "종가",
            "avg_price": "평단",
            "buy_qty": "매수",
            "sell_qty": "매도",
            "principal_before_withdrawal": "입출금전 원금",
            "cash_flow_amount": "입출금",
            "principal_after_withdrawal": "입출금후 원금",
            "cumulative_qty": "누적개수",
            "t_value": "회차T",
            "star_price": "별지점",
            "return_rate": "수익률",
            "fee": "수수료",
            "stop_loss": "수익금",
            "trade_amount": "매수액",
            "cumulative_amount": "누적매수액",
        }
        for column in columns:
            self.infinite_rows_tree.heading(column, text=headings[column])
            self.infinite_rows_tree.column(column, width=95, anchor=tk.E)
        self.infinite_rows_tree.column("no", width=55, anchor=tk.CENTER)
        self.infinite_rows_tree.column("trade_date", anchor=tk.CENTER)
        self.infinite_rows_tree.column("weekday", width=55, anchor=tk.CENTER)
        yscroll = ttk.Scrollbar(rows_frame, orient=tk.VERTICAL, command=self.infinite_rows_tree.yview)
        xscroll = ttk.Scrollbar(rows_frame, orient=tk.HORIZONTAL, command=self.infinite_rows_tree.xview)
        self.infinite_rows_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.infinite_rows_tree.grid(row=0, column=0, sticky="nsew")
        self.infinite_rows_tree.bind("<Double-1>", self.load_infinite_row_to_input)
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        rows_frame.rowconfigure(0, weight=1)
        rows_frame.columnconfigure(0, weight=1)

        orders = ttk.LabelFrame(right, text="다음 주문표", padding=10)
        orders.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        orders.configure(text="금일 주문표")
        order_header = ttk.Frame(orders)
        order_header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(order_header, textvariable=self.infinite_order_info_var).pack(
            side=tk.LEFT, fill=tk.X, expand=True
        )
        self.infinite_order_execute_button = ttk.Button(
            order_header,
            text="주문실행",
            command=self.execute_infinite_orders,
        )
        self.infinite_order_execute_button.pack(side=tk.RIGHT, padx=(8, 0))
        self.infinite_order_execute_after_input_button = ttk.Button(
            order_header,
            text="체결입력 후 주문실행",
            command=self.execute_infinite_after_api_input,
        )
        self.infinite_order_execute_after_input_button.pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Label(
            orders,
            textvariable=self.infinite_order_api_status_var,
            style="Hint.TLabel",
        ).pack(fill=tk.X, pady=(0, 6))
        order_columns = ("side", "order_type", "price", "quantity")
        self.infinite_order_tree = ttk.Treeview(orders, columns=order_columns, show="headings", height=10)
        for column, label in {
            "side": "구분",
            "order_type": "주문",
            "price": "가격",
            "quantity": "개수",
        }.items():
            self.infinite_order_tree.heading(column, text=label)
            self.infinite_order_tree.column(column, width=110, anchor=tk.CENTER)
        self.infinite_order_tree.tag_configure("buy_order", background="#FDECEC")
        self.infinite_order_tree.tag_configure("sell_order", background="#EAF2FF")
        self.infinite_order_tree.tag_configure(
            "order_separator", background="#D8D5CE", foreground="#555555"
        )
        self.infinite_order_tree.pack(fill=tk.BOTH, expand=True)

        self.after_idle(lambda: main.sashpos(0, 430))
        self.after_idle(self.load_infinite_to_form)

    def _build_kiwoom_api_settings(self, parent: ttk.Frame, profile_kind: str) -> None:
        frame = ttk.LabelFrame(parent, text="키움 REST API 키", padding=12)
        frame.pack(fill=tk.X)
        fields = [
            ("investment_type", "투자 구분", "실전투자"),
            ("account_number", "계좌번호", ""),
            ("app_key", "App Key", ""),
            ("app_secret", "App Secret", ""),
            ("expires_at", "만료일", ""),
            ("memo", "메모", ""),
        ]
        field_vars: dict[str, tk.StringVar] = {}
        for row, (key, label, default) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=4)
            var = tk.StringVar(value=default)
            field_vars[key] = var
            if key == "investment_type":
                entry = ttk.Combobox(
                    frame,
                    textvariable=var,
                    values=("실전투자", "모의투자"),
                    state="readonly",
                    width=20,
                )
            else:
                show = "*" if key == "app_secret" else ""
                entry = ttk.Entry(frame, textvariable=var, width=42, show=show)
            entry.grid(row=row, column=1, sticky=tk.EW, padx=(10, 0), pady=4)
        frame.columnconfigure(1, weight=1)
        self.kiwoom_api_fields[profile_kind] = field_vars

        button_frame = ttk.Frame(frame)
        button_frame.grid(row=len(fields), column=0, columnspan=2, sticky=tk.EW, pady=(12, 0))
        ttk.Button(
            button_frame,
            text="API 키 저장",
            command=lambda kind=profile_kind: self.save_kiwoom_api_credentials(kind),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Button(
            button_frame,
            text="토큰 발급 테스트",
            command=lambda kind=profile_kind: self.test_kiwoom_access_token(kind),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))
        ttk.Button(
            button_frame,
            text="다시 불러오기",
            command=lambda kind=profile_kind: self.load_kiwoom_api_credentials(kind),
        ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(8, 0))

        status_var = tk.StringVar(value="")
        self.kiwoom_api_status_vars[profile_kind] = status_var
        ttk.Label(frame, textvariable=status_var, style="Hint.TLabel", wraplength=360).grid(
            row=len(fields) + 1,
            column=0,
            columnspan=2,
            sticky=tk.EW,
            pady=(8, 0),
        )

        if profile_kind == "infinite":
            self._build_infinite_kiwoom_execution_preview(parent)
            self._build_infinite_kiwoom_balance_lookup(parent)
        if profile_kind == "vr":
            self._build_vr_kiwoom_period_lookup(parent)

        ttk.Label(
            parent,
            text=(
                f"키 저장: {kiwoom_credentials_path()}\n"
                f"토큰 캐시: {kiwoom_token_cache_path()}"
            ),
            style="Hint.TLabel",
            wraplength=360,
        ).pack(fill=tk.X, pady=(8, 0))

    def _build_vr_kiwoom_period_lookup(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="VR 결과구간 API 검증", padding=12)
        frame.pack(fill=tk.X, pady=(12, 0))

        fields = [
            ("sell_qty", "매도수량 합계", "0"),
            ("sell_amount", "매도액 USD", "0"),
            ("buy_qty", "매수수량 합계", "0"),
            ("buy_amount", "매수액 USD", "0"),
            ("holding_qty", "현재 보유개수", "0"),
            ("period_end_holding_qty", "기간말 추정보유개수", "0"),
        ]
        for row, (key, label, default) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar(value=default)
            self.kiwoom_vr_period_fields[key] = var
            ttk.Entry(frame, textvariable=var, width=22, state="readonly").grid(
                row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2
            )

        ttk.Button(
            frame,
            text="호출",
            command=self.call_vr_kiwoom_period_lookup,
        ).grid(row=0, column=2, rowspan=2, sticky="nsew", padx=(10, 0), pady=2)

        ttk.Label(
            frame,
            textvariable=self.kiwoom_vr_period_status_var,
            style="Hint.TLabel",
            wraplength=360,
        ).grid(row=len(fields), column=0, columnspan=3, sticky=tk.EW, pady=(8, 0))
        frame.columnconfigure(1, weight=1)

    def _build_vr_fill_history(self, parent: ttk.Frame) -> None:
        header = ttk.Frame(parent)
        header.pack(fill=tk.X)
        ttk.Label(header, textvariable=self.kiwoom_vr_fill_period_var).pack(
            side=tk.LEFT
        )
        ttk.Button(
            header,
            text="지난차수 조회",
            command=lambda: self.call_vr_kiwoom_fill_history("previous"),
        ).pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Button(
            header,
            text="현재차수 조회",
            command=lambda: self.call_vr_kiwoom_fill_history("current"),
        ).pack(side=tk.RIGHT)

        fill_frame = ttk.LabelFrame(parent, text="대상기간 체결내역", padding=8)
        fill_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))
        columns = (
            "date",
            "side",
            "price",
            "quantity",
            "amount",
            "order_no",
            "order_quantity",
            "status",
        )
        self.kiwoom_vr_fill_tree = ttk.Treeview(
            fill_frame,
            columns=columns,
            show="headings",
            height=12,
        )
        headings = {
            "date": "날짜",
            "side": "구분",
            "price": "체결가",
            "quantity": "체결수량",
            "amount": "체결금액",
            "order_no": "주문번호",
            "order_quantity": "원주문수량",
            "status": "상태",
        }
        widths = {
            "date": 92,
            "side": 54,
            "price": 76,
            "quantity": 70,
            "amount": 88,
            "order_no": 120,
            "order_quantity": 78,
            "status": 110,
        }
        for column in columns:
            self.kiwoom_vr_fill_tree.heading(column, text=headings[column])
            anchor = tk.CENTER if column in {"date", "side", "status"} else tk.E
            if column == "order_no":
                anchor = tk.W
            self.kiwoom_vr_fill_tree.column(
                column, width=widths[column], anchor=anchor
            )
        yscroll = ttk.Scrollbar(
            fill_frame, orient=tk.VERTICAL, command=self.kiwoom_vr_fill_tree.yview
        )
        xscroll = ttk.Scrollbar(
            fill_frame, orient=tk.HORIZONTAL, command=self.kiwoom_vr_fill_tree.xview
        )
        self.kiwoom_vr_fill_tree.configure(
            yscrollcommand=yscroll.set,
            xscrollcommand=xscroll.set,
        )
        self.kiwoom_vr_fill_tree.tag_configure(
            "date_separator", background="#D8D5CE", foreground="#333333"
        )
        self.kiwoom_vr_fill_tree.tag_configure("buy_fill", background="#FDECEC")
        self.kiwoom_vr_fill_tree.tag_configure("sell_fill", background="#EAF2FF")
        self.kiwoom_vr_fill_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        fill_frame.rowconfigure(0, weight=1)
        fill_frame.columnconfigure(0, weight=1)

        summary_frame = ttk.LabelFrame(parent, text="가격별 차감 기준", padding=8)
        summary_frame.pack(fill=tk.X, pady=(8, 0))
        summary_columns = ("side", "price", "quantity", "amount")
        self.kiwoom_vr_fill_summary_tree = ttk.Treeview(
            summary_frame,
            columns=summary_columns,
            show="headings",
            height=5,
        )
        summary_headings = {
            "side": "구분",
            "price": "체결가",
            "quantity": "합산수량",
            "amount": "합산금액",
        }
        for column in summary_columns:
            self.kiwoom_vr_fill_summary_tree.heading(
                column, text=summary_headings[column]
            )
            self.kiwoom_vr_fill_summary_tree.column(
                column,
                width=86,
                anchor=tk.CENTER if column == "side" else tk.E,
            )
        self.kiwoom_vr_fill_summary_tree.pack(fill=tk.X)

        ttk.Label(
            parent,
            textvariable=self.kiwoom_vr_fill_status_var,
            style="Hint.TLabel",
            wraplength=380,
        ).pack(fill=tk.X, pady=(8, 0))

    def call_vr_kiwoom_fill_history(self, period_kind: str = "current") -> None:
        profile_kind = "vr"
        profile_name = self.kiwoom_profile_name(profile_kind)
        try:
            credentials = self.current_kiwoom_credentials_from_form(profile_kind)
            credentials = self.safe_save_kiwoom_credentials(
                profile_kind, profile_name, credentials
            )
            profile = self.current_profile()
            symbol = profile.symbol.upper()
            query_day = date.today()
            cycle_no, dates = self.vr_fill_lookup_period(
                profile, query_day, period_kind
            )
            start_day = dates.result_start
            end_day = (
                min(query_day, dates.result_end)
                if period_kind == "current"
                else dates.result_end
            )
            if end_day < start_day:
                raise ValueError("조회 가능한 VR 주문구간이 아직 시작되지 않았습니다.")

            period_label = "현재차수" if period_kind == "current" else "지난차수"
            period_text = (
                f"{period_label} 주문표 기간: {start_day} ~ {dates.result_end} "
                f"(조회 {start_day} ~ {end_day})"
            )
            self.kiwoom_vr_fill_period_var.set(period_text)
            self.kiwoom_vr_fill_status_var.set("토큰 확인 중...")
            self.update_idletasks()
            token, renewed = ensure_access_token(profile_kind, profile_name, credentials)
            stex_tp = self.resolve_kiwoom_us_exchange_code(
                credentials, token, symbol
            )

            self.kiwoom_vr_fill_status_var.set("체결내역 조회 중...")
            self.update_idletasks()
            orders = request_us_period_order_history(
                credentials,
                token,
                start_date=start_day.strftime("%Y%m%d"),
                end_date=end_day.strftime("%Y%m%d"),
                slby_tp="0",
                stex_tp=stex_tp,
                stk_cd=symbol,
                oppo_trde_tp="%",
            )
            fill_rows = self.vr_fill_history_rows(self.result_rows(orders), symbol)
            summary_rows = self.vr_fill_price_summary(fill_rows)
            self.kiwoom_vr_fill_result = {
                "profile": profile_name,
                "symbol": symbol,
                "cycle_no": cycle_no,
                "period_kind": period_kind,
                "order_period": {
                    "start_date": start_day.strftime("%Y%m%d"),
                    "end_date": dates.result_end.strftime("%Y%m%d"),
                    "query_end_date": end_day.strftime("%Y%m%d"),
                },
                "token_renewed": renewed,
                "fills": fill_rows,
                "price_summary": summary_rows,
                "orders": orders,
            }
            self.refresh_vr_fill_history_tree(fill_rows, summary_rows)
            token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
            self.kiwoom_vr_fill_status_var.set(
                f"{period_label} 조회 성공: {symbol} / 체결 {len(fill_rows)}건 / {token_state}"
            )
            self.set_status(f"키움 VR {period_label} 체결내역 조회 성공: {profile_name}")
        except KiwoomApiError as exc:
            message = self.format_kiwoom_error("VR 체결내역 조회 실패", exc)
            self.kiwoom_vr_fill_status_var.set(message)
            self.set_status(f"키움 VR 체결내역 조회 실패: {profile_name}")
        except Exception as exc:
            self.kiwoom_vr_fill_status_var.set(f"VR 체결내역 조회 실패: {exc}")
            self.show_error(exc)

    def call_vr_kiwoom_period_lookup(self) -> None:
        profile_kind = "vr"
        profile_name = self.kiwoom_profile_name(profile_kind)
        try:
            credentials = self.current_kiwoom_credentials_from_form(profile_kind)
            credentials = self.safe_save_kiwoom_credentials(
                profile_kind, profile_name, credentials
            )
            profile = self.current_profile()
            symbol = profile.symbol.upper()
            query_day = date.today()
            cycle_no, dates = self.latest_completed_vr_result_period(profile, query_day)
            start_day = dates.result_start.strftime("%Y%m%d")
            end_day = dates.result_end.strftime("%Y%m%d")

            self.kiwoom_vr_period_status_var.set("토큰 확인 중...")
            self.update_idletasks()
            token, renewed = ensure_access_token(profile_kind, profile_name, credentials)
            stex_tp = self.resolve_kiwoom_us_exchange_code(
                credentials, token, symbol
            )

            self.kiwoom_vr_period_status_var.set("결과구간 조회 중...")
            self.update_idletasks()
            orders = request_us_period_order_history(
                credentials,
                token,
                start_date=start_day,
                end_date=end_day,
                slby_tp="0",
                stex_tp=stex_tp,
                stk_cd=symbol,
                oppo_trde_tp="%",
            )
            balance = request_us_ledger_balance(
                credentials, token, stex_tp=stex_tp, stk_cd=symbol
            )
            after_start_day = dates.result_end + timedelta(days=1)
            after_orders = request_us_period_order_history(
                credentials,
                token,
                start_date=after_start_day.strftime("%Y%m%d"),
                end_date=query_day.strftime("%Y%m%d"),
                slby_tp="0",
                stex_tp=stex_tp,
                stk_cd=symbol,
                oppo_trde_tp="%",
            )
            preview = self.build_vr_period_preview(
                symbol, orders, balance, after_orders
            )
            self.kiwoom_vr_period_result = {
                "profile": profile_name,
                "symbol": symbol,
                "cycle_no": cycle_no,
                "result_period": {
                    "start_date": start_day,
                    "end_date": end_day,
                },
                "token_renewed": renewed,
                "preview": preview,
                "orders": orders,
                "after_orders": after_orders,
                "balance": balance,
            }
            for key, value in preview.items():
                field = self.kiwoom_vr_period_fields.get(key)
                if field is not None:
                    field.set(str(value))
            token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
            self.kiwoom_vr_period_status_var.set(
                f"조회 성공: {symbol} / 기준일 {query_day} / 대상 {dates.result_start}~{dates.result_end} / {token_state}"
            )
            self.set_status(f"키움 VR 결과구간 조회 성공: {profile_name}")
        except KiwoomApiError as exc:
            message = self.format_kiwoom_error("VR 결과구간 조회 실패", exc)
            self.kiwoom_vr_period_status_var.set(message)
            self.set_status(f"키움 VR 결과구간 조회 실패: {profile_name}")
        except Exception as exc:
            self.kiwoom_vr_period_status_var.set(f"VR 결과구간 조회 실패: {exc}")
            self.show_error(exc)

    def build_vr_period_preview(
        self, symbol: str, orders: dict, balance: dict, after_orders: dict
    ) -> dict:
        order_summary = self.summarize_order_period(self.result_rows(orders), symbol)
        after_order_summary = self.summarize_order_period(
            self.result_rows(after_orders), symbol
        )
        balance_row = self.find_symbol_row(self.result_rows(balance), symbol)
        holding_qty = self.clean_int(
            balance_row.get("poss_qty")
            or balance_row.get("qty")
            or balance_row.get("evlt_qty")
        )
        period_end_holding_qty = (
            holding_qty
            - after_order_summary["buy_qty"]
            + after_order_summary["sell_qty"]
        )
        return {
            "sell_qty": order_summary["sell_qty"],
            "sell_amount": self.clean_number_text(round(order_summary["sell_amount"], 4)),
            "buy_qty": order_summary["buy_qty"],
            "buy_amount": self.clean_number_text(round(order_summary["buy_amount"], 4)),
            "holding_qty": holding_qty,
            "period_end_holding_qty": period_end_holding_qty,
        }

    def vr_fill_history_rows(self, rows: list[dict], symbol: str) -> list[dict]:
        symbol = symbol.upper()
        fill_rows: list[dict] = []
        for row in rows:
            row_symbol = str(row.get("stk_cd") or "").upper()
            if row_symbol and row_symbol != symbol:
                continue
            quantity = self.order_contract_quantity(row)
            if quantity <= 0:
                continue
            side = self.order_side(row)
            if side not in {"buy", "sell"}:
                continue
            price = self.clean_float(
                self.first_row_value(row, "cntr_uv", "cntr_pric", "avg_pric", "ord_uv")
            )
            amount = self.clean_float(
                self.first_row_value(row, "cntr_amt", "exec_amt", "trde_amt")
            )
            if amount == 0 and price:
                amount = quantity * price
            trade_date = str(
                self.first_row_value(row, "cntr_dt", "ord_dt", "trde_dt") or ""
            ).strip()
            order_no = str(
                self.first_row_value(row, "ord_no", "odno", "orgn_ord_no") or ""
            ).strip()
            order_quantity = self.clean_int(row.get("ord_qty"))
            status = str(
                self.first_row_value(
                    row,
                    "ord_stt_nm",
                    "ord_stat_nm",
                    "cntr_tp_nm",
                    "trde_tp_nm",
                    "ord_stt",
                )
                or ""
            ).strip()
            fill_rows.append(
                {
                    "date": trade_date,
                    "side": side,
                    "side_label": "매수" if side == "buy" else "매도",
                    "price": price,
                    "price_key": f"{round(price, 2):.2f}" if price else "",
                    "quantity": quantity,
                    "amount": abs(amount),
                    "order_no": order_no,
                    "order_quantity": order_quantity,
                    "status": status,
                    "raw": row,
                }
            )
        return sorted(
            fill_rows,
            key=lambda item: (
                str(item.get("date") or ""),
                str(item.get("side") or ""),
                float(item.get("price") or 0),
                str(item.get("order_no") or ""),
            ),
        )

    def vr_fill_price_summary(self, fill_rows: list[dict]) -> list[dict]:
        summary: dict[tuple[str, str], dict] = {}
        for row in fill_rows:
            key = (str(row.get("side") or ""), str(row.get("price_key") or ""))
            if not key[0] or not key[1]:
                continue
            item = summary.setdefault(
                key,
                {
                    "side": key[0],
                    "side_label": row.get("side_label") or "",
                    "price": row.get("price") or 0,
                    "quantity": 0,
                    "amount": 0.0,
                },
            )
            item["quantity"] += int(row.get("quantity") or 0)
            item["amount"] += float(row.get("amount") or 0)
        return sorted(
            summary.values(),
            key=lambda item: (
                0 if item.get("side") == "buy" else 1,
                float(item.get("price") or 0),
            ),
        )

    def refresh_vr_fill_history_tree(
        self, fill_rows: list[dict], summary_rows: list[dict]
    ) -> None:
        if (
            self.kiwoom_vr_fill_tree is None
            or self.kiwoom_vr_fill_summary_tree is None
        ):
            return
        for tree in (self.kiwoom_vr_fill_tree, self.kiwoom_vr_fill_summary_tree):
            for item in tree.get_children():
                tree.delete(item)

        last_date = ""
        for row in fill_rows:
            trade_date = str(row.get("date") or "")
            display_date = self.format_api_date(trade_date)
            if display_date != last_date:
                self.kiwoom_vr_fill_tree.insert(
                    "",
                    tk.END,
                    values=(f"{display_date} 체결내역", "", "", "", "", "", "", ""),
                    tags=("date_separator",),
                )
                last_date = display_date
            side = row.get("side")
            tag = "buy_fill" if side == "buy" else "sell_fill"
            self.kiwoom_vr_fill_tree.insert(
                "",
                tk.END,
                values=(
                    "",
                    row.get("side_label") or "",
                    self.clean_number_text(row.get("price")),
                    row.get("quantity") or 0,
                    self.clean_number_text(row.get("amount")),
                    row.get("order_no") or "",
                    row.get("order_quantity") or "",
                    row.get("status") or "",
                ),
                tags=(tag,),
            )

        for row in summary_rows:
            self.kiwoom_vr_fill_summary_tree.insert(
                "",
                tk.END,
                values=(
                    row.get("side_label") or "",
                    self.clean_number_text(row.get("price")),
                    row.get("quantity") or 0,
                    self.clean_number_text(row.get("amount")),
                ),
            )

    def latest_completed_vr_result_period(
        self, profile: Profile, query_day: date
    ) -> tuple[int, object]:
        start_day = date.fromisoformat(profile.start_date)
        latest: tuple[int, object] | None = None
        cycle_no = 0
        while cycle_no < 10000:
            dates = cycle_dates(start_day, cycle_no)
            if dates.result_end >= query_day:
                break
            latest = (cycle_no, dates)
            cycle_no += 1
        if latest is None:
            raise ValueError("조회일 기준으로 완료된 VR 결과구간이 아직 없습니다.")
        return latest

    def current_vr_order_period(self, profile: Profile, query_day: date) -> tuple[int, object]:
        start_day = date.fromisoformat(profile.start_date)
        latest: tuple[int, object] | None = None
        cycle_no = 0
        while cycle_no < 10000:
            dates = cycle_dates(start_day, cycle_no)
            if dates.result_start > query_day:
                break
            latest = (cycle_no, dates)
            cycle_no += 1
        if latest is None:
            raise ValueError("조회일 기준으로 시작된 VR 주문표 기간이 아직 없습니다.")
        return latest

    def vr_fill_lookup_period(
        self, profile: Profile, query_day: date, period_kind: str
    ) -> tuple[int, object]:
        cycle_no, dates = self.current_vr_order_period(profile, query_day)
        if period_kind == "current":
            return cycle_no, dates
        if period_kind != "previous":
            raise ValueError(f"지원하지 않는 체결내역 조회 구분입니다: {period_kind}")
        previous_cycle_no = cycle_no - 1
        if previous_cycle_no < 0:
            raise ValueError("조회 가능한 지난차수 VR 주문표 기간이 아직 없습니다.")
        start_day = date.fromisoformat(profile.start_date)
        return previous_cycle_no, cycle_dates(start_day, previous_cycle_no)

    @staticmethod
    def first_row_value(row: dict, *keys: str):
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return value
        return ""

    def order_contract_quantity(self, row: dict) -> int:
        return self.clean_int(
            self.first_row_value(row, "cntr_qty", "exec_qty", "cntr_qy")
        )

    def _build_infinite_kiwoom_execution_preview(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="체결입력정보 조회", padding=12)
        frame.pack(fill=tk.X, pady=(12, 0))

        fields = [
            ("trade_date", "입력일", ""),
            ("avg_price", "평균단가", ""),
            ("buy_qty", "매수개수", "0"),
            ("sell_qty", "매도개수", "0"),
        ]
        for row, (key, label, default) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar(value=default)
            self.kiwoom_execution_preview_fields[key] = var
            ttk.Entry(frame, textvariable=var, width=22, state="readonly").grid(
                row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2
            )

        ttk.Button(
            frame,
            text="호출",
            command=self.call_infinite_kiwoom_execution_preview,
        ).grid(row=0, column=2, rowspan=2, sticky="nsew", padx=(10, 0), pady=2)

        ttk.Label(
            frame,
            textvariable=self.kiwoom_execution_preview_status_var,
            style="Hint.TLabel",
            wraplength=360,
        ).grid(row=len(fields), column=0, columnspan=3, sticky=tk.EW, pady=(8, 0))
        frame.columnconfigure(1, weight=1)

    def call_infinite_kiwoom_execution_preview(self) -> None:
        profile_kind = "infinite"
        profile_name = self.kiwoom_profile_name(profile_kind)
        try:
            credentials = self.current_kiwoom_credentials_from_form(profile_kind)
            credentials = self.safe_save_kiwoom_credentials(
                profile_kind, profile_name, credentials
            )
            setting = load_infinite_setting(self.con, self.selected_infinite_profile_name())
            symbol = setting.symbol.upper()
            end_day = date.today()
            start_day = end_day - timedelta(days=30)

            self.kiwoom_execution_preview_status_var.set("토큰 확인 중...")
            self.update_idletasks()
            token, renewed = ensure_access_token(profile_kind, profile_name, credentials)
            stex_tp = self.resolve_kiwoom_us_exchange_code(
                credentials, token, symbol
            )

            self.kiwoom_execution_preview_status_var.set("체결입력정보 조회 중...")
            self.update_idletasks()
            balance = request_us_ledger_balance(
                credentials, token, stex_tp=stex_tp, stk_cd=symbol
            )
            orders = request_us_period_order_history(
                credentials,
                token,
                start_date=start_day.strftime("%Y%m%d"),
                end_date=end_day.strftime("%Y%m%d"),
                slby_tp="0",
                stex_tp=stex_tp,
                stk_cd=symbol,
                oppo_trde_tp="%",
            )
            preview = self.build_infinite_execution_preview(
                symbol, balance, orders
            )
            self.kiwoom_execution_preview_result = {
                "profile": profile_name,
                "symbol": symbol,
                "query_range": {
                    "start_date": start_day.strftime("%Y%m%d"),
                    "end_date": end_day.strftime("%Y%m%d"),
                },
                "token_renewed": renewed,
                "preview": preview,
                "balance": balance,
                "orders": orders,
            }
            for key, value in preview.items():
                field = self.kiwoom_execution_preview_fields.get(key)
                if field is not None:
                    field.set(str(value))
            order_note = (
                " / no fills"
                if orders.get("_meta", {}).get("empty_result")
                else ""
            )
            token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
            self.kiwoom_execution_preview_status_var.set(
                f"조회 성공: {symbol} / 마지막 체결일 {preview['trade_date'] or '-'} / {token_state}"
            )
            self.set_status(f"키움 체결입력정보 조회 성공: {profile_name}")
        except KiwoomApiError as exc:
            message = self.format_kiwoom_error("체결입력정보 조회 실패", exc)
            self.kiwoom_execution_preview_status_var.set(message)
            self.set_status(f"키움 체결입력정보 조회 실패: {profile_name}")
        except Exception as exc:
            self.kiwoom_execution_preview_status_var.set(f"체결입력정보 조회 실패: {exc}")
            self.show_error(exc)

    def build_infinite_execution_preview(
        self, symbol: str, balance: dict, orders: dict
    ) -> dict:
        balance_row = self.find_symbol_row(self.result_rows(balance), symbol)
        order_summary = self.summarize_last_order_day(self.result_rows(orders), symbol)
        avg_price = self.first_row_value(
            balance_row, "frgn_stk_book_uv", "prch_uv", "avg_pric"
        )
        return {
            "trade_date": self.format_api_date(order_summary["last_trade_date"]),
            "avg_price": self.clean_number_text(avg_price) if avg_price else "",
            "buy_qty": order_summary["buy_qty"],
            "sell_qty": order_summary["sell_qty"],
        }

    def result_rows(self, body: dict) -> list[dict]:
        rows = body.get("result_list") or body.get("result_lsit") or []
        return rows if isinstance(rows, list) else []

    def find_symbol_row(self, rows: list[dict], symbol: str) -> dict:
        symbol = symbol.upper()
        for row in rows:
            if str(row.get("stk_cd") or "").upper() == symbol:
                return row
        if len(rows) == 1 and isinstance(rows[0], dict):
            return rows[0]
        return {}

    def summarize_last_order_day(self, rows: list[dict], symbol: str) -> dict:
        symbol = symbol.upper()
        symbol_rows = [
            row
            for row in rows
            if str(row.get("stk_cd") or "").upper() == symbol
            and str(row.get("ord_dt") or "").strip()
        ]
        if not symbol_rows:
            return {"last_trade_date": "", "buy_qty": 0, "sell_qty": 0}
        last_trade_date = max(str(row.get("ord_dt") or "") for row in symbol_rows)
        buy_qty = 0
        sell_qty = 0
        for row in symbol_rows:
            if str(row.get("ord_dt") or "") != last_trade_date:
                continue
            qty = self.order_filled_quantity(row)
            side = self.order_side(row)
            if side == "buy":
                buy_qty += qty
            elif side == "sell":
                sell_qty += qty
        return {
            "last_trade_date": last_trade_date,
            "buy_qty": buy_qty,
            "sell_qty": sell_qty,
        }

    def summarize_order_period(self, rows: list[dict], symbol: str) -> dict:
        symbol = symbol.upper()
        buy_qty = 0
        sell_qty = 0
        buy_amount = 0.0
        sell_amount = 0.0
        for row in rows:
            row_symbol = str(row.get("stk_cd") or "").upper()
            if row_symbol and row_symbol != symbol:
                continue
            qty = self.order_filled_quantity(row)
            amount = self.order_filled_amount(row)
            side = self.order_side(row)
            if side == "buy":
                buy_qty += qty
                buy_amount += amount
            elif side == "sell":
                sell_qty += qty
                sell_amount += amount
        return {
            "buy_qty": buy_qty,
            "buy_amount": buy_amount,
            "sell_qty": sell_qty,
            "sell_amount": sell_amount,
        }

    def order_filled_quantity(self, row: dict) -> int:
        cntr_qty = str(row.get("cntr_qty") or "").strip()
        if cntr_qty:
            return self.clean_int(cntr_qty)
        return self.clean_int(row.get("ord_qty"))

    def order_filled_amount(self, row: dict) -> float:
        amount_text = str(row.get("cntr_amt") or "").strip()
        amount = self.clean_float(amount_text)
        if amount_text and amount != 0:
            return abs(amount)
        qty = self.order_filled_quantity(row)
        price = self.clean_float(row.get("cntr_uv"))
        return abs(qty * price)

    def order_side(self, row: dict) -> str:
        slby_tp = str(row.get("slby_tp") or "").strip()
        if slby_tp == "2":
            return "buy"
        if slby_tp == "1":
            return "sell"
        label = " ".join(
            str(row.get(key) or "")
            for key in ("slby_tp_nm", "trde_tp", "frgn_trde_tp")
        ).lower()
        if "매수" in label or "buy" in label:
            return "buy"
        if "매도" in label or "sell" in label:
            return "sell"
        return ""

    def format_api_date(self, value: str) -> str:
        value = str(value or "").strip()
        if len(value) == 8 and value.isdigit():
            return f"{value[0:4]}-{value[4:6]}-{value[6:8]}"
        return value

    def clean_int(self, value) -> int:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return 0
        try:
            return int(float(text))
        except ValueError:
            return 0

    def clean_float(self, value) -> float:
        text = str(value or "").replace(",", "").strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return 0.0

    def clean_number_text(self, value) -> str:
        number = self.clean_float(value)
        if number == 0:
            return "0"
        text = f"{number:.6f}".rstrip("0").rstrip(".")
        return text or "0"

    def _build_infinite_kiwoom_balance_lookup(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="잔고조회", padding=12)
        frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))

        header = ttk.Frame(frame)
        header.pack(fill=tk.X)
        ttk.Label(header, text="미국주식 원장잔고확인 (ust21070)").pack(side=tk.LEFT)
        ttk.Button(
            header,
            text="호출",
            command=self.call_infinite_kiwoom_balance,
        ).pack(side=tk.RIGHT)

        status_var = tk.StringVar(value="")
        self.kiwoom_balance_status_vars["infinite"] = status_var
        ttk.Label(header, textvariable=status_var, style="Hint.TLabel").pack(
            side=tk.RIGHT, padx=(0, 12)
        )

        result_frame = ttk.Frame(frame)
        result_frame.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        result_frame.columnconfigure(0, weight=1)
        result_frame.rowconfigure(0, weight=1)

        result_text = tk.Text(
            result_frame,
            height=12,
            wrap=tk.NONE,
            state=tk.DISABLED,
            font=("Consolas", 9),
        )
        result_text.grid(row=0, column=0, sticky="nsew")
        y_scroll = ttk.Scrollbar(result_frame, orient=tk.VERTICAL, command=result_text.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(result_frame, orient=tk.HORIZONTAL, command=result_text.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")
        result_text.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
        self.kiwoom_balance_result_widgets["infinite"] = result_text

    def call_infinite_kiwoom_balance(self) -> None:
        profile_kind = "infinite"
        profile_name = self.kiwoom_profile_name(profile_kind)
        status_var = self.kiwoom_balance_status_vars.get(profile_kind)
        try:
            credentials = self.current_kiwoom_credentials_from_form(profile_kind)
            credentials = self.safe_save_kiwoom_credentials(
                profile_kind, profile_name, credentials
            )
            if status_var is not None:
                status_var.set("토큰 확인 중...")
            self.update_idletasks()

            token, renewed = ensure_access_token(profile_kind, profile_name, credentials)
            if status_var is not None:
                status_var.set("잔고조회 요청 중...")
            self.update_idletasks()

            result = request_us_ledger_balance(credentials, token)
            rows = result.get("result_list")
            row_count = len(rows) if isinstance(rows, list) else 0
            token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
            summary = {
                "profile": profile_name,
                "account_number": credentials.account_number,
                "token": {
                    "state": token_state,
                    "expires_dt": self.format_kiwoom_datetime(token.expires_dt),
                },
                "balance": {
                    "row_count": row_count,
                    "return_code": result.get("return_code"),
                    "return_msg": result.get("return_msg"),
                },
                "response": result,
            }
            self.set_kiwoom_result_text(
                profile_kind, json.dumps(summary, ensure_ascii=False, indent=2)
            )
            if status_var is not None:
                status_var.set(f"조회 성공: {row_count}건 / {token_state}")
            self.set_status(f"키움 잔고조회 성공: {profile_name}")
        except KiwoomApiError as exc:
            message = self.format_kiwoom_error("잔고조회 실패", exc)
            if status_var is not None:
                status_var.set(message)
            self.set_kiwoom_result_text(profile_kind, message)
            self.set_status(f"키움 잔고조회 실패: {profile_name}")
        except Exception as exc:
            message = f"잔고조회 실패: {exc}"
            if status_var is not None:
                status_var.set(message)
            self.set_kiwoom_result_text(profile_kind, message)
            self.show_error(exc)

    def set_kiwoom_result_text(self, profile_kind: str, text: str) -> None:
        widget = self.kiwoom_balance_result_widgets.get(profile_kind)
        if widget is None:
            return
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", text)
        widget.configure(state=tk.DISABLED)

    def format_kiwoom_datetime(self, value: str) -> str:
        value = str(value or "").strip()
        if len(value) == 14 and value.isdigit():
            return (
                f"{value[0:4]}-{value[4:6]}-{value[6:8]} "
                f"{value[8:10]}:{value[10:12]}:{value[12:14]}"
            )
        return value or "-"

    def format_kiwoom_error(self, prefix: str, exc: KiwoomApiError) -> str:
        details = []
        if exc.status_code is not None:
            details.append(f"HTTP {exc.status_code}")
        if exc.return_code is not None:
            details.append(f"return_code {exc.return_code}")
        if exc.return_msg:
            details.append(exc.return_msg)
        error_message = str(exc.return_msg or exc or "")
        if str(exc.return_code or "").strip() == "505531" or "주간거래" in error_message:
            details.append(
                "키움이 현재 시간대/주문유형을 지원하지 않아 거절했습니다. "
                "정규장 주문 가능 시간에 다시 실행하거나 주문유형을 확인하세요."
            )
        if exc.response_preview:
            details.append(f"response {exc.response_preview}")
        error_text = str(exc)
        if error_text and error_text not in details:
            details.append(error_text)
        if not details:
            return prefix
        return prefix + ": " + " / ".join(str(item) for item in details)

    def resolve_kiwoom_us_exchange_code(
        self, credentials: KiwoomCredentials, token, symbol: str
    ) -> str:
        try:
            return resolve_us_stock_exchange_code(credentials, token, symbol)
        except Exception:
            return default_us_stock_exchange_code(symbol)

    def kiwoom_profile_name(self, profile_kind: str) -> str:
        if profile_kind == "vr":
            return self.selected_profile_name()
        if profile_kind == "infinite":
            return self.selected_infinite_profile_name()
        raise ValueError(f"Unknown Kiwoom profile kind: {profile_kind}")

    def default_kiwoom_account_number(self, profile_kind: str) -> str:
        try:
            if profile_kind == "vr":
                return self.current_profile().account_number
            if profile_kind == "infinite":
                return load_infinite_setting(
                    self.con, self.selected_infinite_profile_name()
                ).account_number
        except Exception:
            return ""
        return ""

    def load_kiwoom_api_credentials(self, profile_kind: str) -> None:
        fields = self.kiwoom_api_fields.get(profile_kind)
        if not fields:
            return
        profile_name = self.kiwoom_profile_name(profile_kind)
        credentials = load_kiwoom_credentials(profile_kind, profile_name)
        values = {
            "investment_type": credentials.investment_type or "실전투자",
            "account_number": credentials.account_number
            or self.default_kiwoom_account_number(profile_kind),
            "app_key": credentials.app_key,
            "app_secret": credentials.app_secret,
            "expires_at": credentials.expires_at,
            "memo": credentials.memo,
        }
        for key, value in values.items():
            fields[key].set(value)
        status_var = self.kiwoom_api_status_vars.get(profile_kind)
        if status_var is not None:
            status_var.set("")

    def save_kiwoom_api_credentials(self, profile_kind: str) -> None:
        try:
            profile_name = self.kiwoom_profile_name(profile_kind)
            credentials = self.current_kiwoom_credentials_from_form(profile_kind)
            credentials = self.safe_save_kiwoom_credentials(
                profile_kind, profile_name, credentials
            )
            self.set_status(f"키움 API 키 저장 완료: {profile_name}")
        except Exception as exc:
            self.show_error(exc)

    def safe_save_kiwoom_credentials(
        self,
        profile_kind: str,
        profile_name: str,
        credentials: KiwoomCredentials,
    ) -> KiwoomCredentials:
        existing = load_kiwoom_credentials(profile_kind, profile_name)
        merged = KiwoomCredentials(
            investment_type=credentials.investment_type or existing.investment_type,
            account_number=credentials.account_number or existing.account_number,
            app_key=credentials.app_key or existing.app_key,
            app_secret=credentials.app_secret or existing.app_secret,
            expires_at=credentials.expires_at or existing.expires_at,
            memo=credentials.memo or existing.memo,
        )
        self.backup_kiwoom_credentials_file()
        save_kiwoom_credentials(profile_kind, profile_name, merged)
        self.apply_kiwoom_credentials_to_form(profile_kind, merged)
        return merged

    def backup_kiwoom_credentials_file(self) -> None:
        path = kiwoom_credentials_path()
        if not path.exists():
            return
        backup_path = path.with_name(
            f"{path.stem}.bak-{datetime.now().strftime('%Y%m%d_%H%M%S')}{path.suffix}"
        )
        try:
            shutil.copy2(path, backup_path)
        except Exception:
            pass

    def apply_kiwoom_credentials_to_form(
        self, profile_kind: str, credentials: KiwoomCredentials
    ) -> None:
        fields = self.kiwoom_api_fields.get(profile_kind)
        if not fields:
            return
        values = {
            "investment_type": credentials.investment_type,
            "account_number": credentials.account_number,
            "app_key": credentials.app_key,
            "app_secret": credentials.app_secret,
            "expires_at": credentials.expires_at,
            "memo": credentials.memo,
        }
        for key, value in values.items():
            fields[key].set(value)

    def current_kiwoom_credentials_from_form(
        self, profile_kind: str
    ) -> KiwoomCredentials:
        fields = self.kiwoom_api_fields[profile_kind]
        return KiwoomCredentials(
            investment_type=fields["investment_type"].get().strip() or "실전투자",
            account_number=fields["account_number"].get().strip(),
            app_key=fields["app_key"].get().strip(),
            app_secret=fields["app_secret"].get().strip(),
            expires_at=fields["expires_at"].get().strip(),
            memo=fields["memo"].get().strip(),
        )

    def test_kiwoom_access_token(self, profile_kind: str) -> None:
        profile_name = self.kiwoom_profile_name(profile_kind)
        status_var = self.kiwoom_api_status_vars.get(profile_kind)
        try:
            credentials = self.current_kiwoom_credentials_from_form(profile_kind)
            credentials = self.safe_save_kiwoom_credentials(
                profile_kind, profile_name, credentials
            )
            if status_var is not None:
                status_var.set("토큰 발급 요청 중...")
            self.update_idletasks()
            token = issue_access_token(credentials)
            save_profile_token(profile_kind, profile_name, token)
            message = (
                f"토큰 발급 성공: 만료 {token.expires_dt or '-'}"
                f" / {token.return_msg or '정상'}"
            )
            if status_var is not None:
                status_var.set(message)
            self.set_status(f"키움 OAuth 성공: {profile_name}")
        except KiwoomApiError as exc:
            details = []
            if exc.status_code is not None:
                details.append(f"HTTP {exc.status_code}")
            if exc.return_code is not None:
                details.append(f"return_code {exc.return_code}")
            if exc.return_msg:
                details.append(exc.return_msg)
            if exc.response_preview:
                details.append(f"response {exc.response_preview}")
            error_text = str(exc)
            if error_text and error_text not in details:
                details.append(error_text)
            message = "토큰 발급 실패"
            if details:
                message += ": " + " / ".join(str(item) for item in details)
            if status_var is not None:
                status_var.set(message)
            self.set_status(f"키움 OAuth 실패: {profile_name}")
        except Exception as exc:
            message = f"토큰 발급 실패: {exc}"
            if status_var is not None:
                status_var.set(message)
            self.show_error(exc)

    def _build_telegram_tab(self, parent: ttk.Frame) -> None:
        settings_frame = ttk.LabelFrame(parent, text="텔레그램 설정", padding=12)
        settings_frame.pack(fill=tk.X)
        fields = [
            ("bot_token", "Bot Token"),
            ("chat_id", "Chat ID"),
        ]
        for row, (key, label) in enumerate(fields):
            ttk.Label(settings_frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=4)
            var = tk.StringVar(value="")
            self.telegram_fields[key] = var
            show = "*" if key == "bot_token" else ""
            ttk.Entry(settings_frame, textvariable=var, width=58, show=show).grid(
                row=row, column=1, sticky=tk.EW, padx=(10, 0), pady=4
            )
        settings_frame.columnconfigure(1, weight=1)

        button_row = len(fields)
        ttk.Button(
            settings_frame, text="설정 저장", command=self.save_telegram_settings_from_form
        ).grid(row=button_row, column=0, sticky=tk.EW, pady=(10, 0))
        ttk.Button(
            settings_frame, text="테스트 메시지", command=self.send_telegram_test
        ).grid(row=button_row, column=1, sticky=tk.EW, padx=(10, 0), pady=(10, 0))

        manual_frame = ttk.LabelFrame(parent, text="수동발송 항목", padding=12)
        manual_frame.pack(fill=tk.X, pady=(12, 0))
        manual_options = [
            ("send_due", "작성 입력 필요 / 미작성"),
            ("send_dashboard", "대시보드 총괄 요약"),
            ("send_vr_summary", "VR 프로필 요약"),
            ("send_infinite_summary", "무한매수법 프로필 요약"),
            ("send_order_status", "주문표 상태 요약"),
            ("include_paused", "산출 중단 프로필 포함"),
        ]
        for row, (key, label) in enumerate(manual_options):
            var = tk.BooleanVar(value=True)
            self.telegram_option_vars[key] = var
            ttk.Checkbutton(manual_frame, text=label, variable=var).grid(
                row=row // 2, column=row % 2, sticky=tk.W, padx=(0, 24), pady=3
            )
        manual_frame.columnconfigure(0, weight=1)
        manual_frame.columnconfigure(1, weight=1)

        send_frame = ttk.Frame(manual_frame)
        send_frame.grid(
            row=(len(manual_options) + 1) // 2,
            column=0,
            columnspan=2,
            sticky=tk.EW,
            pady=(10, 0),
        )
        ttk.Button(
            send_frame, text="선택 항목 보내기", command=self.send_selected_telegram_message
        ).pack(side=tk.LEFT)
        ttk.Label(send_frame, textvariable=self.telegram_status_var, style="Hint.TLabel").pack(
            side=tk.LEFT, padx=(12, 0)
        )

        auto_frame = ttk.LabelFrame(parent, text="자동발송 항목", padding=12)
        auto_frame.pack(fill=tk.X, pady=(12, 0))
        auto_options = [
            ("auto_send_on_calculation", "산출 완료 시 자동 발송"),
            ("auto_send_vr_orders", "VR 주문표 자동 발송"),
            ("auto_send_infinite_orders", "무한매수법 주문표 자동 발송"),
            ("send_order_table", "주문표 포함"),
        ]
        for row, (key, label) in enumerate(auto_options):
            var = tk.BooleanVar(value=True)
            self.telegram_option_vars[key] = var
            ttk.Checkbutton(auto_frame, text=label, variable=var).grid(
                row=row // 2, column=row % 2, sticky=tk.W, padx=(0, 24), pady=3
            )
        limit_row = (len(auto_options) + 1) // 2
        ttk.Label(auto_frame, text="주문행 최대 개수").grid(
            row=limit_row, column=0, sticky=tk.W, pady=(8, 3)
        )
        self.telegram_fields["order_row_limit"] = tk.StringVar(value="10")
        ttk.Entry(
            auto_frame,
            textvariable=self.telegram_fields["order_row_limit"],
            width=8,
        ).grid(row=limit_row, column=1, sticky=tk.W, pady=(8, 3))
        auto_frame.columnconfigure(0, weight=1)
        auto_frame.columnconfigure(1, weight=1)
        self.load_telegram_settings_to_form()

    def load_telegram_settings_to_form(self) -> None:
        settings = load_telegram_settings()
        if "bot_token" in self.telegram_fields:
            self.telegram_fields["bot_token"].set(settings.bot_token)
        if "chat_id" in self.telegram_fields:
            self.telegram_fields["chat_id"].set(settings.chat_id)
        if "order_row_limit" in self.telegram_fields:
            self.telegram_fields["order_row_limit"].set(str(settings.order_row_limit))
        for key in self.telegram_option_vars:
            if hasattr(settings, key):
                self.telegram_option_vars[key].set(bool(getattr(settings, key)))

    def current_telegram_settings(self) -> TelegramSettings:
        try:
            order_row_limit = max(
                1,
                min(
                    50,
                    int(self.telegram_fields.get("order_row_limit", tk.StringVar(value="10")).get()),
                ),
            )
        except ValueError:
            order_row_limit = 10
        return TelegramSettings(
            bot_token=self.telegram_fields.get("bot_token", tk.StringVar()).get().strip(),
            chat_id=self.telegram_fields.get("chat_id", tk.StringVar()).get().strip(),
            auto_send_on_calculation=self.telegram_option_vars.get("auto_send_on_calculation", tk.BooleanVar(value=True)).get(),
            auto_send_vr_orders=self.telegram_option_vars.get("auto_send_vr_orders", tk.BooleanVar(value=True)).get(),
            auto_send_infinite_orders=self.telegram_option_vars.get("auto_send_infinite_orders", tk.BooleanVar(value=True)).get(),
            send_order_table=self.telegram_option_vars.get("send_order_table", tk.BooleanVar(value=True)).get(),
            order_row_limit=order_row_limit,
            send_due=self.telegram_option_vars.get("send_due", tk.BooleanVar(value=True)).get(),
            send_dashboard=self.telegram_option_vars.get("send_dashboard", tk.BooleanVar(value=True)).get(),
            send_vr_summary=self.telegram_option_vars.get("send_vr_summary", tk.BooleanVar(value=True)).get(),
            send_infinite_summary=self.telegram_option_vars.get("send_infinite_summary", tk.BooleanVar(value=True)).get(),
            send_order_status=self.telegram_option_vars.get("send_order_status", tk.BooleanVar(value=True)).get(),
            include_paused=self.telegram_option_vars.get("include_paused", tk.BooleanVar(value=False)).get(),
        )

    def save_telegram_settings_from_form(self) -> None:
        try:
            path = save_telegram_settings(self.current_telegram_settings())
            self.telegram_status_var.set(f"저장 완료: {path.name}")
            self.set_status("텔레그램 설정 저장 완료")
        except Exception as exc:
            self.show_error(exc)

    def send_telegram_test(self) -> None:
        try:
            settings = self.current_telegram_settings()
            save_telegram_settings(settings)
            send_telegram_message(settings, f"VR Study 테스트 메시지\n{datetime.now():%Y-%m-%d %H:%M:%S}")
            self.telegram_status_var.set("테스트 메시지 전송 완료")
            self.set_status("텔레그램 테스트 메시지 전송 완료")
        except Exception as exc:
            self.show_error(exc)

    def send_selected_telegram_message(self) -> None:
        try:
            settings = self.current_telegram_settings()
            save_telegram_settings(settings)
            message = self.build_telegram_message(settings)
            send_telegram_message(settings, message)
            self.telegram_status_var.set("선택 항목 전송 완료")
            self.set_status("텔레그램 선택 항목 전송 완료")
        except Exception as exc:
            self.show_error(exc)

    def auto_send_vr_telegram_order(self, profile: Profile) -> None:
        settings = load_telegram_settings()
        if not self.telegram_auto_enabled(settings, "vr"):
            return
        try:
            message = self.build_vr_order_telegram_message(profile, settings)
            send_telegram_message(settings, message)
            self.telegram_status_var.set("VR 주문표 자동 발송 완료")
        except Exception as exc:
            self.telegram_status_var.set(f"VR 자동 발송 실패: {exc}")
            self.set_status(f"텔레그램 VR 자동 발송 실패: {exc}")

    def auto_send_infinite_telegram_order(self, setting: InfiniteSetting) -> None:
        settings = load_telegram_settings()
        if not self.telegram_auto_enabled(settings, "infinite"):
            return
        try:
            message = self.build_infinite_order_telegram_message(setting, settings)
            send_telegram_message(settings, message)
            self.telegram_status_var.set("무한매수법 주문표 자동 발송 완료")
        except Exception as exc:
            self.telegram_status_var.set(f"무매 자동 발송 실패: {exc}")
            self.set_status(f"텔레그램 무매 자동 발송 실패: {exc}")

    @staticmethod
    def telegram_auto_enabled(settings: TelegramSettings, strategy: str) -> bool:
        if not settings.bot_token.strip() or not settings.chat_id.strip():
            return False
        if not settings.auto_send_on_calculation:
            return False
        if strategy == "vr":
            return bool(settings.auto_send_vr_orders)
        if strategy == "infinite":
            return bool(settings.auto_send_infinite_orders)
        return False

    @staticmethod
    def order_row_limit(settings: TelegramSettings) -> int:
        return max(1, min(50, int(settings.order_row_limit or 10)))

    def build_vr_order_telegram_message(
        self, profile: Profile, settings: TelegramSettings
    ) -> str:
        basis = order_basis_for_next_cycle(self.con, profile)
        quantity_step = int(self.view_fields.get("quantity_step", tk.StringVar(value=str(profile.quantity_step))).get() or profile.quantity_step)
        order_rows = order_level_values(profile, basis, quantity_step=quantity_step)
        week_no = self.week_no_for_cycle(profile, int(basis["cycle_no"]))
        lines = [
            f"[VR 주문표] {self.vr_profile_label(profile)}",
            f"주차: {week_no}",
            f"기간: {basis.get('start_date')} ~ {basis.get('end_date')}",
            f"G: {self.format_number(basis.get('g'))} / 매수한도: {self.format_percent(basis.get('buy_limit_ratio'))}",
            f"계좌총액: {self.format_money(basis.get('account_total'))}",
            f"수익률: {self.format_percent(basis.get('return_rate'))}",
        ]
        if settings.send_order_table:
            lines.extend(self.format_vr_order_lines(order_rows, self.order_row_limit(settings)))
        return "\n".join(lines)[:3900]

    def build_infinite_order_telegram_message(
        self, setting: InfiniteSetting, settings: TelegramSettings
    ) -> str:
        basis = order_basis_row(self.con, setting)
        plan = infinite_order_plan(self.con, setting)
        today = date.today()
        fx_rate = latest_fx_rate(self.con, today)
        month_profit = self.infinite_realized_profit_between(
            setting.name, today.replace(day=1), today
        )
        year_profit = self.infinite_realized_profit_between(
            setting.name, today.replace(month=1, day=1), today
        )
        lines = [f"[무한매수법 주문표] {self.infinite_profile_label(setting)}"]
        if basis is not None:
            lines.extend(
                [
                    f"주문일: {basis.get('trade_date')}",
                    f"종목: {setting.symbol}",
                    f"상태: {plan.get('title') or '-'}",
                    f"T: {self.format_number(basis.get('t_value'))}",
                    f"보유수량: {basis.get('cumulative_qty')}",
                    f"1회매수금: {self.format_money(plan.get('per_buy_amount'))}",
                ]
            )
        else:
            lines.append("주문 기준 로우가 없습니다.")
        lines.extend(
            [
                f"이번달 수익금(원화): {self.format_won(month_profit * fx_rate)}",
                f"올해 수익금(원화): {self.format_won(year_profit * fx_rate)}",
            ]
        )
        if str(plan.get("title", "")).startswith("주문불가"):
            lines.append(f"사유: {plan.get('title')}")
        elif settings.send_order_table:
            lines.extend(self.format_infinite_order_lines(plan, self.order_row_limit(settings)))
        return "\n".join(lines)[:3900]

    def format_vr_order_lines(self, order_rows: list[dict], limit: int) -> list[str]:
        buy_rows = [row for row in order_rows if row.get("side") == "BUY"]
        sell_rows = [row for row in order_rows if row.get("side") == "SELL"]
        buy_limit, sell_limit = self.split_order_limit(len(buy_rows), len(sell_rows), limit)
        lines: list[str] = []
        if buy_rows:
            lines.append("")
            lines.append("매수")
            for row in buy_rows[:buy_limit]:
                lines.append(
                    f"- {self.format_number(row['price'])} / {row['quantity_step']}주 / Pool {self.format_money(row['pool_after'])}"
                )
        if sell_rows:
            lines.append("")
            lines.append("매도")
            for row in sell_rows[:sell_limit]:
                lines.append(
                    f"- {self.format_number(row['price'])} / {row['quantity_step']}주 / Pool {self.format_money(row['pool_after'])}"
                )
        omitted = max(0, len(buy_rows) - buy_limit) + max(0, len(sell_rows) - sell_limit)
        if omitted:
            lines.append(f"- 외 {omitted}건")
        return lines

    def format_infinite_order_lines(self, plan: dict, limit: int) -> list[str]:
        buy_rows = list(plan.get("buy", []))
        sell_rows = list(plan.get("sell", []))
        buy_limit, sell_limit = self.split_order_limit(len(buy_rows), len(sell_rows), limit)
        lines: list[str] = []
        if buy_rows:
            lines.append("")
            lines.append("매수")
            for row in buy_rows[:buy_limit]:
                price = "시장가" if row.get("price") is None else self.format_number(row.get("price"))
                lines.append(f"- {row.get('order_type')} {price} / {row.get('quantity')}주")
        if sell_rows:
            lines.append("")
            lines.append("매도")
            for row in sell_rows[:sell_limit]:
                price = "시장가" if row.get("price") is None else self.format_number(row.get("price"))
                lines.append(f"- {row.get('order_type')} {price} / {row.get('quantity')}주")
        omitted = max(0, len(buy_rows) - buy_limit) + max(0, len(sell_rows) - sell_limit)
        if omitted:
            lines.append(f"- 외 {omitted}건")
        return lines

    @staticmethod
    def split_order_limit(buy_count: int, sell_count: int, limit: int) -> tuple[int, int]:
        limit = max(1, int(limit or 10))
        if buy_count and sell_count:
            buy_limit = min(buy_count, (limit + 1) // 2)
            sell_limit = min(sell_count, limit - buy_limit)
            if sell_limit == 0:
                sell_limit = min(sell_count, 1)
                buy_limit = max(0, limit - sell_limit)
            return buy_limit, sell_limit
        if buy_count:
            return min(buy_count, limit), 0
        return 0, min(sell_count, limit)

    def infinite_realized_profit_between(
        self, setting_name: str, start_date: date, end_date: date
    ) -> float:
        row = self.con.execute(
            """
            SELECT coalesce(sum(stop_loss), 0) - coalesce(sum(fee), 0)
            FROM infinite_rows
            WHERE setting_name = ?
              AND trade_date BETWEEN ? AND ?
            """,
            [setting_name, start_date, end_date],
        ).fetchone()
        return float(row[0] or 0.0)

    def build_telegram_message(self, settings: TelegramSettings) -> str:
        vr_rows = self.dashboard_vr_rows()
        infinite_rows_data = self.dashboard_infinite_rows()
        if not settings.include_paused:
            vr_rows = [row for row in vr_rows if row.get("missing_text") != "중단"]
            infinite_rows_data = [row for row in infinite_rows_data if row.get("missing_text") != "중단"]

        sections = [f"VR Study 알림 ({date.today()})"]
        if settings.send_due:
            sections.extend(self.telegram_due_lines(vr_rows, infinite_rows_data))
        if settings.send_dashboard:
            sections.extend(self.telegram_dashboard_lines(vr_rows, infinite_rows_data))
        if settings.send_vr_summary:
            sections.extend(self.telegram_vr_lines(vr_rows))
        if settings.send_infinite_summary:
            sections.extend(self.telegram_infinite_lines(infinite_rows_data))
        if settings.send_order_status:
            sections.extend(self.telegram_order_status_lines(vr_rows, infinite_rows_data))
        if len(sections) == 1:
            sections.append("선택된 발송 항목이 없습니다.")
        message = "\n".join(sections)
        return message[:3900]

    def telegram_due_lines(self, vr_rows: list[dict], infinite_rows_data: list[dict]) -> list[str]:
        due = [
            f"- VR {row['label']}: {row['issue']}"
            for row in vr_rows
            if int(row.get("missing_count") or 0) > 0
        ]
        due.extend(
            f"- 무매 {row['label']}: {row['issue']}"
            for row in infinite_rows_data
            if int(row.get("missing_count") or 0) > 0
        )
        lines = ["", "[입력 필요]"]
        if due:
            lines.extend(due[:12])
            if len(due) > 12:
                lines.append(f"- 외 {len(due) - 12}건")
        else:
            lines.append("- 없음")
        return lines

    def telegram_dashboard_lines(self, vr_rows: list[dict], infinite_rows_data: list[dict]) -> list[str]:
        fx_rate = latest_fx_rate(self.con, date.today())
        vr_principal_usd = sum(row["principal"] for row in vr_rows)
        vr_value_usd = sum(row["account_total"] for row in vr_rows)
        vr_bought_usd = sum(row["buy_principal"] for row in vr_rows)
        vr_cash_usd = sum(row["cash_amount"] for row in vr_rows)
        infinite_principal_usd = sum(row["principal"] for row in infinite_rows_data)
        infinite_value_krw = sum(row["cumulative_value"] for row in infinite_rows_data)
        infinite_bought_usd = sum(row["cumulative_amount"] for row in infinite_rows_data)
        infinite_cash_usd = sum(row["cash_amount"] for row in infinite_rows_data)
        total_principal_krw = (vr_principal_usd + infinite_principal_usd) * fx_rate
        total_value_krw = (vr_value_usd * fx_rate) + infinite_value_krw + (infinite_cash_usd * fx_rate)
        total_profit_krw = total_value_krw - total_principal_krw
        total_bought_krw = (vr_bought_usd + infinite_bought_usd) * fx_rate
        total_cash_krw = (vr_cash_usd + infinite_cash_usd) * fx_rate
        total_cash_basis_krw = total_bought_krw + total_cash_krw
        total_cash_ratio = total_cash_krw / total_cash_basis_krw if total_cash_basis_krw > 0 else None
        return [
            "",
            "[총괄]",
            f"- 운용 프로필: VR {len(vr_rows)}개 / 무매 {len(infinite_rows_data)}개",
            f"- 현재자산(원화): {self.format_won(total_value_krw)}",
            f"- 원금(원화): {self.format_won(total_principal_krw)}",
            f"- 손익/수익률: {self.format_won(total_profit_krw)} / {self.format_percent(total_profit_krw / total_principal_krw if total_principal_krw else None)}",
            f"- 총 매수금: {self.format_won(total_bought_krw)}",
            f"- 예수금/비율: {self.format_won(total_cash_krw)} / {self.format_percent(total_cash_ratio)}",
        ]

    def telegram_vr_lines(self, vr_rows: list[dict]) -> list[str]:
        lines = ["", "[VR 요약]"]
        if not vr_rows:
            lines.append("- 없음")
            return lines
        for row in vr_rows[:8]:
            lines.append(
                f"- {row['label']}: 계좌 {self.format_money(row['account_total'])}, "
                f"손익 {self.format_money(row['profit'])} / {self.format_percent(row['return_rate'])}, "
                f"미입력 {row['missing_text'] or '없음'}"
            )
        if len(vr_rows) > 8:
            lines.append(f"- 외 {len(vr_rows) - 8}개")
        return lines

    def telegram_infinite_lines(self, infinite_rows_data: list[dict]) -> list[str]:
        lines = ["", "[무한매수법 요약]"]
        if not infinite_rows_data:
            lines.append("- 없음")
            return lines
        for row in infinite_rows_data[:8]:
            lines.append(
                f"- {row['label']}: 평가 {self.format_won(row['cumulative_value'])}, "
                f"평단 {self.format_number(row['avg_price'])}, 미입력 {row['missing_text'] or '없음'}"
            )
        if len(infinite_rows_data) > 8:
            lines.append(f"- 외 {len(infinite_rows_data) - 8}개")
        return lines

    def telegram_order_status_lines(
        self, vr_rows: list[dict], infinite_rows_data: list[dict]
    ) -> list[str]:
        lines = ["", "[주문표 상태]"]
        if not vr_rows and not infinite_rows_data:
            lines.append("- 없음")
            return lines
        for row in vr_rows[:6]:
            try:
                profile = load_profile(self.profiles_dir, row["name"])
                basis = order_basis_for_next_cycle(self.con, profile)
                lines.append(
                    f"- VR {row['label']}: {self.week_no_for_cycle(profile, int(basis['cycle_no']))}주차 진행중"
                )
            except Exception:
                lines.append(f"- VR {row['label']}: 주문표 확인 필요")
        for row in infinite_rows_data[:6]:
            try:
                setting = load_infinite_setting(self.con, row["name"])
                plan = infinite_order_plan(self.con, setting)
                if str(plan.get("title", "")).startswith("주문불가"):
                    lines.append(f"- 무매 {row['label']}: {plan['title']}")
                else:
                    lines.append(
                        f"- 무매 {row['label']}: {plan.get('title') or '주문표'} "
                        f"매수 {len(plan.get('buy', []))} / 매도 {len(plan.get('sell', []))}"
                    )
            except Exception:
                lines.append(f"- 무매 {row['label']}: 주문표 확인 필요")
        return lines

    def load_infinite_to_form(self) -> None:
        try:
            setting = load_infinite_setting(self.con, self.selected_infinite_profile_name())
            self.infinite_fields["account_number"].set(setting.account_number)
            self.infinite_fields["symbol"].set(setting.symbol)
            self.infinite_fields["start_date"].set(str(setting.start_date))
            self.infinite_fields["initial_principal"].set(self.format_number(setting.initial_principal))
            self.infinite_fields["initial_cumulative_amount"].set(
                self.format_number(setting.initial_cumulative_amount)
            )
            self.infinite_fields["initial_cumulative_qty"].set(
                str(setting.initial_cumulative_qty)
            )
            self.infinite_fields["target_rate"].set(self.format_percent(setting.target_rate))
            self.infinite_fields["split_count"].set(str(setting.split_count))
            self.infinite_fields["fee_rate"].set(self.format_percent(setting.fee_rate, digits=3))
            self.infinite_fields["mode"].set(setting.mode)
            self.load_kiwoom_api_credentials("infinite")
            self.update_infinite_pause_button(setting)
            self.refresh_infinite_tab()
        except Exception as exc:
            self.show_error(exc)

    def current_infinite_setting(self) -> InfiniteSetting:
        name = self.selected_infinite_profile_name()
        existing = load_infinite_setting(self.con, name)
        return InfiniteSetting(
            name=name,
            profile_no=existing.profile_no,
            account_number=self.infinite_fields["account_number"].get().strip(),
            symbol=self.infinite_fields["symbol"].get().strip().upper() or "TQQQ",
            start_date=date.fromisoformat(self.infinite_fields["start_date"].get().strip()),
            initial_principal=self.float_field(self.infinite_fields, "initial_principal"),
            initial_cumulative_amount=self.float_field(
                self.infinite_fields, "initial_cumulative_amount"
            ),
            initial_cumulative_qty=self.int_field(
                self.infinite_fields, "initial_cumulative_qty"
            ),
            target_rate=self.percent_field(self.infinite_fields, "target_rate"),
            split_count=self.int_field(self.infinite_fields, "split_count"),
            fee_rate=self.percent_field(self.infinite_fields, "fee_rate"),
            mode=self.infinite_fields["mode"].get().strip() or "기본",
            calculation_paused=existing.calculation_paused,
        )

    def save_infinite_settings(self) -> None:
        try:
            setting = self.current_infinite_setting()
            self.recalculate_infinite_from_form(setting)
            self.set_status(
                f"무한매수법 설정 저장/재계산 완료: 초기 누적개수 {setting.initial_cumulative_qty}"
            )
        except Exception as exc:
            self.show_error(exc)

    def save_infinite_execution(self) -> None:
        try:
            setting = self.current_infinite_setting()
            save_infinite_setting(self.con, setting)
            trade_date = date.fromisoformat(self.infinite_input_fields["trade_date"].get().strip())
            if not self.infinite_execution_input_allowed(setting, trade_date):
                raise ValueError("무한매수법 체결 입력은 어제 날짜까지만 저장할 수 있습니다.")
            save_infinite_execution(
                self.con,
                setting,
                trade_date,
                self.float_field(self.infinite_input_fields, "avg_price"),
                self.int_field(self.infinite_input_fields, "buy_qty"),
                self.int_field(self.infinite_input_fields, "sell_qty"),
                self.float_field(self.infinite_input_fields, "cash_flow_amount"),
            )
            self.recalculate_infinite_from_form(setting)
            self.auto_send_infinite_telegram_order(setting)
            self.set_status(f"무한매수법 {trade_date} 체결 저장 완료")
        except Exception as exc:
            self.show_error(exc)

    def save_infinite_execution_for_order(self) -> tuple[InfiniteSetting, date]:
        setting = self.current_infinite_setting()
        save_infinite_setting(self.con, setting)
        trade_date = date.fromisoformat(
            self.infinite_input_fields["trade_date"].get().strip()
        )
        if not self.infinite_execution_input_allowed(setting, trade_date):
            raise ValueError("Infinite execution input date is not allowed.")
        save_infinite_execution(
            self.con,
            setting,
            trade_date,
            self.float_field(self.infinite_input_fields, "avg_price"),
            self.int_field(self.infinite_input_fields, "buy_qty"),
            self.int_field(self.infinite_input_fields, "sell_qty"),
            self.float_field(self.infinite_input_fields, "cash_flow_amount"),
        )
        self.recalculate_infinite_from_form(setting)
        return setting, trade_date

    def infinite_execution_input_allowed(
        self, setting: InfiniteSetting | None = None, trade_date: date | None = None
    ) -> bool:
        try:
            setting = setting or self.current_infinite_setting()
            if setting.calculation_paused:
                return False
            trade_date = trade_date or date.fromisoformat(
                self.infinite_input_fields["trade_date"].get().strip()
            )
        except Exception:
            return False
        return setting.start_date <= trade_date < date.today()

    def update_infinite_execution_guard(self) -> None:
        if self.save_infinite_execution_button is None:
            return
        state = tk.NORMAL if self.infinite_execution_input_allowed() else tk.DISABLED
        self.save_infinite_execution_button.configure(state=state)

    def update_infinite_after_input_order_button(
        self, setting: InfiniteSetting, has_today_order_table: bool
    ) -> None:
        if self.infinite_order_execute_after_input_button is None:
            return
        state = (
            tk.NORMAL
            if not has_today_order_table and self.infinite_execution_input_allowed(setting)
            else tk.DISABLED
        )
        self.infinite_order_execute_after_input_button.configure(state=state)

    def refresh_infinite_tab(self) -> None:
        try:
            setting = self.current_infinite_setting()
            self.recalculate_infinite_from_form(setting)
        except Exception as exc:
            self.show_error(exc)

    def recalculate_infinite_from_form(self, setting: InfiniteSetting) -> None:
        save_infinite_setting(self.con, setting)
        generate_infinite_rows(
            self.con,
            setting,
            through=self.infinite_rebuild_through_date(setting.name, setting.start_date),
        )
        self.refresh_infinite_status(setting)
        self.refresh_infinite_rows(setting)
        self.refresh_infinite_orders(setting)
        latest = latest_input_date(self.con, setting.name)
        required_day = previous_us_trading_day(date.today() - timedelta(days=1))
        next_input = required_day
        if latest is not None:
            next_input = min(required_day, next_us_trading_day(latest + timedelta(days=1)))
        if next_input < setting.start_date:
            next_input = next_us_trading_day(setting.start_date)
        self.infinite_input_fields["trade_date"].set(str(next_input))
        self.update_infinite_execution_guard()
        if not self._startup_loading:
            self.refresh_due_badges()
            self.refresh_dashboard()

    def infinite_rebuild_through_date(self, setting_name: str, start_date: date) -> date:
        return max(start_date, date.today())

    def on_close(self) -> None:
        if self._closing:
            return
        self._closing = True
        checkpointed = False
        try:
            if self.con is not None:
                self.con.execute("CHECKPOINT")
                checkpointed = True
        except Exception:
            pass
        self.backup_user_data("close" if checkpointed else "close_uncheckpointed")
        try:
            if self.con is not None:
                self.con.close()
        except Exception:
            pass
        release_single_instance_lock(self._lock_handle)
        self._lock_handle = None
        try:
            (app_data_dir() / "vrstudy.lock").unlink(missing_ok=True)
        except OSError:
            pass
        self.destroy()

    def backup_user_data(self, reason: str) -> None:
        backup_root = Path(self.db_path).parent / "backups"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = backup_root / f"{stamp}_{reason}"
        try:
            backup_dir.mkdir(parents=True, exist_ok=True)
            db_path = Path(self.db_path)
            if db_path.exists():
                shutil.copy2(db_path, backup_dir / db_path.name)
            wal_path = Path(f"{db_path}.wal")
            if wal_path.exists():
                shutil.copy2(wal_path, backup_dir / wal_path.name)
            if self.profiles_dir.exists():
                profile_backup = backup_dir / "profiles"
                profile_backup.mkdir(exist_ok=True)
                for source in self.profiles_dir.glob("*.json"):
                    shutil.copy2(source, profile_backup / source.name)
        except Exception:
            pass

    def refresh_infinite_rows(self, setting: InfiniteSetting) -> None:
        if self.infinite_rows_tree is None:
            return
        for item in self.infinite_rows_tree.get_children():
            self.infinite_rows_tree.delete(item)
        for no, row in enumerate(infinite_rows(self.con, setting.name), start=1):
            self.infinite_rows_tree.insert(
                "",
                tk.END,
                values=(
                    no,
                    row["trade_date"],
                    row["weekday"],
                    self.format_number(row["close_price"]),
                    self.format_number(row["avg_price"]),
                    row.get("buy_qty") or 0,
                    row.get("sell_qty") or 0,
                    self.format_money(row.get("principal_before_withdrawal") or 0),
                    self.format_money(row.get("cash_flow_amount") or 0),
                    self.format_money(row.get("principal_after_withdrawal") or 0),
                    row["cumulative_qty"],
                    self.format_number(row["t_value"]),
                    self.format_number(row["star_price"]),
                    self.format_percent(row["return_rate"]),
                    self.format_money(row["fee"]),
                    self.format_money(row["stop_loss"]),
                    self.format_money(row["trade_amount"]),
                    self.format_money(row["cumulative_amount"]),
                ),
            )

    def load_infinite_row_to_input(self, event=None) -> None:
        if self.infinite_rows_tree is None:
            return
        item_id = self.infinite_rows_tree.identify_row(event.y) if event is not None else ""
        if not item_id:
            selection = self.infinite_rows_tree.selection()
            item_id = selection[0] if selection else ""
        if not item_id:
            return

        self.infinite_rows_tree.selection_set(item_id)
        values = self.infinite_rows_tree.item(item_id, "values")
        if not values or len(values) < 2:
            return

        trade_date_text = str(values[1])
        try:
            trade_date = date.fromisoformat(trade_date_text)
            row = self.con.execute(
                """
                SELECT trade_date, avg_price, buy_qty, sell_qty, cash_flow_amount
                FROM infinite_rows
                WHERE setting_name = ? AND trade_date = ?
                """,
                [self.selected_infinite_profile_name(), trade_date],
            ).fetchone()
        except Exception as exc:
            self.show_error(exc)
            return

        if row is None:
            self.infinite_input_fields["trade_date"].set(trade_date_text)
            self.update_infinite_execution_guard()
            return

        self.infinite_input_fields["trade_date"].set(str(row[0]))
        self.infinite_input_fields["avg_price"].set(self.format_input_number(row[1]))
        self.infinite_input_fields["buy_qty"].set(
            "0" if row[2] is None else str(int(row[2]))
        )
        self.infinite_input_fields["sell_qty"].set(
            "0" if row[3] is None else str(int(row[3]))
        )
        self.infinite_input_fields["cash_flow_amount"].set(
            self.format_input_number(row[4] if row[4] is not None else 0)
        )
        self.update_infinite_execution_guard()
        self.set_status(f"Infinite input loaded: {row[0]}")

    def refresh_infinite_status(self, setting: InfiniteSetting) -> None:
        if self.infinite_status_tree is None:
            return
        for item in self.infinite_status_tree.get_children():
            self.infinite_status_tree.delete(item)
        status = infinite_status_view(self.con, setting)
        rows = [
            ("오늘 날짜", status["today"]),
            ("상태", status["phase"]),
            ("진행률", self.format_percent(status["progress"])),
            ("누적개수", status["cumulative_qty"]),
            ("누적금", self.format_money(status["cumulative_value"])),
            ("초기 누적개수", setting.initial_cumulative_qty),
            ("초기 누적매수액", self.format_money(setting.initial_cumulative_amount)),
            ("평단", self.format_number(status["avg_price"])),
            ("현재가", self.format_number(status["current_price"])),
            ("환율", self.format_number(status["fx_rate"])),
            ("누적수익", self.format_money(status["cumulative_profit"])),
            ("누적입출금", self.format_money(status["cumulative_withdrawal"])),
            ("반복리 기준원금", self.format_money(status["repeat_principal"])),
            ("1회매수금", self.format_money(status["per_buy_amount"])),
            ("수익률", self.format_percent(status["return_rate"])),
            ("일변동", self.format_percent(status["day_change"])),
            ("회차T", self.format_number(status["t_value"])),
        ]
        for field, value in rows:
            self.infinite_status_tree.insert("", tk.END, values=(field, value))
        self.resize_infinite_status_columns()

    def resize_infinite_status_columns(self, _event=None) -> None:
        if self.infinite_status_tree is None:
            return
        width = self.infinite_status_tree.winfo_width()
        if width <= 1:
            return
        available = max(width - 8, 120)
        field_width = max(70, min(112, int(available * 0.32)))
        value_width = max(available - field_width, 1)
        self.infinite_status_tree.column("field", width=field_width, minwidth=70)
        self.infinite_status_tree.column("value", width=value_width, minwidth=1)

    def execute_vr_orders(self) -> None:
        profile_kind = "vr"
        profile_name = self.kiwoom_profile_name(profile_kind)
        try:
            profile = self.current_profile()
            query_day = date.today()
            basis = self.selected_snapshot()
            if basis is None:
                raise ValueError("VR 주문 기준 행이 없습니다.")
            if not basis.get("is_order_basis"):
                raise ValueError("주문생성 기준 행에서만 VR 주문을 실행할 수 있습니다.")
            start_day, end_day = self.snapshot_date_range(basis)
            if not (start_day <= query_day <= end_day):
                raise ValueError(
                    f"오늘 날짜가 주문표 기간에 포함되지 않습니다. 주문표 기간: {start_day}~{end_day}"
                )
            cycle_no = int(basis["cycle_no"])

            order_rows = self.vr_api_order_rows(profile, basis)
            if not order_rows:
                raise ValueError("실행할 VR 주문이 없습니다.")

            credentials = self.current_kiwoom_credentials_from_form(profile_kind)
            credentials = self.safe_save_kiwoom_credentials(
                profile_kind, profile_name, credentials
            )
            self.vr_order_api_status_var.set("토큰 확인 중...")
            self.update_idletasks()
            token, renewed = ensure_access_token(profile_kind, profile_name, credentials)

            self.vr_order_api_status_var.set("현재차수 체결내역 조회 중...")
            self.update_idletasks()
            orders = request_us_period_order_history(
                credentials,
                token,
                start_date=start_day.strftime("%Y%m%d"),
                end_date=query_day.strftime("%Y%m%d"),
                slby_tp="0",
                stex_tp=default_us_stock_exchange_code(profile.symbol),
                stk_cd=profile.symbol.upper(),
                oppo_trde_tp="%",
            )
            fill_rows = self.vr_fill_history_rows(
                self.result_rows(orders), profile.symbol
            )
            fill_summary = self.vr_fill_price_summary(fill_rows)
            remaining_rows, deducted_rows, unmatched_fills = self.apply_vr_fill_exclusions(
                order_rows, fill_summary
            )
            self.kiwoom_vr_fill_result = {
                "profile": profile_name,
                "symbol": profile.symbol.upper(),
                "cycle_no": cycle_no,
                "period_kind": "current",
                "order_period": {
                    "start_date": start_day.strftime("%Y%m%d"),
                    "end_date": end_day.strftime("%Y%m%d"),
                    "query_end_date": query_day.strftime("%Y%m%d"),
                },
                "token_renewed": renewed,
                "fills": fill_rows,
                "price_summary": fill_summary,
                "orders": orders,
            }
            self.refresh_vr_fill_history_tree(fill_rows, fill_summary)
            self.kiwoom_vr_fill_period_var.set(
                f"현재차수 주문표 기간: {start_day} ~ {end_day} "
                f"(조회 {start_day} ~ {query_day})"
            )
            self.kiwoom_vr_fill_status_var.set(
                f"현재차수 조회 성공: {profile.symbol.upper()} / 체결 {len(fill_rows)}건"
            )
            if not remaining_rows:
                self.vr_order_api_status_var.set("현재차수 체결 차감 후 전송할 주문이 없습니다.")
                messagebox.showinfo("VR 주문실행", "현재차수 체결 차감 후 전송할 주문이 없습니다.")
                return

            confirm_lines = self.vr_order_confirm_lines(
                profile,
                start_day,
                end_day,
                order_rows,
                deducted_rows,
                remaining_rows,
                unmatched_fills,
            )
            if not messagebox.askyesno("VR 주문실행 확인", "\n".join(confirm_lines)):
                self.vr_order_api_status_var.set("VR 주문실행 취소")
                return

            successes: list[str] = []
            self.vr_order_api_status_var.set("VR 주문 전송 중...")
            self.update_idletasks()
            for index, row in enumerate(remaining_rows, start=1):
                try:
                    kwargs = {
                        "stex_tp": row["stex_tp"],
                        "stk_cd": row["symbol"],
                        "ord_qty": row["quantity"],
                        "ord_uv": row["price"],
                        "trde_tp": row["trde_tp"],
                    }
                    if row["side"] == "buy":
                        result = request_us_buy_order(credentials, token, **kwargs)
                    else:
                        result = request_us_sell_order(
                            credentials, token, stop_pric=None, **kwargs
                        )
                    ord_no = result.get("ord_no") or "-"
                    successes.append(
                        f"{index}. {row['side_label']} {row['quantity']}주 "
                        f"{self.clean_number_text(row['price'])} 주문번호 {ord_no}"
                    )
                except KiwoomApiError as exc:
                    message = self.format_kiwoom_error(
                        f"{index}번째 VR 주문 실패", exc
                    )
                    if successes:
                        message += "\n성공 주문:\n" + "\n".join(successes)
                    self.vr_order_api_status_var.set(message)
                    self.set_status(f"VR 주문실행 일부 실패: {profile_name}")
                    return

            token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
            message = f"VR 주문실행 완료: {len(successes)}건 / {token_state}"
            self.vr_order_api_status_var.set(message + "\n" + "\n".join(successes))
            self.set_status(f"VR 주문실행 완료: {profile_name}")
        except KiwoomApiError as exc:
            message = self.format_kiwoom_error("VR 주문실행 실패", exc)
            self.vr_order_api_status_var.set(message)
            self.set_status(f"VR 주문실행 실패: {profile_name}")
        except Exception as exc:
            self.vr_order_api_status_var.set(f"VR 주문실행 실패: {exc}")
            self.show_error(exc)

    def vr_api_order_rows(self, profile: Profile, basis: dict) -> list[dict]:
        quantity_step = self.int_field(self.view_fields, "quantity_step")
        if quantity_step <= 0:
            quantity_step = int(profile.quantity_step or 1)
        profile = update_profile(profile, quantity_step=quantity_step)
        rows = order_level_values(profile, basis, quantity_step=quantity_step)
        buy_rows = [row for row in rows if row["side"] == "BUY"]
        sell_rows = [row for row in rows if row["side"] == "SELL"]
        buy_limit = self.optional_int(self.view_fields["buy_rows"].get())
        sell_limit = self.optional_int(self.view_fields["sell_rows"].get())
        if buy_limit is not None:
            buy_rows = buy_rows[:buy_limit]
        if sell_limit is not None:
            sell_rows = sell_rows[:sell_limit]

        order_rows: list[dict] = []
        for source in buy_rows + sell_rows:
            side = "buy" if source["side"] == "BUY" else "sell"
            quantity = int(source.get("quantity_step") or quantity_step)
            if quantity <= 0:
                continue
            price = round(float(source["price"]), 2)
            order_rows.append(
                {
                    "side": side,
                    "side_label": "매수" if side == "buy" else "매도",
                    "symbol": profile.symbol.upper(),
                    "stex_tp": default_us_stock_exchange_code(profile.symbol),
                    "order_type": "지정가",
                    "trde_tp": "00",
                    "price": price,
                    "price_key": self.price_key(price),
                    "quantity": quantity,
                    "level_no": int(source.get("level_no") or 0),
                }
            )
        return order_rows

    def apply_vr_fill_exclusions(
        self, order_rows: list[dict], fill_summary: list[dict]
    ) -> tuple[list[dict], list[dict], list[dict]]:
        fill_remaining: dict[tuple[str, str], int] = {}
        fill_amounts: dict[tuple[str, str], float] = {}
        for fill in fill_summary:
            side = str(fill.get("side") or "")
            price = self.price_key(fill.get("price"))
            if not side or not price:
                continue
            key = (side, price)
            fill_remaining[key] = fill_remaining.get(key, 0) + int(fill.get("quantity") or 0)
            fill_amounts[key] = fill_amounts.get(key, 0.0) + float(fill.get("amount") or 0)

        remaining_rows: list[dict] = []
        deducted_rows: list[dict] = []
        for row in order_rows:
            key = (row["side"], row["price_key"])
            quantity = int(row["quantity"])
            deducted = min(quantity, fill_remaining.get(key, 0))
            if deducted:
                fill_remaining[key] -= deducted
                deducted_rows.append({**row, "deducted_quantity": deducted})
            remaining = quantity - deducted
            if remaining > 0:
                remaining_rows.append({**row, "quantity": remaining, "deducted_quantity": deducted})

        unmatched_fills = []
        for (side, price), quantity in fill_remaining.items():
            if quantity <= 0:
                continue
            unmatched_fills.append(
                {
                    "side": side,
                    "side_label": "매수" if side == "buy" else "매도",
                    "price": price,
                    "quantity": quantity,
                    "amount": fill_amounts.get((side, price), 0.0),
                }
            )
        return remaining_rows, deducted_rows, unmatched_fills

    def vr_order_confirm_lines(
        self,
        profile: Profile,
        start_day: date,
        end_day: date,
        order_rows: list[dict],
        deducted_rows: list[dict],
        remaining_rows: list[dict],
        unmatched_fills: list[dict],
    ) -> list[str]:
        original_summary = self.order_rows_side_summary(order_rows)
        deducted_summary = self.order_rows_side_summary(deducted_rows, "deducted_quantity")
        remaining_summary = self.order_rows_side_summary(remaining_rows)
        lines = [
            f"{profile.symbol.upper()} VR 현재차수 주문을 실행할까요?",
            f"주문표 기간: {start_day} ~ {end_day}",
            "",
            (
                f"원주문: 매수 {original_summary['buy_count']}건/{original_summary['buy_qty']}주, "
                f"매도 {original_summary['sell_count']}건/{original_summary['sell_qty']}주"
            ),
            (
                f"현재차수 체결 제외: 매수 {deducted_summary['buy_qty']}주, "
                f"매도 {deducted_summary['sell_qty']}주"
            ),
            (
                f"실제 전송: 매수 {remaining_summary['buy_count']}건/{remaining_summary['buy_qty']}주, "
                f"매도 {remaining_summary['sell_count']}건/{remaining_summary['sell_qty']}주"
            ),
            "",
            "전송 주문:",
        ]
        for row in remaining_rows:
            lines.append(
                f"- {row['side_label']} {row['quantity']}주 / "
                f"{self.clean_number_text(row['price'])} / 지정가"
            )
        if unmatched_fills:
            lines.extend(["", "주문표 가격과 매칭되지 않은 현재차수 체결:"])
            for row in unmatched_fills:
                lines.append(
                    f"- {row['side_label']} {row['quantity']}주 / {row['price']}"
                )
        lines.extend(
            [
                "",
                "확인을 누르면 키움 REST API로 실제 지정가 주문이 전송됩니다.",
                "오늘 이미 넣어둔 미체결 주문은 체결수량이 아니므로 자동 제외되지 않습니다.",
            ]
        )
        return lines

    @staticmethod
    def order_rows_side_summary(rows: list[dict], quantity_key: str = "quantity") -> dict:
        summary = {
            "buy_count": 0,
            "buy_qty": 0,
            "sell_count": 0,
            "sell_qty": 0,
        }
        for row in rows:
            side = str(row.get("side") or "")
            quantity = int(row.get(quantity_key) or 0)
            if quantity <= 0:
                continue
            if side == "buy":
                summary["buy_count"] += 1
                summary["buy_qty"] += quantity
            elif side == "sell":
                summary["sell_count"] += 1
                summary["sell_qty"] += quantity
        return summary

    def price_key(self, value) -> str:
        price = self.clean_float(value)
        return f"{round(price, 2):.2f}" if price else ""

    def infinite_api_order_rows(
        self, setting: InfiniteSetting, plan: dict[str, object]
    ) -> list[dict]:
        rows: list[dict] = []
        for group, side in (("buy", "buy"), ("sell", "sell")):
            for item in plan.get(group, []):
                quantity = int(item.get("quantity") or 0)
                if quantity <= 0:
                    continue
                order_type = str(item.get("order_type") or "").strip()
                trde_tp = self.kiwoom_order_type_code(side, order_type)
                price = item.get("price")
                if trde_tp in ("00", "30") and price is None:
                    raise ValueError(f"{order_type} 주문은 가격이 필요합니다.")
                rows.append(
                    {
                        "side": side,
                        "side_label": "매수" if side == "buy" else "매도",
                        "symbol": setting.symbol.upper(),
                        "stex_tp": default_us_stock_exchange_code(setting.symbol),
                        "order_type": order_type,
                        "trde_tp": trde_tp,
                        "price": None if trde_tp == "33" else price,
                        "quantity": quantity,
                    }
                )
        return rows

    def kiwoom_order_type_code(self, side: str, order_type: str) -> str:
        normalized = order_type.upper()
        if normalized == "LOC":
            return "30"
        if normalized == "MOC" and side == "sell":
            return "33"
        if order_type == "지정가" or normalized in ("LIMIT", "00"):
            return "00"
        raise ValueError(f"지원하지 않는 주문유형입니다: {side} {order_type}")

    def execute_infinite_after_api_input(self) -> None:
        try:
            result = self.kiwoom_execution_preview_result
            if not result:
                raise ValueError("체결입력정보 조회 결과가 없습니다.")
            profile_name = self.kiwoom_profile_name("infinite")
            setting = load_infinite_setting(
                self.con, self.selected_infinite_profile_name()
            )
            if result.get("profile") != profile_name:
                raise ValueError("조회 결과의 프로필이 현재 선택 프로필과 다릅니다.")
            if str(result.get("symbol") or "").upper() != setting.symbol.upper():
                raise ValueError("조회 결과의 종목이 현재 프로필 종목과 다릅니다.")
            preview = dict(result.get("preview") or {})
            preview_date = str(preview.get("trade_date") or "").strip()
            input_date = self.infinite_input_fields["trade_date"].get().strip()
            if not preview_date or preview_date == "-":
                raise ValueError("조회 결과에 체결 입력일이 없습니다.")
            if preview_date != input_date:
                raise ValueError(
                    f"조회 입력일({preview_date})과 현재 입력일({input_date})이 다릅니다."
                )
            avg_price = str(preview.get("avg_price") or "").strip()
            if self.clean_float(avg_price) <= 0:
                raise ValueError("조회 결과에 평균단가가 없습니다.")
            self.infinite_input_fields["avg_price"].set(avg_price)
            self.infinite_input_fields["buy_qty"].set(str(preview.get("buy_qty") or 0))
            self.infinite_input_fields["sell_qty"].set(str(preview.get("sell_qty") or 0))
            setting, trade_date = self.save_infinite_execution_for_order()
            self.refresh_infinite_orders(setting)
            basis = order_basis_row(self.con, setting)
            if basis is None:
                raise ValueError("금일 주문표를 생성하지 못했습니다.")
            basis_date = basis["trade_date"]
            if isinstance(basis_date, str):
                basis_date = date.fromisoformat(basis_date)
            if basis_date != date.today():
                raise ValueError(f"금일 주문표가 아닙니다: {basis_date}")
            plan = infinite_order_plan(self.con, setting)
            if not plan["buy"] and not plan["sell"]:
                raise ValueError("금일 실행할 주문이 없습니다.")
            self.set_status(f"무한매수법 {trade_date} 체결 입력 후 주문실행 준비 완료")
            self.execute_infinite_orders()
        except Exception as exc:
            self.infinite_order_api_status_var.set(f"체결입력 후 주문실행 실패: {exc}")
            self.show_error(exc)

    def execute_infinite_orders(self) -> None:
        profile_kind = "infinite"
        profile_name = self.kiwoom_profile_name(profile_kind)
        try:
            setting = load_infinite_setting(self.con, self.selected_infinite_profile_name())
            basis = order_basis_row(self.con, setting)
            if basis is None:
                raise ValueError("주문 기준 행이 없습니다.")
            basis_date = basis["trade_date"]
            if isinstance(basis_date, str):
                basis_date = date.fromisoformat(basis_date)
            if basis_date != date.today():
                raise ValueError(
                    f"오늘 주문표만 실행할 수 있습니다. 현재 주문표 날짜: {basis_date}"
                )
            plan = infinite_order_plan(self.con, setting)
            order_rows = self.infinite_api_order_rows(setting, plan)
            if not order_rows:
                raise ValueError("실행할 주문이 없습니다.")

            confirm_lines = [
                f"{setting.symbol.upper()} {basis_date} 주문 {len(order_rows)}건을 실행할까요?",
                "",
            ]
            for row in order_rows:
                price = "시장가" if row["price"] is None else f"{float(row['price']):.2f}"
                confirm_lines.append(
                    f"{row['side_label']} {row['quantity']}주 / {price} / {row['order_type']}"
                )
            confirm_lines.extend(
                [
                    "",
                    "확인을 누르면 키움 REST API로 실제 주문 요청이 전송됩니다.",
                ]
            )
            if not messagebox.askyesno("무한매수법 주문실행 확인", "\n".join(confirm_lines)):
                return

            credentials = self.current_kiwoom_credentials_from_form(profile_kind)
            credentials = self.safe_save_kiwoom_credentials(
                profile_kind, profile_name, credentials
            )
            self.infinite_order_api_status_var.set("토큰 확인 중...")
            self.update_idletasks()
            token, renewed = ensure_access_token(profile_kind, profile_name, credentials)
            stex_tp = self.resolve_kiwoom_us_exchange_code(
                credentials, token, setting.symbol
            )
            order_rows = [{**row, "stex_tp": stex_tp} for row in order_rows]

            successes: list[str] = []
            self.infinite_order_api_status_var.set("주문 전송 중...")
            self.update_idletasks()
            for index, row in enumerate(order_rows, start=1):
                try:
                    kwargs = {
                        "stex_tp": row["stex_tp"],
                        "stk_cd": row["symbol"],
                        "ord_qty": row["quantity"],
                        "ord_uv": row["price"],
                        "trde_tp": row["trde_tp"],
                    }
                    if row["side"] == "buy":
                        result = request_us_buy_order(credentials, token, **kwargs)
                    else:
                        result = request_us_sell_order(
                            credentials, token, stop_pric=None, **kwargs
                        )
                    ord_no = result.get("ord_no") or "-"
                    successes.append(
                        f"{index}. {row['side_label']} {row['quantity']}주 {row['order_type']} 주문번호 {ord_no}"
                    )
                except KiwoomApiError as exc:
                    message = self.format_kiwoom_error(
                        f"{index}번째 주문 실패", exc
                    )
                    if successes:
                        message += "\n성공 주문:\n" + "\n".join(successes)
                    self.infinite_order_api_status_var.set(message)
                    self.set_status(f"무한매수법 주문실행 일부 실패: {profile_name}")
                    return

            token_state = "토큰 자동발급" if renewed else "저장 토큰 사용"
            message = f"주문실행 완료: {len(successes)}건 / {token_state}"
            self.infinite_order_api_status_var.set(message + "\n" + "\n".join(successes))
            self.set_status(f"무한매수법 주문실행 완료: {profile_name}")
        except KiwoomApiError as exc:
            message = self.format_kiwoom_error("무한매수법 주문실행 실패", exc)
            self.infinite_order_api_status_var.set(message)
            self.set_status(f"무한매수법 주문실행 실패: {profile_name}")
        except Exception as exc:
            self.infinite_order_api_status_var.set(f"무한매수법 주문실행 실패: {exc}")
            self.show_error(exc)

    def refresh_infinite_orders(self, setting: InfiniteSetting) -> None:
        if self.infinite_order_tree is None:
            return
        if self.infinite_order_execute_button is not None:
            self.infinite_order_execute_button.configure(state=tk.DISABLED)
        if self.infinite_order_execute_after_input_button is not None:
            self.infinite_order_execute_after_input_button.configure(state=tk.DISABLED)
        self.infinite_order_api_status_var.set("")
        for item in self.infinite_order_tree.get_children():
            self.infinite_order_tree.delete(item)
        basis = order_basis_row(self.con, setting)
        if basis is None:
            self.update_infinite_after_input_order_button(setting, False)
            self.infinite_order_info_var.set("주문 기준 로우가 없습니다.")
            return
        plan = infinite_order_plan(self.con, setting)
        if not plan["buy"] and not plan["sell"] and str(plan["title"]).startswith("\uc8fc\ubb38\ubd88\uac00"):
            self.update_infinite_after_input_order_button(setting, False)
            self.infinite_order_info_var.set(
                f"{plan['title']} | {setting.symbol} | {setting.mode} | "
                f"\u0031\ud68c\ub9e4\uc218\uae08 {self.format_money(plan['per_buy_amount'])}"
            )
            return
        if not plan["buy"] and not plan["sell"] and str(plan["title"]).startswith("주문불가"):
            self.infinite_order_info_var.set(
                f"{plan['title']} | {setting.symbol} | {setting.mode} | "
                f"1회매수금 {self.format_money(plan['per_buy_amount'])}"
            )
            return
        self.infinite_order_info_var.set(
            f"{plan['title']} | {basis['trade_date']} 주문표 | {setting.symbol} | {setting.mode} | "
            f"T {self.format_number(basis['t_value'])} | 누적수량 {basis['cumulative_qty']} | "
            f"1회매수금 {self.format_money(plan['per_buy_amount'])}"
        )
        executable_date = basis["trade_date"]
        if isinstance(executable_date, str):
            executable_date = date.fromisoformat(executable_date)
        has_orders = bool(plan["buy"] or plan["sell"])
        has_today_order_table = executable_date == date.today() and has_orders
        if (
            self.infinite_order_execute_button is not None
            and has_today_order_table
        ):
            self.infinite_order_execute_button.configure(state=tk.NORMAL)
        self.update_infinite_after_input_order_button(setting, has_today_order_table)
        for group in ("buy", "sell"):
            if group == "sell" and plan["buy"] and plan["sell"]:
                self.infinite_order_tree.insert(
                    "",
                    tk.END,
                    values=("", "────────", "", ""),
                    tags=("order_separator",),
                )
            tag = "buy_order" if group == "buy" else "sell_order"
            for item in plan[group]:
                self.infinite_order_tree.insert(
                    "",
                    tk.END,
                    values=(
                        item["side"],
                        item["order_type"],
                        "" if item["price"] is None else f"{item['price']:.2f}",
                        item["quantity"],
                    ),
                    tags=(tag,),
                )

    def _build_settings(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="투자 설정", padding=10)
        frame.pack(fill=tk.X)
        fields = [
            ("start_date", "시작일", "2026-06-08"),
            ("start_week_no", "시작주차", "2"),
            ("symbol", "종목", "TQQQ"),
            ("account_number", "계좌번호", ""),
            ("min_ratio", "최소 비율", "0.85"),
            ("max_ratio", "최대 비율", "1.15"),
            ("initial_v", "초기 V", "0"),
            ("initial_pool", "초기 Pool", "0"),
            ("initial_principal", "초기 투자원금", "0"),
            ("initial_shares", "초기 개수", "0"),
        ]
        for row, (key, label, default) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar(value=default)
            self.profile_fields[key] = var
            ttk.Entry(frame, textvariable=var, width=18).grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)

        frame.columnconfigure(1, weight=1)
        ttk.Button(frame, text="프로필 저장", command=self.save_profile_settings).grid(
            row=len(fields), column=0, columnspan=2, sticky=tk.EW, pady=(10, 0)
        )
    def _build_cycle_input(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="주차별 입력", padding=10)
        frame.pack(fill=tk.X)
        fields = [
            ("cycle_no", "입력 주차", "0"),
            ("result_period", "결과 구간", ""),
            ("next_period", "생성될 주문 구간", ""),
            ("close_price", "종가", ""),
            ("trade_amount", "매수/매도금액", "0"),
            ("shares", "보유 개수", "0"),
            ("contribution_amount", "적립/인출금액", "0"),
            ("dividend", "세후배당", "0"),
            ("g_config", "G 조건", "15,26,1"),
            ("g_start_cycle_no", "G 시작주차", "2"),
            ("buy_limit_config", "매수한도 조건", "25%,26,0%"),
            ("buy_limit_start_week_no", "매수한도 시작주차", "2"),
        ]
        for row, (key, label, default) in enumerate(fields):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar(value=default)
            self.cycle_fields[key] = var
            state = "readonly" if key in {"cycle_no", "result_period", "next_period"} else "normal"
            ttk.Entry(frame, textvariable=var, width=20, state=state).grid(
                row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2
            )
        frame.columnconfigure(1, weight=1)
        ttk.Button(frame, text="주차 날짜 적용", command=self.apply_cycle_dates).grid(
            row=len(fields), column=0, columnspan=2, sticky=tk.EW, pady=(10, 0)
        )
        self.save_cycle_button = ttk.Button(
            frame,
            text="저장하고 다음 주차 매수/매도점 보기",
            command=self.save_cycle_and_show_orders,
        )
        self.save_cycle_button.grid(
            row=len(fields) + 1, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0)
        )
        ttk.Label(
            parent,
            text="G/매수한도 조건은 초기값,증가주기(주),증가값 형식입니다. 예: 15,26,1 / 75%,26,-5%",
            style="Hint.TLabel",
        ).pack(fill=tk.X, pady=(8, 0))

    def add_condition_fields(
        self,
        parent: ttk.Frame,
        row: int,
        prefix: str,
        label: str,
        defaults: tuple[str, str, str],
    ) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        container = ttk.Frame(parent)
        container.grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)
        parts = (
            ("initial", "", defaults[0], 7),
            ("period", "주기", defaults[1], 5),
            ("step", "증분", defaults[2], 7),
        )
        for suffix, part_label, default, width in parts:
            if part_label:
                ttk.Label(container, text=part_label).pack(side=tk.LEFT, padx=(8, 2))
            var = tk.StringVar(value=default)
            self.cycle_fields[f"{prefix}_{suffix}"] = var
            ttk.Entry(container, textvariable=var, width=width).pack(side=tk.LEFT)

    @staticmethod
    def add_form_separator(parent: ttk.Frame, row: int) -> None:
        ttk.Separator(parent, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, pady=(7, 5)
        )

    def _build_cycle_input(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="주차별 입력", padding=10)
        frame.pack(fill=tk.X)
        fields = [
            ("cycle_no", "입력 주차", "0"),
            ("result_period", "결과 구간", ""),
            ("next_period", "생성할 주문 구간", ""),
            ("close_price", "종가", ""),
            ("trade_amount", "매수/매도금액", "0"),
            ("shares", "보유 개수", "0"),
            ("contribution_amount", "적립/인출금액", "0"),
            ("dividend", "세후배당", "0"),
        ]
        row = 0
        for key, label, default in fields:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
            var = tk.StringVar(value=default)
            self.cycle_fields[key] = var
            state = "readonly" if key in {"cycle_no", "result_period", "next_period"} else "normal"
            ttk.Entry(frame, textvariable=var, width=20, state=state).grid(
                row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2
            )
            row += 1
            if key in {"next_period", "shares", "dividend"}:
                self.add_form_separator(frame, row)
                row += 1

        self.cycle_fields["g_config"] = tk.StringVar(value="15,26,1")
        self.cycle_fields["buy_limit_config"] = tk.StringVar(value="25%,26,0%")
        self.add_condition_fields(frame, row, "g", "G 조건", ("15", "26", "1"))
        row += 1
        ttk.Label(frame, text="G 시작주차").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.cycle_fields["g_start_cycle_no"] = tk.StringVar(value="2")
        ttk.Entry(frame, textvariable=self.cycle_fields["g_start_cycle_no"], width=20).grid(
            row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2
        )
        row += 1
        self.add_form_separator(frame, row)
        row += 1
        self.add_condition_fields(frame, row, "buy_limit", "매수한도", ("25%", "26", "0%"))
        row += 1
        ttk.Label(frame, text="매수한도 시작주차").grid(row=row, column=0, sticky=tk.W, pady=2)
        self.cycle_fields["buy_limit_start_week_no"] = tk.StringVar(value="2")
        ttk.Entry(
            frame,
            textvariable=self.cycle_fields["buy_limit_start_week_no"],
            width=20,
        ).grid(row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2)

        frame.columnconfigure(1, weight=1)
        ttk.Button(frame, text="주차 날짜 적용", command=self.apply_cycle_dates).grid(
            row=row + 1, column=0, columnspan=2, sticky=tk.EW, pady=(10, 0)
        )
        self.save_cycle_button = ttk.Button(
            frame,
            text="저장하고 다음 주차 매수/매도점 보기",
            command=self.save_cycle_and_show_orders,
        )
        self.save_cycle_button.grid(
            row=row + 2, column=0, columnspan=2, sticky=tk.EW, pady=(6, 0)
        )

    def _build_order_options(self, parent: ttk.Frame) -> None:
        frame = ttk.LabelFrame(parent, text="매수/매도점 보기 옵션", padding=10)
        frame.pack(fill=tk.X)
        self.view_fields["cycle_no"] = tk.StringVar(value="")
        self.view_fields["quantity_step"] = tk.StringVar(value="4")
        self.view_fields["buy_rows"] = tk.StringVar(value="")
        self.view_fields["sell_rows"] = tk.StringVar(value="")

        labels = [
            ("cycle_no", "기준 주차"),
            ("quantity_step", "갯수 간격"),
            ("buy_rows", "매수 표시 줄수"),
            ("sell_rows", "매도 표시 줄수"),
        ]
        for row, (key, label) in enumerate(labels):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
            ttk.Entry(frame, textvariable=self.view_fields[key], width=18).grid(
                row=row, column=1, sticky=tk.EW, padx=(8, 0), pady=2
            )
        for key in ("quantity_step", "buy_rows", "sell_rows"):
            self.view_fields[key].trace_add("write", lambda *_args: self.after_idle(self.refresh_snapshot))
        frame.columnconfigure(1, weight=1)
        ttk.Button(frame, text="매수/매도점 다시 계산", command=self.recalculate_current_view).grid(
            row=len(labels), column=0, columnspan=2, sticky=tk.EW, pady=(10, 0)
        )
        ttk.Label(
            parent,
            text="갯수 간격을 4, 8 등으로 바꾸면 저장된 주차 결과는 그대로 두고 표만 즉시 다시 계산합니다.",
            style="Hint.TLabel",
        ).pack(fill=tk.X, pady=(8, 0))

    def _build_cycle_rows(self, parent: ttk.Frame, grid_row: int | None = None) -> None:
        frame = ttk.LabelFrame(parent, text="VR 로우데이터", padding=10)
        if grid_row is None:
            frame.pack(fill=tk.BOTH, expand=True)
        else:
            frame.grid(row=grid_row, column=0, sticky="nsew")
        columns = (
            "cycle_no",
            "start_date",
            "end_date",
            "close_price",
            "g",
            "g_config",
            "g_start_cycle_no",
            "week_no",
            "status",
            "valuation",
            "v",
            "min_value",
            "max_value",
            "trade_amount",
            "contribution",
            "dividend",
            "prior_pool",
            "pool",
            "principal",
            "account_total",
            "return_rate",
            "profit",
            "shares",
            "buy_principal",
            "avg_cost",
            "buy_limit_ratio",
        )
        headings = {
            "cycle_no": "순번",
            "start_date": "시작일",
            "end_date": "종료일",
            "close_price": "종가",
            "g": "G",
            "g_config": "G 조건",
            "g_start_cycle_no": "G 시작주차",
            "week_no": "주차",
            "status": "상태",
            "valuation": "평가금",
            "v": "V",
            "min_value": "최소",
            "max_value": "최대",
            "trade_amount": "거래액",
            "contribution": "적립/인출",
            "dividend": "세후배당",
            "prior_pool": "시작 Pool",
            "pool": "마지막 Pool",
            "principal": "투자원금",
            "account_total": "계좌총액",
            "return_rate": "수익률",
            "profit": "수익금",
            "shares": "개수",
            "buy_principal": "매수원금",
            "avg_cost": "평단",
            "buy_limit_ratio": "매수한도",
        }
        self.raw_tree = ttk.Treeview(frame, columns=columns, show="headings", height=7)
        for column in columns:
            self.raw_tree.heading(column, text=headings[column])
            width = 86
            if column in {"start_date", "end_date"}:
                width = 92
            elif column in {"cycle_no", "g", "week_no", "shares"}:
                width = 58
            elif column in {"g_config", "g_start_cycle_no"}:
                width = 86
            self.raw_tree.column(column, width=width, anchor=tk.E)
        self.raw_tree.column("status", anchor=tk.CENTER)
        self.raw_tree.bind("<<TreeviewSelect>>", self.on_cycle_row_selected)

        yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.raw_tree.yview)
        xscroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.raw_tree.xview)
        self.raw_tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        self.raw_tree.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)

    def _build_summary(self, parent: ttk.Frame, grid_row: int | None = None) -> None:
        frame = ttk.LabelFrame(parent, text="선택 행 계산 근거", padding=10)
        if grid_row is None:
            frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        else:
            frame.grid(row=grid_row, column=0, sticky="nsew", pady=(12, 0))
        self.summary_tree = ttk.Treeview(frame, columns=("field", "value"), show="headings", height=11)
        self.summary_tree.heading("field", text="항목")
        self.summary_tree.heading("value", text="값")
        self.summary_tree.column("field", width=190, anchor=tk.W)
        self.summary_tree.column("value", width=520, anchor=tk.W)
        self.summary_tree.pack(fill=tk.BOTH, expand=True)

    def _build_order_table(self, parent: ttk.Frame, grid_row: int | None = None) -> None:
        frame = ttk.LabelFrame(parent, text="매수/매도점", padding=10)
        if grid_row is None:
            frame.pack(fill=tk.BOTH, expand=True, pady=(12, 0))
        else:
            frame.grid(row=grid_row, column=0, sticky="nsew", pady=(12, 0))
        self.order_info_var = tk.StringVar(value="저장된 VR 결과가 없습니다.")
        header = ttk.Frame(frame)
        header.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(header, textvariable=self.order_info_var).pack(side=tk.LEFT, fill=tk.X, expand=True)
        self.vr_order_execute_button = ttk.Button(
            header,
            text="주문실행",
            command=self.execute_vr_orders,
        )
        self.vr_order_execute_button.pack(side=tk.RIGHT, padx=(8, 0))
        ttk.Label(
            frame,
            textvariable=self.vr_order_api_status_var,
            style="Hint.TLabel",
            wraplength=760,
        ).pack(fill=tk.X, pady=(0, 6))
        columns = ("buy_min", "buy_shares", "buy_price", "buy_pool", "sell_max", "sell_shares", "sell_price", "sell_pool")
        self.order_tree = ttk.Treeview(frame, columns=columns, show="headings")
        headings = {
            "buy_min": "최소값",
            "buy_shares": "잔여갯수",
            "buy_price": "매수점",
            "buy_pool": "Pool",
            "sell_max": "최대값",
            "sell_shares": "잔여갯수",
            "sell_price": "매도점",
            "sell_pool": "Pool",
        }
        for column in columns:
            self.order_tree.heading(column, text=headings[column])
            self.order_tree.column(column, width=95, anchor=tk.E)
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.order_tree.yview)
        self.order_tree.configure(yscrollcommand=scroll.set)
        self.order_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_dashboard(self) -> None:
        if (
            self.dashboard_overview_tree is None
            or self.dashboard_due_tree is None
            or self.dashboard_vr_summary_tree is None
            or self.dashboard_infinite_summary_tree is None
            or self.dashboard_vr_tree is None
            or self.dashboard_infinite_tree is None
        ):
            return

        for tree in (
            self.dashboard_overview_tree,
            self.dashboard_due_tree,
            self.dashboard_vr_summary_tree,
            self.dashboard_infinite_summary_tree,
            self.dashboard_vr_tree,
            self.dashboard_infinite_tree,
        ):
            self.clear_tree(tree)

        vr_rows = self.dashboard_vr_rows()
        infinite_rows_data = self.dashboard_infinite_rows()
        self.ensure_dashboard_selection(vr_rows, infinite_rows_data)

        for row in vr_rows:
            self.dashboard_vr_tree.insert(
                "",
                tk.END,
                values=(
                    row["label"],
                    self.format_money(row["principal"]),
                    self.format_money(row["account_total"]),
                    self.format_money(row["profit"]),
                    self.format_percent(row["return_rate"]),
                    row["last_done_text"],
                    row["missing_text"],
                ),
            )

        for row in infinite_rows_data:
            self.dashboard_infinite_tree.insert(
                "",
                tk.END,
                values=(
                    row["label"],
                    self.format_money(row["principal"]),
                    self.format_money(row["cumulative_amount"]),
                    self.format_money(row["cumulative_value"]),
                    self.format_percent(row["return_rate"]),
                    self.format_number(row["avg_price"]),
                    row["missing_text"],
                ),
            )

        self.refresh_dashboard_summaries(vr_rows, infinite_rows_data)
        self.refresh_dashboard_charts(vr_rows, infinite_rows_data)
        self.update_dashboard_scrollregion()

    def ensure_dashboard_selection(
        self, vr_rows: list[dict], infinite_rows_data: list[dict]
    ) -> None:
        if not self.dashboard_selected_vr_name and vr_rows:
            self.dashboard_selected_vr_name = vr_rows[0]["name"]
        if not self.dashboard_selected_infinite_name and infinite_rows_data:
            self.dashboard_selected_infinite_name = infinite_rows_data[0]["name"]
        if self.dashboard_selected_vr_name not in {row["name"] for row in vr_rows}:
            self.dashboard_selected_vr_name = vr_rows[0]["name"] if vr_rows else ""
        if self.dashboard_selected_infinite_name not in {row["name"] for row in infinite_rows_data}:
            self.dashboard_selected_infinite_name = infinite_rows_data[0]["name"] if infinite_rows_data else ""

    def refresh_dashboard_summaries(
        self, vr_rows: list[dict], infinite_rows_data: list[dict]
    ) -> None:
        if (
            self.dashboard_overview_tree is None
            or self.dashboard_due_tree is None
            or self.dashboard_vr_summary_tree is None
            or self.dashboard_infinite_summary_tree is None
        ):
            return
        self.clear_tree(self.dashboard_overview_tree)
        self.clear_tree(self.dashboard_due_tree)
        self.clear_tree(self.dashboard_vr_summary_tree)
        self.clear_tree(self.dashboard_infinite_summary_tree)
        selected_vr = next(
            (row for row in vr_rows if row["name"] == self.dashboard_selected_vr_name),
            None,
        )
        selected_infinite = next(
            (
                row
                for row in infinite_rows_data
                if row["name"] == self.dashboard_selected_infinite_name
            ),
            None,
        )

        vr_due = sum(1 for row in vr_rows if row["missing_count"] > 0)
        infinite_due = sum(1 for row in infinite_rows_data if row["missing_count"] > 0)
        fx_rate = latest_fx_rate(self.con, date.today())

        vr_principal_usd = sum(row["principal"] for row in vr_rows)
        vr_value_usd = sum(row["account_total"] for row in vr_rows)
        vr_bought_usd = sum(row["buy_principal"] for row in vr_rows)
        vr_cash_usd = sum(row["cash_amount"] for row in vr_rows)

        infinite_principal_usd = sum(row["principal"] for row in infinite_rows_data)
        infinite_value_krw = sum(row["cumulative_value"] for row in infinite_rows_data)
        infinite_bought_usd = sum(row["cumulative_amount"] for row in infinite_rows_data)
        infinite_cash_usd = sum(row["cash_amount"] for row in infinite_rows_data)

        total_principal_krw = (vr_principal_usd + infinite_principal_usd) * fx_rate
        total_value_krw = (vr_value_usd * fx_rate) + infinite_value_krw + (infinite_cash_usd * fx_rate)
        total_profit_krw = total_value_krw - total_principal_krw
        total_bought_krw = (vr_bought_usd + infinite_bought_usd) * fx_rate
        total_cash_krw = (vr_cash_usd + infinite_cash_usd) * fx_rate
        total_cash_basis_krw = total_bought_krw + total_cash_krw
        total_cash_ratio = (
            total_cash_krw / total_cash_basis_krw if total_cash_basis_krw > 0 else None
        )
        separator = "\u2500" * 18

        overview_rows = [
            (
                "\uc6b4\uc6a9 \ud504\ub85c\ud544",
                f"VR {len(vr_rows)}\uac1c / \ubb34\ub9e4 {len(infinite_rows_data)}\uac1c",
            ),
            ("\uc801\uc6a9 \ud658\uc728", self.format_number(fx_rate)),
            (separator, separator),
            ("\ud569\uc0b0 \ud604\uc7ac\uc790\uc0b0(\uc6d0\ud654)", self.format_won(total_value_krw)),
            ("\ud569\uc0b0 \uc6d0\uae08(\uc6d0\ud654)", self.format_won(total_principal_krw)),
            (
                "\ud569\uc0b0 \uc190\uc775(\uc6d0\ud654) / \uc218\uc775\ub960",
                f"{self.format_won(total_profit_krw)} / "
                f"{self.format_percent(total_profit_krw / total_principal_krw if total_principal_krw else None)}",
            ),
            (separator, separator),
            ("\ucd1d \ub9e4\uc218\uae08(\uc6d0\ud654)", self.format_won(total_bought_krw)),
            (
                "\ucd1d \uc608\uc218\uae08(\uc6d0\ud654) / \ube44\uc728",
                f"{self.format_won(total_cash_krw)} / {self.format_percent(total_cash_ratio)}",
            ),
        ]
        for field, value in overview_rows:
            if field == separator:
                tags = ("separator",)
            elif field == "\ud569\uc0b0 \ud604\uc7ac\uc790\uc0b0(\uc6d0\ud654)":
                tags = ("summary_primary",)
            elif field.startswith("\ud569\uc0b0 \uc190\uc775"):
                tags = (
                    "summary_profit_positive"
                    if total_profit_krw >= 0
                    else "summary_profit_negative",
                )
            else:
                tags = ()
            self.dashboard_overview_tree.insert("", tk.END, values=(field, value), tags=tags)

        due_count = vr_due + infinite_due
        if self.dashboard_due_frame is not None:
            self.dashboard_due_frame.configure(
                text=f"\ub300\uae30 / \ubbf8\uc791\uc131 ({due_count}\uac1c)"
            )

        for row in vr_rows:
            if row["missing_count"] > 0:
                self.dashboard_due_tree.insert(
                    "",
                    tk.END,
                    values=("VR", row["label"], row["issue"]),
                    tags=("due",),
                )
        for row in infinite_rows_data:
            if row["missing_count"] > 0:
                self.dashboard_due_tree.insert(
                    "",
                    tk.END,
                    values=("\ubb34\ub9e4", row["label"], row["issue"]),
                    tags=("due",),
                )
        if not self.dashboard_due_tree.get_children():
            self.dashboard_due_tree.insert(
                "",
                tk.END,
                values=("-", "-", "\ub300\uae30 / \ubbf8\uc791\uc131 \uc5c6\uc74c"),
                tags=("empty",),
            )

        vr_summary_rows = []
        if selected_vr is not None:
            latest = latest_cycle_snapshot(self.con, selected_vr["name"])
            vr_summary_rows.extend(
                [
                    ("VR \uc120\ud0dd", selected_vr["label"]),
                    ("\uacc4\uc88c\ucd1d\uc561", self.format_money(selected_vr["account_total"])),
                    (
                        "\uc190\uc775 / \uc218\uc775\ub960",
                        f"{self.format_money(selected_vr['profit'])} / "
                        f"{self.format_percent(selected_vr['return_rate'])}",
                    ),
                    (
                        "\uc644\ub8cc\uc8fc\ucc28 / \ubbf8\uc785\ub825",
                        f"{selected_vr['last_done_text']} / {selected_vr['missing_text'] or '\uc5c6\uc74c'}",
                    ),
                ]
            )
            if latest is not None:
                vr_summary_rows.extend(
                    [
                        (
                            "\ubc34\ub4dc \ud558\ub2e8/\uc0c1\ub2e8",
                            f"{self.format_money(latest['min_value'])} / "
                            f"{self.format_money(latest['max_value'])}",
                        ),
                        ("\ud3c9\uac00\uae08", self.format_money(latest["valuation"])),
                    ]
                )
        else:
            vr_summary_rows.append(("VR \uc120\ud0dd", "VR \ud45c\uc5d0\uc11c \ud504\ub85c\ud544\uc744 \ub354\ube14\ud074\ub9ad"))

        for field, value in vr_summary_rows:
            self.dashboard_vr_summary_tree.insert("", tk.END, values=(field, value))

        infinite_summary_rows = []
        if selected_infinite is not None:
            setting = self.selected_infinite_setting_for_dashboard()
            status = infinite_status_view(self.con, setting) if setting is not None else None
            infinite_summary_rows.extend(
                [
                    ("\ubb34\ub9e4 \uc120\ud0dd", selected_infinite["label"]),
                    ("\ud604\uc7ac \uc790\uc0b0", self.format_money(selected_infinite["cumulative_value"])),
                    (
                        "\ud3c9\ub2e8 / \uc218\uc775\ub960",
                        f"{self.format_number(selected_infinite['avg_price'])} / "
                        f"{self.format_percent(selected_infinite['return_rate'])}",
                    ),
                    (
                        "\ud22c\uc785 \uc9c4\ud589\ub960",
                        self.format_infinite_progress(status, setting.split_count)
                        if status is not None and setting is not None
                        else "",
                    ),
                ]
            )
            if status is not None:
                infinite_summary_rows.extend(
                    [
                        ("\ub204\uc801\uc218\uc775", self.format_money(status["cumulative_profit"])),
                        ("\ub204\uc801\uc785\ucd9c\uae08", self.format_money(status["cumulative_withdrawal"])),
                        ("1\ud68c\ub9e4\uc218\uae08", self.format_money(status["per_buy_amount"])),
                    ]
                )
        else:
            infinite_summary_rows.append(("\ubb34\ub9e4 \uc120\ud0dd", "\ubb34\ud55c\ub9e4\uc218 \ud45c\uc5d0\uc11c \ud504\ub85c\ud544\uc744 \ub354\ube14\ud074\ub9ad"))

        for field, value in infinite_summary_rows:
            self.dashboard_infinite_summary_tree.insert("", tk.END, values=(field, value))
    def refresh_dashboard_charts(
        self, vr_rows: list[dict], infinite_rows_data: list[dict]
    ) -> None:
        if not self.dashboard_chart_axes:
            return
        self.draw_vr_band_chart()
        self.draw_vr_profit_chart()
        self.draw_infinite_asset_chart()
        self.draw_infinite_profit_chart()
        for canvas in self.dashboard_chart_canvases.values():
            canvas.draw_idle()

    def draw_vr_band_chart(self) -> None:
        axis = self.dashboard_chart_axes.get("vr_band")
        if axis is None:
            return
        axis.clear()
        rows = self.selected_vr_snapshots()
        if not rows:
            self.draw_empty_chart(axis, "VR 프로필을 더블클릭하면 밴드 분석이 표시됩니다.")
            return
        dates = [row["end_date"] for row in rows]
        min_values = [float(row["min_value"]) for row in rows]
        max_values = [float(row["max_value"]) for row in rows]
        account_totals = [float(row["account_total"]) for row in rows]
        valuations = [float(row["valuation"]) for row in rows]
        label = self.vr_display_label(self.dashboard_selected_vr_name)
        axis.fill_between(dates, min_values, max_values, color="#dbe7ff", alpha=0.7, label="밴드(0.85~1.15)")
        axis.plot(dates, min_values, color="#4f7df3", linewidth=1.2, linestyle="--", label="하단")
        axis.plot(dates, max_values, color="#f0b429", linewidth=1.2, linestyle="--", label="상단")
        axis.plot(dates, account_totals, color="#2f9e44", marker="o", linewidth=1.8, markersize=3, label="계좌총액")
        axis.plot(dates, valuations, color="#e03131", linewidth=1.4, label="평가금")
        axis.set_title(label)
        axis.set_ylabel("금액")
        axis.grid(True, alpha=0.25)
        axis.legend(loc="best", fontsize=7)
        axis.tick_params(axis="x", labelrotation=25)
        axis.figure.tight_layout()

    def draw_vr_profit_chart(self) -> None:
        axis = self.dashboard_chart_axes.get("vr_profit")
        if axis is None:
            return
        axis.clear()
        rows = self.selected_vr_snapshots()
        if not rows:
            self.draw_empty_chart(axis, "VR 원금/손익 데이터가 없습니다.")
            return
        dates = [row["end_date"] for row in rows]
        principals = [float(row["principal"]) for row in rows]
        account_totals = [float(row["account_total"]) for row in rows]
        profits = [float(row["profit"]) for row in rows]
        axis.plot(dates, principals, color="#555", linewidth=1.4, label="원금")
        axis.plot(dates, account_totals, color="#2f9e44", marker="o", linewidth=1.8, markersize=3, label="계좌총액")
        axis.bar(dates, profits, color=["#36a269" if value >= 0 else "#e03131" for value in profits], alpha=0.35, label="손익")
        axis.axhline(0, color="#777", linewidth=0.8)
        axis.set_title(self.vr_display_label(self.dashboard_selected_vr_name))
        axis.set_ylabel("금액")
        axis.grid(True, alpha=0.25)
        axis.legend(loc="best", fontsize=7)
        axis.tick_params(axis="x", labelrotation=25)
        axis.figure.tight_layout()

    def draw_infinite_asset_chart(self) -> None:
        axis = self.dashboard_chart_axes.get("infinite_asset")
        if axis is None:
            return
        axis.clear()
        rows = self.selected_infinite_rows()
        setting = self.selected_infinite_setting_for_dashboard()
        if not rows or setting is None:
            self.draw_empty_chart(axis, "무한매수 프로필을 더블클릭하면 자산 분석이 표시됩니다.")
            return
        dates = [row["trade_date"] for row in rows]
        principals = [float(row.get("principal_after_withdrawal") or setting.initial_principal) for row in rows]
        cumulative_amounts = [float(row["cumulative_amount"] or 0) for row in rows]
        market_values = [
            float(row["cumulative_qty"] or 0) * float(row.get("close_price") or row.get("avg_price") or 0)
            for row in rows
        ]
        axis.plot(dates, principals, color="#555", linewidth=1.4, label="입출금 후 기준원금")
        axis.plot(dates, cumulative_amounts, color="#4f7df3", linewidth=1.4, label="누적매수액")
        axis.plot(dates, market_values, color="#2f9e44", marker="o", linewidth=1.8, markersize=2.5, label="현재 자산")
        axis.set_title(self.infinite_display_label(self.dashboard_selected_infinite_name))
        axis.set_ylabel("금액")
        axis.grid(True, alpha=0.25)
        axis.legend(loc="best", fontsize=7)
        axis.tick_params(axis="x", labelrotation=25)
        axis.figure.tight_layout()

    def draw_infinite_profit_chart(self) -> None:
        axis = self.dashboard_chart_axes.get("infinite_profit")
        if axis is None:
            return
        axis.clear()
        rows = self.selected_infinite_rows()
        if not rows:
            self.draw_empty_chart(axis, "무한매수 누적수익 데이터가 없습니다.")
            return
        dates = [row["trade_date"] for row in rows]
        stop_losses = []
        fees = []
        cash_flows = []
        net_profits = []
        stop_loss_total = 0.0
        fee_total = 0.0
        cash_flow_total = 0.0
        for row in rows:
            stop_loss_total += float(row.get("stop_loss") or 0)
            fee_total += float(row.get("fee") or 0)
            cash_flow_total += float(row.get("cash_flow_amount") or 0)
            stop_losses.append(stop_loss_total)
            fees.append(fee_total)
            cash_flows.append(cash_flow_total)
            net_profits.append(stop_loss_total - fee_total)
        axis.plot(dates, net_profits, color="#2f9e44", linewidth=1.8, label="누적수익-수수료")
        axis.plot(dates, stop_losses, color="#4f7df3", linewidth=1.2, linestyle="--", label="누적실현")
        axis.plot(dates, fees, color="#e03131", linewidth=1.2, linestyle="--", label="누적수수료")
        axis.plot(dates, cash_flows, color="#f08c00", linewidth=1.2, label="누적입출금")
        axis.axhline(0, color="#777", linewidth=0.8)
        axis.set_title(self.infinite_display_label(self.dashboard_selected_infinite_name))
        axis.set_ylabel("금액")
        axis.grid(True, alpha=0.25)
        axis.legend(loc="best", fontsize=7)
        axis.tick_params(axis="x", labelrotation=25)
        axis.figure.tight_layout()

    @staticmethod
    def draw_empty_chart(axis, message: str) -> None:
        axis.text(0.5, 0.5, message, ha="center", va="center", transform=axis.transAxes)
        axis.set_xticks([])
        axis.set_yticks([])
        for spine in axis.spines.values():
            spine.set_alpha(0.2)

    def dashboard_vr_rows(self) -> list[dict]:
        rows: list[dict] = []
        for profile in self.visible_vr_profiles():
            if profile.name == DEFAULT_PROFILE_NAME:
                continue
            snapshot = latest_cycle_snapshot(self.con, profile.name)
            status = profile_cycle_status(self.con, profile)
            missing = status["missing_cycles"]
            missing_count = 0 if profile.calculation_paused else int(status["missing_count"])
            principal = float(snapshot["principal"]) if snapshot else 0.0
            account_total = float(snapshot["account_total"]) if snapshot else 0.0
            profit = float(snapshot["profit"]) if snapshot else 0.0
            return_rate = float(snapshot["return_rate"]) if snapshot else None
            buy_principal = float(snapshot["buy_principal"]) if snapshot else 0.0
            cash_amount = float(snapshot["pool"]) if snapshot else 0.0
            last_done = status["last_done_cycle"]
            missing_text = "중단" if profile.calculation_paused else (f"{missing_count}개" if missing_count else "")
            missing_list = ", ".join(
                str(self.week_no_for_cycle(profile, item)) for item in missing[:8]
            )
            if len(missing) > 8:
                missing_list += "..."
            rows.append(
                {
                    "name": profile.name,
                    "label": self.vr_profile_label(profile),
                    "principal": principal,
                    "account_total": account_total,
                    "profit": profit,
                    "return_rate": return_rate,
                    "buy_principal": buy_principal,
                    "cash_amount": cash_amount,
                    "last_done_text": "-" if last_done is None else str(self.week_no_for_cycle(profile, last_done)),
                    "missing_count": missing_count,
                    "missing_text": missing_text,
                    "issue": "산출 중단" if profile.calculation_paused else f"{missing_count}개 주차 미입력: {missing_list}",
                }
            )
        return rows

    def dashboard_infinite_rows(self) -> list[dict]:
        rows: list[dict] = []
        yesterday = previous_us_trading_day(date.today() - timedelta(days=1))
        for setting in self.visible_infinite_profiles():
            if setting.name == INFINITE_DEFAULT_SETTING:
                continue
            generate_infinite_rows(
                self.con,
                setting,
                through=max(
                    yesterday,
                    self.infinite_rebuild_through_date(setting.name, setting.start_date),
                ),
            )
            status = infinite_status_view(self.con, setting)
            daily_rows = infinite_rows(self.con, setting.name)
            latest = daily_rows[-1] if daily_rows else None
            missing = self.infinite_missing_summary(setting)
            market_price = status["current_price"] or status["avg_price"] or 0.0
            market_value = (
                float(status["cumulative_qty"] or 0)
                * float(status["fx_rate"] or 1.0)
                * float(market_price)
            )
            principal = float(status["repeat_principal"] or setting.initial_principal)
            cumulative_amount = float(latest["cumulative_amount"]) if latest else 0.0
            cash_basis_principal = (
                float(latest.get("principal_after_withdrawal") or principal)
                if latest
                else principal
            )
            cash_amount = max(0.0, cash_basis_principal - cumulative_amount)
            rows.append(
                {
                    "name": setting.name,
                    "label": self.infinite_profile_label(setting),
                    "principal": principal,
                    "cumulative_amount": cumulative_amount,
                    "cumulative_value": market_value,
                    "cash_amount": cash_amount,
                    "return_rate": status["return_rate"],
                    "avg_price": status["avg_price"],
                    "missing_count": missing["count"],
                    "missing_text": "중단" if setting.calculation_paused else (f"{missing['count']}일" if missing["count"] else ""),
                    "issue": missing["issue"],
                }
            )
        return rows

    def infinite_missing_summary(self, setting: InfiniteSetting) -> dict:
        if setting.calculation_paused:
            return {"count": 0, "issue": "산출 중단"}
        yesterday = previous_us_trading_day(date.today() - timedelta(days=1))
        if yesterday < setting.start_date:
            return {"count": 0, "issue": ""}
        row = self.con.execute(
            """
            SELECT count(*), min(trade_date), max(trade_date)
            FROM infinite_rows
            WHERE setting_name = ?
              AND trade_date <= ?
              AND avg_price IS NULL
            """,
            [setting.name, yesterday],
        ).fetchone()
        count = int(row[0] or 0)
        if count == 0:
            return {"count": 0, "issue": ""}
        first_day = row[1]
        last_day = row[2]
        if first_day == last_day:
            issue = f"평단 미입력 {count}일: {first_day}"
        else:
            issue = f"평단 미입력 {count}일: {first_day} ~ {last_day}"
        return {"count": count, "issue": issue}

    def select_dashboard_vr_profile(self, event=None) -> None:
        if self.dashboard_vr_tree is None:
            return
        item_id = self.dashboard_vr_tree.identify_row(event.y) if event is not None else ""
        if not item_id:
            selection = self.dashboard_vr_tree.selection()
            item_id = selection[0] if selection else ""
        if not item_id:
            return
        values = self.dashboard_vr_tree.item(item_id, "values")
        if not values:
            return
        label = str(values[0])
        name = self.profile_display_to_name.get(label, label)
        self.dashboard_selected_vr_name = name
        self.set_status(f"VR 그래프 분석: {label}")
        self.refresh_dashboard()

    def select_dashboard_infinite_profile(self, event=None) -> None:
        if self.dashboard_infinite_tree is None:
            return
        item_id = self.dashboard_infinite_tree.identify_row(event.y) if event is not None else ""
        if not item_id:
            selection = self.dashboard_infinite_tree.selection()
            item_id = selection[0] if selection else ""
        if not item_id:
            return
        values = self.dashboard_infinite_tree.item(item_id, "values")
        if not values:
            return
        label = str(values[0])
        name = self.infinite_display_to_name.get(label, label)
        self.dashboard_selected_infinite_name = name
        self.set_status(f"무한매수 그래프 분석: {label}")
        self.refresh_dashboard()

    def open_dashboard_due_item(self, event=None) -> None:
        if self.dashboard_due_tree is None or self.strategy_tabs is None:
            return
        item_id = self.dashboard_due_tree.identify_row(event.y) if event is not None else ""
        if not item_id:
            selection = self.dashboard_due_tree.selection()
            item_id = selection[0] if selection else ""
        if not item_id:
            return
        values = self.dashboard_due_tree.item(item_id, "values")
        if len(values) < 2:
            return
        strategy = str(values[0])
        label = str(values[1])
        if strategy == "VR" and self.vr_tab is not None:
            name = self.profile_display_to_name.get(label, label)
            self.dashboard_selected_vr_name = name
            self.set_profile_selection(name)
            self.strategy_tabs.select(self.vr_tab)
            self.load_profile_to_form()
            self.set_status(f"VR 미작성 이동: {label}")
        elif strategy == "무매" and self.infinite_tab is not None:
            name = self.infinite_display_to_name.get(label, label)
            self.dashboard_selected_infinite_name = name
            self.set_infinite_profile_selection(name)
            self.strategy_tabs.select(self.infinite_tab)
            self.load_infinite_to_form()
            self.set_status(f"무한매수 미작성 이동: {label}")

    def selected_vr_snapshots(self) -> list[dict]:
        if not self.dashboard_selected_vr_name:
            return []
        return cycle_snapshots(self.con, self.dashboard_selected_vr_name)

    def selected_infinite_rows(self) -> list[dict]:
        if not self.dashboard_selected_infinite_name:
            return []
        return infinite_rows(self.con, self.dashboard_selected_infinite_name)

    def selected_infinite_setting_for_dashboard(self) -> InfiniteSetting | None:
        if not self.dashboard_selected_infinite_name:
            return None
        try:
            return load_infinite_setting(self.con, self.dashboard_selected_infinite_name)
        except Exception:
            return None

    def vr_display_label(self, name: str) -> str:
        for label, profile_name in self.profile_display_to_name.items():
            if profile_name == name:
                return label
        return name or "VR"

    def infinite_display_label(self, name: str) -> str:
        for label, setting_name in self.infinite_display_to_name.items():
            if setting_name == name:
                return label
        return name or "무한매수법"

    @staticmethod
    def clear_tree(tree: ttk.Treeview) -> None:
        for item in tree.get_children():
            tree.delete(item)

    def reload_profiles(self) -> None:
        ensure_default_profile(self.profiles_dir)
        selected_name = self.selected_profile_name()
        profiles = self.visible_vr_profiles()
        self.profile_display_to_name = {
            self.vr_profile_label(profile): profile.name for profile in profiles
        }
        self.profile_combo["values"] = list(self.profile_display_to_name)
        names = [profile.name for profile in profiles]
        if selected_name not in names:
            selected_name = names[0] if names else DEFAULT_PROFILE_NAME
        self.set_profile_selection(selected_name)
        self.load_profile_to_form()
        if not self._startup_loading:
            self.refresh_due_badges()
            self.refresh_dashboard()

    def reload_infinite_profiles(self) -> None:
        ensure_infinite_profile(self.con, INFINITE_DEFAULT_SETTING)
        selected_name = self.selected_infinite_profile_name()
        settings = self.visible_infinite_profiles()
        self.infinite_display_to_name = {
            self.infinite_profile_label(setting): setting.name for setting in settings
        }
        self.infinite_profile_combo["values"] = list(self.infinite_display_to_name)
        names = [setting.name for setting in settings]
        if selected_name not in names:
            selected_name = names[0] if names else INFINITE_DEFAULT_SETTING
        self.set_infinite_profile_selection(selected_name)
        self.load_infinite_to_form()
        if not self._startup_loading:
            self.refresh_due_badges()
            self.refresh_dashboard()

    def visible_vr_profiles(self) -> list[Profile]:
        profiles = list_profiles(self.profiles_dir)
        visible = [profile for profile in profiles if profile.name != DEFAULT_PROFILE_NAME]
        return sorted(visible or profiles, key=lambda profile: (profile.profile_no, profile.name))

    def visible_infinite_profiles(self) -> list[InfiniteSetting]:
        settings = [
            load_infinite_setting(self.con, name)
            for name in list_infinite_profile_names(self.con)
        ]
        visible = [setting for setting in settings if setting.name != INFINITE_DEFAULT_SETTING]
        return sorted(visible or settings, key=lambda setting: (setting.profile_no, setting.name))

    @staticmethod
    def vr_profile_label(profile: Profile) -> str:
        return (
            f"#{profile.profile_no} {profile.name}"
            if profile.name != DEFAULT_PROFILE_NAME and profile.profile_no > 0
            else profile.name
        )

    @staticmethod
    def infinite_profile_label(setting: InfiniteSetting) -> str:
        return (
            f"#{setting.profile_no} {setting.name}"
            if setting.name != INFINITE_DEFAULT_SETTING and setting.profile_no > 0
            else setting.name
        )

    def selected_profile_name(self) -> str:
        value = self.profile_var.get()
        return self.profile_display_to_name.get(value, value or DEFAULT_PROFILE_NAME)

    def selected_infinite_profile_name(self) -> str:
        value = self.infinite_profile_var.get()
        return self.infinite_display_to_name.get(value, value or INFINITE_DEFAULT_SETTING)

    def set_profile_selection(self, name: str) -> None:
        for label, profile_name in self.profile_display_to_name.items():
            if profile_name == name:
                self.profile_var.set(label)
                return
        self.profile_var.set(name)

    def set_infinite_profile_selection(self, name: str) -> None:
        for label, setting_name in self.infinite_display_to_name.items():
            if setting_name == name:
                self.infinite_profile_var.set(label)
                return
        self.infinite_profile_var.set(name)

    def update_vr_pause_button(self, profile: Profile | None = None) -> None:
        if self.pause_vr_button is None:
            return
        profile = profile or self.current_profile()
        text = "산출 재개" if profile.calculation_paused else "산출 중단"
        self.pause_vr_button.configure(text=text)

    def update_infinite_pause_button(self, setting: InfiniteSetting | None = None) -> None:
        if self.pause_infinite_button is None:
            return
        setting = setting or load_infinite_setting(self.con, self.selected_infinite_profile_name())
        text = "산출 재개" if setting.calculation_paused else "산출 중단"
        self.pause_infinite_button.configure(text=text)

    def toggle_vr_calculation_paused(self) -> None:
        try:
            profile = self.current_profile()
            if profile.name == DEFAULT_PROFILE_NAME:
                self.set_status("default 프로필은 산출 중단 대상에서 제외합니다.")
                return
            updated = update_profile(
                profile,
                calculation_paused=not profile.calculation_paused,
            )
            save_profile(updated, self.profiles_dir)
            self.update_vr_pause_button(updated)
            self.refresh_cycle_status()
            self.refresh_due_badges()
            self.refresh_dashboard()
            self.set_status(
                f"VR 산출 {'중단' if updated.calculation_paused else '재개'}: {updated.name}"
            )
        except Exception as exc:
            self.show_error(exc)

    def toggle_infinite_calculation_paused(self) -> None:
        try:
            setting = load_infinite_setting(self.con, self.selected_infinite_profile_name())
            if setting.name == INFINITE_DEFAULT_SETTING:
                self.set_status("default 무한매수 프로필은 산출 중단 대상에서 제외합니다.")
                return
            updated = InfiniteSetting(
                **{**setting.__dict__, "calculation_paused": not setting.calculation_paused}
            )
            save_infinite_setting(self.con, updated)
            self.update_infinite_pause_button(updated)
            self.refresh_due_badges()
            self.refresh_dashboard()
            self.set_status(
                f"무한매수 산출 {'중단' if updated.calculation_paused else '재개'}: {updated.name}"
            )
        except Exception as exc:
            self.show_error(exc)

    def goto_current_vr_row(self) -> None:
        if self.raw_tree is None:
            return
        profile = self.current_profile()
        self.refresh_cycle_rows()
        target_cycle = next_input_cycle(self.con, profile.name)
        basis_id = f"basis-{target_cycle}"
        cycle_id = f"cycle-{target_cycle}"
        fallback_id = ""
        children = self.raw_tree.get_children()
        if children:
            fallback_id = str(children[-1])
        target = basis_id if self.raw_tree.exists(basis_id) else cycle_id
        if not self.raw_tree.exists(target):
            latest = latest_cycle_snapshot(self.con, profile.name)
            if latest is not None:
                target = f"cycle-{int(latest['cycle_no'])}"
        if not self.raw_tree.exists(target):
            target = fallback_id
        if target:
            self.raw_tree.selection_set(target)
            self.raw_tree.focus(target)
            self.raw_tree.see(target)
            self.on_cycle_row_selected()
            self.set_status(f"현재조회: {profile.name}")

    def goto_current_infinite_row(self) -> None:
        if self.infinite_rows_tree is None:
            return
        setting = load_infinite_setting(self.con, self.selected_infinite_profile_name())
        self.refresh_infinite_rows(setting)
        target = ""
        yesterday = previous_us_trading_day(date.today() - timedelta(days=1))
        for item_id in self.infinite_rows_tree.get_children():
            values = self.infinite_rows_tree.item(item_id, "values")
            if len(values) < 5:
                continue
            trade_date = date.fromisoformat(str(values[1]))
            avg_price = str(values[4]).strip()
            if trade_date <= yesterday and not avg_price:
                target = str(item_id)
                break
        if not target:
            children = self.infinite_rows_tree.get_children()
            target = str(children[-1]) if children else ""
        if target:
            self.infinite_rows_tree.selection_set(target)
            self.infinite_rows_tree.focus(target)
            self.infinite_rows_tree.see(target)
            self.set_status(f"현재조회: {setting.name}")

    def refresh_due_badges(self) -> None:
        if self.strategy_tabs is None or self.vr_tab is None or self.infinite_tab is None:
            return
        try:
            vr_count = self.vr_due_profile_count()
            infinite_count = self.infinite_due_profile_count()
            self.strategy_tabs.tab(self.vr_tab, text=self.badge_text("VR", vr_count))
            self.strategy_tabs.tab(
                self.infinite_tab, text=self.badge_text("무한매수법", infinite_count)
            )
        except Exception:
            pass

    def vr_due_profile_count(self) -> int:
        count = 0
        for profile in list_profiles(self.profiles_dir):
            if profile.name == DEFAULT_PROFILE_NAME:
                continue
            if profile.calculation_paused:
                continue
            status = profile_cycle_status(self.con, profile)
            if int(status["missing_count"]) > 0:
                count += 1
        return count

    def infinite_due_profile_count(self) -> int:
        yesterday = previous_us_trading_day(date.today() - timedelta(days=1))
        count = 0
        for name in list_infinite_profile_names(self.con):
            if name == INFINITE_DEFAULT_SETTING:
                continue
            setting = load_infinite_setting(self.con, name)
            if setting.calculation_paused:
                continue
            if yesterday < setting.start_date:
                continue
            generate_infinite_rows(
                self.con,
                setting,
                through=max(
                    yesterday,
                    self.infinite_rebuild_through_date(setting.name, setting.start_date),
                ),
            )
            row = self.con.execute(
                """
                SELECT 1
                FROM infinite_rows
                WHERE setting_name = ?
                  AND trade_date <= ?
                  AND avg_price IS NULL
                LIMIT 1
                """,
                [name, yesterday],
            ).fetchone()
            if row is not None:
                count += 1
        return count

    @staticmethod
    def badge_text(title: str, count: int) -> str:
        return f"{title} ({count})" if count > 0 else title

    def load_profile_to_form(self) -> None:
        profile = self.current_profile()
        values = {
            "start_date": profile.start_date,
            "start_week_no": profile.start_week_no,
            "symbol": profile.symbol,
            "account_number": profile.account_number,
            "min_ratio": profile.min_ratio,
            "max_ratio": profile.max_ratio,
            "initial_v": profile.initial_v,
            "initial_pool": profile.initial_pool,
            "initial_principal": profile.initial_principal,
            "initial_shares": profile.initial_shares,
        }
        for key, value in values.items():
            self.profile_fields[key].set("" if value is None else str(value))
        self.load_kiwoom_api_credentials("vr")
        self.update_vr_pause_button(profile)
        self.view_fields["quantity_step"].set(str(profile.quantity_step))
        self.sync_next_input_cycle()
        latest = latest_cycle_snapshot(self.con, profile.name)
        self.view_fields["cycle_no"].set(
            str(self.week_no_for_cycle(profile, int(latest["cycle_no"]) + 1))
            if latest
            else ""
        )
        self.apply_cycle_dates()
        self.refresh_cycle_rows()
        self.refresh_cycle_status()
        self.refresh_snapshot()

    def create_profile_dialog(self) -> None:
        name = simpledialog.askstring("새 프로필", "프로필 이름")
        if not name:
            return
        try:
            create_profile(name, self.profiles_dir)
            self.profile_var.set(name)
            self.reload_profiles()
        except Exception as exc:
            self.show_error(exc)

    def rename_profile_dialog(self) -> None:
        old_name = self.selected_profile_name()
        if old_name == DEFAULT_PROFILE_NAME:
            self.set_status("default 프로필은 내부 기본값이라 이름을 바꾸지 않습니다.")
            return
        new_name = simpledialog.askstring("이름 변경", "새 이름", initialvalue=old_name)
        if not new_name or new_name == old_name:
            return
        try:
            rename_profile(old_name, new_name, self.profiles_dir)
            rename_profile_snapshots(self.con, old_name, new_name)
            rename_kiwoom_credentials("vr", old_name, new_name)
            rename_profile_token("vr", old_name, new_name)
            self.profile_var.set(new_name)
            self.reload_profiles()
        except Exception as exc:
            self.show_error(exc)

    def delete_profile_dialog(self) -> None:
        name = self.selected_profile_name()
        if not name:
            return
        if name == DEFAULT_PROFILE_NAME:
            self.set_status("default 프로필은 내부 기본값이라 삭제하지 않습니다.")
            return
        confirmed = messagebox.askyesno(
            "프로필 삭제",
            f"'{name}' 프로필과 계산기록을 모두 삭제할까요?",
        )
        if not confirmed:
            return
        try:
            delete_profile_records(self.con, name)
            delete_profile(name, self.profiles_dir)
            delete_kiwoom_credentials("vr", name)
            delete_profile_token("vr", name)
            ensure_default_profile(self.profiles_dir)
            self.profile_var.set(DEFAULT_PROFILE_NAME)
            self.reload_profiles()
            self.set_status(f"프로필 삭제 완료: {name}")
        except Exception as exc:
            self.show_error(exc)

    def create_infinite_profile_dialog(self) -> None:
        name = simpledialog.askstring("새 무한매수 프로필", "프로필 이름")
        if not name:
            return
        try:
            create_infinite_profile(self.con, name.strip())
            self.infinite_profile_var.set(name.strip())
            self.reload_infinite_profiles()
        except Exception as exc:
            self.show_error(exc)

    def rename_infinite_profile_dialog(self) -> None:
        old_name = self.selected_infinite_profile_name()
        if old_name == INFINITE_DEFAULT_SETTING:
            self.set_status("default 무한매수 프로필은 내부 기본값이라 이름을 바꾸지 않습니다.")
            return
        new_name = simpledialog.askstring("무한매수 이름 변경", "새 이름", initialvalue=old_name)
        if not new_name or new_name == old_name:
            return
        try:
            rename_infinite_profile_records(self.con, old_name, new_name.strip())
            rename_kiwoom_credentials("infinite", old_name, new_name.strip())
            rename_profile_token("infinite", old_name, new_name.strip())
            self.infinite_profile_var.set(new_name.strip())
            self.reload_infinite_profiles()
        except Exception as exc:
            self.show_error(exc)

    def delete_infinite_profile_dialog(self) -> None:
        name = self.selected_infinite_profile_name()
        if not name:
            return
        if name == INFINITE_DEFAULT_SETTING:
            self.set_status("default 무한매수 프로필은 내부 기본값이라 삭제하지 않습니다.")
            return
        confirmed = messagebox.askyesno(
            "무한매수 프로필 삭제",
            f"'{name}' 무한매수 프로필과 일별 기록을 모두 삭제할까요?",
        )
        if not confirmed:
            return
        try:
            delete_infinite_profile_records(self.con, name)
            delete_kiwoom_credentials("infinite", name)
            delete_profile_token("infinite", name)
            ensure_infinite_profile(self.con, INFINITE_DEFAULT_SETTING)
            self.infinite_profile_var.set(INFINITE_DEFAULT_SETTING)
            self.reload_infinite_profiles()
            self.set_status(f"무한매수 프로필 삭제 완료: {name}")
        except Exception as exc:
            self.show_error(exc)

    def save_profile_settings(self) -> None:
        try:
            profile = self.current_profile()
            updated = update_profile(
                profile,
                start_date=self.profile_fields["start_date"].get().strip(),
                start_week_no=self.int_field(self.profile_fields, "start_week_no"),
                symbol=self.profile_fields["symbol"].get().strip(),
                account_number=self.profile_fields["account_number"].get().strip(),
                min_ratio=self.float_field(self.profile_fields, "min_ratio"),
                max_ratio=self.float_field(self.profile_fields, "max_ratio"),
                initial_v=self.float_field(self.profile_fields, "initial_v"),
                initial_pool=self.float_field(self.profile_fields, "initial_pool"),
                initial_principal=self.float_field(self.profile_fields, "initial_principal"),
                initial_shares=self.int_field(self.profile_fields, "initial_shares"),
                quantity_step=self.int_field(self.view_fields, "quantity_step"),
            )
            save_profile(updated, self.profiles_dir)
            self.set_status("프로필 저장 완료")
            self.sync_next_input_cycle()
            self.apply_cycle_dates()
            self.refresh_cycle_status()
            self.refresh_due_badges()
            self.refresh_dashboard()
        except Exception as exc:
            self.show_error(exc)

    def set_g_condition_fields(self, config: str) -> None:
        initial, period, step = parse_g_config(config)
        self.cycle_fields["g_config"].set(f"{initial:g},{period},{step:g}")
        self.cycle_fields["g_initial"].set(self.format_input_number(initial))
        self.cycle_fields["g_period"].set(str(period))
        self.cycle_fields["g_step"].set(self.format_input_number(step))

    def set_buy_limit_condition_fields(self, config: str) -> None:
        initial, period, step = parse_buy_limit_config(config)
        normalized = f"{initial * 100:g}%,{period},{step * 100:g}%"
        self.cycle_fields["buy_limit_config"].set(normalized)
        self.cycle_fields["buy_limit_initial"].set(f"{initial * 100:g}%")
        self.cycle_fields["buy_limit_period"].set(str(period))
        self.cycle_fields["buy_limit_step"].set(f"{step * 100:g}%")

    def compose_g_condition(self) -> str:
        config = (
            f"{self.cycle_fields['g_initial'].get().strip()},"
            f"{self.cycle_fields['g_period'].get().strip()},"
            f"{self.cycle_fields['g_step'].get().strip()}"
        )
        self.set_g_condition_fields(config)
        return self.cycle_fields["g_config"].get()

    def compose_buy_limit_condition(self) -> str:
        initial = self.ensure_percent_text(self.cycle_fields["buy_limit_initial"].get())
        step = self.ensure_percent_text(self.cycle_fields["buy_limit_step"].get())
        config = (
            f"{initial},"
            f"{self.cycle_fields['buy_limit_period'].get().strip()},"
            f"{step}"
        )
        self.set_buy_limit_condition_fields(config)
        return self.cycle_fields["buy_limit_config"].get()

    @staticmethod
    def ensure_percent_text(value: str) -> str:
        text = value.strip()
        if not text:
            return "0%"
        return text if text.endswith("%") else f"{text}%"

    def apply_cycle_dates(self) -> None:
        try:
            profile = self.current_profile()
            cycle_no = self.input_cycle_no(profile)
            dates = cycle_dates(date.fromisoformat(profile.start_date), cycle_no)
            next_dates = cycle_dates(date.fromisoformat(profile.start_date), cycle_no + 1)
            self.cycle_fields["result_period"].set(f"{dates.result_start} ~ {dates.result_end}")
            self.cycle_fields["next_period"].set(f"{next_dates.result_start} ~ {next_dates.result_end}")
            self.autofill_close_price(cycle_no, dates.result_start, dates.result_end)
            self.update_cycle_guard()
        except Exception as exc:
            self.show_error(exc)

    def input_cycle_no(self, profile: Profile | None = None) -> int:
        profile = profile or self.current_profile()
        week_no = self.int_field(self.cycle_fields, "cycle_no")
        return cycle_no_from_week(profile, week_no)

    def week_no_for_cycle(self, profile: Profile, cycle_no: int) -> int:
        if cycle_no <= 0:
            return 0
        return int(profile.start_week_no) + (cycle_no - 1) * 2

    def snapshot_g_start_week(self, profile: Profile, snapshot: dict) -> int:
        return int(snapshot.get("g_start_cycle_no") or 2)

    def cycle_label(self, profile: Profile, cycle_no: int) -> str:
        return f"{self.week_no_for_cycle(profile, cycle_no)}주차"

    def autofill_close_price(self, cycle_no: int, start_day: date, end_day: date) -> None:
        if self.editing_saved_cycle:
            return
        if self.cycle_fields["close_price"].get().strip():
            return
        profile = self.current_profile()
        available_date = cycle_input_available_date(date.fromisoformat(profile.start_date), cycle_no)
        if date.today() < available_date:
            return
        expected = next_input_cycle(self.con, self.current_profile().name)
        if cycle_no != expected:
            return
        try:
            close_price = find_close_price(
                self.con,
                profile.symbol,
                end_day,
                start_day,
            )
            self.cycle_fields["close_price"].set(self.format_number(close_price))
        except Exception:
            self.cycle_fields["close_price"].set("")

    def sync_next_input_cycle(self) -> None:
        profile = self.current_profile()
        cycle_no = next_input_cycle(self.con, profile.name)
        self.cycle_fields["cycle_no"].set(str(self.week_no_for_cycle(profile, cycle_no)))
        self.cycle_fields["trade_amount"].set("0")
        self.cycle_fields["dividend"].set("0")
        self.cycle_fields["close_price"].set("")
        self.cycle_fields["contribution_amount"].set(
            self.format_number(latest_contribution_amount(self.con, profile))
        )
        self.set_g_condition_fields(latest_g_config(self.con, profile))
        self.cycle_fields["g_start_cycle_no"].set(
            str(latest_g_start_cycle_no(self.con, profile))
        )
        self.set_buy_limit_condition_fields(latest_buy_limit_config(self.con, profile))
        self.cycle_fields["buy_limit_start_week_no"].set(
            str(latest_buy_limit_start_week_no(self.con, profile))
        )

        self.cycle_fields["shares"].set("")
        self.editing_saved_cycle = False

    def update_cycle_guard(self) -> bool:
        profile = self.current_profile()
        cycle_no = self.input_cycle_no(profile)
        week_no = self.week_no_for_cycle(profile, cycle_no)
        if self.editing_saved_cycle:
            if self.save_cycle_button is not None:
                self.save_cycle_button.configure(text="수정값 재계산 저장", state=tk.NORMAL)
            self.set_status(f"{week_no}주차 저장값 수정 가능")
            return True

        expected = next_input_cycle(self.con, profile.name)
        dates = cycle_dates(date.fromisoformat(profile.start_date), cycle_no)
        available_date = cycle_input_available_date(date.fromisoformat(profile.start_date), cycle_no)

        allowed = cycle_no == expected and date.today() >= available_date
        if self.save_cycle_button is not None:
            self.save_cycle_button.configure(
                text="저장하고 다음 주차 매수/매도점 보기",
                state=tk.NORMAL if allowed else tk.DISABLED,
            )

        if cycle_no != expected:
            self.set_status(
                f"다음 입력 주차는 {self.week_no_for_cycle(profile, expected)}주차입니다."
            )
        elif date.today() < available_date:
            self.set_status(
                f"{week_no}주차는 {dates.result_start}~{dates.result_end} 구간 종료 후 "
                f"{available_date}부터 입력 가능합니다."
            )
        else:
            self.set_status(f"{week_no}주차 입력 가능")
        return allowed

    def save_cycle_and_show_orders(self) -> None:
        try:
            profile = self.current_profile()
            cycle_no = self.input_cycle_no(profile)
            week_no = self.week_no_for_cycle(profile, cycle_no)

            close_text = self.cycle_fields["close_price"].get().strip()
            cycle_input = CycleInput(
                cycle_no=cycle_no,
                close_price=float(close_text.replace(",", "")) if close_text else None,
                trade_amount=self.float_field(self.cycle_fields, "trade_amount"),
                shares=self.int_field(self.cycle_fields, "shares"),
                dividend=self.float_field(self.cycle_fields, "dividend"),
                contribution_amount=self.float_field(self.cycle_fields, "contribution_amount"),
                g_config=self.compose_g_condition(),
                g_start_cycle_no=self.int_field(self.cycle_fields, "g_start_cycle_no"),
                buy_limit_config=self.compose_buy_limit_condition(),
                buy_limit_start_week_no=self.int_field(
                    self.cycle_fields, "buy_limit_start_week_no"
                ),
            )

            if self.editing_saved_cycle:
                snapshot_id = recalculate_cycle_results_from(
                    self.con,
                    profile=profile,
                    cycle_input=cycle_input,
                )
                self.set_status(f"{week_no}주차 재계산 완료 #{snapshot_id}")
            else:
                expected = next_input_cycle(self.con, profile.name)
                if cycle_no != expected:
                    raise ValueError(
                        f"다음 입력 주차는 {self.week_no_for_cycle(profile, expected)}주차입니다."
                    )
                if not self.update_cycle_guard():
                    raise ValueError("아직 이 주차 결과를 입력할 수 없습니다.")
                snapshot_id = save_cycle_result(
                    self.con,
                    profile=profile,
                    cycle_input=cycle_input,
                )
                self.set_status(f"{week_no}주차 저장 완료 #{snapshot_id}")

            self.sync_next_input_cycle()
            self.view_fields["cycle_no"].set(str(self.week_no_for_cycle(profile, cycle_no + 1)))
            self.apply_cycle_dates()
            self.refresh_cycle_rows()
            self.refresh_cycle_status()
            self.refresh_snapshot()
            self.refresh_due_badges()
            self.refresh_dashboard()
            self.auto_send_vr_telegram_order(profile)
        except Exception as exc:
            self.show_error(exc)

    def refresh_cycle_status(self) -> None:
        try:
            profile = self.current_profile()
            if profile.calculation_paused:
                self.cycle_status_var.set("산출 중단")
                return
            status = profile_cycle_status(self.con, profile)
            missing = status["missing_cycles"]
            missing_text = ", ".join(
                str(self.week_no_for_cycle(profile, item)) for item in missing[:8]
            )
            if len(missing) > 8:
                missing_text += "..."
            if not missing_text:
                missing_text = "없음"
            last_done = status["last_done_cycle"]
            last_done_text = (
                "-" if last_done is None else str(self.week_no_for_cycle(profile, last_done))
            )
            last_available = status["last_available_input_cycle"]
            last_available_text = (
                "-" if last_available < 0 else str(self.week_no_for_cycle(profile, last_available))
            )
            self.cycle_status_var.set(
                f"현재 {self.week_no_for_cycle(profile, status['current_cycle'])}주차 진행중 | "
                f"입력가능 마지막 {last_available_text}주차 | "
                f"완료 마지막 {last_done_text}주차 | "
                f"미입력 {status['missing_count']}개: {missing_text}"
            )
        except Exception:
            self.cycle_status_var.set("")

    def auto_update_prices(self, startup: bool = False) -> None:
        if self._closing:
            return
        try:
            self.set_status("가격 업데이트 중...")
            if startup:
                self.update_startup_progress(99, "가격 데이터 업데이트 중...")
            else:
                self.update_idletasks()
            summary = update_market_prices(self.con)
            try:
                self.con.execute("CHECKPOINT")
            except Exception:
                pass
            parts = []
            for symbol, item in summary.items():
                latest = item.get("latest")
                parts.append(f"{symbol} {item['fetched']}건 최신 {latest}")
            self.set_status("가격 업데이트 완료: " + " | ".join(parts))
            if not self.editing_saved_cycle:
                self.apply_cycle_dates()
            self.refresh_due_badges()
            self.refresh_dashboard()
        except Exception as exc:
            self.set_status(f"가격 업데이트 실패: {exc}")
            if startup:
                self.update_startup_progress(99, f"가격 업데이트 실패: {exc}")

    def refresh_cycle_rows(self) -> None:
        if self.raw_tree is None:
            return
        for item in self.raw_tree.get_children():
            self.raw_tree.delete(item)

        profile = self.current_profile()
        selected_week = self.view_fields["cycle_no"].get().strip()
        for snapshot in display_cycle_rows(self.con, profile):
            cycle_no = int(snapshot["cycle_no"])
            week_no = int(snapshot["week_no"])
            is_order_basis = bool(snapshot.get("is_order_basis"))
            item_id = f"basis-{cycle_no}" if is_order_basis else f"cycle-{cycle_no}"
            self.raw_tree.insert(
                "",
                tk.END,
                iid=item_id,
                values=(
                    cycle_no,
                    snapshot["start_date"],
                    snapshot["end_date"],
                    "" if is_order_basis else self.format_number(snapshot["close_price"]),
                    self.format_g(snapshot),
                    snapshot.get("g_config") or "",
                    self.snapshot_g_start_week(profile, snapshot),
                    week_no,
                    snapshot.get("status", "done"),
                    "" if is_order_basis else self.format_money(snapshot["valuation"]),
                    self.format_money(snapshot["v"]),
                    self.format_money(snapshot["min_value"]),
                    self.format_money(snapshot["max_value"]),
                    "" if is_order_basis else self.format_money(snapshot["trade_amount"]),
                    self.format_money(snapshot.get("contribution")),
                    "" if is_order_basis else self.format_money(snapshot.get("dividend")),
                    self.format_money(snapshot["prior_pool"]),
                    self.format_money(snapshot["pool"]),
                    self.format_money(snapshot["principal"]),
                    self.format_money(snapshot["account_total"]),
                    self.format_percent(snapshot["return_rate"]),
                    self.format_money(snapshot["profit"]),
                    "" if is_order_basis else snapshot["shares"],
                    self.format_money(snapshot["buy_principal"]),
                    self.format_number(snapshot["avg_cost"]),
                    self.format_percent(snapshot["buy_limit_ratio"]),
                ),
            )
            if selected_week and selected_week == str(week_no):
                self.raw_tree.selection_set(item_id)
                self.raw_tree.see(item_id)

    def on_cycle_row_selected(self, _event=None) -> None:
        if self.raw_tree is None:
            return
        selected = self.raw_tree.selection()
        if not selected:
            return
        item_id = selected[0]
        item_id_text = str(item_id)
        if item_id_text.startswith("cycle-"):
            cycle_no = int(item_id_text.split("-", 1)[1])
            snapshot = snapshot_for_cycle(self.con, self.current_profile().name, cycle_no)
            self.editing_saved_cycle = True
            if snapshot is not None:
                self.load_cycle_input_from_snapshot(snapshot, saved=True)
            self.view_fields["cycle_no"].set(
                str(self.week_no_for_cycle(self.current_profile(), cycle_no))
            )
        elif item_id_text.startswith("basis-"):
            cycle_no = int(item_id_text.split("-", 1)[1])
            snapshot = order_basis_for_next_cycle(self.con, self.current_profile())
            self.editing_saved_cycle = False
            if snapshot is not None:
                self.load_cycle_input_from_snapshot(snapshot, saved=False)
            self.view_fields["cycle_no"].set(
                str(self.week_no_for_cycle(self.current_profile(), cycle_no))
            )
        else:
            return
        self.refresh_snapshot()

    def load_cycle_input_from_snapshot(self, snapshot: dict, *, saved: bool) -> None:
        cycle_no = int(snapshot["cycle_no"])
        self.cycle_fields["cycle_no"].set(
            str(self.week_no_for_cycle(self.current_profile(), cycle_no))
        )
        dates = cycle_dates(date.fromisoformat(self.current_profile().start_date), cycle_no)
        next_dates = cycle_dates(date.fromisoformat(self.current_profile().start_date), cycle_no + 1)
        self.cycle_fields["result_period"].set(f"{dates.result_start} ~ {dates.result_end}")
        self.cycle_fields["next_period"].set(f"{next_dates.result_start} ~ {next_dates.result_end}")
        if saved:
            close_price = self.format_number(snapshot["close_price"])
        else:
            close_price = self.close_price_from_price_table(cycle_no, dates.result_start, dates.result_end)
        self.cycle_fields["close_price"].set(close_price)
        self.cycle_fields["trade_amount"].set(self.format_number(snapshot["trade_amount"]) if saved else "0")
        self.cycle_fields["shares"].set(str(snapshot["shares"]) if saved else "")
        self.cycle_fields["contribution_amount"].set(
            self.format_number(snapshot.get("contribution"))
        )
        self.cycle_fields["dividend"].set(self.format_number(snapshot.get("dividend")) if saved else "0")
        self.set_g_condition_fields(
            snapshot.get("g_config") or latest_g_config(self.con, self.current_profile())
        )
        self.cycle_fields["g_start_cycle_no"].set(
            str(self.snapshot_g_start_week(self.current_profile(), snapshot))
        )
        self.set_buy_limit_condition_fields(
            snapshot.get("buy_limit_config")
            or latest_buy_limit_config(self.con, self.current_profile())
        )
        self.cycle_fields["buy_limit_start_week_no"].set(
            str(
                snapshot.get("buy_limit_start_week_no")
                or latest_buy_limit_start_week_no(self.con, self.current_profile())
            )
        )
        self.update_cycle_guard()

    def close_price_from_price_table(self, cycle_no: int, start_day: date, end_day: date) -> str:
        profile = self.current_profile()
        available_date = cycle_input_available_date(date.fromisoformat(profile.start_date), cycle_no)
        if date.today() < available_date:
            return ""
        try:
            close_price = find_close_price(self.con, profile.symbol, end_day, start_day)
        except Exception:
            return ""
        return self.format_number(close_price)

    def selected_snapshot(self) -> dict | None:
        profile = self.current_profile()
        week_text = self.view_fields["cycle_no"].get().strip()
        if week_text:
            cycle_no = cycle_no_from_week(profile, int(week_text))
            snapshot = snapshot_for_cycle(self.con, profile.name, cycle_no)
            if snapshot is not None:
                return snapshot
            basis = order_basis_for_next_cycle(self.con, profile)
            if basis is not None and int(basis["cycle_no"]) == cycle_no:
                return basis
            return None
        return latest_cycle_snapshot(self.con, profile.name)

    def refresh_snapshot(self) -> None:
        if self.vr_order_execute_button is not None:
            self.vr_order_execute_button.configure(state=tk.DISABLED)
        self.vr_order_api_status_var.set("")
        for tree in (self.summary_tree, self.order_tree):
            for item in tree.get_children():
                tree.delete(item)

        snapshot = self.selected_snapshot()
        if snapshot is None:
            self.order_info_var.set("저장된 VR 결과가 없습니다.")
            return

        self.insert_calculation_basis(snapshot)
        if int(snapshot["cycle_no"]) == 0 and not snapshot.get("is_order_basis"):
            self.order_info_var.set("0주차는 기준 입력값이라 매수/매도점이 없습니다. 다음 주차 진행중 행을 선택하세요.")
            return

        profile = self.current_profile()
        quantity_step = self.int_field(self.view_fields, "quantity_step")
        if quantity_step <= 0:
            self.order_info_var.set("갯수 간격은 1 이상이어야 합니다.")
            return
        profile = update_profile(profile, quantity_step=quantity_step)
        save_profile(profile, self.profiles_dir)

        rows = order_level_values(profile, snapshot, quantity_step=quantity_step)
        buy_rows = [row for row in rows if row["side"] == "BUY"]
        sell_rows = [row for row in rows if row["side"] == "SELL"]
        buy_limit = self.optional_int(self.view_fields["buy_rows"].get())
        sell_limit = self.optional_int(self.view_fields["sell_rows"].get())
        if buy_limit is not None:
            buy_rows = buy_rows[:buy_limit]
        if sell_limit is not None:
            sell_rows = sell_rows[:sell_limit]

        self.order_info_var.set(
            self.order_info_text(snapshot, quantity_step)
        )
        if self.vr_order_execute_button is not None:
            state = tk.NORMAL if self.vr_order_execution_available(profile, snapshot) else tk.DISABLED
            self.vr_order_execute_button.configure(state=state)
        self.order_tree.insert(
            "",
            tk.END,
            values=(
                f"{snapshot['min_value']:,.2f}",
                snapshot["shares"],
                "",
                f"{snapshot['pool']:,.2f}",
                f"{snapshot['max_value']:,.2f}",
                snapshot["shares"],
                "",
                f"{snapshot['pool']:,.2f}",
            ),
        )
        for index in range(max(len(buy_rows), len(sell_rows))):
            buy = buy_rows[index] if index < len(buy_rows) else None
            sell = sell_rows[index] if index < len(sell_rows) else None
            self.order_tree.insert(
                "",
                tk.END,
                values=(
                    "",
                    buy["after_shares"] if buy else "",
                    f"{buy['price']:.2f}" if buy else "",
                    f"{buy['pool_after']:,.2f}" if buy else "",
                    "",
                    sell["after_shares"] if sell else "",
                    f"{sell['price']:.2f}" if sell else "",
                    f"{sell['pool_after']:,.2f}" if sell else "",
                ),
            )

    def vr_order_execution_available(self, profile: Profile, snapshot: dict) -> bool:
        try:
            if not snapshot.get("is_order_basis"):
                return False
            today = date.today()
            start_day, end_day = self.snapshot_date_range(snapshot)
            return start_day <= today <= end_day
        except Exception:
            return False

    @staticmethod
    def snapshot_date_range(snapshot: dict) -> tuple[date, date]:
        return (
            date.fromisoformat(str(snapshot["start_date"])),
            date.fromisoformat(str(snapshot["end_date"])),
        )

    def recalculate_current_view(self) -> None:
        try:
            snapshot = self.selected_snapshot()
            if snapshot is None:
                self.refresh_snapshot()
                return
            if snapshot.get("is_order_basis"):
                profile = self.current_profile()
                source_cycle = int(snapshot["source_cycle_no"])
                source = snapshot_for_cycle(self.con, profile.name, source_cycle)
                if source is None:
                    raise ValueError(
                        f"{self.week_no_for_cycle(profile, source_cycle)}주차 기준값을 찾을 수 없습니다."
                    )
                snapshot_id = recalculate_cycle_results_from(
                    self.con,
                    profile=profile,
                    cycle_input=self.cycle_input_from_snapshot(source),
                )
                self.view_fields["cycle_no"].set(
                    str(self.week_no_for_cycle(profile, source_cycle + 1))
                )
                self.set_status(
                    f"{self.week_no_for_cycle(profile, source_cycle)}주차 기준값 재계산 완료 #{snapshot_id}"
                )
                self.refresh_cycle_rows()
                self.refresh_cycle_status()
                self.refresh_snapshot()
                return
            if self.editing_saved_cycle:
                self.save_cycle_and_show_orders()
                return
            self.refresh_snapshot()
        except Exception as exc:
            self.show_error(exc)

    def cycle_input_from_snapshot(self, snapshot: dict) -> CycleInput:
        return CycleInput(
            cycle_no=int(snapshot["cycle_no"]),
            close_price=float(snapshot["close_price"]),
            trade_amount=float(snapshot["trade_amount"]),
            shares=int(snapshot["shares"]),
            dividend=float(snapshot.get("dividend") or 0),
            contribution_amount=float(snapshot.get("contribution") or 0),
            g_config=str(snapshot.get("g_config") or ""),
            g_start_cycle_no=self.snapshot_g_start_week(self.current_profile(), snapshot),
            buy_limit_config=str(snapshot.get("buy_limit_config") or ""),
            buy_limit_start_week_no=int(snapshot.get("buy_limit_start_week_no") or 2),
        )


    def insert_calculation_basis(self, snapshot: dict) -> None:
        profile = self.current_profile()
        cycle_no = int(snapshot["cycle_no"])
        if snapshot.get("is_order_basis"):
            previous = snapshot_for_cycle(self.con, profile.name, int(snapshot["source_cycle_no"]))
        else:
            previous = snapshot_for_cycle(self.con, profile.name, cycle_no - 1) if cycle_no > 0 else None
        contribution = float(snapshot.get("contribution") or 0)
        dividend = float(snapshot.get("dividend") or 0)
        trade_amount = None if snapshot.get("trade_amount") is None else float(snapshot["trade_amount"])
        g = float(snapshot["g"] or 0)

        if previous is None:
            base_v = float(profile.initial_v)
            base_pool = float(profile.initial_pool)
            base_principal = float(profile.initial_principal)
            previous_valuation = float(snapshot["valuation"])
            v_formula = f"초기 V {self.format_money(base_v)} + 적립/인출금액 {self.format_money(contribution)}"
        else:
            base_v = float(previous["v"])
            base_pool = float(previous["pool"])
            base_principal = float(previous["principal"])
            previous_valuation = float(previous["valuation"])
            v_base = round(
                base_v + base_pool / g + (previous_valuation - base_v) / (2 * (g ** 0.5)),
                2,
            )
            v_formula = (
                f"ROUND({self.format_money(base_v)} + {self.format_money(base_pool)} / {self.format_number(g)} "
                f"+ ({self.format_money(previous_valuation)} - {self.format_money(base_v)}) "
                f"/ (2 * SQRT({self.format_number(g)})), 2) "
                f"+ {self.format_money(contribution)} = {self.format_money(v_base + contribution)}"
            )

        rows = [
            ("기준", self.basis_text(snapshot)),
            ("결과 구간", f"{snapshot['start_date']} ~ {snapshot['end_date']}"),
            ("종가 / 개수 / 평가금 E", f"{self.format_number(snapshot['close_price'])} / {snapshot['shares']} / {self.format_money(snapshot['valuation'])}"),
            ("G 조건", snapshot.get("g_config") or ""),
            ("G 시작주차", self.snapshot_g_start_week(profile, snapshot)),
            ("G / 주차", f"{self.format_g(snapshot)} / {snapshot['week_no']}"),
            ("매수한도 조건", snapshot.get("buy_limit_config") or ""),
            ("매수한도 시작주차", snapshot.get("buy_limit_start_week_no") or 2),
            ("직전 V", self.format_money(base_v)),
            ("직전 마지막 Pool", self.format_money(base_pool)),
            ("직전 평가금 E", self.format_money(previous_valuation)),
            ("V 산식", v_formula),
            ("계산된 V", self.format_money(snapshot["v"])),
            ("최소 / 최대", f"{self.format_money(snapshot['min_value'])} / {self.format_money(snapshot['max_value'])}"),
            ("시작 Pool", f"{self.format_money(base_pool)} + 적립/인출금액 {self.format_money(contribution)} = {self.format_money(snapshot['prior_pool'])}"),
            ("마지막 Pool", self.pool_text(snapshot, trade_amount)),
            ("투자원금", f"{self.format_money(base_principal)} + 적립/인출금액 {self.format_money(contribution)} = {self.format_money(snapshot['principal'])}"),
            ("계좌총액 / 수익률 / 수익금", f"{self.format_money(snapshot['account_total'])} / {self.format_percent(snapshot['return_rate'])} / {self.format_money(snapshot['profit'])}"),
            ("매수원금 / 평단 / 매수한도", f"{self.format_money(snapshot['buy_principal'])} / {self.format_number(snapshot['avg_cost'])} / {self.format_percent(snapshot['buy_limit_ratio'])}"),
        ]
        for field, value in rows:
            self.summary_tree.insert("", tk.END, values=(field, value))

    def order_info_text(self, snapshot: dict, quantity_step: int) -> str:
        cycle_no = int(snapshot["cycle_no"])
        if snapshot.get("is_order_basis"):
            return f"{self.week_no_for_cycle(self.current_profile(), cycle_no)}주차 주문생성 기준 | 갯수간격 {quantity_step}"
        return f"{self.week_no_for_cycle(self.current_profile(), cycle_no)}주차 완료 행 기준 | 갯수간격 {quantity_step}"

    def basis_text(self, snapshot: dict) -> str:
        cycle_no = int(snapshot["cycle_no"])
        if snapshot.get("is_order_basis"):
            source_week = self.week_no_for_cycle(
                self.current_profile(), int(snapshot["source_cycle_no"])
            )
            return (
                f"{source_week}주차 결과로 계산한 "
                f"{self.week_no_for_cycle(self.current_profile(), cycle_no)}주차 매수/매도점"
            )
        return f"{self.week_no_for_cycle(self.current_profile(), cycle_no)}주차 완료 저장값"

    def pool_text(self, snapshot: dict, trade_amount: float | None) -> str:
        if trade_amount is None:
            return f"{self.format_money(snapshot['pool'])} (주문생성 기준 Pool)"
        dividend = float(snapshot.get("dividend") or 0)
        return (
            f"{self.format_money(snapshot['prior_pool'])} + 거래액 {self.format_money(trade_amount)} "
            f"+ 세후배당 {self.format_money(dividend)} = {self.format_money(snapshot['pool'])}"
        )

    def current_profile(self) -> Profile:
        return load_profile(self.selected_profile_name(), self.profiles_dir)

    def set_status(self, message: str) -> None:
        self.status_var.set(message)

    def show_error(self, exc: Exception) -> None:
        self.status_var.set("오류")
        messagebox.showerror("VR Study", str(exc))

    @staticmethod
    def float_field(fields: dict[str, tk.StringVar], key: str) -> float:
        value = fields[key].get().strip().replace(",", "")
        return float(value) if value else 0.0

    @staticmethod
    def int_field(fields: dict[str, tk.StringVar], key: str) -> int:
        value = fields[key].get().strip().replace(",", "")
        return int(value) if value else 0

    @staticmethod
    def percent_field(fields: dict[str, tk.StringVar], key: str) -> float:
        value = fields[key].get().strip().replace(",", "")
        if not value:
            return 0.0
        if value.endswith("%"):
            return float(value[:-1].strip()) / 100
        number = float(value)
        return number / 100 if number > 1 else number

    @staticmethod
    def optional_int(value: str) -> int | None:
        value = value.strip()
        return int(value) if value else None

    @staticmethod
    def format_value(value) -> str:
        if isinstance(value, float):
            return f"{value:.4f}" if abs(value) < 10 and value != 0 else f"{value:,.2f}"
        return str(value)

    @staticmethod
    def format_money(value) -> str:
        return "" if value is None else f"{float(value):,.2f}"

    @staticmethod
    def format_won(value) -> str:
        return "" if value is None else f"{float(value):,.0f}"

    @staticmethod
    def format_number(value) -> str:
        return "" if value is None else f"{float(value):,.2f}"

    @staticmethod
    def format_input_number(value) -> str:
        if value is None:
            return ""
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if number.is_integer():
            return str(int(number))
        return f"{number:.10f}".rstrip("0").rstrip(".")

    @staticmethod
    def format_percent(value, digits: int = 2) -> str:
        return "" if value is None else f"{float(value) * 100:.{digits}f}%"

    @staticmethod
    def format_t_value(value) -> str:
        if value is None:
            return ""
        return f"{float(value):,.1f}".rstrip("0").rstrip(".")

    def format_infinite_progress(self, status: dict, split_count: int) -> str:
        t_value = status.get("t_value")
        if t_value is None or not split_count:
            return ""
        parts = [
            f"{self.format_t_value(t_value)}T / {int(split_count)}T",
            self.format_percent(status.get("progress"), digits=1),
        ]
        phase = status.get("phase")
        if phase:
            parts.append(str(phase))
        return " · ".join(parts)

    @staticmethod
    def format_g(snapshot: dict) -> str:
        if int(snapshot.get("cycle_no") or 0) == 0 and not snapshot.get("is_order_basis"):
            return ""
        value = snapshot.get("g")
        return "" if value is None else f"{float(value):,.2f}"


def main() -> None:
    app = VrStudyApp()
    app.mainloop()
