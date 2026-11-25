%global app_id io.github.djshiye.Audius
# One package for every Fedora: the code lives in %{_datadir}/%{name} (not in a
# python3.X site-packages) and runs on the system's /usr/bin/python3, so nothing
# may pin a Python version. Nothing should generate one; this is the safety net.
%global __requires_exclude ^python\\(abi\\)
%global __brp_python_bytecompile %{nil}

Name:           audius
Version:        1.1.1
# CI appends .<commit count> so every build from main is a newer release.
Release:        1%{?release_suffix}%{?dist}
Summary:        Gain, monitoring and routing for the RME Babyface Pro FS

License:        MIT
URL:            https://github.com/djshiye/audius
Source0:        %{name}-%{version}.tar.gz
# The public package signing key; CI exports it from the signing secret.
Source1:        RPM-GPG-KEY-djshiye
BuildArch:      noarch

BuildRequires:  python3
BuildRequires:  desktop-file-utils
BuildRequires:  appstream
BuildRequires:  alsa-lib

Requires:       python3-gobject
Requires:       gtk4
Requires:       libadwaita >= 1.6
Requires:       webkitgtk6.0
Requires:       alsa-lib
Requires:       gstreamer1-plugins-good
Requires:       pipewire-gstreamer
Requires:       pipewire-utils
Requires:       hicolor-icon-theme

%description
A control panel for the RME Babyface Pro FS in Class Compliant mode, where
RME's TotalMix FX isn't available: mic gain with live levels, 48V and PAD,
switching between headphones and speakers, a per-output mixer, a routing grid,
scenes and undo. It drives the Linux kernel's Babyface Pro mixer controls and
works around a bug in them (see docs/KERNEL-BUG.md).

%prep
%autosetup -n %{name}-%{version}

%build

%install
# The whole package tree, including the web interface under audius/ui.
install -d %{buildroot}%{_datadir}/%{name}
cp -r audius %{buildroot}%{_datadir}/%{name}/
find %{buildroot}%{_datadir}/%{name} -name __pycache__ -prune -exec rm -rf {} +
find %{buildroot}%{_datadir}/%{name} -type d -exec chmod 0755 {} +
find %{buildroot}%{_datadir}/%{name} -type f -exec chmod 0644 {} +
install -d %{buildroot}%{_bindir}
printf '#!/usr/bin/python3 -sP\nimport sys\nsys.path.insert(0, "%{_datadir}/%{name}")\nfrom audius.app import main\nsys.exit(main())\n' > %{buildroot}%{_bindir}/audius
chmod 0755 %{buildroot}%{_bindir}/audius
install -Dpm 0644 data/%{app_id}.desktop %{buildroot}%{_datadir}/applications/%{app_id}.desktop
install -Dpm 0644 data/%{app_id}.metainfo.xml %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml
install -Dpm 0644 data/icons/%{app_id}.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{app_id}.svg
install -Dpm 0644 data/icons/%{app_id}-symbolic.svg %{buildroot}%{_datadir}/icons/hicolor/symbolic/apps/%{app_id}-symbolic.svg
# Keeps the boot-time sound restore from overriding the Babyface volume knob: before the
# first restore of each boot, the saved Main-Out volumes go back to the driver's "never written"
# placeholder. alsa-state is Fedora's default; alsa-restore runs instead without the daemon.
install -Dpm 0755 tools/keep-knob-volumes.py %{buildroot}%{_libexecdir}/%{name}/keep-knob-volumes
for unit in alsa-state alsa-restore; do
  install -Dpm 0644 data/systemd/audius-keep-knob.conf %{buildroot}%{_prefix}/lib/systemd/system/$unit.service.d/audius-keep-knob.conf
done
# The DNF repository definition and its signing key, so the repository keeps itself configured.
install -Dpm 0644 build-aux/%{name}.repo %{buildroot}%{_sysconfdir}/yum.repos.d/%{name}.repo
install -Dpm 0644 %{SOURCE1} %{buildroot}%{_sysconfdir}/pki/rpm-gpg/RPM-GPG-KEY-djshiye-%{name}

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{app_id}.desktop
appstreamcli validate --no-net --explain %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml
/usr/bin/python3 -m unittest discover -s tests

%files
%license LICENSE
%doc README.md docs/KERNEL-BUG.md
%{_bindir}/audius
%{_datadir}/%{name}/
%{_datadir}/applications/%{app_id}.desktop
%{_metainfodir}/%{app_id}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{app_id}.svg
%{_datadir}/icons/hicolor/symbolic/apps/%{app_id}-symbolic.svg
%{_libexecdir}/%{name}/
%dir %{_prefix}/lib/systemd/system/alsa-state.service.d
%dir %{_prefix}/lib/systemd/system/alsa-restore.service.d
%{_prefix}/lib/systemd/system/alsa-state.service.d/audius-keep-knob.conf
%{_prefix}/lib/systemd/system/alsa-restore.service.d/audius-keep-knob.conf
# Plain %%config, not noreplace: if the repository ever moves, an upgrade moves
# users with it (a hand-edited copy is kept as .rpmsave).
%config %{_sysconfdir}/yum.repos.d/%{name}.repo
%{_sysconfdir}/pki/rpm-gpg/RPM-GPG-KEY-djshiye-%{name}

%changelog
* Wed Nov 25 2026 Dino Klisura <115914552+djshiye@users.noreply.github.com> - 1.1.1-1
- The headphone volume no longer drops when you scroll it after using the Babyface knob
- The boot-time sound restore no longer pulls the headphones back to an old level: alsa-state
  and alsa-restore drop-ins reset the saved Babyface output volumes once per boot
- Volumes set in an earlier boot count as unknown; unknown volumes can't be nudged by scrolling
- A hand-made alsa-state drop-in for the same problem can be removed; leaving it is harmless

* Wed Nov 04 2026 Dino Klisura <115914552+djshiye@users.noreply.github.com> - 1.1.0-1
- One package for every Fedora release: installed under /usr/share/audius, runs on any Python 3
- Signed DNF repository on GitHub Pages; the package installs its own repository file and key

* Wed Oct 07 2026 Dino Klisura <115914552+djshiye@users.noreply.github.com> - 1.0.0-1
- First release
