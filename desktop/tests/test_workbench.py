"""隔离测试：模板渲染是真实执行；外部 LLM / ComfyUI 用 HTTP mock，不能替代供应商实测。"""
import json,hashlib,zipfile,io,time
from pathlib import Path
import cv2,httpx,pytest
from pydantic import ValidationError
from fastapi.testclient import TestClient
from evovid.models import CreateJob,Scene,Storyboard
from evovid.providers import template_plan,llm_plan
from evovid.store import Store
from evovid.engine import Engine
from evovid.render import render_storyboard
from evovid.vision import analyze_video,require_opencv5
from evovid.server import create_app
from evovid.comfy import run_comfy,approved_workflow
TOKEN='isolated-test-token-no-user-secrets-0123456789'

@pytest.fixture
def client(tmp_path):
    """不启动后台线程，让状态测试可重复。"""
    app=create_app(tmp_path,TOKEN,background=False)
    with TestClient(app) as c:yield c

@pytest.fixture(scope='module')
def real_job(tmp_path_factory):
    """执行真实 12 秒动效视频、故障注入、视觉检测、一次修复及 MP4 编码。"""
    home=tmp_path_factory.mktemp('real');s=Store(home);e=Engine(s)
    i=s.create(CreateJob(prompt='A community coffee shop',inject_dark_scene=True).model_dump())
    e.process(i)
    return s,i

def test_schema_rejects_extra():
    with pytest.raises(ValidationError):CreateJob(prompt='hello',execute='rm -rf')

def test_scene_boundaries():
    with pytest.raises(ValidationError):Scene(title='hello',seconds=100)
    with pytest.raises(ValidationError):Storyboard(title='hi',scenes=[])

def test_template_is_deterministic():
    assert template_plan('coffee')==template_plan('coffee')

def test_remote_llm_requires_consent(monkeypatch):
    monkeypatch.setenv('EVOVID_LLM_BASE_URL','https://example.com/v1')
    monkeypatch.delenv('EVOVID_ALLOW_REMOTE_LLM',raising=False)
    with pytest.raises(ValueError,match='Remote'):llm_plan('hello')

def test_llm_json_validated(monkeypatch):
    monkeypatch.setenv('EVOVID_LLM_MODEL','mock-model');monkeypatch.setenv('EVOVID_LLM_BASE_URL','http://127.0.0.1:9000/v1')
    def handler(req):
        assert req.url.path=='/v1/chat/completions'
        return httpx.Response(200,json={'choices':[{'message':{'content':template_plan('mock response').model_dump_json()}}]})
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        assert llm_plan('brief',c).title=='mock response'

def test_llm_bad_output_rejected(monkeypatch):
    monkeypatch.setenv('EVOVID_LLM_MODEL','mock');monkeypatch.setenv('EVOVID_LLM_BASE_URL','http://localhost:9000/v1')
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'choices':[{'message':{'content':'{"run_command":"hack"}'}}]}))) as c:
        with pytest.raises(ValidationError):llm_plan('test',c)

def test_queue_capacity(tmp_path):
    s=Store(tmp_path)
    for _ in range(10):s.create({'prompt':'valid'})
    with pytest.raises(ValueError,match='Queue'):s.create({'prompt':'overflow'})

def test_restart_marks_interrupted(tmp_path):
    s=Store(tmp_path);i=s.create({});s.update(i,'running');s.mark_interrupted()
    assert s.get(i)['status']=='interrupted'

def test_cancel_and_resume(tmp_path):
    s=Store(tmp_path);e=Engine(s);i=s.create(CreateJob(prompt='test').model_dump())
    assert e.cancel(i)['status']=='cancelled'
    e.resume(i);assert s.get(i)['status']=='queued'
    with pytest.raises(ValueError):e.resume(i)

def test_render_cancellation_cleans_raw(tmp_path):
    with pytest.raises(InterruptedError):render_storyboard(template_plan('x'),tmp_path/'cancel.mp4',stop=lambda:True)
    assert not (tmp_path/'cancel.avi').exists()

def test_invalid_video(tmp_path):
    f=tmp_path/'bad.mp4';f.write_bytes(b'not a video')
    with pytest.raises(ValueError):analyze_video(f)

def test_opencv_major_gate():
    if cv2.__version__.startswith('5.'):require_opencv5()
    else:
        with pytest.raises(RuntimeError,match='OpenCV 5'):require_opencv5()

def test_real_fault_detection_and_repair(real_job):
    s,i=real_job;j=s.get(i)
    assert j['status']=='completed',j
    r=j['result'];assert r['before']['underexposed'] is True
    assert r['after']['underexposed'] is False and r['repair_success'] is True
    assert r['after']['duration_seconds']==12.0
    assert r['llm_used'] is False and r['generative_video_model'] is False
    assert r['after']['opencv_version']==cv2.__version__

def test_bounded_retry(real_job):
    s,i=real_job
    assert len([x for x in s.events(i) if x['kind']=='repair_decision'])==1

def test_mp4_decodable(real_job):
    s,i=real_job
    for file in ['before.mp4','after.mp4']:
        cap=cv2.VideoCapture(str(s.home/'jobs'/i/file));ok,frame=cap.read();cap.release()
        assert ok and frame.shape[:2]==(360,640)

