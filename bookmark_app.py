import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import threading
import requests
import os
import json
from html.parser import HTMLParser

class BookmarkHTMLParser(HTMLParser):
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
            self.current_title = data.strip()

class BookmarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title('Bookmark Organizer')
        self.bookmarks = []
        self.collections = {'Study': [], 'Work': [], 'Shopping': []}
        self.api_key = None
        self.create_widgets()

    def create_widgets(self):
        frame = tk.Frame(self.root)
        frame.pack(padx=10, pady=10)

        self.import_btn = tk.Button(frame, text='Import Bookmarks', command=self.import_bookmarks)
        self.import_btn.grid(row=0, column=0, padx=5, pady=5)

        self.check_btn = tk.Button(frame, text='Check URLs', command=self.check_urls)
        self.check_btn.grid(row=0, column=1, padx=5, pady=5)

        self.save_btn = tk.Button(frame, text='Save Collections', command=self.save_collections)
        self.save_btn.grid(row=0, column=2, padx=5, pady=5)

        self.load_btn = tk.Button(frame, text='Load Collections', command=self.load_collections)
        self.load_btn.grid(row=0, column=3, padx=5, pady=5)

        self.ai_group_btn = tk.Button(frame, text='AI Group Bookmarks', command=self.ai_group_bookmarks)
        self.ai_group_btn.grid(row=0, column=4, padx=5, pady=5)

        self.settings_btn = tk.Button(frame, text='Settings', command=self.open_settings)
        self.settings_btn.grid(row=0, column=5, padx=5, pady=5)

        self.add_bm_btn = tk.Button(frame, text='Add Bookmark', command=self.add_bookmark)
        self.add_bm_btn.grid(row=0, column=6, padx=5, pady=5)

        self.listbox = tk.Listbox(frame, width=80, height=15)
        self.listbox.grid(row=1, column=0, columnspan=7, pady=10)
        self.listbox.bind('<Double-Button-1>', self.add_to_collection)

        self.status = tk.Label(frame, text='Status: Ready')
        self.status.grid(row=2, column=0, columnspan=7)

    def import_bookmarks(self):
        file_path = filedialog.askopenfilename(filetypes=[('HTML files', '*.html')])
        if not file_path:
            return
        with open(file_path, 'r', encoding='utf-8') as f:
            html = f.read()
        parser = BookmarkHTMLParser()
        parser.feed(html)
        self.bookmarks = parser.bookmarks
        self.refresh_listbox()
        self.status.config(text=f'Imported {len(self.bookmarks)} bookmarks.')

    def refresh_listbox(self, show_collections=False):
        self.listbox.delete(0, tk.END)
        if show_collections and self.collections:
            for collection, bookmarks in self.collections.items():
                for bm in bookmarks:
                    self.listbox.insert(tk.END, f"[{collection}] {bm['title']} - {bm['url']}")
        else:
            for bm in self.bookmarks:
                self.listbox.insert(tk.END, f"{bm['title']} - {bm['url']}")

    def check_urls(self):
        def worker():
            alive = []
            total = len(self.bookmarks)
            for i, bm in enumerate(self.bookmarks, 1):
                try:
                    r = requests.head(bm['url'], timeout=5)
                    if r.status_code < 400:
                        alive.append(bm)
                except Exception:
                    pass
                self.status.config(text=f'Checking URLs... {i}/{total} done')
                self.status.update_idletasks()
            self.bookmarks = alive
            self.refresh_listbox()
            self.status.config(text=f'Checked URLs. {len(self.bookmarks)} are alive.')
        threading.Thread(target=worker).start()
        self.status.config(text='Checking URLs...')

    def add_to_collection(self, event):
        idx = self.listbox.curselection()
        if not idx:
            return
        bm = self.bookmarks[idx[0]]
        collection = simpledialog.askstring('Add to Collection', 'Enter collection (Study, Work, Shopping):')
        if collection and collection in self.collections:
            self.collections[collection].append(bm)
            self.status.config(text=f'Added to {collection}.')
        else:
            messagebox.showerror('Error', 'Invalid collection name.')

    def save_collections(self):
        file_path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON files', '*.json')])
        if not file_path:
            return
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.collections, f, indent=2)
        self.status.config(text='Collections saved.')

    def load_collections(self):
        file_path = filedialog.askopenfilename(filetypes=[('JSON files', '*.json')])
        if not file_path:
            return
        with open(file_path, 'r', encoding='utf-8') as f:
            self.collections = json.load(f)
        self.status.config(text='Collections loaded.')
        # Flatten loaded collections into bookmarks for compatibility
        self.bookmarks = []
        for collection, bookmarks in self.collections.items():
            for bm in bookmarks:
                self.bookmarks.append(bm)
        # Show loaded collections in the listbox with collection names
        self.refresh_listbox(show_collections=True)

    def ai_group_bookmarks(self):
        if not self.api_key:
            messagebox.showerror('Error', 'OpenAI API key not set. Please set it in Settings.')
            return
        import requests
        import math
        import json as _json
        # Prepare for batching
        batch_size = 100
        total = len(self.bookmarks)
        collections = self.collections.copy() if self.collections else {}
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            batch = self.bookmarks[start:end]
            prompt = """
You are an assistant that classifies bookmarks into learning collections. Given a list of bookmarks and existing collections, assign each bookmark to the most suitable collection (existing or new) that helps the user learn something new. Return a JSON object where keys are collection names and values are lists of bookmarks (title and url). If a collection already exists, add to it, otherwise create a new one.

Existing collections:
"""
            prompt += _json.dumps(collections, indent=2)
            prompt += "\n\nBookmarks to classify:\n"
            for bm in batch:
                prompt += f"- {bm['title']} ({bm['url']})\n"
            prompt += "\nJSON:"
            try:
                response = requests.post(
                    'https://api.openai.com/v1/chat/completions',
                    headers={
                        'Authorization': f'Bearer {self.api_key}',
                        'Content-Type': 'application/json'
                    },
                    json={
                        'model': 'gpt-3.5-turbo',
                        'messages': [
                            {'role': 'system', 'content': 'You are a helpful assistant.'},
                            {'role': 'user', 'content': prompt}
                        ],
                        'max_tokens': 1024,
                        'temperature': 0.2
                    }
                )
                response.raise_for_status()
                collections = _json.loads(response.json()['choices'][0]['message']['content'])
                self.status.config(text=f'AI grouped {end}/{total} bookmarks...')
                self.status.update_idletasks()
            except Exception as e:
                messagebox.showerror('Error', f'Failed to group bookmarks: {e}')
                return
        self.collections = collections
        self.status.config(text=f'AI grouped bookmarks into {len(self.collections)} collections.')
        messagebox.showinfo('AI Grouping Complete', f"Grouped into: {', '.join(self.collections.keys())}")
        # Update display to show collections
        self.refresh_listbox(show_collections=True)

    def open_settings(self):
        key = simpledialog.askstring('OpenAI API Key', 'Enter your OpenAI API key:', show='*')
        if key:
            self.api_key = key
            self.status.config(text='OpenAI API key set.')
        else:
            self.status.config(text='OpenAI API key not set.')

    def add_bookmark(self):
        title = simpledialog.askstring('Add Bookmark', 'Enter bookmark title:')
        url = simpledialog.askstring('Add Bookmark', 'Enter bookmark URL:')
        if not title or not url:
            messagebox.showerror('Error', 'Both title and URL are required.')
            return
        bm = {'title': title, 'url': url}
        self.classify_and_add_bookmark(bm)

    def classify_and_add_bookmark(self, bm):
        if not self.api_key:
            messagebox.showerror('Error', 'OpenAI API key not set. Please set it in Settings.')
            return
        import requests
        prompt = f"""
You are an assistant that classifies bookmarks into learning collections. Given the following bookmark, suggest a suitable collection name (existing or new) that helps the user learn something new. Only return the collection name.

Bookmark title: {bm['title']}
Bookmark URL: {bm['url']}

Collection name:"""
        try:
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers={
                    'Authorization': f'Bearer {self.api_key}',
                    'Content-Type': 'application/json'
                },
                json={
                    'model': 'gpt-3.5-turbo',
                    'messages': [
                        {'role': 'system', 'content': 'You are a helpful assistant.'},
                        {'role': 'user', 'content': prompt}
                    ],
                    'max_tokens': 10,
                    'temperature': 0.2
                }
            )
            response.raise_for_status()
            collection = response.json()['choices'][0]['message']['content'].strip()
            if collection not in self.collections:
                self.collections[collection] = []
            self.collections[collection].append(bm)
            self.status.config(text=f'Bookmark added to collection: {collection}')
            messagebox.showinfo('Bookmark Added', f'Added to collection: {collection}')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to classify bookmark: {e}')

if __name__ == '__main__':
    root = tk.Tk()
    app = BookmarkApp(root)
    root.mainloop()
