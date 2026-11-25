# Changelog

## 0.3.11 (2026-11-25)

- One bar at the top instead of two: the Windows title bar is gone, and minute's own bar now moves the window and holds minimize, maximize and close. Drag it to move, double-click it to maximize, and resize from any edge as before
- Known limit: hovering the maximize button no longer shows the Windows 11 snap layouts; Win+Z and dragging to the screen edges still snap

## 0.3.10 (2026-11-25)

- New note shows only on the home page, so a call and Settings have a cleaner top bar
- Switches in Settings are black and white instead of green, in line with the rest of minute
- Settings descriptions are one short line each, and What's new folds into a single row you can open
- A call shows how long it lasted and the app it was on (Telegram, Zoom, Meet…) next to its date

## 0.3.9 (2026-11-25)

- The home list shows all your calls at once: no more days to open one by one. Calls are grouped into Today, Yesterday, This week and then by month, and about six times as many fit on screen
- Each call shows the first line of its notes under the title, and its date and length on the right
- Press / anywhere outside a text field to jump to the search bar
- New note, Calls and the top bar icons are smaller and lighter, so the buttons no longer outweigh your calls

## 0.3.8 (2026-11-24)

- minute opens faster: the window is on screen in under half a second instead of about two, and your calls show up in about 1.3 seconds instead of 2.2 (median of 20 launches each). The window now talks to the browser engine directly instead of through .NET, and the recorder, the pill and the tray load while your calls are already showing
- Opening minute from the Start menu while it sits in the tray brings it up in about half a second instead of 1.1 to 1.4 seconds
- In dark mode the window no longer flashes white while it opens

## 0.3.7 (2026-11-16)

- The recording pill is now horizontal and floats at the top centre of the screen. Hover it to see the stop button: only the red button stops, a click anywhere else opens minute, and you can drag it where you like, it remembers the spot
- The stop button sits at the right end of the bottom bar, away from Transcript, so a click aimed at the transcript can't end the recording
- Ask answers take about a third of the window and scroll inside, so your notes stay readable above them
- While the AI names a call, the temporary title is readable instead of almost invisible
- The scrollbar shows only when you hover, and the list fades out under the search bar instead of hiding the last call behind it
- When the enhanced notes fail, the call says "Notes failed" in the list and the note says what went wrong in one sentence, with "Open Settings" when the API key or the AI settings are the problem
- Fixed: a few misheard words on a near-silent call could give the call a title in the wrong language. A very short transcript no longer decides the title, your notes do
- Fixed: on a scaled display (125%, 150%) the pill could sit off centre
- Known issue: on recent Windows 11 builds minute may not start recording on its own when a call begins. Start it with New note until it's fixed

## 0.3.6 (2026-11-15)

- Every decision and next step in the enhanced notes ends with the time it was said, like [12:34]: click it and the transcript opens at that line, highlighted for a moment, so you can check who agreed to what
- Times in Ask answers are links too, and "Back to answer" brings you back from the transcript
- In the files a time stays plain [12:34] text, readable in Obsidian or any editor
- Fixed: on a long call the enhanced notes could fail with "the model ran out of tokens before answering" and never arrive. The model now has more room to think, and when it still runs out it is asked again with less thinking. Same for Ask

## 0.3.5 (2026-10-22)

- Search your calls from the Ask bar: on the home page the list narrows as you type to the calls with every word you typed in their title, your notes, the enhanced notes or the transcript. Case and accents don't matter, and each result shows the words in context, in bold
- Click a result and the call opens where the words are, highlighted: in your notes, the enhanced notes or the transcript
- Enter still asks about your calls. Esc or an empty bar brings the whole list back, and Back from a call returns to your search

## 0.3.4 (2026-10-11)

- Pick your microphone in Settings > Recordings: Windows default (as before) or a specific mic, used whenever it's connected; if it isn't, minute falls back to the Windows default

## 0.3.3 (2026-10-11)

- Your name in Settings: Ask now knows that you are the one people call by that name, so "what do I have to do?" finds the tasks given to you by name
- Next steps no longer make up an owner: a task with no named owner is listed without one, never given to "them" or to whoever spoke
- Short calls get a few lines instead of sections, and notes never say what wasn't decided or discussed
- Ideas and proposals stay ideas: only what the call actually settled is written as a decision
- Dates like "tomorrow" or "next Wednesday" are read from the day of the call, also when notes are regenerated later
- With a model on your PC, long transcripts are cut in the middle: Ask now says when an answer may be in the part left out instead of saying it wasn't discussed

