// 真实 SDK + RevenueCat 测试服务器；点击官方 Test Store 弹窗，不替换 SDK、不注入成功状态。
import XCTest
import Foundation

final class TestStoreProofUITests: XCTestCase {
    private func capture(_ name:String){
        let a=XCTAttachment(screenshot:XCUIScreen.main.screenshot());a.name=name;a.lifetime = .keepAlways;add(a)
    }
    private func waitLabel(_ element:XCUIElement,_ text:String,_ seconds:TimeInterval=45){
        let p=NSPredicate(format:"label CONTAINS %@",text)
        XCTAssertEqual(XCTWaiter.wait(for:[XCTNSPredicateExpectation(predicate:p,object:element)],timeout:seconds),.completed,"Expected UI state: "+text)
    }
    private func show(_ element:XCUIElement,in app:XCUIApplication){
        for _ in 0..<8{if element.isHittable{return};app.swipeUp()}
        XCTAssertTrue(element.isHittable)
    }
    func testActualPurchaseLifecycle() throws {
        continueAfterFailure=false
        let app=XCUIApplication();app.launchArguments=["--ci-test-store"];app.launch()
        XCTAssertTrue(app.navigationBars["EvoVid Pocket"].waitForExistence(timeout:20))
        capture("01-native-home")
        let render=app.buttons["renderLocal"];show(render,in:app);render.tap()
        let preview=app.buttons["previewVideo"]
        XCTAssertTrue(preview.waitForExistence(timeout:130));show(preview,in:app);preview.tap()
        XCTAssertTrue(app.buttons["Done"].waitForExistence(timeout:15));sleep(5)
        capture("02-real-local-video");app.buttons["Done"].tap()
        app.tabBars.buttons["Test Store"].tap()
        let state=app.staticTexts["purchaseState"]
        XCTAssertTrue(state.waitForExistence(timeout:20))
        waitLabel(state,"Real offerings loaded",60)
        let monthly=app.buttons["buy_$rc_monthly"]
        XCTAssertTrue(monthly.waitForExistence(timeout:30));show(monthly,in:app)
        capture("03-server-offerings-pro-locked")
        // 取消与失败不能解锁；所有结果来自 SDK callback。
        monthly.tap()
        let dialog=app.alerts["Test Store Purchase"]
        XCTAssertTrue(dialog.waitForExistence(timeout:20));capture("04-official-teststore-dialog")
        dialog.buttons["Cancel"].tap();waitLabel(state,"cancelled")
        XCTAssertTrue(app.staticTexts["Pro locked"].exists);capture("05-cancelled-still-locked")
        show(monthly,in:app);monthly.tap()
        XCTAssertTrue(dialog.waitForExistence(timeout:20));dialog.buttons["Test failed purchase"].tap()
        waitLabel(state,"Test purchase failed:");XCTAssertTrue(app.staticTexts["Pro locked"].exists)
        capture("06-failure-still-locked")
        // 成功路径是官方测试交易，不涉及任何实际扣款。
        show(monthly,in:app);monthly.tap()
        XCTAssertTrue(dialog.waitForExistence(timeout:20));dialog.buttons["Test valid purchase"].tap()
        waitLabel(state,"Test purchase verified",60);capture("07-sdk-verified-pro-unlocked")
        app.tabBars.buttons["Create"].tap()
        let export=app.buttons["proExport"];XCTAssertTrue(export.waitForExistence(timeout:15));show(export,in:app)
        capture("08-pro-export-unlocked")
        export.tap();sleep(2);capture("09-native-export-share-sheet")
        // 分享面板只展示，不向任何人发送内容。
        let close=app.buttons["Close"].firstMatch
        if close.waitForExistence(timeout:3){close.tap()}
        else if app.buttons["Cancel"].firstMatch.exists{app.buttons["Cancel"].firstMatch.tap()}
        else{app.swipeDown()}
        app.tabBars.buttons["Test Store"].tap()
        let refresh=app.buttons["Refresh status"];show(refresh,in:app);refresh.tap()
        waitLabel(state,"Real offerings loaded")
        let restore=app.buttons["Restore purchases"];show(restore,in:app);restore.tap()
        // Test Store 没有真实 Apple 账号历史；只核验当前用户回调，不宣称跨账号恢复。
        let restorePredicate=NSPredicate(format:"label BEGINSWITH %@","Test Store")
        XCTAssertEqual(XCTWaiter.wait(for:[XCTNSPredicateExpectation(predicate:restorePredicate,object:state)],timeout:45),.completed)
        capture("10-current-user-restore-callback")
        let proof=app.staticTexts["purchaseProof"];show(proof,in:app)
        let record=XCTAttachment(string:proof.label);record.name="Last SDK callback (redacted)";record.lifetime = .keepAlways;add(record)
        capture("11-redacted-callback-record")
    }
}
