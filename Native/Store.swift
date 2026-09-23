// 真实 RevenueCat SDK；严格只允许 Debug Test Store，不读取或保存 secret API key。
import Foundation
import SwiftUI
import RevenueCat
@MainActor final class EntitlementStore:ObservableObject {
    @Published var packages:[Package]=[]
    @Published var isPro=false
    @Published var status="Not configured. No RevenueCat purchase has been verified."
    @Published var busy=false
    @Published var configured=false
    @Published var proof="No verified purchase evidence."
    // 配置一次真实 SDK，失败时不解锁任何权限。
    func configure(_ raw:String){
        #if DEBUG
        let key=raw.trimmingCharacters(in:.whitespacesAndNewlines)
        guard key.hasPrefix("test_"),key.count>12,!key.contains(" ") else{status="Enter a public Test Store SDK key (test_). Never enter a secret key.";return}
        guard !configured else{refresh();return}
        Purchases.logLevel = .warn
        Purchases.configure(withAPIKey:key);configured=true;refresh()
        #else
        status="Test Store is disabled in Release. No purchase will be started."
        #endif
    }
    // offerings 和 CustomerInfo 串行读取，避免并发状态互相覆盖。
    func refresh(){
        guard configured,!busy else{return};busy=true
        Purchases.shared.getOfferings{[weak self] offerings,error in
            Task{@MainActor in
                guard let self=self else{return}
                if let error=error{self.busy=false;self.isPro=false;self.status=error.localizedDescription;return}
                self.packages=offerings?.current?.availablePackages ?? []
                Purchases.shared.getCustomerInfo{[weak self] info,infoError in
                    Task{@MainActor in
                        guard let self=self else{return};self.busy=false
                        self.isPro=info?.entitlements["evovid_pocket_pro"]?.isActive == true
                        if let error=infoError{self.isPro=false;self.status=error.localizedDescription}
                        else{self.status=self.packages.isEmpty ? "No current Offering. Attach Test Store products in the dashboard." : "Real offerings loaded; entitlement refreshed."}
                    }
                }
            }
        }
    }
    // 取消、失败、成功分开处理，不能用按钮点击替代 transaction 结果。
    func purchase(_ package:Package){
        guard configured,!busy else{return};busy=true
        Purchases.shared.purchase(package:package){[weak self] _,info,error,cancelled in
            Task{@MainActor in
                guard let self=self else{return};self.busy=false
                if cancelled{self.status="Test purchase cancelled. No new purchase claimed.";return}
                if let error=error{self.status=error.localizedDescription;return}
                self.isPro=info?.entitlements["evovid_pocket_pro"]?.isActive == true
                self.status=self.isPro ? "Test purchase verified. Pro export unlocked." : "Purchase returned, but the pro entitlement is missing."
                if self.isPro{self.record("test_purchase",product:package.storeProduct.productIdentifier)}
            }
        }
    }
    func restore(){
        guard configured,!busy else{return};busy=true
        Purchases.shared.restorePurchases{[weak self] info,error in
            Task{@MainActor in
                guard let self=self else{return};self.busy=false
                if let error=error{self.isPro=false;self.status=error.localizedDescription;return}
                self.isPro=info?.entitlements["evovid_pocket_pro"]?.isActive == true
                self.status=self.isPro ? "Restore returned active pro." : "Restore finished. No active pro."
                if self.isPro{self.record("restore",product:"existing_entitlement")}
            }
        }
    }
    // 导出记录不含 key、用户 ID、姓名、邮箱，不等同于服务器签名收据。
    private func record(_ operation:String,product:String){
        let object:[String:Any]=["operation":operation,"product":product,"entitlement":"evovid_pocket_pro","active":isPro,
            "observed_at":ISO8601DateFormatter().string(from:Date()),"environment":"RevenueCat Test Store","real_money":false]
        if let data=try? JSONSerialization.data(withJSONObject:object,options:[.prettyPrinted,.sortedKeys]),let text=String(data:data,encoding:.utf8){proof=text}
    }
}
