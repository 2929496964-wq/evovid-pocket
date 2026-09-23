# Current Test Store configuration

Project `EvoVid Pocket` exists, ID `76bfcb20`. No bank card or paid plan was configured.

The default Offering `default` has monthly, annual and lifetime packages, all linked to **Test Store** products. The actual generated entitlement identifier is `evovid_pocket_pro`, matching the native code. The public Test Store SDK key is stored only in the owner's local private configuration, never in this repository.

1. RevenueCat email confirmation has completed successfully through the official confirmation page.
2. Generate the Xcode project with `xcodegen generate` on a Mac and run Debug on an iPhone simulator.
3. Open the native app's Test Store tab and enter the public `test_` SDK key. Never enter a secret `sk_` API key.
4. Confirm actual SDK Offerings load. Tap a test purchase and choose the official Test Store success outcome. No real money changes hands.
5. Verify CustomerInfo returns active `evovid_pocket_pro`, storyboard export unlocks, and the dashboard shows the transaction.
6. Separately exercise cancellation, failure, refresh and restore. Record actual results. No successful transaction is claimed yet.

The Devpost submission ID is not the RevenueCat project ID. An unconfigured paywall screenshot is not purchase evidence. The public source and automated recording workflow are preparation until actual Apple compilation and testing complete.

References:
- https://www.revenuecat.com/docs/test-and-launch/sandbox/test-store
- https://www.revenuecat.com/docs/getting-started/configuring-sdk
