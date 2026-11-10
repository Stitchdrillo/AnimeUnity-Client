# AnimeUnity Client

A Python app for downloading and watching anime from AnimeUnity.

## Highlights

- **Tabulated View:** Clean, easy navigation between library, download manager, settings, and console.
- **Metadata Management:** Convenient downloading and updating of covers and metadata.
- **Concurrent Downloads:** Multi-threaded downloads with tracking, queue handling, and support for full-season or range downloads.
- **Customizable Storage:** Configurable video download locations with automated folder structures.
- **Quality of Life:** Built-in player controls and smooth storage management settings.

## External Requirements

- A computer with a working internet connection
- [Python 3](https://www.python.org/downloads/) installed

## Setup

Clone the repository in the desired folder. (Note that git creates a subfolder for the repo)
``` bash
git clone https://github.com/Stitchdrillo/AnimeUnity-Client.git
```
Go into the project folder.
``` bash
cd AnimeUnity-Client
```
Install the required packages.
``` bash
pip install -r requirements.txt
```

## Usage

If `.pyw` files are correctly associated with `pythonw.exe` on your system, you can run the project by double-clicking `main.pyw`.

If you prefer a visible shell, you can launch it via shell or use a `.py` extension. *(Note: Standard output is redirected to the console tab inside the application).*

On first startup, files like `library.db`, `config.json`, and an `assets/` folder will automatically be created in the project root.

### First use (Initial Setup)

The app opens on the library tab, the first time this will be empty.

Open the **Settings** tab. Set your video download folder, choose concurrent download limit (recommended: $\le 4$ to avoid server blocks), set the download spinbox (1 MB standard) and set the domain url.
Check if this url still works and if necessary change the TLD. *(Note: If downloads ever stop working check again)*
Hit **Save Settings**.

Back to the **Library** tab, click **"Sync from XML"** in the top right.
> *Note: Because this populates your local database with all available series, the first sync takes roughly 1–2 hours. Future syncs will only fetch updates and take significantly less time.*
You can monitor syncing progress in real time on the left of the button.

### Normal use

- **Library:** Use the fast search bar (exact substring) or filter by currently downloaded episodes. Double-click any anime cover to open its details page.
- **Details & Downloads:** View metadata, related seasons/movies, and manage episode downloads. You can download single episodes, full series, or custom ranges. Check progress in the **Downloads** tab.
- **Deletion:** You can delete individual episodes or wipe all downloads for a series via the "Delete All" button (this leaves the parent filesystem folder intact).

### The Player

Powered by the PyQt6 multimedia module right inside the app. 
Click the top-left button anytime to return to the details page.

**Hotkeys:**
- `Spacebar`: Pause / Resume
- `Left Arrow`: Jump back 10 seconds
- `Right Arrow`: Jump forward 10 seconds
- `F` (or double-click): Toggle fullscreen
- `Esc`: Exit fullscreen
*(Tip: Click once directly on the video canvas if hotkeys don't register immediately).*

## Contributing

Contributions are welcome! Feel free to open issues or submit pull requests following standard GitHub workflows.

## License

Distributed under the **GPLv3** License. See `LICENSE` for more information.
