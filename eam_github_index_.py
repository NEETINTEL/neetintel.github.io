#!/usr/bin/env python3
"""
EAM GitHub Index Generator
Generates index.html with heatmap previews for all generated EAM structure heatmap pages.
Can be run independently or imported by eam_heatmap_.py
"""

import re
import json
import html as html_module
import math
import os
import sys
from pathlib import Path
from collections import defaultdict
import pandas as pd


def extract_heatmap_colors(html_path):
    """Extract heatmap cell colors from a generated HTML file."""
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all heatmap cells with their background colors
        pattern = r'<div class="heatmap-cell" style="background-color: ([^"]+);"'
        matches = re.findall(pattern, content)

        return matches if matches else None
    except Exception as e:
        print(f"Error reading {html_path}: {e}")
        return None


def extract_groups(html_path):
    """Extract which groups are present in this file."""
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        groups_present = set()
        pattern = r'data-group="([^"]+)"'
        matches = re.findall(pattern, content)

        for group in matches:
            if group == 'unclassified':
                groups_present.add('unclassified')
            else:
                groups_present.add(int(group))

        return groups_present
    except Exception as e:
        print(f"Error reading {html_path}: {e}")
        return set()


def extract_message_count(html_path):
    """Extract total number of messages from the HTML file."""
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Count unique messages by counting data-group attributes
        pattern = r'data-group="([^"]+)"'
        matches = re.findall(pattern, content)

        return len(matches) if matches else 0
    except Exception as e:
        print(f"Error reading {html_path}: {e}")
        return 0


def get_prefixes_for_message_length(df, pr_groups_df, message_length):
    """Get which prefixes belong to which groups for a specific message length.

    Returns:
        dict: group -> list of prefixes
    """
    if df is None or pr_groups_df is None:
        return {}

    try:
        # Filter messages by length
        df_filtered = df[df['MESSAGE'].apply(lambda m: len(str(m)) == message_length if pd.notna(m) else False)].copy()

        group_prefixes = {}

        for _, row in df_filtered.iterrows():
            prefix = row.get('PR')
            if pd.isna(prefix):
                continue

            # Get year from date
            date_str = str(row.get('DATE', ''))
            try:
                # Parse year from date string (format: YYYY.MM.DD or similar)
                year = int(date_str.split('.')[0]) if '.' in date_str else int(date_str.split('-')[0])
            except:
                continue

            # Look up group for this prefix/year
            group = lookup_group(pr_groups_df, prefix, year)
            if group is not None:
                if group not in group_prefixes:
                    group_prefixes[group] = set()
                group_prefixes[group].add(prefix)
            else:
                # Unclassified
                if 'unclassified' not in group_prefixes:
                    group_prefixes['unclassified'] = set()
                group_prefixes['unclassified'].add(prefix)

        # Convert sets to sorted lists
        return {g: sorted(list(p)) for g, p in group_prefixes.items()}
    except Exception as e:
        print(f"Error getting prefixes for length {message_length}: {e}")
        return {}


