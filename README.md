# spotify-to-ytmusic

Sync Spotify playlists (Exportify `.csv`) to YouTube Music while preserving `Added At` recency order.

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
3. Export playlists from `https://exportify.net` and put each `.csv` into `playlists/<Playlist Name>.csv`, then verify:
   ```bash
   make step2
   ```
4. Preview matches and reorder plan (no writes to YouTube Music):
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
make step4 PLAYLIST="Oznaczone gwiazdką"
```
