import json
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from openai import APIConnectionError, APIStatusError

from bookmark_app import (
    AiConfig,
    AiOrganizer,
    AiResponseError,
    Bookmark,
    BookmarkApp,
    BookmarkFolder,
    BookmarkStore,
)


def agent_stream_with_assignments(assignments, session_id='sess_123'):
    result = Mock(
        output_text=json.dumps({'assignments': assignments}),
        session_id=session_id,
    )
    stream = MagicMock()
    stream.__iter__.return_value = iter([])
    stream.get_final_result.return_value = result
    context = MagicMock()
    context.__enter__.return_value = stream
    context.__exit__.return_value = False
    session_stream = Mock()
    session_stream.with_result_collection.return_value = context
    return session_stream


class AiOrganizerTests(unittest.TestCase):
    def setUp(self):
        self.bookmark = Bookmark(
            title='Python docs',
            url='https://docs.python.org',
            assignment_key='bookmark-1',
        )
        self.config = AiConfig(api_key='secret-key', retries=1)
        self.client = Mock()
        self.sessions = self.client.beta.agents.sessions
        self.organizer = AiOrganizer(self.config, client=self.client)

    def test_classifies_batch_without_network_and_validates_result(self):
        self.sessions.create.return_value = agent_stream_with_assignments([{
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
        request = self.sessions.create.call_args.kwargs
        self.assertEqual(request['agent']['model'], 'gpt-6-astra')
        self.assertEqual(request['environment'], {'type': 'none'})
        self.assertTrue(request['stream'])
        self.sessions.delete.assert_called_once_with('sess_123')

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
        self.sessions.create.side_effect = [
            APIConnectionError(request=Mock()),
            agent_stream_with_assignments([{
                'assignment_key': 'bookmark-1',
                'folder': 'Python',
            }]),
        ]

        with patch('backend.core.time.sleep'):
            result = self.organizer.classify_batch([self.bookmark], [])

        self.assertEqual(result['bookmark-1'], 'Python')
        self.assertEqual(self.sessions.create.call_count, 2)

    def test_existing_folders_only_rejects_invented_destination(self):
        self.sessions.create.return_value = agent_stream_with_assignments([{
            'assignment_key': 'bookmark-1',
            'folder': 'New AI Folder',
        }])

        with self.assertRaisesRegex(AiResponseError, 'does not exist'):
            self.organizer.classify_batch(
                [self.bookmark],
                ['Existing'],
                existing_folders_only=True,
            )

    def test_never_includes_api_key_in_error_message(self):
        self.sessions.create.side_effect = APIStatusError(
            'server rejected',
            response=Mock(status_code=500),
            body=None,
        )

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

    def test_finds_dates_folders_and_all_descendant_bookmarks(self):
        dated = Bookmark('Dated', 'https://dated.example')
        root = Bookmark(
            'Root dated',
            'https://root-dated.example',
        )
        ordinary = Bookmark('Ordinary', 'https://ordinary.example')
        store = BookmarkStore(folders=[
            BookmarkFolder(
                name='Даты',
                bookmarks=[root],
                children=[
                    BookmarkFolder(
                        name='2026-05-12',
                        bookmarks=[dated],
                    ),
                ],
            ),
            BookmarkFolder(name='Development', bookmarks=[ordinary]),
        ])

        paths = store.date_folder_paths()
        selected = store.bookmarks_under_paths(paths)
        destinations = [
            path
            for path in store.folder_paths
            if not store.is_path_within(path, paths)
        ]

        self.assertEqual(paths, [('Даты',)])
        self.assertEqual(selected, [root, dated])
        self.assertEqual(destinations, [('Development',)])

    def test_reference_file_identifies_dates_tree_and_existing_targets(self):
        from bookmark_app import BookmarkHTMLParser

        parser = BookmarkHTMLParser()
        parser.feed(Path('bookmarks_11_19_26.html').read_text(encoding='utf-8'))
        parser.close()

        source_paths = parser.store.date_folder_paths()
        selected = parser.store.bookmarks_under_paths(source_paths)
        destinations = [
            path
            for path in parser.store.folder_paths
            if not parser.store.is_path_within(path, source_paths)
        ]

        self.assertEqual(source_paths, [('Даты',)])
        self.assertGreater(len(selected), 0)
        self.assertGreater(len(destinations), 0)

    def test_preview_does_not_replace_store_until_confirmed(self):
        bookmark = Bookmark('Python', 'https://python.example')
        current = BookmarkStore(uncategorized=[bookmark])
        proposed = BookmarkStore.from_dict(current.to_dict())
        self.app.store = current

        with patch.object(
            self.app,
            '_confirm_ai_preview',
            return_value=False,
        ):
            self.app._preview_ai_grouping((
                proposed,
                {bookmark.assignment_key: 'Learning'},
                [],
                False,
            ))

        self.assertIs(self.app.store, current)

        with patch.object(
            self.app,
            '_confirm_ai_preview',
            return_value=True,
        ):
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

    def test_ai_preview_dialog_has_scrollbar_and_defaults_to_cancel(self):
        observations = []

        def inspect_dialog():
            dialog = next(
                child
                for child in self.root.winfo_children()
                if isinstance(child, tk.Toplevel)
                and child.title() == 'Review AI Organization'
            )

            widgets = [dialog]
            index = 0
            while index < len(widgets):
                widgets.extend(widgets[index].winfo_children())
                index += 1
            observations.append(any(
                isinstance(widget, tk.Text)
                for widget in widgets
            ))
            observations.append(any(
                isinstance(widget, tk.Scrollbar)
                for widget in widgets
            ))
            dialog.destroy()

        self.root.after(50, inspect_dialog)

        decision = self.app._confirm_ai_preview('A long proposal')

        self.assertFalse(decision)
        self.assertEqual(observations, [True, True])


if __name__ == '__main__':
    unittest.main()
