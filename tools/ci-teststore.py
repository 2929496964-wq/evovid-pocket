"""Create private CI config; verify only test-user receipts; export sanitized proof.
No credential is printed. No compiled binary or raw xcresult is published.
"""
from __future__ import annotations
import base64, datetime as dt, json, os, pathlib, plistlib, re, sys, time
import urllib.error, urllib.parse, urllib.request
ROOT = pathlib.Path.cwd()
PRIVATE = ROOT / '.private-proof'
PUBLIC = ROOT / 'public-proof'

def key() -> str:
    value = os.environ.get('RC_TEST_STORE_SDK_KEY', '').strip()
    if not re.fullmatch(r'test_[A-Za-z0-9_-]{12,150}', value):
        raise ValueError('Missing or invalid Test Store key; no transaction attempted.')
    return value

def user_id() -> str:
    return 'evovid-ci-' + re.sub(r'[^0-9-]', '', os.environ.get('GITHUB_RUN_ID', '0') + '-' + os.environ.get('GITHUB_RUN_ATTEMPT', '1'))

def write_json(name: str, value: object) -> None:
    PUBLIC.mkdir(exist_ok=True)
    (PUBLIC/name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf8')

def prepare() -> None:
    value = key()
    PRIVATE.mkdir(mode=0o700, exist_ok=True)
    PUBLIC.mkdir(exist_ok=True)
    config = ROOT / 'Native/CIRevenueCat.plist'
    config.write_bytes(plistlib.dumps({'sdk_key': value, 'app_user_id': user_id()}))
    config.chmod(0o600)
    write_json('status.json', {'phase':'prepared', 'test_user':user_id(), 'real_money':False, 'purchase_verified':False, 'final_submission_ready':False})
    print('Test Store config prepared privately; no key emitted.')

def server_verify() -> dict:
    report = {'test_user':user_id(), 'purchase_verified':False, 'real_money':False}
    request = urllib.request.Request('https://api.revenuecat.com/v1/subscribers/'+urllib.parse.quote(user_id(),safe=''), headers={'Authorization':'Bearer '+key(), 'Accept':'application/json'})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(request,timeout=25) as response:
                data=json.load(response)
            subscriber=data.get('subscriber',{})
            entitlement=subscriber.get('entitlements',{}).get('evovid_pocket_pro',{})
            product=entitlement.get('product_identifier')
            subscription=subscriber.get('subscriptions',{}).get(product,{})
            expires=entitlement.get('expires_date')
            active=bool(product) and (expires is None or dt.datetime.fromisoformat(expires.replace('Z','+00:00')) > dt.datetime.now(dt.timezone.utc))
            report.update({'http_status':200, 'entitlement':'evovid_pocket_pro', 'product':product,
                'entitlement_active':active, 'is_sandbox':subscription.get('is_sandbox') is True,
                'store':subscription.get('store'), 'purchase_date':entitlement.get('purchase_date'),
                'expires_date':expires, 'purchase_verified':active and subscription.get('is_sandbox') is True})
            if report['purchase_verified']:
                return report
        except urllib.error.HTTPError as exc:
            report.update({'http_status':exc.code, 'error_type':'HTTPError'})
        except Exception as exc:
            report['error_type']=type(exc).__name__
        if attempt<3: time.sleep(3)
    return report

def finalize(exit_code: int) -> None:
    PUBLIC.mkdir(exist_ok=True)
    value=key()
    audit=[]
    source=PRIVATE/'test-store-audit.json'
    if source.exists():
        try:
            raw=json.loads(source.read_text())
            allowed={'operation','product','entitlement','active','observed_at','environment','real_money'}
            audit=[{k:v for k,v in event.items() if k in allowed} for event in raw]
        except (ValueError,TypeError): audit=[]
    write_json('sdk-callback-audit.json',audit)
    verification=server_verify()
    write_json('server-verification.json',verification)
    ops=[x.get('operation') for x in audit]
    purchase=any(x.get('operation')=='test_purchase' and x.get('active') is True for x in audit)
    cancel=any(x.get('operation')=='cancelled' and x.get('active') is False for x in audit)
    failed=any(x.get('operation')=='failed' and x.get('active') is False for x in audit)
    # Export text diagnostics only after removing full keys, key patterns and authorization lines.
    for name in ['build.log','ui-tests.log','recording.log','xcode-version.txt']:
        p=PRIVATE/name
        if p.exists():
            text=p.read_text(errors='replace').replace(value,'[REDACTED_TEST_STORE_KEY]')
            text=re.sub(r'test_[A-Za-z0-9_-]{18,}', '[REDACTED_TEST_STORE_KEY]',text)
            text=re.sub(r'(?im)^.*(?:Authorization:|sdk_key["\s]*[=:]).*$', '[REDACTED_AUTH_LINE]',text)
            (PUBLIC/name).write_text(text)
    status={'observed_at':dt.datetime.now(dt.timezone.utc).isoformat(), 'head_sha':os.environ.get('GITHUB_SHA'),
        'test_user':user_id(), 'device':'iOS Simulator; not physical iPhone', 'native_ui_exit_code':exit_code,
        'native_ui_passed':exit_code==0,'sdk_purchase_verified':purchase,'server_purchase_verified':verification['purchase_verified'],
        'cancellation_kept_locked':cancel,'failure_kept_locked':failed,
        'restore_callback':[x for x in audit if str(x.get('operation','')).startswith('restore_')],
        'restore_scope':'Test Store current CustomerInfo only; no App Store account restoration or transfer claimed.',
        'real_money':False,'final_submission_ready':False,'final_submission_sent':False}
    write_json('status.json',status)
    # Stop publication if a sensitive value escaped; upload no derived data/xcresult/app bundle.
    patterns=[value.encode(),base64.b64encode(value.encode())]
    leaked=[]
    for p in PUBLIC.rglob('*'):
        if p.is_file() and any(token in p.read_bytes() for token in patterns):
            leaked.append(p.name);p.unlink()
    if leaked:
        write_json('privacy-block.json',{'blocked_files':leaked, 'reason':'sensitive value detected; file removed'})
        raise RuntimeError('Proof export blocked by privacy check.')
    print(json.dumps({k:status[k] for k in ['native_ui_passed','sdk_purchase_verified','server_purchase_verified','cancellation_kept_locked','failure_kept_locked','real_money']}))
    if exit_code or not (purchase and cancel and failed and verification['purchase_verified']):
        raise RuntimeError('Test Store proof incomplete; inspect sanitized results. No success is assumed.')

if __name__=='__main__':
    if sys.argv[1]=='prepare': prepare()
    elif sys.argv[1]=='finalize': finalize(int(sys.argv[2]))
    else: raise SystemExit('Unknown operation')
