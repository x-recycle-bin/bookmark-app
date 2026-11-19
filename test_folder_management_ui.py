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
        bookmark_items = [
            item_id
            for item_id, key in self.app._tree_bookmark_keys.items()
            if key == 'docs'
        ]
        self.assertEqual(len(bookmark_items), 1)
        self.assertTrue(
            self.app.tree.item(bookmark_items[0], 'text').startswith('Docs')
        )

    def test_move_selected_bookmark_updates_store_and_tree(self):
        bookmark = Bookmark(
            title='Example',
            url='https://example.com',
            assignment_key='example',
        )
        self.app.store.uncategorized.append(bookmark)
        self.app.store.create_folder('Later')
        self.app.refresh_bookmark_views()
        bookmark_item = next(
            item_id
            for item_id, key in self.app._tree_bookmark_keys.items()
            if key == 'example'
        )
        self.app.tree.selection_set(bookmark_item)

        with patch(
            'bookmark_app.simpledialog.askstring',
            return_value='Later'
        ):
            self.app.move_selected_bookmark()

        self.assertEqual(self.app.store.uncategorized, [])
        self.assertEqual(self.app.store.folders[0].bookmarks, [bookmark])
        self.assertEqual(len(self.app._tree_bookmark_keys), 1)

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

    def test_tree_supports_multiple_bookmark_selection_and_delete(self):
        first = Bookmark('First', 'https://first.example', assignment_key='first')
        second = Bookmark(
            'Second',
            'https://second.example',
            assignment_key='second',
        )
        self.app.store.uncategorized.extend([first, second])
        self.app.refresh_bookmark_views()
        items = [
            item_id
            for item_id, key in self.app._tree_bookmark_keys.items()
            if key in {'first', 'second'}
        ]
        self.app.tree.selection_set(items)

        with patch('bookmark_app.messagebox.askyesno', return_value=True):
            self.app.delete_selected_bookmarks()

        self.assertEqual(self.app.store.bookmarks, [])
        self.assertEqual(str(self.app.tree['selectmode']), 'extended')

    def test_drag_bookmark_moves_to_target_folder(self):
        bookmark = Bookmark(
            'Dragged',
            'https://dragged.example',
            assignment_key='dragged',
        )
        self.app.store.uncategorized.append(bookmark)
        self.app.store.create_folder('Target')
        self.app.refresh_bookmark_views()
        bookmark_item = next(
            item_id
            for item_id, key in self.app._tree_bookmark_keys.items()
            if key == 'dragged'
        )
        target_item = next(
            item_id
            for item_id, path in self.app._tree_folder_paths.items()
            if path == ('Target',)
        )
        self.app._drag_items = (bookmark_item,)
        with patch.object(
            self.app.tree,
            'identify_row',
            return_value=target_item,
        ):
            self.app._finish_drag(type('Event', (), {'y': 1})())

        self.assertEqual(self.app.store.uncategorized, [])
        self.assertEqual(self.app.store.folders[0].bookmarks, [bookmark])

    def test_edit_and_bulk_delete_are_exposed(self):
        self.assertTrue(self.app.edit_bookmark_btn.winfo_exists())
        self.assertTrue(self.app.delete_bookmark_btn.winfo_exists())

    def test_folder_drag_does_not_move_folder(self):
        self.app.store.folders.extend([
            BookmarkFolder(name='Source'),
            BookmarkFolder(name='Target'),
        ])
        self.app.refresh_bookmark_views()
        source_item = next(
            item_id
            for item_id, path in self.app._tree_folder_paths.items()
            if path == ('Source',)
        )
        target_item = next(
            item_id
            for item_id, path in self.app._tree_folder_paths.items()
            if path == ('Target',)
        )
        press = type(
            'PressEvent',
            (),
            {'y': 1, 'x_root': 1, 'y_root': 1},
        )()
        release = type('ReleaseEvent', (), {'y': 1})()
        self.app.tree.selection_set(source_item)

        with patch.object(
            self.app.tree,
            'identify_row',
            side_effect=[source_item, target_item],
        ):
            self.app._begin_drag(press)
            self.app._finish_drag(release)

        self.assertEqual(
            self.app.store.folder_paths,
            [('Source',), ('Target',)],
        )


if __name__ == '__main__':
    unittest.main()
