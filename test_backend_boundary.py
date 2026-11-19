import json
import tempfile
import unittest
from pathlib import Path

from backend.api_contract import ENDPOINTS, JOB_EVENTS
from backend.persistence import WorkspaceRepository
from backend.core import Bookmark, BookmarkStore


class BackendBoundaryTests(unittest.TestCase):
    def test_workspace_repository_migrates_legacy_json(self):
        legacy = {
            'Legacy': [{
                'title': 'Docs',
                'url': 'https://docs.example',
            }],
        }
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'legacy.json'
            destination = Path(directory) / 'workspace.json'
            source.write_text(json.dumps(legacy), encoding='utf-8')

            store = WorkspaceRepository.migrate(source, destination)
            payload = json.loads(destination.read_text(encoding='utf-8'))

        self.assertEqual(len(store.bookmarks), 1)
        self.assertEqual(payload['version'], BookmarkStore.SCHEMA_VERSION)
        self.assertEqual(
            payload['folders'][0]['bookmarks'][0]['title'],
            'Docs',
        )

    def test_workspace_repository_round_trips_current_store(self):
        store = BookmarkStore(uncategorized=[
            Bookmark('Example', 'https://example.com'),
        ])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'workspace.json'
            WorkspaceRepository(path).save(store)
            restored = WorkspaceRepository(path).load()

        self.assertEqual(restored.to_dict(), store.to_dict())

    def test_api_contract_covers_async_operations_and_crud(self):
        paths = {endpoint.path for endpoint in ENDPOINTS}

        self.assertIn('/api/workspace', paths)
        self.assertIn('/api/bookmarks/{bookmark_id}', paths)
        self.assertIn('/api/jobs/{job_id}/events', paths)
        self.assertTrue(any(
            endpoint.asynchronous
            for endpoint in ENDPOINTS
        ))
        self.assertIn('requires_review', JOB_EVENTS)
        self.assertIn('failed', JOB_EVENTS)


if __name__ == '__main__':
    unittest.main()
