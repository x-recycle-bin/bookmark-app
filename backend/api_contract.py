from dataclasses import dataclass


@dataclass(frozen=True)
class EndpointContract:
    method: str
    path: str
    description: str
    asynchronous: bool = False


ENDPOINTS = (
    EndpointContract('GET', '/api/workspace', 'Read the active workspace'),
    EndpointContract('PUT', '/api/workspace', 'Replace the active workspace'),
    EndpointContract('POST', '/api/import/html', 'Import browser bookmark HTML'),
    EndpointContract('GET', '/api/export/html', 'Export browser bookmark HTML'),
    EndpointContract('POST', '/api/folders', 'Create a folder'),
    EndpointContract('PATCH', '/api/folders/{folder_id}', 'Update a folder'),
    EndpointContract('DELETE', '/api/folders/{folder_id}', 'Delete a folder'),
    EndpointContract('POST', '/api/bookmarks', 'Create a bookmark'),
    EndpointContract('PATCH', '/api/bookmarks/{bookmark_id}', 'Update a bookmark'),
    EndpointContract(
        'DELETE',
        '/api/bookmarks/{bookmark_id}',
        'Delete a bookmark',
    ),
    EndpointContract(
        'POST',
        '/api/bookmarks/move',
        'Move multiple bookmarks',
    ),
    EndpointContract(
        'POST',
        '/api/duplicates/resolve',
        'Resolve duplicate bookmarks',
    ),
    EndpointContract(
        'POST',
        '/api/jobs/url-check',
        'Start URL validation',
        asynchronous=True,
    ),
    EndpointContract(
        'POST',
        '/api/jobs/ai-group',
        'Start AI grouping',
        asynchronous=True,
    ),
    EndpointContract(
        'POST',
        '/api/jobs/ai-sort-dates',
        'Start Dates folder sorting',
        asynchronous=True,
    ),
    EndpointContract(
        'GET',
        '/api/jobs/{job_id}/events',
        'Stream job events',
        asynchronous=True,
    ),
    EndpointContract(
        'DELETE',
        '/api/jobs/{job_id}',
        'Cancel a job',
        asynchronous=True,
    ),
)

JOB_EVENTS = (
    'queued',
    'running',
    'progress',
    'requires_review',
    'completed',
    'cancelled',
    'failed',
)
