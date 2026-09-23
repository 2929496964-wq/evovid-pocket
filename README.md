# EvoVid Pocket

An isolated iPhone/iPad competition prototype for small creators: edit a three-shot storyboard, render a silent 720×1280 MP4 on device, and optionally connect your own EvoVid desktop workflow. RevenueCat's **real Purchases SDK** unlocks storyboard export only after returning an active `evovid_pocket_pro` entitlement.

## Current truth

This is development source, not a final Shipaton submission. Offline planning is a deterministic template, **not an LLM**. Local MP4 rendering is AVFoundation motion graphics, **not neural video generation**. The optional desktop adapter can use your explicitly configured LLM; it never silently enables paid APIs.

A Native proof workflow is supplied to compile and run the actual iOS simulator, capture screenshots, export a real MP4 and record the native UI. A workflow file alone is **not proof of execution**. See its actual run result; no native-build or purchase success is assumed.

RevenueCat registration, project configuration and Test Store transaction evidence are still required. Student eligibility is pending organizer confirmation. No final entry has been submitted.

## Native build

On a Mac with Xcode: install XcodeGen (`brew install xcodegen`), run `xcodegen generate`, open `EvoVidPocket.xcodeproj`, select an iPhone simulator and run the **Debug** scheme. Simulator testing requires no paid Apple account. Physical-device installation needs your own signing setup.

`bash tools/native-proof.sh` performs the same build and native UI test used by CI and saves actual logs/screenshots/recording under `evidence/`. A failure remains a failure in those artifacts.

## Test Store setup

See [the setup checklist](docs/revenuecat-setup.md). Use an actual RevenueCat Test Store public SDK key starting `test_` in the app. Do not enter secret `sk_` keys. The build refuses production purchases and disables Test Store configuration in Release. Purchase cancellation, failure, restore and success remain separate outcomes. A no-key paywall screenshot does not count as purchase evidence.

## Optional desktop

The isolated server source is included in `desktop/`. Install `desktop/requirements.txt`, then run `python desktop/launcher.py --profile pocket`. This binds loopback by default. A real iPhone requires explicitly enabling `--lan` on a trusted private network and entering the pairing token shown by the launcher. Never include that token in a public screenshot. No cloud provider is called unless you configure it and select LLM mode.

## Tests

`swiftc Native/Models.swift Tests/ModelChecks.swift -o /tmp/evovid-checks && /tmp/evovid-checks` checks the portable model. `cd desktop && python -m pytest -q` exercises desktop code. Neither test substitutes for native compilation or a RevenueCat transaction.

## Privacy and licenses

Only isolated competition code is published. No personal EvoVid memory, user photographs, credentials, cookies, academic proof, private configuration or model weights are included. Authored code is MIT licensed; RevenueCat and all other dependencies retain their own licenses. Apple frameworks and system fonts are used on device, not redistributed. Development used AI coding assistance. Bundled sample text is generic fiction.

## Observed backend setup

On 2026-09-21 the RevenueCat developer project `76bfcb20` (EvoVid Pocket) was created without a bank card. Its `default` Offering contains monthly, annual and lifetime Test Store products. The actual entitlement identifier is `evovid_pocket_pro`. Owner email confirmation completed successfully. SDK offerings, native build and test transactions have **not** yet been verified. The public GitHub repository exists, but the source-upload connector returned HTTP 403; this archive is the complete prepared source package, not proof of an uploaded repository.
