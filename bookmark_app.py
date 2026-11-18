import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
import queue
import threading
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
import requests


@dataclass(frozen=True)
class Bookmark:
    title: str
    url: str
    assignment_key: str = field(default_factory=lambda: uuid4().hex)
    original_folder: tuple[str, ...] = ()
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        title = self.title.strip()
        url = self.url.strip()
        assignment_key = self.assignment_key.strip()
        if not title:
            raise ValueError('Bookmark title cannot be empty.')
        if not url:
            raise ValueError('Bookmark URL cannot be empty.')
        if not assignment_key:
            raise ValueError('Bookmark assignment key cannot be empty.')
        object.__setattr__(self, 'title', title)
        object.__setattr__(self, 'url', url)
        object.__setattr__(self, 'assignment_key', assignment_key)
        object.__setattr__(self, 'original_folder', tuple(self.original_folder))
        object.__setattr__(self, 'metadata', dict(self.metadata))

    def to_dict(self):
        return {
            'title': self.title,
            'url': self.url,
            'assignment_key': self.assignment_key,
            'original_folder': list(self.original_folder),
            'metadata': self.metadata,
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('Bookmark must be a JSON object.')
        title = value.get('title')
        url = value.get('url')
        assignment_key = value.get('assignment_key') or uuid4().hex
        original_folder = value.get('original_folder', [])
        metadata = value.get('metadata', {})

        if not isinstance(title, str) or not isinstance(url, str):
            raise ValueError('Bookmark title and URL must be strings.')
        if not isinstance(assignment_key, str):
            raise ValueError('Bookmark assignment key must be a string.')
        if (
            not isinstance(original_folder, list)
            or not all(isinstance(part, str) for part in original_folder)
        ):
            raise ValueError('Bookmark original folder must be a list of strings.')
        if not isinstance(metadata, dict) or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in metadata.items()
        ):
            raise ValueError('Bookmark metadata must contain string values.')

        return cls(
            title=title,
            url=url,
            assignment_key=assignment_key,
            original_folder=tuple(original_folder),
            metadata=metadata,
        )


@dataclass(frozen=True)
class UrlCheckResult:
    bookmark: Bookmark
    outcome: str
    detail: str


@dataclass(frozen=True)
class AiConfig:
    api_key: str
    endpoint: str = 'https://api.openai.com/v1/chat/completions'
    model: str = 'gpt-4o-mini'
    timeout: float = 30
    batch_size: int = 50
    retries: int = 2

    @classmethod
    def from_environment(cls):
        return cls(
            api_key=os.environ.get('OPENAI_API_KEY', '').strip(),
            endpoint=os.environ.get(
                'BOOKMARK_AI_ENDPOINT',
                'https://api.openai.com/v1/chat/completions',
            ).strip(),
            model=os.environ.get(
                'BOOKMARK_AI_MODEL',
                'gpt-4o-mini',
            ).strip(),
            timeout=float(os.environ.get('BOOKMARK_AI_TIMEOUT', '30')),
            batch_size=int(os.environ.get('BOOKMARK_AI_BATCH_SIZE', '50')),
            retries=int(os.environ.get('BOOKMARK_AI_RETRIES', '2')),
        )

    def __post_init__(self):
        if not self.endpoint:
            raise ValueError('AI endpoint cannot be empty.')
        if not self.model:
            raise ValueError('AI model cannot be empty.')
        if self.timeout <= 0 or self.batch_size <= 0 or self.retries < 0:
            raise ValueError('AI timeout, batch size, and retries are invalid.')

    def with_key(self, api_key):
        return AiConfig(
            api_key=api_key.strip(),
            endpoint=self.endpoint,
            model=self.model,
            timeout=self.timeout,
            batch_size=self.batch_size,
            retries=self.retries,
        )


class AiResponseError(ValueError):
    pass


