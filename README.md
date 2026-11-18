# 🔖 Bookmark Organizer

A powerful Python application for organizing and managing browser bookmarks with AI-powered categorization and HTML export functionality.

## ✨ Features

### 📥 Import & Export
- **HTML Import**: Import bookmarks from any browser's exported HTML file
- **Browser-Ready Export**: Generate organized HTML files ready for browser import
- **JSON Backup**: Save and load bookmark folder configurations

### 🤖 AI-Powered Organization
- **Smart Categorization**: Automatically organize bookmarks using OpenAI GPT models
- **Batch Processing**: Handle large bookmark collections efficiently
- **Intelligent Naming**: AI suggests meaningful folder names

### 🔧 Management Tools
- **URL Validation**: Check links concurrently and review failed URLs before removal
- **Manual Organization**: Move bookmarks by double-click or the Move Bookmark control
- **Folder Management**: Create, rename, and organize bookmark folders
- **Duplicate Detection**: Identify and handle duplicate bookmarks

### 🎯 Special Features
- **Bookmarks Bar Protection**: Preserves the "Bookmarks bar" during organization and export
- **Multi-format Support**: Works with bookmarks from Chrome, Firefox, Safari, Edge
- **Clean Export**: Generates properly formatted HTML for seamless browser import

## 🚀 Quick Start

### Prerequisites
```bash
py -m pip install -r requirements.txt
```

### Basic Usage
1. **Launch the application:**
   ```bash
   py bookmark_app.py
   ```

2. **Import bookmarks:**
   - Click "Import Bookmarks"
   - Select your browser's exported HTML file
   - View imported bookmarks in the list

3. **Organize bookmarks:**
   - Use "AI Group Bookmarks" for automatic organization
   - Or double-click bookmarks to manually assign to folders
   - Create new folders as needed

4. **Export organized bookmarks:**
   - Click "Export HTML"
   - Save the organized bookmark file
   - Import the file into your browser

## 📖 Detailed Workflow

### Step 1: Export from Browser
Export your current bookmarks:
- **Chrome**: Settings → Bookmarks → Bookmark manager → Organize → Export bookmarks
- **Firefox**: Bookmarks → Show All Bookmarks → Import and Backup → Export Bookmarks to HTML
- **Safari**: File → Export Bookmarks
- **Edge**: Settings → Favorites → More options → Export favorites

### Step 2: Import & Organize
1. Open Bookmark Organizer
2. Click "Import Bookmarks" and select your HTML file
3. Review imported bookmarks
4. Create or rename folders and double-click a bookmark to move it
5. Use Duplicates to choose how matching URLs are handled
6. The Bookmarks bar remains visible and cannot be renamed or deleted

### Step 3: Export & Import
1. Click "Export HTML" to generate organized bookmark file
2. In your browser, import the organized file
3. Enjoy your clean, categorized bookmarks!

Before export, **Check URLs** follows redirects up to the request library's
configured limit and reports reachable, redirected, invalid, client-error,
server-error, timeout, and network-error results. Only invalid URLs and client
errors are offered for deletion; timeouts and server/network failures are kept
unless you change them manually.

## 🔧 Configuration

### AI Features (Optional)
To use AI-powered bookmark organization:
1. Provide an OpenAI-compatible API key using the `OPENAI_API_KEY`
   environment variable, or click **AI Settings** for session-only
   configuration.
2. Optionally configure:
   - `BOOKMARK_AI_ENDPOINT`
   - `BOOKMARK_AI_MODEL`
   - `BOOKMARK_AI_TIMEOUT`
   - `BOOKMARK_AI_BATCH_SIZE`
   - `BOOKMARK_AI_RETRIES`
3. Click **AI Group**, review the proposed folders, and confirm before
   applying them.
4. **Add Bookmark** also offers an optional AI folder suggestion. If AI is
   unavailable, the bookmark can still be assigned manually.

API keys are kept only in process memory or read from the environment. They
are not written to bookmark exports, JSON backups, logs, or repository files.
AI requests run in the background; the Bookmarks bar is excluded from
classification.

### Folder Organization
The app organizes bookmarks into logical folders such as:
- Programming & Development
- Research & Academia  
- Documentation & Tools
- Social & Communities
- Learning & Education
- Work & Business
- And more based on content analysis

## 📁 File Structure

```
bookmark-app/
├── bookmark_app.py              # Main application
├── requirements.txt             # Python dependencies
├── short_bookmarks.html         # Sample bookmark file
├── test_*.py                    # Offline unit and GUI smoke tests
└── README.md                    # This file
```

## 🧪 Testing

Run the complete test suite:
```bash
py -m unittest discover -v
```

This test demonstrates:
- ✅ HTML bookmark parsing (105 bookmarks processed)
- ✅ Smart categorization into 6 folders
- ✅ Browser-compatible HTML export
- ✅ Preservation of the "Bookmarks bar" folder and its hierarchy
- ✅ File validation and verification

## 🌟 Key Benefits

### For Individual Users
- **Clean Organization**: Transform messy bookmark collections into organized folders
- **Dead Link Removal**: Automatically detect and remove broken bookmarks  
- **Cross-Browser**: Move bookmarks between different browsers easily
- **Backup & Restore**: JSON format for bookmark backup and sharing

### For Power Users
- **AI Integration**: Leverage GPT models for intelligent categorization
- **Batch Processing**: Handle thousands of bookmarks efficiently
- **Custom Organization**: Create personalized folder structures
- **Automation**: Set up automated bookmark organization workflows

## 🔒 Privacy & Security

- **Local Processing**: All bookmark data stays on your computer
- **Optional AI**: AI features require API key but can be disabled
- **No Data Collection**: Application doesn't collect or transmit personal data
- **Open Source**: Full source code available for review

## 📊 Performance

- **Fast Import**: Processes 100+ bookmarks in seconds
- **Efficient Export**: Generates browser-ready HTML files
- **Memory Optimized**: Handles large bookmark collections
- **Cross-Platform**: Works on Windows, macOS, and Linux

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Add tests for new functionality
4. Submit a pull request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For issues, questions, or feature requests:
1. Check the test files for usage examples
2. Review the TRANSFORMATION_SUMMARY.md for technical details
3. Run the test suite to verify functionality

---

**Made with ❤️ for organized browsing!** 🌐📚
