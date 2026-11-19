import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.api import create_app
from backend.api_contract import ENDPOINTS


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.workspace_path = Path(self.temporary.name) / 'workspace.json'
        self.client = TestClient(create_app(self.workspace_path))

    def tearDown(self):
        self.temporary.cleanup()

    def test_health_and_empty_workspace(self):
        self.assertEqual(
            self.client.get('/health').json(),
            {'status': 'ok'},
        )
        response = self.client.get('/api/workspace')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['workspace']['version'], 1)

    def test_import_export_and_bookmark_crud_persist(self):
        files = {
            'file': (
                'bookmarks.html',
                b'<DL><DT><A HREF="https://example.com">Example</A></DL>',
                'text/html',
            ),
        }
        response = self.client.post('/api/import/html', files=files)
        self.assertEqual(response.status_code, 200)
        bookmark = response.json()['workspace']['bookmarks'][0]

        update = self.client.patch(
            f"/api/bookmarks/{bookmark['assignment_key']}",
            json={'title': 'Updated', 'url': 'https://updated.example'},
        )
        self.assertEqual(update.status_code, 200)

        exported = self.client.get('/api/export/html')
        self.assertIn('Updated', exported.text)
        self.assertIn('https://updated.example', exported.text)

        removed = self.client.delete(
            f"/api/bookmarks/{bookmark['assignment_key']}"
        )
        self.assertEqual(removed.status_code, 200)
        self.assertEqual(
            removed.json()['workspace']['bookmarks'],
            [],
        )
        self.assertTrue(self.workspace_path.exists())

    def test_folder_and_bulk_move_operations(self):
        folder = self.client.post(
            '/api/folders',
            json={'name': 'Reference', 'parent_path': []},
        )
        self.assertEqual(folder.status_code, 200)
        created = self.client.post(
            '/api/bookmarks',
            json={
                'title': 'Docs',
                'url': 'https://docs.example',
                'destination_path': [],
            },
        )
        bookmark = created.json()['workspace']['bookmarks'][0]

        moved = self.client.post(
            '/api/bookmarks/move',
            json={
                'assignment_keys': [bookmark['assignment_key']],
                'destination_path': ['Reference'],
            },
        )

        self.assertEqual(moved.status_code, 200)
        self.assertEqual(moved.json()['workspace']['bookmarks'], [])
        self.assertEqual(
            moved.json()['workspace']['folders'][0]['bookmarks'][0]['title'],
            'Docs',
        )

    def test_invalid_workspace_is_rejected_without_overwrite(self):
        self.client.put(
            '/api/workspace',
            json={
                'workspace': {
                    'version': 1,
                    'bookmarks': [],
                    'folders': [],
                },
            },
        )
        before = self.workspace_path.read_text(encoding='utf-8')

        response = self.client.put(
            '/api/workspace',
            json={'workspace': {'version': 999}},
        )

        self.assertEqual(response.status_code, 422)
        self.assertEqual(
            self.workspace_path.read_text(encoding='utf-8'),
            before,
        )

    def test_url_job_reaches_review_state(self):
        self.client.post(
            '/api/bookmarks',
            json={
                'title': 'Example',
                'url': 'https://example.com',
                'destination_path': [],
            },
        )
        response = Mock(status_code=200, history=[])
        with patch('backend.api.requests.head', return_value=response):
            started = self.client.post('/api/jobs/url-check')
            job_id = started.json()['job_id']
            job = self.client.get(f'/api/jobs/{job_id}').json()

        self.assertEqual(started.status_code, 200)
        self.assertEqual(job['status'], 'requires_review')
        self.assertEqual(job['result'][0]['outcome'], 'reachable')

    def test_ai_job_requires_server_side_key(self):
        with patch.dict('os.environ', {'OPENAI_API_KEY': ''}):
            response = self.client.post('/api/jobs/ai-group')

        self.assertEqual(response.status_code, 422)
        self.assertIn('OPENAI_API_KEY', response.text)

    def test_ai_job_returns_preview_without_applying_it(self):
        self.client.post(
            '/api/folders',
            json={'name': 'Learning', 'parent_path': []},
        )
        self.client.post(
            '/api/bookmarks',
            json={
                'title': 'Python',
                'url': 'https://python.example',
                'destination_path': [],
            },
        )
        organizer = Mock()
        organizer.classify_batch.return_value = {
            next(iter(
                self.client.get('/api/workspace').json()['workspace'][
                    'bookmarks'
                ]
            ))['assignment_key']: 'Learning',
        }
        with patch.dict(
            'os.environ',
            {'OPENAI_API_KEY': 'test-key'},
        ), patch('backend.api.AiOrganizer', return_value=organizer):
            started = self.client.post('/api/jobs/ai-group')
            job_id = started.json()['job_id']
            job = self.client.get(f'/api/jobs/{job_id}').json()

        self.assertEqual(started.status_code, 200)
        self.assertEqual(job['status'], 'requires_review')
        self.assertEqual(job['result']['classified'], 1)
        current = self.client.get('/api/workspace').json()['workspace']
        self.assertEqual(len(current['bookmarks']), 1)
        self.assertEqual(current['folders'][0]['bookmarks'], [])

    def test_every_static_contract_route_is_registered(self):
        app = self.client.app
        registered = {
            (method, route.path)
            for route in app.routes
            for method in getattr(route, 'methods', set())
        }
        for endpoint in ENDPOINTS:
            self.assertIn(
                (endpoint.method, endpoint.path),
                registered,
                endpoint.path,
            )


if __name__ == '__main__':
    unittest.main()
