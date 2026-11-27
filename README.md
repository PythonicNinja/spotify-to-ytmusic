# spotify-to-ytmusic

Sync Spotify playlists ([Exportify](https://exportify.net) `.csv`) to YouTube Music while preserving `Added At` recency order (under both **Newest first** and **Manual** sort modes).

Run `make help` to see all steps.

## Workflow

1. Install environment:
   ```bash
   make dev_install
   ```
2. Save YouTube Music auth (`browser.json`):
   - Open `https://music.youtube.com` logged in -> DevTools -> Network -> filter `browse` -> right-click a `POST` `browse` request -> Copy -> **Copy as cURL**.
   ```bash
   make step1
   ```
3. Export your Spotify playlists using [Exportify](https://exportify.net) ([source](https://github.com/watsonbox/exportify)) and put each `.csv` into `playlists/<Playlist Name>.csv`, then verify:
   ```bash
   make step2
   ```
4. Preview matches and sync plan (no writes to YouTube Music):
   ```bash
   make step3
   ```
5. Sync to YouTube Music:
   ```bash
   make step4          # incremental sync (adds missing tracks + reorders)
   make step4_rebuild  # clean rebuild (clears old extras/duplicates + writes in exact order)
   ```

Target a single playlist on any step:
```bash
make step4 PLAYLIST="Roadtrip"
```