## 0.3.2 (2026-10-10)

- Delete a call right from the list: hover it and use the ... button
- Deleting no longer asks for confirmation and is never final: the call goes to the Windows Recycle Bin, and Undo brings it back for a few seconds
- Cleaner list: no file icon next to each call
- Days fold: Today and Yesterday (or the latest day) are open, older days are closed with their number of calls; click a day to open or close it
- Today and Yesterday move on at midnight even if minute stays open, and days from earlier years show the year

## 0.3.1 (2026-10-10)

- Ask about your calls finds the right call across languages and synonyms: when not everything fits, the AI first picks the calls to read in full from their notes, instead of matching words. Ask in English about a call held in Italian, or the other way round
- When no call covers the question, it says so right away
- The AI's choice of calls is checked: only calls that exist are accepted, and a malformed reply is sent back to the model to fix
- Faster choice, better answers: the AI thinks briefly to pick the calls and harder to write the answer

## 0.3.0 (2026-10-10)

- Ask anything: type a question in the bar at the bottom. In a note it answers about that call ("what did we agree on the price?"), on the home page about all your calls, with links to the calls it used. Follow-up questions keep the thread; New chat starts over
- Pick your AI in Settings: DeepSeek (paste a key, or use pi's), Ollama for a free model that runs on your PC with nothing leaving it, or any other OpenAI-compatible API
- Clearer AI errors: missing key, model or endpoint, and Ollama not running
- Notes and answers no longer use em dashes

## 0.2.7 (2026-10-10)

- Fixed: in continuous speech (an interview, a video, someone talking for minutes) the text of the other side only appeared when the call ended, so your replies piled up in one bubble and the transcript came out in the wrong order. Text now appears within about 15 seconds, in the right order
- Fixed: a language tag such as <sl-SI> could show up in the transcript

## 0.2.6 (2026-10-10)

- Language detection is now the default and the recommended setting: it handles any language and calls that switch language, while a wrong fixed language could drop whole sentences
- Better enhanced notes: misheard words are corrected, what you put in bold or as a heading is treated as most important, no generic sections, technical terms kept as they are, and instructions hidden in a transcript are ignored

## 0.2.5 (2026-10-10)

- Much lighter between calls: the speech model is freed after 10 minutes without calls (about 1 GB of RAM) and reloads in a couple of seconds when the next call starts, while its audio is already being recorded
- Default language follows Windows when the speech model supports it, otherwise English
- All 32 languages of the speech model are available in Settings

## 0.2.4 (2026-10-10)

- Less on screen: no call duration, no "Your calls" heading, no timer or Stop in the top bar during a call
- One recording control at the bottom of the note: transcript and stop together
- The speech model status only appears when something is wrong
- Transcript reads like a conversation: them on the left, you on the right, a time marker at most once a minute

## 0.2.3 (2026-10-10)

- The auto-stop is visible: when the call app lets go of the mic the pill turns amber and the note shows "Call ended · stopping in 32s"
- Keep recording: cancels the auto-stop for this call, you stop it yourself
- A notification confirms when a call has ended and its notes are saved
- One "Calls" button to go back, instead of Back and Home doing the same thing

## 0.2.2 (2026-10-10)

- About section in Settings: installed version, creator, website, GitHub repository and this changelog
- Version shown in the tray icon tooltip

## 0.2.1 (2026-10-10)

- Raw files for every call: play their audio or yours, open the raw live text, open the folder (note menu, Transcript panel and error banners)
- raw-transcript.txt: a readable copy of the raw live text

## 0.2.0 (2026-10-10)

- Calls are recorded automatically when a call app turns on the mic, and stop when the call ends
- Nothing is lost when something fails: audio and raw text are saved live, missing transcripts are redone from the audio, failed AI steps are retried
- Calls interrupted by a crash are recovered on the next start
- Speech model loaded at startup, its status always visible on the home bar
- Notes in Markdown: lists that continue on Enter, Tab to nest, headings, bold and italic
- Enhanced notes: your notes completed with the transcript into a summary, topics, decisions and next steps

## 0.1.0 (2026-10-10)

- Live transcription of your mic and of the call audio, on your PC
- Notes page, history of calls, transcript panel, recording pill on the screen edge
- AI titles when a call ends
- Settings: open at login, language, recordings folder, keep audio, AI key and model
- Windows installer
