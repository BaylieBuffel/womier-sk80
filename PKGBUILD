# Maintainer: BaylieBuffel <berklassevangerwen@gmail.com>

pkgname=womier-sk80
pkgver=1.0.0
pkgrel=3
pkgdesc="Native Linux control tool and GUI for the Womier SK80 keyboard"
arch=('any')
url="https://github.com/BaylieBuffel/womier-sk80"
license=('MIT')
depends=('python-pyusb' 'python-pillow' 'pyside6')
optdepends=(
  'python-numpy: Faster screen/GIF conversion'
  'qt6-wayland: For Wayland display support'
)
provides=('sk80ctl' 'sk80-gui')
conflicts=('womier-sk80-git')

makedepends=('python-build' 'python-installer' 'python-setuptools' 'python-wheel')

# This package is built straight from the source tree that contains this
# PKGBUILD, so no tarball or VCS checkout is needed.
source=()
install=womier-sk80.install

build() {
  cd "$startdir"
  rm -rf "$srcdir/wheel"
  python -m build --wheel --no-isolation --outdir "$srcdir/wheel"
}

check() {
  cd "$startdir"
  # No test suite is shipped yet.
}

package() {
  cd "$startdir"

  python -m installer --destdir="$pkgdir" "$srcdir"/wheel/*.whl

  # Desktop entry: always point Exec at the packaged binary in /usr/bin.
  install -Dm644 sk80-gui.desktop \
    "$pkgdir/usr/share/applications/sk80-gui.desktop"
  sed -i 's|^Exec=.*|Exec=sk80-gui|' \
    "$pkgdir/usr/share/applications/sk80-gui.desktop"

  # udev rule granting the logged-in user access to the keyboard.
  install -Dm644 udev/99-womier-sk80.rules \
    "$pkgdir/usr/lib/udev/rules.d/99-womier-sk80.rules"

  # License (required by the MIT identifier in .PKGINFO).
  install -Dm644 LICENSE "$pkgdir/usr/share/licenses/$pkgname/LICENSE"
}
