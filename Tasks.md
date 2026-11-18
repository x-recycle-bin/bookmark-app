# Bookmark Organizer Development Tasks

## Current state

The README describes a complete bookmark organizer, but the current
`bookmark_app.py` still has a flat list and does not yet support complete
folder-aware organization. HTML import and basic JSON save/load are wired
through a responsive shell; controls and methods for organization, URL
checking, AI grouping, settings, and HTML export are still absent or commented
out.

The current worktree contains additional, uncommitted parser work in
`bookmark_app.py` and an untracked `parser_test.py`. Preserve and reconcile that
work instead of restoring the previous committed implementation wholesale.

## Priority 0: Recover a usable baseline

### 1. Stabilize the application shell

- [x] Create the status label and enable every control that is implemented.
- [x] Make window sizing, layout, scrolling, and resizing usable with large
  bookmark files.
- [x] Add explicit handling for file read/write and JSON errors.
- [x] Marshal background validation and AI UI updates through `root.after` by
  routing worker results and exceptions through `run_background()`.
- [x] Disable conflicting actions while an import or active persistence
  is running.

**Acceptance criteria**

- The app launches without errors.
- Import, folder, persistence, validation, and export actions are reachable
  from the GUI once implemented.
- Canceling a file dialog leaves the current data unchanged.
- Failures show a useful message without leaving the UI frozen.

### 2. Define one bookmark and folder data model

- [x] Introduce typed data structures for bookmarks and folders rather than
  passing loosely validated dictionaries between methods.
- [x] Preserve at least `title`, `url`, original folder, optional browser
  metadata, and an assignment key.
- [x] Ensure `self.bookmarks`, `self.bookmarks_folders`, the list display, and
  exported output cannot drift out of sync.
- [x] Define how duplicate URLs, duplicate titles, uncategorized bookmarks, and
  bookmarks in nested folders are represented.

Duplicate policy: separate assignment keys represent separate bookmark records,
so equal titles or URLs remain valid until duplicate detection is implemented.
The same assignment key may occur only once in the hierarchy; root-level
bookmarks are uncategorized and nested folders retain their full path.

**Acceptance criteria**

- Every UI and persistence operation uses the same model.
- Folder membership is explicit and deterministic.
- Tests cover duplicate bookmarks and a bookmark assigned to one or more
  folders according to the documented rule.

### 3. Replace the flat HTML parser with a folder-aware parser

- [x] Complete and integrate folder parsing in `BookmarkDirectory` or replace
  it with a single parser that tracks `<H3>`, `<A>`, nested `<DL>`, and
  `PERSONAL_TOOLBAR_FOLDER`.
- [x] Preserve the browser folder hierarchy and recognize the Bookmarks bar
  without relying only on its display text.
- [x] Decode HTML entities and assemble titles containing nested or split text.
- [x] Ignore malformed links lacking a usable `href` or title while reporting
  the number skipped.
- [x] Support Chrome, Firefox, Safari, and Edge Netscape bookmark exports.

**Acceptance criteria**

- The sample file imports all expected bookmarks and their folder paths.
- The parser handles top-level and nested folders, empty folders, entities,
  icon data, and differently cased tags.
- A malformed file fails clearly instead of silently returning an apparently
  successful empty import.

### 4. Remove all-disabled implementation debt

- [x] Remove obsolete commented blocks rather than keeping a second dormant
  implementation in `bookmark_app.py`.
- [x] Re-enable behavior by moving it into the typed model and UI, not by only
  uncommenting old methods.
- [x] Remove unused imports and the unused top-level state or parser code that
  remains after the refactor.
- [x] Fix inconsistent comments and naming around bookmarks, collections, and
  folders.

**Acceptance criteria**

- One active implementation owns each feature.
- `bookmark_app.py` has no commented-out production feature blocks.
- The module compiles cleanly.

## Priority 1: Complete the README workflow

### 5. Implement folder management and manual organization

- [x] Display folder structure separately from the flat bookmark list, using a
  `Treeview` or an equivalent hierarchical control.
- [x] Support creating, renaming, and deleting folders.
- [x] Support assigning a bookmark by double-click/context menu and moving it
  between folders.
