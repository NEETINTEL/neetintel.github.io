# Per-day thumbnail overrides for the DTCP gallery

Drop an image here named after the date it should represent and the gallery
will use it instead of the YouTube video's thumbnail. This is how multi-day
editions (one video covering e.g. 230911–230922) get a distinct thumbnail per
day card.

## Naming

    YYMMDD.<ext>        e.g.  230922.jpg

Accepted extensions: `.jpg`, `.jpeg`, `.png`, `.webp`.

For a day that has more than one video (rare A/B/C cards), you can target the
suffixed slot — `230912A.jpg` — and it takes precedence over `230912.jpg`.

## Behaviour

- If a file matching the date exists here, the card AND the modal lightbox use
  it. If not, the gallery falls back to `img.youtube.com/.../mqdefault.jpg`.
- Only the still image changes — the card's watch link and the in-modal player
  still point at the real YouTube edition.
- 16:9 images look best (cards and the modal use `aspect-ratio: 16/9`).

## Publishing

This folder is served as static files. Upload it to GitHub in the **same
directory** as `dtcp_gallery.html`; the HTML references `thumbs/230922.jpg`
(relative), so the layout must match: `dtcp_gallery.html` and `thumbs/` side by
side.
