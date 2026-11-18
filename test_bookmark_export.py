import unittest

from bookmark_app import (
    Bookmark,
    BookmarkFolder,
    BookmarkHTMLParser,
    BookmarkStore,
    bookmark_store_to_html,
)


class BookmarkExportTests(unittest.TestCase):
    def test_export_round_trips_hierarchy_and_uncategorized_bookmarks(self):
        loose = Bookmark(
            title='Loose & Useful',
            url='https://example.com/?a=1&b=2',
            metadata={'add_date': '10'},
        )
        nested = Bookmark(
            title='Docs <Python>',
            url='https://docs.example/"quoted"',
            metadata={'last_modified': '20'},
        )
        store = BookmarkStore(
            uncategorized=[loose],
            folders=[
                BookmarkFolder(
                    name='Learning & Research',
                    is_bookmarks_bar=True,
                    metadata={'add_date': '5'},
                    children=[
                        BookmarkFolder(name='Python', bookmarks=[nested]),
                    ],
                ),
            ],
        )

        html = bookmark_store_to_html(store)
        parser = BookmarkHTMLParser()
        parser.feed(html)
        parser.close()

        self.assertEqual(
            [(bookmark.title, bookmark.url) for bookmark in parser.bookmarks],
            [
                ('Loose & Useful', 'https://example.com/?a=1&b=2'),
                ('Docs <Python>', 'https://docs.example/"quoted"'),
            ],
        )
        self.assertEqual(parser.store.uncategorized[0].title, 'Loose & Useful')
        self.assertEqual(
            parser.store.folders[0].children[0].bookmarks[0].original_folder,
            ('Learning & Research', 'Python'),
        )
        self.assertTrue(parser.store.folders[0].is_bookmarks_bar)

    def test_export_escapes_titles_urls_and_attributes(self):
        bookmark = Bookmark(
            title='<script>alert("x")</script>',
            url='https://example.com/?one="1"&two=<2>',
            metadata={'last_visit': 'a&b'},
        )
        html = bookmark_store_to_html(BookmarkStore(uncategorized=[bookmark]))

        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('LAST_VISIT="a&amp;b"', html)
        self.assertIn('&quot;1&quot;', html)


if __name__ == '__main__':
    unittest.main()