- [x] Use the documented double-click/menu-based alternative instead of
  platform-dependent Tkinter drag-and-drop.
- [x] Keep the Bookmarks bar visible and protected from AI reclassification
  and destructive organization.

**Acceptance criteria**

- A user can manually complete the import, organize, and export workflow
  without an API key.
- Moving or deleting a folder does not silently lose bookmarks.
- The folder view stays synchronized with the underlying model.

### 6. Add duplicate detection and resolution

- [x] Detect duplicates by normalized URL, with a URL normalization rule for
  fragments, host casing, and trailing slashes.
- [x] Show duplicate groups and allow keep-all, keep-first, or merge-folder
  resolution.
- [x] Do not perform destructive duplicate removal without user confirmation.
- [x] Apply the shared normalization logic to the current store regardless of
  whether it came from import or JSON load; future AI grouping will use the
  same service-level function.

**Acceptance criteria**

- Exact URL duplicates and normalized-equivalent URLs are found.
- Removing duplicates produces no empty folder references or lost unique
  bookmarks.

### 7. Implement JSON save/load safely

- [x] Define and version the JSON schema.
- [x] Save the complete folder hierarchy and enough metadata to reproduce the
  current organization.
- [x] Validate parsed JSON types, required fields, folder names, and bookmark
  URLs before replacing app state.
- [x] Reject unsupported schema versions and display a specific error.
- [x] Load only after validation succeeds; preserve the current state on
  failure.

**Acceptance criteria**

- Save/load round-trips the full hierarchy without data loss.
- Invalid, truncated, or incompatible JSON does not corrupt the active
  session.

### 8. Restore browser-compatible HTML export

- [x] Export Netscape bookmark HTML with valid UTF-8 metadata and preserved
  nested folders.
- [x] Escape titles and all attribute values, including URLs containing quotes
  or ampersands.
- [x] Preserve the Bookmarks bar unchanged and apply the rule consistently to
  export and future AI grouping; align this decision
  with the README.
- [x] Export uncategorized bookmarks once in an explicit `Uncategorized` folder.
- [x] Write to a temporary file and replace the destination only after a
  successful export.

**Acceptance criteria**

- A generated file can be parsed by the app again without bookmark or folder
  loss.
- Special characters round-trip correctly.
- No duplicate bookmark is emitted solely because the display model contains
  duplicate references.

### 9. Implement URL health checking

- [x] Check URLs in a worker thread with a timeout and bounded concurrency.
- [x] Use `HEAD` first, fall back to `GET` when a server rejects it, and follow
  redirects with a documented redirect limit.
- [x] Distinguish reachable, redirected, client error, server error, timeout,
  invalid URL, and network failure.
- [x] Provide progress, cancellation, a result summary, and a review step before
  deleting dead links.
- [x] Do not treat every non-2xx response or a timeout as safe proof that a link
  should be deleted.

**Acceptance criteria**

- The UI remains responsive while checking.
- Network outcomes are visible and deletion remains user-controlled.
- Tests mock `requests` and cover redirects, `HEAD` fallback, timeouts, and
  malformed URLs.

## Priority 2: AI organization

### 10. Isolate AI configuration and transport

- [x] Replace direct API calls in UI methods with an AI service interface that
  can be tested independently.
- [x] Keep the API key out of source, logs, exported files, and JSON backups.
- [x] Document temporary runtime configuration and, if persistent storage is
  offered, use the operating system's credential manager.
- [x] Configure model, endpoint, timeout, and batch size in one place.
- [x] Add retry limits for transient responses without duplicating bookmarks
  after a partial success.

**Acceptance criteria**

- The non-AI workflow does not require an API key.
- AI service tests run without network access.
- Sensitive values never appear in errors or saved project data.

### 11. Restore safe, batched AI grouping

- [x] Validate the API response against a strict expected schema before
  changing bookmark folders.
- [x] Classify every input bookmark exactly once, or explicitly report
  unclassified items.
- [x] Keep existing folder assignments and the Bookmarks bar policy in the
  prompt and merge result.
