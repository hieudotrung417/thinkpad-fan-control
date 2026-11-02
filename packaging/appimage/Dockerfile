FROM ubuntu:22.04 AS builder

ARG DEBIAN_FRONTEND=noninteractive
ARG APP_VERSION=1.0.0

RUN apt-get update && apt-get install -y --no-install-recommends \
        binutils \
        ca-certificates \
        file \
        gir1.2-ayatanaappindicator3-0.1 \
        gir1.2-gtk-3.0 \
        libayatana-appindicator3-1 \
        libfuse2 \
        python3 \
        python3-dev \
        python3-gi \
        python3-pip \
        wget \
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m pip install --no-cache-dir pyinstaller==6.22.3

WORKDIR /build
COPY . /build/source

RUN pyinstaller \
        --noconfirm \
        --clean \
        --onedir \
        --name fanspeed-appimage \
        --hidden-import gi.repository.AyatanaAppIndicator3 \
        --hidden-import gi.repository.Gdk \
        --hidden-import gi.repository.Gio \
        --hidden-import gi.repository.GLib \
        --hidden-import gi.repository.Gtk \
        --add-data /usr/lib/x86_64-linux-gnu/girepository-1.0/AyatanaAppIndicator3-0.1.typelib:gi_typelibs \
        --add-binary /usr/lib/x86_64-linux-gnu/libayatana-appindicator3.so.1:. \
        /build/source/appimage_entry.py

RUN mkdir -p \
        /build/AppDir/usr/lib/fanspeed \
        /build/AppDir/usr/share/applications \
        /build/AppDir/usr/share/icons/hicolor/scalable/apps \
    && cp -a /build/dist/fanspeed-appimage/. /build/AppDir/usr/lib/fanspeed/ \
    && install -m 755 /build/source/packaging/appimage/AppRun /build/AppDir/AppRun \
    && install -m 644 /build/source/io.github.fanspeed.FanSpeed.desktop \
        /build/AppDir/io.github.fanspeed.FanSpeed.desktop \
    && install -m 644 /build/source/io.github.fanspeed.FanSpeed.desktop \
        /build/AppDir/usr/share/applications/io.github.fanspeed.FanSpeed.desktop \
    && install -m 644 /build/source/io.github.fanspeed.FanSpeed.svg \
        /build/AppDir/io.github.fanspeed.FanSpeed.svg \
    && install -m 644 /build/source/io.github.fanspeed.FanSpeed.svg \
        /build/AppDir/usr/share/icons/hicolor/scalable/apps/io.github.fanspeed.FanSpeed.svg \
    && ln -s io.github.fanspeed.FanSpeed.svg /build/AppDir/.DirIcon \
    && sed -i 's/^Exec=.*/Exec=fanspeed-appimage/' \
        /build/AppDir/io.github.fanspeed.FanSpeed.desktop \
        /build/AppDir/usr/share/applications/io.github.fanspeed.FanSpeed.desktop

RUN wget -q \
        https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
        -O /usr/local/bin/appimagetool \
    && chmod 755 /usr/local/bin/appimagetool \
    && APPIMAGE_EXTRACT_AND_RUN=1 ARCH=x86_64 VERSION="$APP_VERSION" \
        /usr/local/bin/appimagetool \
        /build/AppDir \
        /build/ThinkPad_Fan_Control-x86_64.AppImage

RUN chmod 755 /build/ThinkPad_Fan_Control-x86_64.AppImage

CMD ["cp", "/build/ThinkPad_Fan_Control-x86_64.AppImage", "/output/"]
