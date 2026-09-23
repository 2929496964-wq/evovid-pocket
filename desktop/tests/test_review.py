"""真实媒体路径的集成与安全测试。外部报名、AWS、LLM、原生购买不由这些测试证明。"""
from pathlib import Path
from io import BytesIO
import json, shutil, subprocess, uuid, zipfile
import cv2, pytest
from fastapi.testclient import TestClient
from evovid.server import create_app, ROOT
from evovid.review import ReviewStore, ReviewAction, proposal_for, digest_file
from evovid.render import ffmpeg_path
from tools.make_review_fixture import make_clip
TOKEN='v2-isolated-test-token-not-an-account-credential'
HEAD={'X-EvoVid-Token':TOKEN}

@pytest.fixture
def client(tmp_path):
    """每个 API 测试使用隔离目录与测试令牌。"""
    with TestClient(create_app(tmp_path,TOKEN,background=False)) as client:
        yield client

@pytest.fixture(scope='module')
def assets(tmp_path_factory):
    """创建正常、全黑和静态合成片，避免依赖私有视频。"""
    folder=tmp_path_factory.mktemp('review-assets')
    out={'lowlight':ROOT/'submission-assets'/'demo-input.mp4'}
    for name in ('normal','black','static'):
        out[name]=folder/(name+'.mp4');make_clip(out[name],scenario=name,seconds=6)
    return out

@pytest.fixture(scope='module')
def processed(tmp_path_factory):
    """实际运行 OpenCV → 策略 → FFmpeg → OpenCV 闭环。"""
    store=ReviewStore(tmp_path_factory.mktemp('processed'))
    identity=uuid.uuid4().hex;folder=store.folder(identity);folder.mkdir()
    shutil.copyfile(ROOT/'submission-assets'/'demo-input.mp4',folder/'source.mp4')
    first=store.analyze(identity,demo=True)
    with store.exclusive():result=store.apply(identity,ReviewAction(action='brighten',confirmed=True))
    return store,identity,first,result


def load(client,path):
    """通过实际上传路由导入测试文件。"""
    return client.post('/api/reviews',headers={**HEAD,'Content-Type':'video/mp4'},content=path.read_bytes())


def test_review_routes_require_auth(client):
    for path in ('/api/reviews','/api/reviews/123/report','/api/reviews/123/video'):
        assert client.get(path).status_code==401
    assert client.post('/api/reviews/demo').status_code==401


def test_upload_real_decode_and_source_kind(client,assets):
    response=load(client,assets['lowlight']);assert response.status_code==201,response.text
    r=response.json();assert r['source_kind']=='user_upload'
    assert r['before']['opencv_version']==cv2.__version__
    assert r['before']['sample_count']==60
    assert r['before']['duration_seconds']==8.0
    assert r['llm_used'] is False


def test_demo_declares_synthetic(client):
    response=client.post('/api/reviews/demo',headers=HEAD)
    assert response.status_code==201
    assert response.json()['source_kind']=='synthetic_fixture'
    assert response.json()['source_is_neural_generated']=='not_asserted'


def test_unsupported_mime_rejected(client):
    assert client.post('/api/reviews',headers={**HEAD,'Content-Type':'text/plain'},content=b'hello').status_code==415


def test_playlist_is_not_a_video(client):
    response=client.post('/api/reviews',headers={**HEAD,'Content-Type':'video/mp4'},content=b'#EXTM3U\nhttps://example.com/private\n')
    assert response.status_code==422
    assert client.get('/api/reviews',headers=HEAD).json()==[]


def test_malformed_header_not_persisted(client):
    response=client.post('/api/reviews',headers={**HEAD,'Content-Type':'video/mp4'},content=b'\x00\x00\x00\x18ftypisom'+b'broken'*30)
    assert response.status_code==422
    assert client.get('/api/reviews',headers=HEAD).json()==[]


def test_empty_upload(client):
    response=client.post('/api/reviews',headers={**HEAD,'Content-Type':'video/mp4'},content=b'')
    assert response.status_code==422


def test_oversize_upload_rejected(client,monkeypatch):
    import evovid.review_api as module
    monkeypatch.setattr(module,'MAX_BYTES',64)
    assert client.post('/api/reviews',headers={**HEAD,'Content-Type':'video/mp4'},content=b'x'*65).status_code==413


def test_cross_origin_upload_rejected(client):
    response=client.post('/api/reviews/demo',headers={**HEAD,'Origin':'https://example.com'})
    assert response.status_code==403


def test_confirmation_is_required(client):
    r=client.post('/api/reviews/demo',headers=HEAD).json()
    response=client.post('/api/reviews/'+r['id']+'/apply',headers=HEAD,json={'action':'brighten'})
    assert response.status_code==409
    r2=client.get('/api/reviews/'+r['id'],headers=HEAD).json();assert r2['after'] is None


def test_arbitrary_filter_rejected(client):
    r=client.post('/api/reviews/demo',headers=HEAD).json()
    response=client.post('/api/reviews/'+r['id']+'/apply',headers=HEAD,json={'action':'brighten','confirmed':True,'filter':'movie=https://evil.invalid'})
    assert response.status_code==422


def test_safe_preview_reduces_diagnostic_flags(processed):
    store,identity,first,result=processed
    assert first['before']['underexposed']
    before=sum(x['mean_luma']<20 or x['dark_fraction']>.95 for x in first['before']['samples'])
    after=sum(x['mean_luma']<20 or x['dark_fraction']>.95 for x in result['after']['samples'])
    assert after<before
    assert result['status']=='adjusted_for_review'
    assert result['adjustment_count']==1