class AiOrganizer:
    def __init__(self, config, session=None):
        self.config = config
        self.session = session or requests.Session()

    def classify_batch(self, bookmarks, existing_folder_paths):
        if not self.config.api_key:
            raise ValueError('An AI API key is required.')
        request_items = [
            {
                'assignment_key': bookmark.assignment_key,
                'title': bookmark.title,
                'url': bookmark.url,
            }
            for bookmark in bookmarks
        ]
        prompt = (
            'Classify each bookmark into one useful folder. '
            'Return only JSON with shape '
            '{"assignments":[{"assignment_key":"...","folder":"Folder Name"}]}. '
            'Every assignment_key from bookmarks must appear exactly once. '
            'Folder names must be concise, non-empty strings. '
            'Existing folders may be reused.\n'
            f'Existing folders: {json.dumps(existing_folder_paths)}\n'
            f'Bookmarks: {json.dumps(request_items)}'
        )

        content = self._request_content(prompt)
        payload = self._parse_json_content(content)
        return self._validate_assignments(payload, bookmarks)

    def suggest_folder(self, bookmark, existing_folder_paths):
        assignments = self.classify_batch([bookmark], existing_folder_paths)
        return assignments[bookmark.assignment_key]

    def _request_content(self, prompt):
        last_error = None
        for attempt in range(self.config.retries + 1):
            try:
                response = self.session.post(
                    self.config.endpoint,
                    headers={
                        'Authorization': f'Bearer {self.config.api_key}',
                        'Content-Type': 'application/json',
                    },
                    json={
                        'model': self.config.model,
                        'temperature': 0.1,
                        'messages': [
                            {
                                'role': 'system',
                                'content': (
                                    'You classify bookmarks and return only '
                                    'strict JSON.'
                                ),
                            },
                            {'role': 'user', 'content': prompt},
                        ],
                    },
                    timeout=self.config.timeout,
                )
                status_code = response.status_code
                if (
                    status_code in {408, 429}
                    or isinstance(status_code, int) and status_code >= 500
                ):
                    last_error = AiResponseError(
                        f'AI service returned HTTP {status_code}.'
                    )
                    if attempt < self.config.retries:
                        time.sleep(0.25 * (2 ** attempt))
                        continue
                    break
                response.raise_for_status()
                response_json = response.json()
                return response_json['choices'][0]['message']['content']
            except (requests.Timeout, requests.ConnectionError) as error:
                last_error = error
                if attempt < self.config.retries:
                    time.sleep(0.25 * (2 ** attempt))
                    continue
                break
            except (requests.RequestException, KeyError, IndexError, TypeError) as error:
                raise AiResponseError(
                    f'AI request failed: {error.__class__.__name__}.'
                ) from error
            except (ValueError, json.JSONDecodeError) as error:
                raise AiResponseError('AI service returned invalid JSON.') from error

        message = (
            f'AI request failed after {self.config.retries + 1} attempts: '
            f'{last_error.__class__.__name__}.'
        )
        if isinstance(last_error, AiResponseError):
            message = str(last_error)
        raise AiResponseError(message)

    @staticmethod
    def _parse_json_content(content):
        if not isinstance(content, str):
            raise AiResponseError('AI response content must be text.')
        stripped = content.strip()
        if stripped.startswith('```'):
            lines = stripped.splitlines()
            if lines and lines[0].startswith('```'):
                lines = lines[1:]
            if lines and lines[-1].strip() == '```':
                lines = lines[:-1]
            stripped = '\n'.join(lines).strip()
        try:
            return json.loads(stripped)
        except json.JSONDecodeError as error:
            raise AiResponseError('AI response was not strict JSON.') from error

    @staticmethod
    def _validate_assignments(payload, bookmarks):
        if not isinstance(payload, dict) or set(payload) != {'assignments'}:
            raise AiResponseError(
                'AI response must contain only an assignments array.'
            )
        assignments = payload['assignments']
        if not isinstance(assignments, list):
            raise AiResponseError('AI assignments must be an array.')

        expected = {bookmark.assignment_key for bookmark in bookmarks}
        result = {}
        for item in assignments:
            if not isinstance(item, dict) or set(item) != {
                'assignment_key',
                'folder',
            }:
                raise AiResponseError('AI assignment objects are invalid.')
            key = item['assignment_key']
            folder = item['folder']
            if not isinstance(key, str) or key not in expected:
                raise AiResponseError(
                    'AI response contains an unknown assignment key.'
                )
            if key in result:
                raise AiResponseError(
                    'AI response contains a duplicate assignment key.'
                )
            if not isinstance(folder, str) or not folder.strip():
                raise AiResponseError('AI folder names cannot be empty.')
            result[key] = folder.strip()

        if set(result) != expected:
            missing = len(expected - set(result))
            raise AiResponseError(
                f'AI response omitted {missing} bookmark assignment(s).'
            )
        return result


