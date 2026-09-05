# VoxRelay

A local, push-to-talk voice dictation and voice-command tool for Linux.
Hold a key, speak, release it, and it types out what you said using
[faster-whisper](https://github.com/SYSTRAN/faster-whisper) running
entirely on your machine (no audio ever leaves it). A second key can
run pre-approved shell commands by voice, with a confirmation dialog
before anything executes.

## Features

- Push-to-talk dictation, typed directly into the focused window
- A separate voice-command button: say a phrase, get a confirmation
  dialog showing the exact shell command, approve or cancel
- Unknown phrases can be taught a new command on the spot
- Approved commands run in a single, reusable terminal window with
  live output and a log file
- A custom dictionary to bias transcription toward names, project
  words or jargon it would otherwise mishear
- A blocklist to drop hallucinated sentences, and a profanity filter
  that censors individual words instead of dropping the whole sentence
- Runs fully offline once the model is downloaded

## Requirements

- Linux with X11 (uses `xdotool`/`xclip`, which don't work on Wayland)
- Python 3.11+
- System packages: `xdotool`, `xclip`, `pulseaudio-utils` (for
  `paplay`), `fontconfig`, `python3-gi` + `gir1.2-gtk-3.0` (for the
  confirmation dialog), and a terminal emulator (`gnome-terminal`,
  `alacritty`, or anything providing `x-terminal-emulator`)
- Your user needs to be in the `input` group to read the keyboard
- An Nvidia GPU is optional; without one, transcription runs on CPU
  (slower, but works)

## Setup

```bash
git clone <this repo>
cd voxrelay
./setup.sh                        # copies config files, checks dependencies
pip install -r requirements.txt
python3 voxrelay.py
```

`setup.sh` copies the `.example` config files into place (they're
gitignored so your personal edits never get committed) and reports
any missing system tool. It does not install system packages for you,
follow the hints it prints (usually `sudo apt install ...`).

After that, open `config/config.toml` and set at least:

- `keyboard_name` and `key`: run the command printed inside the file's
  comments to find your keyboard's exact evdev name, and pick which
  key triggers dictation
- `device` / `compute_type`: `"cuda"` / `"float16"` if you have a
  working Nvidia GPU setup, otherwise leave the defaults (`"cpu"` /
  `"int8"`)

## Voice commands

Edit `config/commands.toml` to map spoken phrases to shell commands,
or just say a phrase that isn't in there yet, the dialog will ask you
what it should run and save it for next time. Matching ignores case,
accents, punctuation and spacing, so "Docker list." and "docker list"
are the same phrase.

## Project layout

- `voxrelay.py`: the daemon (dictation + voice commands)
- `dialog.py`: the confirmation/entry popup for voice commands
- `runner.sh`: runs approved commands inside the persistent terminal
- `config/`: your personal settings and word lists (gitignored) plus
  `.example` templates (committed)
- `old/`: earlier reference version, not used by the current code

## Known limitations

- X11 only, no Wayland support
- The profanity filter only matches single words, not multi-word
  phrases
- No automated way yet to discover `keyboard_name`/`key` beyond the
  manual evdev snippet in `config.toml.example`

## License

MIT, see [LICENSE](LICENSE).
