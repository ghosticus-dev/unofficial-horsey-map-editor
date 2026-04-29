import json
import re
import shutil
import sys
import time
import tkinter as tk
import ctypes
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageColor, ImageTk

APP_TITLE = "Unofficial Horsey Game Map Editor"
APP_VERSION = "0.2.0"
BASE_DIR = Path(__file__).resolve().parent
BACKUP_DIR = BASE_DIR / "backups"
TILE_DEFS_FILE = BASE_DIR / "tile_defs.json"
SETTINGS_FILE = BASE_DIR / "editor_settings.json"

PAINT_TILE_ID = "1"
MODE_INSPECT = "inspect"
MODE_PAINT = "paint"
MODE_OBJECT = "object"

REQUIRED_LOC_GIDS = (
    "97", "98", "99", "100", "101", "102", "103", "104",
    "110", "111", "112", "113", "114", "115", "117", "118",
    "119", "120", "121", "122", "123", "124", "125", "126",
    "127", "128", "133", "134", "145", "146", "147", "148",
    "149", "150", "153", "154",
)

LIGHT_THEME = {
    "root_bg": "#d8d8d8",
    "panel_bg": "#ececec",
    "header_bg": "#c4c4c4",
    "row_bg": "#d2d2d2",
    "row_selected_bg": "#f4f4f4",
    "text": "#101010",
    "canvas_bg": "#111111",
    "entry_bg": "#f7f7f7",
    "entry_fg": "#101010",
    "button_bg": "#d4d4d4",
    "button_fg": "#101010",
    "selection_border": "#2f5fb3",
    "panel_border": "#9a9a9a",
    "control_border": "#777777",
    "scrollbar_bg": "#b8b8b8",
    "scrollbar_active_bg": "#9f9f9f",
    "scrollbar_trough": "#d0d0d0",
    "scrollbar_arrow": "#101010",
}

DARK_THEME = {
    "root_bg": "#1f1f1f",
    "panel_bg": "#2a2a2a",
    "header_bg": "#3a3a3a",
    "row_bg": "#333333",
    "row_selected_bg": "#4a4a4a",
    "text": "#f2f2f2",
    "canvas_bg": "#101010",
    "entry_bg": "#151515",
    "entry_fg": "#f2f2f2",
    "button_bg": "#343434",
    "button_fg": "#f2f2f2",
    "selection_border": "#7aa2ff",
    "panel_border": "#303030",
    "control_border": "#555555",
    "scrollbar_bg": "#3a3a3a",
    "scrollbar_active_bg": "#505050",
    "scrollbar_trough": "#1a1a1a",
    "scrollbar_arrow": "#f2f2f2",
}


def load_tile_defs():
    if not TILE_DEFS_FILE.exists():
        return {}

    with open(TILE_DEFS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_settings():
    if not SETTINGS_FILE.exists():
        return {"install_location": "", "dark_mode": True}

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"install_location": "", "dark_mode": True}

    settings.setdefault("install_location", "")
    settings.setdefault("dark_mode", True)
    return settings


def save_settings(settings):
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = SETTINGS_FILE.with_suffix(f"{SETTINGS_FILE.suffix}.tmp")

    with open(temp_file, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)

    temp_file.replace(SETTINGS_FILE)


def load_tmx(path):
    content = path.read_text(encoding="utf-8")

    map_match = re.search(
        r'<map\b[^>]*\swidth="(\d+)"[^>]*\sheight="(\d+)"',
        content
    )

    if not map_match:
        raise ValueError("Could not find map width/height.")

    width = int(map_match.group(1))
    height = int(map_match.group(2))

    data_match = re.search(
        r'(<layer[^>]*name="Tiles"[^>]*>.*?<data encoding="csv">\s*)(.*?)(\s*</data>.*?</layer>)',
        content,
        re.DOTALL
    )

    if not data_match:
        raise ValueError("Could not find Tiles layer CSV data.")

    csv_data = data_match.group(2)

    tiles = []
    for line in csv_data.strip().splitlines():
        tiles.extend([p.strip() for p in line.split(",") if p.strip()])

    if len(tiles) != width * height:
        raise ValueError(f"Tile count mismatch: got {len(tiles)}, expected {width * height}.")

    objects = load_tmx_objects(content)

    return content, csv_data, tiles, width, height, objects


