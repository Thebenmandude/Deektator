%global debug_package %{nil}

Name:           deektator
Version:        %{deektator_version}
Release:        1%{?dist}
Summary:        Offline hold-to-talk dictation for Fedora KDE
License:        LicenseRef-Unlicensed AND MIT
URL:            https://github.com/Thebenmandude/Deektator
Source0:        %{name}-%{version}.tar.gz

BuildRequires:  cmake
BuildRequires:  desktop-file-utils
BuildRequires:  gcc-c++
BuildRequires:  make
Requires:       gtk4
Requires:       gtk-layer-shell
Requires:       pulseaudio-utils
Requires:       python3
Requires:       python3-gobject
Requires:       wl-clipboard
Requires:       xdg-desktop-portal-kde

%description
Hold a global shortcut to dictate text. The included Whisper CPU runtime
transcribes locally, and Deektator copies the result to the desktop clipboard.

%prep
%autosetup

%build
cmake -S whisper.cpp -B whisper-build \
    -DCMAKE_BUILD_TYPE=Release -DBUILD_SHARED_LIBS=OFF \
    -DGGML_NATIVE=OFF -DGGML_OPENMP=OFF -DWHISPER_BUILD_TESTS=OFF
cmake --build whisper-build --target whisper-cli --parallel %{_smp_build_ncpus}

%install
install -d %{buildroot}%{_libexecdir}/deektator/deektator
install -pm0644 deektator/*.py %{buildroot}%{_libexecdir}/deektator/deektator/
install -pm0755 run-deektator whisper-build/bin/whisper-cli %{buildroot}%{_libexecdir}/deektator/
install -Dpm0755 packaging/linux/deektator %{buildroot}%{_bindir}/deektator
desktop-file-install --dir=%{buildroot}%{_datadir}/applications packaging/linux/*.desktop
install -Dm0644 whisper.cpp/LICENSE %{buildroot}%{_licensedir}/%{name}/whisper.cpp.txt

%files
%license %{_licensedir}/%{name}/whisper.cpp.txt
%{_bindir}/deektator
%{_datadir}/applications/io.github.deektator.Deektator.desktop
%{_libexecdir}/deektator/
