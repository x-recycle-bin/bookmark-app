import json
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import requests

from bookmark_app import (
    AiConfig,
    AiOrganizer,
    AiResponseError,
    Bookmark,
    BookmarkApp,
    BookmarkFolder,
    BookmarkStore,
)


def response_with_assignments(assignments):
    response = Mock()
    response.status_code = 200
    response.raise_for_status.return_value = None
    response.json.return_value = {
        'choices': [{
            'message': {
                'content': json.dumps({'assignments': assignments}),
            },
        }],
    }
    return response


class AiOrganizerTests(unittest.TestCase):
    def setUp(self):
        self.bookmark = Bookmark(
            title='Python docs',
            url='https://docs.python.org',
            assignment_key='bookmark-1',
        )
        self.config = AiConfig(api_key='secret-key', retries=1)
        self.session = Mock()
        self.organizer = AiOrganizer(self.config, session=self.session)

    def test_classifies_batch_without_network_and_validates_result(self):
        self.session.post.return_value = response_with_assignments([{
            'assignment_key': 'bookmark-1',
            'folder': 'Programming / Python',
        }])

        result = self.organizer.classify_batch(
            [self.bookmark],
            ['Programming'],
        )

        self.assertEqual(
            result,
            {'bookmark-1': 'Programming / Python'},
        )
        request = self.session.post.call_args.kwargs
        self.assertEqual(request['json']['model'], 'gpt-4o-mini')
        self.assertEqual(
            request['headers']['Authorization'],
            'Bearer secret-key',
        )

    def test_rejects_partial_and_duplicate_assignments(self):
        for assignments in [
            [],
            [
                {
                    'assignment_key': 'bookmark-1',
                    'folder': 'Python',
                },
                {
                    'assignment_key': 'bookmark-1',
                    'folder': 'Docs',
                },
            ],
            [{
                'assignment_key': 'unknown',
                'folder': 'Python',
            }],
        ]:
            with self.subTest(assignments=assignments):
                payload = {'assignments': assignments}
                with self.assertRaises(AiResponseError):
                    AiOrganizer._validate_assignments(
                        payload,
                        [self.bookmark],
                    )

    def test_retries_transient_connection_failures_with_limit(self):
        self.session.post.side_effect = [
            requests.ConnectionError('offline'),
            response_with_assignments([{
                'assignment_key': 'bookmark-1',
                'folder': 'Python',
            }]),
        ]

        with patch('bookmark_app.time.sleep'):
            result = self.organizer.classify_batch([self.bookmark], [])

        self.assertEqual(result['bookmark-1'], 'Python')
        self.assertEqual(self.session.post.call_count, 2)

    def test_retries_transient_http_status_with_limit(self):
        unavailable = Mock(status_code=503)
        success = response_with_assignments([{
            'assignment_key': 'bookmark-1',
            'folder': 'Python',
        }])
        self.session.post.side_effect = [unavailable, success]

        with patch('bookmark_app.time.sleep'):
            result = self.organizer.classify_batch([self.bookmark], [])

        self.assertEqual(result['bookmark-1'], 'Python')
        self.assertEqual(self.session.post.call_count, 2)

    def test_never_includes_api_key_in_error_message(self):
        self.session.post.side_effect = requests.HTTPError('server rejected')

        with self.assertRaises(AiResponseError) as raised:
            self.organizer.classify_batch([self.bookmark], [])

        self.assertNotIn('secret-key', str(raised.exception))


class AiGroupingUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.root = tk.Tk()
            cls.root.withdraw()
        except tk.TclError as error:
            raise unittest.SkipTest(f'Tkinter display unavailable: {error}')

    @classmethod
    def tearDownClass(cls):
        cls.root.destroy()

    def setUp(self):
        self.app = BookmarkApp(self.root)

    def tearDown(self):
        for child in list(self.root.children.values()):
            child.destroy()

    def test_bookmarks_bar_assignments_are_protected(self):
        protected = Bookmark(
            title='Protected',
            url='https://protected.example',
        )
        store = BookmarkStore(folders=[
            BookmarkFolder(
                name='Toolbar',
                bookmarks=[protected],
                is_bookmarks_bar=True,
            ),
        ])

        self.assertEqual(
            store.protected_bookmark_keys(),
            {protected.assignment_key},
        )
        with self.assertRaisesRegex(ValueError, 'Bookmarks bar'):
            store.ensure_folder_path(('Toolbar',))

    def test_preview_does_not_replace_store_until_confirmed(self):
        bookmark = Bookmark('Python', 'https://python.example')
        current = BookmarkStore(uncategorized=[bookmark])
        proposed = BookmarkStore.from_dict(current.to_dict())
        self.app.store = current

        with patch('bookmark_app.messagebox.askyesno', return_value=False):
            self.app._preview_ai_grouping((
                proposed,
                {bookmark.assignment_key: 'Learning'},
                [],
                False,
            ))

        self.assertIs(self.app.store, current)

        with patch('bookmark_app.messagebox.askyesno', return_value=True):
            self.app._preview_ai_grouping((
                proposed,
                {bookmark.assignment_key: 'Learning'},
                [],
                False,
            ))

        self.assertIs(self.app.store, proposed)
        self.assertEqual(proposed.folders[0].bookmarks, [bookmark])

    def test_add_bookmark_works_without_ai_key(self):
        self.app.ai_config = AiConfig(api_key='')
        with patch(
            'bookmark_app.simpledialog.askstring',
            side_effect=['Manual', 'https://manual.example', 'Uncategorized'],
        ):
            self.app.add_bookmark()

        self.assertEqual(len(self.app.store.uncategorized), 1)
        self.assertEqual(self.app.store.uncategorized[0].title, 'Manual')


if __name__ == '__main__':
    unittest.main()