def test_preview_preserves_source_digest(processed):
    store,identity,first,result=processed
    assert digest_file(store.folder(identity)/'source.mp4')==first['input_sha256']==result['input_sha256']
    assert result['original_retained'] is True


def test_preview_duration_geometry(processed):
    _,_,first,result=processed
    assert first['before']['duration_seconds']==result['after']['duration_seconds']
    assert first['before']['width']==result['after']['width']==640
    assert first['before']['height']==result['after']['height']==360


def test_preview_keeps_audio(processed):
    store,identity,_,_=processed
    outputs=[]
    for name in ('source.mp4','preview.mp4'):
        outputs.append(subprocess.run([ffmpeg_path(),'-hide_banner','-loglevel','error','-i',str(store.folder(identity)/name),'-map','0:a:0','-f','hash','-hash','sha256','-'],capture_output=True,check=True,timeout=20).stdout)
    assert outputs[0]==outputs[1] and b'SHA256=' in outputs[0]


def test_preview_is_bounded_to_one(processed):
    store,identity,_,_=processed
    with pytest.raises(ValueError,match='one-preview'):
        store.apply(identity,ReviewAction(action='brighten',confirmed=True))


def test_black_frames_do_not_get_fake_reconstruction(client,assets):
    r=load(client,assets['black']).json()
    assert r['before']['underexposed']
    assert not r['proposal']['can_brighten']
    assert client.post('/api/reviews/'+r['id']+'/apply',headers=HEAD,json={'action':'brighten','confirmed':True}).status_code==409


def test_normal_footage_has_no_brightening_proposal(client,assets):
    r=load(client,assets['normal']).json()
    assert r['proposal']['action']=='preserve'
    assert not r['proposal']['can_brighten']


def test_intentional_night_is_preserved_by_choice(client):
    r=client.post('/api/reviews/demo',headers=HEAD).json()
    result=client.post('/api/reviews/'+r['id']+'/apply',headers=HEAD,json={'action':'preserve','confirmed':True}).json()
    assert result['status']=='preserved'
    assert result['selected_file']=='source.mp4' and result['adjustment_count']==0
    assert result['input_sha256']==r['input_sha256']


def test_static_frame_is_not_automatically_repaired(client,assets):
    r=load(client,assets['static']).json()
    assert r['status']=='analyzed' and r['adjustment_count']==0
    assert any(x['code']=='possibly_static' for x in r['before']['issues'])


def test_export_scope_and_report(client):
    r=client.post('/api/reviews/demo',headers=HEAD).json()
    blob=client.get('/api/reviews/'+r['id']+'/bundle',headers=HEAD).content
    with zipfile.ZipFile(BytesIO(blob)) as z:
        assert set(z.namelist())=={'source.mp4','report.json','NOTICE.txt'}
        assert TOKEN.encode() not in z.read('report.json')
        assert json.loads(z.read('report.json'))['input_sha256']==r['input_sha256']


def test_persistence_after_restart(tmp_path):
    with TestClient(create_app(tmp_path,TOKEN,background=False)) as c:
        r=c.post('/api/reviews/demo',headers=HEAD).json()
    with TestClient(create_app(tmp_path,TOKEN,background=False)) as c:
        assert c.get('/api/reviews/'+r['id'],headers=HEAD).json()['input_sha256']==r['input_sha256']


def test_delete_needs_confirmation(client):
    r=client.post('/api/reviews/demo',headers=HEAD).json()
    assert client.delete('/api/reviews/'+r['id'],headers=HEAD).status_code==409
    assert client.delete('/api/reviews/'+r['id']+'?confirmed=true',headers=HEAD).status_code==200
    assert client.get('/api/reviews/'+r['id'],headers=HEAD).status_code==404


def test_bad_id_rejected_without_filesystem_access(tmp_path,client):
    with pytest.raises(ValueError):ReviewStore(tmp_path).folder('../private')
    assert client.get('/api/reviews/not-a-uuid',headers=HEAD).status_code==404


def test_busy_gate_blocks_parallel_upload(client):
    with client.app.state.reviews.exclusive():
        response=client.post('/api/reviews/demo',headers=HEAD)
    assert response.status_code==409
    assert client.get('/api/reviews',headers=HEAD).json()==[]


def test_source_tamper_refuses_preview(tmp_path):
    store=ReviewStore(tmp_path);identity=uuid.uuid4().hex;folder=store.folder(identity);folder.mkdir()
    shutil.copyfile(ROOT/'submission-assets'/'demo-input.mp4',folder/'source.mp4')
    store.analyze(identity)
    with (folder/'source.mp4').open('ab') as file:file.write(b'tampered')
    with pytest.raises(ValueError,match='Source content changed'):
        store.apply(identity,ReviewAction(action='brighten',confirmed=True))


def test_report_never_asserts_contest_submission(client):
    r=client.post('/api/reviews/demo',headers=HEAD).json()
    assert r['before']['opencv5_verified']==cv2.__version__.startswith('5.')
    assert client.get('/api/status',headers=HEAD).json()['registration_complete'] is None
    assert r['decision_engine']=='bounded_rule_policy'


def test_restart_marks_processing_interrupted(tmp_path):
    store=ReviewStore(tmp_path);identity=uuid.uuid4().hex;folder=store.folder(identity);folder.mkdir()
    shutil.copyfile(ROOT/'submission-assets'/'demo-input.mp4',folder/'source.mp4')
    r=store.analyze(identity);r['status']='processing';store.save(identity,r)
    assert ReviewStore(tmp_path).get(identity)['status']=='interrupted'
