# AUTO-REACT-SHORTS-YT 🎬⚡

Automated YouTube Reaction Shorts stacker and video assembler. Paste any YouTube Shorts link, automatically detect video layout and blur-bars, stack your reaction clip on top, synchronize audio/durations, and render an upload-ready **1080×1920** vertical video.

Powered by **Python**, **FFmpeg**, **FFprobe**, and **yt-dlp** — 100% local, fast, and deterministic without external AI API dependencies.

---

## ✨ Features

- **🧠 Intelligent Split Detection**:
  - **Native 9:16 Vertical Shorts**: Stacks reaction clip on top 1/3 (640px) and source Short on bottom 2/3 (1280px).
  - **16:9 Shorts / Letterboxed Shorts with Blur Bars**: Automatically detects top/bottom blur bars using edge frequency analysis, crops them out, and performs an equal 50/50 split (960px / 960px).
- **⏱️ Auto Duration Matching & Looping**:
  - Loops short reaction takes seamlessly to match source video length.
  - Trims reaction takes if longer than the source.
- **🔊 Stereo Audio Mixing**:
  - Blends reaction audio with source audio using FFmpeg's `amix` filter.
- **💻 Dual Interface**:
  - **Modern Web Dashboard**: Real-time server-sent events (SSE) log terminal, video preview, history, and single-click download.
  - **Command-Line Interface (CLI)**: Automate batches or run single commands directly in terminal.

---

## 📁 Repository Structure

```
AUTO-REACT-SHORTS-YT/
├── storage/            # Place your reaction clip here (storage/react.mp4)
├── out/                # Rendered 1080x1920 output videos
├── tmp/                # Temporary frame and download cache
├── ui/                 # Web interface assets (HTML, CSS, JS)
│   ├── index.html
│   ├── style.css
│   └── app.js
├── main.py             # FastAPI backend with SSE streaming
├── pipeline.py         # Core detection, layout, and FFmpeg encoding engine
├── react_stack.py      # Standalone CLI entrypoint
├── requirements.txt    # Python package dependencies
├── run.bat             # Windows one-click launcher
└── README.md
```

---

## 🛠️ Requirements & Setup

### 1. Prerequisites

1. **Python 3.10+**
2. **FFmpeg & FFprobe**: Ensure `ffmpeg` and `ffprobe` are installed and available on your system `PATH`.
   - *Windows (via winget)*: `winget install Gyan.FFmpeg`
   - *Mac (via Homebrew)*: `brew install ffmpeg`
   - *Linux (Ubuntu/Debian)*: `sudo apt install ffmpeg`

### 2. Installation

Clone this repository and install Python dependencies:

```bash
git clone https://github.com/Etzkennyboi/AUTO-REACT-SHORTS-YT.git
cd AUTO-REACT-SHORTS-YT
pip install -r requirements.txt
```

### 3. Add Your Reaction Clip

Copy your reaction video into the `storage/` directory and name it `react.mp4`:

```bash
# Example
copy "path\to\your_reaction.mp4" "storage\react.mp4"
```

---

## 🚀 How to Use

### Method 1: Web Interface (Recommended)

On **Windows**, simply double-click:
```cmd
run.bat
```

Or start the server via command line:
```bash
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

Open **[http://localhost:8000](http://localhost:8000)** in your browser:
1. Paste any YouTube Shorts URL (e.g. `https://youtube.com/shorts/...`).
2. Select split mode (`Auto-detect`, `1/3 Top (Native 9:16)`, or `1/2 Top (16:9)`).
3. Click **Stack Reaction** and watch the real-time processing terminal.
4. Preview or download the finished 1080×1920 MP4 directly.

---

### Method 2: Command-Line Interface (CLI)

Use `react_stack.py` for one-command terminal generation:

```bash
# Basic usage
python react_stack.py "https://youtube.com/shorts/VIDEO_ID"

# Specify custom reaction clip and output path
python react_stack.py "https://youtube.com/shorts/VIDEO_ID" --react storage/my_take.mp4 --out out/final.mp4

# Force split mode (auto, third, half)
python react_stack.py "https://youtube.com/shorts/VIDEO_ID" --force half
```

#### CLI Options:
| Flag | Description | Default |
|---|---|---|
| `url` | YouTube Shorts URL or local file path | *Required* |
| `--react` | Path to reaction video | `storage/react.mp4` |
| `--out` | Output folder or output `.mp4` path | `out/` |
| `--force` | Force layout split (`auto`, `third`, `half`) | `auto` |
| `--tmp` | Temporary directory for caching | `tmp/` |

---

## ⚙️ Layout Detection Logic

| Source Video Type | Layout Split | Reaction Height | Short Height | Notes |
|---|---|---|---|---|
| **True 9:16 Vertical** | 1/3 Top, 2/3 Bottom | 640 px | 1280 px | Preserves full vertical content without cropping. |
| **16:9 Landscape** | 1/2 Top, 1/2 Bottom | 960 px | 960 px | Scales 16:9 comfortably into lower half. |
| **16:9 with Blur Bars** | 1/2 Top, 1/2 Bottom | 960 px | 960 px | Blur bars automatically detected & cropped. |

---

## 📄 License

MIT License. Feel free to use, modify, and distribute.
