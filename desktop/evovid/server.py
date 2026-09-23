"""带令牌与同源检查的本地 API。无自动上传、无付款、无模型下载入口。"""
from pathlib import Path
from contextlib import asynccontextmanager
from io import BytesIO
import os,secrets,json,zipfile,uuid,urllib.parse
import cv2
from fastapi import FastAPI,Request,HTTPException,Depends
from fastapi.responses import FileResponse,Response
from fastapi.staticfiles import StaticFiles
from .store import Store
from .engine import Engine
from .models import CreateJob
from .vision import analyze_video
ROOT=Path(__file__).resolve().parents[1]

def create_app(home:Path|None=None, token:str|None=None, background:bool=True):
    """测试可指定隔离数据目录；生产默认只由启动器监听 127.0.0.1。"""
    home=home or Path(os.getenv('EVOVID_HOME',str(ROOT/'.evovid')))
    store=Store(home);engine=Engine(store);token=token or secrets.token_urlsafe(32)
    @asynccontextmanager
    async def lifespan(app):
        if background:engine.start()
        yield
        if background:engine.close()
    app=FastAPI(title='EvoVid Competition Workbench',lifespan=lifespan,docs_url=None,redoc_url=None,openapi_url=None)
    app.state.store=store;app.state.engine=engine;app.state.token=token
    @app.middleware('http')
    async def headers(request,call_next):
        """拒绝跨站写入请求，添加基础浏览器隔离响应头。"""
        origin=request.headers.get('origin')
        if request.method not in ('GET','HEAD','OPTIONS') and origin:
            if urllib.parse.urlparse(origin).netloc != request.headers.get('host'):
                return Response('Cross-origin mutation denied',status_code=403)
        r=await call_next(request)
        r.headers['X-Content-Type-Options']='nosniff';r.headers['Referrer-Policy']='no-referrer'
        r.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'"
        r.headers['Cache-Control']='no-store'
        return r
    def auth(request:Request):
        """所有任务/媒体接口都需要随机访问令牌；不允许通过 URL 查询参数传密钥。"""
        provided=request.headers.get('X-EvoVid-Token','')
        if not secrets.compare_digest(provided,token):raise HTTPException(401,'Local access token required.')
    def job_or_404(job_id):
        """仅接受已存储 ID，不拼接未经验证的文件路径。"""
        job=store.get(job_id)
        if not job:raise HTTPException(404,'Job not found.')
        return job
    @app.get('/health')
    def health():
        """公开健康检查不含用户数据。"""
        return {'ok':True,'application':'EvoVid Workbench'}
    @app.get('/api/status',dependencies=[Depends(auth)])
    def status():
        """直观报告实测运行时和未配置能力。"""
        return {'opencv_version':cv2.__version__,'opencv5_verified':cv2.__version__.startswith('5.'),
            'llm_configured':bool(os.getenv('EVOVID_LLM_MODEL')),'aws_verified':False,
            'real_video_model_connected':False,'registration_complete':None,'registration_state_source':'Not connected to contest accounts',
            'notices':['Motion-graphics renderer, not a neural video model.','AWS and native purchase flow require separate verification.']}
    @app.get('/api/jobs',dependencies=[Depends(auth)])
    def jobs():return store.list()
    @app.post('/api/jobs',dependencies=[Depends(auth)],status_code=201)
    def create(req:CreateJob):
        """建立任务；队列上限避免误触或插件滥用造成资源耗尽。"""
        try:i=store.create(req.model_dump())
        except ValueError as e:raise HTTPException(429,str(e))
        return {'id':i,'status':'queued'}
    @app.get('/api/jobs/{job_id}',dependencies=[Depends(auth)])
    def get(job_id:str):return job_or_404(job_id)
    @app.get('/api/jobs/{job_id}/events',dependencies=[Depends(auth)])
    def events(job_id:str):job_or_404(job_id);return store.events(job_id)
    @app.post('/api/jobs/{job_id}/cancel',dependencies=[Depends(auth)])
    def cancel(job_id:str):job_or_404(job_id);return engine.cancel(job_id)
    @app.post('/api/jobs/{job_id}/resume',dependencies=[Depends(auth)])
    def resume(job_id:str):
        job_or_404(job_id)
        try:engine.resume(job_id)
        except ValueError as e:raise HTTPException(409,str(e))
        return {'id':job_id,'status':'queued'}
    @app.get('/api/jobs/{job_id}/video',dependencies=[Depends(auth)])
    def video(job_id:str,before:bool=False):
        j=job_or_404(job_id)
        if not j['result']:raise HTTPException(409,'Video not ready.')
        name='before.mp4' if before else j['result']['video_file']
        return FileResponse(store.home/'jobs'/job_id/name,media_type='video/mp4')
    @app.get('/api/jobs/{job_id}/bundle',dependencies=[Depends(auth)])
    def bundle(job_id:str):
        """只导出用户选择的单任务，不导出数据库、令牌、配置或其他私人文件。"""
        j=job_or_404(job_id)
        if not j['result']:raise HTTPException(409,'Result not ready.')
        mem=BytesIO();d=store.home/'jobs'/job_id
        with zipfile.ZipFile(mem,'w',zipfile.ZIP_DEFLATED) as z:
            for name in ['storyboard.json','result.json','before.mp4','after.mp4']:
                if (d/name).is_file():z.write(d/name,name)
            z.writestr('events.json',json.dumps(store.events(job_id),ensure_ascii=False,indent=2))
            z.writestr('NOTICE.txt','Selected task only. Inspect for private content before sharing. Not a final competition submission.')
        return Response(mem.getvalue(),media_type='application/zip',headers={'Content-Disposition':f'attachment; filename="evovid-{job_id[:8]}.zip"'})
    @app.post('/api/audit',dependencies=[Depends(auth)])
    async def audit(request:Request):
        """本机上传视频，最大 32 MB；只分析并返回，随后删除临时上传。不会发送云端。"""
        filename=store.home/(uuid.uuid4().hex+'.mp4');size=0
        try:
            with filename.open('wb') as f:
                async for chunk in request.stream():
                    size+=len(chunk)
                    if size>32*1024*1024:raise HTTPException(413,'Maximum video size is 32 MB.')
                    f.write(chunk)
            with filename.open('rb') as check:
                if check.read(32)[4:8] != b'ftyp':
                    raise HTTPException(422, 'Only MP4/MOV media containers are supported.')
            # CPU 检测在线程执行，不阻塞事件循环的请求接收。
            from starlette.concurrency import run_in_threadpool
            try:return await run_in_threadpool(analyze_video,filename)
            except ValueError as e:raise HTTPException(422,str(e))
        finally:filename.unlink(missing_ok=True)
    from .review_api import attach_review_routes
    attach_review_routes(app, home, auth, ROOT)
    app.mount('/',StaticFiles(directory=ROOT/'static',html=True),name='ui')
    return app
