import unittest
from pathlib import Path

from bookmark_app import BookmarkHTMLParser


def parse_bookmarks(html):
    parser = BookmarkHTMLParser()
    parser.feed(html)
    parser.close()
    return parser


class BookmarkHtmlParserTests(unittest.TestCase):
    def test_parses_nested_folders_and_bookmarks_bar_attribute(self):
        parser = parse_bookmarks("""
            <DL>
                <DT><H3 PERSONAL_TOOLBAR_FOLDER="TRUE">Toolbar</H3>
                <DL>
                    <DT><A HREF="https://root.example">Root</A>
                    <DT><H3>Learning</H3>
                    <DL>
                        <DT><A HREF="https://nested.example"
                            ADD_DATE="123">Nested</A>
                    </DL>
                </DL>
            </DL>
        """)

        self.assertEqual(len(parser.bookmarks), 2)
        toolbar = parser.store.folders[0]
        self.assertEqual(toolbar.name, 'Toolbar')
        self.assertTrue(toolbar.is_bookmarks_bar)
        self.assertEqual(toolbar.children[0].name, 'Learning')
        nested = toolbar.children[0].bookmarks[0]
        self.assertEqual(toolbar.metadata['personal_toolbar_folder'], 'TRUE')
        self.assertEqual(nested.original_folder, ('Toolbar', 'Learning'))
        self.assertEqual(nested.metadata['add_date'], '123')

    def test_decodes_entities_and_mixed_case_tags(self):
        parser = parse_bookmarks("""
            <dl><dt><h3>Research &amp; Docs</h3><DL>
                <DT><a href="https://example.com/?a=1&amp;b=2">
                    Guides <strong>&amp;</strong> References
                </a>
            </dl></DL>
        """)

        folder = parser.store.folders[0]
        self.assertEqual(folder.name, 'Research & Docs')
        self.assertEqual(folder.bookmarks[0].title, 'Guides & References')
        self.assertEqual(
            folder.bookmarks[0].url,
            'https://example.com/?a=1&b=2',
        )

    def test_preserves_empty_folders_and_uncategorized_bookmarks(self):
        parser = parse_bookmarks("""
            <DL>
                <DT><A HREF="https://uncategorized.example">Loose</A>
                <DT><H3>Empty</H3>
                <DL></DL>
            </DL>
        """)

        self.assertEqual(len(parser.store.uncategorized), 1)
        self.assertEqual(parser.store.folders[0].name, 'Empty')
        self.assertEqual(parser.store.folders[0].bookmarks, [])

    def test_counts_links_missing_title_or_url(self):
        parser = parse_bookmarks("""
            <DL>
                <DT><A HREF="">Missing URL</A>
                <DT><A>No URL at all</A>
                <DT><A HREF="https://title.example"> </A>
                <DT><A HREF="https://valid.example">Valid</A>
            </DL>
        """)

        self.assertEqual(len(parser.bookmarks), 1)
        self.assertEqual(parser.bookmarks[0].title, 'Valid')
        self.assertEqual(parser.skipped_links, 3)

    def test_detects_input_without_bookmark_list(self):
        parser = parse_bookmarks('<html><body>Not bookmarks</body></html>')

        self.assertTrue(parser.malformed_file)

    def test_real_sample_preserves_all_links_and_hierarchy(self):
        html = Path('short_bookmarks.html').read_text(encoding='utf-8')
        parser = parse_bookmarks(html)

        self.assertEqual(len(parser.bookmarks), 175)
        self.assertEqual(parser.skipped_links, 0)
        self.assertEqual(parser.store.folders[0].name, 'Bookmarks bar')
        self.assertTrue(parser.store.folders[0].is_bookmarks_bar)
        self.assertTrue(any(
            bookmark.original_folder[-1:] == ('IELTS',)
            for bookmark in parser.bookmarks
        ))


if __name__ == '__main__':
    unittest.main()
