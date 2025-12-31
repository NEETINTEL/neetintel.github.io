"""
Generate index.html with heatmap previews for each page.
"""

import os
import re
from pathlib import Path

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

def main():
    output_dir = Path(__file__).parent / 'output'

    # Find all HTML files in the output directory
    all_html_files = list(output_dir.glob('*.html'))

    # Separate heatmap files from other HTML files
    heatmap_entries = []
    other_entries = []

    for html_file in all_html_files:
        # Skip group-filtered files and index.html itself
        if '-gr' in html_file.name or html_file.name == 'index.html':
            continue

        # Check if it's a structure_heatmap file
        match = re.search(r'structure_heatmap_(\d+)char\.html', html_file.name)
        if match:
            # It's a heatmap file - extract full data
            length = int(match.group(1))
            colors = extract_heatmap_colors(html_file)
            groups = extract_groups(html_file)
            num_messages = extract_message_count(html_file)

            heatmap_entries.append({
                'type': 'heatmap',
                'length': length,
                'filename': html_file.name,
                'colors': colors,
                'groups': groups,
                'num_messages': num_messages
            })
        else:
            # It's another HTML file - just add the filename
            other_entries.append({
                'type': 'other',
                'filename': html_file.name
            })

    # Sort heatmap entries by length
    heatmap_entries.sort(key=lambda x: x['length'])

    # Combine: other files first (unsorted), then heatmap files (sorted by length)
    entries = other_entries + heatmap_entries

    # Generate HTML
    index_path = output_dir / 'index.html'

    with open(index_path, 'w', encoding='utf-8') as f:
        f.write("""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>EAM Structure Heatmaps</title>
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
      margin-bottom: 0.25rem;
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
  </style>
</head>
<body>
  <main>
    <h1>EAM Structure Heatmaps</h1>

    <ul>
""")

        # Write entries
        for entry in entries:
            filename = entry['filename']
            entry_type = entry['type']

            if entry_type == 'other':
                # Simple row for non-heatmap files - just the filename link
                f.write(f"""      <li>
        <div class="entry">
          <div class="entry-left">
            <a class="link" href="{filename}">{filename}</a>
          </div>
        </div>
      </li>
""")
            else:
                # Full heatmap row with preview and group indicators
                length = entry['length']
                colors = entry['colors']
                groups = entry['groups']
                num_messages = entry['num_messages']

                # Sakamichi for 46
                entry_class = 'entry sakamichi-46' if length == 46 else 'entry'

                # Generate heatmap preview
                if colors and num_messages > 0:
                    heatmap_svg = generate_svg_heatmap(colors, num_messages)
                else:
                    heatmap_svg = '<svg width="100" height="12"><rect width="100" height="12" fill="#1a1a1a"/></svg>'

                # Generate group indicators (always show all 6)
                indicators = []
                for group_num in [1, 2, 3, 4, 5]:
                    active_class = '' if group_num in groups else 'inactive'
                    indicators.append(f'<span class="group-indicator group-indicator-{group_num} {active_class}" title="Group {group_num}"></span>')

                # Unclassified
                active_class = '' if 'unclassified' in groups else 'inactive'
                indicators.append(f'<span class="group-indicator group-indicator-unclassified {active_class}" title="Unclassified"></span>')

                indicators_html = ''.join(indicators)

                f.write(f"""      <li>
        <div class="{entry_class}">
          <div class="entry-left">
            <a class="link" href="{filename}">{filename}</a>
            <div class="heatmap-preview">{heatmap_svg}</div>
          </div>
          <div class="entry-right">
            {indicators_html}
          </div>
        </div>
      </li>
""")

        f.write("""    </ul>
  </main>
</body>
</html>
""")

    print(f"✓ Generated index with {len(entries)} entries")
    print(f"  Saved to: {index_path}")

def generate_svg_heatmap(colors, num_messages, height=12):
    """Generate inline SVG representation of heatmap with width proportional to message length and normalized colors."""
    if not colors:
        return '<svg width="100" height="12"><rect width="100" height="12" fill="#1a1a1a"/></svg>'

    # Calculate proportional width: ~4 pixels per character position
    pixels_per_char = 4
    total_width = len(colors) * pixels_per_char
    width_per_cell = total_width / len(colors)

    # Find average intensity (R value) in this heatmap for normalization
    # Average represents overall structural strength better than max (which could be an outlier)
    r_values = []
    for color in colors:
        if color.startswith('rgb('):
            rgb_match = re.search(r'rgb\((\d+),\s*(\d+),\s*(\d+)\)', color)
            if rgb_match:
                r = int(rgb_match.group(1))
                r_values.append(r)

    avg_intensity = sum(r_values) / len(r_values) if r_values else 0

    svg_parts = [f'<svg width="{total_width}" height="{height}" xmlns="http://www.w3.org/2000/svg">']

    for i, color in enumerate(colors):
        x = i * width_per_cell
        normalized_color = normalize_color(color, avg_intensity, num_messages)
        svg_parts.append(f'<rect x="{x}" y="0" width="{width_per_cell}" height="{height}" fill="{normalized_color}"/>')

    svg_parts.append('</svg>')

    return ''.join(svg_parts)

if __name__ == "__main__":
    main()
