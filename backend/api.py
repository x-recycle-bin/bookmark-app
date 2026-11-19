import asyncio
import json
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import requests
from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    HTTPException,
    UploadFile,
)
from fastapi.responses import PlainTextResponse, StreamingResponse
from pydantic import BaseModel, Field
from urllib.parse import urlsplit

from .core import (
    AiConfig,
    AiOrganizer,
    Bookmark,
    BookmarkHTMLParser,
    BookmarkStore,
    bookmark_store_to_html,
)
from .persistence import WorkspaceRepository


class WorkspacePayload(BaseModel):
    workspace: dict


class FolderCreate(BaseModel):
    name: str
    parent_path: list[str] = Field(default_factory=list)


class FolderUpdate(BaseModel):
    path: list[str]
    name: str


class FolderDelete(BaseModel):
    path: list[str]


class BookmarkCreate(BaseModel):
    title: str
    url: str
    destination_path: list[str] = Field(default_factory=list)


class BookmarkUpdate(BaseModel):
    title: str
    url: str


class BookmarkMove(BaseModel):
    assignment_keys: list[str]
    destination_path: list[str] = Field(default_factory=list)


class DuplicateResolve(BaseModel):
    strategy: str


@dataclass
class Job:
    job_id: str
    kind: str
    status: str = 'queued'
    progress: int = 0
    total: int = 0
    events: list[dict] = field(default_factory=list)
    result: object = None
    error: str | None = None
    cancelled: threading.Event = field(default_factory=threading.Event)

    def publish(self, status, **details):
        self.status = status
        event = {
            'job_id': self.job_id,
            'type': status,
            **details,
        }
        self.events.append(event)

    def to_dict(self):
        return {
            'job_id': self.job_id,
            'kind': self.kind,
            'status': self.status,
            'progress': self.progress,
            'total': self.total,
            'result': self.result,
            'error': self.error,
        }


class WorkspaceService:
    def __init__(self, repository):
        self.repository = repository
        self.lock = threading.RLock()
        if repository.path.exists():
            self.store = repository.load()
        else:
            self.store = BookmarkStore()

    def snapshot(self):
        with self.lock:
            return BookmarkStore.from_dict(self.store.to_dict())

    def mutate(self, operation):
        with self.lock:
            store = BookmarkStore.from_dict(self.store.to_dict())
            result = operation(store)
            self.repository.save(store)
            self.store = store
            return result


class JobRegistry:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()

    def create(self, kind, total):
        job = Job(job_id=uuid4().hex, kind=kind, total=total)
        job.publish('queued')
        with self.lock:
            self.jobs[job.job_id] = job
        return job

    def get(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail='Job not found.')
        return job


