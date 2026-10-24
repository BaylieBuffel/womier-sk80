# Installing the SK80 GUI Desktop Launcher

## Installation Steps

1. **Copy the desktop file to your applications directory:**

   ```bash
   cp sk80-gui.desktop ~/.local/share/applications/
   ```

2. **Optional: Customize the icon** (if you have a specific icon for your app):

   Replace the `Icon=utilities-terminal` line with your preferred icon name, or add an absolute path to an icon file:

   ```bash
   # Example: using a custom icon
   Icon=/path/to/your/icon.png
   ```

3. **Make sure the desktop file is readable:**

   ```bash
   chmod +r ~/.local/share/applications/sk80-gui.desktop
   ```

4. **Refresh your desktop environment** (usually automatic, but if not):

   - Log out and log back in
   - Or run: `killall gnome-shell` (for GNOME) / restart your panel

## Verification

After installation, you should be able to:
- Launch the GUI from your application menu
- Run `sk80-gui` from terminal
- Use `sk80ctl` for command-line operations

## Available Commands

```bash
# CLI tool
sk80ctl --help

# GUI application
sk80-gui
```
