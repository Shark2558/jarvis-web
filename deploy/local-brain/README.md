# Offline mode: your laptop as JARVIS's backup brain

When Claude can't be reached (no internet at the cloud end, a timeout, a provider outage), JARVIS can
ask a small model running on your own laptop instead. It is **off until you set it up**, costs
nothing, and your words only go to your own machine.

Offline mode is a one-time job on your laptop. It is not required for anything else, and JARVIS
works exactly as before without it.

## What you get, and what you don't

- Replies say "Offline mode - answered by your laptop (model)".
- Only 12 simple tools: calendar look-ups, reminders, to-dos, groceries, unread-mail digest, parcel
  status. No sending, no deleting, nothing you can't take back.
- **Every change asks first** (a one-tap card), because a small model is easier to fool.
- Slower and less clever than Claude. Answers are kept short.
- The laptop must be **awake**, with Ollama and the gate running. If it isn't, JARVIS says "Claude
  can't be reached and your laptop didn't answer."
- Nothing is sent to the laptop while Claude works: it is only used when Claude can't be reached.
  (After a miss, the next 2 minutes go straight to the laptop, then JARVIS tries Claude again.)

## One-time setup (about 20 minutes)

1. **Ollama.** Install it from ollama.com, open it, then pull a model:
   `ollama pull qwen2.5:7b` (laptop with 16 GB memory) or `ollama pull qwen2.5:3b` (8 GB).
2. **Caddy** (the little gate that checks the key). macOS: `brew install caddy`. Windows:
   `winget install CaddyServer.Caddy`. Linux: see caddyserver.com/docs/install.
3. **Tailscale** (free Personal plan): install it from tailscale.com/download and sign in. In the
   Tailscale admin console, turn on **HTTPS certificates** (DNS page) and allow **Funnel** when it
   asks. The first address can take up to 10 minutes to start working.
4. **Start the gate.**
   - macOS / Linux: `bash deploy/local-brain/start-unix.sh`
   - Windows: `powershell -ExecutionPolicy Bypass -File deploy\local-brain\start-windows.ps1`

   It makes your key the first time (kept in a file only you can read), starts the gate, opens
   Funnel and prints:

   ```
   Address: https://my-laptop.tail1234.ts.net
   Key: <43 characters>
   ```
5. **Tell JARVIS.** Integrations -> Offline mode: paste the address, the key and the model name
   (the one you pulled), press **Save**, then **Test**. It should say "Your laptop answered (model
   ...)". Then switch it **On**.
6. **Try it.** The Test button is the check you can run any time. A real fallback only happens when
   Claude can't be reached; that reply then carries the offline marker, writes show a card, and (if
   Telegram is set up) you get an alert.
7. Check tool calling with your model: ask "what's on today?" in offline mode. Small models
   sometimes call tools badly; if so, try a bigger one (`qwen2.5:7b`) and change the model name in
   Integrations.

Keep the script window open. Ctrl+C stops the gate and closes Funnel. You can run it at login if you
like.

## Why it is safe

- The address is a **Tailscale Funnel** name (`<machine>.<tailnet>.ts.net`): the encrypted connection
  ends on **your laptop**, not at Tailscale. JARVIS only accepts that kind of address, over https,
  and refuses anything that points at a private network.
- Anyone on the internet can *find* the address, so the gate (Caddy) answers only two requests
  (`POST /v1/chat/completions`, `GET /v1/models`) and only with your key. Everything else is 401 or 404.
  Ollama itself is never published.
- The key is 256 random bits, stored encrypted in JARVIS and only in a private file on your laptop.
  JARVIS never shows it back.
- A new address needs the key pasted again. To change the key: delete the key file
  (`~/.jarvis-local-brain/key`, or `%LOCALAPPDATA%\JarvisLocalBrain\key` on Windows), run the script
  again, and paste the new key.

## Problems

| Test says | What to do |
|---|---|
| "Your laptop didn't answer. Is it awake, with Tailscale Funnel on?" | Wake the laptop, check the script window is open, run `tailscale funnel status`. |
| "The laptop refused the key." | Copy the key printed by the script again (no spaces). |
| "Something answered, but it isn't the JARVIS gate." | Run the start script; check the address is the one it printed. |
| "The tunnel is up but Ollama isn't answering." | Open the Ollama app. |
| "...the model ... isn't installed there." | Run the `ollama pull ...` line it shows. |
| Funnel won't start | Tailscale admin console -> allow Funnel for this device; try again in 10 minutes. |

Funnel is still marked beta by Tailscale. If it ever stops working, Offline mode simply stays
"Laptop not answering" and JARVIS carries on with Claude only.
