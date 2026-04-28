import json
import re
import shutil
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

from PIL import Image, ImageColor, ImageTk

TMX_FILE = Path("test_horsey.tmx")
OUTPUT_FILE = Path("output_horsey.tmx")
BACKUP_DIR = Path("backups")
TILE_DEFS_FILE = Path("tile_defs.json")
SETTINGS_FILE = Path("editor_settings.json")

PAINT_TILE_ID = "1"
MODE_INSPECT = "inspect"
MODE_PAINT = "paint"


def load_tile_defs():
    if not TILE_DEFS_FILE.exists():
        return {}

    with open(TILE_DEFS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def load_settings():
    if not SETTINGS_FILE.exists():
        return {"install_location": ""}

    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            settings = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"install_location": ""}

    settings.setdefault("install_location", "")
    return settings


def save_settings(settings):
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)


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

    return content, csv_data, tiles, width, height


class HorseyMapEditor:
    def __init__(self, root):
        self.root = root
        self.root.title("Horsey Map Editor - Prototype")

        self.tile_defs = load_tile_defs()
        self.settings = load_settings()
        self.color_cache = {}
        self.selected_tile_id = PAINT_TILE_ID
        self.editor_mode = MODE_INSPECT
        self.tile_buttons = {}
        self.inspected_tile_xy = None

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

        self.hover_tile_xy = None
        self.highlight_tile_xy = None
        self.last_mouse_x = None
        self.last_mouse_y = None

        self.undo_stack = []
        self.current_action = None
        self.is_painting = False
        self.hover_rect = None
        self.highlight_rect = None
        self.grid_lines = []

        self.current_file = TMX_FILE
        self.output_file = OUTPUT_FILE
        self.content, self.original_csv, self.tiles, self.map_width, self.map_height = load_tmx(self.current_file)

        self.toolbar = tk.Frame(root, relief="raised", bd=1)
        self.toolbar.pack(side="top", fill="x")

        self.editor_button = tk.Menubutton(self.toolbar, text="Editor", relief="flat")
        self.editor_menu = tk.Menu(self.editor_button, tearoff=0)
        self.editor_menu.add_command(label="Load Map...", command=self.load_map_dialog)
        self.editor_menu.add_command(label="Save As...", command=self.save_as_dialog)
        self.editor_menu.add_separator()
        self.editor_menu.add_command(label="Export Map to Game", command=self.export_map_to_game)
        self.editor_menu.add_command(label="Restore Original Map TMX", command=self.restore_original_map_tmx)
        self.editor_button.config(menu=self.editor_menu)
        self.editor_button.pack(side="left", padx=4, pady=2)

        self.view_button = tk.Menubutton(self.toolbar, text="View", relief="flat")
        self.view_menu = tk.Menu(self.view_button, tearoff=0)
        self.show_grid = tk.BooleanVar(value=True)
        self.view_menu.add_checkbutton(label="Grid Lines", variable=self.show_grid, command=self.toggle_grid)
        self.view_button.config(menu=self.view_menu)
        self.view_button.pack(side="left", padx=4, pady=2)

        self.settings_button = tk.Menubutton(self.toolbar, text="Settings", relief="flat")
        self.settings_menu = tk.Menu(self.settings_button, tearoff=0)
        self.settings_menu.add_command(label="Editor Settings...", command=self.open_settings_window)
        self.settings_button.config(menu=self.settings_menu)
        self.settings_button.pack(side="left", padx=4, pady=2)

        self.help_button = tk.Menubutton(self.toolbar, text="Help", relief="flat")
        self.help_menu = tk.Menu(self.help_button, tearoff=0)
        self.help_menu.add_command(label="Show Controls", command=self.show_controls_dialog)
        self.help_button.config(menu=self.help_menu)
        self.help_button.pack(side="left", padx=4, pady=2)

        # DEBUG menu (temporary)
        self.debug_button = tk.Menubutton(self.toolbar, text="DEBUG", relief="flat")
        self.debug_menu = tk.Menu(self.debug_button, tearoff=0)
        self.debug_menu.add_command(label="Clear Install Location", command=self.debug_clear_install_location)
        self.debug_button.config(menu=self.debug_menu)
        self.debug_button.pack(side="left", padx=4, pady=2)

        self.main_area = tk.Frame(root)
        self.main_area.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(self.main_area, width=240, relief="groove", bd=1)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        self.tools_panel = tk.Frame(self.sidebar)
        self.tools_panel.pack(side="top", fill="both", expand=True)

        self.sidebar_title = tk.Label(self.tools_panel, text="Tools", anchor="w", font=("TkDefaultFont", 10, "bold"))
        self.sidebar_title.pack(fill="x", padx=8, pady=(8, 4))

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

        

        self.inspector_panel = tk.Frame(self.sidebar, height=120, relief="groove", bd=1, bg="white")
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

        self.inspector_details_label = tk.Label(
            self.inspector_panel,
            text="No Coordinate Selected",
            anchor="nw",
            justify="left",
            wraplength=220,
            bg="white"
        )
        self.inspector_details_label.pack(fill="x", padx=8, pady=(0, 4))

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
        self.tile_list_scroll = tk.Scrollbar(self.tile_list_container, orient="vertical", command=self.tile_list_canvas.yview)
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

        self.frame = tk.Frame(self.main_area)
        self.frame.pack(side="left", fill="both", expand=True)

        self.canvas = tk.Canvas(
            self.frame,
            width=1000,
            height=700,
            bg="black",
            highlightthickness=0
        )

        self.h_scroll = tk.Scrollbar(self.frame, orient="horizontal", command=self.on_h_scrollbar)
        self.v_scroll = tk.Scrollbar(self.frame, orient="vertical", command=self.on_v_scrollbar)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.v_scroll.grid(row=0, column=1, sticky="ns")
        self.h_scroll.grid(row=1, column=0, sticky="ew")

        self.frame.rowconfigure(0, weight=1)
        self.frame.columnconfigure(0, weight=1)

        self.bottom_bar = tk.Frame(root, relief="sunken", bd=1)
        self.bottom_bar.pack(side="bottom", fill="x")

        self.file_label = tk.Label(self.bottom_bar, text=f"Map: {self.current_file.name}", anchor="w")
        self.file_label.pack(side="left", padx=6)

        self.status = tk.Label(self.bottom_bar, text="Loaded map.", anchor="e")
        self.status.pack(side="right", fill="x", expand=True, padx=6)


        self.canvas.bind("<ButtonPress-1>", self.on_left_press)
        self.canvas.bind("<B1-Motion>", self.on_left_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<Button-3>", self.clear_highlight)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)
        self.canvas.bind("<Shift-MouseWheel>", self.on_shift_wheel)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<Leave>", self.on_mouse_leave)
        self.canvas.bind("<Control-MouseWheel>", self.on_ctrl_scroll)
        self.canvas.bind("<Configure>", self.on_canvas_resize)
        self.root.bind("<Control-z>", self.undo)

        self.populate_tile_selector()
        self.update_selected_tile_label()

        self.status.config(text="Loading map image...")
        self.root.after(100, self.draw_map)
        self.root.after(250, self.ensure_valid_install_location)

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
            "- Editor Settings...: Set the Horsey Game install location\n\n"
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

        def browse_location():
            selected = filedialog.askdirectory(title="Select Folder Containing Horsey.exe")
            if selected:
                location_var.set(selected)

        def save_location():
            install_path = Path(location_var.get().strip())
            horsey_exe = install_path / "Horsey.exe"

            if not install_path.exists() or not install_path.is_dir():
                messagebox.showerror("Invalid Install Location", "That folder does not exist.")
                return

            if not horsey_exe.exists() or not horsey_exe.is_file():
                messagebox.showerror(
                    "Horsey.exe Not Found",
                    f"Could not find Horsey.exe in:\n{install_path}"
                )
                return

            self.settings["install_location"] = str(install_path)
            save_settings(self.settings)

            try:
                self.create_official_map_backup(overwrite=False)
            except Exception as exc:
                messagebox.showerror("Backup Failed", str(exc))
                return

            settings_window.destroy()
            messagebox.showinfo(
                "Install Location Valid",
                "Install Location was valid.\n\n"
                "A backup of /data/horsey.tmx has been created.\n\n"
                "You are ready to start making maps."
            )
            self.status.config(text="Install location valid. Official map backup ready.")

        button_row = tk.Frame(settings_window)
        button_row.pack(fill="x", padx=10, pady=(0, 10))

        tk.Button(button_row, text="Browse...", command=browse_location).pack(side="left")
        tk.Button(button_row, text="Save", command=save_location).pack(side="right", padx=(4, 0))
        tk.Button(button_row, text="Cancel", command=settings_window.destroy).pack(side="right")

        self.center_window(settings_window)

    def has_valid_install_location(self):
        install_location = self.settings.get("install_location", "").strip()
        if not install_location:
            return False

        install_path = Path(install_location)
        return install_path.is_dir() and (install_path / "Horsey.exe").is_file()

    def ensure_valid_install_location(self):
        if not self.has_valid_install_location():
            self.open_settings_window("No Install Location Set. Please define the path to Horsey.exe")

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

    def debug_clear_install_location(self):
        self.settings["install_location"] = ""
        save_settings(self.settings)
        messagebox.showinfo("DEBUG", "Install location cleared. Restart or trigger validation to test.")
        self.status.config(text="DEBUG: Install location cleared.")

    def export_map_to_game(self):
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
        self.update_inspector_panel()
        self.status.config(text=f"Mode: {self.editor_mode.title()}")

    def set_mode(self, mode):
        self.editor_mode = mode
        self.mode_var.set(mode)
        self.update_tile_selector_selection()
        self.update_inspector_panel()
        self.status.config(text=f"Mode: {self.editor_mode.title()}")

    def on_left_press(self, event):
        if self.editor_mode == MODE_PAINT:
            self.is_painting = True
            self.begin_action("Paint")
            self.paint_tile(event)
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

    def on_tile_list_resize(self, event):
        self.tile_list_canvas.itemconfig(self.tile_list_window, width=event.width)

    def on_tile_selector_wheel(self, event):
        step = int(-1 * (event.delta / 120))
        self.tile_list_canvas.yview_scroll(step, "units")
        return "break"

    def populate_tile_selector(self):
        for child in self.tile_list_frame.winfo_children():
            child.destroy()

        self.tile_buttons = {}
        tile_ids = sorted(self.tile_defs.keys(), key=lambda value: int(value) if value.isdigit() else value)

        for tile_id in tile_ids:
            tile_name = self.tile_name(tile_id)
            tile_color = self.tile_color(tile_id)

            outer = tk.Frame(self.tile_list_frame, bg="white", height=30)
            outer.pack(fill="x", pady=1, padx=(1, 4))
            outer.pack_propagate(False)

            row = tk.Frame(outer, relief="ridge", bd=1, bg="#d9d9d9")
            row.pack(fill="both", expand=True, padx=2, pady=2)

            swatch = tk.Label(row, text="", bg=tile_color, width=3, height=1, relief="sunken", bd=1)
            swatch.pack(side="left", padx=4, pady=4)

            label = tk.Label(row, text=f"{tile_name} | ID: {tile_id}", anchor="w", justify="left", bg="#d9d9d9")
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

    def update_tile_selector_selection(self):
        for tile_id, widgets in self.tile_buttons.items():
            is_selected = self.editor_mode == MODE_PAINT and tile_id == self.selected_tile_id
            bg = "white" if is_selected else "#d9d9d9"

            outer, row, label = widgets
            row.config(bg=bg)
            label.config(bg=bg)

            # Resize the inner row inside a fixed-height outer frame instead of changing borders.
            # This gives a thicker-looking selection without pushing neighboring rows around.
            if is_selected:
                outer.config(bg="black")
                row.pack_configure(padx=1, pady=1)
            else:
                outer.config(bg="white")
                row.pack_configure(padx=2, pady=2)

    def update_inspector_panel(self):
        if self.inspected_tile_xy is None:
            self.inspector_details_label.config(text="No Coordinate Selected")
            self.copy_tile_button.pack_forget()
            return

        x, y = self.inspected_tile_xy
        index = y * self.map_width + x
        tile_id = self.tiles[index]

        self.inspector_details_label.config(
            text=(
                f"Coordinate: ({x}, {y})\n"
                f"Type: {self.tile_name(tile_id)}\n"
                f"ID: {tile_id}"
            )
        )

        if not self.copy_tile_button.winfo_ismapped():
            self.copy_tile_button.pack(fill="x", padx=8, pady=(0, 6))

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

        self.canvas.delete("all")
        self.viewport_image_id = None
        self.hover_rect = None
        self.highlight_rect = None
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
            self.current_file = Path(file_path)
            self.output_file = self.current_file.with_name(f"{self.current_file.stem}_edited.tmx")
            self.content, self.original_csv, self.tiles, self.map_width, self.map_height = load_tmx(self.current_file)

            self.view_x = 0
            self.view_y = 0
            self.hover_tile_xy = None
            self.highlight_tile_xy = None
            self.inspected_tile_xy = None
            self.last_mouse_x = None
            self.last_mouse_y = None

            self.draw_map()
            self.populate_tile_selector()
            self.update_selected_tile_label()
            self.update_inspector_panel()
            self.file_label.config(text=f"Map: {self.current_file.name}")
            self.status.config(text=f"Loaded map: {self.current_file.name}")
        except Exception as exc:
            messagebox.showerror("Load Failed", str(exc))

    def save_as_dialog(self):
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
        new_lines = []
        for row in range(0, len(self.tiles), self.map_width):
            new_lines.append(",".join(self.tiles[row:row + self.map_width]))

        new_csv = "\n".join(new_lines)
        return self.content.replace(self.original_csv, new_csv)

    def save(self):
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
            return
        self.clamp_view()
        self.redraw_viewport()

    def on_ctrl_scroll(self, event):
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

    def get_tile_xy_from_position(self, canvas_x, canvas_y):
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
        if self.hover_rect is not None:
            self.canvas.delete(self.hover_rect)
            self.hover_rect = None
        self.status.config(text="Outside map.")

    def update_hover_from_position(self, canvas_x, canvas_y):
        x, y = self.get_tile_xy_from_position(canvas_x, canvas_y)

        if x is None:
            self.hover_tile_xy = None
            self.status.config(text="Outside map.")
        else:
            self.hover_tile_xy = (x, y)
            index = y * self.map_width + x
            tile_id = self.tiles[index]
            self.status.config(text=f"({x}, {y}) | {self.tile_name(tile_id)}")

    def highlight_tile(self, event):
        x, y = self.get_tile_xy_from_event(event)

        if x is None:
            return

        self.highlight_tile_xy = (x, y)
        self.inspected_tile_xy = (x, y)
        index = y * self.map_width + x
        tile_id = self.tiles[index]

        self.status.config(text=f"Selected ({x}, {y}) | {self.tile_name(tile_id)}")
        self.update_inspector_panel()
        self.redraw_overlays()

    def clear_highlight(self, event=None):
        self.highlight_tile_xy = None
        self.inspected_tile_xy = None
        self.update_inspector_panel()
        self.status.config(text="Highlight cleared.")
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

    def paint_tile(self, event):
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

        self.status.config(text=f"({x}, {y}) | {self.tile_name(old)} → {self.tile_name(self.selected_tile_id)}")
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

        for x in range(tile_x1, tile_x2 + 1):
            screen_x = x * self.tile_size - self.view_x
            self.grid_lines.append(
                self.canvas.create_line(screen_x, 0, screen_x, self.canvas_height(), fill="#222222", width=1, tags="grid")
            )

        for y in range(tile_y1, tile_y2 + 1):
            screen_y = y * self.tile_size - self.view_y
            self.grid_lines.append(
                self.canvas.create_line(0, screen_y, self.canvas_width(), screen_y, fill="#222222", width=1, tags="grid")
            )

    def redraw_overlays(self):
        if self.hover_rect is not None:
            self.canvas.delete(self.hover_rect)
            self.hover_rect = None

        if self.highlight_rect is not None:
            self.canvas.delete(self.highlight_rect)
            self.highlight_rect = None

        if self.highlight_tile_xy is not None:
            self.highlight_rect = self.draw_tile_outline(*self.highlight_tile_xy, color="yellow", width=3)

        if self.hover_tile_xy is not None:
            self.hover_rect = self.draw_tile_outline(*self.hover_tile_xy, color="white", width=2)

    def draw_tile_outline(self, x, y, color="yellow", width=2):
        x1 = x * self.tile_size - self.view_x
        y1 = y * self.tile_size - self.view_y
        x2 = x1 + self.tile_size
        y2 = y1 + self.tile_size

        return self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=width)


if __name__ == "__main__":
    root = tk.Tk()
    app = HorseyMapEditor(root)
    root.mainloop()

