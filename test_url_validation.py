import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import requests

from bookmark_app import Bookmark, BookmarkApp, BookmarkStore


class UrlValidationTests(unittest.TestCase):
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

    def result_for(self, url, response, use_get=False):
        bookmark = Bookmark('Test', url)
        target = 'bookmark_app.requests.get' if use_get else 'bookmark_app.requests.head'
        with patch(target, return_value=response):
            return self.app._check_bookmark_url(bookmark)

    def response(self, status_code, history=None):
        response = Mock()
        response.status_code = status_code
        response.history = history or []
        return response

    def test_classifies_reachable_and_redirected_urls(self):
        self.assertEqual(
            self.result_for(
                'https://example.com',
                self.response(200)
            ).outcome,
            'reachable',
        )
        self.assertEqual(
            self.result_for(
                'https://example.com',
                self.response(200, history=[self.response(301)])
            ).outcome,
            'redirected',
        )

    def test_falls_back_to_get_when_head_is_rejected(self):
        bookmark = Bookmark('Fallback', 'https://example.com')
        get_response = self.response(200)
        with patch(
            'bookmark_app.requests.head',
            return_value=self.response(405)
        ), patch(
            'bookmark_app.requests.get',
            return_value=get_response
        ) as get:
            result = self.app._check_bookmark_url(bookmark)

        self.assertEqual(result.outcome, 'reachable')
        get.assert_called_once()
        get_response.close.assert_called_once()

    def test_classifies_error_timeout_and_invalid_url(self):
        self.assertEqual(
            self.result_for(
                'https://example.com',
                self.response(404)
            ).outcome,
            'client-error',
        )
        bookmark = Bookmark('Timeout', 'https://timeout.example')
        with patch(
            'bookmark_app.requests.head',
            side_effect=requests.Timeout('timed out')
        ):
            self.assertEqual(
                self.app._check_bookmark_url(bookmark).outcome,
                'timeout',
            )
        self.assertEqual(
            self.app._check_bookmark_url(
                Bookmark('Invalid', 'javascript:void(0)')
            ).outcome,
            'invalid-url',
        )

    def test_remove_bookmarks_removes_only_selected_assignments(self):
        first = Bookmark('Remove', 'https://remove.example')
        second = Bookmark('Keep', 'https://keep.example')
        store = BookmarkStore(uncategorized=[first, second])

        self.assertEqual(store.remove_bookmarks([first.assignment_key]), 1)
        self.assertEqual(store.bookmarks, [second])


if __name__ == '__main__':
    unittest.main()
