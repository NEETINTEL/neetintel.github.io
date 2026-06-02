#!/usr/bin/env python3
"""
DTCP Gallery Generator
Generates output/dtcp_gallery.html — YouTube thumbnail gallery laid out as
a 7-wide ISO-week calendar (Mon → Sun).
"""

import re
import sys
from pathlib import Path
from collections import defaultdict
from datetime import date, timedelta

sys.path.insert(0, str(Path(__file__).parent))
from eam_github_index_ import (
    load_hfgcs_data,
    parse_youtube_playlist,
    get_groups_for_date,
)

def parse_yymmdd(s):
    return date(2000 + int(s[:2]), int(s[2:4]), int(s[4:6]))



HTML_HEAD = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>DTCP Gallery</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="referrer" content="strict-origin-when-cross-origin">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #0f1220;
      --fg: #e6e6eb;
      --muted: #9aa0b4;
      --link: #7aa2ff;
      --hover: #a5b9ff;
      --border: #2a2f4a;
      --empty: rgba(255,255,255,0.025);
    }

    *, *::before, *::after { box-sizing: border-box; }

    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--fg);
      line-height: 1.4;
    }

    main {
      max-width: 1400px;
      padding: 2rem 1.5rem 3rem;
      margin: 0 auto;
    }

    .page-header { margin-bottom: 1rem; }
    .page-header h1 { font-size: 1.3rem; font-weight: 600; margin: 0 0 0.2rem; }
    .page-header .subtitle { font-size: 0.85rem; color: var(--muted); margin: 0; }
    .page-header .subtitle a { color: var(--link); text-decoration: none; }
    .page-header .subtitle a:hover { color: var(--hover); text-decoration: underline; }

    .page-intro {
      margin: 0 0 1.5rem;
      padding: 0.9rem 1rem;
      background: rgba(122, 162, 255, 0.05);
      border: 1px solid var(--border);
      border-radius: 6px;
      font-size: 0.85rem;
      line-height: 1.6;
    }
    .page-intro p { margin: 0; }
    .page-intro p + p { margin-top: 0.75rem; }

    /* ── Filter bar ── */
    .filter-bar {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 0.5rem;
      margin-bottom: 1.25rem;
    }

    .filter-label {
      font-size: 0.8rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    .filter-btn {
      padding: 0.28rem 0.7rem;
      background: transparent;
      color: var(--muted);
      border: 1px solid var(--border);
      border-radius: 4px;
      cursor: pointer;
      font-family: inherit;
      font-size: 0.78rem;
      transition: all 0.15s;
    }

    .filter-btn:hover { color: var(--hover); border-color: var(--hover); }
    .filter-btn.active-all { color: var(--link); border-color: var(--link); background: rgba(122,162,255,0.1); }
    .filter-btn.active-f1  { color: #06b050; border-color: #06b050; background: rgba(6,176,80,0.1); }
    .filter-btn.active-f2  { color: #ed7d32; border-color: #ed7d32; background: rgba(237,125,50,0.1); }
    .filter-btn.active-f3  { color: #ffcc00; border-color: #ffcc00; background: rgba(255,204,0,0.1); }
    .filter-btn.active-f4  { color: #ff0467; border-color: #ff0467; background: rgba(255,4,103,0.1); }
    .filter-btn.active-f5  { color: #9063cd; border-color: #9063cd; background: rgba(144,99,205,0.1); }

    /* ── Scroll wrapper (enables horizontal scroll on narrow viewports) ── */
    .calendar-wrap {
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }

    /* ── DOW header bar ── */
    .dow-bar {
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      column-gap: 0.5rem;
      padding-bottom: 0.4rem;
      border-bottom: 1px solid var(--border);
      margin-bottom: 0.6rem;
    }

    .dow-bar .dow-cell {
      text-align: center;
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    /* ── Calendar grid ── */
    .dtcp-grid {
      display: grid;
      grid-template-columns: repeat(7, minmax(0, 1fr));
      column-gap: 0.5rem;
      row-gap: 0.5rem;
      align-items: stretch;
    }

    /* ── Day slot ── */
    .day-slot {
      display: flex;
      flex-direction: column;
      gap: 0.4rem;
      min-width: 0;
    }

    .day-slot.empty {
      background: var(--empty);
      border: 1px dashed rgba(255,255,255,0.07);
      border-radius: 5px;
      opacity: 0.15;
    }

    .day-slot.empty::after {
      content: '';
      display: block;
      aspect-ratio: 16 / 9;
    }

    /* ── Card ── */
    .dtcp-card {
      background: rgba(122, 162, 255, 0.04);
      border: 1px solid var(--border);
      border-radius: 5px;
      overflow: hidden;
      text-decoration: none;
      display: flex;
      flex-direction: column;
      transition: border-color 0.15s, background 0.15s;
    }

    .dtcp-card:hover {
      border-color: var(--link);
      background: rgba(122, 162, 255, 0.10);
    }

    .dtcp-card img {
      width: 100%;
      display: block;
      aspect-ratio: 16 / 9;
      object-fit: cover;
      background: #111;
    }

    .card-body {
      padding: 0.35rem 0.45rem 0.4rem;
      display: flex;
      flex-direction: column;
      gap: 0.3rem;
    }

    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .card-date {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.8rem;
      color: var(--link);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
      min-width: 0;
    }

    .dtcp-card:hover .card-date { color: var(--hover); }

    .card-groups {
      display: flex;
      gap: 3px;
      align-items: center;
      flex-shrink: 0;
      overflow: hidden;
    }

    /* ── Group indicators ── */
    .gi {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      transition: opacity 0.15s;
    }

    .gi.inactive { opacity: 0.15; }
    .gi-1 { background-color: #06b050; }
    .gi-2 { background-color: #ed7d32; }
    .gi-3 { background-color: #ffcc00; }
    .gi-4 { background-color: #ff0467; }
    .gi-5 { background-color: #9063cd; }
    .gi-u { background-color: #555; }

    /* ── Timeline ── */
    .timeline {
      display: flex;
      align-items: flex-end;
      height: 1rem;
      gap: 1px;
      background: #000;
      border: 1px solid var(--border);
      border-radius: 3px;
      overflow: hidden;
      flex-shrink: 0;
    }

    .tbar-c {
      flex: 1;
      min-width: 1px;
      display: flex;
      flex-direction: column-reverse;
    }

    .tbar-e {
      flex: 1;
      min-width: 1px;
      background: #333;
      height: 2px;
      opacity: 0.2;
      align-self: flex-start;
    }

    .tseg { width: 100%; }
    .tseg[data-group="1"] { background: #06b050; }
    .tseg[data-group="2"] { background: #ed7d32; }
    .tseg[data-group="3"] { background: #ffcc00; }
    .tseg[data-group="4"] { background: #ff0467; }
    .tseg[data-group="5"] { background: #9063cd; }
    .tseg[data-group="unclassified"] { background: #555; }

    /* ── Filter dimming ── */
    .dtcp-card.dimmed {
      opacity: 0.15;
    }

    /* ── Responsive ── */

    /* Tablet (600–899px): tighter columns, date stacks above groups */
    @media (max-width: 899px) {
      main { padding: 1rem 0.75rem 2rem; }
      .dow-bar,
      .dtcp-grid  { grid-template-columns: repeat(7, minmax(0, 1fr)); column-gap: 0.3rem; }
      .dtcp-grid  { row-gap: 0.3rem; }
      .card-date  { font-size: 0.72rem; }
      .card-header {
        flex-direction: column;
        align-items: flex-start;
        gap: 0.15rem;
      }
    }

    /* Mobile (< 560px): thumbnails-only mosaic, single-letter DOW */
    @media (max-width: 559px) {
      main { padding: 0.75rem 0.4rem 1.5rem; }
      .page-header h1 { font-size: 1.1rem; }
      .page-intro     { font-size: 0.78rem; }
      .dow-bar,
      .dtcp-grid  { grid-template-columns: repeat(7, minmax(0, 1fr)); column-gap: 2px; }
      .dtcp-grid  { row-gap: 3px; }
      .dow-bar    { margin-bottom: 3px; }
      .dow-cell   { font-size: 0.5rem; letter-spacing: 0; overflow: hidden; }
      .card-body  { display: none; }
      .dtcp-card  { border-radius: 2px; }
      /* Modal: full-width, compact info bar */
      .modal-overlay { padding: 0.4rem; }
      .modal-info {
        flex-wrap: wrap;
        gap: 0.4rem;
        padding: 0.5rem 0.6rem;
      }
      .modal-timeline { flex-basis: 100%; }
      .modal-yt-link  { margin-left: 0; }
    }

    /* ── Modal overlay ── */
    .modal-overlay {
      display: none;
      position: fixed;
      inset: 0;
      background: rgba(0, 0, 0, 0.88);
      z-index: 1000;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
    }

    .modal-overlay.open {
      display: flex;
    }

    .modal-box {
      background: #141728;
      border: 1px solid var(--border);
      border-radius: 8px;
      width: min(820px, 100%);
      overflow: hidden;
      position: relative;
      display: flex;
      flex-direction: column;
      box-shadow: 0 24px 80px rgba(0,0,0,0.6);
    }

    .modal-video {
      position: relative;
      width: 100%;
      aspect-ratio: 16 / 9;
      background: #000;
    }

    .modal-facade {
      position: absolute;
      inset: 0;
    }

    .modal-facade img {
      width: 100%;
      height: 100%;
      object-fit: cover;
      display: block;
    }

    .modal-facade img.sharpened {
      filter: url(#modal-sharpen);
    }

.modal-video iframe {
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      border: none;
    }

    .modal-info {
      padding: 0.7rem 1rem 0.8rem;
      display: flex;
      align-items: center;
      gap: 0.9rem;
    }

    .modal-date {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 1rem;
      font-weight: 600;
      color: var(--fg);
      flex-shrink: 0;
    }

    .modal-groups {
      display: flex;
      gap: 5px;
      align-items: center;
      flex-shrink: 0;
    }

    .modal-groups .gi {
      width: 11px;
      height: 11px;
    }

    .modal-timeline {
      flex: 1;
      min-width: 0;
    }

    .modal-timeline .timeline {
      height: 1.5rem;
    }

    .modal-yt-link {
      margin-left: auto;
      flex-shrink: 0;
      font-size: 0.8rem;
      color: var(--muted);
      text-decoration: none;
      white-space: nowrap;
      transition: color 0.15s;
    }

    .modal-yt-link:hover { color: var(--link); }

    /* ── Scroll jump button ── */
    .scroll-btn {
      position: fixed;
      bottom: 1.25rem;
      right: 1.25rem;
      background: rgba(42,47,74,0.92);
      color: var(--muted);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 0.35rem 0.65rem;
      font-size: 0.75rem;
      font-family: inherit;
      cursor: pointer;
      z-index: 500;
      backdrop-filter: blur(6px);
      transition: color 0.15s, border-color 0.15s;
    }
    .scroll-btn:hover { color: var(--fg); border-color: var(--muted); }

  </style>
</head>
<body>
<main>
  <div class="page-header">
    <h1>NEET INTEL DAILY TIMECARD PROJECT Gallery</h1>
    <p class="subtitle"><a href="index.html">← Back to index</a></p>
  </div>

  <div class="page-intro">
    <p>The <strong>NEET INTEL DAILY TIMECARD PROJECT</strong> is a set of daily timecards of transcribed Emergency Action Messages (EAMs) and/or Force Direction Messages (FDMs) broadcast by the US military over the High Frequency Global Communications System (HFGCS). The timecards are combined with the musical output of overseas (Korean, Japanese, and Chinese) entertainment industries for significant trends in military and musical activity.</p>
    <p>The <strong>NEET INTEL DAILY TIMECARD PROJECT</strong> is the Lindy Post-OSINT Kpop Aesthetic Project for Cryptographic Data Aggregation.</p>
  </div>

  <div class="filter-bar">
    <span class="filter-label">Filter:</span>
    <button class="filter-btn active-f1" data-filter="1" onclick="toggleGroup('1')" title="Group 1 (YL)">Group 1</button>
    <button class="filter-btn active-f2" data-filter="2" onclick="toggleGroup('2')" title="Group 2 (T5)">Group 2</button>
    <button class="filter-btn active-f3" data-filter="3" onclick="toggleGroup('3')" title="Group 3 (W5)">Group 3</button>
    <button class="filter-btn active-f4" data-filter="4" onclick="toggleGroup('4')" title="Group 4 (6K)">Group 4</button>
    <button class="filter-btn active-f5" data-filter="5" onclick="toggleGroup('5')" title="Group 5">Group 5</button>
  </div>

  <div class="calendar-wrap">
    <div class="dow-bar">
      <div class="dow-cell">Mon</div>
      <div class="dow-cell">Tue</div>
      <div class="dow-cell">Wed</div>
      <div class="dow-cell">Thu</div>
      <div class="dow-cell">Fri</div>
      <div class="dow-cell">Sat</div>
      <div class="dow-cell">Sun</div>
    </div>
    <div class="dtcp-grid" id="dtcp-grid">
"""

HTML_FOOT = """\
    </div><!-- .dtcp-grid -->
  </div><!-- .calendar-wrap -->
</main>

<button class="scroll-btn" id="scroll-btn">↓ Latest</button>

<!-- Sharpening filter for upscaled fallback thumbnails -->
<svg style="position:absolute;width:0;height:0;overflow:hidden" aria-hidden="true">
  <defs>
    <filter id="modal-sharpen" x="0" y="0" width="100%" height="100%" color-interpolation-filters="sRGB">
      <feConvolveMatrix order="3" kernelMatrix="-1 -1 -1  -1 9 -1  -1 -1 -1" preserveAlpha="true" result="sharpened"/>
      <feComponentTransfer in="sharpened">
        <feFuncR type="linear" slope="1.4" intercept="-0.2"/>
        <feFuncG type="linear" slope="1.4" intercept="-0.2"/>
        <feFuncB type="linear" slope="1.4" intercept="-0.2"/>
      </feComponentTransfer>
    </filter>
  </defs>
</svg>

<!-- Modal lightbox -->
<div id="modal" class="modal-overlay" onclick="handleOverlayClick(event)">
  <div class="modal-box">
<div class="modal-video" id="modal-video">
      <div class="modal-facade" id="modal-facade" onclick="loadVideo()" style="cursor:pointer">
        <img id="modal-thumb-img" src="" alt="">
      </div>
    </div>
    <div class="modal-info">
      <span class="modal-date" id="modal-date"></span>
      <span class="modal-groups" id="modal-groups"></span>
      <div class="modal-timeline" id="modal-timeline"></div>
      <a class="modal-yt-link" id="modal-yt-link" href="#" target="_blank">Watch on YouTube ↗</a>
    </div>
  </div>
</div>

<script>
  /* ── Filter ── */
  const ALL_GROUPS = ['1','2','3','4','5'];

  // Seed activeGroups from ?group= URL param if present.
  // e.g. ?group=3 or ?group=1,2,3 — unrecognised values ignored.
  const _urlGroups = new URLSearchParams(location.search).get('group');
  const _seed = _urlGroups
    ? _urlGroups.split(',').map(s => s.trim()).filter(g => ALL_GROUPS.includes(g))
    : [];
  let activeGroups = new Set(_seed.length ? _seed : ALL_GROUPS);

  function toggleGroup(g) {
    activeGroups.has(g) ? activeGroups.delete(g) : activeGroups.add(g);
    applyFilter();
  }

  function applyFilter() {
    const noFilter = activeGroups.size === ALL_GROUPS.length;
    document.querySelectorAll('.filter-btn[data-filter]').forEach(btn => {
      const g = btn.dataset.filter;
      btn.className = 'filter-btn';
      if (noFilter || activeGroups.has(g)) btn.classList.add('active-f' + g);
    });
    document.querySelectorAll('.dtcp-card[data-groups]').forEach(card => {
      if (noFilter) { card.classList.remove('dimmed'); return; }
      const groups = card.dataset.groups.split(',');
      card.classList.toggle('dimmed', !groups.some(g => activeGroups.has(g)));
    });
    // Sync URL
    const u = new URL(location.href);
    if (noFilter) { u.searchParams.delete('group'); }
    else { u.searchParams.set('group', [...activeGroups].sort().join(',')); }
    history.replaceState(null, '', u);
  }

  applyFilter();

  /* ── Modal ── */
  let currentCard = null;

  function openModal(event, el) {
    event.preventDefault();
    showModal(el);
  }

  function showModal(el) {
    currentCard = el;
    const url = el.href;
    const vid = new URL(url).searchParams.get('v');

    // Remove any existing iframe and reset facade
    const existing = document.getElementById('modal-iframe');
    if (existing) existing.remove();
    document.getElementById('modal-facade').style.display = '';
    document.getElementById('modal-video').dataset.vid = vid;

    // YouTube returns a valid 120×90 placeholder JPEG for missing maxresdefault,
    // so onerror never fires — check naturalWidth instead.
    // Apply CSS sharpening when we fall back to a lower-res image.
    const thumbQualities = ['maxresdefault', 'sddefault', 'hqdefault', 'mqdefault'];
    function tryThumb(vid, qualities, isFallback) {
      if (!qualities.length) return;
      const img = document.getElementById('modal-thumb-img');
      img.onload = function() {
        if (this.naturalWidth === 120 && this.naturalHeight === 90) {
          tryThumb(vid, qualities.slice(1), true);
        } else {
          this.classList.toggle('sharpened', isFallback);
        }
      };
      img.onerror = function() { this.onerror = null; tryThumb(vid, qualities.slice(1), true); };
      img.src = 'https://img.youtube.com/vi/' + vid + '/' + qualities[0] + '.jpg';
    }
    tryThumb(vid, thumbQualities, false);
    document.getElementById('modal-thumb-img').alt =
      el.querySelector('.card-date').textContent;

    document.getElementById('modal-date').textContent =
      el.querySelector('.card-date').textContent;
    document.getElementById('modal-groups').innerHTML =
      el.querySelector('.card-groups').innerHTML;
    document.getElementById('modal-timeline').innerHTML =
      el.querySelector('.timeline').outerHTML;
    document.getElementById('modal-yt-link').href = url;
    document.getElementById('modal').classList.add('open');
    document.body.style.overflow = 'hidden';
  }

  function loadVideo() {
    const vid = document.getElementById('modal-video').dataset.vid;
    document.getElementById('modal-facade').style.display = 'none';
    const iframe = document.createElement('iframe');
    iframe.id = 'modal-iframe';
    iframe.src = 'https://www.youtube-nocookie.com/embed/' + vid + '?autoplay=1&rel=0';
    iframe.allow = 'autoplay; encrypted-media; picture-in-picture';
    iframe.allowFullscreen = true;
    iframe.setAttribute('referrerpolicy', 'strict-origin-when-cross-origin');
    document.getElementById('modal-video').appendChild(iframe);
  }

  function closeModal() {
    document.getElementById('modal').classList.remove('open');
    const iframe = document.getElementById('modal-iframe');
    if (iframe) iframe.remove();
    document.getElementById('modal-facade').style.display = '';
    document.body.style.overflow = '';
    currentCard = null;
  }

  function handleOverlayClick(event) {
    if (event.target === document.getElementById('modal')) closeModal();
  }

  /* ── Grid navigation ── */
  function isoDow(dateStr) {
    // dateStr: YYMMDD or YYMMDDsuffix — returns ISO weekday Mon=1 … Sun=7
    const base = dateStr.replace(/[A-Z]+$/, '');
    const d = new Date(2000 + +base.slice(0,2), +base.slice(2,4) - 1, +base.slice(4,6));
    return d.getDay() === 0 ? 7 : d.getDay();
  }

  function navigateModal(dir) {
    if (!currentCard) return;
    const all = Array.from(document.querySelectorAll('.dtcp-card'));
    const idx = all.indexOf(currentCard);

    let next = null;
    if (dir === 'right') {
      next = all[idx + 1] ?? null;
    } else if (dir === 'left') {
      next = all[idx - 1] ?? null;
    } else {
      const curDow = isoDow(currentCard.querySelector('.card-date').textContent);
      const sameDow = all.filter(c => isoDow(c.querySelector('.card-date').textContent) === curDow);
      const si = sameDow.indexOf(currentCard);
      next = dir === 'down' ? (sameDow[si + 1] ?? null) : (sameDow[si - 1] ?? null);
    }

    if (next) showModal(next);
  }

  document.addEventListener('keydown', e => {
    const modalOpen = document.getElementById('modal').classList.contains('open');
    if (e.key === 'Escape') { closeModal(); return; }
    if (!modalOpen) return;
    const map = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' };
    if (map[e.key]) { e.preventDefault(); navigateModal(map[e.key]); }
  });

  /* ── Scroll jump button ── */
  const _scrollBtn = document.getElementById('scroll-btn');
  function _updateScrollBtn() {
    const atBottom = (window.scrollY + window.innerHeight) >= (document.body.scrollHeight - 100);
    _scrollBtn.textContent = atBottom ? '↑ Top' : '↓ Latest';
  }
  _scrollBtn.addEventListener('click', () => {
    if (_scrollBtn.textContent.startsWith('↓')) {
      window.scrollTo({ top: document.body.scrollHeight, behavior: 'smooth' });
    } else {
      window.scrollTo({ top: 0, behavior: 'smooth' });
    }
  });
  window.addEventListener('scroll', _updateScrollBtn, { passive: true });
  _updateScrollBtn();
</script>
</body>
</html>
"""


def get_video_id(url):
    m = re.search(r'v=([a-zA-Z0-9_-]+)', url)
    return m.group(1) if m else None


def build_group_indicators(groups, group_prefixes):
    parts = []
    for g in [1, 2, 3, 4, 5]:
        active = '' if g in groups else 'inactive'
        if g in groups and g in group_prefixes:
            title = ', '.join(sorted(str(p) for p in group_prefixes[g]))
        else:
            title = f'Group {g}'
        parts.append(f'<span class="gi gi-{g} {active}" data-group="{g}" title="{title}"></span>')
    active = '' if 'unclassified' in groups else 'inactive'
    if 'unclassified' in groups and 'unclassified' in group_prefixes:
        title = ', '.join(sorted(str(p) for p in group_prefixes['unclassified']))
    else:
        title = 'Unknown'
    parts.append(f'<span class="gi gi-u {active}" data-group="unclassified" title="{title}"></span>')
    return ''.join(parts)


def build_timeline(period_counts, period_groups, period_group_counts):
    max_count = max(period_counts) if period_counts else 1
    group_order = [1, 2, 3, 4, 5, 'unclassified']
    html = '<div class="timeline">'
    for i in range(72):
        count = period_counts[i] if i < len(period_counts) else 0
        if count > 0:
            h = min(100, (count / max_count) * 100) if max_count > 0 else 0
            html += f'<span class="tbar-c" style="height:{h:.1f}%;">'
            pg = period_groups[i] if i < len(period_groups) else set()
            pgc = period_group_counts[i] if i < len(period_group_counts) else {}
            for g in group_order:
                if g in pg:
                    s = (pgc.get(g, 0) / count * 100) if count > 0 else 0
                    html += f'<span class="tseg" data-group="{g}" style="height:{s:.1f}%;"></span>'
            html += '</span>'
        else:
            html += '<span class="tbar-e"></span>'
    html += '</div>'
    return html


def groups_attr(groups):
    parts = [str(g) for g in groups if g != 'unclassified']
    if 'unclassified' in groups:
        parts.append('unclassified')
    return ','.join(parts)


def write_card(f, entry, display_date):
    vid = entry['video_id'] or ''
    thumb = f'https://img.youtube.com/vi/{vid}/mqdefault.jpg' if vid else ''
    indicators = build_group_indicators(entry['groups'], entry['group_prefixes'])
    timeline = build_timeline(
        entry['period_counts'], entry['period_groups'], entry['period_group_counts']
    )
    gattr = groups_attr(entry['groups'])
    f.write(
        f'<a class="dtcp-card" href="{entry["url"]}" target="_blank" data-groups="{gattr}" onclick="openModal(event,this)">\n'
        f'  <img src="{thumb}" alt="{display_date}" loading="lazy">\n'
        f'  <div class="card-body">\n'
        f'    <div class="card-header">\n'
        f'      <span class="card-date">{display_date}</span>\n'
        f'      <span class="card-groups">{indicators}</span>\n'
        f'    </div>\n'
        f'    {timeline}\n'
        f'  </div>\n'
        f'</a>\n'
    )


def main():
    script_dir = Path(__file__).parent
    output_path = script_dir / 'output'
    json_path = output_path / 'data' / 'dtcp_playlist_data.json'
    out_file = output_path / 'dtcp_gallery.html'

    if not json_path.exists():
        print(f"Error: {json_path} not found")
        sys.exit(1)

    print("Loading HFGCS data...")
    hfgcs_df, pr_groups_df = load_hfgcs_data()

    print("Parsing DTCP playlist...")
    videos = parse_youtube_playlist(json_path)

    # Build entries list
    entries = []
    for video in videos:
        for date_str in video['dates']:
            base_date = date_str.rstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
            groups, group_prefixes, period_counts, period_groups, period_group_counts = \
                get_groups_for_date(hfgcs_df, pr_groups_df, base_date)
            entries.append({
                'url': video['url'],
                'date': date_str,
                'base_date': base_date,
                'video_id': get_video_id(video['url']),
                'groups': groups,
                'group_prefixes': group_prefixes,
                'period_counts': period_counts,
                'period_groups': period_groups,
                'period_group_counts': period_group_counts,
            })

    # 230911 ~ 230922 range video: its 230911 slot belongs to the single-day video;
    # treat this video as starting from 230912.
    entries = [e for e in entries if not (e['video_id'] == 'b09RcZU8m9s' and e['base_date'] == '230911')]

    print(f"Found {len(entries)} DTCP entries")

    # Group by base_date
    by_date = defaultdict(list)
    for entry in entries:
        by_date[entry['base_date']].append(entry)

    # Group by ISO week: {(iso_year, iso_week): {dow(1-7): [entries]}}
    by_week = defaultdict(lambda: defaultdict(list))
    for base_date, date_entries in by_date.items():
        d = parse_yymmdd(base_date)
        iso = d.isocalendar()
        by_week[(iso[0], iso[1])][iso[2]].append((base_date, date_entries))

    data_weeks = sorted(by_week.keys())
    # Fill every ISO week between first and last, inclusive (no gaps).
    first_mon = date.fromisocalendar(*data_weeks[0], 1)
    last_mon  = date.fromisocalendar(*data_weeks[-1], 1)
    sorted_weeks = []
    cur = first_mon
    while cur <= last_mon:
        iso = cur.isocalendar()
        sorted_weeks.append((iso[0], iso[1]))
        cur += timedelta(weeks=1)
    print(f"Spanning {len(sorted_weeks)} ISO weeks ({len(data_weeks)} with entries)")

    print(f"Writing {out_file}...")

    with open(out_file, 'w', encoding='utf-8') as f:
        f.write(HTML_HEAD)

        for (iso_year, iso_week) in sorted_weeks:
            week_data = by_week[(iso_year, iso_week)]

            # DOW columns 1 (Mon) through 7 (Sun)
            for dow in range(1, 8):
                day_entries = week_data.get(dow, [])
                if not day_entries:
                    f.write('      <div class="day-slot empty"></div>\n')
                else:
                    f.write('      <div class="day-slot">\n')
                    for base_date, date_entries in day_entries:
                        for i, entry in enumerate(date_entries):
                            if len(date_entries) > 1:
                                display_date = f'{base_date}{chr(65 + i)}'
                            else:
                                display_date = entry['date']
                            f.write('        ')
                            write_card(f, entry, display_date)
                    f.write('      </div>\n')

        f.write(HTML_FOOT)

    print(f"Done! → {out_file}")


if __name__ == '__main__':
    main()
