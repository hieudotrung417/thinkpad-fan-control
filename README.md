# ThinkPad Fan Control

A small native GTK app for monitoring and manually controlling the fans on
this ThinkPad T14 Gen 5. It supports:

- automatic firmware control;
- manual fan levels 1 through 7;
- full-speed cooling;
- live fan RPM and CPU/GPU temperature readings;
- a Linux status-bar menu for changing fan speed without opening the window.

The desktop app runs as the normal user. A narrow, root-owned helper performs
only validated fan-mode changes through `thinkpad_acpi`; PolicyKit displays the
system authentication dialog when needed.

## Install

From this directory:

```bash
chmod +x install.sh
sudo ./install.sh
```

Then open **ThinkPad Fan Control** from the Ubuntu app launcher, or run:

```bash
fanspeed
```

The installer adds the GTK 3 Ayatana AppIndicator binding on Ubuntu when it is
not already installed. This binding provides the DBusMenu interface required
for interactive menus in GNOME's status bar. On other distributions, install
the corresponding AyatanaAppIndicator GObject-introspection package before
running the installer.

## AppImage

Download `ThinkPad_Fan_Control-x86_64.AppImage`, make it executable, and run it:

```bash
chmod +x ThinkPad_Fan_Control-x86_64.AppImage
./ThinkPad_Fan_Control-x86_64.AppImage
```

The AppImage bundles the application, Python, GTK, and AppIndicator libraries.
Fan changes still display the normal PolicyKit authentication prompt, but the
AppImage does not install a privileged helper or other files on the system.

To build the AppImage reproducibly in the Ubuntu 22.04 container:

```bash
./build-appimage.sh
```

The artifact is written to `dist/ThinkPad_Fan_Control-x86_64.AppImage`.
GitHub Actions also publishes it as a workflow artifact. Pushing a tag such as
`v1.0.0` creates a GitHub release and attaches the executable AppImage for
direct download.

## Uninstall

From the project directory, run:

```bash
sudo ./uninstall.sh
```

The installer also places the uninstaller on the system, so this works even if
the project directory has been deleted:

```bash
sudo fanspeed-uninstall
```

The uninstaller restores automatic firmware fan control, stops the installed
status-bar process, and removes the application, launcher, icon, privileged
helper, PolicyKit policy, and installed uninstaller. Shared GTK and
AppIndicator packages are retained because other applications may use them.

## Status-bar controls

The status-bar icon displays the current mode: `A` for automatic, `1` through
`7` for a manual level, and `MAX` for full speed. Open its menu to see live
temperature/RPM information and switch modes immediately.

Closing the main window leaves the app running in the status bar. Choose
**Open Fan Control** to restore the window, or **Quit** to exit completely.

## How fan control works

The application does not control the fan motor directly. It sends commands
through Linux's `thinkpad_acpi` driver to the ThinkPad embedded controller
(EC). The EC is the hardware controller that ultimately changes the electrical
or PWM signal driving the fans.

Linux disables manual fan commands by default. When a manual level is selected
for the first time, the privileged helper reloads the driver with manual fan
control enabled, equivalent to:

```bash
modprobe thinkpad_acpi fan_control=1
```

It then writes one of the following commands to `/proc/acpi/ibm/fan`:

```text
level 1
level 2
...
level 7
level full-speed
level auto
```

Levels 1 through 7 are discrete cooling levels understood by the embedded
controller. They are not exact RPM values or percentages, so the resulting RPM
can vary with the laptop model and operating conditions. Level 7 is the highest
normal manual level. `full-speed` requests the maximum available fan speed and
can be faster than level 7. Both fans in this ThinkPad follow the same
controller level.

The `level auto` command returns control to the firmware. In automatic mode,
the firmware continuously chooses the fan speed from temperatures, workload,
and the active platform power profile. Merely opening or closing the
application does not change the current mode; **Automatic (recommended)** must
be selected to return to automatic control without rebooting.

## Safety

Manual mode remains active after closing the app. Select **Automatic
(recommended)** when manual cooling is no longer needed. A reboot also restores
automatic control because the app does not persist the kernel's manual-control
option.

The UI deliberately excludes level 0, which would stop the fan. The kernel and
firmware retain their emergency thermal protections, but manual fan control
should still be used with care.

## Run from the project directory

After installing the helper, the current development version can be launched
with:

```bash
python3 fanspeed_app.py
```