@dataclass
class BookmarkFolder:
    name: str
    bookmarks: list[Bookmark] = field(default_factory=list)
    children: list['BookmarkFolder'] = field(default_factory=list)
    is_bookmarks_bar: bool = False
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        self.name = self.name.strip()
        if not self.name:
            raise ValueError('Folder name cannot be empty.')
        self.metadata = dict(self.metadata)

    def iter_folders(self, parent_path=()):
        path = parent_path + (self.name,)
        yield path, self
        for child in self.children:
            yield from child.iter_folders(path)

    def iter_bookmarks(self):
        yield from self.bookmarks
        for child in self.children:
            yield from child.iter_bookmarks()

    def to_dict(self):
        return {
            'name': self.name,
            'is_bookmarks_bar': self.is_bookmarks_bar,
            'metadata': self.metadata,
            'bookmarks': [bookmark.to_dict() for bookmark in self.bookmarks],
            'folders': [folder.to_dict() for folder in self.children],
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('Folder must be a JSON object.')
        name = value.get('name')
        bookmarks = value.get('bookmarks', [])
        folders = value.get('folders', [])
        is_bookmarks_bar = value.get('is_bookmarks_bar', False)
        metadata = value.get('metadata', {})
        if not isinstance(name, str):
            raise ValueError('Folder name must be a string.')
        if not isinstance(bookmarks, list) or not isinstance(folders, list):
            raise ValueError('Folder bookmarks and folders must be lists.')
        if not isinstance(is_bookmarks_bar, bool):
            raise ValueError('Folder is_bookmarks_bar value must be boolean.')
        if not isinstance(metadata, dict) or not all(
            isinstance(key, str) and isinstance(item, str)
            for key, item in metadata.items()
        ):
            raise ValueError('Folder metadata must contain string values.')
        return cls(
            name=name,
            bookmarks=[Bookmark.from_dict(item) for item in bookmarks],
            children=[cls.from_dict(item) for item in folders],
            is_bookmarks_bar=is_bookmarks_bar,
            metadata=metadata,
        )


class BookmarkStore:
    SCHEMA_VERSION = 1

    def __init__(self, uncategorized=None, folders=None):
        self.uncategorized = list(uncategorized or [])
        self.folders = list(folders or [])
        self.validate()

    @property
    def bookmarks(self):
        return list(self.uncategorized) + [
            bookmark
            for folder in self.folders
            for bookmark in folder.iter_bookmarks()
        ]

    @property
    def flattened_folders(self):
        result = {}
        for folder in self.folders:
            for path, child in folder.iter_folders():
                result[' / '.join(path)] = child.bookmarks
        return result

    @property
    def folder_paths(self):
        paths = []
        for folder in self.folders:
            paths.extend(path for path, _ in folder.iter_folders())
        return paths

    def find_folder(self, path):
        path = tuple(path)
        for folder_path, folder in self._iter_folder_locations():
            if folder_path == path:
                return folder
        return None

    def create_folder(self, name, parent_path=()):
        name = name.strip()
        if not name:
            raise ValueError('Folder name cannot be empty.')
        siblings = self._folder_children(tuple(parent_path))
        if any(folder.name == name for folder in siblings):
            raise ValueError(f'A folder named "{name}" already exists here.')
        folder = BookmarkFolder(name=name)
        siblings.append(folder)
        return folder

    def rename_folder(self, path, new_name):
        path = tuple(path)
        folder = self._require_folder(path)
        if folder.is_bookmarks_bar:
            raise ValueError('The Bookmarks bar cannot be renamed.')
        new_name = new_name.strip()
        if not new_name:
            raise ValueError('Folder name cannot be empty.')
        siblings = self.folders if len(path) == 1 else self._require_folder(
            path[:-1]
        ).children
        if any(
            sibling is not folder and sibling.name == new_name
            for sibling in siblings
        ):
            raise ValueError(f'A folder named "{new_name}" already exists here.')
        folder.name = new_name

    def delete_folder(self, path):
        path = tuple(path)
        folder = self._require_folder(path)
        if folder.is_bookmarks_bar:
            raise ValueError('The Bookmarks bar cannot be deleted.')
        siblings = self.folders if len(path) == 1 else self._require_folder(
            path[:-1]
        ).children
        siblings.remove(folder)

        if len(path) == 1:
            self.uncategorized.extend(folder.bookmarks)
            self.folders.extend(folder.children)
        else:
            parent = self._require_folder(path[:-1])
            parent.bookmarks.extend(folder.bookmarks)
            parent.children.extend(folder.children)
        self.validate()
        return folder

    def find_bookmark(self, assignment_key):
        for index, bookmark in enumerate(self.uncategorized):
            if bookmark.assignment_key == assignment_key:
                return self.uncategorized, index, bookmark
        for _, folder in self._iter_folder_locations():
            for index, bookmark in enumerate(folder.bookmarks):
                if bookmark.assignment_key == assignment_key:
                    return folder.bookmarks, index, bookmark
        raise ValueError('Bookmark no longer exists.')

    def move_bookmark(self, assignment_key, destination_path=()):
        source, source_index, bookmark = self.find_bookmark(assignment_key)
        destination = self.uncategorized
        if destination_path:
            destination = self._require_folder(tuple(destination_path)).bookmarks
        if source is destination:
            return
        source.pop(source_index)
        destination.append(bookmark)
        self.validate()

    def bookmark_path(self, assignment_key):
        if any(
            bookmark.assignment_key == assignment_key
            for bookmark in self.uncategorized
        ):
            return ()
        for path, folder in self._iter_folder_locations():
            if any(
                bookmark.assignment_key == assignment_key
                for bookmark in folder.bookmarks
            ):
                return path
        raise ValueError('Bookmark no longer exists.')

    def protected_bookmark_keys(self):
        protected = set()
        for folder in self.folders:
            if not any(
                location[1].is_bookmarks_bar
                for location in folder.iter_folders()
            ):
                continue
            for location in folder.iter_folders():
                path_folder = location[1]
                if path_folder.is_bookmarks_bar:
                    protected.update(
                        bookmark.assignment_key
                        for bookmark in path_folder.iter_bookmarks()
                    )
        return protected

    def has_normalized_url(self, url):
        normalized = normalize_bookmark_url(url)
        return any(
            normalize_bookmark_url(bookmark.url) == normalized
            for bookmark in self.bookmarks
        )

    def ensure_folder_path(self, parts):
        if not parts:
            return ()
        clean_parts = []
        for part in parts:
            name = part.strip()
            if not name:
                raise ValueError('AI folder paths cannot contain empty names.')
            clean_parts.append(name)
        if clean_parts and any(
            folder.is_bookmarks_bar and folder.name.casefold() == clean_parts[0].casefold()
            for folder in self.folders
        ):
            raise ValueError('AI cannot move bookmarks into the Bookmarks bar.')

        path = ()
        for index, name in enumerate(clean_parts):
            current = path + (name,)
            folder = self.find_folder(current)
            if folder is None:
                folder = self.create_folder(name, path)
            if folder.is_bookmarks_bar and index >= 0:
                raise ValueError('AI cannot use the Bookmarks bar.')
            path = current
        return path

    def duplicate_groups(self):
        groups = {}
        for bookmark in self.bookmarks:
            normalized_url = normalize_bookmark_url(bookmark.url)
            groups.setdefault(normalized_url, []).append(bookmark)
        return [
            bookmarks
            for bookmarks in groups.values()
            if len(bookmarks) > 1
        ]

    def remove_bookmarks(self, assignment_keys):
        keys = set(assignment_keys)
        original_count = len(self.bookmarks)
        self.uncategorized[:] = [
            bookmark
            for bookmark in self.uncategorized
            if bookmark.assignment_key not in keys
        ]
        for location in self._iter_folder_locations():
            folder = location[1]
            folder.bookmarks[:] = [
                bookmark
                for bookmark in folder.bookmarks
                if bookmark.assignment_key not in keys
            ]
        self.validate()
        return original_count - len(self.bookmarks)

    def resolve_duplicates(self, strategy):
        if strategy not in {'keep-all', 'keep-first', 'merge-folder'}:
            raise ValueError(f'Unknown duplicate strategy: {strategy}.')
        groups = self.duplicate_groups()
        if strategy == 'keep-all':
            return 0

        changed = 0
        for group in groups:
            if strategy == 'merge-folder':
                destination = self.bookmark_path(group[0].assignment_key)
                for bookmark in group[1:]:
                    self.move_bookmark(bookmark.assignment_key, destination)
                    changed += 1
                continue

            for bookmark in group[1:]:
                source, index, stored = self.find_bookmark(
                    bookmark.assignment_key
                )
                if stored is not bookmark:
                    raise ValueError('Bookmark data changed during resolution.')
                source.pop(index)
                changed += 1
        self.validate()
        return changed

    def _folder_children(self, path):
        return self.folders if not path else self._require_folder(path).children

    def _require_folder(self, path):
        folder = self.find_folder(path)
        if folder is None:
            raise ValueError(f'Folder "{" / ".join(path)}" does not exist.')
        return folder

    def _iter_folder_locations(self):
        for folder in self.folders:
            yield from folder.iter_folders()

    def validate(self):
        assignment_keys = [
            bookmark.assignment_key
            for bookmark in self.bookmarks
        ]
        if len(assignment_keys) != len(set(assignment_keys)):
            raise ValueError(
                'A bookmark cannot be assigned to more than one location.'
            )

    def replace_bookmarks(self, bookmarks):
        self.uncategorized = list(bookmarks)
        self.folders = []
        self.validate()

    def to_dict(self):
        self.validate()
        return {
            'version': self.SCHEMA_VERSION,
            'bookmarks': [bookmark.to_dict() for bookmark in self.uncategorized],
            'folders': [folder.to_dict() for folder in self.folders],
        }

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict):
            raise ValueError('Bookmark data must be a JSON object.')

        if 'version' not in value:
            return cls._from_legacy_dict(value)
        if value['version'] != cls.SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported bookmark schema version: {value['version']}."
            )

        uncategorized = value.get('bookmarks', [])
        folders = value.get('folders', [])
        if not isinstance(uncategorized, list) or not isinstance(folders, list):
            raise ValueError('Bookmark and folder groups must be lists.')
        return cls(
            uncategorized=[
                Bookmark.from_dict(bookmark) for bookmark in uncategorized
            ],
            folders=[
                BookmarkFolder.from_dict(folder) for folder in folders
            ],
        )

    @classmethod
    def _from_legacy_dict(cls, value):
        folders = []
        for name, bookmark_values in value.items():
            if not isinstance(name, str) or not isinstance(bookmark_values, list):
                raise ValueError(
                    'Legacy folders must map names to lists of bookmarks.'
                )
            folders.append(BookmarkFolder(
                name=name,
                bookmarks=[
                    Bookmark.from_dict(bookmark)
                    for bookmark in bookmark_values
                ],
            ))
        return cls(folders=folders)


