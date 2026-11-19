import unittest

from bookmark_app import (
    Bookmark,
    BookmarkFolder,
    BookmarkStore,
    normalize_bookmark_url,
)


class BookmarkModelTests(unittest.TestCase):
    def test_store_round_trips_nested_folders_and_metadata(self):
        bookmark = Bookmark(
            title='Example',
            url='https://example.com',
            assignment_key='bookmark-1',
            original_folder=('Learning', 'Python'),
            metadata={'add_date': '123'},
        )
        store = BookmarkStore(folders=[
            BookmarkFolder(
                name='Learning',
                children=[
                    BookmarkFolder(name='Python', bookmarks=[bookmark]),
                ],
            ),
        ])

        restored = BookmarkStore.from_dict(store.to_dict())

        self.assertEqual(restored.bookmarks, [bookmark])
        self.assertEqual(
            list(restored.flattened_folders),
            ['Learning', 'Learning / Python'],
        )
        self.assertEqual(restored.to_dict(), store.to_dict())

    def test_legacy_folder_json_is_converted_to_typed_model(self):
        store = BookmarkStore.from_dict({
            'Docs': [{'title': 'Reference', 'url': 'https://docs.example'}],
        })

        self.assertIsInstance(store.folders[0], BookmarkFolder)
        self.assertIsInstance(store.bookmarks[0], Bookmark)
        self.assertEqual(store.folders[0].name, 'Docs')

    def test_assignment_key_can_exist_only_once(self):
        bookmark = Bookmark(
            title='Duplicate assignment',
            url='https://example.com',
            assignment_key='same-key',
        )

        with self.assertRaisesRegex(ValueError, 'more than one location'):
            BookmarkStore(folders=[
                BookmarkFolder(name='One', bookmarks=[bookmark]),
                BookmarkFolder(name='Two', bookmarks=[bookmark]),
            ])

    def test_duplicate_urls_are_distinct_when_assignment_keys_differ(self):
        first = Bookmark(
            title='First',
            url='https://example.com',
            assignment_key='first',
        )
        second = Bookmark(
            title='Second',
            url='https://example.com',
            assignment_key='second',
        )

        store = BookmarkStore(uncategorized=[first, second])

        self.assertEqual(store.bookmarks, [first, second])

    def test_blank_bookmark_fields_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'title cannot be empty'):
            Bookmark(title=' ', url='https://example.com')
        with self.assertRaisesRegex(ValueError, 'URL cannot be empty'):
            Bookmark(title='Example', url=' ')

    def test_creates_renames_and_deletes_folders_without_losing_bookmarks(self):
        store = BookmarkStore()
        folder = store.create_folder('Learning')
        nested = store.create_folder('Python', ('Learning',))
        bookmark = Bookmark(
            title='Docs',
            url='https://docs.example',
            assignment_key='docs',
        )
        nested.bookmarks.append(bookmark)

        store.rename_folder(('Learning',), 'Study')

        self.assertEqual(
            [path for path in store.folder_paths],
            [('Study',), ('Study', 'Python')],
        )
        store.delete_folder(('Study', 'Python'))
        self.assertNotIn(('Study', 'Python'), store.folder_paths)
        self.assertEqual(store.folders[0].bookmarks, [bookmark])

    def test_moves_bookmark_between_folder_and_uncategorized_once(self):
        bookmark = Bookmark(
            title='Example',
            url='https://example.com',
            assignment_key='move-me',
        )
        store = BookmarkStore(uncategorized=[bookmark])
        store.create_folder('Reference')

        store.move_bookmark('move-me', ('Reference',))
        self.assertEqual(store.uncategorized, [])
        self.assertEqual(store.folders[0].bookmarks, [bookmark])

        store.move_bookmark('move-me')
        self.assertEqual(store.uncategorized, [bookmark])
        self.assertEqual(store.folders[0].bookmarks, [])

    def test_bookmarks_bar_is_protected_from_rename_and_delete(self):
        store = BookmarkStore(folders=[
            BookmarkFolder(name='Bookmarks bar', is_bookmarks_bar=True),
        ])

        with self.assertRaisesRegex(ValueError, 'cannot be renamed'):
            store.rename_folder(('Bookmarks bar',), 'Other')
        with self.assertRaisesRegex(ValueError, 'cannot be deleted'):
            store.delete_folder(('Bookmarks bar',))

    def test_duplicate_urls_are_normalized(self):
        self.assertEqual(
            normalize_bookmark_url(' HTTPS://EXAMPLE.com/path/#section '),
            normalize_bookmark_url('https://example.com/path'),
        )

        store = BookmarkStore(uncategorized=[
            Bookmark('One', 'HTTPS://EXAMPLE.com/path/#first'),
            Bookmark('Two', 'https://example.com/path'),
            Bookmark('Other', 'https://example.com/different'),
        ])
        self.assertEqual(len(store.duplicate_groups()), 1)
        self.assertEqual(len(store.duplicate_groups()[0]), 2)

    def test_keep_first_removes_only_duplicate_copies(self):
        store = BookmarkStore(uncategorized=[
            Bookmark('First', 'https://example.com'),
            Bookmark('Second', 'https://example.com/'),
            Bookmark('Unique', 'https://other.example'),
        ])

        changed = store.resolve_duplicates('keep-first')

        self.assertEqual(changed, 1)
        self.assertEqual(
            [bookmark.title for bookmark in store.bookmarks],
            ['First', 'Unique'],
        )

    def test_merge_folder_keeps_duplicate_records_in_first_location(self):
        first = Bookmark('First', 'https://example.com/one#first')
        second = Bookmark('Second', 'HTTPS://EXAMPLE.COM/one#second')
        store = BookmarkStore(
            folders=[
                BookmarkFolder(name='Reference', bookmarks=[first]),
                BookmarkFolder(name='Other', bookmarks=[second]),
            ],
        )

        changed = store.resolve_duplicates('merge-folder')

        self.assertEqual(changed, 1)
        self.assertEqual(store.folders[0].bookmarks, [first, second])
        self.assertEqual(store.folders[1].bookmarks, [])

    def test_bulk_bookmark_crud_operations_keep_assignments_unique(self):
        first = Bookmark('First', 'https://first.example', assignment_key='first')
        second = Bookmark('Second', 'https://second.example', assignment_key='second')
        store = BookmarkStore(uncategorized=[first, second])
        store.create_folder('Target')

        self.assertEqual(
            store.move_bookmarks(['first', 'second'], ('Target',)),
            2,
        )
        updated = store.update_bookmark(
            'first',
            'Updated',
            'https://updated.example',
        )
        self.assertEqual(updated.assignment_key, 'first')
        self.assertEqual(updated.title, 'Updated')
        self.assertEqual(store.remove_bookmarks(['first']), 1)
        self.assertEqual(store.bookmarks, [second])

    def test_folder_drag_move_prevents_cycles_and_toolbar_moves(self):
        toolbar = BookmarkFolder(
            name='Toolbar',
            is_bookmarks_bar=True,
        )
        nested = BookmarkFolder(name='Nested')
        parent = BookmarkFolder(name='Parent', children=[nested])
        target = BookmarkFolder(name='Target')
        store = BookmarkStore(folders=[toolbar, parent, target])

        store.move_folder(('Target',), ('Parent',))
        self.assertEqual(parent.children, [nested, target])
        with self.assertRaisesRegex(ValueError, 'inside itself'):
            store.move_folder(('Parent',), ('Parent', 'Nested'))
        with self.assertRaisesRegex(ValueError, 'cannot be moved'):
            store.move_folder(('Toolbar',), ('Parent',))
        with self.assertRaisesRegex(ValueError, 'Bookmarks bar'):
            store.move_folder(('Parent', 'Nested'), ('Toolbar',))


if __name__ == '__main__':
    unittest.main()
