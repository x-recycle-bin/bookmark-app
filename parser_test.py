from html.parser import HTMLParser
import json

class MyHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.bookmarks = []
        self.in_a = False
        self.current_url = None
        self.current_title = None

    def handle_starttag(self, tag, attrs):
        if tag == 'a':
            self.in_a = True
            for attr in attrs:
                if attr[0] == 'href':
                    self.current_url = attr[1]

    def handle_endtag(self, tag):
        if tag == 'a' and self.in_a:
            if self.current_url and self.current_title:
                self.bookmarks.append({'title': self.current_title, 'url': self.current_url})
            self.in_a = False
            self.current_url = None
            self.current_title = None

    def handle_data(self, data):
        if self.in_a:
            if self.current_title is None:
                self.current_title = data.strip()
            else:
                self.current_title += " " + data.strip()

with open("short_bookmarks.html", 'r', encoding='utf-8') as f:
    html = f.read()
parser = MyHTMLParser()
parser.feed(html)

print("Stop")