def create_app(workspace_path=None):
    repository = WorkspaceRepository(
        workspace_path
        or os.environ.get(
            'BOOKMARK_WORKSPACE_FILE',
            'data/workspace.json',
        )
    )
    workspace = WorkspaceService(repository)
    jobs = JobRegistry()
    app = FastAPI(title='Bookmark Organizer API', version='1.0.0')
    app.state.workspace = workspace
    app.state.jobs = jobs

    def workspace_response(result=None):
        payload = {'workspace': workspace.snapshot().to_dict()}
        if result is not None:
            payload['result'] = result
        return payload

    @app.get('/health')
    def health():
        return {'status': 'ok'}

    @app.get('/api/workspace')
    def get_workspace():
        return workspace_response()

    @app.put('/api/workspace')
    def replace_workspace(payload: WorkspacePayload):
        with workspace.lock:
            store = BookmarkStore.from_dict(payload.workspace)
            workspace.repository.save(store)
            workspace.store = store
        return workspace_response()

    @app.post('/api/import/html')
    async def import_html(file: UploadFile = File(...)):
        if file.content_type not in {'text/html', 'application/octet-stream'}:
            raise HTTPException(status_code=415, detail='Expected HTML upload.')
        content = await file.read()
        try:
            html = content.decode('utf-8')
        except UnicodeDecodeError as error:
            raise HTTPException(
                status_code=422,
                detail='Bookmark HTML must be UTF-8.',
            ) from error
        parser = BookmarkHTMLParser()
        parser.feed(html)
        parser.close()
        if parser.malformed_file or not parser.bookmarks:
            raise HTTPException(
                status_code=422,
                detail='The upload is not a usable Netscape bookmark file.',
            )

        with workspace.lock:
            workspace.repository.save(parser.store)
            workspace.store = parser.store
        return workspace_response({
            'imported': len(parser.bookmarks),
            'skipped': parser.skipped_links,
        })

    @app.get('/api/export/html')
    def export_html():
        html = bookmark_store_to_html(workspace.snapshot())
        return PlainTextResponse(html, media_type='text/html; charset=utf-8')

    @app.post('/api/folders')
    def create_folder(payload: FolderCreate):
        result = workspace.mutate(
            lambda store: store.create_folder(
                payload.name,
                payload.parent_path,
            )
        )
        return workspace_response({'name': result.name})

    @app.patch('/api/folders/{folder_id}')
    def update_folder(folder_id: str, payload: FolderUpdate):
        del folder_id
        workspace.mutate(
            lambda store: store.rename_folder(payload.path, payload.name)
        )
        return workspace_response()

    @app.delete('/api/folders/{folder_id}')
    def delete_folder(folder_id: str, payload: FolderDelete):
        del folder_id
        workspace.mutate(lambda store: store.delete_folder(payload.path))
        return workspace_response()

    @app.post('/api/bookmarks')
    def create_bookmark(payload: BookmarkCreate):
        bookmark = Bookmark(payload.title, payload.url)

        def create(store):
            if payload.destination_path:
                folder = store._require_folder(payload.destination_path)
                folder.bookmarks.append(bookmark)
            else:
                store.uncategorized.append(bookmark)
            store.validate()
            return bookmark.assignment_key

        return workspace_response({'assignment_key': workspace.mutate(create)})

    @app.patch('/api/bookmarks/{bookmark_id}')
    def update_bookmark(bookmark_id: str, payload: BookmarkUpdate):
        workspace.mutate(
            lambda store: store.update_bookmark(
                bookmark_id,
                payload.title,
                payload.url,
            )
        )
        return workspace_response()

    @app.delete('/api/bookmarks/{bookmark_id}')
    def delete_bookmark(bookmark_id: str):
        result = workspace.mutate(
            lambda store: store.remove_bookmarks([bookmark_id])
        )
        return workspace_response({'removed': result})

    @app.post('/api/bookmarks/move')
    def move_bookmarks(payload: BookmarkMove):
        result = workspace.mutate(
            lambda store: store.move_bookmarks(
                payload.assignment_keys,
                payload.destination_path,
            )
        )
        return workspace_response({'moved': result})

    @app.post('/api/duplicates/resolve')
    def resolve_duplicates(payload: DuplicateResolve):
        result = workspace.mutate(
            lambda store: store.resolve_duplicates(payload.strategy)
        )
        return workspace_response({'changed': result})

    @app.post('/api/jobs/url-check')
    def start_url_check(background_tasks: BackgroundTasks):
        store = workspace.snapshot()
        job = jobs.create('url-check', len(store.bookmarks))
        background_tasks.add_task(_run_url_check, job, store.bookmarks)
        return job.to_dict()

    @app.post('/api/jobs/ai-group')
    def start_ai_group(background_tasks: BackgroundTasks):
        return _start_ai_job(background_tasks, jobs, workspace.snapshot(), False)

    @app.post('/api/jobs/ai-sort-dates')
    def start_ai_sort_dates(background_tasks: BackgroundTasks):
        return _start_ai_job(background_tasks, jobs, workspace.snapshot(), True)

    @app.get('/api/jobs/{job_id}')
    def get_job(job_id: str):
        return jobs.get(job_id).to_dict()

    @app.get('/api/jobs/{job_id}/events')
    async def job_events(job_id: str):
        job = jobs.get(job_id)

        async def stream():
            sent = 0
            while True:
                while sent < len(job.events):
                    event = job.events[sent]
                    sent += 1
                    yield f'data: {json.dumps(event)}\n\n'
                if job.status in {
                    'completed',
                    'cancelled',
                    'failed',
                } and sent >= len(job.events):
                    return
                await asyncio.sleep(0.1)

        return StreamingResponse(
            stream(),
            media_type='text/event-stream',
        )

    @app.delete('/api/jobs/{job_id}')
    def cancel_job(job_id: str):
        job = jobs.get(job_id)
        job.cancelled.set()
        if job.status in {'queued', 'running'}:
            job.publish('cancelled')
        return job.to_dict()

    @app.exception_handler(ValueError)
    async def value_error_handler(_request, error):
        return _json_error(422, str(error))

    return app


def _json_error(status_code, detail):
    from fastapi.responses import JSONResponse

    return JSONResponse(status_code=status_code, content={'detail': detail})


