# Reddit Video Maker Bot 🎥

All done WITHOUT video editing or asset compiling. Just pure ✨programming magic✨.

Created by Lewis Menelaws & [TMRRW](https://tmrrwinc.ca)

<a target="_blank" href="https://tmrrwinc.ca">
<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://user-images.githubusercontent.com/6053155/170528535-e274dc0b-7972-4b27-af22-637f8c370133.png">
  <source media="(prefers-color-scheme: light)" srcset="https://user-images.githubusercontent.com/6053155/170528582-cb6671e7-5a2f-4bd4-a048-0e6cfa54f0f7.png">
  <img src="https://user-images.githubusercontent.com/6053155/170528582-cb6671e7-5a2f-4bd4-a048-0e6cfa54f0f7.png" width="350">
</picture>

</a>

## Video Explainer

[![lewisthumbnail](https://user-images.githubusercontent.com/6053155/173631669-1d1b14ad-c478-4010-b57d-d79592a789f2.png)
](https://www.youtube.com/watch?v=3gjcY_00U1w)

## Motivation 🤔

These videos on TikTok, YouTube and Instagram get MILLIONS of views across all platforms and require very little effort.
The only original thing being done is the editing and gathering of all materials...

... but what if we can automate that process? 🤔

## Disclaimers 🚨

- **At the moment**, this repository won't attempt to upload this content through this bot. It will give you a file that
  you will then have to upload manually. This is for the sake of avoiding any sort of community guideline issues.

## Requirements

- Python 3.10
- Playwright (this should install automatically in installation)

## Installation 👩‍💻

1. Clone this repository:
    ```sh
    git clone https://github.com/elebumm/RedditVideoMakerBot.git
    cd RedditVideoMakerBot
    ```

2. Create and activate a virtual environment:
    - On **Windows**:
        ```sh
        python -m venv ./venv
        .\venv\Scripts\activate
        ```
    - On **macOS and Linux**:
        ```sh
        python3 -m venv ./venv
        source ./venv/bin/activate
        ```

3. Install the required dependencies:
    ```sh
    pip install -r requirements.txt
    ```

4. Install Playwright and its dependencies:
    ```sh
    python -m playwright install
    python -m playwright install-deps
    ```

---

**EXPERIMENTAL!!!!**

   - On macOS and Linux (Debian, Arch, Fedora, CentOS, and based on those), you can run an installation script that will automatically install steps 1 to 3. (requires bash)
   - `bash <(curl -sL https://raw.githubusercontent.com/elebumm/RedditVideoMakerBot/master/install.sh)`
   - This can also be used to update the installation

---

5. Run the bot:
    ```sh
    python main.py
    ```

6. Visit [the Reddit Apps page](https://www.reddit.com/prefs/apps), and set up an app that is a "script". Paste any URL in the redirect URL field, for example: `https://jasoncameron.dev`.

7. The bot will prompt you to fill in your details to connect to the Reddit API and configure the bot to your liking.

8. Enjoy 😎

9. If you need to reconfigure the bot, simply open the `config.toml` file and delete the lines that need to be changed. On the next run of the bot, it will help you reconfigure those options.

(Note: If you encounter any errors installing or running the bot, try using `python3` or `pip3` instead of `python` or `pip`.)

For a more detailed guide about the bot, please refer to the [documentation](https://reddit-video-maker-bot.netlify.app/).

## Video

https://user-images.githubusercontent.com/66544866/173453972-6526e4e6-c6ef-41c5-ab40-5d275e724e7c.mp4

## Contributing & Ways to improve 📈

In its current state, this bot does exactly what it needs to do. However, improvements can always be made!

I have tried to simplify the code so anyone can read it and start contributing at any skill level. Don't be shy :) contribute!

- [ ] Creating better documentation and adding a command line interface.
- [x] Allowing the user to choose background music for their videos.
- [x] Allowing users to choose a reddit thread instead of being randomized.
- [x] Allowing users to choose a background that is picked instead of the Minecraft one.
- [x] Allowing users to choose between any subreddit.
- [x] Allowing users to change voice.
- [x] Checks if a video has already been created
- [x] Light and Dark modes
- [x] NSFW post filter

Please read our [contributing guidelines](CONTRIBUTING.md) for more detailed information.

### For any questions or support join the [Discord](https://discord.gg/qfQSx45xCV) server

## Developers and maintainers.

Elebumm (Lewis#6305) - https://github.com/elebumm (Founder)

Jason Cameron - https://github.com/JasonLovesDoggo (Maintainer)

Simon (OpenSourceSimon) - https://github.com/OpenSourceSimon

CallumIO (c.#6837) - https://github.com/CallumIO

Verq (Verq#2338) - https://github.com/CordlessCoder

LukaHietala (Pix.#0001) - https://github.com/LukaHietala

Freebiell (Freebie#3263) - https://github.com/FreebieII

Aman Raza (electro199#8130) - https://github.com/electro199

Cyteon (cyteon) - https://github.com/cyteon


## LICENSE
[Roboto Fonts](https://fonts.google.com/specimen/Roboto/about) are licensed under [Apache License V2](https://www.apache.org/licenses/LICENSE-2.0)

## Translation

The bot can translate post titles, body text, and comments into a target language using the Anthropic Claude API. Translation is configured via the `[translation]` and `[translation.anthropic]` sections in `config.toml`.

### `[translation]`

| Key | Default | Options | Description |
|-----|---------|---------|-------------|
| `provider` | `"none"` | `"none"`, `"anthropic"` | Translation backend. `"none"` disables translation entirely. Any unrecognized value is treated as `"none"` with a warning logged. |
| `target_lang` | `""` | Any ISO 639-1 / BCP-47 code | Target language code (e.g. `"es"`, `"pt-BR"`, `"ja"`). An empty string disables translation. |
| `failure_policy` | `"skip"` | `"skip"`, `"fail"` | What to do when Anthropic returns an error. `"skip"` uses the original text and logs a warning; `"fail"` re-raises and aborts the run. |
| `cache_enabled` | `true` | `true`, `false` | Cache translations to disk so repeated runs on the same post don't re-call Anthropic. |
| `force_translate` | `false` | `true`, `false` | Skip source-language detection and translate every field unconditionally. |

### `[translation.anthropic]`

| Key | Default | Description |
|-----|---------|-------------|
| `model` | `"claude-3-5-sonnet-latest"` | Claude model identifier passed with each request. |
| `max_output_tokens` | `4096` | Maximum output tokens per Anthropic request. |
| `api_key` | `""` | Anthropic API key. The `ANTHROPIC_API_KEY` environment variable takes precedence over this value when both are set. |

### Notes

- **API key precedence**: `ANTHROPIC_API_KEY` environment variable overrides `[translation.anthropic].api_key`. If neither is set and `provider = "anthropic"`, the error is deferred until the first translation attempt and the configured `failure_policy` is applied.
- **Disabling translation**: Set `provider = "none"` to skip translation entirely. Setting `provider` to an unknown value also disables translation but logs a warning naming the offending value.
- **Translation cache**: When `cache_enabled = true`, translations are stored under `assets/temp/{thread_id}/translation_cache.json` and are cleaned up alongside other per-thread artifacts when the thread's temp directory is removed.

### Example configuration

```toml
[translation]
provider = "anthropic"
target_lang = "es"
failure_policy = "skip"
cache_enabled = true

[translation.anthropic]
model = "claude-3-5-sonnet-latest"
max_output_tokens = 4096
api_key = ""  # or set ANTHROPIC_API_KEY in your environment
```