def load_tmx_objects(content):
    root = ET.fromstring(content)
    locs_group = None

    for object_group in root.findall("objectgroup"):
        if object_group.get("name") == "Locs":
            locs_group = object_group
            break

    if locs_group is None:
        return []

    objects = []
    for tmx_object in locs_group.findall("object"):
        properties = {}
        properties_element = tmx_object.find("properties")

        if properties_element is not None:
            for prop in properties_element.findall("property"):
                properties[prop.get("name", "")] = {
                    "type": prop.get("type", ""),
                    "value": prop.get("value", "")
                }

        x = float(tmx_object.get("x", "0"))
        y = float(tmx_object.get("y", "0"))

        objects.append({
            "id": tmx_object.get("id", ""),
            "type": tmx_object.get("type", ""),
            "gid": tmx_object.get("gid", ""),
            "x": x,
            "y": y,
            "width": float(tmx_object.get("width", "0")),
            "height": float(tmx_object.get("height", "0")),
            "tile_x": int(x // 32),
            "tile_y": int(y // 32),
            "properties": properties,
        })

    return objects


class HorseyMapEditor:
    def __init__(self, root):
        self.root = root
        self.root.title(f"{APP_TITLE} {APP_VERSION}")

        self.tile_defs = load_tile_defs()
        self.settings = load_settings()
        self.ttk_style = ttk.Style()
        self.color_cache = {}
        self.selected_tile_id = PAINT_TILE_ID
        self.editor_mode = MODE_INSPECT
        self.tile_buttons = {}
        self.object_buttons = {}
        self.inspected_tile_xy = None
        self.inspected_object = None
        self.selected_object_template = None

        self.zoom_levels = [5, 6, 8, 10, 12, 14, 16, 18, 20, 24, 28, 32, 36, 40]
        self.zoom_index = 3
        self.tile_size = self.zoom_levels[self.zoom_index]

        self.last_zoom_time = 0.0
        self.zoom_cooldown = 0.05

        # Redraws are coalesced so rapid input produces one redraw per UI cycle.
        self.scroll_redraw_pending = False
        self.paint_redraw_pending = False

        # View position in scaled-map pixels. The canvas displays only this viewport.
        self.view_x = 0
        self.view_y = 0

        self.image = None
        self.viewport_image_id = None
        self.tk_image = None
        self.empty_view_button = None
        self.empty_view_window_id = None

        self.hover_tile_xy = None
        self.highlight_tile_xy = None
        self.hover_object = None
        self.highlight_object = None
        self.last_mouse_x = None
        self.last_mouse_y = None

        self.undo_stack = []
        self.current_action = None
        self.is_painting = False
        self.hover_rect = None
        self.highlight_rect = None
        self.object_marker_ids = []
        self.hover_object_outline = None
        self.hover_object_label_ids = []
        self.highlight_object_outline = None
        self.grid_lines = []

        self.current_file = None
        self.output_file = None
        self.content = ""
        self.original_csv = ""
        self.tiles = []
        self.map_objects = []
        self.object_templates = []
        self.next_object_id = 1
        self.map_width = 0
        self.map_height = 0

        self.toolbar = tk.Frame(root, relief="raised", bd=1)
        self.toolbar.pack(side="top", fill="x")
        self.toolbar_popup = None
        self.toolbar_popup_button = None

        self.editor_button = self.create_toolbar_menu_button(
            "Editor",
            [
                {"label": "Load Map...", "command": self.load_map_dialog},
                {"label": "Save As...", "command": self.save_as_dialog},
                {"separator": True},
                {"label": "Export Map to Game", "command": self.export_map_to_game},
                {"label": "Restore Original Map TMX", "command": self.restore_original_map_tmx},
            ]
        )
        self.editor_button.pack(side="left", padx=4, pady=2)

        self.show_grid = tk.BooleanVar(value=True)
        self.show_locs = tk.BooleanVar(value=True)
        self.view_button = self.create_toolbar_menu_button(
            "View",
            [
                {
                    "label": "Grid Lines",
                    "command": self.toggle_grid_menu_item,
                    "dynamic_label": self.grid_toggle_menu_label
                },
                {
                    "label": "Locs Layer",
                    "command": self.toggle_locs_menu_item,
                    "dynamic_label": self.locs_toggle_menu_label
                },
            ]
        )
        self.view_button.pack(side="left", padx=4, pady=2)

        self.settings_button = self.create_toolbar_menu_button(
            "Settings",
            [
                {"label": "Editor Settings...", "command": self.open_settings_window},
                {"separator": True},
                {"label": "Clear Install Location", "command": self.clear_install_location},
            ]
        )
        self.settings_button.pack(side="left", padx=4, pady=2)

        self.help_button = self.create_toolbar_menu_button(
            "Help",
            [
                {"label": "Show Controls", "command": self.show_controls_dialog},
            ]
        )
        self.help_button.pack(side="left", padx=4, pady=2)

        self.main_area = tk.Frame(root)
        self.main_area.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(self.main_area, width=240, relief="groove", bd=1)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.tools_panel = tk.Frame(self.sidebar)
        self.tools_panel.pack(side="top", fill="both", expand=True)

        self.sidebar_title = tk.Label(
            self.tools_panel,
            text="Tools",
            anchor="center",
            font=("TkDefaultFont", 9, "bold"),
            bg="#d0d0d0"
        )
        self.sidebar_title.pack(fill="x", padx=0, pady=(0, 4))

        self.mode_var = tk.StringVar(value=self.editor_mode)
        self.inspect_button = tk.Radiobutton(
            self.tools_panel,
            text="Inspect Mode",
            variable=self.mode_var,
            value=MODE_INSPECT,
            indicatoron=False,
            command=self.set_mode_from_ui
        )
        self.inspect_button.pack(fill="x", padx=8, pady=2)

        self.paint_button = tk.Radiobutton(
            self.tools_panel,
            text="Paint Mode",
            variable=self.mode_var,
            value=MODE_PAINT,
            indicatoron=False,
            command=self.set_mode_from_ui
        )
        self.paint_button.pack(fill="x", padx=8, pady=2)

        self.object_button = tk.Radiobutton(
            self.tools_panel,
            text="Object Mode",
            variable=self.mode_var,
            value=MODE_OBJECT,
            indicatoron=False,
            command=self.set_mode_from_ui
        )
        self.object_button.pack(fill="x", padx=8, pady=2)

        

        self.inspector_panel = tk.Frame(self.sidebar, height=145, relief="groove", bd=1, bg="white")
        self.inspector_panel.pack(side="top", fill="x", padx=4, pady=(4, 0))
        self.inspector_panel.pack_propagate(False)

        self.inspector_title = tk.Label(
            self.inspector_panel,
            text="Tile Details",
            anchor="center",
            font=("TkDefaultFont", 8),
            bg="#d0d0d0"
        )
        self.inspector_title.pack(fill="x", padx=0, pady=(0, 2))

        self.inspector_details_frame = tk.Frame(self.inspector_panel, bg="white")
        self.inspector_details_frame.pack(fill="both", expand=True, padx=8, pady=(0, 4))

        self.inspector_details_text = tk.Text(
            self.inspector_details_frame,
            height=4,
            wrap="word",
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="arrow",
            takefocus=0
        )
        self.inspector_details_scroll = ttk.Scrollbar(
            self.inspector_details_frame,
            orient="vertical",
            command=self.inspector_details_text.yview
        )
        self.inspector_details_text.configure(yscrollcommand=self.on_inspector_details_scroll)
        self.inspector_details_text.pack(side="left", fill="both", expand=True)
        self.inspector_details_text.bind("<MouseWheel>", self.on_inspector_details_wheel)

        self.inspector_details_label = tk.Label(
            self.inspector_panel,
            text="No Coordinate Selected",
            anchor="nw",
            justify="left",
            wraplength=220,
            bg="white"
        )
        self.inspector_details_label.pack_forget()

        self.copy_tile_button = tk.Button(self.inspector_panel, text="Copy Tile", command=self.copy_inspected_tile)
        self.copy_tile_button.pack(fill="x", padx=8, pady=(0, 6))
        self.copy_tile_button.pack_forget()

        self.undo_button = tk.Button(self.sidebar, text="Undo", command=self.undo)
        self.undo_button.pack(side="bottom", fill="x", padx=8, pady=(0, 4))

        self.tile_selector_panel = tk.Frame(self.sidebar, height=260, relief="groove", bd=1, bg="white")
        self.tile_selector_panel.pack(side="bottom", fill="x", padx=4, pady=4)
        self.tile_selector_panel.pack_propagate(False)


        self.tile_selector_title = tk.Label(
            self.tile_selector_panel,
            text="Tile Selector",
            anchor="center",
            font=("TkDefaultFont", 8),
            bg="#d0d0d0"
        )
        self.tile_selector_title.pack(fill="x", padx=0, pady=(0, 2))

        self.selected_tile_label = tk.Label(self.tile_selector_panel, text="Selected: None", anchor="w", wraplength=220, justify="left", bg="white")
        self.selected_tile_label.pack(fill="x", padx=8, pady=(0, 4))

        self.tile_list_container = tk.Frame(self.tile_selector_panel, relief="sunken", bd=1, bg="white")
        self.tile_list_container.pack(fill="both", expand=True, padx=6, pady=(4, 8))

        self.tile_list_canvas = tk.Canvas(self.tile_list_container, width=190, highlightthickness=0, bg="white")
        self.tile_list_scroll = ttk.Scrollbar(self.tile_list_container, orient="vertical", command=self.tile_list_canvas.yview)
        self.tile_list_frame = tk.Frame(self.tile_list_canvas, bg="white")

        self.tile_list_frame.bind(
            "<Configure>",
            lambda event: self.tile_list_canvas.configure(scrollregion=self.tile_list_canvas.bbox("all"))
        )

        self.tile_list_window = self.tile_list_canvas.create_window((0, 0), window=self.tile_list_frame, anchor="nw")
        self.tile_list_canvas.configure(yscrollcommand=self.tile_list_scroll.set)
        self.tile_list_scroll.pack(side="right", fill="y")
        self.tile_list_canvas.pack(side="left", fill="both", expand=True)
        self.tile_list_canvas.bind("<Configure>", self.on_tile_list_resize)
        self.tile_list_canvas.bind("<MouseWheel>", self.on_tile_selector_wheel)
        self.tile_list_frame.bind("<MouseWheel>", self.on_tile_selector_wheel)
        self.tile_selector_panel.bind("<MouseWheel>", self.on_tile_selector_wheel)
        self.tile_list_container.bind("<MouseWheel>", self.on_tile_selector_wheel)

        self.object_selector_panel = tk.Frame(self.sidebar, height=260, relief="groove", bd=1, bg="white")
        self.object_selector_panel.pack(side="bottom", fill="x", padx=4, pady=4, before=self.tile_selector_panel)
        self.object_selector_panel.pack_propagate(False)

        self.object_selector_title = tk.Label(
            self.object_selector_panel,
            text="Object Selector",
            anchor="center",
            font=("TkDefaultFont", 8),
            bg="#d0d0d0"
        )
        self.object_selector_title.pack(fill="x", padx=0, pady=(0, 2))

        self.selected_object_label = tk.Label(
            self.object_selector_panel,
            text="Selected: None",
            anchor="w",
            wraplength=220,
            justify="left",
            bg="white"
        )
        self.selected_object_label.pack(fill="x", padx=8, pady=(0, 4))

        self.object_list_container = tk.Frame(self.object_selector_panel, relief="sunken", bd=1, bg="white")
        self.object_list_container.pack(fill="both", expand=True, padx=6, pady=(4, 8))

        self.object_list_canvas = tk.Canvas(self.object_list_container, width=190, highlightthickness=0, bg="white")
        self.object_list_scroll = ttk.Scrollbar(self.object_list_container, orient="vertical", command=self.object_list_canvas.yview)
        self.object_list_frame = tk.Frame(self.object_list_canvas, bg="white")

        self.object_list_frame.bind(
            "<Configure>",
            lambda event: self.object_list_canvas.configure(scrollregion=self.object_list_canvas.bbox("all"))
        )

        self.object_list_window = self.object_list_canvas.create_window((0, 0), window=self.object_list_frame, anchor="nw")
        self.object_list_canvas.configure(yscrollcommand=self.object_list_scroll.set)
        self.object_list_scroll.pack(side="right", fill="y")
        self.object_list_canvas.pack(side="left", fill="both", expand=True)
        self.object_list_canvas.bind("<Configure>", self.on_object_list_resize)
        self.object_list_canvas.bind("<MouseWheel>", self.on_object_selector_wheel)
        self.object_list_frame.bind("<MouseWheel>", self.on_object_selector_wheel)
        self.object_selector_panel.bind("<MouseWheel>", self.on_object_selector_wheel)
        self.object_list_container.bind("<MouseWheel>", self.on_object_selector_wheel)

        self.frame = tk.Frame(self.main_area)
        self.frame.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(
            self.frame,
            width=1000,
            height=700,
            bg="black",
            highlightthickness=0
        )

        self.h_scroll = ttk.Scrollbar(self.frame, orient="horizontal", command=self.on_h_scrollbar)
        self.v_scroll = ttk.Scrollbar(self.frame, orient="vertical", command=self.on_v_scrollbar)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scroll.grid(row=0, column=1, sticky="ns")
        self.h_scroll.grid(row=1, column=0, sticky="ew")

        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)

        self.bottom_bar = tk.Frame(root, relief="sunken", bd=1)
        self.bottom_bar.pack(side="bottom", fill="x")

        self.file_label = tk.Label(self.bottom_bar, text="Map: None", anchor="w")
        self.file_label.pack(side="left", padx=6)

        self.status = tk.Label(self.bottom_bar, text="No map loaded.", anchor="e")
        self.status.pack(side="right", fill="x", expand=True, padx=6)


        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<Button-3>", self.on_right_press)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self.on_shift_wheel)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Leave>", self.on_mouse_leave)
        self.canvas.bind("<Control-MouseWheel>", self.on_ctrl_scroll)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.root.bind("<Control-z>", self.undo)

        self.populate_tile_selector()
        self.update_selected_tile_label()
        self.populate_object_selector()
        self.update_selected_object_label()
        self.apply_theme()

        self.root.after(100, self.show_empty_view)
        self.root.after_idle(self.ensure_valid_install_location)

    def create_toolbar_menu_button(self, text, items):
        button = tk.Button(
            self.toolbar,
            text=text,
            relief="flat",
            bd=0,
            command=lambda: self.show_toolbar_popup(button, items)
        )
        button.menu_items = items
        return button

    def show_toolbar_popup(self, button, items):
        if self.toolbar_popup is not None and self.toolbar_popup_button == button:
            self.close_toolbar_popup()
            return

        self.close_toolbar_popup()
        theme = self.theme()

        popup = tk.Toplevel(self.root)
        popup.overrideredirect(True)
        popup.transient(self.root)
        popup.config(bg=theme["panel_border"], bd=0, highlightthickness=0)

        content = tk.Frame(
            popup,
            bg=theme["panel_bg"],
            bd=0,
            highlightthickness=1,
            highlightbackground=theme["panel_border"],
            highlightcolor=theme["panel_border"]
        )
        content.pack(fill="both", expand=True, padx=1, pady=1)

        for item in items:
            if item.get("separator"):
                tk.Frame(content, height=1, bg=theme["panel_border"]).pack(fill="x", padx=6, pady=3)
                continue

            if "dynamic_label" in item:
                display_label = f"  {item['dynamic_label']()}"
            else:
                display_label = f"  {item['label']}"

            row = tk.Label(
                content,
                text=display_label,
                anchor="w",
                bg=theme["panel_bg"],
                fg=theme["text"],
                padx=18,
                pady=3
            )
            row.pack(fill="x")

            def run_command(event=None, command=item["command"]):
                self.close_toolbar_popup()
                command()

            def activate(event, widget=row):
                widget.config(bg=theme["row_selected_bg"])

            def deactivate(event, widget=row):
                widget.config(bg=theme["panel_bg"])

            row.bind("<Button-1>", run_command)
            row.bind("<Return>", run_command)
            row.bind("<Enter>", activate)
            row.bind("<Leave>", deactivate)

        x = button.winfo_rootx()
        y = button.winfo_rooty() + button.winfo_height()
        popup.geometry(f"+{x}+{y}")
        popup.bind("<Escape>", lambda event: self.close_toolbar_popup())
        popup.lift(self.root)
        popup.attributes("-topmost", True)
        popup.after_idle(lambda: popup.attributes("-topmost", False))

        self.toolbar_popup = popup
        self.toolbar_popup_button = button

    def close_toolbar_popup(self):
        if self.toolbar_popup is None:
            return

        try:
            if self.toolbar_popup.winfo_exists():
                self.toolbar_popup.destroy()
        except tk.TclError:
            pass

        self.toolbar_popup = None
        self.toolbar_popup_button = None

    def toggle_grid_menu_item(self):
        self.show_grid.set(not self.show_grid.get())
        self.toggle_grid()

    def grid_toggle_menu_label(self):
        return "Hide Gridlines" if self.show_grid.get() else "Show Gridlines"

    def toggle_locs_menu_item(self):
        self.show_locs.set(not self.show_locs.get())
        if not self.show_locs.get():
            self.hover_object = None
            self.highlight_object = None
            self.inspected_object = None
            self.update_inspector_panel()
        self.redraw_viewport()

    def locs_toggle_menu_label(self):
        return "Hide Locs Layer" if self.show_locs.get() else "Show Locs Layer"

    def center_window(self, window):
        window.update_idletasks()

        parent_x = self.root.winfo_rootx()
        parent_y = self.root.winfo_rooty()
        parent_w = self.root.winfo_width()
        parent_h = self.root.winfo_height()

        window_w = window.winfo_width()
        window_h = window.winfo_height()

        x = parent_x + (parent_w // 2) - (window_w // 2)
        y = parent_y + (parent_h // 2) - (window_h // 2)

        window.geometry(f"+{x}+{y}")

    def theme(self):
        return DARK_THEME if self.settings.get("dark_mode", False) else LIGHT_THEME

    def apply_theme(self, window=None):
        theme = self.theme()
        target = window or self.root

        self.apply_ttk_theme(theme)
        self.apply_window_chrome(target)
        self.schedule_window_chrome_refresh(target)
        self.apply_theme_to_widget(target, theme)
        self.apply_theme_to_known_widgets(theme)
        self.update_tile_selector_selection()
        self.update_object_selector_selection()

        if self.has_map_loaded():
            self.draw_grid(
                max(0, int(self.view_x // self.tile_size)),
                max(0, int(self.view_y // self.tile_size)),
                min(self.map_width, int((self.view_x + self.canvas_width()) // self.tile_size) + 2),
                min(self.map_height, int((self.view_y + self.canvas_height()) // self.tile_size) + 2)
            )

    def apply_theme_to_widget(self, widget, theme):
        if getattr(widget, "is_tile_swatch", False):
            return

        try:
            if isinstance(widget, (tk.Tk, tk.Toplevel)):
                widget.config(bg=theme["root_bg"])
            elif isinstance(widget, tk.Canvas):
                widget.config(bg=theme["canvas_bg"])
            elif isinstance(widget, ttk.Scrollbar):
                widget.config(style="Horsey.Vertical.TScrollbar")
            elif isinstance(widget, tk.Entry):
                widget.config(
                    bg=theme["entry_bg"],
                    fg=theme["entry_fg"],
                    insertbackground=theme["entry_fg"],
                    relief="flat",
                    bd=1,
                    highlightthickness=1,
                    highlightbackground=theme["control_border"],
                    highlightcolor=theme["selection_border"]
                )
            elif isinstance(widget, tk.Text):
                widget.config(
                    bg=theme["panel_bg"],
                    fg=theme["text"],
                    insertbackground=theme["text"],
                    relief="flat",
                    bd=0,
                    highlightthickness=0
                )
            elif isinstance(widget, tk.Radiobutton):
                widget.config(
                    bg=theme["button_bg"],
                    fg=theme["button_fg"],
                    activebackground=theme["row_selected_bg"],
                    activeforeground=theme["text"],
                    selectcolor=theme["panel_bg"],
                    relief="raised",
                    bd=2,
                    borderwidth=2,
                    highlightthickness=0,
                    offrelief="raised",
                    overrelief="raised"
                )
            elif isinstance(widget, tk.Checkbutton):
                widget.config(
                    bg=theme["button_bg"],
                    fg=theme["button_fg"],
                    activebackground=theme["row_selected_bg"],
                    activeforeground=theme["text"],
                    selectcolor=theme["panel_bg"],
                    relief="flat",
                    bd=0,
                    highlightthickness=0
                )
            elif isinstance(widget, tk.Menubutton):
                widget.config(
                    bg=theme["root_bg"],
                    fg=theme["button_fg"],
                    activebackground=theme["row_selected_bg"],
                    activeforeground=theme["text"],
                    relief="flat",
                    bd=0,
                    borderwidth=0,
                    highlightthickness=0,
                    takefocus=0
                )
            elif isinstance(widget, tk.Button):
                if widget.master == self.toolbar:
                    widget.config(
                        bg=theme["root_bg"],
                        fg=theme["button_fg"],
                        activebackground=theme["row_selected_bg"],
                        activeforeground=theme["text"],
                        relief="flat",
                        bd=0,
                        highlightthickness=0,
                        takefocus=0
                    )
                else:
                    widget.config(
                        bg=theme["button_bg"],
                        fg=theme["button_fg"],
                        activebackground=theme["row_selected_bg"],
                        activeforeground=theme["text"],
                        relief="raised",
                        bd=2,
                        highlightthickness=0,
                        takefocus=0
                    )
            elif isinstance(widget, tk.Label):
                widget.config(
                    bg=theme["panel_bg"],
                    fg=theme["text"],
                    bd=0,
                    highlightthickness=0
                )
            elif isinstance(widget, tk.Frame):
                widget.config(
                    bg=theme["root_bg"],
                    highlightbackground=theme["panel_border"],
                    highlightcolor=theme["panel_border"]
                )
            elif isinstance(widget, tk.Menu):
                widget.config(
                    bg=theme["panel_bg"],
                    fg=theme["text"],
                    activebackground=theme["row_selected_bg"],
                    activeforeground=theme["text"]
                )
        except tk.TclError:
            pass

        for child in widget.winfo_children():
            self.apply_theme_to_widget(child, theme)

    def apply_ttk_theme(self, theme):
        try:
            self.ttk_style.theme_use("clam")
        except tk.TclError:
            pass

        common_scrollbar_settings = {
            "background": theme["scrollbar_bg"],
            "darkcolor": theme["scrollbar_bg"],
            "lightcolor": theme["scrollbar_bg"],
            "troughcolor": theme["scrollbar_trough"],
            "bordercolor": theme["root_bg"],
            "arrowcolor": theme["scrollbar_arrow"],
            "relief": "flat",
            "borderwidth": 1,
        }

        self.ttk_style.configure("Horsey.Vertical.TScrollbar", **common_scrollbar_settings)
        self.ttk_style.configure("Horsey.Horizontal.TScrollbar", **common_scrollbar_settings)

        for style_name in ["Horsey.Vertical.TScrollbar", "Horsey.Horizontal.TScrollbar"]:
            self.ttk_style.map(
                style_name,
                background=[
                    ("active", theme["scrollbar_active_bg"]),
                    ("pressed", theme["scrollbar_active_bg"]),
                    ("!disabled", theme["scrollbar_bg"]),
                ],
                arrowcolor=[
                    ("disabled", theme["scrollbar_trough"]),
                    ("!disabled", theme["scrollbar_arrow"]),
                ],
            )

    def apply_window_chrome(self, window):
        if sys.platform != "win32":
            return

        try:
            window.update_idletasks()
            hwnd = self.window_handle(window)
            enabled = ctypes.c_int(1 if self.settings.get("dark_mode", False) else 0)
            dark_mode = self.settings.get("dark_mode", False)

            for attribute in (20, 19):
                result = ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    attribute,
                    ctypes.byref(enabled),
                    ctypes.sizeof(enabled)
                )

                if result == 0:
                    break

            border_color = self.colorref("#2b2b2b" if dark_mode else "#d8d8d8")
            caption_color = self.colorref("#1f1f1f" if dark_mode else "#d8d8d8")
            text_color = self.colorref("#f2f2f2" if dark_mode else "#000000")

            for attribute, color in [(34, border_color), (35, caption_color), (36, text_color)]:
                color_value = ctypes.c_int(color)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd,
                    attribute,
                    ctypes.byref(color_value),
                    ctypes.sizeof(color_value)
                )
        except Exception:
            pass

    def schedule_window_chrome_refresh(self, window):
        for delay in (1, 50, 200):
            try:
                window.after(delay, lambda target=window: self.apply_window_chrome(target))
            except tk.TclError:
                pass

    def window_handle(self, window):
        hwnd = window.winfo_id()
        parent = ctypes.windll.user32.GetParent(hwnd)
        return parent or hwnd

    def colorref(self, color):
        red = int(color[1:3], 16)
        green = int(color[3:5], 16)
        blue = int(color[5:7], 16)
        return red | (green << 8) | (blue << 16)

    def apply_theme_to_known_widgets(self, theme):
        themed_widgets = [
            (self.toolbar, "root_bg"),
            (self.main_area, "root_bg"),
            (self.sidebar, "root_bg"),
            (self.tools_panel, "root_bg"),
            (self.sidebar_title, "header_bg"),
            (self.inspector_panel, "panel_bg"),
            (self.inspector_title, "header_bg"),
            (self.inspector_details_frame, "panel_bg"),
            (self.inspector_details_text, "panel_bg"),
            (self.tile_selector_panel, "panel_bg"),
            (self.tile_selector_title, "header_bg"),
            (self.selected_tile_label, "panel_bg"),
            (self.tile_list_container, "panel_bg"),
            (self.tile_list_canvas, "panel_bg"),
            (self.tile_list_frame, "panel_bg"),
            (self.object_selector_panel, "panel_bg"),
            (self.object_selector_title, "header_bg"),
            (self.selected_object_label, "panel_bg"),
            (self.object_list_container, "panel_bg"),
            (self.object_list_canvas, "panel_bg"),
            (self.object_list_frame, "panel_bg"),
            (self.frame, "root_bg"),
            (self.bottom_bar, "root_bg"),
            (self.file_label, "root_bg"),
            (self.status, "root_bg"),
        ]

        for widget, bg_key in themed_widgets:
            try:
                widget.config(bg=theme[bg_key])
                if isinstance(widget, tk.Label):
                    widget.config(fg=theme["text"])
            except tk.TclError:
                pass

        bordered_widgets = [
            self.toolbar,
            self.sidebar,
            self.inspector_panel,
            self.tile_selector_panel,
            self.tile_list_container,
            self.object_selector_panel,
            self.object_list_container,
            self.bottom_bar,
        ]

        for widget in bordered_widgets:
            try:
                widget.config(
                    relief="flat",
                    bd=0,
                    highlightthickness=1,
                    highlightbackground=theme["panel_border"],
                    highlightcolor=theme["panel_border"]
                )
            except tk.TclError:
                pass

        scrollbar_styles = [
            (self.inspector_details_scroll, "Horsey.Vertical.TScrollbar"),
            (self.tile_list_scroll, "Horsey.Vertical.TScrollbar"),
            (self.object_list_scroll, "Horsey.Vertical.TScrollbar"),
            (self.v_scroll, "Horsey.Vertical.TScrollbar"),
            (self.h_scroll, "Horsey.Horizontal.TScrollbar"),
        ]

        for scrollbar, style_name in scrollbar_styles:
            try:
                scrollbar.config(style=style_name)
            except tk.TclError:
                pass

    def set_dark_mode(self, enabled, active_window=None):
        old_dark_mode = self.settings.get("dark_mode", False)
        self.settings["dark_mode"] = bool(enabled)

        try:
            save_settings(self.settings)
        except OSError as exc:
            self.settings["dark_mode"] = old_dark_mode
            messagebox.showerror("Settings Save Failed", str(exc))
            return

        self.apply_theme()

        if active_window is not None and active_window.winfo_exists():
            self.apply_theme(active_window)

    def show_controls_dialog(self):
        controls_text = (
            "Horsey Map Editor Controls\n\n"
            "Editor Menu\n"
            "- Load Map...: Load a TMX map file\n"
            "- Save As...: Save edited map to a chosen TMX file\n"
            "- Export Map to Game: Export the current edited map to /data/horsey.tmx\n"
            "- Restore Original Map TMX: Restore /data/horsey.tmx from the preserved backup\n\n"
            "View Menu\n"
            "- Grid Lines: Toggle tile grid visibility\n\n"
            "Settings Menu\n"
            "- Editor Settings...: Set the Horsey Game install location\n"
            "- Clear Install Location: Clear the saved install folder and reopen setup\n\n"
            "Mouse Controls\n"
            "- Left Click in Inspect Mode: Highlight/select tile\n"
            "- Left Click + Drag in Paint Mode: Paint tiles\n"
            "- Right Click: Clear highlighted tile\n"
            "- Mouse Wheel: Scroll vertically\n"
            "- Shift + Mouse Wheel: Scroll horizontally\n"
            "- Ctrl + Mouse Wheel: Zoom in/out across multiple zoom levels (14 total)\n"
            "- Mouse over map: Inspect tile under cursor\n\n"
            "Hotkeys\n"
            "- Ctrl + Z: Undo last action\n"
        )

        messagebox.showinfo("Controls", controls_text)

    def save_install_location(self, install_path):
        install_path = install_path.resolve()
        horsey_exe = install_path / "Horsey.exe"

        if not install_path.exists() or not install_path.is_dir():
            raise ValueError("That folder does not exist.")

        if not horsey_exe.exists() or not horsey_exe.is_file():
            raise ValueError(f"Could not find Horsey.exe in:\n{install_path}")

        old_install_location = self.settings.get("install_location", "")
        old_install_path = Path(old_install_location).resolve() if old_install_location else None
        install_location_changed = old_install_path != install_path
        self.settings["install_location"] = str(install_path)

        try:
            save_settings(self.settings)
            backup_path = self.create_official_map_backup(overwrite=False) if install_location_changed else self.official_backup_path()
        except Exception:
            self.settings["install_location"] = old_install_location
            try:
                save_settings(self.settings)
            except OSError:
                pass
            raise

        self.status.config(text="Install location valid. Official map backup ready.")
        return backup_path, install_location_changed

    def open_settings_window(self, startup_message=None):
        settings_window = tk.Toplevel(self.root)
        settings_window.title("Editor Settings")
        settings_window.resizable(False, False)
        settings_window.transient(self.root)
        settings_window.grab_set()

        if startup_message:
            tk.Label(
                settings_window,
                text=startup_message,
                anchor="w",
                justify="left",
                fg="red"
            ).pack(fill="x", padx=10, pady=(10, 4))
            label_pad = (4, 4)
        else:
            label_pad = (10, 4)

        tk.Label(settings_window, text="Horsey Game Install Location", anchor="w").pack(fill="x", padx=10, pady=label_pad)
        tk.Label(settings_window, text="Select the folder that contains Horsey.exe", anchor="w").pack(fill="x", padx=10, pady=(0, 4))

        location_var = tk.StringVar(value=self.settings.get("install_location", ""))
        entry = tk.Entry(settings_window, textvariable=location_var, width=60)
        entry.pack(fill="x", padx=10, pady=(0, 6))

        dark_mode_var = tk.BooleanVar(value=self.settings.get("dark_mode", False))
        dark_mode_check = tk.Checkbutton(
            settings_window,
            text="Dark Mode",
            variable=dark_mode_var,
            command=lambda: self.set_dark_mode(dark_mode_var.get(), settings_window)
        )
        dark_mode_check.pack(fill="x", padx=10, pady=(0, 10))

        def browse_location():
            selected = filedialog.askdirectory(title="Select Folder Containing Horsey.exe")
            if selected:
                location_var.set(selected)

        def save_location():
            install_path = Path(location_var.get().strip())

            try:
                backup_path, install_location_changed = self.save_install_location(install_path)
            except ValueError as exc:
                messagebox.showerror("Invalid Install Location", str(exc))
                return
            except OSError as exc:
                messagebox.showerror("Install Location Save Failed", str(exc))
                return

            settings_window.destroy()

            if install_location_changed:
                messagebox.showinfo(
                    "Install Location Valid",
                    "Install Location was valid.\n\n"
                    "A backup of the official map was created at:\n"
                    f"{backup_path}\n\n"
                    "You are ready to start making maps."
                )

            self.status.config(text="Install location valid. Official map backup ready.")

        button_row = tk.Frame(settings_window)
        button_row.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(button_row, text="Browse...", command=browse_location).pack(side="left")
        tk.Button(button_row, text="Save", command=save_location).pack(side="right", padx=(4, 0))
        tk.Button(button_row, text="Cancel", command=settings_window.destroy).pack(side="right")

        self.apply_theme(settings_window)
        self.center_window(settings_window)

    def has_valid_install_location(self):
        install_location = self.settings.get("install_location", "").strip()
        if not install_location:
            return False

        install_path = Path(install_location)
        return install_path.is_dir() and (install_path / "Horsey.exe").is_file()

    def ensure_valid_install_location(self):
        if not self.has_valid_install_location():
            self.open_welcome_window()

    def open_welcome_window(self):
        welcome_window = tk.Toplevel(self.root)
        welcome_window.title(APP_TITLE)
        welcome_window.resizable(False, False)
        welcome_window.transient(self.root)
        welcome_window.grab_set()

        def close_program():
            welcome_window.grab_release()
            welcome_window.destroy()
            self.root.destroy()

        welcome_window.protocol("WM_DELETE_WINDOW", close_program)

        tk.Label(
            welcome_window,
            text=APP_TITLE,
            anchor="center",
            font=("TkDefaultFont", 14, "bold")
        ).pack(fill="x", padx=18, pady=(16, 2))

        tk.Label(
            welcome_window,
            text=f"Version {APP_VERSION}",
            anchor="center"
        ).pack(fill="x", padx=18, pady=(0, 12))

        commands_text = (
            "Viewport Commands\n\n"
            "Zoom: Ctrl + Mouse Wheel\n"
            "Scroll: Mouse Wheel vertically, Shift + Mouse Wheel horizontally\n"
            "Select: Inspect Mode, then left-click a tile\n"
            "Paint: Pick a tile, then left-click or drag in Paint Mode"
        )

        tk.Label(
            welcome_window,
            text=commands_text,
            anchor="w",
            justify="left"
        ).pack(fill="x", padx=18, pady=(0, 14))

        status_label = tk.Label(
            welcome_window,
            text="Select the folder that contains Horsey.exe to continue.",
            anchor="w",
            justify="left",
            fg="red",
            wraplength=380
        )
        status_label.pack(fill="x", padx=18, pady=(0, 8))

        def select_horsey_game_folder():
            selected = filedialog.askdirectory(
                title="Select Horsey Game Folder",
                parent=welcome_window
            )

            if not selected:
                status_label.config(text="Select a valid Horsey Game folder to continue.")
                return

            try:
                backup_path, install_location_changed = self.save_install_location(Path(selected))
            except Exception as exc:
                status_label.config(text=str(exc))
                messagebox.showerror("Invalid Horsey Game Folder", str(exc), parent=welcome_window)
                return

            welcome_window.grab_release()
            welcome_window.destroy()

            backup_text = (
                "A backup of the official map was created at:\n"
                f"{backup_path}\n\n"
                if install_location_changed
                else ""
            )
            messagebox.showinfo(
                "Horsey Game Folder Saved",
                "Horsey Game folder accepted.\n\n"
                f"{backup_text}"
                "You are ready to start making maps.",
                parent=self.root
            )

        button_row = tk.Frame(welcome_window)
        button_row.pack(fill="x", padx=18, pady=(0, 16))

        tk.Button(
            button_row,
            text="Select Horsey Game Folder",
            command=select_horsey_game_folder
        ).pack(side="left")

        tk.Button(
            button_row,
            text="Exit",
            command=close_program
        ).pack(side="right")

        self.apply_theme(welcome_window)
        self.center_window(welcome_window)

    def official_map_path(self):
        install_location = self.settings.get("install_location", "").strip()
        if not install_location:
            return None
        return Path(install_location) / "data" / "horsey.tmx"

    def official_backup_path(self):
        official_map = self.official_map_path()
        if official_map is None:
            return None
        return official_map.with_name(f"{official_map.name}.backup")

    def create_official_map_backup(self, overwrite=False):
        official_map = self.official_map_path()
        backup_path = self.official_backup_path()

        if official_map is None or backup_path is None:
            raise ValueError("No install location is set.")

        if not official_map.exists():
            raise FileNotFoundError(f"Could not find official map:\n{official_map}")

        if backup_path.exists() and not overwrite:
            return backup_path

        shutil.copy2(official_map, backup_path)
        return backup_path

    def clear_install_location(self):
        confirmed = messagebox.askyesno(
            "Clear Install Location",
            "Clear the saved Horsey Game install location?\n\n"
            "You will need to select a valid Horsey Game folder before continuing.",
            parent=self.root
        )

        if not confirmed:
            self.status.config(text="Install location unchanged.")
            return

        self.settings["install_location"] = ""
        save_settings(self.settings)
        messagebox.showinfo(
            "Install Location Cleared",
            "Install location cleared. Select a valid folder to continue.",
            parent=self.root
        )
        self.status.config(text="Install location cleared.")
        self.open_welcome_window()

    def missing_required_loc_gids(self):
        present_gids = {obj.get("gid", "") for obj in self.map_objects}
        return [gid for gid in REQUIRED_LOC_GIDS if gid not in present_gids]

    def is_repeatable_loc_object(self, obj):
        properties = obj.get("properties", {})
        has_creature_spawn_properties = "count" in properties and "radius" in properties
        has_buried_property = "buried" in properties
        return has_creature_spawn_properties or has_buried_property

    def duplicate_unique_loc_gids(self):
        unique_gid_objects = {}

        for obj in self.map_objects:
            if self.is_repeatable_loc_object(obj):
                continue

            gid = obj.get("gid", "")
            if not gid:
                continue

            unique_gid_objects.setdefault(gid, []).append(obj)

        return {
            gid: objects
            for gid, objects in unique_gid_objects.items()
            if len(objects) > 1
        }

    def missing_required_loc_gids_message(self, missing_gids):
        return (
            "This map is missing required Locs object GIDs and is not game ready.\n\n"
            "Missing GIDs:\n"
            f"{', '.join(missing_gids)}\n\n"
            "Every map must contain at least one Locs object for every required GID."
        )

    def duplicate_unique_loc_gids_message(self, duplicate_gids):
        lines = []

        for gid, objects in duplicate_gids.items():
            object_ids = ", ".join(obj.get("id", "") for obj in objects)
            object_type = objects[0].get("type") or "(blank)"
            lines.append(f"GID {gid} ({object_type}) appears {len(objects)} times: object IDs {object_ids}")

        return (
            "This map has duplicate unique Locs object GIDs and is not game ready.\n\n"
            "Only creature spawners with count/radius and buried objects may appear more than once.\n\n"
            "Duplicate unique GIDs:\n"
            + "\n".join(lines)
        )

    def locs_readiness_errors(self):
        errors = []
        missing_gids = self.missing_required_loc_gids()
        duplicate_gids = self.duplicate_unique_loc_gids()

        if missing_gids:
            errors.append(self.missing_required_loc_gids_message(missing_gids))

        if duplicate_gids:
            errors.append(self.duplicate_unique_loc_gids_message(duplicate_gids))

        return errors

    def locs_readiness_message(self, errors):
        return "\n\n".join(errors)

    def confirm_save_with_locs_rule_failures(self):
        errors = self.locs_readiness_errors()

        if not errors:
            return True

        return messagebox.askyesno(
            "Map Not Game Ready",
            self.locs_readiness_message(errors)
            + "\n\nSave anyway?"
        )

    def can_export_with_required_locs(self):
        errors = self.locs_readiness_errors()

        if not errors:
            return True

        messagebox.showerror(
            "Export Blocked",
            self.locs_readiness_message(errors)
            + "\n\nExport is blocked until the required objects are present."
        )
        self.status.config(text="Export blocked. Locs object rules failed.")
        return False

    def export_map_to_game(self):
        if not self.has_map_loaded():
            messagebox.showwarning("No Map Loaded", "Load a map before exporting to the game.")
            return

        if not self.can_export_with_required_locs():
            return

        confirmed = messagebox.askyesno(
            "Export Map to Game",
            "This will replace the game's current /data/horsey.tmx with the map currently open in the editor.\n\n"
            "A backup will be created first if one does not already exist.\n\n"
            "Continue?"
        )

        if not confirmed:
            self.status.config(text="Export cancelled.")
            return

        official_map = self.official_map_path()
        backup_path = self.official_backup_path()

        if official_map is None or backup_path is None:
            messagebox.showwarning(
                "Install Location Needed",
                "Set a valid Horsey Game install location in Settings > Editor Settings... first."
            )
            return

        try:
            if not backup_path.exists():
                self.create_official_map_backup(overwrite=False)

            if official_map.exists():
                official_map.unlink()

            official_map.write_text(self.build_current_map_content(), encoding="utf-8")

            messagebox.showinfo(
                "Export Successful",
                "Current edited map exported to:\n"
                f"{official_map}\n\n"
                "If anything breaks, use Editor > Restore Original Map TMX to restore the backup."
            )
            self.status.config(text="Current map exported to game data folder.")
        except Exception as exc:
            messagebox.showerror("Export Failed", str(exc))
            self.status.config(text="Export failed.")

    def restore_original_map_tmx(self):
        official_map = self.official_map_path()
        backup_path = self.official_backup_path()

        if official_map is None or backup_path is None:
            messagebox.showwarning(
                "Install Location Needed",
                "Set a valid Horsey Game install location in Settings > Editor Settings... first."
            )
            return

        if not backup_path.exists():
            messagebox.showerror(
                "Backup Not Found",
                f"Could not find backup:\n{backup_path}"
            )
            return

        restore = messagebox.askyesno(
            "Restore Original Map TMX",
            "This will delete the current /data/horsey.tmx and replace it with the preserved backup.\n\n"
            "The backup file will remain untouched.\n\n"
            "Continue?"
        )

        if not restore:
            return

        try:
            if official_map.exists():
                official_map.unlink()
            shutil.copy2(backup_path, official_map)
            messagebox.showinfo("Restore Complete", f"Restored original map to:\n{official_map}")
            self.status.config(text="Original map TMX restored from backup.")
        except OSError as exc:
            messagebox.showerror("Restore Failed", str(exc))

    def set_mode_from_ui(self):
        self.editor_mode = self.mode_var.get()
        self.update_tile_selector_selection()
        self.update_object_selector_selection()
        self.update_inspector_panel()
        self.status.config(text=f"Mode: {self.editor_mode.title()}")

    def set_mode(self, mode):
        self.editor_mode = mode
        self.mode_var.set(mode)
        self.update_tile_selector_selection()
        self.update_object_selector_selection()
        self.update_inspector_panel()
        self.status.config(text=f"Mode: {self.editor_mode.title()}")

    def on_left_press(self, event):
        if self.editor_mode == MODE_PAINT:
            self.is_painting = True
            self.begin_action("Paint")
            self.paint_tile(event)
        elif self.editor_mode == MODE_OBJECT:
            self.place_selected_object(event)
        else:
            self.highlight_tile(event)

    def on_left_drag(self, event):
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        self.update_hover_from_position(event.x, event.y)

        if self.editor_mode == MODE_PAINT and self.is_painting:
            self.paint_tile(event)
        else:
            self.redraw_overlays()

    def on_left_release(self, event):
        if self.editor_mode == MODE_PAINT and self.is_painting:
            self.paint_tile(event)
            self.commit_action()

        self.is_painting = False

    def on_right_press(self, event):
        if self.editor_mode == MODE_OBJECT:
            self.remove_hovered_object(event)
        else:
            self.clear_highlight(event)

    def on_tile_list_resize(self, event):
        self.tile_list_canvas.itemconfig(self.tile_list_window, width=event.width)

    def on_object_list_resize(self, event):
        self.object_list_canvas.itemconfig(self.object_list_window, width=event.width)

    def on_tile_selector_wheel(self, event):
        step = int(-1 * (event.delta / 120))
        self.tile_list_canvas.yview_scroll(step, "units")
        return "break"

    def on_object_selector_wheel(self, event):
        step = int(-1 * (event.delta / 120))
        self.object_list_canvas.yview_scroll(step, "units")
        return "break"

    def populate_tile_selector(self):
        theme = self.theme()

        for child in self.tile_list_frame.winfo_children():
            child.destroy()

        self.tile_buttons = {}
        tile_ids = sorted(self.tile_defs.keys(), key=lambda value: int(value) if value.isdigit() else value)

        for tile_id in tile_ids:
            tile_name = self.tile_name(tile_id)
            tile_color = self.tile_color(tile_id)

            outer = tk.Frame(self.tile_list_frame, bg=theme["panel_bg"], height=30)
            outer.pack(fill="x", pady=1, padx=(1, 4))
            outer.pack_propagate(False)

            row = tk.Frame(
                outer,
                relief="raised",
                bd=2,
                bg=theme["row_bg"],
                highlightthickness=0
            )
            row.pack(fill="both", expand=True, padx=2, pady=2)

            swatch = tk.Label(
                row,
                text="",
                bg=tile_color,
                width=3,
                height=1,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=theme["control_border"],
                highlightcolor=theme["control_border"]
            )
            swatch.is_tile_swatch = True
            swatch.pack(side="left", padx=4, pady=4)

            label = tk.Label(
                row,
                text=f"{tile_name} | ID: {tile_id}",
                anchor="w",
                justify="left",
                bg=theme["row_bg"],
                fg=theme["text"]
            )
            label.pack(side="left", fill="x", expand=True, padx=4, pady=2)

            row.bind("<Button-1>", lambda event, tid=tile_id: self.select_tile(tid))
            swatch.bind("<Button-1>", lambda event, tid=tile_id: self.select_tile(tid))
            label.bind("<Button-1>", lambda event, tid=tile_id: self.select_tile(tid))
            outer.bind("<MouseWheel>", self.on_tile_selector_wheel)
            row.bind("<MouseWheel>", self.on_tile_selector_wheel)
            swatch.bind("<MouseWheel>", self.on_tile_selector_wheel)
            label.bind("<MouseWheel>", self.on_tile_selector_wheel)

            self.tile_buttons[tile_id] = (outer, row, label)

    def select_tile(self, tile_id):
        self.selected_tile_id = tile_id
        self.update_selected_tile_label()
        self.set_mode(MODE_PAINT)

    def build_object_templates(self):
        templates = {}

        for obj in self.map_objects:
            key = self.object_template_key(obj)

            if key not in templates:
                templates[key] = {
                    "key": key,
                    "type": obj.get("type", ""),
                    "gid": obj.get("gid", ""),
                    "width": obj.get("width", 32.0),
                    "height": obj.get("height", 32.0),
                    "properties": self.copy_object_properties(obj.get("properties", {})),
                    "repeatable": self.is_repeatable_loc_object(obj),
                }

        self.object_templates = sorted(
            templates.values(),
            key=lambda template: (
                self.object_display_name(template).lower(),
                int(template.get("gid", 0)) if str(template.get("gid", "")).isdigit() else 0
            )
        )

    def object_template_key(self, obj):
        properties = obj.get("properties", {})
        property_names = tuple(sorted(properties.keys()))
        return (obj.get("gid", ""), obj.get("type", ""), property_names)

    def copy_object_properties(self, properties):
        return {
            name: {
                "type": prop.get("type", ""),
                "value": prop.get("value", "")
            }
            for name, prop in properties.items()
        }

    def object_display_name(self, obj):
        object_type = obj.get("type") or "(blank)"
        return object_type.strip() or "(blank)"

    def object_template_count(self, template):
        return sum(1 for obj in self.map_objects if self.object_template_key(obj) == template.get("key"))

    def gid_count(self, gid):
        return sum(1 for obj in self.map_objects if obj.get("gid", "") == gid)

    def template_is_repeatable(self, template):
        return template.get("repeatable", False)

    def object_template_is_placed(self, template):
        return self.gid_count(template.get("gid", "")) > 0

    def next_available_object_id(self):
        existing_ids = {
            int(obj.get("id", 0))
            for obj in self.map_objects
            if str(obj.get("id", "")).isdigit()
        }

        while self.next_object_id in existing_ids:
            self.next_object_id += 1

        object_id = self.next_object_id
        self.next_object_id += 1
        return str(object_id)

    def populate_object_selector(self):
        theme = self.theme()

        for child in self.object_list_frame.winfo_children():
            child.destroy()

        self.object_buttons = {}

        for template in self.object_templates:
            object_name = self.object_display_name(template)
            gid = template.get("gid", "")
            count = self.object_template_count(template)
            missing_required = gid in REQUIRED_LOC_GIDS and self.gid_count(gid) == 0

            outer = tk.Frame(self.object_list_frame, bg=theme["panel_bg"], height=36)
            outer.pack(fill="x", pady=1, padx=(1, 4))
            outer.pack_propagate(False)

            row = tk.Frame(
                outer,
                relief="raised",
                bd=2,
                bg=theme["row_bg"],
                highlightthickness=0
            )
            row.pack(fill="both", expand=True, padx=2, pady=2)

            status_color = "#d63b3b" if missing_required else "#2fb36d"
            swatch = tk.Label(
                row,
                text="",
                bg=status_color,
                width=2,
                height=1,
                relief="flat",
                bd=0,
                highlightthickness=1,
                highlightbackground=theme["control_border"],
                highlightcolor=theme["control_border"]
            )
            swatch.is_tile_swatch = True
            swatch.pack(side="left", padx=4, pady=4)

            label = tk.Label(
                row,
                text=f"{object_name} | GID: {gid} | Count: {count}",
                anchor="w",
                justify="left",
                bg=theme["row_bg"],
                fg=theme["text"],
                wraplength=170
            )
            label.pack(side="left", fill="x", expand=True, padx=4, pady=2)

            row.bind("<Button-1>", lambda event, tmpl=template: self.select_object_template(tmpl))
            swatch.bind("<Button-1>", lambda event, tmpl=template: self.select_object_template(tmpl))
            label.bind("<Button-1>", lambda event, tmpl=template: self.select_object_template(tmpl))
            outer.bind("<MouseWheel>", self.on_object_selector_wheel)
            row.bind("<MouseWheel>", self.on_object_selector_wheel)
            swatch.bind("<MouseWheel>", self.on_object_selector_wheel)
            label.bind("<MouseWheel>", self.on_object_selector_wheel)

            self.object_buttons[template["key"]] = (outer, row, label, swatch)

    def select_object_template(self, template):
        self.selected_object_template = template
        self.update_selected_object_label()
        self.set_mode(MODE_OBJECT)

    def update_selected_object_label(self):
        if self.selected_object_template is None:
            self.selected_object_label.config(text="Selected: None")
            return

        self.selected_object_label.config(
            text=(
                f"Selected: {self.object_display_name(self.selected_object_template)} | "
                f"GID: {self.selected_object_template.get('gid')}"
            )
        )

    def update_object_selector_selection(self):
        theme = self.theme()

        for template in self.object_templates:
            widgets = self.object_buttons.get(template["key"])
            if widgets is None:
                continue

            is_selected = self.editor_mode == MODE_OBJECT and self.selected_object_template is not None and template["key"] == self.selected_object_template.get("key")
            bg = theme["row_selected_bg"] if is_selected else theme["row_bg"]
            missing_required = template.get("gid", "") in REQUIRED_LOC_GIDS and self.gid_count(template.get("gid", "")) == 0
            status_color = "#d63b3b" if missing_required else "#2fb36d"
            outer, row, label, swatch = widgets

            row.config(bg=bg, relief="sunken" if is_selected else "raised")
            label.config(
                text=f"{self.object_display_name(template)} | GID: {template.get('gid')} | Count: {self.object_template_count(template)}",
                bg=bg,
                fg=theme["text"]
            )
            swatch.config(bg=status_color)

            if is_selected:
                outer.config(bg=theme["selection_border"])
                row.pack_configure(padx=1, pady=1)
            else:
                outer.config(bg=theme["panel_bg"])
                row.pack_configure(padx=2, pady=2)

    def update_tile_selector_selection(self):
        theme = self.theme()

        for tile_id, widgets in self.tile_buttons.items():
            is_selected = self.editor_mode == MODE_PAINT and tile_id == self.selected_tile_id
            bg = theme["row_selected_bg"] if is_selected else theme["row_bg"]

            outer, row, label = widgets
            row.config(
                bg=bg,
                relief="sunken" if is_selected else "raised",
                highlightbackground=theme["selection_border"] if is_selected else theme["panel_border"],
                highlightcolor=theme["selection_border"] if is_selected else theme["panel_border"]
            )
            label.config(bg=bg, fg=theme["text"])

            # Resize the inner row inside a fixed-height outer frame instead of changing borders.
            # This gives a thicker-looking selection without pushing neighboring rows around.
            if is_selected:
                outer.config(bg=theme["selection_border"])
                row.pack_configure(padx=1, pady=1)
            else:
                outer.config(bg=theme["panel_bg"])
                row.pack_configure(padx=2, pady=2)

    def update_inspector_panel(self):
        if self.inspected_object is not None:
            obj = self.inspected_object
            properties = obj.get("properties", {})
            property_lines = []

            for name, prop in properties.items():
                prop_type = prop.get("type")
                type_text = f" ({prop_type})" if prop_type else ""
                property_lines.append(f"{name}{type_text}: {prop.get('value', '')}")

            property_text = "\n".join(property_lines) if property_lines else "None"
            type_text = obj.get("type") or "(blank)"

            self.set_inspector_details(
                "Object Layer: Locs\n"
                f"Object ID: {obj.get('id')}\n"
                f"Type: {type_text}\n"
                f"GID: {obj.get('gid')}\n"
                f"Coordinate: ({obj.get('tile_x')}, {obj.get('tile_y')})\n"
                f"Properties:\n{property_text}"
            )
            self.copy_tile_button.pack_forget()
            return

        if self.inspected_tile_xy is None:
            self.set_inspector_details("No Coordinate Selected")
            self.copy_tile_button.pack_forget()
            return

        x, y = self.inspected_tile_xy
        index = y * self.map_width + x
        tile_id = self.tiles[index]

        self.set_inspector_details(
            f"Coordinate: ({x}, {y})\n"
            f"Type: {self.tile_name(tile_id)}\n"
            f"ID: {tile_id}"
        )

        if not self.copy_tile_button.winfo_ismapped():
            self.copy_tile_button.pack(fill="x", padx=8, pady=(0, 6))

    def set_inspector_details(self, text):
        self.inspector_details_text.config(state="normal")
        self.inspector_details_text.delete("1.0", "end")
        self.inspector_details_text.insert("1.0", text)
        self.inspector_details_text.config(state="disabled")
        self.inspector_details_text.yview_moveto(0)
        self.root.after_idle(self.update_inspector_details_scrollbar)

    def on_inspector_details_scroll(self, first, last):
        self.update_inspector_details_scrollbar()

    def update_inspector_details_scrollbar(self):
        first, last = self.inspector_details_text.yview()
        has_overflow = float(first) > 0.0 or float(last) < 1.0

        if has_overflow and not self.inspector_details_scroll.winfo_ismapped():
            self.inspector_details_scroll.pack(side="right", fill="y")
        elif not has_overflow and self.inspector_details_scroll.winfo_ismapped():
            self.inspector_details_scroll.pack_forget()

        self.inspector_details_scroll.set(first, last)

    def on_inspector_details_wheel(self, event):
        first, last = self.inspector_details_text.yview()
        if float(first) <= 0.0 and float(last) >= 1.0:
            return "break"

        step = int(-1 * (event.delta / 120))
        self.inspector_details_text.yview_scroll(step, "units")
        return "break"

    def copy_inspected_tile(self):
        if self.inspected_tile_xy is None:
            return

        x, y = self.inspected_tile_xy
        index = y * self.map_width + x
        tile_id = self.tiles[index]

        self.selected_tile_id = tile_id
        self.update_selected_tile_label()
        self.set_mode(MODE_PAINT)
        self.status.config(text=f"Copied tile type: {self.tile_name(tile_id)} | ID: {tile_id}")

    def update_selected_tile_label(self):
        self.selected_tile_label.config(
            text=f"Selected: {self.tile_name(self.selected_tile_id)} | ID: {self.selected_tile_id}"
        )

    def tile_color(self, tile_id):
        if tile_id in self.tile_defs:
            return self.tile_defs[tile_id].get("color", "black")

        n = int(tile_id) if tile_id.isdigit() else 0
        return f"#{(n * 53) % 255:02x}{(n * 97) % 255:02x}{(n * 193) % 255:02x}"

    def tile_name(self, tile_id):
        if tile_id in self.tile_defs:
            return self.tile_defs[tile_id].get("name", f"Tile {tile_id}")
        return f"Unknown ({tile_id})"

    def has_map_loaded(self):
        return self.image is not None

    def show_empty_view(self):
        self.canvas.delete("all")
        self.empty_view_window_id = None
        self.viewport_image_id = None
        self.hover_rect = None
        self.highlight_rect = None
        self.object_marker_ids = []
        self.hover_object_outline = None
        self.highlight_object_outline = None
        self.grid_lines = []

        if self.empty_view_button is None:
            self.empty_view_button = tk.Button(
                self.canvas,
                text="Load Map",
                command=self.load_map_dialog,
                width=18,
                height=2
            )
            self.apply_theme_to_widget(self.empty_view_button, self.theme())

        x = self.canvas_width() // 2
        y = self.canvas_height() // 2

        if self.empty_view_window_id is None:
            self.empty_view_window_id = self.canvas.create_window(
                x,
                y,
                window=self.empty_view_button
            )
        else:
            self.canvas.coords(self.empty_view_window_id, x, y)

        self.update_scrollbars()
        self.status.config(text="No map loaded.")

    def clear_empty_view(self):
        if self.empty_view_window_id is not None:
            self.canvas.delete(self.empty_view_window_id)
            self.empty_view_window_id = None

        if self.empty_view_button is not None:
            self.empty_view_button.destroy()
            self.empty_view_button = None

    def draw_map(self):
        tile_rgb_cache = {}
        pixel_data = []

        for tile_id in self.tiles:
            if tile_id not in tile_rgb_cache:
                color = self.tile_color(tile_id)
                tile_rgb_cache[tile_id] = self.to_rgb(color)

            pixel_data.append(tile_rgb_cache[tile_id])

        self.image = Image.new("RGB", (self.map_width, self.map_height))
        self.image.putdata(pixel_data)

        self.clear_empty_view()
        self.canvas.delete("all")
        self.viewport_image_id = None
        self.hover_rect = None
        self.highlight_rect = None
        self.object_marker_ids = []
        self.hover_object_outline = None
        self.highlight_object_outline = None
        self.grid_lines = []

        self.clamp_view()
        self.redraw_viewport()
        self.status.config(text="Loaded map.")

    def load_map_dialog(self):
        file_path = filedialog.askopenfilename(
            title="Load Horsey TMX Map",
            filetypes=[("TMX files", "*.tmx"), ("All files", "*.*")]
        )

        if not file_path:
            return

        try:
            loaded_file = Path(file_path)
            content, original_csv, tiles, map_width, map_height, map_objects = load_tmx(loaded_file)

            self.current_file = loaded_file
            self.output_file = loaded_file.with_name(f"{loaded_file.stem}_edited.tmx")
            self.content = content
            self.original_csv = original_csv
            self.tiles = tiles
            self.map_objects = map_objects
            self.map_width = map_width
            self.map_height = map_height

            self.view_x = 0
            self.view_y = 0
            self.hover_tile_xy = None
            self.highlight_tile_xy = None
            self.hover_object = None
            self.highlight_object = None
            self.inspected_tile_xy = None
            self.inspected_object = None
            self.selected_object_template = None
            self.last_mouse_x = None
            self.last_mouse_y = None
            self.undo_stack = []
            self.current_action = None
            self.is_painting = False
            existing_object_ids = [
                int(obj.get("id", 0))
                for obj in self.map_objects
                if str(obj.get("id", "")).isdigit()
            ]
            self.next_object_id = max(existing_object_ids, default=0) + 1

            self.draw_map()
            self.populate_tile_selector()
            self.build_object_templates()
            self.populate_object_selector()
            self.update_selected_tile_label()
            self.update_selected_object_label()
            self.update_inspector_panel()
            self.file_label.config(text=f"Map: {self.current_file.name}")
            self.status.config(text=f"Loaded map: {self.current_file.name}")
        except Exception as exc:
            messagebox.showerror("Load Failed", str(exc))

    def save_as_dialog(self):
        if not self.has_map_loaded():
            messagebox.showwarning("No Map Loaded", "Load a map before saving.")
            return

        file_path = filedialog.asksaveasfilename(
            title="Save Horsey TMX As",
            defaultextension=".tmx",
            filetypes=[("TMX files", "*.tmx"), ("All files", "*.*")]
        )

        if not file_path:
            return

        self.output_file = Path(file_path)
        self.save()

    def build_current_map_content(self):
        if not self.has_map_loaded():
            raise ValueError("No map is loaded.")

        new_lines = []
        for row in range(0, len(self.tiles), self.map_width):
            new_lines.append(",".join(self.tiles[row:row + self.map_width]))

        new_csv = "\n".join(new_lines)
        content = self.content.replace(self.original_csv, new_csv)
        content = self.build_current_object_content(content)
        return self.update_next_object_id(content)

    def build_current_object_content(self, content):
        object_group_pattern = r'(<objectgroup\b[^>]*name="Locs"[^>]*>\s*)(.*?)(\s*</objectgroup>)'
        object_group_match = re.search(object_group_pattern, content, re.DOTALL)

        if not object_group_match:
            return content

        object_lines = [self.serialize_map_object(obj) for obj in self.map_objects]
        new_objects = "\n".join(object_lines)
        return (
            content[:object_group_match.start(2)]
            + new_objects
            + content[object_group_match.end(2):]
        )

    def update_next_object_id(self, content):
        next_object_id = self.next_object_id

        for obj in self.map_objects:
            object_id = obj.get("id", "")
            if str(object_id).isdigit():
                next_object_id = max(next_object_id, int(object_id) + 1)

        return re.sub(
            r'nextobjectid="\d+"',
            f'nextobjectid="{next_object_id}"',
            content,
            count=1
        )

    def serialize_map_object(self, obj):
        attrs = [
            f'id="{self.xml_escape(obj.get("id", ""))}"',
        ]

        object_type = obj.get("type", "")
        if object_type != "":
            attrs.append(f'type="{self.xml_escape(object_type)}"')

        attrs.extend([
            f'gid="{self.xml_escape(obj.get("gid", ""))}"',
            f'x="{self.format_tmx_number(obj.get("x", 0))}"',
            f'y="{self.format_tmx_number(obj.get("y", 0))}"',
            f'width="{self.format_tmx_number(obj.get("width", 32))}"',
            f'height="{self.format_tmx_number(obj.get("height", 32))}"',
        ])

        properties = obj.get("properties", {})

        if not properties:
            return f'  <object {" ".join(attrs)}/>'

        property_lines = []
        for name, prop in properties.items():
            prop_attrs = [f'name="{self.xml_escape(name)}"']
            prop_type = prop.get("type", "")

            if prop_type:
                prop_attrs.append(f'type="{self.xml_escape(prop_type)}"')

            prop_attrs.append(f'value="{self.xml_escape(prop.get("value", ""))}"')
            property_lines.append(f'    <property {" ".join(prop_attrs)}/>')

        return (
            f'  <object {" ".join(attrs)}>\n'
            "   <properties>\n"
            + "\n".join(property_lines)
            + "\n   </properties>\n"
            "  </object>"
        )

    def format_tmx_number(self, value):
        value = float(value)
        if value.is_integer():
            return str(int(value))
        return str(value)

    def xml_escape(self, value):
        return (
            str(value)
            .replace("&", "&amp;")
            .replace('"', "&quot;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )

    def save(self):
        if not self.has_map_loaded() or self.current_file is None or self.output_file is None:
            messagebox.showwarning("No Map Loaded", "Load a map before saving.")
            return

        if not self.confirm_save_with_locs_rule_failures():
            self.status.config(text="Save cancelled. Locs object rules failed.")
            return

        BACKUP_DIR.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = BACKUP_DIR / f"{self.current_file.stem}_backup_{timestamp}.tmx"
        shutil.copy2(self.current_file, backup_path)

        self.output_file.write_text(self.build_current_map_content(), encoding="utf-8")

        messagebox.showinfo(
            "Saved",
            f"Saved {self.output_file}\nBackup created:\n{backup_path}"
        )

    def to_rgb(self, color):
        if color not in self.color_cache:
            self.color_cache[color] = ImageColor.getrgb(color)
        return self.color_cache[color]

    def canvas_width(self):
        return max(1, self.canvas.winfo_width())

    def canvas_height(self):
        return max(1, self.canvas.winfo_height())

    def scaled_map_width(self):
        return self.map_width * self.tile_size

    def scaled_map_height(self):
        return self.map_height * self.tile_size

    def clamp_view(self):
        max_x = max(0, self.scaled_map_width() - self.canvas_width())
        max_y = max(0, self.scaled_map_height() - self.canvas_height())

        self.view_x = max(0, min(self.view_x, max_x))
        self.view_y = max(0, min(self.view_y, max_y))

    def update_scrollbars(self):
        total_w = self.scaled_map_width()
        total_h = self.scaled_map_height()
        canvas_w = self.canvas_width()
        canvas_h = self.canvas_height()

        if total_w <= canvas_w:
            self.h_scroll.set(0, 1)
        else:
            self.h_scroll.set(self.view_x / total_w, min(1, (self.view_x + canvas_w) / total_w))

        if total_h <= canvas_h:
            self.v_scroll.set(0, 1)
        else:
            self.v_scroll.set(self.view_y / total_h, min(1, (self.view_y + canvas_h) / total_h))

    def on_h_scrollbar(self, command, value, units=None):
        self.handle_scrollbar("x", command, value, units)

    def on_v_scrollbar(self, command, value, units=None):
        self.handle_scrollbar("y", command, value, units)

    def handle_scrollbar(self, axis, command, value, units=None):
        # Prevent hover highlight from reappearing when interacting with scrollbars
        self.last_mouse_x = None
        self.last_mouse_y = None
        self.hover_tile_xy = None
        if command == "moveto":
            fraction = float(value)
            if axis == "x":
                self.view_x = fraction * self.scaled_map_width()
            else:
                self.view_y = fraction * self.scaled_map_height()
        elif command == "scroll":
            amount = int(value)

            # clamp scrollbar scroll bursts
            amount = max(-3, min(3, amount))

            unit_px = self.tile_size * 2
            if units == "pages":
                unit_px = self.canvas_width() if axis == "x" else self.canvas_height()

            if axis == "x":
                self.view_x += amount * unit_px
            else:
                self.view_y += amount * unit_px

        self.clamp_view()
        self.redraw_viewport()

    def on_mouse_wheel(self, event):
        step = max(-3, min(3, int(-1 * (event.delta / 120))))
        self.view_y += step * self.tile_size * 2

        self.clamp_view()
        self.update_hover_from_position(event.x, event.y)
        self.schedule_scroll_redraw()
        return "break"

    def on_shift_wheel(self, event):
        step = max(-3, min(3, int(-1 * (event.delta / 120))))
        self.view_x += step * self.tile_size * 2

        self.clamp_view()
        self.update_hover_from_position(event.x, event.y)
        self.schedule_scroll_redraw()
        return "break"

    def schedule_scroll_redraw(self):
        if self.scroll_redraw_pending:
            return

        self.scroll_redraw_pending = True
        self.root.after_idle(self.flush_scroll_redraw)

    def flush_scroll_redraw(self):
        self.scroll_redraw_pending = False
        self.redraw_viewport()

    def schedule_paint_redraw(self):
        if self.paint_redraw_pending:
            return

        self.paint_redraw_pending = True
        self.root.after_idle(self.flush_paint_redraw)

    def flush_paint_redraw(self):
        self.paint_redraw_pending = False
        self.redraw_viewport()

    def on_canvas_resize(self, event=None):
        if self.image is None:
            self.show_empty_view()
            return
        self.clamp_view()
        self.redraw_viewport()

    def on_ctrl_scroll(self, event):
        if not self.has_map_loaded():
            return "break"

        now = time.monotonic()

        if now - self.last_zoom_time < self.zoom_cooldown:
            return

        if event.delta > 0:
            new_zoom_index = min(self.zoom_index + 1, len(self.zoom_levels) - 1)
        else:
            new_zoom_index = max(self.zoom_index - 1, 0)

        if new_zoom_index == self.zoom_index:
            return

        old_tile_size = self.tile_size
        mouse_tile_x = (self.view_x + event.x) / old_tile_size
        mouse_tile_y = (self.view_y + event.y) / old_tile_size

        self.last_zoom_time = now
        self.zoom_index = new_zoom_index
        self.tile_size = self.zoom_levels[self.zoom_index]

        self.view_x = mouse_tile_x * self.tile_size - event.x
        self.view_y = mouse_tile_y * self.tile_size - event.y

        self.clamp_view()
        self.redraw_viewport()

    def get_tile_xy_from_event(self, event):
        return self.get_tile_xy_from_position(event.x, event.y)

    def get_object_from_tile_xy(self, x, y):
        if x is None or y is None or not self.show_locs.get():
            return None

        for obj in reversed(self.map_objects):
            if obj.get("tile_x") == x and obj.get("tile_y") == y:
                return obj

        return None

    def object_label(self, obj):
        object_type = obj.get("type") or "(blank)"
        return f"{object_type} | ID: {obj.get('id')} | GID: {obj.get('gid')}"

    def get_tile_xy_from_position(self, canvas_x, canvas_y):
        if not self.has_map_loaded():
            return None, None

        if canvas_x < 0 or canvas_y < 0 or canvas_x >= self.canvas_width() or canvas_y >= self.canvas_height():
            return None, None

        world_x = self.view_x + canvas_x
        world_y = self.view_y + canvas_y

        x = int(world_x // self.tile_size)
        y = int(world_y // self.tile_size)

        if x < 0 or y < 0 or x >= self.map_width or y >= self.map_height:
            return None, None

        return x, y

    def on_mouse_move(self, event):
        self.last_mouse_x = event.x
        self.last_mouse_y = event.y
        self.update_hover_from_position(event.x, event.y)
        self.redraw_overlays()

    def on_mouse_leave(self, event):
        self.hover_tile_xy = None
        self.hover_object = None
        if self.hover_rect is not None:
            self.canvas.delete(self.hover_rect)
            self.hover_rect = None
        self.redraw_overlays()
        if not self.has_map_loaded():
            self.status.config(text="No map loaded.")
            return
        self.status.config(text="Outside map.")

    def update_hover_from_position(self, canvas_x, canvas_y):
        if not self.has_map_loaded():
            self.hover_tile_xy = None
            self.status.config(text="No map loaded.")
            return

        x, y = self.get_tile_xy_from_position(canvas_x, canvas_y)

        if x is None:
            self.hover_tile_xy = None
            self.hover_object = None
            self.status.config(text="Outside map.")
        else:
            self.hover_tile_xy = (x, y)
            self.hover_object = self.get_object_from_tile_xy(x, y)
            index = y * self.map_width + x
            tile_id = self.tiles[index]
            if self.hover_object is not None:
                self.status.config(text=f"({x}, {y}) | Locs: {self.object_label(self.hover_object)}")
            else:
                self.status.config(text=f"({x}, {y}) | {self.tile_name(tile_id)}")

    def highlight_tile(self, event):
        x, y = self.get_tile_xy_from_event(event)

        if x is None:
            return

        obj = self.get_object_from_tile_xy(x, y)
        self.highlight_object = obj
        self.inspected_object = obj
        self.highlight_tile_xy = (x, y)
        self.inspected_tile_xy = None if obj is not None else (x, y)
        index = y * self.map_width + x
        tile_id = self.tiles[index]

        if obj is not None:
            self.status.config(text=f"Selected Locs object ({x}, {y}) | {self.object_label(obj)}")
        else:
            self.status.config(text=f"Selected ({x}, {y}) | {self.tile_name(tile_id)}")
        self.update_inspector_panel()
        self.redraw_overlays()

    def clear_highlight(self, event=None):
        self.highlight_tile_xy = None
        self.hover_object = None
        self.highlight_object = None
        self.inspected_tile_xy = None
        self.inspected_object = None
        self.update_inspector_panel()
        if self.has_map_loaded():
            self.status.config(text="Highlight cleared.")
        else:
            self.status.config(text="No map loaded.")
        self.redraw_overlays()

    def begin_action(self, description):
        self.current_action = {
            "description": description,
            "changes": {}
        }

    def commit_action(self):
        if self.current_action and self.current_action["changes"]:
            self.undo_stack.append(self.current_action)
            self.status.config(text=f"{self.current_action['description']} action recorded.")

        self.current_action = None

    def undo(self, event=None):
        if not self.undo_stack:
            self.status.config(text="Nothing to undo.")
            return "break"

        action = self.undo_stack.pop()

        for index, change in action["changes"].items():
            old_tile = change["old"]
            self.tiles[index] = old_tile
            x = index % self.map_width
            y = index // self.map_width
            self.image.putpixel((x, y), self.to_rgb(self.tile_color(old_tile)))

        self.status.config(text=f"Undid: {action['description']}")
        self.redraw_viewport()
        return "break"

    def place_selected_object(self, event):
        if self.selected_object_template is None:
            self.status.config(text="No object selected.")
            return

        x, y = self.get_tile_xy_from_event(event)

        if x is None:
            return

        template = self.selected_object_template
        object_name = self.object_display_name(template)

        if not self.template_is_repeatable(template) and self.object_template_is_placed(template):
            self.status.config(text=f"{object_name} is already placed!")
            return

        new_object = {
            "id": self.next_available_object_id(),
            "type": template.get("type", ""),
            "gid": template.get("gid", ""),
            "x": float(x * 32),
            "y": float(y * 32),
            "width": float(template.get("width", 32.0)),
            "height": float(template.get("height", 32.0)),
            "tile_x": x,
            "tile_y": y,
            "properties": self.copy_object_properties(template.get("properties", {})),
        }

        self.map_objects.append(new_object)
        self.highlight_object = new_object
        self.inspected_object = new_object
        self.highlight_tile_xy = (x, y)
        self.inspected_tile_xy = None
        self.status.config(text=f"Placed {object_name} at ({x}, {y}).")
        self.populate_object_selector()
        self.update_object_selector_selection()
        self.update_inspector_panel()
        self.redraw_viewport()

    def remove_hovered_object(self, event):
        x, y = self.get_tile_xy_from_event(event)
        obj = self.hover_object or self.get_object_from_tile_xy(x, y)

        if obj is None:
            self.status.config(text="No object under cursor.")
            return

        object_name = self.object_display_name(obj)
        self.map_objects.remove(obj)

        if self.highlight_object is obj:
            self.highlight_object = None
            self.inspected_object = None
            self.highlight_tile_xy = None

        if self.hover_object is obj:
            self.hover_object = None

        self.status.config(text=f"Removed {object_name}.")
        self.populate_object_selector()
        self.update_object_selector_selection()
        self.update_inspector_panel()
        self.redraw_viewport()

    def paint_tile(self, event):
        if not self.has_map_loaded():
            return

        x, y = self.get_tile_xy_from_event(event)

        if x is None:
            return

        index = y * self.map_width + x
        old = self.tiles[index]

        if old == self.selected_tile_id:
            return

        if self.current_action is None:
            self.begin_action("Paint")
            single_step_action = True
        else:
            single_step_action = False

        if index not in self.current_action["changes"]:
            self.current_action["changes"][index] = {
                "old": old,
                "new": self.selected_tile_id
            }
        else:
            self.current_action["changes"][index]["new"] = self.selected_tile_id

        self.tiles[index] = self.selected_tile_id
        self.image.putpixel((x, y), self.to_rgb(self.tile_color(self.selected_tile_id)))

        self.status.config(text=f"({x}, {y}) | {self.tile_name(old)} -> {self.tile_name(self.selected_tile_id)}")
        self.schedule_paint_redraw()

        if single_step_action:
            self.commit_action()

    def redraw_viewport(self):
        if self.image is None:
            return

        canvas_w = self.canvas_width()
        canvas_h = self.canvas_height()

        tile_x1 = max(0, int(self.view_x // self.tile_size))
        tile_y1 = max(0, int(self.view_y // self.tile_size))
        tile_x2 = min(self.map_width, int((self.view_x + canvas_w) // self.tile_size) + 2)
        tile_y2 = min(self.map_height, int((self.view_y + canvas_h) // self.tile_size) + 2)

        if tile_x2 <= tile_x1 or tile_y2 <= tile_y1:
            return

        crop = self.image.crop((tile_x1, tile_y1, tile_x2, tile_y2))

        scaled_w = (tile_x2 - tile_x1) * self.tile_size
        scaled_h = (tile_y2 - tile_y1) * self.tile_size
        display = crop.resize((scaled_w, scaled_h), Image.NEAREST)

        offset_x = -int(self.view_x - tile_x1 * self.tile_size)
        offset_y = -int(self.view_y - tile_y1 * self.tile_size)

        self.tk_image = ImageTk.PhotoImage(display)

        if self.viewport_image_id is None:
            self.viewport_image_id = self.canvas.create_image(offset_x, offset_y, anchor="nw", image=self.tk_image)
        else:
            self.canvas.coords(self.viewport_image_id, offset_x, offset_y)
            self.canvas.itemconfig(self.viewport_image_id, image=self.tk_image)

        self.canvas.tag_lower(self.viewport_image_id)
        self.draw_grid(tile_x1, tile_y1, tile_x2, tile_y2)
        self.draw_locs_layer(tile_x1, tile_y1, tile_x2, tile_y2)
        self.redraw_overlays()
        self.update_scrollbars()

    def toggle_grid(self):
        self.redraw_viewport()

    def draw_grid(self, tile_x1, tile_y1, tile_x2, tile_y2):
        self.canvas.delete("grid")
        self.grid_lines = []

        if hasattr(self, 'show_grid') and not self.show_grid.get():
            return

        if self.tile_size < 6:
            return

        grid_color = "#222222" if not self.settings.get("dark_mode", False) else "#4a4a4a"

        for x in range(tile_x1, tile_x2 + 1):
            screen_x = x * self.tile_size - self.view_x
            self.grid_lines.append(
                self.canvas.create_line(screen_x, 0, screen_x, self.canvas_height(), fill=grid_color, width=1, tags="grid")
            )

        for y in range(tile_y1, tile_y2 + 1):
            screen_y = y * self.tile_size - self.view_y
            self.grid_lines.append(
                self.canvas.create_line(0, screen_y, self.canvas_width(), screen_y, fill=grid_color, width=1, tags="grid")
            )

    def draw_locs_layer(self, tile_x1, tile_y1, tile_x2, tile_y2):
        self.canvas.delete("locs")
        self.object_marker_ids = []

        if not self.show_locs.get():
            return

        for obj in self.map_objects:
            x = obj.get("tile_x")
            y = obj.get("tile_y")

            if x is None or y is None or x < tile_x1 or x >= tile_x2 or y < tile_y1 or y >= tile_y2:
                continue

            self.object_marker_ids.extend(self.draw_object_marker(obj))

    def draw_object_marker(self, obj):
        x = obj.get("tile_x", 0)
        y = obj.get("tile_y", 0)
        x1 = x * self.tile_size - self.view_x
        y1 = y * self.tile_size - self.view_y
        x2 = x1 + self.tile_size
        y2 = y1 + self.tile_size
        inset = max(1, self.tile_size * 0.18)
        fill = "#2f7dff"
        outline = "#ffffff"

        ids = [
            self.canvas.create_rectangle(
                x1 + inset,
                y1 + inset,
                x2 - inset,
                y2 - inset,
                fill=fill,
                outline=outline,
                width=1,
                tags="locs"
            )
        ]

        if self.tile_size >= 14:
            label = (obj.get("type") or "?").strip()[:1].upper() or "?"
            ids.append(
                self.canvas.create_text(
                    (x1 + x2) / 2,
                    (y1 + y2) / 2,
                    text=label,
                    fill="#ffffff",
                    font=("TkDefaultFont", max(6, int(self.tile_size * 0.45)), "bold"),
                    tags="locs"
                )
            )

        return ids

    def redraw_overlays(self):
        if self.hover_rect is not None:
            self.canvas.delete(self.hover_rect)
            self.hover_rect = None

        if self.highlight_rect is not None:
            self.canvas.delete(self.highlight_rect)
            self.highlight_rect = None

        if self.hover_object_outline is not None:
            self.canvas.delete(self.hover_object_outline)
            self.hover_object_outline = None

        for label_id in self.hover_object_label_ids:
            self.canvas.delete(label_id)
        self.hover_object_label_ids = []

        if self.highlight_object_outline is not None:
            self.canvas.delete(self.highlight_object_outline)
            self.highlight_object_outline = None

        if self.highlight_tile_xy is not None:
            self.highlight_rect = self.draw_tile_outline(*self.highlight_tile_xy, color="yellow", width=3)

        if self.highlight_object is not None and self.show_locs.get():
            self.highlight_object_outline = self.draw_object_outline(self.highlight_object, color="#00ffcc", width=3)

        if self.hover_tile_xy is not None:
            self.hover_rect = self.draw_tile_outline(*self.hover_tile_xy, color="white", width=2)

        if self.hover_object is not None and self.show_locs.get():
            self.hover_object_outline = self.draw_object_outline(self.hover_object, color="#66ccff", width=2)
            if self.editor_mode != MODE_PAINT:
                self.hover_object_label_ids = self.draw_object_hover_label(self.hover_object)

    def draw_tile_outline(self, x, y, color="yellow", width=2):
        x1 = x * self.tile_size - self.view_x
        y1 = y * self.tile_size - self.view_y
        x2 = x1 + self.tile_size
        y2 = y1 + self.tile_size

        return self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=width)

    def draw_object_outline(self, obj, color="#00ffcc", width=2):
        return self.draw_tile_outline(obj.get("tile_x", 0), obj.get("tile_y", 0), color=color, width=width)

    def draw_object_hover_label(self, obj):
        object_name = self.object_display_name(obj)
        x = obj.get("tile_x", 0)
        y = obj.get("tile_y", 0)
        center_x = x * self.tile_size - self.view_x + self.tile_size / 2
        label_y = y * self.tile_size - self.view_y - 10

        if label_y < 12:
            label_y = (y + 1) * self.tile_size - self.view_y + 12

        text_id = self.canvas.create_text(
            center_x,
            label_y,
            text=object_name,
            fill="#ffffff",
            font=("TkDefaultFont", 9, "bold"),
            tags="object_hover_label"
        )
        bbox = self.canvas.bbox(text_id)

        if bbox is None:
            return [text_id]

        pad_x = 5
        pad_y = 3
        rect_id = self.canvas.create_rectangle(
            bbox[0] - pad_x,
            bbox[1] - pad_y,
            bbox[2] + pad_x,
            bbox[3] + pad_y,
            fill="#111111",
            outline="#66ccff",
            width=1,
            tags="object_hover_label"
        )
        self.canvas.tag_raise(text_id, rect_id)
        return [rect_id, text_id]


if __name__ == "__main__":
    root = tk.Tk()
    app = HorseyMapEditor(root)
    root.mainloop()

