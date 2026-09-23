#!/usr/bin/env bash
# Actual native SDK tests. Secrets stay private to the runner. No bank/card configuration.
set -euo pipefail
mkdir -p .private-proof public-proof
REC=""
finish() {
  CODE=$?
  trap - EXIT
  if [ -n "$REC" ]; then kill -INT "$REC" 2>/dev/null || true; wait "$REC" 2>/dev/null || true; fi
  if [ -d .private-proof/TestStore.xcresult ]; then
    xcrun xcresulttool export attachments --path .private-proof/TestStore.xcresult --output-path .private-proof/attachments >/dev/null 2>&1 || true
    mkdir -p public-proof/screenshots
    find .private-proof/attachments -type f -name '*.png' -exec cp {} public-proof/screenshots/ \; || true
  fi
  if [ -n "${UDID:-}" ]; then
    APPDATA=$(xcrun simctl get_app_container "$UDID" dev.evovid.pocket.competition data 2>/dev/null || true)
    if [ -n "$APPDATA" ]; then
      if [ -f "$APPDATA/Documents/test-store-audit.json" ]; then cp "$APPDATA/Documents/test-store-audit.json" .private-proof/; fi
      mkdir -p public-proof/rendered-video
      find "$APPDATA/Documents" -maxdepth 1 -name 'evovid-*.mp4' -exec cp {} public-proof/rendered-video/ \; || true
    fi
  fi
  VERIFY=0
  python3 tools/ci-teststore.py finalize "$CODE" || VERIFY=$?
  rm -f Native/CIRevenueCat.plist
  if [ "$CODE" -ne 0 ]; then exit "$CODE"; fi
  exit "$VERIFY"
}
python3 tools/ci-teststore.py prepare
trap finish EXIT
xcodebuild -version > .private-proof/xcode-version.txt
xcodegen generate
UDID=$(xcrun simctl list devices available -j | python3 -c 'import json,sys;d=json.load(sys.stdin);print(next(x["udid"] for k,v in d["devices"].items() if "iOS" in k for x in v if "iPhone" in x["name"] and x.get("isAvailable")))')
xcrun simctl boot "$UDID" 2>/dev/null || true
xcrun simctl bootstatus "$UDID" -b
xcrun simctl status_bar "$UDID" override --time '9:41' --batteryState charged --batteryLevel 100 || true
xcodebuild build-for-testing -project EvoVidPocket.xcodeproj -scheme EvoVidPocket -configuration Debug -destination "platform=iOS Simulator,id=$UDID" -derivedDataPath DerivedData CODE_SIGNING_ALLOWED=NO > .private-proof/build.log 2>&1
xcrun simctl io "$UDID" recordVideo --codec=h264 public-proof/native-teststore-ui.mp4 > .private-proof/recording.log 2>&1 &
REC=$!
xcodebuild test-without-building -only-testing:EvoVidPocketUITests/TestStoreProofUITests/testActualPurchaseLifecycle -project EvoVidPocket.xcodeproj -scheme EvoVidPocket -configuration Debug -destination "platform=iOS Simulator,id=$UDID" -derivedDataPath DerivedData -resultBundlePath .private-proof/TestStore.xcresult CODE_SIGNING_ALLOWED=NO > .private-proof/ui-tests.log 2>&1