def normalize_bookmark_url(url):
    parsed = urlsplit(url.strip())
    path = parsed.path.rstrip('/') or '/'
    return urlunsplit((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        path,
        parsed.query,
        '',
    ))


class BookmarkHTMLParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self._uncategorized = []
        self._folders = []
        self._pending_folder = None
        self._folder_stack = []
        self._dl_depth = 0
        self._title_parts = []
        self._link_attributes = None
        self.skipped_links = 0
        self._saw_list = False

    @property
    def store(self):
        return BookmarkStore(
            uncategorized=self._uncategorized,
            folders=self._folders,
        )

    @property
    def bookmarks(self):
        return self.store.bookmarks

    @property
    def malformed_file(self):
        return not self._saw_list

    def handle_starttag(self, tag, attrs):
        attributes = {
            key.lower(): value
            for key, value in attrs
            if value is not None
        }
        if tag == 'h3':
            self._title_parts = []
            self._pending_folder = {
                'attributes': attributes,
                'title_parts': self._title_parts,
            }
        elif tag == 'dl':
            self._saw_list = True
            self._dl_depth += 1
            if self._pending_folder is not None:
                folder_name = self._join_text(
                    self._pending_folder['title_parts']
                ) or 'Untitled Folder'
                folder = BookmarkFolder(
                    name=folder_name,
                    is_bookmarks_bar=(
                        self._pending_folder['attributes'].get(
                            'personal_toolbar_folder'
                        ).lower() == 'true'
                        if self._pending_folder['attributes'].get(
                            'personal_toolbar_folder'
                        )
                        else False
                    ),
                    metadata=self._pending_folder['attributes'],
                )
                if not folder.metadata.get('organizer_uncategorized'):
                    if self._folder_stack:
                        self._folder_stack[-1][0].children.append(folder)
                    else:
                        self._folders.append(folder)
                self._folder_stack.append((folder, self._dl_depth))
                self._pending_folder = None
                self._title_parts = []
        elif tag == 'a':
            if self._link_attributes is not None:
                self.skipped_links += 1
            self._link_attributes = attributes
            self._title_parts = []

    def handle_endtag(self, tag):
        if tag == 'dl':
            if (
                self._folder_stack
                and self._folder_stack[-1][1] == self._dl_depth
            ):
                self._folder_stack.pop()
            self._dl_depth = max(0, self._dl_depth - 1)
        elif tag == 'a' and self._link_attributes is not None:
            self._finish_link()

    def handle_data(self, data):
        if self._link_attributes is not None or self._pending_folder is not None:
            if data.strip():
                self._title_parts.append(data.strip())

    def close(self):
        super().close()
        if self._link_attributes is not None:
            self._finish_link()

    def _finish_link(self):
        attributes = self._link_attributes
        title = self._join_text(self._title_parts)
        url = (attributes or {}).get('href', '').strip()
        self._link_attributes = None
        self._title_parts = []

        if not title or not url:
            self.skipped_links += 1
            return

        path = tuple(
            folder.name
            for folder, _ in self._folder_stack
            if not folder.metadata.get('organizer_uncategorized')
        )
        bookmark = Bookmark(
            title=title,
            url=url,
            original_folder=path,
            metadata=dict(attributes or {}),
        )
        if (
            self._folder_stack
            and not self._folder_stack[-1][0].metadata.get(
                'organizer_uncategorized'
            )
        ):
            self._folder_stack[-1][0].bookmarks.append(bookmark)
        else:
            self._uncategorized.append(bookmark)

    @staticmethod
    def _join_text(parts):
        return ' '.join(' '.join(parts).split())


