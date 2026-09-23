// 本机 UI smoke：真实启动 App、渲染视频；不伪造 RevenueCat transaction。
import XCTest
final class PocketUITests:XCTestCase {
    private func capture(_ name:String){let a=XCTAttachment(screenshot:XCUIScreen.main.screenshot());a.name=name;a.lifetime = .keepAlways;add(a)}
    func testNativeRenderAndHonestPaywall() throws {
        continueAfterFailure=false
        let app=XCUIApplication();app.launch()
        XCTAssertTrue(app.navigationBars["EvoVid Pocket"].waitForExistence(timeout:20))
        capture("01-native-home")
        let render=app.buttons["renderLocal"]
        for _ in 0..<7{if render.isHittable{break};app.swipeUp()}
        XCTAssertTrue(render.isHittable);render.tap()
        let preview=app.buttons["previewVideo"]
        XCTAssertTrue(preview.waitForExistence(timeout:130),"Native video file must exist before preview is offered")
        for _ in 0..<3{if preview.isHittable{break};app.swipeUp()}
        capture("02-render-complete");preview.tap()
        XCTAssertTrue(app.buttons["Done"].waitForExistence(timeout:15))
        sleep(8);capture("03-video-preview");app.buttons["Done"].tap()
        app.tabBars.buttons["Test Store"].tap()
        let state=app.staticTexts["purchaseState"]
        XCTAssertTrue(state.waitForExistence(timeout:10))
        XCTAssertTrue(state.label.contains("Not configured"))
        XCTAssertFalse(app.buttons["proExport"].exists)
        capture("04-unconfigured-real-paywall")
    }
}
