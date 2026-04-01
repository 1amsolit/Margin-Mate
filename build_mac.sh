#!/usr/bin/env bash
# Build Margin Mate as a macOS .app bundle
# Run from the project root:  bash build_mac.sh
set -e

echo "==> Installing dependencies..."
pip install -r requirements.txt
pip install pyinstaller

echo "==> Building app..."
pyinstaller margin_mate.spec --clean

echo ""
echo "Done! App is at: dist/MarginMate.app"
echo "To distribute: zip -r MarginMate-mac.zip dist/MarginMate.app"
