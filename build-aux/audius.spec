%global app_id io.github.djshiye.Audius

Name:           audius
Version:        1.0.0
# CI appends .<commit count> so every build from main is a newer release.
Release:        1%{?release_suffix}%{?dist}
Summary:        Gain, monitoring and routing for the RME Babyface Pro FS

License:        MIT
URL:            https://github.com/djshiye/audius
Source0:        %{name}-%{version}.tar.gz
BuildArch:      noarch

BuildRequires:  python3-devel
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
install -d %{buildroot}%{python3_sitelib}
cp -r audius %{buildroot}%{python3_sitelib}/
find %{buildroot}%{python3_sitelib}/audius -name __pycache__ -prune -exec rm -rf {} +
install -d %{buildroot}%{_bindir}
printf '#!%{python3}\nimport sys\nfrom audius.app import main\nsys.exit(main())\n' > %{buildroot}%{_bindir}/audius
chmod 0755 %{buildroot}%{_bindir}/audius
install -Dpm 0644 data/%{app_id}.desktop %{buildroot}%{_datadir}/applications/%{app_id}.desktop
install -Dpm 0644 data/%{app_id}.metainfo.xml %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml
install -Dpm 0644 data/icons/%{app_id}.svg %{buildroot}%{_datadir}/icons/hicolor/scalable/apps/%{app_id}.svg
install -Dpm 0644 data/icons/%{app_id}-symbolic.svg %{buildroot}%{_datadir}/icons/hicolor/symbolic/apps/%{app_id}-symbolic.svg

%check
desktop-file-validate %{buildroot}%{_datadir}/applications/%{app_id}.desktop
appstreamcli validate --no-net --explain %{buildroot}%{_metainfodir}/%{app_id}.metainfo.xml
%{python3} -m unittest discover -s tests

%files
%license LICENSE
%doc README.md docs/KERNEL-BUG.md
%{_bindir}/audius
%{python3_sitelib}/audius/
%{_datadir}/applications/%{app_id}.desktop
%{_metainfodir}/%{app_id}.metainfo.xml
%{_datadir}/icons/hicolor/scalable/apps/%{app_id}.svg
%{_datadir}/icons/hicolor/symbolic/apps/%{app_id}-symbolic.svg

%changelog
* Wed Oct 07 2026 Dino Klisura <115914552+djshiye@users.noreply.github.com> - 1.0.0-1
- First release