def _start_ai_job(background_tasks, jobs, source_store, dates_only):
    try:
        config = AiConfig.from_environment()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    if not config.api_key:
        raise HTTPException(status_code=422, detail='OPENAI_API_KEY is required.')

    protected = source_store.protected_bookmark_keys()
    source_paths = source_store.date_folder_paths() if dates_only else []
    bookmarks = (
        source_store.bookmarks_under_paths(source_paths)
        if dates_only
        else [
            bookmark
            for bookmark in source_store.bookmarks
            if bookmark.assignment_key not in protected
        ]
    )
    if not bookmarks:
        raise HTTPException(
            status_code=422,
            detail='No bookmarks match the requested AI operation.',
        )
    destination_paths = [
        path
        for path in source_store.folder_paths
        if not (dates_only and source_store.is_path_within(path, source_paths))
        and not _is_protected_folder_path(path, source_store)
    ]
    job = jobs.create('ai-sort-dates' if dates_only else 'ai-group', len(bookmarks))
    background_tasks.add_task(
        _run_ai_job,
        job,
        source_store,
        bookmarks,
        destination_paths,
        config,
        dates_only,
    )
    return job.to_dict()


def _run_url_check(job, bookmarks):
    job.publish('running')
    results = []
    try:
        for bookmark in bookmarks:
            if job.cancelled.is_set():
                job.publish('cancelled')
                return
            result = _check_url(bookmark)
            results.append(result)
            job.progress += 1
            job.publish(
                'progress',
                completed=job.progress,
                total=job.total,
            )
        job.result = results
        job.publish('requires_review')
    except Exception as error:
        job.error = error.__class__.__name__
        job.publish('failed', error=job.error)


def _check_url(bookmark):
    parsed = urlsplit(bookmark.url)
    if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
        return {
            'assignment_key': bookmark.assignment_key,
            'outcome': 'invalid-url',
            'detail': 'Only HTTP and HTTPS URLs can be checked.',
        }
    try:
        response = requests.head(
            bookmark.url,
            timeout=5,
            allow_redirects=True,
        )
        if response.status_code in {405, 501}:
            response = requests.get(
                bookmark.url,
                timeout=5,
                allow_redirects=True,
                stream=True,
            )
            response.close()
        if response.status_code < 400:
            outcome = 'redirected' if response.history else 'reachable'
        elif response.status_code < 500:
            outcome = 'client-error'
        else:
            outcome = 'server-error'
        detail = str(response.status_code)
    except requests.Timeout as error:
        outcome = 'timeout'
        detail = str(error)
    except requests.RequestException as error:
        outcome = 'network-error'
        detail = str(error)
    return {
        'assignment_key': bookmark.assignment_key,
        'outcome': outcome,
        'detail': detail,
    }


def _run_ai_job(
    job,
    source_store,
    bookmarks,
    destination_paths,
    config,
    existing_only,
):
    job.publish('running')
    organizer = AiOrganizer(config)
    folder_names = [' / '.join(path) for path in destination_paths]
    assignments = {}
    failures = []
    try:
        for start in range(0, len(bookmarks), config.batch_size):
            if job.cancelled.is_set():
                job.publish('cancelled')
                return
            batch = bookmarks[start:start + config.batch_size]
            try:
                assignments.update(organizer.classify_batch(
                    batch,
                    folder_names,
                    existing_folders_only=existing_only,
                ))
            except ValueError as error:
                failures.append({
                    'batch': start // config.batch_size + 1,
                    'error': error.__class__.__name__,
                })
            job.progress += len(batch)
            job.publish(
                'progress',
                completed=job.progress,
                total=job.total,
            )

        proposed = BookmarkStore.from_dict(source_store.to_dict())
        for assignment_key, folder_name in assignments.items():
            destination = proposed.ensure_folder_path(
                tuple(part.strip() for part in folder_name.split(' / '))
            )
            proposed.move_bookmark(assignment_key, destination)
        proposed.validate()
        job.result = {
            'workspace': proposed.to_dict(),
            'classified': len(assignments),
            'failures': failures,
        }
        job.publish('requires_review')
    except Exception as error:
        job.error = error.__class__.__name__
        job.publish('failed', error=job.error)


def _is_protected_folder_path(path, store):
    return any(
        (folder := store.find_folder(path[:index])) is not None
        and folder.is_bookmarks_bar
        for index in range(1, len(path) + 1)
    )


app = create_app()