def extract_messages_by_group(html_path, message_length):
    """
    Extract pattern data organized by group and calculate per-group heatmaps.
    Returns dict: {group: position_counts_array}
    """
    try:
        with open(html_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # Find all message blocks with their group and pattern data
        block_pattern = r'<div class="message-block"[^>]*data-group="([^"]+)"[^>]*data-patterns="([^"]+)"'
        matches = re.findall(block_pattern, content)

        # Organize by group
        group_patterns = {}
        for group, patterns_json in matches:
            if group not in group_patterns:
                group_patterns[group] = []

            # Parse pattern data
            try:
                patterns_data = json.loads(html_module.unescape(patterns_json))
                group_patterns[group].append(patterns_data)
            except:
                pass

        # Calculate position counts for each group
        group_heatmaps = {}
        for group, patterns_list in group_patterns.items():
            position_counts = [0.0] * message_length

            for patterns_data in patterns_list:
                # Each patterns_data is a list of pattern objects with 'positions' and 'weight'
                covered_positions = set()
                for pattern in patterns_data:
                    if 'positions' in pattern and isinstance(pattern['positions'], list):
                        for pos in pattern['positions']:
                            if 0 <= pos < message_length:
                                covered_positions.add(pos)

                # Increment count for each covered position
                for pos in covered_positions:
                    position_counts[pos] += 1.0

            group_heatmaps[group] = position_counts

        return group_heatmaps
    except Exception as e:
        print(f"Error extracting messages by group from {html_path}: {e}")
        return {}


def generate_colors_from_counts(position_counts):
    """Generate heatmap colors from position counts using cubic scaling."""
    max_count = max(position_counts) if position_counts else 1
    colors = []

    for count in position_counts:
        if count == 0:
            colors.append('#1a1a1a')  # Dark background
        else:
            log_ratio = math.log(count + 1) / math.log(max_count + 1)
            intensity_ratio = log_ratio ** 3  # Cubic power
            intensity = int(intensity_ratio * 255)
            # Orange/yellow gradient
            colors.append(f'rgb({intensity}, {intensity//2}, 0)')

    return colors


def normalize_color(color_str, avg_intensity, num_messages, ref_intensity=68.4, ref_messages=39):
    """
    Normalize color intensity based on BOTH structural strength and sample size.
    Uses 51-char as the baseline reference (avg_intensity=68.4, messages=39).

    Key insight: Sample size effect DEPENDS on what you find:
    - Large sample + strong patterns → boost (we're confident it's real)
    - Large sample + weak patterns → penalize (we're confident there's no structure)
    - Small sample → less effect either way (not enough data to be sure)
    """
    if color_str == '#1a1a1a':
        return color_str  # Keep dark background as-is

    # Parse rgb color
    if color_str.startswith('rgb('):
        rgb_match = re.search(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color_str)
        if rgb_match:
            r, g, b = int(rgb_match.group(1)), int(rgb_match.group(2)), int(rgb_match.group(3))

            # Factor 1: Structural strength relative to 51-char reference
            structural_factor = (avg_intensity / ref_intensity) ** 0.7 if avg_intensity > 0 else 0
            structural_factor = min(structural_factor, 1.3)  # Cap boost at 30%

            # Factor 2: Sample size effect - DIRECTION depends on ABSOLUTE structural strength
            # Use 150 as threshold (not the reference) - truly strong patterns are >150
            # Weak patterns (<150): larger sample confirms lack of structure → penalize
            # Strong patterns (>150): larger sample boosts confidence
            if avg_intensity > 150:
                # Truly strong patterns: large sample boosts
                sample_factor = (num_messages / ref_messages) ** 0.4
                sample_factor = min(sample_factor, 1.2)
            else:
                # Weak/moderate patterns: large sample penalizes (inverted relationship)
                sample_factor = (ref_messages / num_messages) ** 0.4
                sample_factor = max(sample_factor, 0.7)  # Don't penalize too harshly

            # Combine both factors
            combined_factor = structural_factor * sample_factor

            r = int(r * combined_factor)
            g = int(g * combined_factor)
            b = int(b * combined_factor)

            # Clamp to valid RGB range
            r = min(255, r)
            g = min(255, g)
            b = min(255, b)

            return f'rgb({r}, {g}, {b})'

    return color_str


def generate_svg_heatmap(colors, num_messages, height=12, max_length=None):
    """Generate inline SVG representation of heatmap with width proportional to message length and normalized colors.

    When max_length is provided, the SVG width is scaled so that a max_length
    heatmap fills the container and shorter heatmaps are proportionally narrower.
    """
    if not colors:
        return '<svg width="100" height="12"><rect width="100" height="12" fill="#1a1a1a"/></svg>'

    # Scale width as a percentage of max_length (if provided) so all
    # heatmaps share a consistent spatial scale.
    effective_max = max_length if max_length else len(colors)
    width_pct = (len(colors) / effective_max) * 100
    width_attr = f'{width_pct:.2f}%'

    # Use a viewBox sized to the number of cells so each cell is 1 unit wide
    viewbox_w = len(colors)

    # Find average intensity (R value) in this heatmap for normalization
    r_values = []
    for color in colors:
        if color.startswith('rgb('):
            rgb_match = re.search(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color)
            if rgb_match:
                r = int(rgb_match.group(1))
                r_values.append(r)

    avg_intensity = sum(r_values) / len(r_values) if r_values else 0

    svg_parts = [f'<svg width="{width_attr}" height="{height}" viewBox="0 0 {viewbox_w} {height}" preserveAspectRatio="none" xmlns="http://www.w3.org/2000/svg">']

    for i, color in enumerate(colors):
        normalized_color = normalize_color(color, avg_intensity, num_messages)
        svg_parts.append(f'<rect x="{i}" y="0" width="1" height="{height}" fill="{normalized_color}"/>')

    svg_parts.append('</svg>')

    return ''.join(svg_parts)


def load_hfgcs_data():
    """Load the HFGCS dataset for group lookups."""
    excel_path = Path("/Users/core/Documents/_CORE/SHORTWAVES.xlsx")
    csv_path = Path("data/set-all.csv")

    try:
        # Load SET-ALL
        if csv_path.exists():
            df = pd.read_csv(csv_path)
        else:
            df = pd.read_excel(excel_path, sheet_name='SET-ALL')

        # Filter out quality issues
        if 'Q' in df.columns:
            df = df[~df['Q'].astype(str).str.contains(r'[\\*]', na=False)]

        # Filter out uncertain transcriptions
        if 'MESSAGE' in df.columns:
            df = df[df['MESSAGE'].notna()]
            df = df[~df['MESSAGE'].astype(str).str.contains(r'[?_.]', na=False)]

        # Load PR_GROUPS sheet
        pr_groups_df = pd.read_excel(excel_path, sheet_name='PR_GROUPS')

        return df, pr_groups_df
    except Exception as e:
        print(f"Error loading HFGCS data: {e}")
        return None, None


def parse_dates_from_title(title):
    """Extract YYMMDD dates from video title, including A/B/C suffixes and ranges."""
    from datetime import datetime, timedelta

    # First check for range pattern like "220101 ~ 220110" (inclusive)
    range_pattern = r'\b(\d{6})\s*~\s*(\d{6})\b'
    range_match = re.search(range_pattern, title)
    if range_match:
        start_str, end_str = range_match.group(1), range_match.group(2)
        try:
            start_date = datetime(int('20' + start_str[:2]), int(start_str[2:4]), int(start_str[4:6]))
            end_date = datetime(int('20' + end_str[:2]), int(end_str[2:4]), int(end_str[4:6]))
            dates = []
            current = start_date
            while current <= end_date:
                dates.append(current.strftime('%y%m%d'))
                current += timedelta(days=1)
            return dates
        except (ValueError, IndexError):
            pass

    # Match patterns like "220126", "230222A", "230222B", or "220129 + 220130 + 220131"
    # Also match dates with trailing 'x' like "240327x" and strip the 'x'
    date_pattern = r'\b(\d{6}[A-Z]?)x?\b'
    matches = re.findall(date_pattern, title)
    return matches


def are_dates_consecutive(date1, date2):
    """Check if two YYMMDD dates are consecutive (date2 is one day after date1)."""
    from datetime import datetime, timedelta

    try:
        # Parse YYMMDD format (strip any letter suffix)
        date1_str = date1.rstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
        date2_str = date2.rstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ')

        # Convert YY to full year (20YY for now, adjust if needed)
        year1 = int('20' + date1_str[0:2])
        month1 = int(date1_str[2:4])
        day1 = int(date1_str[4:6])

        year2 = int('20' + date2_str[0:2])
        month2 = int(date2_str[2:4])
        day2 = int(date2_str[4:6])

        d1 = datetime(year1, month1, day1)
        d2 = datetime(year2, month2, day2)

        # Check if d2 is exactly one day after d1
        return (d2 - d1).days == 1
    except:
        return False


def lookup_group(pr_groups_df, prefix, year):
    """Look up group number for a prefix and year, with fallback to previous years."""
    if pr_groups_df is None or pd.isna(prefix):
        return None

    # Convert prefix to string for comparison (handles numeric prefixes like 24, 44, etc.)
    prefix_str = str(prefix)

    # Try exact year match first
    match = pr_groups_df[(pr_groups_df['PREFIX'].astype(str) == prefix_str) & (pr_groups_df['YEAR'] == year)]
    if not match.empty:
        return match.iloc[0]['GROUP']

    # Fall back to most recent year before the target year
    earlier_matches = pr_groups_df[(pr_groups_df['PREFIX'].astype(str) == prefix_str) & (pr_groups_df['YEAR'] < year)]
    if not earlier_matches.empty:
        # Get the most recent year
        most_recent = earlier_matches.sort_values('YEAR', ascending=False).iloc[0]
        return most_recent['GROUP']

    return None


def get_groups_for_date(df, pr_groups_df, yymmdd):
    """Get set of group numbers and prefixes mapping for a specific YYMMDD date.

    Returns:
        tuple: (set of groups, dict of group -> list of prefixes, list of 20-min period counts, list of period groups, list of period group counts)
    """
    if df is None:
        return set(), {}, [], [], []

    # Convert YYMMDD to various date formats to match
    try:
        # Try parsing as YYMMDD
        year = int('20' + yymmdd[:2])
        month = int(yymmdd[2:4])
        day = int(yymmdd[4:6])

        # Create date strings in various formats
        date_formats = [
            f"{year}.{month:02d}.{day:02d}",
            f"{year}-{month:02d}-{day:02d}",
            f"{year}/{month:02d}/{day:02d}",
            f"{month:02d}/{day:02d}/{year}"
        ]

        # Filter messages for this date
        date_messages = df[df['DATE'].astype(str).isin(date_formats)]

        # Filter out messages with prefix '%' (indicates no messages broadcast)
        if 'PR' in date_messages.columns:
            date_messages = date_messages[date_messages['PR'] != '%']

        # Get unique prefixes (PR column) and map to groups
        groups = set()
        group_prefixes = {}  # group -> list of prefixes

        if 'PR' in date_messages.columns:
            prefixes = date_messages['PR'].dropna().unique()

            for prefix in prefixes:
                group = lookup_group(pr_groups_df, prefix, year)
                if group is not None:
                    groups.add(group)
                    if group not in group_prefixes:
                        group_prefixes[group] = []
                    group_prefixes[group].append(prefix)
                else:
                    # Prefix not classified
                    groups.add('unclassified')
                    if 'unclassified' not in group_prefixes:
                        group_prefixes['unclassified'] = []
                    group_prefixes['unclassified'].append(prefix)

        # Extract UTC times and track groups by 20-minute periods (72 segments)
        period_counts = [0] * 72  # 72 periods (24 hours * 3 per hour) - total message count
        period_groups = [set() for _ in range(72)]  # which groups had messages in each period
        period_group_counts = [{} for _ in range(72)]  # count per group per period

        if 'UTC' in date_messages.columns and 'PR' in date_messages.columns:
            for _, row in date_messages.iterrows():
                utc = row.get('UTC')
                prefix = row.get('PR')

                if pd.isna(utc):
                    continue

                try:
                    utc_str = str(utc).strip()
                    # Parse time formats like "14:30:00" or "14:30" or "14"
                    if ':' in utc_str:
                        parts = utc_str.split(':')
                        hour = int(parts[0])
                        minute = int(parts[1]) if len(parts) > 1 else 0
                    else:
                        hour = int(utc_str)
                        minute = 0

                    # Calculate 20-minute period (0-71)
                    if 0 <= hour < 24:
                        period = hour * 3 + (minute // 20)
                        if 0 <= period < 72:
                            period_counts[period] += 1

                            # Track which group this message belongs to and count
                            if pd.notna(prefix):
                                group = lookup_group(pr_groups_df, str(prefix).strip(), year)
                                if group is not None:
                                    period_groups[period].add(group)
                                    if group not in period_group_counts[period]:
                                        period_group_counts[period][group] = 0
                                    period_group_counts[period][group] += 1
                                else:
                                    period_groups[period].add('unclassified')
                                    if 'unclassified' not in period_group_counts[period]:
                                        period_group_counts[period]['unclassified'] = 0
                                    period_group_counts[period]['unclassified'] += 1
                except:
                    pass

        return groups, group_prefixes, period_counts, period_groups, period_group_counts
    except Exception as e:
        print(f"Error processing date {yymmdd}: {e}")
        return set(), {}, [], [], []


def parse_youtube_playlist(json_path):
    """Parse yt-dlp JSON output and extract video info with dates."""
    videos = []

    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            for line in f:
                data = json.loads(line.strip())

                title = data.get('title', '')
                url = data.get('webpage_url', '')
                playlist_id = data.get('playlist_id', '')
                playlist_index = data.get('playlist_index', '')

                # Extract dates from title
                dates = parse_dates_from_title(title)

                if dates:
                    # Add playlist context to URL
                    if playlist_id and playlist_index:
                        url_with_playlist = f"{url}&list={playlist_id}&index={playlist_index}"
                    else:
                        url_with_playlist = url

                    videos.append({
                        'title': title,
                        'url': url_with_playlist,
                        'dates': dates
                    })

    except Exception as e:
        print(f"Error parsing YouTube playlist: {e}")

    return videos


def generate_index(output_dir):
    """Generate index.html with heatmap previews for all generated pages."""
    output_path = Path(output_dir)

    # Load HFGCS data for YouTube group lookups
    print("Loading HFGCS data for YouTube group indicators...")
    hfgcs_df, pr_groups_df = load_hfgcs_data()

    # Parse YouTube playlist data if it exists
    def parse_playlist_entries(json_path, label):
        """Parse a playlist JSON and expand into date-keyed entries."""
        entries = []
        if json_path.exists():
            print(f"Processing {label} playlist data...")
            videos = parse_youtube_playlist(json_path)
            for video in videos:
                for date in video['dates']:
                    base_date = date.rstrip('ABCDEFGHIJKLMNOPQRSTUVWXYZ')
                    groups, group_prefixes, period_counts, period_groups, period_group_counts = get_groups_for_date(hfgcs_df, pr_groups_df, base_date)
                    entries.append({
                        'title': video['title'],
                        'url': video['url'],
                        'date': date,
                        'base_date': base_date,
                        'groups': groups,
                        'group_prefixes': group_prefixes,
                        'period_counts': period_counts,
                        'period_groups': period_groups,
                        'period_group_counts': period_group_counts
                    })
            print(f"Found {len(entries)} {label} entries")
        return entries

    dcrp_entries = parse_playlist_entries(output_path / "data" / "dcrp_playlist_data.json", "DCRP")
    dtcp_entries = parse_playlist_entries(output_path / "data" / "dtcp_playlist_data.json", "DTCP")

    # Find all HTML files in the output directory
    all_html_files = list(output_path.glob('*.html'))

    # Separate heatmap files from other HTML files
    heatmap_entries = []
    other_entries = []

    for html_file in all_html_files:
        # Skip group-filtered files and index.html itself
        if '-gr' in html_file.name or html_file.name == 'index.html':
            continue

        # Check if it's a structure heatmap file
        match = re.search(r'structure_heatmap_(\d+)char\.html', html_file.name)
        if match:
            # It's a heatmap file - extract full data
            length = int(match.group(1))
            colors = extract_heatmap_colors(html_file)
            groups = extract_groups(html_file)
            num_messages = extract_message_count(html_file)
            group_prefixes = get_prefixes_for_message_length(hfgcs_df, pr_groups_df, length)

            # Extract per-group heatmaps (raw data — SVGs generated after max_length is known)
            group_heatmaps = extract_messages_by_group(html_file, length)

            heatmap_entries.append({
                'type': 'heatmap',
                'length': length,
                'filename': html_file.name,
                'colors': colors,
                'groups': groups,
                'num_messages': num_messages,
                'group_heatmaps': group_heatmaps,
                'group_prefixes': group_prefixes
            })
        else:
            # It's another HTML file - just add the filename
            other_entries.append({
                'type': 'other',
                'filename': html_file.name
            })

    # Sort heatmap entries by length
    heatmap_entries.sort(key=lambda x: x['length'])

    # Generate all SVGs with a shared scale based on the longest heatmap
    max_length = max((e['length'] for e in heatmap_entries), default=1)
    for entry in heatmap_entries:
        colors = entry['colors']
        num_messages = entry['num_messages']
        if colors and num_messages > 0:
            entry['heatmap_svg'] = generate_svg_heatmap(colors, num_messages, max_length=max_length)
        else:
            entry['heatmap_svg'] = '<svg width="100" height="12"><rect width="100" height="12" fill="#1a1a1a"/></svg>'

        group_svgs = {}
        for group, position_counts in entry.get('group_heatmaps', {}).items():
            group_colors = generate_colors_from_counts(position_counts)
            group_msg_count = len([p for p in position_counts if p > 0])
            if group_msg_count == 0:
                group_msg_count = 1
            group_svgs[group] = generate_svg_heatmap(group_colors, group_msg_count, max_length=max_length)
        entry['group_svgs'] = group_svgs

    # Sort other entries alphabetically by filename
    other_entries.sort(key=lambda x: x['filename'])

    # Combine: other files first (alphabetically sorted), then heatmap files (sorted by length)
    entries = other_entries + heatmap_entries

    # Generate HTML
    index_path = output_path / 'index.html'

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write("""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>NEET INTEL GitHub</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {
      --bg: #0f1220;
      --fg: #e6e6eb;
      --muted: #9aa0b4;
      --link: #7aa2ff;
      --hover: #a5b9ff;
      --border: #2a2f4a;
      --sakamichi: #b16cff;
    }

    body {
      margin: 0;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: var(--bg);
      color: var(--fg);
      line-height: 1.4;
    }

    main {
      max-width: 900px;
      padding: 2rem 1.5rem 3rem;
      margin: 0 auto;
    }

    h1 {
      font-size: 1.4rem;
      font-weight: 600;
      margin-bottom: 0.5rem;
    }

    .tabs {
      display: flex;
      justify-content: center;
      gap: 0;
      margin-bottom: 1.5rem;
      border-bottom: 1px solid var(--border);
    }

    .tab {
      padding: 0.5rem 1rem;
      background: transparent;
      color: var(--muted);
      border: none;
      border-bottom: 2px solid transparent;
      cursor: pointer;
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      font-size: 0.875rem;
      font-weight: 500;
      transition: all 0.15s;
    }

    .tab:hover {
      color: var(--hover);
    }

    .tab.active {
      color: var(--link);
      border-bottom-color: var(--link);
    }

    .tab-content {
      display: none;
    }

    .tab-content.active {
      display: block;
    }

    .wiki-intro, .youtube-intro, .heatmap-intro, .start-intro {
      max-width: 900px;
      margin: 0 auto 2rem;
      padding: 1rem;
      background: rgba(122, 162, 255, 0.05);
      border: 1px solid var(--border);
      border-radius: 6px;
      line-height: 1.6;
      color: var(--fg);
      font-size: 0.85rem;
    }

    .tab-content h2 {
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--fg);
      margin-bottom: 1rem;
      text-align: center;
    }

    .support-section {
      margin-top: 2rem;
    }

    .support-section:first-child {
      margin-top: 0;
    }

    .support-section h2 {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--muted);
      margin-bottom: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    .support-section .entry-left {
      display: grid;
      grid-template-columns: 180px 1fr;
      gap: 1rem;
      align-items: center;
    }

    .support-label {
      font-weight: 600;
      color: var(--fg);
      text-align: left;
    }

    .crypto-address {
      margin-left: -0.5rem;
    }

    .wiki-section {
      margin-top: 2rem;
    }

    .wiki-section:first-child {
      margin-top: 0;
    }

    .wiki-section h2 {
      font-size: 0.95rem;
      font-weight: 600;
      color: var(--muted);
      margin-bottom: 0.75rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
    }

    .start-section {
      margin-top: 1.5rem;
    }

    .start-section:first-of-type {
      margin-top: 0;
    }

    .start-section h2 {
      font-size: 0.85rem;
      font-weight: 600;
      color: var(--muted);
      margin: 0 0 0.4rem 0;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      text-align: left;
    }

    .start-section p {
      margin: 0;
      font-size: 0.9rem;
      line-height: 1.6;
      color: var(--fg);
    }

    .start-section a {
      color: var(--link);
      text-decoration: none;
    }

    .start-section a:hover {
      color: var(--hover);
      text-decoration: underline;
    }

    .start-section a.tab-jump {
      cursor: pointer;
      font-weight: 500;
    }

    .header-link {
      margin-bottom: 2rem;
    }

    .header-link a {
      color: var(--link);
      text-decoration: none;
    }

    .header-link a:hover {
      color: var(--hover);
      text-decoration: underline;
    }

    ul {
      list-style: none;
      padding: 0;
      margin: 0;
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
    }

    li + li {
      border-top: 1px solid var(--border);
    }

    .entry {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.65rem 0.85rem;
      gap: 1rem;
      transition: background 0.15s;
    }

    #youtube .entry {
      align-items: flex-start;
    }

    #youtube .entry-right {
      align-self: center;
    }

    .entry:hover {
      background: rgba(122, 162, 255, 0.08);
    }

    .entry.sakamichi-46:hover {
      background: rgba(177, 108, 255, 0.12);
    }

    .entry.sakamichi-46:hover .link {
      color: var(--sakamichi);
    }

    .entry-left {
      flex: 1;
      display: flex;
      align-items: center;
      gap: 1rem;
      min-width: 0;
    }

    #youtube .entry-left {
      display: flex;
      align-items: flex-start;
      gap: 1rem;
      line-height: 1.4;
    }

    .date-links {
      display: flex;
      flex-direction: column;
      gap: 0;
      min-width: 4rem;
    }

    #youtube .entry-left .link {
      display: block;
      flex-shrink: 0;
    }

    .date-gap {
      height: 0.5rem;
      background: transparent;
      pointer-events: none;
    }

    .timeline {
      display: flex;
      align-items: flex-end;
      height: 1rem;
      gap: 1px;
      flex: 1;
      min-width: 0;
      align-self: center;
      padding: 0;
      background: #000;
      border: 1px solid var(--border);
      border-radius: 4px;
      overflow: hidden;
    }

    .timeline-bar-container {
      flex: 1;
      min-width: 1px;
      display: flex;
      flex-direction: column-reverse;
      align-self: flex-end;
    }

    .timeline-bar.empty {
      flex: 1;
      min-width: 1px;
      background: #333;
      height: 2px !important;
      opacity: 0.2;
    }

    .timeline-segment {
      width: 100%;
      background: #666;
      opacity: 0.5;
      transition: all 0.15s;
    }

    .timeline-segment[data-group="1"] { background: #06b050; }
    .timeline-segment[data-group="2"] { background: #ed7d32; }
    .timeline-segment[data-group="3"] { background: #ffcc00; }
    .timeline-segment[data-group="4"] { background: #ff0467; }
    .timeline-segment[data-group="5"] { background: #9063cd; }
    .timeline-segment[data-group="unclassified"] { background: #555; }

    .timeline-segment.highlight {
      opacity: 1 !important;
    }

    .timeline-segment.dimmed {
      opacity: 0.25;
    }

    .link {
      flex: 0 0 auto;
      text-decoration: none;
      color: var(--link);
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.85rem;
      white-space: nowrap;
    }

    .entry:hover .link {
      color: var(--hover);
    }

    /* Fixed-width filename in heatmaps list so bars align regardless of digit count */
    #heatmaps .entry-left > .link {
      min-width: 30ch;
    }

    .heatmap-preview {
      flex: 1 1 auto;
      display: flex;
      align-items: center;
      min-width: 0;
    }

    .heatmap-preview svg {
      display: block;
      border: 1px solid var(--border);
      border-radius: 2px;
    }

    .entry-right {
      flex: 0 0 auto;
      display: flex;
      gap: 6px;
      align-items: center;
    }

    .group-indicator {
      width: 12px;
      height: 12px;
      border-radius: 50%;
      transition: opacity 0.15s;
    }

    .group-indicator.inactive {
      opacity: 0.15;
    }

    .group-indicator-1 { background-color: #06b050; }
    .group-indicator-2 { background-color: #ed7d32; }
    .group-indicator-3 { background-color: #ffcc00; }
    .group-indicator-4 { background-color: #ff0467; }
    .group-indicator-5 { background-color: #9063cd; }
    .group-indicator-unclassified { background-color: #555; }

    /* SKYMASTERs tab styles */
    .skymaster-list .entry {
      display: flex;
      align-items: center;
      gap: 1rem;
    }

    .sm-date {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #4ade80;
      white-space: nowrap;
      flex: 0 0 5.5rem;
    }

    .sm-event {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #4ade80;
      flex: 1;
    }

    .sm-day {
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      color: #ed7d32;
      font-style: italic;
      text-align: right;
      flex: 0 0 5rem;
    }

    /* Forecast list has wider date column */
    .skymaster-list.forecast .sm-date {
      flex: 0 0 12rem;
    }

    /* Subtabs for SKYMASTERs */
    .subtabs {
      display: flex;
      justify-content: center;
      gap: 0.5rem;
      margin-bottom: 1.25rem;
    }

    .subtab {
      padding: 0.4rem 1rem;
      background: transparent;
      color: var(--muted);
      border: 1px solid var(--border);
      border-radius: 4px;
      cursor: pointer;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.8rem;
      font-weight: 500;
      transition: all 0.15s;
    }

    .subtab:hover {
      color: var(--hover);
      border-color: var(--hover);
    }

    .subtab.active {
      color: #4ade80;
      border-color: #4ade80;
      background: rgba(74, 222, 128, 0.1);
    }

    .subtab-content {
      display: none;
    }

    .subtab-content.active {
      display: block;
    }

    /* Fakemaster styling - lighter green */
    .entry.fakemaster .sm-date,
    .entry.fakemaster .sm-event {
      color: #86efac;
    }

    /* Hover effects */
    .skymaster-list .entry.skymaster:hover {
      background: rgba(74, 222, 128, 0.12);
    }

    .skymaster-list .entry.fakemaster:hover {
      background: rgba(134, 239, 172, 0.12);
    }

    .forecast-header {
      font-size: 0.85rem;
      font-weight: 500;
      color: var(--muted);
      margin: 1rem 0 0.5rem 0;
      font-style: italic;
    }

    .skymaster-list.forecast {
      opacity: 0.85;
    }

    .skymaster-list.forecast .sm-date,
    .skymaster-list.forecast .sm-event {
      color: #86efac;
    }

    /* Compare table */
    .compare-table {
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      border: 1px solid var(--border);
      border-radius: 6px;
      overflow: hidden;
      font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
      font-size: 0.85rem;
    }

    .compare-table thead {
      background: rgba(122, 162, 255, 0.08);
    }

    .compare-table th {
      padding: 0.5rem 0.75rem;
      text-align: center;
      font-weight: 600;
      color: var(--muted);
      font-size: 0.8rem;
      border-bottom: 1px solid var(--border);
    }

    .compare-table td {
      padding: 0.4rem 0.5rem;
      text-align: center;
      border-bottom: 1px solid var(--border);
      color: #4ade80;
    }

    .compare-table td.fakemaster {
      color: #86efac;
    }

    .compare-table td:empty {
      background: rgba(0, 0, 0, 0.15);
    }

    .compare-table tr:last-child td {
      border-bottom: none;
    }

    .compare-table tr:hover td:not(:empty) {
      background: rgba(74, 222, 128, 0.12);
    }

    .compare-table tr:hover td.fakemaster {
      background: rgba(134, 239, 172, 0.12);
    }

    /* Mobile responsive styles */
    @media (max-width: 640px) {
      main {
        padding: 1rem 0.75rem 2rem;
      }

      h1 {
        font-size: 1.2rem;
      }

      .tabs {
        flex-wrap: wrap;
        gap: 0.25rem;
        border-bottom: none;
        margin-bottom: 1rem;
      }

      .tab {
        flex: 1 1 auto;
        min-width: calc(50% - 0.25rem);
        padding: 0.5rem 0.5rem;
        font-size: 0.75rem;
        text-align: center;
        border: 1px solid var(--border);
        border-radius: 4px;
        border-bottom: 1px solid var(--border);
      }

      .tab.active {
        border-color: var(--link);
        background: rgba(122, 162, 255, 0.1);
      }

      .wiki-intro, .youtube-intro, .heatmap-intro, .start-intro {
        padding: 0.75rem;
        font-size: 0.8rem;
        line-height: 1.5;
      }

      .entry {
        flex-direction: column;
        align-items: stretch;
        gap: 0.5rem;
        padding: 0.5rem 0.65rem;
      }

      .entry-left {
        flex-direction: column;
        align-items: stretch;
        gap: 0.5rem;
      }

      #youtube .entry-left {
        flex-direction: column;
        align-items: stretch;
      }

      .date-links {
        flex-direction: row;
        flex-wrap: wrap;
        gap: 0.5rem;
      }

      .link {
        font-size: 0.8rem;
        word-break: break-all;
      }

      .heatmap-preview {
        width: 100%;
        overflow-x: auto;
      }

      .heatmap-preview svg {
        max-width: 100%;
        height: auto;
      }

      .timeline {
        width: 100%;
        min-height: 1rem;
      }

      .entry-right {
        justify-content: flex-start;
        padding-top: 0.25rem;
      }

      .support-section .entry-left {
        grid-template-columns: 1fr;
        gap: 0.5rem;
      }

      .support-label {
        font-size: 0.85rem;
      }

      .crypto-address {
        margin-left: 0;
        font-size: 0.7rem;
        word-break: break-all;
        display: block;
      }

      .wiki-section h2,
      .support-section h2 {
        font-size: 0.85rem;
      }

      .tab-content h2 {
        font-size: 1rem;
      }

      .skymaster-list .entry {
        flex-direction: row;
        align-items: center;
        font-size: 0.75rem;
        gap: 0.5rem;
        padding: 0.4rem 0.65rem;
      }

      .sm-date {
        flex: 0 0 4rem;
      }

      .sm-day {
        flex: 0 0 3.5rem;
        font-size: 0.7rem;
      }

      .skymaster-list.forecast .sm-date {
        flex: 0 0 7rem;
      }

      .subtabs {
        gap: 0.35rem;
      }

      .subtab {
        padding: 0.35rem 0.75rem;
        font-size: 0.75rem;
      }

      .compare-table {
        font-size: 0.7rem;
      }

      .compare-table th,
      .compare-table td {
        padding: 0.35rem 0.25rem;
      }
    }

    @media (max-width: 400px) {
      .tab {
        min-width: 100%;
        font-size: 0.7rem;
      }

      .group-indicator {
        width: 10px;
        height: 10px;
      }

      .crypto-address {
        font-size: 0.65rem;
      }

      .skymaster-list .entry {
        flex-direction: row;
        font-size: 0.65rem;
        gap: 0.4rem;
        padding: 0.35rem 0.5rem;
      }

      .sm-date {
        flex: 0 0 3.5rem;
      }

      .sm-day {
        display: none;
      }

      .skymaster-list.forecast .sm-date {
        flex: 0 0 5.5rem;
      }

      .compare-table {
        font-size: 0.6rem;
      }

      .compare-table th,
      .compare-table td {
        padding: 0.3rem 0.2rem;
      }
    }
  </style>
</head>
<body>
  <main>
    <h1>NEET INTEL GitHub</h1>

    <div class="tabs">
      <button class="tab active" onclick="showTab('start')">Start Here</button>
      <button class="tab" onclick="showTab('heatmaps')">EAM Structure Analysis</button>
      <button class="tab" onclick="showTab('misc')">Miscellaneous</button>
      <button class="tab" onclick="showTab('skymasters')">SKYMASTERs</button>
      <button class="tab" onclick="showTab('youtube')">NEET INTEL YouTube</button>
      <button class="tab" onclick="showTab('wiki')">HFGCS Wiki</button>
      <button class="tab" onclick="showTab('support')">Contact and Support</button>
    </div>

    <div id="start" class="tab-content active">
      <p class="start-intro">NEET INTEL is a research project documenting the High Frequency Global Communications System (HFGCS) and the Emergency Action Messages (EAMs) broadcast on it. The HFGCS is a US Air Force shortwave network used to relay short, encoded messages to military forces. The transmissions are public — anyone with a shortwave receiver can hear them — but the messages themselves are deliberately opaque, and little has been published about how they are structured or how their patterns shift over time. This site collects the project's analyses, recordings, and reference material in one place.</p>

      <div class="start-section">
        <h2>If you are new to the HFGCS</h2>
        <p>Start with the <a href="hfgcs_faq.html" target="_blank">HFGCS FAQ</a> for a plain-language overview, then browse the <a class="tab-jump" href="#" onclick="showTab('wiki'); return false;">HFGCS Wiki</a> tab for additional information.</p>
      </div>

      <div class="start-section">
        <h2>If you came for EAM structure analysis</h2>
        <p>The <a class="tab-jump" href="#" onclick="showTab('heatmaps'); return false;">EAM Structure Analysis</a> tab groups EAMs by character length and highlights repeating segments across messages. The <a href="about_structure_heatmaps.html" target="_blank">"How to read these heatmaps"</a> page explains the visualization.</p>
      </div>

      <div class="start-section">
        <h2>If you came for the recordings</h2>
        <p>The <a class="tab-jump" href="#" onclick="showTab('youtube'); return false;">NEET INTEL YouTube</a> tab indexes every video in the DCRP (early daily compilations) and the DTCP (daily timecards with transcribed EAMs).</p>
      </div>

      <div class="start-section">
        <h2>If you are tracking SKYMASTERs</h2>
        <p>The <a class="tab-jump" href="#" onclick="showTab('skymasters'); return false;">SKYMASTER</a> tab catalogs SKYMASTER and FAKEMASTER events from 2023 onward, with 2026 forecasts and a year-over-year comparison.</p>
      </div>

      <div class="start-section">
        <h2>Everything else</h2>
        <p>The <a class="tab-jump" href="#" onclick="showTab('misc'); return false;">Miscellaneous</a> tab links to additional pages that do not fit cleanly under the categories above.</p>
      </div>

      <div class="start-section">
        <h2>Contact</h2>
        <p>The <a class="tab-jump" href="#" onclick="showTab('support'); return false;">Contact and Support</a> tab lists ways to reach NEET INTEL and to support the project. Tip: ← / → switches tabs from the keyboard.</p>
      </div>
    </div>

    <div id="heatmaps" class="tab-content">
      <div class="heatmap-intro">
        <p style="margin: 0 0 10px 0;">Emergency Action Messages are known to be highly structured. These pages group EAMs by character length and analyze them for repeating segments to identify candidate structural elements. Colored positions indicate possible pattern segments across messages. Click any colored position to highlight additional instances of that pattern.</p>
        <p style="margin: 0;"><strong>Note:</strong> If the browser is unable to display the entire text of messages, the display automatically switches from individual characters to an abstract timeline view where colored segments represent pattern positions. <i>(For desktop devices, try reducing the font size. For mobile devices, try turning your device to landscape mode to increase the vertical space.)</i></p>
        <p style="margin: 10px 0 0 0;"><a href="about_structure_heatmaps.html" style="color: #4a9eff;">How to read these heatmaps</a> <span style="color: #888; font-size: 0.85em;">(AI-generated)</span></p>
      </div>
      <ul>
""")

        # Write heatmap entries
        for entry in heatmap_entries:
            filename = entry['filename']
            length = entry['length']
            groups = entry['groups']
            group_svgs = entry.get('group_svgs', {})

            # Sakamichi for 46
            entry_class = 'entry sakamichi-46' if length == 46 else 'entry'

            heatmap_svg = entry['heatmap_svg']

            # Build data attributes for group SVGs
            group_data_attrs = []
            for group, svg in group_svgs.items():
                escaped_svg = html_module.escape(svg, quote=True)
                group_data_attrs.append(f'data-group-{group}-svg="{escaped_svg}"')

            group_data_str = ' '.join(group_data_attrs)

            # Generate group indicators (always show all 6)
            indicators = []
            for group_num in [1, 2, 3, 4, 5]:
                active_class = '' if group_num in groups else 'inactive'
                tooltip = f"Group {group_num}"
                indicators.append(f'<span class="group-indicator group-indicator-{group_num} {active_class}" data-group="{group_num}" title="{tooltip}"></span>')

            # Unclassified
            active_class = '' if 'unclassified' in groups else 'inactive'
            tooltip = "Unknown"
            indicators.append(f'<span class="group-indicator group-indicator-unclassified {active_class}" data-group="unclassified" title="{tooltip}"></span>')

            indicators_html = ''.join(indicators)

            f.write(f"""      <li>
        <div class="{entry_class}">
          <div class="entry-left">
            <a class="link" href="{filename}" target="_blank">{filename}</a>
            <div class="heatmap-preview" {group_data_str} data-original-svg="{html_module.escape(heatmap_svg, quote=True)}">{heatmap_svg}</div>
          </div>
          <div class="entry-right">
            {indicators_html}
          </div>
        </div>
      </li>
""")

        f.write("""      </ul>
    </div>

    <div id="skymasters" class="tab-content">
      <h2>SKYMASTER Events</h2>

      <div class="subtabs">
        <button class="subtab active" onclick="showSubtab('sky-2023')">2023</button>
        <button class="subtab" onclick="showSubtab('sky-2024')">2024</button>
        <button class="subtab" onclick="showSubtab('sky-2025')">2025</button>
        <button class="subtab" onclick="showSubtab('sky-2026')">2026</button>
        <button class="subtab" onclick="showSubtab('sky-compare')">Compare</button>
      </div>

      <div id="sky-2023" class="subtab-content active">
        <ul class="skymaster-list">
          <li><div class="entry skymaster"><span class="sm-date">230111</span><span class="sm-event">JANUARY SKYMASTER</span><span class="sm-day">2nd Wed</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">230201</span><span class="sm-event">FEBRUARY SKYMASTER</span><span class="sm-day">1st Wed</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">230416</span><span class="sm-event">GLOBAL THUNDER 23 SKYMASTER</span><span class="sm-day">3rd Sun</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">230421</span><span class="sm-event">GLOBAL THUNDER 23 SKYMASTER II[?]</span><span class="sm-day">3rd Fri</span></div></li>
          <li><div class="entry fakemaster"><span class="sm-date">230711</span><span class="sm-event">GLOBAL STORM 23 FAKEMASTER</span><span class="sm-day">2nd Tue</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">230830</span><span class="sm-event">AUGUST SKYMASTER</span><span class="sm-day">5th Wed</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">230927</span><span class="sm-event">SEPTEMBER SKYMASTER</span><span class="sm-day">4th Wed</span></div></li>
        </ul>
      </div>

      <div id="sky-2024" class="subtab-content">
        <ul class="skymaster-list">
          <li><div class="entry skymaster"><span class="sm-date">240111</span><span class="sm-event">JANUARY SKYMASTER</span><span class="sm-day">2nd Thu</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">240207</span><span class="sm-event">FAROE ISLANDS SKYMASTER</span><span class="sm-day">1st Wed</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">240412</span><span class="sm-event">APRIL SKYMASTER I (PRAIRIE VIGILANCE?)</span><span class="sm-day">2nd Fri</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">240418</span><span class="sm-event">APRIL SKYMASTER II</span><span class="sm-day">3rd Thu</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">240515</span><span class="sm-event">EAST COAST MINI-SKYMASTER</span><span class="sm-day">3rd Wed</span></div></li>
          <li><div class="entry fakemaster"><span class="sm-date">240623</span><span class="sm-event">NORWAY FAKEMASTER</span><span class="sm-day">4th Sun</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">240821</span><span class="sm-event">AUGUST SKYMASTER</span><span class="sm-day">3rd Wed</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">240925</span><span class="sm-event">SEPTEMBER SKYMASTER</span><span class="sm-day">4th Wed</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">241024</span><span class="sm-event">GLOBAL THUNDER 25 SKYMASTER</span><span class="sm-day">4th Thu</span></div></li>
        </ul>
      </div>

      <div id="sky-2025" class="subtab-content">
        <ul class="skymaster-list">
          <li><div class="entry skymaster"><span class="sm-date">250108</span><span class="sm-event">JANUARY SKYMASTER</span><span class="sm-day">2nd Wed</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">250416</span><span class="sm-event">APRIL SKYMASTER</span><span class="sm-day">3rd Wed</span></div></li>
          <li><div class="entry fakemaster"><span class="sm-date">250430</span><span class="sm-event">APRIL NOTHINGMASTER</span><span class="sm-day">5th Wed</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">250528</span><span class="sm-event">MAY MINI-SKYMASTER</span><span class="sm-day">4th Wed</span></div></li>
          <li><div class="entry fakemaster"><span class="sm-date">250706</span><span class="sm-event">LAJES FAKEMASTER</span><span class="sm-day">1st Sun</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">250820</span><span class="sm-event">GREENLAND SKYMASTER</span><span class="sm-day">3rd Wed</span></div></li>
          <li><div class="entry fakemaster"><span class="sm-date">250822</span><span class="sm-event">GREENLAND FAKEMASTER</span><span class="sm-day">4th Fri</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">250924</span><span class="sm-event">FAROE ISLANDS SKYMASTER</span><span class="sm-day">4th Fri</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">251026</span><span class="sm-event">GLOBAL THUNDER 26 SKYMASTER I</span><span class="sm-day">4th Sun</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">251029</span><span class="sm-event">GLOBAL THUNDER 26 SKYMASTER II</span><span class="sm-day">5th Wed</span></div></li>
        </ul>
      </div>

      <div id="sky-2026" class="subtab-content">
        <ul class="skymaster-list">
          <li><div class="entry skymaster"><span class="sm-date">260114</span><span class="sm-event">JANUARY SKYMASTER</span><span class="sm-day">2nd Wed</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">260211</span><span class="sm-event">FEBRUARY SKYMASTER</span><span class="sm-day">2nd Wed</span></div></li>
          <li><div class="entry fakemaster"><span class="sm-date">260421</span><span class="sm-event">APRIL NOTHINGMASTER</span><span class="sm-day">3rd Tue</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">260430</span><span class="sm-event">APRIL SKYMASTER</span><span class="sm-day">5th Thu</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">260513</span><span class="sm-event">FAROE ISLANDS SKYMASTER</span><span class="sm-day">2nd Wed</span></div></li>
        </ul>
        <h4 class="forecast-header">Forecasts</h4>
        <ul class="skymaster-list forecast">
          <li><div class="entry skymaster"><span class="sm-date">260622 ~ 260628</span><span class="sm-event">GLOBAL STORM 26[?] {not SKYMASTER but still..}</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">260819 / 260827</span><span class="sm-event">August SKYMASTER</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">260923 / 260930</span><span class="sm-event">September SKYMASTER</span></div></li>
          <li><div class="entry skymaster"><span class="sm-date">2610## - 2611##</span><span class="sm-event">GLOBAL THUNDER 27 SKYMASTER</span></div></li>
        </ul>
      </div>

      <div id="sky-compare" class="subtab-content">
        <table class="compare-table">
          <thead>
            <tr>
              <th>2023</th>
              <th>2024</th>
              <th>2025</th>
              <th>2026</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="sm-date">230111</td>
              <td class="sm-date">240111</td>
              <td class="sm-date">250108</td>
              <td class="sm-date">260114</td>
            </tr>
            <tr>
              <td class="sm-date">230201</td>
              <td class="sm-date">240207</td>
              <td></td>
              <td class="sm-date">260211</td>
            </tr>
            <tr>
              <td class="sm-date">230416</td>
              <td class="sm-date">240412</td>
              <td class="sm-date">250416</td>
              <td class="sm-date fakemaster">260421</td>
            </tr>
            <tr>
              <td class="sm-date">230421</td>
              <td class="sm-date">240418</td>
              <td class="sm-date fakemaster">250430</td>
              <td class="sm-date">260430</td>
            </tr>
            <tr>
              <td></td>
              <td class="sm-date">240515</td>
              <td class="sm-date">250528</td>
              <td class="sm-date">260513</td>
            </tr>
            <tr>
              <td class="sm-date fakemaster">230711</td>
              <td class="sm-date fakemaster">240623</td>
              <td class="sm-date fakemaster">250706</td>
              <td></td>
            </tr>
            <tr>
              <td class="sm-date">230830</td>
              <td class="sm-date">240821</td>
              <td class="sm-date">250820</td>
              <td></td>
            </tr>
            <tr>
              <td></td>
              <td></td>
              <td class="sm-date fakemaster">250822</td>
              <td></td>
            </tr>
            <tr>
              <td class="sm-date">230927</td>
              <td class="sm-date">240925</td>
              <td class="sm-date">250924</td>
              <td></td>
            </tr>
            <tr>
              <td></td>
              <td class="sm-date">241024</td>
              <td class="sm-date">251026</td>
              <td></td>
            </tr>
            <tr>
              <td></td>
              <td></td>
              <td class="sm-date">251029</td>
              <td></td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <div id="misc" class="tab-content">
      <ul>
""")

        # Write misc (other) entries
        for entry in other_entries:
            filename = entry['filename']
            # Sakamichi easter egg: extend to any file whose name contains
            # "46char" (covers both structure_heatmap_46char.html and
            # eam_46char_format_analysis.html).
            entry_class = 'entry sakamichi-46' if '46char' in filename else 'entry'
            f.write(f"""      <li>
        <div class="{entry_class}">
          <div class="entry-left">
            <a class="link" href="{filename}" target="_blank">{filename}</a>
          </div>
        </div>
      </li>
""")

        f.write("""      </ul>
    </div>
""")

        # Helper to write YouTube entries as a <ul> list
        def write_youtube_entries(f, yt_entries):
            if not yt_entries:
                f.write("""      <p>Playlist data not available. Run yt-dlp to generate playlist data.</p>
""")
                return

            grouped_entries = defaultdict(list)
            for entry in yt_entries:
                grouped_entries[entry['base_date']].append(entry)

            sorted_base_dates = sorted(grouped_entries.keys())

            f.write("""      <ul>
""")

            prev_date = None
            for base_date in sorted_base_dates:
                if prev_date and not are_dates_consecutive(prev_date, base_date):
                    f.write("""      <li class="date-gap"></li>
""")
                prev_date = base_date
                entries = grouped_entries[base_date]

                groups = entries[0]['groups']
                group_prefixes = entries[0]['group_prefixes']

                indicators = []
                for group_num in [1, 2, 3, 4, 5]:
                    active_class = '' if group_num in groups else 'inactive'
                    if group_num in groups and group_num in group_prefixes:
                        prefixes_str = ', '.join(sorted(group_prefixes[group_num]))
                        tooltip = prefixes_str
                    else:
                        tooltip = f"Group {group_num}"
                    indicators.append(f'<span class="group-indicator group-indicator-{group_num} {active_class}" data-group="{group_num}" title="{tooltip}"></span>')

                active_class = '' if 'unclassified' in groups else 'inactive'
                if 'unclassified' in groups and 'unclassified' in group_prefixes:
                    prefixes_str = ', '.join(sorted(group_prefixes['unclassified']))
                    tooltip = prefixes_str
                else:
                    tooltip = "Unknown"
                indicators.append(f'<span class="group-indicator group-indicator-unclassified {active_class}" data-group="unclassified" title="{tooltip}"></span>')

                indicators_html = ''.join(indicators)

                links_html = '<div class="date-links">'
                for i, entry in enumerate(entries):
                    if len(entries) > 1:
                        suffix = chr(65 + i)
                        display_date = f'{base_date}{suffix}'
                    else:
                        display_date = entry["date"]
                    links_html += f'<a class="link" href="{entry["url"]}" target="_blank">{display_date}</a>\n              '
                links_html += '</div>'

                period_counts = entries[0].get('period_counts', [0] * 72)
                period_groups = entries[0].get('period_groups', [set() for _ in range(72)])
                period_group_counts = entries[0].get('period_group_counts', [{} for _ in range(72)])
                max_count = max(period_counts) if period_counts else 1

                group_order = [1, 2, 3, 4, 5, 'unclassified']

                timeline_html = '<div class="timeline">'
                for period in range(72):
                    count = period_counts[period]
                    groups_in_period = period_groups[period] if period < len(period_groups) else set()
                    group_counts_in_period = period_group_counts[period] if period < len(period_group_counts) else {}

                    if count > 0:
                        overall_height_pct = min(100, (count / max_count) * 100) if max_count > 0 else 0
                        timeline_html += f'<span class="timeline-bar-container" style="height: {overall_height_pct}%;">'

                        for group in group_order:
                            if group in groups_in_period:
                                group_count = group_counts_in_period.get(group, 0)
                                segment_pct = (group_count / count) * 100 if count > 0 else 0
                                timeline_html += f'<span class="timeline-segment" data-group="{group}" style="height: {segment_pct}%;"></span>'

                        timeline_html += '</span>'
                    else:
                        timeline_html += '<span class="timeline-bar empty"></span>'
                timeline_html += '</div>'

                f.write(f"""      <li>
        <div class="entry">
          <div class="entry-left">
            {links_html}
            {timeline_html}
          </div>
          <div class="entry-right">
            {indicators_html}
          </div>
        </div>
      </li>
""")

            f.write("""      </ul>
""")

        f.write("""
    <div id="youtube" class="tab-content">
      <div class="subtabs">
        <button class="subtab active" onclick="showSubtab('yt-dcrp')">DCRP</button>
        <button class="subtab" onclick="showSubtab('yt-dtcp')">DTCP</button>
      </div>

      <div id="yt-dcrp" class="subtab-content active">
        <h2>HFGCS EAM DAILY COMPILATION RECORDINGS PROJECT</h2>
        <p class="youtube-intro">The HFGCS EAM DAILY COMPILATION RECORDINGS PROJECT (DCRP) is the first attempt by NEET INTEL to collect recordings of EAMs broadcast on the HFGCS and share them with a wider audience. Unlike the later NEET INTEL DAILY TIMECARD PROJECT (DTCP), this series does not necessarily reflect comprehensive 24/7 HFGCS monitoring, and many of the videos represent a “whatever I happened to hear that day” effort, though the series does become more ambitious by its end (setting up for the more ambitious DTCP). Originally 100+1 videos (owing to 23022 being split into two parts), an additional 7 videos (after the series concluded) that are functionally similar have been classified as part of this project.</p>
""")

        write_youtube_entries(f, dcrp_entries)

        f.write("""      </div>

      <div id="yt-dtcp" class="subtab-content">
        <h2>NEET INTEL DAILY TIMECARD PROJECT</h2>
        <p class="youtube-intro">The NEET INTEL DAILY TIMECARD PROJECT (DTCP) is the successor to the HFGCS EAM DAILY COMPILATION RECORDINGS PROJECT. The project generates daily timecards of transcribed Emergency Action Messages (EAMs) and/or Force Direction Messages (FDMs) broadcast by the US military over the High Frequency Global Communications System (HFGCS), paired with jpop, kpop, and occasionally cpop. Part 1 is comprehensive, starting 230623 and ending 240201, representing a 7-month period of continuous and near-comprehensive HFGCS coverage. The remainder of the project covers mostly non-consecutive dates, with several shorter periods of continuous coverage included.</p>
""")

        write_youtube_entries(f, dtcp_entries)

        f.write("""      </div>
""")

        f.write("""    </div>

    <div id="wiki" class="tab-content">
      <p class="wiki-intro">An HFGCS Wiki is a proposed project by NEET INTEL to provide a centralized repository of information about the HFGCS and EAMs. The scale of a project is too ambitious for a single person, but NEET INTEL initiated a pilot project in December 2025 to demonstrate what it could look like. Below are some examples of the Wiki's pages as saved by archive.org.</p>

      <div class="wiki-section">
        <h2>Informational</h2>
        <ul>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214235556/https://wiki.hfgcs.com/index.php?title=Directed_EAM&curid=100&oldid=2026" target="_blank">https://wiki.hfgcs.com/wiki/Directed_EAM</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251216192330/https://wiki.hfgcs.com/wiki/Emergency_Action_Message" target="_blank">https://wiki.hfgcs.com/wiki/Emergency_Action_Message</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251216164002/https://wiki.hfgcs.com/wiki/Grand_Forks_Air_Force_Base" target="_blank">https://wiki.hfgcs.com/wiki/Grand_Forks_Air_Force_Base</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215090356/https://wiki.hfgcs.com/wiki/HFGCS" target="_blank">https://wiki.hfgcs.com/wiki/HFGCS</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215122754/https://wiki.hfgcs.com/wiki/List_of_Radio_Frequencies" target="_blank">https://wiki.hfgcs.com/wiki/List_of_Radio_Frequencies</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214154655/https://wiki.hfgcs.com/wiki/NEET_INTEL_DAILY_TIMECARD_PROJECT" target="_blank">https://wiki.hfgcs.com/wiki/NEET_INTEL_DAILY_TIMECARD_PROJECT</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214202921/https://wiki.hfgcs.com/wiki/Nothing_ever_happens" target="_blank">https://wiki.hfgcs.com/wiki/Nothing_ever_happens</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215142658/https://wiki.hfgcs.com/wiki/SCW-1" target="_blank">https://wiki.hfgcs.com/wiki/SCW-1</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214034417/https://wiki.hfgcs.com/wiki/Utah_Test_and_Training_Range" target="_blank">https://wiki.hfgcs.com/wiki/Utah_Test_and_Training_Range</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215001054/https://wiki.hfgcs.com/wiki/Special:Version" target="_blank">https://wiki.hfgcs.com/wiki/Special:Version</a>
              </div>
            </div>
          </li>
        </ul>
      </div>

      <div class="wiki-section">
        <h2>YYMMDD Pages</h2>
        <ul>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214122348/https://wiki.hfgcs.com/wiki/Auxiliary:YYMMDD_Infobox_Usage_List" target="_blank">https://wiki.hfgcs.com/wiki/Auxiliary:YYMMDD_Infobox_Usage_List</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215154052/https://wiki.hfgcs.com/wiki/Tentative:220128" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220128</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251216235157/https://wiki.hfgcs.com/wiki/Tentative:220129" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220129</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215115456/https://wiki.hfgcs.com/wiki/Tentative:220130" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220130</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215172713/https://wiki.hfgcs.com/wiki/Tentative:220214" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220214</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214150051/https://wiki.hfgcs.com/wiki/Tentative:220215" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220215</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214135952/https://wiki.hfgcs.com/wiki/Tentative:220217" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220217</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214190503/https://wiki.hfgcs.com/wiki/Tentative:220222" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220222</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214192727/https://wiki.hfgcs.com/wiki/Tentative:220225" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220225</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214044815/https://wiki.hfgcs.com/wiki/Tentative:220301" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220301</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214135833/https://wiki.hfgcs.com/wiki/Tentative:220303" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220303</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215070445/https://wiki.hfgcs.com/wiki/Tentative:220305" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:220305</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214041611/https://wiki.hfgcs.com/wiki/251029" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:251029</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215011639/https://wiki.hfgcs.com/wiki/Tentative:251130" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:251130</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215163719/https://wiki.hfgcs.com/wiki/Tentative:251202" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:251202</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251214031338/https://wiki.hfgcs.com/wiki/Tentative:251209" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:251209</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <a class="link" href="https://web.archive.org/web/20251215110924/https://wiki.hfgcs.com/wiki/Tentative:251210" target="_blank">https://wiki.hfgcs.com/wiki/Tentative:251210</a>
              </div>
            </div>
          </li>
        </ul>
      </div>
    </div>

    <div id="support" class="tab-content">
      <div class="support-section">
        <h2>Contact</h2>
        <ul>
          <li>
            <div class="entry">
              <div class="entry-left">
                <span class="support-label">Email</span>
                <button id="reveal-email" onclick="revealEmail()" style="cursor: pointer; background: rgba(0, 0, 0, 0.3); border: 1px solid var(--border); padding: 0.25rem 0.75rem; border-radius: 4px; color: var(--link); font-size: 0.85rem;">Click to reveal</button>
                <div id="email-container"></div>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <span class="support-label">Signal</span>
                <span style="color: var(--fg);">Email or contact on X to request Signal address</span>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <span class="support-label">Substack</span>
                <a class="link" href="https://neetintel.substack.com/" target="_blank">https://neetintel.substack.com/</a>
              </div>
            </div>
          </li>
        </ul>
      </div>

      <div class="support-section">
        <h2>Support</h2>
        <ul>
          <li>
            <div class="entry">
              <div class="entry-left">
                <span class="support-label">Ko-Fi</span>
                <a class="link" href="https://www.ko-fi.com/neetintel" target="_blank">https://www.ko-fi.com/neetintel</a>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <span class="support-label">Bitcoin</span>
                <code class="crypto-address" onclick="copyToClipboard('bc1qhvq27kay730wk634ur8yp0ngftf0kgplxa6y3p', this)" style="cursor: pointer; background: rgba(0, 0, 0, 0.3); padding: 0.25rem 0.5rem; border-radius: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.85rem; color: var(--link);">bc1qhvq27kay730wk634ur8yp0ngftf0kgplxa6y3p</code>
              </div>
            </div>
          </li>
          <li>
            <div class="entry">
              <div class="entry-left">
                <span class="support-label">Ethereum</span>
                <code class="crypto-address" onclick="copyToClipboard('0x40fCF87C9289B1157CAaB6d1c22dE45baA70B3D8', this)" style="cursor: pointer; background: rgba(0, 0, 0, 0.3); padding: 0.25rem 0.5rem; border-radius: 4px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size: 0.85rem; color: var(--link);">0x40fCF87C9289B1157CAaB6d1c22dE45baA70B3D8</code>
              </div>
            </div>
          </li>
        </ul>
      </div>
    </div>
  </main>

  <script>
    // Handle URL parameters for direct tab navigation
    (function() {
      const params = new URLSearchParams(window.location.search);
      const tabMap = {
        'heatmap': 'heatmaps',
        'heatmaps': 'heatmaps',
        'skymaster': 'skymasters',
        'skymasters': 'skymasters',
        'misc': 'misc',
        'youtube': 'youtube',
        'wiki': 'wiki',
        'contact': 'support',
        'support': 'support'
      };

      const subtabMap = {
        '2023': 'sky-2023',
        '2024': 'sky-2024',
        '2025': 'sky-2025',
        '2026': 'sky-2026',
        'compare': 'sky-compare',
        'dcrp': 'yt-dcrp',
        'dtcp': 'yt-dtcp'
      };

      let targetTab = null;
      let targetSubtab = null;

      for (const key of params.keys()) {
        const lowerKey = key.toLowerCase();
        if (tabMap[lowerKey]) {
          targetTab = tabMap[lowerKey];
        }
        if (subtabMap[lowerKey]) {
          targetSubtab = subtabMap[lowerKey];
          // Infer parent tab from subtab prefix if not already set
          if (!targetTab) {
            targetTab = targetSubtab.startsWith('yt-') ? 'youtube' : 'skymasters';
          }
        }
      }

      if (targetTab) {
        document.addEventListener('DOMContentLoaded', function() {
          // Hide all tab contents
          document.querySelectorAll('.tab-content').forEach(content => {
            content.classList.remove('active');
          });

          // Remove active class from all tabs
          document.querySelectorAll('.tab').forEach(tab => {
            tab.classList.remove('active');
          });

          // Show selected tab content
          document.getElementById(targetTab).classList.add('active');

          // Activate corresponding tab button
          document.querySelectorAll('.tab').forEach(tab => {
            if (tab.getAttribute('onclick') && tab.getAttribute('onclick').includes(targetTab)) {
              tab.classList.add('active');
            }
          });

          // Handle subtab if specified
          if (targetSubtab) {
            const parentTab = document.getElementById(targetTab);
            if (parentTab) {
              // Hide all subtab contents within this parent
              parentTab.querySelectorAll('.subtab-content').forEach(content => {
                content.classList.remove('active');
              });

              // Remove active class from all subtabs within this parent
              parentTab.querySelectorAll('.subtab').forEach(subtab => {
                subtab.classList.remove('active');
              });

              // Show selected subtab content
              const subtabContent = document.getElementById(targetSubtab);
              if (subtabContent) {
                subtabContent.classList.add('active');
              }

              // Activate corresponding subtab button
              parentTab.querySelectorAll('.subtab').forEach(subtab => {
                if (subtab.getAttribute('onclick') && subtab.getAttribute('onclick').includes(targetSubtab)) {
                  subtab.classList.add('active');
                }
              });
            }
          }
        });
      }
    })();

    // Reveal email as CAPTCHA-style canvas image (anti-OCR)
    function revealEmail() {
      const parts = ['02', '_', '0279', String.fromCharCode(64), 'proton', String.fromCharCode(46), 'me'];
      const email = parts.join('');

      const canvas = document.createElement('canvas');
      const ctx = canvas.getContext('2d');

      // Set canvas size
      ctx.font = '14px system-ui, sans-serif';
      const metrics = ctx.measureText(email);
      canvas.width = metrics.width + 20;
      canvas.height = 28;

      // Get text color from CSS variable
      const textColor = getComputedStyle(document.documentElement).getPropertyValue('--text').trim() || '#e0e0e0';
      const rgb = textColor.match(/\\d+/g) || [224, 224, 224];

      // Add background noise pattern (snow-like)
      for (let i = 0; i < 150; i++) {
        const x = Math.random() * canvas.width;
        const y = Math.random() * canvas.height;
        const size = Math.random() * 1.5;
        const alpha = Math.random() * 0.3;
        ctx.fillStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${alpha})`;
        ctx.fillRect(x, y, size, size);
      }

      // Draw random wavy lines through text area
      ctx.lineWidth = 0.8;
      for (let i = 0; i < 3; i++) {
        ctx.beginPath();
        ctx.strokeStyle = `rgba(${rgb[0]},${rgb[1]},${rgb[2]},${0.2 + Math.random() * 0.15})`;
        const startY = Math.random() * canvas.height;
        ctx.moveTo(0, startY);

        for (let x = 0; x < canvas.width; x += 5) {
          const y = startY + Math.sin(x / 8 + i * 2) * 4;
          ctx.lineTo(x, y);
        }
        ctx.stroke();
      }

      // Draw each character with slight rotation and position variation
      ctx.font = '14px system-ui, sans-serif';
      ctx.textBaseline = 'middle';

      let xPos = 4;
      for (let i = 0; i < email.length; i++) {
        const char = email[i];
        const charMetrics = ctx.measureText(char);

        ctx.save();

        // Random rotation (-8 to +8 degrees)
        const rotation = (Math.random() - 0.5) * 0.28;
        const yOffset = (Math.random() - 0.5) * 2;

        ctx.translate(xPos + charMetrics.width / 2, 14 + yOffset);
        ctx.rotate(rotation);

        // Slight color variation per character
        const colorVar = Math.floor((Math.random() - 0.5) * 30);
        const r = Math.min(255, Math.max(0, parseInt(rgb[0]) + colorVar));
        const g = Math.min(255, Math.max(0, parseInt(rgb[1]) + colorVar));
        const b = Math.min(255, Math.max(0, parseInt(rgb[2]) + colorVar));

        // Draw faint shadow
        ctx.globalAlpha = 0.3;
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fillText(char, -charMetrics.width / 2 + 0.5, 0.5);

        // Draw main character
        ctx.globalAlpha = 0.95;
        ctx.fillStyle = `rgb(${r},${g},${b})`;
        ctx.fillText(char, -charMetrics.width / 2, 0);

        ctx.restore();

        xPos += charMetrics.width;
      }

      // Add aggressive pixel noise
      const imageData = ctx.getImageData(0, 0, canvas.width, canvas.height);
      const data = imageData.data;

      for (let i = 0; i < data.length; i += 4) {
        if (Math.random() < 0.12) {  // 12% of pixels
          const noise = Math.random() * 50 - 25;
          data[i] = Math.min(255, Math.max(0, data[i] + noise));
          data[i + 1] = Math.min(255, Math.max(0, data[i + 1] + noise));
          data[i + 2] = Math.min(255, Math.max(0, data[i + 2] + noise));
        }
      }

      ctx.putImageData(imageData, 0, 0);

      // Convert to image
      const img = document.createElement('img');
      img.src = canvas.toDataURL();
      img.style.verticalAlign = 'middle';

      document.getElementById('email-container').appendChild(img);
      document.getElementById('reveal-email').style.display = 'none';
    }

    // Copy to clipboard functionality
    function copyToClipboard(text, element) {
      navigator.clipboard.writeText(text).then(function() {
        // Visual feedback
        const originalText = element.textContent;
        element.textContent = 'Copied!';
        element.style.color = '#00ff00';

        setTimeout(function() {
          element.textContent = originalText;
          element.style.color = '';
        }, 1500);
      }).catch(function(err) {
        console.error('Failed to copy: ', err);
      });
    }

    // Tab switching functionality
    function showTab(tabName) {
      // Hide all tab contents
      document.querySelectorAll('.tab-content').forEach(content => {
        content.classList.remove('active');
      });

      // Remove active class from all tabs
      document.querySelectorAll('.tab').forEach(tab => {
        tab.classList.remove('active');
      });

      // Show selected tab content
      document.getElementById(tabName).classList.add('active');

      // Activate the corresponding tab button
      const tabButtons = document.querySelectorAll('.tab');
      tabButtons.forEach(tab => {
        if (tab.getAttribute('onclick').includes(tabName)) {
          tab.classList.add('active');
        }
      });
    }

    // Keyboard navigation for tabs
    const tabOrder = ['start', 'heatmaps', 'misc', 'skymasters', 'youtube', 'wiki', 'support'];

    document.addEventListener('keydown', function(e) {
      if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
        // Find currently active tab
        const activeContent = document.querySelector('.tab-content.active');
        if (!activeContent) return;

        const currentTab = activeContent.id;
        const currentIndex = tabOrder.indexOf(currentTab);

        if (currentIndex === -1) return;

        const delta = e.key === 'ArrowLeft' ? -1 : 1;
        const newIndex = (currentIndex + delta + tabOrder.length) % tabOrder.length;

        showTab(tabOrder[newIndex]);
        e.preventDefault();
      }

      if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
        const activeContent = document.querySelector('.tab-content.active');
        if (!activeContent) return;
        if (activeContent.id !== 'skymasters' && activeContent.id !== 'youtube') return;

        const subtabs = Array.from(activeContent.querySelectorAll('.subtab'));
        if (subtabs.length === 0) return;

        const currentIndex = subtabs.findIndex(s => s.classList.contains('active'));
        if (currentIndex === -1) return;

        const delta = e.key === 'ArrowUp' ? -1 : 1;
        const newIndex = (currentIndex + delta + subtabs.length) % subtabs.length;

        subtabs[newIndex].click();
        e.preventDefault();
      }
    });

    // Subtab switching functionality
    function showSubtab(subtabName) {
      // Find the parent tab content
      const parentTab = event.target.closest('.tab-content');

      // Hide all subtab contents within this parent
      parentTab.querySelectorAll('.subtab-content').forEach(content => {
        content.classList.remove('active');
      });

      // Remove active class from all subtabs within this parent
      parentTab.querySelectorAll('.subtab').forEach(subtab => {
        subtab.classList.remove('active');
      });

      // Show selected subtab content
      document.getElementById(subtabName).classList.add('active');

      // Activate clicked subtab button
      event.target.classList.add('active');
    }

    // Hover functionality for group indicators
    document.querySelectorAll('.group-indicator').forEach(indicator => {
      indicator.addEventListener('mouseenter', function() {
        const group = this.getAttribute('data-group');
        const preview = this.closest('.entry').querySelector('.heatmap-preview');

        if (!preview) return;

        // Get the SVG for this group
        const groupSvg = preview.getAttribute(`data-group-${group}-svg`);

        if (groupSvg) {
          // Replace the preview content with the group-specific heatmap
          preview.innerHTML = groupSvg;
        }
      });

      indicator.addEventListener('mouseleave', function() {
        const preview = this.closest('.entry').querySelector('.heatmap-preview');

        if (!preview) return;

        // Restore the original combined heatmap
        const originalSvg = preview.getAttribute('data-original-svg');

        if (originalSvg) {
          preview.innerHTML = originalSvg;
        }
      });
    });

    // Timeline highlighting on group hover
    const groupColors = {
      '1': '#06b050',
      '2': '#ed7d32',
      '3': '#ffcc00',
      '4': '#ff0467',
      '5': '#9063cd',
      'unclassified': '#fff'  // White for better contrast against grey default
    };

    document.querySelectorAll('.group-indicator').forEach(indicator => {
      indicator.addEventListener('mouseenter', function() {
        const groupNum = this.getAttribute('data-group');
        if (!groupNum || this.classList.contains('inactive')) return;

        // Get the color for this group
        const groupColor = groupColors[groupNum];

        // For each entry in the YouTube tab
        const entry = this.closest('.entry');
        if (!entry) return;

        const timelineSegments = entry.querySelectorAll('.timeline-segment');
        timelineSegments.forEach(segment => {
          const segmentGroup = segment.getAttribute('data-group');
          if (segmentGroup === groupNum) {
            segment.classList.add('highlight');
            segment.style.background = groupColor;
          } else {
            segment.classList.add('dimmed');
          }
        });
      });

      indicator.addEventListener('mouseleave', function() {
        const entry = this.closest('.entry');
        if (!entry) return;

        const timelineSegments = entry.querySelectorAll('.timeline-segment');
        timelineSegments.forEach(segment => {
          segment.classList.remove('highlight', 'dimmed');
          segment.style.background = '';
        });
      });
    });

  </script>
</body>
</html>
""")

    print(f"\n✓ Generated index with {len(entries)} entries")
    print(f"  Saved to: {index_path}")
    return index_path


def main():
    """Main execution function for standalone use."""
    print("EAM GitHub Index Generator")
    print("=" * 70)
    print()

    # Determine output directory
    if len(sys.argv) > 1:
        output_dir = sys.argv[1]
    else:
        # Default to output/ in the same directory as this script
        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')

    if not os.path.exists(output_dir):
        print(f"Error: Output directory does not exist: {output_dir}")
        print("Usage: python eam_github_index_.py [output_directory]")
        sys.exit(1)

    print(f"Scanning directory: {output_dir}")
    print()

    generate_index(output_dir)

    print()
    print("Done!")


if __name__ == '__main__':
    main()
