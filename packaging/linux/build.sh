#!/usr/bin/env bash
set -euo pipefail

version=${1:?expected a release version}
output=${2:?expected a destination directory}
whisper_commit=96ec4d9823e9d0211944172da35f9f29134af990
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

source_dir="$work/deektator-$version"
mkdir -p "$source_dir/whisper.cpp" "$work/rpm/SOURCES" "$output"
cp -R deektator packaging run-deektator "$source_dir/"
printf 'VERSION = "%s"\n' "$version" > "$source_dir/deektator/_release_version.py"
curl --fail --location --retry 3 "https://codeload.github.com/ggml-org/whisper.cpp/tar.gz/$whisper_commit" |
    tar --extract --gzip --strip-components=1 --directory "$source_dir/whisper.cpp"
tar --create --gzip --file "$work/rpm/SOURCES/deektator-$version.tar.gz" \
    --directory "$work" "deektator-$version"

rpmbuild -bb --define "_topdir $work/rpm" --define "deektator_version $version" \
    packaging/linux/deektator.spec
cp "$work"/rpm/RPMS/x86_64/deektator-*.rpm "$output/"
