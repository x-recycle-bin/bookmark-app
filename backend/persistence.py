import json
import os
import tempfile
from pathlib import Path

from .core import BookmarkStore


class WorkspaceRepository:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        with self.path.open('r', encoding='utf-8') as source:
            return BookmarkStore.from_dict(json.load(source))

    def save(self, store):
        payload = store.to_dict()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=self.path.parent,
                prefix=f'.{self.path.name}.',
                suffix='.tmp',
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                json.dump(payload, temporary, indent=2, ensure_ascii=False)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self.path)
            temporary_path = None
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    @staticmethod
    def migrate(source_path, destination_path):
        source_repository = WorkspaceRepository(source_path)
        destination_repository = WorkspaceRepository(destination_path)
        store = source_repository.load()
        destination_repository.save(store)
        return store
