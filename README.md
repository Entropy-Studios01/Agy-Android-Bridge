# AGY Remote — PC Antigravity Sessions Tracker & Mobile Bridge

Track, inspect, and access **all Antigravity (`agy`) sessions across your Windows PC** from your phone (Android or iOS) anywhere.

---

## 🌟 Key Features

1. **PC-Wide Session Tracker**:
   - Automatically discovers every active and historical `agy` session across all projects on your PC by reading the local Antigravity database (`conversation_summaries.db`) and live presence locks.
   - Shows live status: **`● RUNNING`** (active execution) vs **`○ IDLE`**, step counts, workspace directories, and timestamps.
   - Real-time search and filter by project name, session title, or status.

2. **Mobile Activity & Transcript Inspector**:
   - View recent user prompts, agent summaries, and tool execution logs directly on your phone without opening terminal windows.

3. **One-Tap Session Resume**:
   - Tap **"⚡ Resume / Attach"** on any session to spawn an interactive ConPTY terminal tab running `agy -r <conversation_id>` inside that exact project workspace.

4. **Mobile-First Interactive Terminal**:
   - Full [xterm.js](https://github.com/xtermjs/xterm.js) terminal with 200 KB scrollback buffer.
   - Touch quick keys: `Ctrl+C`, `Enter ↵`, `y ↵`, `Esc`, `Tab`, `↑`, `↓`, `agy`, `Clear`.
   - Dedicated prompt composer bar compatible with mobile virtual keyboards (swipe typing & voice input).
   - Multi-tab session switching and font size controls (`A-` / `A+`).

5. **Installable PWA**:
   - Save to your home screen for full-screen native mobile app feel with permanent token login.

---

## 🚀 Quick Start (Windows PC)

1. Double-click **`start_agy_remote.bat`** (or run `.venv\Scripts\python.exe server.py`).
2. The terminal displays:
   - **Local Wi-Fi URL** (e.g. `http://11.0.0.7:8765/?token=YOUR_TOKEN`)
   - **Tailscale URL** (if Tailscale is installed on your PC)
   - An **ASCII QR Code** for instant camera scanning.
3. Open the link on your phone (scan the QR code or paste the URL in Brave/Chrome/Safari).

---

## 📱 Accessing From Your Phone

### Option 1: Local Wi-Fi (Same Network)
- Connect your phone to the same Wi-Fi network as your PC.
- Scan the printed QR code with your phone camera or visit `http://<your-pc-ip>:8765/?token=...`.

### Option 2: Tailscale (Recommended — Access Anywhere over 4G/5G)
1. Install [Tailscale on Windows](https://tailscale.com/docs/install/windows) and sign in.
2. Install [Tailscale on your Phone](https://tailscale.com/download) and sign in with the same account.
3. Restart `start_agy_remote.bat` — it automatically detects your private `100.x.y.z` Tailscale IP and generates a permanent, secure QR code.

### Option 3: Cloudflare Quick Tunnel (Zero-Config Public HTTPS)
1. Install `cloudflared`: `winget install Cloudflare.cloudflared`
2. Run: `start_agy_remote.bat --tunnel`
3. Open the generated `https://....trycloudflare.com/?token=...` URL on your phone.

---

## 📲 Install as an App (PWA)

1. Open the URL in your phone's browser.
2. Tap the browser menu (`⋮` or Share icon) -> **Add to Home screen** / **Install app**.
3. It opens full-screen like a native app and remembers your authentication token automatically.
