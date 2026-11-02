# ThinkPad Fan Control

A small native GTK 4 app for monitoring and manually controlling the fans on
this ThinkPad T14 Gen 5. It supports:

- automatic firmware control;
- manual fan levels 1 through 7;
- full-speed cooling;
- live fan RPM and CPU/GPU temperature readings.

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
