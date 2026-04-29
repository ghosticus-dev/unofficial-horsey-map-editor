# Unofficial Horsey Game Map Editor

**ALPHA 0.2.1 HOTFIX**

An unofficial TMX map editor for Horsey. The editor currently focuses on terrain painting and Locs object inspection/placement while preserving game-critical TMX object GIDs.

This is an early alpha modding tool. Keep backups of anything you care about.

[Download the latest release](https://github.com/ghosticus-dev/unofficial-horsey-map-editor/releases)

## Quick Install

1. Download the latest release from the Releases page.
2. Extract the release files to a folder.
3. Keep `tile_defs.json` in the same folder as the editor executable.
4. Run the editor.
5. On first launch, select the folder that contains `Horsey.exe`.

## Important Save Notes

Back up your Horsey save files before exporting edited maps.

New maps require a new game/save file. Horsey bakes map data into save data, so an existing save may not reflect newly exported map changes correctly.

## Current Features

- Load and save Horsey TMX maps.
- Paint terrain tiles from `tile_defs.json`.
- Inspect tile coordinates, tile IDs, and Locs objects.
- View Locs objects on a separate editor overlay.
- Select Locs object templates from the map and place/remove objects in Object Mode.
- Enforce map-readiness rules for required Locs GIDs before exporting.
- Preserve object GIDs when saving or exporting.
- Export the current map to the configured Horsey install folder.
- Restore the original game map from a preserved backup.
- Dark mode and light mode.

## Safety Notes

The game depends on TMX object GIDs. If object GIDs change, the game may fail to load or behave incorrectly.

The editor is designed to preserve object GIDs during save/export. It also blocks export if required Locs objects are missing, and warns when saving a map that is not game-ready.

On first setup, the editor asks for the Horsey game folder and creates a backup of the official map before exports are allowed.

## Requirements

- Windows
- Python 3
- Pillow
- Tkinter, included with most Python installs
- A local Horsey install folder containing `Horsey.exe`

Install Python dependencies:

```powershell
python -m pip install pillow
```

## Running From Source

From the repo folder:

```powershell
python .\horsey_map_editor.py
```

On first launch, select the folder that contains `Horsey.exe`. The editor will not continue until a valid game folder is selected.

## Basic Controls

- `Ctrl + Mouse Wheel`: Zoom
- `Mouse Wheel`: Scroll vertically
- `Shift + Mouse Wheel`: Scroll horizontally
- `Inspect Mode + Left Click`: Select/inspect a tile or Locs object
- `Paint Mode + Left Click/Drag`: Paint terrain
- `Object Mode + Left Click`: Place the selected object
- `Object Mode + Right Click`: Remove the object under the cursor
- `Ctrl + Z`: Undo terrain paint actions

## Menus

- `Editor > Load Map...`: Load a TMX map.
- `Editor > Save As...`: Save the edited map to a TMX file.
- `Editor > Export Map to Game`: Replace the game map with the current edited map.
- `Editor > Restore Original Map TMX`: Restore the preserved backup.
- `View > Grid Lines`: Show or hide tile gridlines.
- `View > Locs Layer`: Show or hide Locs object markers.
- `Settings > Editor Settings...`: Set install location and dark mode.
- `Settings > Clear Install Location`: Clear the saved game folder after confirmation.

## Project Files

- `horsey_map_editor.py`: Main editor application.
- `tile_defs.json`: Tile names and editor colors.
- `.gitignore`: Ignores local settings, generated backups, build output, and private reference files.

Ignored local files/folders:

- `editor_settings.json`: Your local editor settings.
- `backups/`: Generated map backups.
- `dev/`: Private/reference files used during development.
- `build/` and `dist/`: Local packaged builds.

## Development Notes

Reference TMX and game-definition files can be placed in the ignored `dev/` folder for local analysis. These files are useful for understanding the game's map data, but they should not be committed or edited by the editor.

When changing object editing behavior, preserve these rules:

- Never alter existing object GIDs unless the user explicitly chooses a different object template.
- Every required Locs GID must exist at least once before export.
- Creature spawners with `count` and `radius` properties may have multiple placements.
- Buried objects may have multiple placements.
- Other Locs GIDs are treated as unique and should only appear once per map.

## Status

This project is an unofficial alpha tool and is not affiliated with Horsey or its developers.
