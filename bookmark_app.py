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
            if self.current_title is None:
                self.current_title = data.strip()
            else:
                self.current_title += " " + data.strip()

class BookmarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title('Bookmark Organizer')
        self.bookmarks = []
        self.bookmarks_folders = {'Books': []}
        self.api_key = None
        self.create_widgets()

    def create_widgets(self):
        frame = tk.Frame(self.root)
        frame.pack(padx=10, pady=10)

        self.import_btn = tk.Button(frame, text='Import Bookmarks', command=self.import_bookmarks)
        self.import_btn.grid(row=0, column=0, padx=5, pady=5)

        self.check_btn = tk.Button(frame, text='Check URLs', command=self.check_urls)
        self.check_btn.grid(row=0, column=1, padx=5, pady=5)

        self.save_btn = tk.Button(frame, text='Save Bookmarks', command=self.save_bookmarks_folders)
        self.save_btn.grid(row=0, column=2, padx=5, pady=5)

        self.load_btn = tk.Button(frame, text='Load Bookmarks', command=self.load_bookmarks_folders)
        self.load_btn.grid(row=0, column=3, padx=5, pady=5)

        self.ai_group_btn = tk.Button(frame, text='AI Group Bookmarks', command=self.ai_group_bookmarks)
        self.ai_group_btn.grid(row=0, column=4, padx=5, pady=5)

        self.settings_btn = tk.Button(frame, text='Settings', command=self.open_settings)
        self.settings_btn.grid(row=0, column=5, padx=5, pady=5)

        self.add_bm_btn = tk.Button(frame, text='Add Bookmark', command=self.add_bookmark)
        self.add_bm_btn.grid(row=0, column=6, padx=5, pady=5)

        self.export_btn = tk.Button(frame, text='Export HTML', command=self.export_html)
        self.export_btn.grid(row=1, column=0, padx=5, pady=5)

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

    def refresh_listbox(self, show_bookmarks_folders=False):
        self.listbox.delete(0, tk.END)
        if show_bookmarks_folders and self.bookmarks_folders:
            for folder, bookmarks in self.bookmarks_folders.items():
                for bm in bookmarks:
                    self.listbox.insert(tk.END, f"[{folder}] {bm['title']} - {bm['url']}")
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
        
        # Get the bookmark depending on the current view
        selected_text = self.listbox.get(idx[0])
        if selected_text.startswith('['):
            # Folder view - extract URL from the display text
            url_part = selected_text.split(' - ')[-1]
            bm = None
            # Find the bookmark in folders
            for folder_bookmarks in self.bookmarks_folders.values():
                for bookmark in folder_bookmarks:
                    if bookmark['url'] == url_part:
                        bm = bookmark
                        break
                if bm:
                    break
        else:
            # Regular bookmark view
            if idx[0] < len(self.bookmarks):
                bm = self.bookmarks[idx[0]]
            else:
                messagebox.showerror('Error', 'Invalid bookmark selection.')
                return
        
        if not bm:
            messagebox.showerror('Error', 'Could not find bookmark.')
            return
            
        # Get available folders or allow creating new ones
        folder_list = list(self.bookmarks_folders.keys())
        folder_str = ', '.join(folder_list) if folder_list else 'No folders yet'
        folder = simpledialog.askstring(
            'Add to Folder', 
            f'Enter folder name.\nExisting: {folder_str}'
        )
        
        if folder:
            if folder not in self.bookmarks_folders:
                self.bookmarks_folders[folder] = []
            
            # Check if bookmark is already in this folder
            if bm not in self.bookmarks_folders[folder]:
                self.bookmarks_folders[folder].append(bm)
                self.status.config(text=f'Added to {folder}.')
            else:
                self.status.config(text=f'Bookmark already in {folder}.')
        else:
            self.status.config(text='No folder specified.')

    def save_bookmarks_folders(self):
        file_path = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('JSON files', '*.json')])
        if not file_path:
            return
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(self.bookmarks_folders, f, indent=2)
        self.status.config(text='Bookmark folders saved.')

    def load_bookmarks_folders(self):
        file_path = filedialog.askopenfilename(filetypes=[('JSON files', '*.json')])
        if not file_path:
            return
        with open(file_path, 'r', encoding='utf-8') as f:
            self.bookmarks_folders = json.load(f)
        self.status.config(text='Bookmark folders loaded.')
        # Flatten loaded folders into bookmarks for compatibility
        self.bookmarks = []
        for folder, bookmarks in self.bookmarks_folders.items():
            for bm in bookmarks:
                self.bookmarks.append(bm)        # Show loaded folders in the listbox with folder names
        self.refresh_listbox(show_bookmarks_folders=True)

    def ai_group_bookmarks(self):
        if not self.api_key:
            messagebox.showerror('Error', 'OpenAI API key not set. Please set it in Settings.')
            return
        import json as _json
        # Prepare for batching
        batch_size = 50
        total = len(self.bookmarks)
        collections = self.bookmarks_folders.copy() if self.bookmarks_folders else {}
        processed_bookmarks = set()  # Track processed bookmarks to avoid duplicates
        failed_batches = 0
        
        for start in range(0, total, batch_size):
            end = min(start + batch_size, total)
            batch = self.bookmarks[start:end]
            
            # Create a summary of existing collections to keep prompt manageable
            collection_summary = {}
            for name, items in collections.items():
                collection_summary[name] = f"{len(items)} bookmarks"
            
            prompt = f"""
You are an assistant that classifies bookmarks into learning folders. Given a list of bookmarks and existing folder summary, assign each bookmark to the most suitable folder (existing or new) that helps the user learn something new. Return a JSON object where keys are folder names and values are lists of bookmarks (title and url).

Existing folders summary:
{_json.dumps(collection_summary, indent=2)}

Bookmarks to classify (batch {start//batch_size + 1} of {(total + batch_size - 1)//batch_size}):
"""
            for bm in batch:
                prompt += f"- {bm['title']} ({bm['url']})\n"
            prompt += "\nReturn only valid JSON in this format: {\"Folder Name\": [{\"title\": \"Title\", \"url\": \"URL\"}]}"
            
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
                            {'role': 'system', 'content': 'You are a helpful assistant that returns only valid JSON.'},
                            {'role': 'user', 'content': prompt}
                        ],
                        'max_tokens': 1500,
                        'temperature': 0.2
                    }
                )
                response.raise_for_status()
                content = response.json()['choices'][0]['message']['content']
                
                # Try to extract and parse JSON from the response
                try:
                    # Look for JSON in the response
                    json_start = content.find('{')
                    json_end = content.rfind('}') + 1
                    if json_start != -1 and json_end > json_start:
                        json_content = content[json_start:json_end]
                        new_collections = _json.loads(json_content)
                    else:
                        new_collections = _json.loads(content)
                    
                    # Merge new collections with existing ones, avoiding duplicates
                    for collection_name, bookmarks in new_collections.items():
                        if collection_name not in collections:
                            collections[collection_name] = []
                        
                        # Add bookmarks that haven't been processed yet
                        for bm in bookmarks:
                            bookmark_key = f"{bm.get('title', '')}-{bm.get('url', '')}"
                            if bookmark_key not in processed_bookmarks:
                                collections[collection_name].append(bm)
                                processed_bookmarks.add(bookmark_key)
                        
                except _json.JSONDecodeError as json_error:
                    failed_batches += 1
                    self.status.config(text=f'Warning: Failed to parse batch {start//batch_size + 1}, continuing...')
                    # Continue processing other batches instead of stopping
                    continue
                    
                self.status.config(text=f'AI grouped {end}/{total} bookmarks...')
                self.status.update_idletasks()
                
            except Exception as e:
                failed_batches += 1
                self.status.config(text=f'Warning: Failed batch {start//batch_size + 1}: {str(e)[:50]}...')
                # Continue with next batch instead of stopping entirely
                continue
        
        # Update bookmarks_folders and provide summary
        self.bookmarks_folders = collections
        successful_batches = (total + batch_size - 1) // batch_size - failed_batches
        
        status_msg = f'AI grouped bookmarks into {len(self.bookmarks_folders)} folders.'
        if failed_batches > 0:
            status_msg += f' ({failed_batches} batches failed)'
        
        self.status.config(text=status_msg)
        
        summary_msg = f"Grouped into: {', '.join(self.bookmarks_folders.keys())}"
        if failed_batches > 0:
            summary_msg += f"\n\nNote: {failed_batches} out of {successful_batches + failed_batches} batches failed due to AI response issues."
        
        messagebox.showinfo('AI Grouping Complete', summary_msg)
        # Update display to show folders
        self.refresh_listbox(show_bookmarks_folders=True)

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
            if collection not in self.bookmarks_folders:
                self.bookmarks_folders[collection] = []
            self.bookmarks_folders[collection].append(bm)
            self.status.config(text=f'Bookmark added to collection: {collection}')
            messagebox.showinfo('Bookmark Added', f'Added to collection: {collection}')
        except Exception as e:
            messagebox.showerror('Error', f'Failed to classify bookmark: {e}')

    def export_html(self):
        """Export bookmarks as HTML file that can be imported into browsers"""
        file_path = filedialog.asksaveasfilename(
            defaultextension='.html', 
            filetypes=[('HTML files', '*.html')],
            initialfile='bookmarks_export.html'
        )
        if not file_path:
            return
        
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                # Write HTML header
                f.write('<!DOCTYPE NETSCAPE-Bookmark-file-1>\n')
                f.write('<!-- This is an automatically generated file.\n')
                f.write('     It will be read and overwritten.\n')
                f.write('     DO NOT EDIT! -->\n')
                f.write('<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">\n')
                f.write('<TITLE>Bookmarks</TITLE>\n')
                f.write('<H1>Bookmarks</H1>\n')
                f.write('<DL><p>\n')
                
                # Process each folder (excluding Bookmarks bar)
                for folder_name, bookmarks in self.bookmarks_folders.items():
                    if folder_name.lower() == 'bookmarks bar':
                        continue  # Skip Bookmarks bar folder
                    
                    if bookmarks:  # Only create folder if it has bookmarks
                        # Create folder header
                        f.write(f'    <DT><H3 ADD_DATE="1596901886" LAST_MODIFIED="1596901886">{folder_name}</H3>\n')
                        f.write('    <DL><p>\n')
                        
                        # Add bookmarks in this folder
                        for bm in bookmarks:
                            title = bm.get('title', 'Untitled')
                            url = bm.get('url', '')
                            # Escape HTML entities in title
                            title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                            f.write(f'        <DT><A HREF="{url}" ADD_DATE="0">{title}</A>\n')
                        
                        f.write('    </DL><p>\n')
                
                # Add any uncategorized bookmarks
                uncategorized = []
                for bm in self.bookmarks:
                    # Check if bookmark is already in a folder
                    found = False
                    for folder_bookmarks in self.bookmarks_folders.values():
                        if bm in folder_bookmarks:
                            found = True
                            break
                    if not found:
                        uncategorized.append(bm)
                
                if uncategorized:
                    f.write('    <DT><H3 ADD_DATE="1596901886" LAST_MODIFIED="1596901886">Uncategorized</H3>\n')
                    f.write('    <DL><p>\n')
                    for bm in uncategorized:
                        title = bm.get('title', 'Untitled')
                        url = bm.get('url', '')
                        title = title.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                        f.write(f'        <DT><A HREF="{url}" ADD_DATE="0">{title}</A>\n')
                    f.write('    </DL><p>\n')
                
                # Close HTML
                f.write('</DL><p>\n')
            
            self.status.config(text=f'Bookmarks exported to {file_path}')
            messagebox.showinfo('Export Complete', f'Bookmarks exported successfully!\n\nFile: {file_path}\n\nYou can now import this file into your browser.')
            
        except Exception as e:
            messagebox.showerror('Error', f'Failed to export bookmarks: {e}')

if __name__ == '__main__':
    root = tk.Tk()
    app = BookmarkApp(root)
    root.mainloop()
