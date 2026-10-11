# Changelog

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
