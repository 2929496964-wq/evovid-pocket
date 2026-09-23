// Linux/macOS 纯模型检查，不冒充原生 UI 或真实购买测试。
import Foundation
@main struct ModelChecks {
    static func main() throws {
        let b=Board.template("A neighborhood coffee shop");try b.validate()
        precondition(b.scenes.count==3)
        precondition(b.scenes.reduce(0,{$0+$1.seconds})==12)
        precondition(b.text.contains("coffee"))
        let data=try JSONEncoder().encode(b)
        let decoded=try JSONDecoder().decode(Board.self,from:data);precondition(decoded==b)
        let empty=Board.template("   ");try empty.validate()
        precondition(empty.title=="A small story")
        precondition(Board.template(String(repeating:"a",count:500)).title.count==120)
        let invalid=[Board(title:"",scenes:b.scenes),Board(title:"x",scenes:[]),Board(title:"x",scenes:[SceneItem(title:"a",caption:"b",seconds:40)])]
        for value in invalid {do{try value.validate();fatalError("Invalid board accepted")}catch StudioError.invalidBoard{}}
        print("9 model assertions passed. Native build, UI and RevenueCat transactions remain separate checks.")
    }
}
