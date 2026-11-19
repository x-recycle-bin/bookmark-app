import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import queue
import threading
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlsplit
import requests

from backend.core import (
    AiConfig, AiOrganizer, AiResponseError, Bookmark, BookmarkFolder,
    BookmarkHTMLParser, BookmarkStore, UrlCheckResult, bookmark_store_to_html,
    normalize_bookmark_url,
)
from backend.persistence import WorkspaceRepository


class BookmarkApp:
    def __init__(self, root):
        self.root = root
        self.root.title('Bookmark Organizer')
        self.store = BookmarkStore()
        self._ui_events = queue.Queue()
        self._ui_poll_id = None
        self._active_background_tasks = 0
        self._cancel_url_check = threading.Event()
        self._cancel_ai = threading.Event()
        self._ai_config_error = None
        try:
            self.ai_config = AiConfig.from_environment()
        except ValueError as error:
            self.ai_config = AiConfig(api_key='')
            self._ai_config_error = str(error)
        self.root.minsize(700, 360)
        self.root.geometry('900x500')
        self.create_widgets()

    @property
    def bookmarks(self):
        return self.store.bookmarks

    @property
    def bookmarks_folders(self):
        return self.store.flattened_folders

    def create_widgets(self):
        frame = tk.Frame(self.root, padx=10, pady=10)
        frame.pack(fill=tk.BOTH, expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(1, weight=1)

        toolbar = tk.Frame(frame)
        toolbar.grid(row=0, column=0, sticky=tk.EW, pady=(0, 10))

        self.import_btn = tk.Button(toolbar, text='Import Bookmarks', command=self.import_bookmarks)
        self.import_btn.pack(side=tk.LEFT, padx=(0, 5))

        self.save_btn = tk.Button(
            toolbar,
            text='Save Bookmarks',
            command=self.save_bookmarks_folders
        )
        self.save_btn.pack(side=tk.LEFT, padx=5)

        self.load_btn = tk.Button(
            toolbar,
            text='Load Bookmarks',
            command=self.load_bookmarks_folders
        )
        self.load_btn.pack(side=tk.LEFT, padx=5)
        self.export_btn = tk.Button(
            toolbar,
            text='Export HTML',
            command=self.export_html
        )
        self.export_btn.pack(side=tk.LEFT, padx=5)

        self.add_folder_btn = tk.Button(
            toolbar,
            text='New Folder',
            command=self.create_folder
        )
        self.add_folder_btn.pack(side=tk.LEFT, padx=5)

        self.rename_folder_btn = tk.Button(
            toolbar,
            text='Rename Folder',
            command=self.rename_folder
        )
        self.rename_folder_btn.pack(side=tk.LEFT, padx=5)

        self.delete_folder_btn = tk.Button(
            toolbar,
            text='Delete Folder',
            command=self.delete_folder
        )
        self.delete_folder_btn.pack(side=tk.LEFT, padx=5)

        self.move_bookmark_btn = tk.Button(
            toolbar,
            text='Move Bookmark',
            command=self.move_selected_bookmark
        )
        self.move_bookmark_btn.pack(side=tk.LEFT, padx=5)
        self.edit_bookmark_btn = tk.Button(
            toolbar,
            text='Edit Bookmark',
            command=self.edit_selected_bookmark
        )
        self.edit_bookmark_btn.pack(side=tk.LEFT, padx=5)
        self.delete_bookmark_btn = tk.Button(
            toolbar,
            text='Delete Bookmark',
            command=self.delete_selected_bookmarks
        )
        self.delete_bookmark_btn.pack(side=tk.LEFT, padx=5)
        self.duplicates_btn = tk.Button(
            toolbar,
            text='Duplicates',
            command=self.resolve_duplicates
        )
        self.duplicates_btn.pack(side=tk.LEFT, padx=5)
        self.check_urls_btn = tk.Button(
            toolbar,
            text='Check URLs',
            command=self.check_urls
        )
        self.check_urls_btn.pack(side=tk.LEFT, padx=5)
        self.cancel_check_btn = tk.Button(
            toolbar,
            text='Cancel Check',
            state=tk.DISABLED,
            command=self.cancel_url_check
        )
        self.cancel_check_btn.pack(side=tk.LEFT, padx=5)
        self.settings_btn = tk.Button(
            toolbar,
            text='AI Settings',
            command=self.configure_ai
        )
        self.settings_btn.pack(side=tk.LEFT, padx=5)
        self.ai_group_btn = tk.Button(
            toolbar,
            text='AI Group',
            command=self.ai_group_bookmarks
        )
        self.ai_group_btn.pack(side=tk.LEFT, padx=5)
        self.sort_dates_btn = tk.Button(
            toolbar,
            text='Sort Dates',
            command=self.ai_sort_dates
        )
        self.sort_dates_btn.pack(side=tk.LEFT, padx=5)
        self.cancel_ai_btn = tk.Button(
            toolbar,
            text='Cancel AI',
            state=tk.DISABLED,
            command=self.cancel_ai_grouping
        )
        self.cancel_ai_btn.pack(side=tk.LEFT, padx=5)
        self.add_bookmark_btn = tk.Button(
            toolbar,
            text='Add Bookmark',
            command=self.add_bookmark
        )
        self.add_bookmark_btn.pack(side=tk.LEFT, padx=5)
        self._action_buttons = [
            self.import_btn,
            self.save_btn,
            self.load_btn,
            self.export_btn,
            self.add_folder_btn,
            self.rename_folder_btn,
            self.delete_folder_btn,
            self.move_bookmark_btn,
            self.edit_bookmark_btn,
            self.delete_bookmark_btn,
            self.duplicates_btn,
            self.check_urls_btn,
            self.settings_btn,
            self.ai_group_btn,
            self.sort_dates_btn,
            self.add_bookmark_btn,
        ]
        toolbar_buttons = [
            *self._action_buttons,
            self.cancel_check_btn,
            self.cancel_ai_btn,
        ]
        for button in toolbar_buttons:
            button.pack_forget()
        for index, button in enumerate(toolbar_buttons):
            row, column = divmod(index, 6)
            button.grid(
                row=row,
                column=column,
                sticky=tk.EW,
                padx=3,
                pady=2
            )
            toolbar.columnconfigure(column, weight=1)

        tree_frame = tk.Frame(frame)
        tree_frame.grid(row=1, column=0, sticky=tk.NSEW)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(1, weight=1)
        tk.Label(tree_frame, text='Folders and Bookmarks', anchor=tk.W).grid(
            row=0, column=0, sticky=tk.EW, pady=(0, 5)
        )
        self.tree = ttk.Treeview(tree_frame, selectmode='extended', show='tree')
        self.tree.grid(row=1, column=0, sticky=tk.NSEW)
        tree_scrollbar = tk.Scrollbar(
            tree_frame,
            orient=tk.VERTICAL,
            command=self.tree.yview
        )
        tree_scrollbar.grid(row=1, column=1, sticky=tk.NS)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)
        self.tree.bind('<Double-Button-1>', self._tree_double_click)
        self.tree.bind('<ButtonPress-1>', self._begin_drag)
        self.tree.bind('<B1-Motion>', self._track_drag)
        self.tree.bind('<ButtonRelease-1>', self._finish_drag)

        self.status = tk.Label(frame, text='Status: Ready', anchor=tk.W)
        self.status.grid(row=2, column=0, sticky=tk.EW, pady=(10, 0))
        self._tree_folder_paths = {}
        self._tree_bookmark_keys = {}
        self.refresh_bookmark_views()
        if self._ai_config_error:
            self.status.config(
                text=f'AI environment configuration ignored: {self._ai_config_error}'
            )

    def import_bookmarks(self):
        file_path = filedialog.askopenfilename(filetypes=[('HTML files', '*.html')])
        if not file_path:
            return

        self._set_busy(True, 'Importing bookmarks...')
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                html = f.read()
            parser = BookmarkHTMLParser()
            parser.feed(html)
            parser.close()
            if parser.malformed_file:
                raise ValueError('The selected file is not a Netscape bookmark export.')
            if not parser.bookmarks:
                raise ValueError(
                    f'The selected file contained no usable bookmarks '
                    f'({parser.skipped_links} malformed links skipped).'
                )

            self.store = parser.store
            self.refresh_bookmark_views()
            skipped_message = (
                f' ({parser.skipped_links} malformed links skipped)'
                if parser.skipped_links
                else ''
            )
            self.status.config(
                text=(
                    f'Imported {len(self.bookmarks)} bookmarks'
                    f'{skipped_message}.'
                )
            )
        except (OSError, UnicodeError, ValueError) as error:
            messagebox.showerror(
                'Import Failed',
                f'Could not read the selected bookmark file:\n{error}'
            )
            self.status.config(text='Import failed.')
        finally:
            self._set_busy(False)

    def _set_busy(self, busy, message=None):
        state = tk.DISABLED if busy else tk.NORMAL
        for button in self._action_buttons:
            button.config(state=state)
        if message is not None:
            self.status.config(text=message)
        self.root.update_idletasks()

    def run_background(self, worker, on_success, on_error=None, on_progress=None):
        """Run non-UI work and invoke callbacks from Tkinter's main thread."""
        self._active_background_tasks += 1

        def report_progress(value):
            if on_progress is not None:
                self._ui_events.put(('progress', on_progress, value))

        def execute():
            try:
                result = worker(report_progress)
            except Exception as error:
                self._ui_events.put(('error', on_error, error))
            else:
                self._ui_events.put(('success', on_success, result))

        threading.Thread(target=execute, daemon=True).start()
        self._schedule_ui_poll()

    def _schedule_ui_poll(self):
        if self._ui_poll_id is None:
            self._ui_poll_id = self.root.after(50, self._process_ui_events)

    def _process_ui_events(self):
        self._ui_poll_id = None
        processed = 0

        while processed < 100:
            try:
                event_type, callback, value = self._ui_events.get_nowait()
            except queue.Empty:
                break

            processed += 1
            try:
                if event_type == 'progress':
                    if callback is not None:
                        callback(value)
                elif event_type == 'success':
                    self._active_background_tasks -= 1
                    callback(value)
                elif event_type == 'error':
                    self._active_background_tasks -= 1
                    if callback is not None:
                        callback(value)
                    else:
                        self._report_background_error(value)
            except Exception as error:
                self._report_background_error(error)

        if self._active_background_tasks or not self._ui_events.empty():
            self._schedule_ui_poll()

    def _report_background_error(self, error):
        message = f'Background operation failed: {error}'
        self.status.config(text=message)
        messagebox.showerror('Operation Failed', message)

    def _refresh_bookmark_views(self):
        self._refresh_tree()

    def refresh_bookmark_views(self):
        self._refresh_bookmark_views()

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        self._tree_folder_paths = {}
        self._tree_bookmark_keys = {}

        uncategorized_id = self.tree.insert(
            '',
            tk.END,
            text=f'Uncategorized ({len(self.store.uncategorized)})',
            open=True
        )
        self._tree_folder_paths[uncategorized_id] = ()
        for bookmark in self.store.uncategorized:
            item_id = self.tree.insert(
                uncategorized_id,
                tk.END,
                text=f'{bookmark.title} - {bookmark.url}'
            )
            self._tree_bookmark_keys[item_id] = bookmark.assignment_key

        for folder in self.store.folders:
            self._insert_folder('', folder, ())

    def _insert_folder(self, parent_item, folder, parent_path):
        path = parent_path + (folder.name,)
        label = folder.name
        if folder.is_bookmarks_bar:
            label += ' [Bookmarks bar]'
        count = len(folder.bookmarks)
        if count:
            label += f' ({count})'
        item_id = self.tree.insert(
            parent_item,
            tk.END,
            text=label,
            open=folder.is_bookmarks_bar
        )
        self._tree_folder_paths[item_id] = path

        for bookmark in folder.bookmarks:
            bookmark_id = self.tree.insert(
                item_id,
                tk.END,
                text=f'{bookmark.title} - {bookmark.url}'
            )
            self._tree_bookmark_keys[bookmark_id] = bookmark.assignment_key
        for child in folder.children:
            self._insert_folder(item_id, child, path)
        return item_id

    def create_folder(self):
        parent_path = self._selected_folder_path()
        name = simpledialog.askstring(
            'New Folder',
            'Enter a folder name:'
        )
        if name is None:
            return
        try:
            self.store.create_folder(name, parent_path)
            self.refresh_bookmark_views()
            self.status.config(text=f'Created folder "{name.strip()}".')
        except ValueError as error:
            messagebox.showerror('Cannot Create Folder', str(error))

    def rename_folder(self):
        paths = self._selected_folder_paths()
        if len(paths) != 1:
            messagebox.showerror(
                'Rename Folder',
                'Select exactly one folder to rename.'
            )
            return
        path = paths[0]
        folder = self.store.find_folder(path)
        if folder is None or folder.is_bookmarks_bar:
            messagebox.showerror(
                'Rename Folder',
                'The selected folder cannot be renamed.'
            )
            return
        name = simpledialog.askstring(
            'Rename Folder',
            'Enter the new folder name:',
            initialvalue=folder.name
        )
        if name is None:
            return
        try:
            self.store.rename_folder(path, name)
            self.refresh_bookmark_views()
            self.status.config(text=f'Renamed folder to "{name.strip()}".')
        except ValueError as error:
            messagebox.showerror('Cannot Rename Folder', str(error))

    def delete_folder(self):
        paths = self._selected_folder_paths()
        if not paths:
            messagebox.showerror(
                'Delete Folder',
                'Select one or more folders to delete.'
            )
            return
        paths = [
            path
            for path in paths
            if not any(
                tuple(path[:len(parent)]) == tuple(parent)
                for parent in paths
                if parent != path
            )
        ]
        folders = [self.store.find_folder(path) for path in paths]
        if any(folder is None or folder.is_bookmarks_bar for folder in folders):
            messagebox.showerror(
                'Delete Folder',
                'The Bookmarks bar and Uncategorized cannot be deleted.'
            )
            return
        bookmark_count = sum(
            len(list(folder.iter_bookmarks()))
            for folder in folders
        )
        child_count = sum(
            len(list(folder.iter_folders())) - 1
            for folder in folders
        )
        detail = (
            f'This keeps {bookmark_count} bookmark(s) and promotes '
            f'{child_count} child folder(s) to the parent level.'
        )
        if not messagebox.askyesno(
            'Delete Folder',
            f'Delete {len(paths)} selected folder(s)?\n\n{detail}',
            icon='warning'
        ):
            return
        try:
            for path in sorted(paths, key=len, reverse=True):
                self.store.delete_folder(path)
            self.refresh_bookmark_views()
            self.status.config(text=f'Deleted {len(paths)} folder(s).')
        except ValueError as error:
            messagebox.showerror('Cannot Delete Folder', str(error))

    def move_selected_bookmark(self):
        assignment_keys = self._selected_bookmark_keys()
        if not assignment_keys:
            messagebox.showerror(
                'Move Bookmark',
                'Select one or more bookmarks in the tree.'
            )
            return

        choices = ['Uncategorized'] + [
            ' / '.join(path) for path in self.store.folder_paths
        ]
        destination = simpledialog.askstring(
            'Move Bookmark',
            'Choose a destination exactly as shown:\n\n' + '\n'.join(choices)
        )
        if destination is None:
            return
        destination = destination.strip()
        if destination == 'Uncategorized':
            destination_path = ()
        else:
            matches = [
                path
                for path in self.store.folder_paths
                if ' / '.join(path) == destination
            ]
            if len(matches) != 1:
                messagebox.showerror(
                    'Move Bookmark',
                    'Choose one of the listed folder paths.'
                )
                return
            destination_path = matches[0]

        try:
            moved = self.store.move_bookmarks(
                assignment_keys,
                destination_path
            )
            self.refresh_bookmark_views()
            label = destination or 'Uncategorized'
            self.status.config(text=f'Moved {moved} bookmark(s) to {label}.')
        except ValueError as error:
            messagebox.showerror('Cannot Move Bookmark', str(error))

    def edit_selected_bookmark(self):
        keys = self._selected_bookmark_keys()
        if len(keys) != 1:
            messagebox.showerror(
                'Edit Bookmark',
                'Select exactly one bookmark to edit.'
            )
            return
        bookmark = self.store.find_bookmark(keys[0])[2]
        title = simpledialog.askstring(
            'Edit Bookmark',
            'Bookmark title:',
            initialvalue=bookmark.title
        )
        if title is None:
            return
        url = simpledialog.askstring(
            'Edit Bookmark',
            'Bookmark URL:',
            initialvalue=bookmark.url
        )
        if url is None:
            return
        try:
            parsed = urlsplit(url.strip())
            if (
                parsed.scheme.lower() not in {'http', 'https'}
                or not parsed.netloc
            ):
                raise ValueError('Bookmark URL must start with http:// or https://.')
            self.store.update_bookmark(keys[0], title, url)
        except ValueError as error:
            messagebox.showerror('Edit Bookmark', str(error))
            return
        self.refresh_bookmark_views()
        self.status.config(text=f'Updated "{title.strip()}".')

    def delete_selected_bookmarks(self):
        keys = self._selected_bookmark_keys()
        if not keys:
            messagebox.showerror(
                'Delete Bookmarks',
                'Select one or more bookmarks.'
            )
            return
        if not messagebox.askyesno(
            'Delete Bookmarks',
            f'Delete {len(keys)} selected bookmark(s)?'
        ):
            return
        removed = self.store.remove_bookmarks(keys)
        self.refresh_bookmark_views()
        self.status.config(text=f'Deleted {removed} bookmark(s).')

    def resolve_duplicates(self):
        groups = self.store.duplicate_groups()
        if not groups:
            messagebox.showinfo(
                'Duplicate Bookmarks',
                'No duplicate URLs were found.'
            )
            return

        summary = '\n'.join(
            f'{len(group)} copies: {group[0].title}'
            for group in groups[:10]
        )
        if len(groups) > 10:
            summary += f'\n...and {len(groups) - 10} more groups'
        strategy = simpledialog.askstring(
            'Resolve Duplicate Bookmarks',
            (
                f'Found {len(groups)} duplicate URL group(s):\n\n'
                f'{summary}\n\n'
                'Enter one action:\n'
                'keep-all: make no changes\n'
                'keep-first: remove later copies\n'
                'merge-folder: keep copies in the first copy’s folder'
            )
        )
        if strategy is None:
            return
        strategy = strategy.strip().lower()
        if strategy not in {'keep-all', 'keep-first', 'merge-folder'}:
            messagebox.showerror(
                'Duplicate Bookmarks',
                'Choose keep-all, keep-first, or merge-folder.'
            )
            return
        if strategy != 'keep-all' and not messagebox.askyesno(
            'Confirm Duplicate Changes',
            f'Apply "{strategy}" to all duplicate groups?'
        ):
            return

        changed = self.store.resolve_duplicates(strategy)
        self.refresh_bookmark_views()
        self.status.config(
            text=f'Duplicate review complete: {changed} bookmark(s) changed.'
        )

    def check_urls(self):
        if not self.bookmarks:
            messagebox.showinfo('Check URLs', 'Import or load bookmarks first.')
            return
        self._cancel_url_check.clear()
        bookmarks = list(self.bookmarks)
        self._set_busy(True, 'Checking bookmark URLs...')
        self.cancel_check_btn.config(state=tk.NORMAL)

        def worker(report_progress):
            results = []
            with ThreadPoolExecutor(max_workers=5) as executor:
                futures = {
                    executor.submit(self._check_bookmark_url, bookmark): bookmark
                    for bookmark in bookmarks
                }
                for future in as_completed(futures):
                    if self._cancel_url_check.is_set():
                        for pending in futures:
                            pending.cancel()
                        break
                    try:
                        results.append(future.result())
                    except requests.RequestException as error:
                        bookmark = futures[future]
                        results.append(UrlCheckResult(
                            bookmark,
                            'network-error',
                            str(error),
                        ))
                    report_progress((len(results), len(bookmarks)))
            return results, self._cancel_url_check.is_set()

        self.run_background(
            worker,
            on_success=self._finish_url_check,
            on_error=self._url_check_failed,
            on_progress=lambda progress: self.status.config(
                text=f'Checking URLs: {progress[0]}/{progress[1]}'
            ),
        )

    def cancel_url_check(self):
        self._cancel_url_check.set()
        self.cancel_check_btn.config(state=tk.DISABLED)
        self.status.config(text='Canceling URL check...')

    def _check_bookmark_url(self, bookmark):
        parsed = urlsplit(bookmark.url)
        if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
            return UrlCheckResult(
                bookmark,
                'invalid-url',
                'Only HTTP and HTTPS URLs can be checked.',
            )
        try:
            response = requests.head(
                bookmark.url,
                timeout=5,
                allow_redirects=True
            )
            if response.status_code in {405, 501}:
                response = requests.get(
                    bookmark.url,
                    timeout=5,
                    allow_redirects=True,
                    stream=True
                )
                response.close()
            if response.history and response.status_code < 400:
                return UrlCheckResult(
                    bookmark,
                    'redirected',
                    f'{response.status_code} after redirect'
                )
            if response.status_code < 400:
                return UrlCheckResult(
                    bookmark,
                    'reachable',
                    str(response.status_code)
                )
            if response.status_code < 500:
                return UrlCheckResult(
                    bookmark,
                    'client-error',
                    str(response.status_code)
                )
            return UrlCheckResult(
                bookmark,
                'server-error',
                str(response.status_code)
            )
        except requests.Timeout as error:
            return UrlCheckResult(bookmark, 'timeout', str(error))
        except requests.RequestException as error:
            return UrlCheckResult(bookmark, 'network-error', str(error))

    def _finish_url_check(self, payload):
        results, cancelled = payload
        self.cancel_check_btn.config(state=tk.DISABLED)
        self._set_busy(False)
        counts = {}
        for result in results:
            counts[result.outcome] = counts.get(result.outcome, 0) + 1
        summary = ', '.join(
            f'{outcome}: {count}'
            for outcome, count in sorted(counts.items())
        ) or 'no results'
        self.status.config(
            text=(
                f'URL check {"canceled" if cancelled else "complete"}: '
                f'{summary}.'
            )
        )

        removable = [
            result
            for result in results
            if result.outcome in {'client-error', 'invalid-url'}
        ]
        if not removable:
            return
        preview = '\n'.join(
            f'{result.bookmark.title}: {result.outcome} ({result.detail})'
            for result in removable[:10]
        )
        if len(removable) > 10:
            preview += f'\n...and {len(removable) - 10} more'
        if messagebox.askyesno(
            'Review Failed URLs',
            (
                f'Remove {len(removable)} bookmark(s) with invalid URLs '
                f'or client errors?\n\n{preview}\n\n'
                'Timeouts, network errors, and server errors will be kept.'
            )
        ):
            removed = self.store.remove_bookmarks(
                result.bookmark.assignment_key
                for result in removable
            )
            self.refresh_bookmark_views()
            self.status.config(text=f'Removed {removed} failed bookmark(s).')

    def _url_check_failed(self, error):
        self.cancel_check_btn.config(state=tk.DISABLED)
        self._set_busy(False)
        self._report_background_error(error)

    def configure_ai(self):
        api_key = simpledialog.askstring(
            'AI Settings',
            'Enter the API key for this session.\n'
            'Leave blank to keep the current key or use OPENAI_API_KEY.',
            show='*'
        )
        if api_key is None:
            return
        endpoint = simpledialog.askstring(
            'AI Settings',
            'OpenAI API base URL:',
            initialvalue=self.ai_config.endpoint
        )
        if endpoint is None:
            return
        model = simpledialog.askstring(
            'AI Settings',
            'Model:',
            initialvalue=self.ai_config.model
        )
        if model is None:
            return
        batch_size = simpledialog.askinteger(
            'AI Settings',
            'Bookmarks per batch:',
            initialvalue=self.ai_config.batch_size,
            minvalue=1,
            maxvalue=200
        )
        if batch_size is None:
            return

        selected_key = api_key.strip() or self.ai_config.api_key
        try:
            self.ai_config = AiConfig(
                api_key=selected_key,
                endpoint=endpoint.strip(),
                model=model.strip(),
                timeout=self.ai_config.timeout,
                batch_size=batch_size,
                retries=self.ai_config.retries,
            )
        except ValueError as error:
            messagebox.showerror('AI Settings', str(error))
            return
        self.status.config(
            text=(
                'AI settings updated for this session.'
                if self.ai_config.api_key
                else 'AI settings saved; API key is still required.'
            )
        )

    def ai_group_bookmarks(self):
        if not self.ai_config.api_key:
            messagebox.showerror(
                'AI Grouping',
                'Set OPENAI_API_KEY or configure an API key in AI Settings.'
            )
            return
        protected = self.store.protected_bookmark_keys()
        bookmarks = [
            bookmark
            for bookmark in self.bookmarks
            if bookmark.assignment_key not in protected
        ]
        if not bookmarks:
            messagebox.showinfo(
                'AI Grouping',
                'There are no bookmarks available outside the Bookmarks bar.'
            )
            return

        service = AiOrganizer(self.ai_config)
        source_store = BookmarkStore.from_dict(self.store.to_dict())
        folder_paths = [
            ' / '.join(path)
            for path in source_store.folder_paths
            if not self._is_protected_folder_path(path, source_store)
        ]
        self._cancel_ai.clear()
        self._set_busy(True, 'AI grouping started...')
        self.cancel_ai_btn.config(state=tk.NORMAL)

        def worker(report_progress):
            assignments = {}
            failures = []
            batches = [
                bookmarks[start:start + self.ai_config.batch_size]
                for start in range(
                    0,
                    len(bookmarks),
                    self.ai_config.batch_size
                )
            ]
            for index, batch in enumerate(batches, start=1):
                if self._cancel_ai.is_set():
                    break
                try:
                    assignments.update(
                        service.classify_batch(batch, folder_paths)
                    )
                except (AiResponseError, ValueError) as error:
                    failures.append((index, error))
                report_progress((index, len(batches), len(assignments)))
            return source_store, assignments, failures, self._cancel_ai.is_set()

        self.run_background(
            worker,
            on_success=self._preview_ai_grouping,
            on_error=self._ai_grouping_failed,
            on_progress=lambda progress: self.status.config(
                text=(
                    f'AI grouping batch {progress[0]}/{progress[1]}: '
                    f'{progress[2]} classified.'
                )
            ),
        )

    def ai_sort_dates(self):
        if not self.ai_config.api_key:
            messagebox.showerror(
                'Sort Dates',
                'Set OPENAI_API_KEY or configure an API key in AI Settings.'
            )
            return

        source_paths = self.store.date_folder_paths()
        if not source_paths:
            messagebox.showinfo(
                'Sort Dates',
                'No folder named "Даты" or "Dates" was found.'
            )
            return
        bookmarks = self.store.bookmarks_under_paths(source_paths)
        if not bookmarks:
            messagebox.showinfo(
                'Sort Dates',
                'The Dates folder tree contains no bookmarks.'
            )
            return

        destination_paths = [
            path
            for path in self.store.folder_paths
            if not self.store.is_path_within(path, source_paths)
            and not self._is_protected_folder_path(path, self.store)
        ]
        folder_names = [' / '.join(path) for path in destination_paths]
        if not folder_names:
            messagebox.showinfo(
                'Sort Dates',
                'Create at least one destination folder outside the Dates tree.'
            )
            return

        if not messagebox.askyesno(
            'Sort Dates with AI',
            (
                f'Classify {len(bookmarks)} bookmark(s) from '
                f'{len(source_paths)} Dates folder(s) into one of '
                f'{len(folder_names)} existing folders?\n\n'
                'No new folders will be created. The original data is unchanged '
                'until you approve the preview.'
            )
        ):
            return

        service = AiOrganizer(self.ai_config)
        source_store = BookmarkStore.from_dict(self.store.to_dict())
        self._cancel_ai.clear()
        self._set_busy(True, 'AI sorting Dates bookmarks...')
        self.cancel_ai_btn.config(state=tk.NORMAL)

        def worker(report_progress):
            assignments = {}
            failures = []
            batches = [
                bookmarks[start:start + self.ai_config.batch_size]
                for start in range(
                    0,
                    len(bookmarks),
                    self.ai_config.batch_size
                )
            ]
            for index, batch in enumerate(batches, start=1):
                if self._cancel_ai.is_set():
                    break
                try:
                    assignments.update(
                        service.classify_batch(
                            batch,
                            folder_names,
                            existing_folders_only=True,
                        )
                    )
                except (AiResponseError, ValueError) as error:
                    failures.append((index, error))
                report_progress((index, len(batches), len(assignments)))
            return source_store, assignments, failures, self._cancel_ai.is_set()

        self.run_background(
            worker,
            on_success=self._preview_ai_grouping,
            on_error=self._ai_grouping_failed,
            on_progress=lambda progress: self.status.config(
                text=(
                    f'Sorting Dates batch {progress[0]}/{progress[1]}: '
                    f'{progress[2]} classified.'
                )
            ),
        )

    def cancel_ai_grouping(self):
        self._cancel_ai.set()
        self.cancel_ai_btn.config(state=tk.DISABLED)
        self.status.config(text='Canceling AI grouping...')

    def _preview_ai_grouping(self, payload):
        proposed_store, assignments, failures, cancelled = payload
        self.cancel_ai_btn.config(state=tk.DISABLED)
        self._set_busy(False)
        if cancelled and not assignments:
            self.status.config(text='AI grouping canceled before classification.')
            return

        failed_summary = ''
        if failures:
            failed_batches = ', '.join(
                f'{index}: {error.__class__.__name__}'
                for index, error in failures
            )
            failed_summary = (
                f'\n{len(failures)} batch(es) failed and will remain in their '
                f'current folders.\nFailed batches: {failed_batches}.'
            )
        try:
            for assignment_key, folder_name in assignments.items():
                parts = tuple(
                    part.strip()
                    for part in folder_name.split(' / ')
                )
                destination = proposed_store.ensure_folder_path(parts)
                proposed_store.move_bookmark(assignment_key, destination)
        except ValueError as error:
            self._report_background_error(
                AiResponseError(f'Cannot apply AI folder proposal: {error}')
            )
            return

        proposed_store.validate()
        classified = len(assignments)
        preview = (
            f'AI classified {classified} bookmark(s).'
            f'{failed_summary}\n\n'
            f'Preview folders:\n'
            + '\n'.join(
                f'- {" / ".join(path)} ({len(folder.bookmarks)})'
                for path, folder in proposed_store._iter_folder_locations()
            )
        )
        if len(preview) > 3000:
            preview = preview[:3000] + '\n...'
        if self._confirm_ai_preview(preview):
            self.store = proposed_store
            self.refresh_bookmark_views()
            self.status.config(
                text=f'Applied AI grouping to {classified} bookmark(s).'
            )
        else:
            self.status.config(text='AI grouping proposal was not applied.')

    def _confirm_ai_preview(self, preview):
        dialog = tk.Toplevel(self.root)
        dialog.title('Review AI Organization')
        dialog.transient(self.root)
        dialog.geometry('700x460')
        dialog.minsize(500, 320)
        dialog.resizable(True, True)
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(1, weight=1)

        tk.Label(
            dialog,
            text='Review the proposed organization, then choose Apply or Cancel.',
            anchor=tk.W,
            justify=tk.LEFT,
            padx=12,
            pady=10,
        ).grid(row=0, column=0, sticky=tk.EW)

        text_frame = tk.Frame(dialog, padx=12)
        text_frame.grid(row=1, column=0, sticky=tk.NSEW)
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)

        text_widget = tk.Text(
            text_frame,
            wrap=tk.WORD,
            width=80,
            height=20,
            takefocus=True,
        )
        text_widget.grid(row=0, column=0, sticky=tk.NSEW)
        scrollbar = tk.Scrollbar(
            text_frame,
            orient=tk.VERTICAL,
            command=text_widget.yview,
        )
        scrollbar.grid(row=0, column=1, sticky=tk.NS)
        text_widget.configure(yscrollcommand=scrollbar.set)
        text_widget.insert(tk.END, preview)
        text_widget.configure(state=tk.DISABLED)

        decision = {'apply': False}

        def finish(apply):
            decision['apply'] = apply
            dialog.destroy()

        button_frame = tk.Frame(dialog, pady=10)
        button_frame.grid(row=2, column=0, sticky=tk.E)
        tk.Button(
            button_frame,
            text='Cancel',
            width=12,
            command=lambda: finish(False),
        ).pack(side=tk.RIGHT, padx=(5, 12))
        tk.Button(
            button_frame,
            text='Apply',
            width=12,
            command=lambda: finish(True),
        ).pack(side=tk.RIGHT, padx=5)

        dialog.protocol('WM_DELETE_WINDOW', lambda: finish(False))
        dialog.bind('<Escape>', lambda event: self._finish_preview(
            event, finish, False
        ))
        dialog.bind('<Return>', lambda event: self._finish_preview(
            event, finish, True
        ))
        dialog.grab_set()
        text_widget.focus_set()
        self.root.wait_window(dialog)
        return decision['apply']

    @staticmethod
    def _finish_preview(event, finish, apply):
        del event
        finish(apply)

    def _ai_grouping_failed(self, error):
        self.cancel_ai_btn.config(state=tk.DISABLED)
        self._set_busy(False)
        self._report_background_error(error)

    @staticmethod
    def _is_protected_folder_path(path, store):
        return any(
            (folder := store.find_folder(path[:index])) is not None
            and folder.is_bookmarks_bar
            for index in range(1, len(path) + 1)
        )

    def add_bookmark(self):
        title = simpledialog.askstring('Add Bookmark', 'Bookmark title:')
        if title is None:
            return
        url = simpledialog.askstring('Add Bookmark', 'Bookmark URL:')
        if url is None:
            return
        title = title.strip()
        url = url.strip()
        try:
            bookmark = Bookmark(title=title, url=url)
            parsed = urlsplit(url)
            if parsed.scheme.lower() not in {'http', 'https'} or not parsed.netloc:
                raise ValueError('Bookmark URL must start with http:// or https://.')
        except ValueError as error:
            messagebox.showerror('Add Bookmark', str(error))
            return

        if self.store.has_normalized_url(url) and not messagebox.askyesno(
            'Possible Duplicate',
            'A bookmark with a matching URL already exists. Add another copy?'
        ):
            return

        if self.ai_config.api_key and messagebox.askyesno(
            'AI Folder Suggestion',
            'Ask AI for a folder suggestion?'
        ):
            service = AiOrganizer(self.ai_config)
            self._set_busy(True, 'Getting AI folder suggestion...')

            def worker(report_progress):
                report_progress('Classifying bookmark...')
                return service.suggest_folder(
                    bookmark,
                    [
                        ' / '.join(path)
                        for path in self.store.folder_paths
                        if not self._is_protected_folder_path(
                            path, self.store
                        )
                    ],
                )

            self.run_background(
                worker,
                on_success=lambda suggestion: self._choose_bookmark_destination(
                    bookmark,
                    suggestion
                ),
                on_error=lambda error: self._ai_add_failed(bookmark, error),
                on_progress=lambda message: self.status.config(text=message),
            )
            return
        self._choose_bookmark_destination(bookmark)

    def _ai_add_failed(self, bookmark, error):
        self._set_busy(False)
        messagebox.showerror(
            'AI Suggestion Failed',
            f'{error}\nThe bookmark is still available to add manually.'
        )
        self._choose_bookmark_destination(bookmark)

    def _choose_bookmark_destination(self, bookmark, suggested_folder=''):
        self._set_busy(False)

        choices = ['Uncategorized'] + [
            ' / '.join(path)
            for path in self.store.folder_paths
            if not self._is_protected_folder_path(path, self.store)
        ]
        destination = simpledialog.askstring(
            'Add Bookmark',
            (
                'Choose a folder path, or enter a new folder name.\n'
                'Existing choices:\n' + '\n'.join(choices)
            ),
            initialvalue=suggested_folder or 'Uncategorized'
        )
        if destination is None:
            return
        destination = destination.strip()
        try:
            if destination == 'Uncategorized':
                self.store.uncategorized.append(bookmark)
            else:
                path = self.store.ensure_folder_path(
                    tuple(part.strip() for part in destination.split(' / '))
                )
                self.store.find_folder(path).bookmarks.append(bookmark)
            self.store.validate()
        except ValueError as error:
            messagebox.showerror('Add Bookmark', str(error))
            return
        self.refresh_bookmark_views()
        self.status.config(text=f'Added "{bookmark.title}".')

    def _tree_double_click(self, event):
        del event
        if self._selected_bookmark_keys():
            self.edit_selected_bookmark()

    def _selected_folder_path(self):
        selection = self.tree.selection()
        if not selection:
            return ()
        return self._tree_folder_paths.get(selection[0], ())

    def _selected_bookmark_keys(self):
        return [
            self._tree_bookmark_keys[item_id]
            for item_id in self.tree.selection()
            if item_id in self._tree_bookmark_keys
        ]

    def _selected_folder_paths(self):
        return [
            self._tree_folder_paths[item_id]
            for item_id in self.tree.selection()
            if item_id in self._tree_folder_paths
            and self._tree_folder_paths[item_id]
        ]

    def _begin_drag(self, event):
        item = self.tree.identify_row(event.y)
        selected = (
            tuple(self.tree.selection())
            if item in self.tree.selection()
            else (item,)
        )
        bookmark_items = tuple(
            selected_item
            for selected_item in selected
            if selected_item in self._tree_bookmark_keys
        )
        self._drag_items = bookmark_items
        if not bookmark_items:
            self._drag_start = None
            return
        self._drag_start = (event.x_root, event.y_root)

    def _track_drag(self, event):
        if getattr(self, '_drag_start', None) is None:
            return
        if abs(event.x_root - self._drag_start[0]) < 5 and abs(
            event.y_root - self._drag_start[1]
        ) < 5:
            return
        target = self.tree.identify_row(event.y)
        self.tree.selection_set(target or ())

    def _finish_drag(self, event):
        dragged = getattr(self, '_drag_items', ())
        self.__dict__.pop('_drag_items', None)
        self.__dict__.pop('_drag_start', None)
        target = self.tree.identify_row(event.y)
        if not target or not dragged:
            return
        destination_path = self._tree_folder_paths.get(
            target,
            self._folder_path_for_item(target)
        )
        if destination_path is None:
            return

        bookmark_keys = [
            self._tree_bookmark_keys[item]
            for item in dragged
            if item in self._tree_bookmark_keys
        ]
        if not bookmark_keys:
            return
        try:
            self.store.move_bookmarks(bookmark_keys, destination_path)
        except ValueError as error:
            messagebox.showerror('Cannot Move Item', str(error))
            return
        self.refresh_bookmark_views()
        self.status.config(text='Moved selected item(s).')

    def _folder_path_for_item(self, item_id):
        parent = self.tree.parent(item_id)
        while parent and parent not in self._tree_folder_paths:
            parent = self.tree.parent(parent)
        return self._tree_folder_paths.get(parent)

    def save_bookmarks_folders(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension='.json',
            filetypes=[('JSON files', '*.json')]
        )
        if not file_path:
            return

        self._set_busy(True, 'Saving bookmark folders...')
        try:
            WorkspaceRepository(file_path).save(self.store)
            self.status.config(text='Bookmark folders saved.')
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror(
                'Save Failed',
                f'Could not save the bookmark folders:\n{error}'
            )
            self.status.config(text='Save failed.')
        finally:
            self._set_busy(False)

    def load_bookmarks_folders(self):
        file_path = filedialog.askopenfilename(filetypes=[('JSON files', '*.json')])
        if not file_path:
            return

        self._set_busy(True, 'Loading bookmark folders...')
        try:
            self.store = WorkspaceRepository(file_path).load()
            self.refresh_bookmark_views()
            self.status.config(text=f'Loaded {len(self.bookmarks)} bookmarks.')
        except (OSError, UnicodeError, ValueError) as error:
            messagebox.showerror(
                'Load Failed',
                f'Could not load the bookmark folders:\n{error}'
            )
            self.status.config(text='Load failed.')
        finally:
            self._set_busy(False)

    def export_html(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension='.html',
            filetypes=[('HTML files', '*.html')],
            initialfile='bookmarks_export.html'
        )
        if not file_path:
            return

        self._set_busy(True, 'Exporting bookmark HTML...')
        temporary_path = None
        try:
            destination = os.path.abspath(file_path)
            directory = os.path.dirname(destination)
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=directory,
                prefix='.bookmark-export-',
                suffix='.tmp',
                delete=False
            ) as temporary_file:
                temporary_path = temporary_file.name
                temporary_file.write(bookmark_store_to_html(self.store))
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            os.replace(temporary_path, destination)
            temporary_path = None
            self.status.config(
                text=f'Exported {len(self.bookmarks)} bookmarks to HTML.'
            )
            messagebox.showinfo(
                'Export Complete',
                f'Bookmarks exported successfully:\n{destination}'
            )
        except (OSError, TypeError, ValueError) as error:
            messagebox.showerror(
                'Export Failed',
                f'Could not export bookmark HTML:\n{error}'
            )
            self.status.config(text='Export failed.')
        finally:
            if temporary_path is not None:
                if os.path.exists(temporary_path):
                    os.unlink(temporary_path)
            self._set_busy(False)

if __name__ == '__main__':
    root = tk.Tk()
    app = BookmarkApp(root)
    root.mainloop()