- [x] Report per-batch progress, failures, retryable items, and a final summary.
- [x] Run AI grouping outside the Tkinter thread and support cancellation.
- [x] Require preview and confirmation before replacing the active folder
  structure.

**Acceptance criteria**

- Malformed or partial AI JSON cannot corrupt the active organization.
- A simulated failed batch leaves prior successful work reviewable.
- The same input cannot create duplicate bookmark entries.

### 12. Restore AI-assisted single-bookmark addition

- [x] Validate title and URL before classification.
- [x] Preview the suggested folder and let the user confirm or override it.
- [x] Use the same folder normalization and duplicate policy as bulk grouping.
- [x] Allow ordinary manual addition when AI is unavailable.

**Acceptance criteria**

- A user can add a bookmark manually without an API key.
- AI classification failure does not lose the entered bookmark.

## Priority 3: Quality, tests, and release readiness

### 13. Convert parser experiments into automated tests

- [ ] Replace or move `parser_test.py` into a proper `tests/` test suite.
- [ ] Use Python's `unittest` or add one explicit test dependency for `pytest`.
- [ ] Add fixtures for nested folders, a Bookmarks bar, entities, malformed
  links, duplicate URLs, empty folders, and special-character export.
- [ ] Cover JSON versioning/validation, folder moves, and export re-import.
- [ ] Mock network and AI calls; the test suite must not depend on internet
  access or a real API key.

**Acceptance criteria**

- A single documented command runs all tests.
- Core parser, organization, persistence, and export tests pass offline.
- No test writes into tracked sample or user data files.

### 14. Add integration and GUI smoke coverage

- [ ] Add an end-to-end test for import, group, save, load, and export using
  temporary files.
- [ ] Add a headless-safe Tkinter smoke check or clearly document any GUI test
  requiring a display.
- [ ] Verify that the real sample import does not create empty titles or URLs.
- [ ] Add a large-file fixture or generated dataset to check responsiveness and
  memory behavior.

**Acceptance criteria**

- The complete documented workflow runs automatically against temporary data.
- Tests catch broken folder hierarchy, status-label references, and missing
  UI wiring.

### 15. Add project hygiene and reproducible setup

- [ ] Pin or define compatible versions in `requirements.txt`.
- [ ] Separate runtime and test dependencies if a test package is added.
- [ ] Add a standard lint/format/type-check configuration only after the core
  refactor is stable.
- [ ] Keep virtual environments, archives, generated exports, API keys, and
  large personal bookmark files out of tracked source.
- [ ] Add a small, sanitized bookmark fixture suitable for documentation and
  tests.

**Acceptance criteria**

- A fresh environment installs with the README commands.
- The repository can be cloned and tested without personal bookmark data.

### 16. Reconcile the README with implemented behavior

- [ ] Mark features as available only after their tests pass.
- [ ] Replace stale claims about `test_complete_workflow.py`, performance,
  supported operations, and the file tree unless those artifacts exist.
- [ ] Document the JSON schema, Bookmarks bar rule, duplicate policy, AI
  configuration, privacy behavior, and cancellation behavior.
- [ ] Add troubleshooting for display/Tkinter requirements, malformed imports,
  network validation, and API errors.

**Acceptance criteria**

- Every quick-start step can be followed with the current repository.
- The README does not advertise a feature that is still disabled or
  unimplemented.

## Recommended implementation order

1. Complete tasks 1-4 to establish a stable, testable application core.
2. Complete tasks 5-8 for the non-AI import-to-export workflow.
3. Complete task 13 early enough to test each core change as it lands.
4. Complete tasks 9 and 14, then add AI through tasks 10-12.
5. Finish tasks 15-16 before calling the application release-ready.

## Definition of done

- [ ] Fresh install instructions succeed on a clean environment.
- [ ] The full manual import/organize/save/load/export workflow passes.
- [ ] Automated tests pass without network credentials or private bookmark
  data.
- [ ] AI grouping is optional, previewable, cancellable, and schema-validated.
- [ ] Failed I/O, malformed input, API failures, and network failures leave the
  active session usable.
- [ ] README behavior and the implemented behavior match.