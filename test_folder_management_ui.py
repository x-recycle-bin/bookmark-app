import tkinter as tk
import unittest
from unittest.mock import patch

from bookmark_app import Bookmark, BookmarkApp, BookmarkFolder


class FolderManagementUiTests(unittest.TestCase):
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

    def test_tree_displays_folders_and_bookmarks(self):
        bookmark = Bookmark(
            title='Docs',
            url='https://docs.example',
            assignment_key='docs',
        )
        self.app.store.folders.append(
            BookmarkFolder(name='Reference', bookmarks=[bookmark])
        )

        self.app.refresh_bookmark_views()

        self.assertTrue(any(
            self.app.tree.item(item_id, 'text').startswith('Reference')
            for item_id in self.app.tree.get_children()
        ))
        self.assertEqual(self.app.listbox.get(0), 'Docs - https://docs.example')

    def test_move_selected_bookmark_updates_store_and_tree(self):
        bookmark = Bookmark(
            title='Example',
            url='https://example.com',
            assignment_key='example',
        )
        self.app.store.uncategorized.append(bookmark)
        self.app.store.create_folder('Later')
        self.app.refresh_bookmark_views()
        self.app.listbox.selection_set(0)

        with patch(
            'bookmark_app.simpledialog.askstring',
            return_value='Later'
        ):
            self.app.move_selected_bookmark()

        self.assertEqual(self.app.store.uncategorized, [])
        self.assertEqual(self.app.store.folders[0].bookmarks, [bookmark])
        self.assertEqual(self.app.listbox.size(), 1)

    def test_delete_folder_requires_confirmation_and_preserves_bookmarks(self):
        bookmark = Bookmark(
            title='Keep',
            url='https://keep.example',
            assignment_key='keep',
        )
        self.app.store.folders.append(
            BookmarkFolder(name='Temporary', bookmarks=[bookmark])
        )
        self.app.refresh_bookmark_views()
        folder_item = next(
            item_id
            for item_id in self.app.tree.get_children()
            if self.app._tree_folder_paths.get(item_id) == ('Temporary',)
        )
        self.app.tree.selection_set(folder_item)

        with patch('bookmark_app.messagebox.askyesno', return_value=False):
            self.app.delete_folder()
        self.assertEqual(len(self.app.store.folders), 1)

        with patch('bookmark_app.messagebox.askyesno', return_value=True):
            self.app.delete_folder()
        self.assertEqual(self.app.store.folders, [])
        self.assertEqual(self.app.store.uncategorized, [bookmark])


if __name__ == '__main__':
    unittest.main()
