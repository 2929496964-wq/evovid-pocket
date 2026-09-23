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
    // CI 仅在 Debug 且明确传入启动标记时读取临时配置；不把 key 传入命令参数或日志。
    private var audit:[[String:Any]]=[]
    private var refreshGeneration=0
    private var refreshTimeout:Task<Void,Never>?
    private var offeringPending=false
    init(){
        #if DEBUG
        guard ProcessInfo.processInfo.arguments.contains("--ci-test-store") else{return}
        guard let url=Bundle.main.url(forResource:"CIRevenueCat",withExtension:"plist"),
              let data=try? Data(contentsOf:url),
              let values=(try? PropertyListSerialization.propertyList(from:data,format:nil)) as? [String:String],
              let key=values["sdk_key"],let user=values["app_user_id"],user.hasPrefix("evovid-ci-") else{
            status="Test Store CI configuration missing. No purchase attempted.";return
        }
        Task { @MainActor [weak self] in
            await Task.yield()
            self?.configure(key,appUserID:user)
        }
        #endif
    }
    // 配置一次真实 SDK，失败时不解锁任何权限。
    func configure(_ raw:String,appUserID:String?=nil){
        #if DEBUG
        let key=raw.trimmingCharacters(in:.whitespacesAndNewlines)
        guard key.hasPrefix("test_"),key.count>12,!key.contains(" ") else{status="Enter a public Test Store SDK key (test_). Never enter a secret key.";return}
        guard !configured else{refresh();return}
        Purchases.logLevel = .error
        Purchases.configure(withAPIKey:key,appUserID:appUserID);configured=true;refresh()
        #else
        status="Test Store is disabled in Release. No purchase will be started."
        #endif
    }
    // offerings 和 CustomerInfo 串行读取，避免并发状态互相覆盖。
    // Separate requests: products release the UI; only SDK CustomerInfo can unlock Pro.
    func refresh(){
        guard configured,!busy else{return}
        refreshGeneration += 1
        let generation=refreshGeneration
        busy=true;offeringPending=true
        status="Loading products from RevenueCat..."
        record("refresh_started",product:"current_customer_info")
        refreshTimeout?.cancel()
        refreshTimeout=Task { @MainActor [weak self] in
            do { try await Task.sleep(nanoseconds:30_000_000_000) } catch { return }
            guard let self=self,self.refreshGeneration==generation else{return}
            if self.offeringPending {
                self.offeringPending=false;self.busy=false
                self.status="Product loading timed out. Refresh to retry; no purchase was made."
                self.record("offerings_timeout",product:"current_offering")
            }
            self.refreshGeneration += 1
        }
        Purchases.shared.getOfferings { [weak self] offerings,error in
            Task { @MainActor in
                guard let self=self,self.refreshGeneration==generation else{return}
                self.offeringPending=false;self.busy=false
                if error != nil {
                    self.packages=[]
                    self.status="Product loading failed. Refresh to retry; no purchase was made."
                    self.record("offerings_failed",product:"current_offering")
                    return
                }
                self.packages=offerings?.current?.availablePackages ?? []
                self.status=self.packages.isEmpty ? "No current Offering. Attach Test Store products in the dashboard." : "Real offerings loaded; entitlement verification is separate."
                self.record("offerings_loaded",product:"current_offering")
            }
        }
        // Never nest this request inside the offerings completion.
        Purchases.shared.getCustomerInfo { [weak self] info,error in
            Task { @MainActor in
                guard let self=self,self.refreshGeneration==generation else{return}
                guard error==nil,let info=info else{
                    self.record("customer_info_failed",product:"current_customer_info");return
                }
                self.isPro=info.entitlements["evovid_pocket_pro"]?.isActive == true
                self.record("refresh",product:"current_customer_info")
            }
        }
    }
    private func beginTransaction(){
        refreshGeneration += 1
        refreshTimeout?.cancel()
        offeringPending=false;busy=true
    }
    // 取消、失败、成功分开处理，不能用按钮点击替代 transaction 结果。
    func purchase(_ package:Package){
        guard configured,!busy else{return};beginTransaction()
        Purchases.shared.purchase(package:package){[weak self] _,info,error,cancelled in
            Task{@MainActor in
                guard let self=self else{return};self.busy=false
                if cancelled{self.status="Test purchase cancelled. No new purchase claimed.";self.record("cancelled",product:package.storeProduct.productIdentifier);return}
                if let error=error{self.status="Test purchase failed: "+error.localizedDescription;self.record("failed",product:package.storeProduct.productIdentifier);return}
                self.isPro=info?.entitlements["evovid_pocket_pro"]?.isActive == true
                self.status=self.isPro ? "Test purchase verified. Pro export unlocked." : "Purchase returned, but the pro entitlement is missing."
                if self.isPro{self.record("test_purchase",product:package.storeProduct.productIdentifier)}
            }
        }
    }
    func restore(){
        guard configured,!busy else{return};beginTransaction()
        Purchases.shared.restorePurchases{[weak self] info,error in
            Task{@MainActor in
                guard let self=self else{return};self.busy=false
                if let error=error{self.isPro=false;self.status="Test Store restore callback failed: "+error.localizedDescription;self.record("restore_failed",product:"current_customer_info");return}
                self.isPro=info?.entitlements["evovid_pocket_pro"]?.isActive == true
                self.status=self.isPro ? "Test Store returned current active pro. Not App Store recovery." : "Test Store returned no active pro. Not App Store recovery."
                self.record("restore_current_customer_info",product:"existing_entitlement")
            }
        }
    }
    // 导出记录不含 key、用户 ID、姓名、邮箱，不等同于服务器签名收据。
    private func record(_ operation:String,product:String){
        let object:[String:Any]=["operation":operation,"product":product,"entitlement":"evovid_pocket_pro","active":isPro,
            "observed_at":ISO8601DateFormatter().string(from:Date()),"environment":"RevenueCat Test Store","real_money":false]
        if let data=try? JSONSerialization.data(withJSONObject:object,options:[.prettyPrinted,.sortedKeys]),let text=String(data:data,encoding:.utf8){proof=text}
        #if DEBUG
        if ProcessInfo.processInfo.arguments.contains("--ci-test-store"){
            audit.append(object)
            let folder=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0]
            if let data=try? JSONSerialization.data(withJSONObject:audit,options:[.prettyPrinted,.sortedKeys]){
                try? data.write(to:folder.appendingPathComponent("test-store-audit.json"),options:.atomic)
            }
        }
        #endif
    }
}
