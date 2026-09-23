"""一个工作线程、持久任务和受约束的质量反馈闭环。只自动修复本引擎可控故障。"""
from pathlib import Path
import threading,time,json,os,logging
from .store import Store
from .models import CreateJob
from .providers import template_plan,llm_plan
from .render import render_storyboard
from .vision import analyze_video
from .comfy import run_comfy
log=logging.getLogger(__name__)
class Engine:
    """串行重任务。开发时不常驻多个 GPU 模型，不假设现有模型可用。"""
    def __init__(self,store:Store):
        self.store=store;self.shutdown=threading.Event();self.cancelled=set();self.lock=threading.Lock();self.thread=None
    def start(self):
        """恢复服务但不自动重跑上次被中断的生成任务。"""
        self.store.mark_interrupted();self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start()
    def close(self):
        """停止接取新任务，并通知当前渲染正常中止。"""
        self.shutdown.set()
        if self.thread:self.thread.join(timeout=95)
    def loop(self):
        """从 SQLite 拉取队列。单实例运行，不支持多个服务副本共享该队列。"""
        while not self.shutdown.is_set():
            jobs=[j for j in reversed(self.store.list()) if j['status']=='queued']
            if jobs:self.process(jobs[0]['id'])
            else:self.shutdown.wait(.25)
    def cancel(self,job_id):
        """禁止取消已成功的任务，避免破坏输出；返回当前状态。"""
        with self.lock:
            job=self.store.get(job_id)
            if not job:return None
            if job['status'] in ('queued','running'):
                self.cancelled.add(job_id)
                if job['status']=='queued':self.store.update(job_id,'cancelled')
            return self.store.get(job_id)
    def resume(self,job_id):
        """仅从已失败/取消/中断任务重跑。保留原有日志供比较。"""
        with self.lock:
            j=self.store.get(job_id)
            if not j or j['status'] not in ('failed','cancelled','interrupted'):raise ValueError('Job is not resumable.')
            if sum(x['status'] in ('queued','running') for x in self.store.list())>=10:raise ValueError('Queue is full.')
            self.cancelled.discard(job_id);self.store.update(job_id,'queued')
            self.store.event(job_id,'resumed',{'policy':'restart pipeline; previous events retained'})
    def process(self,job_id):
        """执行规划、渲染、检测和最多一次可解释重渲染；不会无限修复。"""
        with self.lock:
            j=self.store.get(job_id)
            if not j or j['status']!='queued':return
            self.store.update(job_id,'running')
        home=self.store.home/'jobs'/job_id;home.mkdir(parents=True,exist_ok=True)
        stopped=lambda:self.shutdown.is_set() or job_id in self.cancelled
        try:
            req=CreateJob.model_validate(j['request']);used=req.planner
            self.store.event(job_id,'planning',{'requested':used})
            try:board=llm_plan(req.prompt) if used=='llm' else template_plan(req.prompt)
            except Exception as e:
                # 不泄露供应商返回的正文、Authorization 或其他私人数据。
                self.store.event(job_id,'planner_fallback',{'type':type(e).__name__,'to':'template','note':'LLM not successful; no claim of AI planning'})
                board=template_plan(req.prompt);used='template'
            if stopped():raise InterruptedError()
            (home/'storyboard.json').write_text(board.model_dump_json(indent=2),encoding='utf-8')
            renderer='local_motion_graphics'
            if req.renderer=='comfy':
                self.store.event(job_id,'rendering',{'provider':'comfyui','approval':'local workflow hash required'})
                try:
                    run_comfy(req.prompt,home/'before.mp4',stopped)
                    analyze_video(home/'before.mp4')  # 下载成功不等于视频可解码。
                    renderer='comfyui'
                except InterruptedError:raise
                except Exception as e:
                    self.store.event(job_id,'renderer_fallback',{'type':type(e).__name__,'to':'local_motion_graphics','note':'ComfyUI not successful; no neural video claim'})
                    render_storyboard(board,home/'before.mp4',req.inject_dark_scene,stopped)
            else:
                self.store.event(job_id,'rendering',{'provider':renderer,'generative_video_model':False})
                render_storyboard(board,home/'before.mp4',req.inject_dark_scene,stopped)
            before=analyze_video(home/'before.mp4')
            self.store.event(job_id,'visual_inspection',{'underexposed':before['underexposed'],'opencv':before['opencv_version']})
            repaired=False;final=home/'before.mp4';after=before
            # 只在已知故障注入场景自动重渲染。未知输入中的夜景等交给人工判断。
            if before['underexposed'] and req.inject_dark_scene and renderer=='local_motion_graphics':
                self.store.event(job_id,'repair_decision',{'action':'rerender_without_fault','max_retry':1,'reason':'Known test fault measured as underexposure'})
                render_storyboard(board,home/'after.mp4',False,stopped)
                after=analyze_video(home/'after.mp4');repaired=not after['underexposed'];final=home/'after.mp4'
            if stopped():raise InterruptedError()
            result={'storyboard':board.model_dump(),'planner_requested':req.planner,'planner_used':used,
                'llm_used':used=='llm','renderer_requested':req.renderer,'renderer':renderer,'generative_video_model':False,
                'comfyui_workflow_executed':renderer=='comfyui','model_provenance':'Not independently verified; inspect the approved workflow.',
                'test_fault_injected':req.inject_dark_scene and renderer=='local_motion_graphics','repair_success':repaired,'before':before,'after':after,
                'video_file':final.name,'status_note':'Local development result; not competition submission proof.'}
            (home/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            self.store.event(job_id,'completed',{'repair_success':repaired,'human_review_required':True})
            self.store.update(job_id,'completed',result)
        except InterruptedError:
            self.store.event(job_id,'cancelled',{'by':'user_or_shutdown'});self.store.update(job_id,'cancelled')
        except Exception as e:
            log.warning('Job %s failed: %s',job_id,type(e).__name__)
            self.store.event(job_id,'failed',{'type':type(e).__name__})
            self.store.update(job_id,'failed',error=f'{type(e).__name__}: pipeline failed; check local configuration.')
