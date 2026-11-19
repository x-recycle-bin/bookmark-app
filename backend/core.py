import json
import os
import time
from dataclasses import dataclass, field
from html import escape
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4
from openai import OpenAI
from openai import APIConnectionError, APIStatusError, APITimeoutError, InternalServerError, RateLimitError
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
    endpoint: str = 'https://api.openai.com/v1'
    model: str = 'gpt-6-astra'
    timeout: float = 30
    batch_size: int = 50
    retries: int = 2

    @classmethod
    def from_environment(cls):
        return cls(
            api_key=os.environ.get('OPENAI_API_KEY', '').strip(),
            endpoint=os.environ.get(
                'BOOKMARK_AI_ENDPOINT',
                'https://api.openai.com/v1',
            ).strip(),
            model=os.environ.get(
                'BOOKMARK_AI_MODEL',
                'gpt-6-astra',
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
    def __init__(self, config, client=None):
        self.config = config
        base_url = config.endpoint.removesuffix('/chat/completions')
        self.client = client or OpenAI(
            api_key=config.api_key,
            base_url=base_url,
            timeout=config.timeout,
            max_retries=0,
        )

    def classify_batch(
        self,
        bookmarks,
        existing_folder_paths,
        existing_folders_only=False,
    ):
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
            + (
                'The folder must exactly match one of Existing folders; '
                'do not invent a new folder.\n'
                if existing_folders_only
                else 'Existing folders may be reused.\n'
            )
            + f'Existing folders: {json.dumps(existing_folder_paths)}\n'
            + f'Bookmarks: {json.dumps(request_items)}'
        )

        content = self._request_content(prompt)
        payload = self._parse_json_content(content)
        assignments = self._validate_assignments(payload, bookmarks)
        if existing_folders_only:
            allowed = set(existing_folder_paths)
            invalid = sorted(set(assignments.values()) - allowed)
            if invalid:
                raise AiResponseError(
                    'AI selected a folder that does not exist: '
                    + ', '.join(invalid[:3])
                )
        return assignments

    def suggest_folder(self, bookmark, existing_folder_paths):
        assignments = self.classify_batch([bookmark], existing_folder_paths)
        return assignments[bookmark.assignment_key]

    def _request_content(self, prompt):
        last_error = None
        for attempt in range(self.config.retries + 1):
            session_id = None
            try:
                stream_context = self.client.beta.agents.sessions.create(
                    agent={
                        'model': self.config.model,
                        'instructions': (
                            'You classify bookmarks and return only strict '
                            'JSON. Do not use tools or create files.'
                        ),
                    },
                    environment={'type': 'none'},
                    input=prompt,
                    stream=True,
                    timeout=self.config.timeout,
                ).with_result_collection()
                with stream_context as stream:
                    for event in stream:
                        del event
                    result = stream.get_final_result()
                session_id = result.session_id
                output_text = result.output_text
                if not isinstance(output_text, str) or not output_text.strip():
                    raise AiResponseError('AI agent returned no output text.')
                return output_text
            except (
                APITimeoutError,
                APIConnectionError,
                RateLimitError,
                InternalServerError,
            ) as error:
                last_error = error
                if attempt < self.config.retries:
                    time.sleep(0.25 * (2 ** attempt))
                    continue
                break
            except APIStatusError as error:
                raise AiResponseError(
                    f'Agents API request failed with status {error.status_code}.'
                ) from error
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                if isinstance(error, AiResponseError):
                    raise
                raise AiResponseError(
                    f'Agents API returned an invalid result: '
                    f'{error.__class__.__name__}.'
                ) from error
            finally:
                if session_id is not None:
                    try:
                        self.client.beta.agents.sessions.delete(session_id)
                    except (
                        APITimeoutError,
                        APIConnectionError,
                        RateLimitError,
                        InternalServerError,
                        APIStatusError,
                    ):
                        pass

        message = (
            f'Agents API request failed after '
            f'{self.config.retries + 1} attempts: '
            f'{last_error.__class__.__name__}.'
        )
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

    def move_bookmarks(self, assignment_keys, destination_path=()):
        moved = 0
        for assignment_key in assignment_keys:
            before = self.bookmark_path(assignment_key)
            self.move_bookmark(assignment_key, destination_path)
            if before != tuple(destination_path):
                moved += 1
        return moved

    def update_bookmark(self, assignment_key, title, url):
        _source, _index, bookmark = self.find_bookmark(assignment_key)
        replacement = Bookmark(
            title=title,
            url=url,
            assignment_key=bookmark.assignment_key,
            original_folder=bookmark.original_folder,
            metadata=bookmark.metadata,
        )
        _source[_index] = replacement
        self.validate()
        return replacement

    def move_folder(self, path, destination_parent=()):
        path = tuple(path)
        destination_parent = tuple(destination_parent)
        folder = self._require_folder(path)
        if folder.is_bookmarks_bar:
            raise ValueError('The Bookmarks bar cannot be moved.')
        if destination_parent[:len(path)] == path:
            raise ValueError('A folder cannot be moved inside itself.')
        if destination_parent and self._require_folder(
            destination_parent
        ).is_bookmarks_bar:
            raise ValueError('Folders cannot be moved into the Bookmarks bar.')

        siblings = self.folders if len(path) == 1 else self._require_folder(
            path[:-1]
        ).children
        destination = (
            self.folders
            if not destination_parent
            else self._require_folder(destination_parent).children
        )
        if any(
            sibling is not folder and sibling.name == folder.name
            for sibling in destination
        ):
            raise ValueError(
                f'A folder named "{folder.name}" already exists at the destination.'
            )
        if siblings is destination:
            return
        siblings.remove(folder)
        destination.append(folder)

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

    def date_folder_paths(self):
        names = {'dates', 'даты'}
        return [
            path
            for path, folder in self._iter_folder_locations()
            if path[-1].casefold() in names
            and folder is not None
        ]

    def bookmarks_under_paths(self, source_paths):
        sources = {tuple(path) for path in source_paths}
        bookmarks = []
        for path, folder in self._iter_folder_locations():
            if any(path[:len(source)] == source for source in sources):
                bookmarks.extend(folder.bookmarks)
        return bookmarks

    @staticmethod
    def is_path_within(path, parent_paths):
        return any(
            tuple(path[:len(parent)]) == tuple(parent)
            for parent in parent_paths
        )

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