def bookmark_store_to_html(store):
        lines = [
            '<!DOCTYPE NETSCAPE-Bookmark-file-1>',
            '<!-- This is an automatically generated file. -->',
            '<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">',
            '<TITLE>Bookmarks</TITLE>',
            '<H1>Bookmarks</H1>',
            '<DL><p>',
        ]

        if store.uncategorized:
            lines.extend([
                '    <DT><H3 ORGANIZER_UNCATEGORIZED="true">Uncategorized</H3>',
                '    <DL><p>',
            ])
            for bookmark in store.uncategorized:
                lines.append(_bookmark_html(bookmark, 8))
            lines.append('    </DL><p>')

        for folder in store.folders:
            lines.extend(_folder_html(folder, 1))
        lines.append('</DL><p>')
        return '\n'.join(lines) + '\n'


def _folder_html(folder, depth):
        indent = '    ' * depth
        attributes = dict(folder.metadata)
        if folder.is_bookmarks_bar:
            attributes['personal_toolbar_folder'] = 'true'
        attribute_text = _html_attributes(attributes)
        lines = [
            f'{indent}<DT><H3{attribute_text}>{escape(folder.name)}</H3>',
            f'{indent}<DL><p>',
        ]
        for bookmark in folder.bookmarks:
            lines.append(_bookmark_html(bookmark, (depth + 1) * 4))
        for child in folder.children:
            lines.extend(_folder_html(child, depth + 1))
        lines.append(f'{indent}</DL><p>')
        return lines


