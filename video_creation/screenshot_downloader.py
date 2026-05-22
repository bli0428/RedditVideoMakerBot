import json
import re
from pathlib import Path
from typing import Final

import translators
from playwright.sync_api import ViewportSize, sync_playwright
from rich.progress import track

from utils import settings
from utils.console import print_step, print_substep
from utils.imagenarator import imagemaker
from utils.videos import save_data

__all__ = ["get_screenshots_of_reddit_posts"]


def get_screenshots_of_reddit_posts(reddit_object: dict, screenshot_num: int):
    """Downloads screenshots of reddit posts as seen on the web.

    For non-storymode: takes a single full-page screenshot of the entire thread
    and records the Y position of each comment. This enables the scroll-reveal
    transition in final_video.py.

    Saves:
      - assets/temp/{id}/png/title.png          — title card screenshot
      - assets/temp/{id}/png/thread.png          — full thread screenshot
      - assets/temp/{id}/png/comment_positions.json — [{y, height}, ...] per comment

    Args:
        reddit_object (dict): Reddit object received from reddit/subreddit.py
        screenshot_num (int): Number of comments to include
    """
    W: Final[int] = int(settings.config["settings"]["resolution_w"])
    H: Final[int] = int(settings.config["settings"]["resolution_h"])
    lang: Final[str] = settings.config["reddit"]["thread"]["post_lang"]
    storymode: Final[bool] = settings.config["settings"]["storymode"]

    print_step("Downloading screenshots of reddit posts...")
    reddit_id = re.sub(r"[^\w\s-]", "", reddit_object["thread_id"])
    Path(f"assets/temp/{reddit_id}/png").mkdir(parents=True, exist_ok=True)

    # Theme colors for story-mode image generation
    if settings.config["settings"]["theme"] == "dark":
        bgcolor = (33, 33, 36, 255)
        txtcolor = (240, 240, 240)
        transparent = False
    elif settings.config["settings"]["theme"] == "transparent":
        if storymode:
            bgcolor = (0, 0, 0, 0)
            txtcolor = (255, 255, 255)
            transparent = True
        else:
            bgcolor = (33, 33, 36, 255)
            txtcolor = (240, 240, 240)
            transparent = False
    else:
        bgcolor = (255, 255, 255, 255)
        txtcolor = (0, 0, 0)
        transparent = False

    if storymode and settings.config["settings"]["storymodemethod"] == 1:
        print_substep("Generating images...")
        return imagemaker(
            theme=bgcolor, reddit_obj=reddit_object, txtclr=txtcolor, transparent=transparent,
        )

    theme = settings.config["settings"]["theme"]
    color_scheme = "dark" if theme in ("dark", "transparent") else "light"

    with sync_playwright() as p:
        print_substep("Launching Headless Browser...")

        browser = p.chromium.launch(headless=True)
        dsf = (W // 600) + 1

        context = browser.new_context(
            locale=lang or "en-CA,en;q=0.9",
            color_scheme=color_scheme,
            viewport=ViewportSize(width=W, height=H),
            device_scale_factor=dsf,
            user_agent=(
                f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{browser.version}.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        # Login only for NSFW posts
        username = settings.config["reddit"]["creds"].get("username", "")
        password = settings.config["reddit"]["creds"].get("password", "")
        needs_login = reddit_object.get("is_nsfw", False) and username and password

        if needs_login:
            print_substep("NSFW post detected — logging in to Reddit...")
            page.goto("https://www.reddit.com/login", timeout=30000)
            page.wait_for_load_state("domcontentloaded")
            page.locator('input[name="username"]').fill(username)
            page.locator('input[name="password"]').fill(password)
            page.get_by_role("button", name="Log In").click()
            page.wait_for_timeout(5000)
        else:
            print_substep("Skipping Reddit login (not required for public posts).")

        # Navigate to the thread
        permalink = reddit_object["thread_url"]
        www_url = re.sub(
            r"https?://(new\.|old\.)?reddit\.com",
            "https://www.reddit.com",
            permalink,
        )
        page.goto(www_url, timeout=30000)
        page.wait_for_load_state("domcontentloaded")
        page.locator("shreddit-post").first.wait_for(state="visible", timeout=15000)
        page.wait_for_timeout(3000)

        # Dismiss popups
        for dismiss_selector in [
            "button:has-text('Accept All')",
            "button:has-text('Accept')",
            "[aria-label='Close']",
        ]:
            dismiss = page.locator(dismiss_selector).first
            if dismiss.is_visible():
                try:
                    dismiss.click(timeout=2000)
                    page.wait_for_timeout(500)
                except Exception:
                    pass

        zoom = settings.config["settings"]["zoom"]
        if zoom != 1:
            page.evaluate(f"document.body.style.zoom={zoom}")

        def translate_text(text: str) -> str:
            return translators.translate_text(text, to_language=lang, translator="google")

        # ── Title screenshot ──────────────────────────────────────────────
        postcontentpath = f"assets/temp/{reddit_id}/png/title.png"
        try:
            post_el = page.locator("shreddit-post").first

            if lang:
                print_substep("Translating post title...")
                translated_title = translate_text(reddit_object["thread_title"])
                page.evaluate(
                    """(tl) => {
                        const post = document.querySelector('shreddit-post');
                        const h1 = post.querySelector('h1') || post.shadowRoot?.querySelector('h1');
                        if (h1) h1.textContent = tl;
                    }""",
                    translated_title,
                )

            post_el.screenshot(path=postcontentpath)
            print_substep("Title screenshot captured.", style="bold green")
        except Exception as e:
            print_substep(f"Failed to screenshot title: {e}", style="red")
            resp = input("Something went wrong with the title screenshot. Skip this post? (y/n) ")
            if resp.casefold().startswith("y"):
                save_data("", "", "skipped", reddit_id, "")
                print_substep("Post skipped.", style="green")
                exit()
            raise e

        # ── Story mode ────────────────────────────────────────────────────
        if storymode:
            try:
                story_el = page.locator("shreddit-post .text-neutral-content").first
                story_el.wait_for(state="visible", timeout=10000)
                story_el.screenshot(path=f"assets/temp/{reddit_id}/png/story_content.png")
                print_substep("Story content screenshot captured.", style="bold green")
            except Exception as e:
                print_substep(f"Failed to screenshot story content: {e}", style="red")
                raise e
        else:
            # ── Full-thread screenshot + comment positions ────────────────
            print_substep("Waiting for comments to load...")

            # Wait for at least one comment to appear
            page.locator('shreddit-comment[depth="0"]').first.wait_for(
                state="visible", timeout=15000
            )
            page.wait_for_timeout(2000)

            # Collect the comment IDs we care about (from the reddit object)
            target_ids = [c["comment_id"] for c in reddit_object["comments"][:screenshot_num]]

            # Record positions of each target comment
            comment_positions = []
            found_count = 0
            for cid in track(target_ids, description="Locating comments..."):
                selector = f'shreddit-comment[thingid="t1_{cid}"]'
                el = page.locator(selector).first
                try:
                    el.scroll_into_view_if_needed()
                    page.wait_for_timeout(300)
                    box = el.bounding_box()
                    if box:
                        comment_positions.append({
                            "comment_id": cid,
                            "y": box["y"],
                            "height": box["height"],
                        })
                        found_count += 1
                except Exception as e:
                    print(f"Could not locate comment {cid}: {e}")
                    comment_positions.append({
                        "comment_id": cid,
                        "y": None,
                        "height": None,
                    })

            print_substep(f"Located {found_count}/{len(target_ids)} comments.")

            # Scroll back to top before taking the full-page screenshot
            page.evaluate("window.scrollTo(0, 0)")
            page.wait_for_timeout(1000)

            # Take the full-page screenshot
            thread_path = f"assets/temp/{reddit_id}/png/thread.png"
            page.screenshot(path=thread_path, full_page=True)
            print_substep("Full thread screenshot captured.", style="bold green")

            # The bounding_box Y values are in CSS pixels relative to the
            # page top. The screenshot is scaled by the device_scale_factor.
            # Save both the positions and the scale factor so final_video
            # can map correctly.
            positions_path = f"assets/temp/{reddit_id}/png/comment_positions.json"
            with open(positions_path, "w") as f:
                json.dump(
                    {
                        "device_scale_factor": dsf,
                        "viewport_width": W,
                        "viewport_height": H,
                        "comments": comment_positions,
                    },
                    f,
                    indent=2,
                )
            print_substep(f"Comment positions saved to {positions_path}", style="bold green")

        browser.close()

    print_substep("Screenshots downloaded Successfully.", style="bold green")
