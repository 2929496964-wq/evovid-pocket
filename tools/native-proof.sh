#!/usr/bin/env bash
# Actual macOS/iOS build and evidence. No production purchases, secrets or model downloads.
set -euo pipefail
mkdir -p evidence
xcodebuild -version > evidence/xcode-version.txt
xcodegen generate
swiftc Native/Models.swift Tests/ModelChecks.swift -o /tmp/evovid-model-checks
/tmp/evovid-model-checks | tee evidence/model-checks.txt
UDID=$(xcrun simctl list devices available -j | python3 -c 'import sys,json;d=json.load(sys.stdin);print(next(x["udid"] for k,v in d["devices"].items() if "iOS" in k for x in v if "iPhone" in x["name"] and x.get("isAvailable")))')
xcrun simctl boot "$UDID" || true
xcrun simctl bootstatus "$UDID" -b
xcrun simctl status_bar "$UDID" override --time '9:41' --batteryState charged --batteryLevel 100 || true
xcodebuild build-for-testing -project EvoVidPocket.xcodeproj -scheme EvoVidPocket -configuration Debug -destination "platform=iOS Simulator,id=$UDID" -derivedDataPath DerivedData CODE_SIGNING_ALLOWED=NO > evidence/build.log 2>&1
xcrun simctl io "$UDID" recordVideo --codec=h264 evidence/native-ui-smoke.mp4 > evidence/recording.log 2>&1 &
REC=$!
stop_recording(){ kill -INT "$REC" 2>/dev/null || true;wait "$REC" 2>/dev/null || true; }
trap stop_recording EXIT
set +e
xcodebuild test-without-building -only-testing:EvoVidPocketUITests/PocketUITests/testNativeRenderAndHonestPaywall -project EvoVidPocket.xcodeproj -scheme EvoVidPocket -configuration Debug -destination "platform=iOS Simulator,id=$UDID" -derivedDataPath DerivedData -resultBundlePath evidence/NativeProof.xcresult CODE_SIGNING_ALLOWED=NO > evidence/ui-tests.log 2>&1
CODE=$?
set -e
stop_recording;trap - EXIT
xcrun xcresulttool export attachments --path evidence/NativeProof.xcresult --output-path evidence/screenshots || true
APPDATA=$(xcrun simctl get_app_container "$UDID" dev.evovid.pocket.competition data 2>/dev/null || true)
if [ -n "$APPDATA" ]; then
 mkdir -p evidence/rendered-video
 find "$APPDATA/Documents" -maxdepth 1 -name 'evovid-*.mp4' -exec cp {} evidence/rendered-video/ \; || true
fi
python3 - "$CODE" <<'PY'
import sys,json,datetime,pathlib
code=int(sys.argv[1]);d={'recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'native_ui_exit_code':code,'native_ui_passed':code==0,'revenuecat_purchase_verified':False,'device':'iOS Simulator, not a physical iPhone','video':'Actual AVFoundation motion graphics from generic text, not neural generation','final_submission_ready':False}
pathlib.Path('evidence/status.json').write_text(json.dumps(d,indent=2))
PY
exit "$CODE"