def test_api_auth(client):
    assert client.get('/api/jobs').status_code==401
    assert client.get('/api/jobs',headers={'X-EvoVid-Token':TOKEN}).status_code==200
    assert client.get('/health').json()['ok']

def test_cross_origin_rejected(client):
    assert client.post('/api/jobs',headers={'X-EvoVid-Token':TOKEN,'Origin':'https://evil.invalid'},json={'prompt':'hello'}).status_code==403

def test_api_validation_and_not_found(client):
    h={'X-EvoVid-Token':TOKEN}
    assert client.post('/api/jobs',headers=h,json={'prompt':'x'}).status_code==422
    assert client.get('/api/jobs/unknown',headers=h).status_code==404
    assert client.post('/api/jobs',headers=h,json={'prompt':'valid'}).status_code==201

def test_raw_audit_cleanup(client):
    r=client.post('/api/audit',headers={'X-EvoVid-Token':TOKEN},content=b'not video')
    assert r.status_code==422
    assert not list(client.app.state.store.home.glob('*.mp4'))

def test_selected_export_has_no_token(real_job):
    s,i=real_job
    with TestClient(create_app(s.home,TOKEN,background=False)) as c:
        response=c.get('/api/jobs/'+i+'/bundle',headers={'X-EvoVid-Token':TOKEN})
        assert response.status_code==200
        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            assert set(z.namelist())=={'storyboard.json','result.json','before.mp4','after.mp4','events.json','NOTICE.txt'}
            assert TOKEN.encode() not in b''.join(z.read(n) for n in z.namelist())

def test_comfy_workflow_approval(tmp_path,monkeypatch):
    f=tmp_path/'wf.json';f.write_text('{}');monkeypatch.setenv('EVOVID_COMFY_WORKFLOW',str(f));monkeypatch.delenv('EVOVID_COMFY_WORKFLOW_SHA256',raising=False)
    with pytest.raises(ValueError,match='SHA256'):approved_workflow()

def test_comfy_mock_protocol(tmp_path,monkeypatch,real_job):
    s,i=real_job;mp4=(s.home/'jobs'/i/'after.mp4').read_bytes()
    wf={'1':{'class_type':'TestOnly','inputs':{'text':'{{EVOVID_PROMPT}}'}}}
    raw=json.dumps(wf).encode();f=tmp_path/'wf.json';f.write_bytes(raw)
    monkeypatch.setenv('EVOVID_COMFY_WORKFLOW',str(f));monkeypatch.setenv('EVOVID_COMFY_WORKFLOW_SHA256',hashlib.sha256(raw).hexdigest())
    monkeypatch.setenv('EVOVID_COMFY_URL','http://127.0.0.1:8188')
    def handler(req):
        if req.url.path=='/prompt':
            assert json.loads(req.content)['prompt']['1']['inputs']['text']=='hello'
            return httpx.Response(200,json={'prompt_id':'abc-123'})
        if req.url.path=='/history/abc-123':return httpx.Response(200,json={'abc-123':{'outputs':{'9':{'gifs':[{'filename':'x.mp4','subfolder':'','type':'output'}]}}}})
        if req.url.path=='/view':return httpx.Response(200,content=mp4)
        raise AssertionError(req.url)
    with httpx.Client(transport=httpx.MockTransport(handler)) as c:
        out=run_comfy('hello',tmp_path/'generated.mp4',client=c)
        assert out.read_bytes()==mp4

def test_comfy_remote_is_disabled(tmp_path,monkeypatch):
    monkeypatch.setenv('EVOVID_COMFY_URL','http://example.com')
    with pytest.raises(ValueError,match='loopback'):run_comfy('test',tmp_path/'x.mp4')

def test_comfy_missing_settings_falls_back(tmp_path,monkeypatch):
    import evovid.engine as mod
    monkeypatch.delenv('EVOVID_COMFY_WORKFLOW',raising=False)
    monkeypatch.setenv('EVOVID_COMFY_URL','http://127.0.0.1:8188')
    # 这里仅测试状态转移，复用假渲染避免重复耗时，不能作为真实视频证据。
    monkeypatch.setattr(mod,'render_storyboard',lambda b,p,*a: p.write_bytes(b'mock'))
    monkeypatch.setattr(mod,'analyze_video',lambda p:{'underexposed':False,'opencv_version':cv2.__version__})
    s=Store(tmp_path);e=Engine(s);i=s.create(CreateJob(prompt='test',renderer='comfy').model_dump());e.process(i)
    assert s.get(i)['result']['renderer']=='local_motion_graphics'
    assert any(x['kind']=='renderer_fallback' for x in s.events(i))

def test_local_config_safe_allowlist(tmp_path,monkeypatch):
    from evovid.config import load_local_config
    f=tmp_path/'config.local.env';f.write_text('EVOVID_LLM_MODEL=local-test\n')
    monkeypatch.delenv('EVOVID_LLM_MODEL',raising=False);load_local_config(f)
    import os
    assert os.environ['EVOVID_LLM_MODEL']=='local-test'
    f.write_text('PATH=unsafe\n')
    with pytest.raises(ValueError):load_local_config(f)

def test_resume_respects_capacity(tmp_path):
    s=Store(tmp_path);e=Engine(s);i=s.create({'prompt':'test'});s.update(i,'cancelled')
    for _ in range(10):s.create({'prompt':'another'})
    with pytest.raises(ValueError,match='Queue'):e.resume(i)
    assert s.get(i)['status']=='cancelled'
