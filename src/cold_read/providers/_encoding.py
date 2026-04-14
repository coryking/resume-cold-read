"""Shared image-encoding helpers for OpenAI-SDK shapes.

Only the two Azure shapes use base64-image-in-messages today. `claude-cli`
writes paths as strings into its prompt and the subprocess Reads them
off disk — it never touches this module.
"""

from __future__ import annotations

import base64
from pathlib import Path


def build_chat_messages(
    prompt_text: str,
    images: list[Path],
    max_images: int | None,
) -> list[dict]:
    """Return a chat-completions `messages` list with images as base64 parts.

    If `max_images` is set and smaller than the image count, the prompt
    gets an explicit truncation note so the model doesn't silently assume
    it saw the whole document.
    """
    pages = images
    truncated = False
    if max_images and len(pages) > max_images:
        pages = pages[:max_images]
        truncated = True

    content_parts: list[dict] = []
    for png in pages:
        b64 = base64.b64encode(png.read_bytes()).decode("utf-8")
        content_parts.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{b64}",
                    "detail": "high",
                },
            }
        )

    suffix = ""
    if truncated:
        suffix = (
            f"\n\n[NOTE: This model can only process {max_images} image(s). "
            f"You are seeing page(s) 1-{max_images} of {len(images)}.]"
        )

    content_parts.append({"type": "text", "text": prompt_text + suffix})
    return [{"role": "user", "content": content_parts}]
