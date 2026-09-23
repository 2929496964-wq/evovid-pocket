"""真实素材质检 API。仅本机文件上传，不提供任意 URL 抓取或任意命令执行。"""
from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from io import BytesIO
from pathlib import Path
from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from starlette.concurrency import run_in_threadpool

from .review import ReviewAction, ReviewStore, MAX_BYTES


def attach_review_routes(app, home: Path, auth, root: Path) -> None:
    """与原工作台共用令牌；全部处理结果都留在独立本地目录中。"""
    store = ReviewStore(home)
    app.state.reviews = store

    def get_review(review_id):
        """统一处理没有找到与非法 ID，避免泄露磁盘目录细节。"""
        try:
            return store.get(review_id)
        except (ValueError, FileNotFoundError):
            raise HTTPException(404, "Review not found.")

    @app.get('/api/reviews', dependencies=[Depends(auth)])
    def reviews():
        """列出持久化的当前用户 review 摘要。"""
        return store.list()

    @app.post('/api/reviews', dependencies=[Depends(auth)], status_code=201)
    async def upload(request: Request):
        """流式接收至 32MB；按固定容器头检查，防止把播放列表当素材。"""
        if request.headers.get('content-type', '').split(';')[0] not in ('video/mp4', 'video/quicktime', 'application/octet-stream'):
            raise HTTPException(415, 'Upload an MP4/MOV video.')
        review_id = uuid.uuid4().hex
        folder = store.folder(review_id)
        try:
            with store.exclusive():
                store.check_capacity()
                folder.mkdir()
                size = 0
                with (folder/'source.mp4').open('wb') as file:
                    async for chunk in request.stream():
                        size += len(chunk)
                        if size > MAX_BYTES:
                            raise HTTPException(413, 'Maximum video size is 32 MB.')
                        file.write(chunk)
                return await run_in_threadpool(store.analyze, review_id)
        except HTTPException:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        except RuntimeError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(409, str(exc))
        except ValueError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(422, str(exc))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(422, 'Video could not be decoded; incomplete upload removed.')

    @app.post('/api/reviews/demo', dependencies=[Depends(auth)], status_code=201)
    def demo():
        """复制本包自制合成测试片；绝不把它称作真实相机拍摄或 AI 生成。"""
        sample = root/'submission-assets'/'demo-input.mp4'
        if not sample.is_file():
            raise HTTPException(503, 'Bundled synthetic demo is unavailable.')
        review_id = uuid.uuid4().hex
        folder = store.folder(review_id)
        try:
            with store.exclusive():
                store.check_capacity()
                folder.mkdir()
                shutil.copyfile(sample, folder/'source.mp4')
                return store.analyze(review_id, demo=True)
        except RuntimeError as exc:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(409, str(exc))
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(422, 'Synthetic sample could not be analyzed.')

    @app.get('/api/reviews/{review_id}', dependencies=[Depends(auth)])
    def get(review_id: str):
        """返回观测、策略和处理轨迹，不返回密钥或绝对路径。"""
        return get_review(review_id)

    @app.post('/api/reviews/{review_id}/apply', dependencies=[Depends(auth)])
    def apply(review_id: str, action: ReviewAction):
        """只有显式同意后执行策略；任意视频不做无人监管修图。"""
        get_review(review_id)
        try:
            with store.exclusive():
                return store.apply(review_id, action)
        except ValueError as exc:
            raise HTTPException(409, str(exc))
        except (RuntimeError, OSError):
            raise HTTPException(409, 'Review processing failed or is busy; original retained.')
        except Exception:
            raise HTTPException(422, 'Processing failed; original retained.')

    @app.get('/api/reviews/{review_id}/video', dependencies=[Depends(auth)])
    def video(review_id: str, original: bool = False):
        """只允许访问该任务已知的两个视频文件，不接受用户文件路径。"""
        report = get_review(review_id)
        name = 'source.mp4' if original else report['selected_file']
        if name not in ('source.mp4', 'preview.mp4'):
            raise HTTPException(409, 'Unexpected review output.')
        file = store.folder(review_id)/name
        if not file.is_file() or file.is_symlink():
            raise HTTPException(404, 'Video not found.')
        return FileResponse(file, media_type='video/mp4')

    @app.get('/api/reviews/{review_id}/report', dependencies=[Depends(auth)])
    def report_json(review_id: str):
        """可复核 JSON 报告：原文件哈希、版本、采样指标、日志与限制。"""
        data = json.dumps(get_review(review_id), ensure_ascii=False, indent=2).encode('utf-8')
        return Response(data, media_type='application/json', headers={'Content-Disposition': 'attachment; filename="evovid-review.json"'})

    @app.get('/api/reviews/{review_id}/bundle', dependencies=[Depends(auth)])
    def bundle(review_id: str):
        """用户主动导出的一份素材和报告；不打包任何其他素材、配置或身份。"""
        report = get_review(review_id)
        folder = store.folder(review_id)
        content = BytesIO()
        with zipfile.ZipFile(content, 'w', zipfile.ZIP_DEFLATED) as archive:
            for name in ('source.mp4', 'preview.mp4'):
                file = folder/name
                if file.is_file() and not file.is_symlink():
                    archive.write(file, name)
            archive.writestr('report.json', json.dumps(report, ensure_ascii=False, indent=2))
            archive.writestr('NOTICE.txt', 'Contains the selected source video. Review privacy and rights before sharing. Not proof of contest submission, OpenCV5 or AWS eligibility.')
        return Response(content.getvalue(), media_type='application/zip', headers={'Content-Disposition': 'attachment; filename="evovid-review.zip"'})

    @app.delete('/api/reviews/{review_id}', dependencies=[Depends(auth)])
    def remove(review_id: str, confirmed: bool = False):
        """删除必须指定 ID 和二次确认标志，范围只限该 review 文件夹。"""
        if not confirmed:
            raise HTTPException(409, 'Confirm deletion first.')
        get_review(review_id)
        try:
            with store.exclusive():
                store.delete(review_id)
        except RuntimeError:
            raise HTTPException(409, 'Processing is busy.')
        return {'deleted': review_id}
