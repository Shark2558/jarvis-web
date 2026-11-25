---
chapter: story_setup
written_by: Workshop · Mark XXIV
written_on: 2026-11-25
pages:
  "pg_chapter_setup": "e768b0b16ec2fd7f"
---
- [show:title] This chapter is about running JARVIS on a computer of your own.
- [show:plain] You might do it to try something out, or an engineer might do it to work on JARVIS, without ever touching the live one.
- You install it from the project folder, give it its settings in a small file, and start it.
- The same console then opens in a browser on that machine.
- Set the brain to the built-in test brain, and it answers without any AI key, so you see every screen without spending a rupee.
- With a Claude key, it thinks just as the live JARVIS does.
- [show:how] Here is how a local JARVIS comes to life.
- [show:overview] This is JARVIS on your own computer, from installing it to talking with it.
- [node:install] It starts with you, installing JARVIS from the project, together with the libraries it needs and the development tools.
- [edge:install>settings] Once installed, it needs its settings.
- [node:settings] Every setting is read from the environment, or from a small settings file beside the project.
- Unless you say otherwise, JARVIS runs in {{fact:settings.env}} mode, which relaxes rules meant for production.
- That development mode refuses to start on Cloud Run, where the live JARVIS runs.
- One setting picks the brain: the Claude brain needs its key, while the mock brain gives fixed answers and needs none.
- Another decides how you sign in: token mode accepts only your bearer token, and Google mode needs the Google sign-in settings.
- [edge:settings>check] With the settings read, start-up checks them.
- [node:check] Start-up checks the settings JARVIS can't run without, such as the chosen brain's key.
- [edge:check>stop] If a key is missing, the path turns aside.
- [node:stop] JARVIS stops, with one line naming the missing setting, so you know exactly what to add.
- [edge:check>server] When the checks pass, the server starts.
- [node:server] It is the very same server as the cloud one, and any feature whose settings or keys are missing simply stays off.
- It writes one short line saying that JARVIS is up and which parts started, never a key or an address.
- [edge:server>brain] The server talks to the brain you chose.
- [node:brain] That is either the mock brain, with its fixed answers, or the Claude brain, thinking for real.
- [edge:server>store] It also keeps your conversations somewhere.
- [node:store] By default they live in memory; under Docker, in a Redis database that keeps them across restarts; on Cloud Run, in Firestore.
- [edge:server>console] Then the console opens.
- [node:console] It is the same console page, now served from your own machine, in your browser.
- [edge:settings>cli] There is a second way in, with no server at all.
- [node:cli] You can chat with the brain straight from a terminal, in the same process.
- [show:example] In the made-up example, Kabir, an engineer friend helping with JARVIS, copies the project to his laptop on a Saturday.
- He installs it, writes a settings file that picks the mock brain and a bearer token, and starts the server.
- The console opens in his browser and asks for the token, and the test brain answers each message with a fixed reply.
- He runs the tests, and a few minutes later every one of them has passed.
- Nothing he did reached the live JARVIS or its data.
- [show:costs] With the mock brain it costs nothing: it runs on your own computer, and calls no outside service.
- With a Claude key, each reply costs the same tokens as on the live JARVIS, counted against the monthly limit.
- The terminal chat prints each reply's cost under it, or price unknown for a model JARVIS has no price for.
- [show:fails] With the Claude brain chosen and no key, start-up stops, with a line naming the missing setting.
- Outside development mode, a missing bearer token stops it too.
- An unknown brain asked for in the terminal chat stops with the list of brains you have set up.
- And a custom AI address must use an encrypted link unless it is on this machine or your home network, and a Tailscale name always needs one.
- That is a local JARVIS: the same server, the same console, and nothing at stake.
