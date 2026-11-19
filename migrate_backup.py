import argparse

from backend.persistence import WorkspaceRepository


def main():
    parser = argparse.ArgumentParser(
        description='Validate and migrate a bookmark JSON backup.'
    )
    parser.add_argument('source', help='Existing bookmark JSON backup')
    parser.add_argument('destination', help='Versioned output JSON file')
    arguments = parser.parse_args()

    store = WorkspaceRepository.migrate(
        arguments.source,
        arguments.destination,
    )
    print(
        f'Migrated {len(store.bookmarks)} bookmarks to '
        f'{arguments.destination}.'
    )


if __name__ == '__main__':
    main()