def _bookmark_html(bookmark, spaces):
        attributes = dict(bookmark.metadata)
        attributes['href'] = bookmark.url
        return (
            f'{" " * spaces}<DT><A{_html_attributes(attributes)}>'
            f'{escape(bookmark.title)}</A>'
        )


def _html_attributes(attributes):
        if not attributes:
            return ''
        return ''.join(
            f' {key.upper()}="{escape(value, quote=True)}"'
            for key, value in attributes.items()
        )

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
            self.duplicates_btn,
            self.check_urls_btn,
            self.settings_btn,
            self.ai_group_btn,
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

        content = ttk.Panedwindow(frame, orient=tk.HORIZONTAL)
        content.grid(row=1, column=0, sticky=tk.NSEW)

        list_frame = tk.Frame(content)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(1, weight=1)
        content.add(list_frame, weight=3)
        tk.Label(list_frame, text='Bookmarks', anchor=tk.W).grid(
            row=0, column=0, sticky=tk.EW, pady=(0, 5)
        )
        self.listbox = tk.Listbox(
            list_frame,
            width=55,
            height=15,
            activestyle='dotbox'
        )
        self.listbox.grid(row=1, column=0, sticky=tk.NSEW)
        y_scrollbar = tk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        y_scrollbar.grid(row=1, column=1, sticky=tk.NS)
        x_scrollbar = tk.Scrollbar(list_frame, orient=tk.HORIZONTAL, command=self.listbox.xview)
        x_scrollbar.grid(row=2, column=0, sticky=tk.EW)
        self.listbox.config(
            yscrollcommand=y_scrollbar.set,
            xscrollcommand=x_scrollbar.set
        )
        self.listbox.bind(
            '<Double-Button-1>',
            self._list_double_click
        )

        tree_frame = tk.Frame(content)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(1, weight=1)
        content.add(tree_frame, weight=2)
        tk.Label(tree_frame, text='Folders', anchor=tk.W).grid(
            row=0, column=0, sticky=tk.EW, pady=(0, 5)
        )
        self.tree = ttk.Treeview(tree_frame, selectmode='browse', show='tree')
        self.tree.grid(row=1, column=0, sticky=tk.NSEW)
        tree_scrollbar = tk.Scrollbar(
            tree_frame,
            orient=tk.VERTICAL,
            command=self.tree.yview
        )
        tree_scrollbar.grid(row=1, column=1, sticky=tk.NS)
        self.tree.configure(yscrollcommand=tree_scrollbar.set)
        self.tree.bind('<Double-Button-1>', self._tree_double_click)

        self.status = tk.Label(frame, text='Status: Ready', anchor=tk.W)
        self.status.grid(row=2, column=0, sticky=tk.EW, pady=(10, 0))
        self._tree_folder_paths = {}
        self._tree_bookmark_keys = {}
        self._listbox_bookmark_keys = []
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
            self.refresh_listbox(show_bookmarks_folders=True)
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

    def refresh_listbox(self, show_bookmarks_folders=False):
        del show_bookmarks_folders
        self.listbox.delete(0, tk.END)
        self._listbox_bookmark_keys = []
        for bookmark in self.bookmarks:
            self._listbox_bookmark_keys.append(bookmark.assignment_key)
            self.listbox.insert(
                tk.END,
                f"{bookmark.title} - {bookmark.url}"
            )
        self._refresh_tree()

    def refresh_bookmark_views(self):
        self.refresh_listbox(show_bookmarks_folders=True)

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
        path = self._selected_folder_path()
        if not path:
            messagebox.showerror('Rename Folder', 'Select a folder to rename.')
            return
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
        path = self._selected_folder_path()
        if not path:
            messagebox.showerror('Delete Folder', 'Select a folder to delete.')
            return
        folder = self.store.find_folder(path)
        if folder is None or folder.is_bookmarks_bar:
            messagebox.showerror(
                'Delete Folder',
                'The Bookmarks bar and Uncategorized cannot be deleted.'
            )
            return
        bookmark_count = len(list(folder.iter_bookmarks()))
        child_count = len(list(folder.iter_folders())) - 1
        detail = (
            f'This keeps {bookmark_count} bookmark(s) and promotes '
            f'{child_count} child folder(s) to the parent level.'
        )
        if not messagebox.askyesno(
            'Delete Folder',
            f'Delete "{folder.name}"?\n\n{detail}',
            icon='warning'
        ):
            return
        try:
            self.store.delete_folder(path)
            self.refresh_bookmark_views()
            self.status.config(text=f'Deleted folder "{folder.name}".')
        except ValueError as error:
            messagebox.showerror('Cannot Delete Folder', str(error))

    def move_selected_bookmark(self):
        assignment_key = self._selected_bookmark_key()
        if assignment_key is None:
            messagebox.showerror(
                'Move Bookmark',
                'Select a bookmark in the list or folder tree.'
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
            bookmark = self.store.find_bookmark(assignment_key)[2]
            self.store.move_bookmark(assignment_key, destination_path)
            self.refresh_bookmark_views()
            label = destination or 'Uncategorized'
            self.status.config(text=f'Moved "{bookmark.title}" to {label}.')
        except ValueError as error:
            messagebox.showerror('Cannot Move Bookmark', str(error))

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
            'OpenAI-compatible endpoint:',
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
        if messagebox.askyesno(
            'Review AI Organization',
            preview + '\n\nApply this organization?'
        ):
            self.store = proposed_store
            self.refresh_bookmark_views()
            self.status.config(
                text=f'Applied AI grouping to {classified} bookmark(s).'
            )
        else:
            self.status.config(text='AI grouping proposal was not applied.')

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

    def _list_double_click(self, event):
        del event
        self.move_selected_bookmark()

    def _tree_double_click(self, event):
        del event
        if self._selected_bookmark_key() is not None:
            self.move_selected_bookmark()

    def _selected_folder_path(self):
        selection = self.tree.selection()
        if not selection:
            return ()
        return self._tree_folder_paths.get(selection[0], ())

    def _selected_bookmark_key(self):
        tree_selection = self.tree.selection()
        if (
            tree_selection
            and tree_selection[0] in self._tree_bookmark_keys
        ):
            return self._tree_bookmark_keys[tree_selection[0]]
        list_selection = self.listbox.curselection()
        if list_selection:
            return self._listbox_bookmark_keys[list_selection[0]]
        return None

    def save_bookmarks_folders(self):
        file_path = filedialog.asksaveasfilename(
            defaultextension='.json',
            filetypes=[('JSON files', '*.json')]
        )
        if not file_path:
            return

        self._set_busy(True, 'Saving bookmark folders...')
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(self.store.to_dict(), f, indent=2)
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
            with open(file_path, 'r', encoding='utf-8') as f:
                loaded_folders = json.load(f)
            loaded_store = BookmarkStore.from_dict(loaded_folders)
            self.store = loaded_store
            self.refresh_listbox(show_bookmarks_folders=True)
            self.status.config(text=f'Loaded {len(self.bookmarks)} bookmarks.')
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
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
