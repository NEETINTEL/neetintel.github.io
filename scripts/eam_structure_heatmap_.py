"""
EAM Structure Heatmap Generator
Identifies hot position pairs and generates consolidated pattern visualizations.
"""

import pandas as pd
from collections import defaultdict
import os
from datetime import datetime
from data_loader import load_eam_data, get_messages_by_length

GROUP_COLORS = {
    1: '#06b050',  # Green
    2: '#ed7d32',  # Orange
    3: '#ffcc00',  # Yellow
    4: '#ff0467',  # Pink
    5: '#9063cd'   # Purple
}

# Cache for group classifications
_group_data_cache = None

def load_group_classifications():
    """Load PR_GROUPS worksheet from SHORTWAVES.xlsx."""
    global _group_data_cache

    if _group_data_cache is not None:
        return _group_data_cache

    excel_path = '/SHORTWAVES.xlsx'

    try:
        df_groups = pd.read_excel(excel_path, sheet_name='PR_GROUPS')
        # Expected columns: PREFIX, YEAR, GROUP, NOTES
        _group_data_cache = df_groups[['PREFIX', 'YEAR', 'GROUP']].copy()
        # Convert PREFIX to string to match the data format in messages
        _group_data_cache['PREFIX'] = _group_data_cache['PREFIX'].astype(str)
        return _group_data_cache
    except Exception as e:
        print(f"Warning: Could not load PR_GROUPS worksheet: {e}")
        return pd.DataFrame(columns=['PREFIX', 'YEAR', 'GROUP'])

def get_message_group(prefix, year):
    """
    Determine which group a message belongs to based on its prefix and year.

    If no exact match for the year, uses the most recent prior year's classification.
    """
    df_groups = load_group_classifications()

    if df_groups.empty:
        return None

    # Filter to this prefix
    prefix_data = df_groups[df_groups['PREFIX'] == prefix].copy()

    if prefix_data.empty:
        return None

    # Sort by year descending
    prefix_data = prefix_data.sort_values('YEAR', ascending=False)

    # Find the most recent year <= message year
    for idx, row in prefix_data.iterrows():
        if row['YEAR'] <= year:
            return row['GROUP']

    # If no match found, return None
    return None

def identify_hot_position_pairs(messages, min_frequency=0.3):
    """
    Identify position pairs where ANY character repeats across ≥min_frequency of messages.
    Returns set of (pos1, pos2) tuples that are structurally significant.
    """
    if not messages:
        return set()

    msg_len = len(messages[0])
    position_pair_counts = defaultdict(int)

    # For each message, find ALL position pairs where any character repeats
    for msg in messages:
        seen_pairs = set()  # Track pairs per message to avoid double-counting

        for pos1 in range(msg_len):
            char = msg[pos1]
            for pos2 in range(pos1 + 1, msg_len):
                if msg[pos2] == char:
                    pair = (pos1, pos2)
                    if pair not in seen_pairs:
                        position_pair_counts[pair] += 1
                        seen_pairs.add(pair)

    # Filter to pairs that appear in ≥min_frequency of messages
    threshold = len(messages) * min_frequency
    hot_pairs = {pair for pair, count in position_pair_counts.items() if count >= threshold}

    return hot_pairs

def identify_hot_position_pairs_by_group(message_data, min_frequency=0.3):
    """
    Identify position pairs that are hot within ANY group, rather than globally.
    This prevents majority groups from drowning out minority group patterns.

    Args:
        message_data: List of dicts with 'message' and 'group' keys
        min_frequency: Threshold for considering a pair hot within a group

    Returns:
        Set of (pos1, pos2) tuples that are hot in at least one group
    """
    if not message_data:
        return set()

    # Organize messages by group
    groups = defaultdict(list)
    for data in message_data:
        group = data.get('group', 0)  # 0 for unclassified
        groups[group].append(data['message'])

    # Find hot pairs for each group independently
    all_hot_pairs = set()

    for group, messages in groups.items():
        if len(messages) < 2:  # Need at least 2 messages to find patterns
            continue

        group_hot_pairs = identify_hot_position_pairs(messages, min_frequency)

        # Debug output
        if group_hot_pairs:
            if group is None or group == 0 or group == 'unclassified':
                group_name = "Unclassified"
            else:
                group_name = f"Group {group}"
            print(f"  {group_name}: {len(group_hot_pairs)} hot pairs from {len(messages)} messages")

        all_hot_pairs.update(group_hot_pairs)

    return all_hot_pairs

def matches_gapped_pattern(message, pos, pattern_str):
    """
    Check if message[pos:pos+len(pattern)] matches the gapped pattern.
    Wildcards (*) match any character, others must match exactly.
    """
    if pos + len(pattern_str) > len(message):
        return False

    for i, pattern_char in enumerate(pattern_str):
        if pattern_char != '*' and message[pos + i] != pattern_char:
            return False

    return True

def find_all_gapped_occurrences(message, pattern_str):
    """
    Find ALL positions in message where the gapped pattern appears.
    Returns set of starting positions.
    """
    occurrences = set()
    pattern_len = len(pattern_str)

    for pos in range(len(message) - pattern_len + 1):
        if matches_gapped_pattern(message, pos, pattern_str):
            occurrences.add(pos)

    return occurrences

def find_gapped_patterns(message, min_length=4, max_gap=3):
    """
    Find patterns like 'AB*CD' where * is a wildcard matching any single character.
    Returns list of pattern dictionaries with ALL positions where pattern appears.
    """
    patterns = []
    msg_len = len(message)
    seen_patterns = {}  # (pattern_str, length) -> set of positions

    for gap_size in range(1, max_gap + 1):
        for pos1 in range(msg_len):
            for pos2 in range(pos1 + gap_size + 1, msg_len):
                delta = pos2 - pos1

                # Build pattern with gap
                pattern_parts = []
                valid = True

                for i in range(msg_len):
                    if i < pos1:
                        continue
                    if i >= pos1 + delta:
                        break

                    offset = i - pos1
                    if pos2 + offset >= msg_len:
                        valid = False
                        break

                    char1 = message[pos1 + offset]
                    char2 = message[pos2 + offset]

                    if char1 == char2:
                        pattern_parts.append(char1)
                    else:
                        pattern_parts.append('*')

                if not valid or len(pattern_parts) < min_length:
                    continue

                pattern_str = ''.join(pattern_parts)

                # Must have at least 4 actual characters (not wildcards)
                non_wildcard_chars = pattern_str.replace('*', '')
                if len(non_wildcard_chars) >= 4:
                    key = (pattern_str, len(pattern_str))
                    if key not in seen_patterns:
                        seen_patterns[key] = set()
                        # Search ENTIRE message for ALL occurrences of this pattern
                        all_occurrences = find_all_gapped_occurrences(message, pattern_str)
                        seen_patterns[key] = all_occurrences
                    # If we already found this pattern, the positions are already complete

    # Convert to pattern list - gapped patterns always have 2+ positions by definition
    for (pattern_str, length), positions in seen_patterns.items():
        positions_list = sorted(list(positions))
        patterns.append({
            'type': 'gapped',
            'pattern': pattern_str,
            'positions': positions_list,
            'length': length,
            'count': len(positions_list)
        })

    return patterns

def find_exact_kmers(message, min_k=2):
    """
    Find exact repeating k-mers (k ≥ 2) in the message.
    Returns list of pattern dictionaries with ALL positions where pattern appears.
    """
    patterns = []
    msg_len = len(message)
    seen_patterns = {}  # pattern_string -> list of positions

    for k in range(min_k, msg_len // 2 + 1):
        for pos in range(msg_len - k + 1):
            kmer = message[pos:pos+k]

            # Track this occurrence
            if kmer not in seen_patterns:
                seen_patterns[kmer] = []
            seen_patterns[kmer].append(pos)

    # Convert to pattern list (only keep patterns that appear 2+ times)
    for kmer, positions in seen_patterns.items():
        if len(positions) >= 2:
            patterns.append({
                'type': 'exact',
                'pattern': kmer,
                'positions': positions,  # All positions where it appears
                'length': len(kmer),
                'count': len(positions)
            })

    return patterns

def find_hot_k1_patterns(message, hot_pairs):
    """
    Find single-character repeats that occur at hot position pairs.
    Groups by character to find all positions where each character repeats at hot pairs.
    Returns list of pattern dictionaries.
    """
    patterns = []
    char_to_positions = {}  # char -> list of positions where it appears at hot pairs

    # For each hot pair, if chars match, track them
    for pos1, pos2 in hot_pairs:
        if pos1 < len(message) and pos2 < len(message):
            if message[pos1] == message[pos2]:
                char = message[pos1]
                if char not in char_to_positions:
                    char_to_positions[char] = set()
                char_to_positions[char].add(pos1)
                char_to_positions[char].add(pos2)

    # Convert to pattern list
    for char, positions in char_to_positions.items():
        if len(positions) >= 2:
            positions_list = sorted(list(positions))
            patterns.append({
                'type': 'hot_k1',
                'pattern': char,
                'positions': positions_list,
                'length': 1,
                'count': len(positions_list)
            })

    return patterns

def find_quadruple_repeats(message):
    """
    Find quadruple character repeats (e.g., AAAA, BBBB).
    These are considered highly significant structural markers.
    Returns list of pattern dictionaries.
    """
    patterns = []
    import re

    # Find all quadruple repeats using regex
    for match in re.finditer(r'(.)\1{3,}', message):
        start_pos = match.start()
        repeat_char = match.group(1)
        repeat_length = len(match.group())

        # Treat each quad as a special pattern (self-contained, single position)
        patterns.append({
            'type': 'quad_repeat',
            'pattern': repeat_char * repeat_length,
            'positions': [start_pos],  # Single occurrence (self-contained)
            'length': repeat_length,
            'count': 1
        })

    return patterns

def get_pattern_positions(pattern_obj):
    """
    Get actual character positions covered by a pattern.
    For patterns with multiple occurrences, returns all positions for all occurrences.
    Returns a single set of all positions.
    """
    all_positions = set()

    if pattern_obj['type'] == 'gapped':
        pattern_str = pattern_obj['pattern']
        # For each occurrence position
        for start_pos in pattern_obj['positions']:
            # Add only non-wildcard character positions
            for i, char in enumerate(pattern_str):
                if char != '*':
                    all_positions.add(start_pos + i)
    elif pattern_obj['type'] == 'quad_repeat':
        # Quadruple repeats are self-contained at a single position
        start_pos = pattern_obj['positions'][0]
        for i in range(pattern_obj['length']):
            all_positions.add(start_pos + i)
    elif pattern_obj['type'] in ['exact', 'hot_k1']:
        # For each occurrence position, add all character positions
        for start_pos in pattern_obj['positions']:
            for i in range(pattern_obj['length']):
                all_positions.add(start_pos + i)

    return all_positions

def consolidate_patterns(patterns):
    """
    Consolidate patterns to remove redundancy:
    1. Quad repeats always take highest priority (never removed)
    2. For patterns with same string and type, merge their positions
    3. Remove patterns whose positions are entirely covered by higher-priority patterns
    4. PRESERVE exact patterns with high count (≥3) even if covered - they're structurally significant
    """
    if not patterns:
        return []

    # Step 1: Merge patterns with same (pattern, type) combination
    pattern_map = {}  # (pattern_str, type) -> merged pattern
    for p in patterns:
        key = (p['pattern'], p['type'])
        if key not in pattern_map:
            pattern_map[key] = p.copy()
        else:
            # Merge positions
            existing_positions = set(pattern_map[key]['positions'])
            new_positions = set(p['positions'])
            merged_positions = sorted(list(existing_positions | new_positions))
            pattern_map[key]['positions'] = merged_positions
            pattern_map[key]['count'] = len(merged_positions)

    merged_patterns = list(pattern_map.values())

    # Step 2: Identify highly significant patterns that should be preserved
    # Exact patterns appearing 3+ times are structurally impossible to be random
    significant_exact = [p for p in merged_patterns
                         if p['type'] == 'exact' and p.get('count', 0) >= 3 and p['length'] >= 4]

    # Step 3: Sort by priority and length
    # Priority: quad_repeat (4) > significant_exact (3.5) > gapped (3) > exact (2) > hot_k1 (1)
    priority_order = {'quad_repeat': 4, 'gapped': 3, 'exact': 2, 'hot_k1': 1}

    def sort_key(p):
        # Boost priority for significant exact patterns
        base_priority = priority_order.get(p['type'], 0)
        if p in significant_exact:
            base_priority = 3.5  # Higher than gapped
        return (base_priority, p.get('count', 1), p['length'])

    sorted_patterns = sorted(merged_patterns, key=sort_key, reverse=True)

    # Step 4: Remove patterns whose positions are entirely covered by higher-priority patterns
    # Exception: Always keep significant exact patterns
    final_patterns = []
    covered_positions = set()

    for p in sorted_patterns:
        pattern_positions = get_pattern_positions(p)

        # Keep if: any position uncovered OR it's a significant exact pattern
        if not pattern_positions.issubset(covered_positions) or p in significant_exact:
            final_patterns.append(p)
            covered_positions.update(pattern_positions)

    return final_patterns

def analyze_message_patterns(message, hot_pairs):
    """
    Find all patterns in a message using hot position pairs as filter for k=1.
    Returns consolidated list of patterns.
    """
    all_patterns = []

    # Find quadruple repeats first
    all_patterns.extend(find_quadruple_repeats(message))

    # Find gapped patterns
    all_patterns.extend(find_gapped_patterns(message, min_length=4, max_gap=3))

    # Find exact k-mers (k ≥ 2)
    all_patterns.extend(find_exact_kmers(message, min_k=2))

    # Find hot k=1 patterns
    all_patterns.extend(find_hot_k1_patterns(message, hot_pairs))

    # Consolidate
    consolidated = consolidate_patterns(all_patterns)

    return consolidated

def generate_aggregate_heatmap(messages):
    """
    Generate aggregate heatmap showing which positions have redundancy across messages.
    Uses cubic scaling for color intensity.
    Quadruple repeats have equal weight but higher priority.
    """
    msg_len = len(messages[0]) if messages else 0
    position_counts = [0.0] * msg_len  # Use float for weighted counts

    for msg in messages:
        patterns = analyze_message_patterns(msg, identify_hot_position_pairs(messages))

        # Separate quad repeats from other patterns
        quad_positions = set()
        other_positions = set()

        for p in patterns:
            pattern_positions = get_pattern_positions(p)

            if p['type'] == 'quad_repeat':
                quad_positions.update(pattern_positions)
            else:
                other_positions.update(pattern_positions)

        # Increment count for positions with quad repeats (1.0x weight - equal to others)
        for pos in quad_positions:
            position_counts[pos] += 1.0

        # Increment count for other positions (1x weight)
        for pos in other_positions:
            if pos not in quad_positions:  # Don't double-count
                position_counts[pos] += 1.0

    # Calculate color intensity using cubic scaling
    max_count = max(position_counts) if position_counts else 1

    colors = []
    for count in position_counts:
        if count == 0:
            colors.append('#1a1a1a')  # Dark background
        else:
            import math
            log_ratio = math.log(count + 1) / math.log(max_count + 1)
            intensity_ratio = log_ratio ** 3  # Cubic power
            intensity = int(intensity_ratio * 255)
            # Orange/yellow gradient
            colors.append(f'rgb({intensity}, {intensity//2}, 0)')

    return position_counts, colors

def generate_html_report(messages, full_df, target_length, output_dir='./output', prev_length=None, next_length=None, all_available_lengths=None, exclude_groups_12=False):
    """
    Generate HTML report with sticky aggregate heatmap and two-line message display.

    Args:
        prev_length: Previous message length for navigation (optional)
        next_length: Next message length for navigation (optional)
        all_available_lengths: List of all available message lengths for dropdown (optional)
    """
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f'structure_heatmap_{target_length}char.html')

    # First pass: collect message-group pairs for group-aware hot pair detection
    print(f"\nIdentifying hot position pairs using group-aware analysis...")
    message_group_data = []
    for msg in messages:
        msg_rows = full_df[full_df['MESSAGE'] == msg]
        if not msg_rows.empty:
            first_row = msg_rows.iloc[0]
            prefix = str(first_row['PR'])
            date_str = str(first_row['DATE'])
            utc_str = str(first_row['UTC'])

            # Parse datetime for year
            try:
                dt = pd.to_datetime(date_str + ' ' + utc_str, format='%Y.%m.%d %H:%M')
                year = dt.year
            except:
                year = None

            # Get group classification
            group = get_message_group(prefix, year) if year else None

            message_group_data.append({
                'message': msg,
                'group': group
            })

    # Identify hot pairs using group-aware approach
    # This finds pairs that are hot within ANY group, preventing majority groups from drowning out minority patterns
    hot_pairs = identify_hot_position_pairs_by_group(message_group_data, min_frequency=0.3)
    print(f"Total hot pairs (union across all groups): {len(hot_pairs)}")

    # Generate aggregate heatmap
    position_counts, colors = generate_aggregate_heatmap(messages)

    # Prepare message data with metadata
    message_data = []
    for msg in messages:
        # Get first occurrence metadata
        msg_rows = full_df[full_df['MESSAGE'] == msg]
        if not msg_rows.empty:
            first_row = msg_rows.iloc[0]
            date_str = str(first_row['DATE'])
            utc_str = str(first_row['UTC'])
            callsign = str(first_row['CALLSIGN'])
            prefix = str(first_row['PR'])

            # Parse datetime
            try:
                dt = pd.to_datetime(date_str + ' ' + utc_str, format='%Y.%m.%d %H:%M')
                timestamp = dt
                year = dt.year
            except:
                timestamp = None
                year = None

            # Get group classification
            group = get_message_group(prefix, year) if year else None

            patterns = analyze_message_patterns(msg, hot_pairs)

            message_data.append({
                'message': msg,
                'timestamp': timestamp,
                'callsign': callsign,
                'prefix': prefix,
                'group': group,
                'patterns': patterns
            })

    # Sort by timestamp
    message_data.sort(key=lambda x: x['timestamp'] if x['timestamp'] else datetime.min)

    # Write HTML
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>EAM Structure Heatmap - {target_length} Characters</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&family=Roboto+Condensed:wght@700&family=Roboto+Mono&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Roboto', sans-serif;
            background-color: #0d0d0d;
            color: #e0e0e0;
            padding: 20px;
            margin: 0;
        }}

        h1 {{
            color: #ffffff;
            border-bottom: 3px solid #4a9eff;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}

        .nav-box {{
            background-color: #1a1a1a;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
            border: 2px solid #4a9eff;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}

        .nav-link {{
            display: inline-block;
            padding: 10px 20px;
            background-color: #4a9eff;
            color: #000;
            text-decoration: none;
            border-radius: 5px;
            font-weight: bold;
            transition: background-color 0.2s;
        }}

        .nav-link:hover {{
            background-color: #6bb6ff;
        }}

        .nav-link.disabled {{
            background-color: #333;
            color: #666;
            cursor: not-allowed;
            pointer-events: none;
        }}

        .nav-center {{
            display: flex;
            align-items: center;
            gap: 15px;
            text-align: center;
            font-size: 1em;
        }}

        .nav-center a {{
            color: #4a9eff;
            text-decoration: none;
            font-weight: bold;
        }}

        .nav-center a:hover {{
            color: #6dd77d;
        }}

        .nav-jump {{
            display: flex;
            align-items: center;
            gap: 5px;
        }}

        .nav-jump select {{
            padding: 5px 8px;
            background-color: #2a2a2a;
            border: 1px solid #444;
            color: #fff;
            border-radius: 3px;
            cursor: pointer;
        }}

        .nav-jump select:focus {{
            outline: none;
            border-color: #4a9eff;
        }}

        .nav-jump select:hover {{
            background-color: #333;
        }}

        .heatmap-container {{
            position: sticky;
            top: 0;
            z-index: 100;
            background-color: #0d0d0d;
            padding: 15px 0;
            margin-bottom: 5px;
        }}

        .heatmap-bar {{
            display: flex;
            gap: 0;
            margin-bottom: 3px;
        }}

        .heatmap-cell {{
            flex: 1;
            height: 20px;
            border-right: 1px solid #333;
        }}

        .position-ruler {{
            display: flex;
            gap: 0;
            font-family: 'Roboto Mono', monospace;
            font-size: 10px;
            color: #666;
        }}

        .position-label {{
            flex: 1;
            text-align: center;
        }}

        .message-block {{
            margin-bottom: 0px;
            line-height: 1.2;
        }}

        .message-meta {{
            font-family: 'Roboto Condensed', sans-serif;
            font-weight: 700;
            font-size: 11px;
            color: #888;
            margin-bottom: 0px;
            line-height: 1.1;
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .dot {{
            font-family: 'Roboto Condensed', sans-serif;
            cursor: pointer;
            display: inline;
        }}

        .group-1-dot {{
            color: #06b050;
        }}

        .group-2-dot {{
            color: #ed7d32;
        }}

        .group-3-dot {{
            color: #ffcc00;
        }}

        .group-4-dot {{
            color: #ff0467;
        }}

        .group-5-dot {{
            color: #9063cd;
        }}

        .message-display {{
            display: flex;
            font-family: 'Roboto Mono', monospace;
            font-size: 13px;
            line-height: 1.8;
            margin-bottom: 1px;
        }}

        .char {{
            flex: 1;
            text-align: center;
            color: #e0e0e0;
            padding: 3px 0;
        }}

        .char-exact {{
            background-color: #4a9eff;
            color: #000000;
        }}

        .char-gapped {{
            background-color: #51cf66;
            color: #000000;
        }}

        .char-hot_k1 {{
            background-color: #cc5de8;
            color: #000000;
        }}

        .char-quad_repeat {{
            background-color: #ff69b4;
            color: #000000;
        }}

        .char-selected {{
            outline: 3px solid #ffffff;
            outline-offset: -3px;
            box-shadow: 0 0 10px rgba(255, 255, 255, 0.8);
            z-index: 10;
            position: relative;
            opacity: 1.0 !important;
        }}

        .char[data-patterns] {{
            cursor: pointer;
        }}

        .top-section {{
            display: flex;
            gap: 15px;
            margin: 20px 0;
            align-items: stretch;
        }}

        .info-box {{
            flex: 1;
            background-color: #1a1a1a;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #4a9eff;
        }}

        .stat-card {{
            background-color: #1a1a1a;
            padding: 15px;
            border-radius: 5px;
            text-align: center;
            min-width: 150px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
        }}

        .stat-value {{
            font-size: 2em;
            color: #4a9eff;
            font-weight: bold;
        }}

        .stat-label {{
            color: #999;
            font-size: 0.9em;
            margin-top: 5px;
        }}

        .controls-container {{
            display: flex;
            gap: 20px;
            margin: 20px 0;
        }}

        .filter-controls {{
            background-color: #1a1a1a;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #4a9eff;
            flex: 1;
        }}

        .filter-group {{
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            margin-top: 10px;
        }}

        .filter-checkbox {{
            display: flex;
            align-items: center;
            gap: 8px;
            cursor: pointer;
        }}

        .filter-checkbox input[type="checkbox"] {{
            width: 18px;
            height: 18px;
            cursor: pointer;
        }}

        .filter-checkbox label {{
            cursor: pointer;
            user-select: none;
        }}

        .group-label {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-weight: bold;
            font-size: 0.9em;
        }}

        .group-label-1 {{ background-color: #06b050; color: #000; }}
        .group-label-2 {{ background-color: #ed7d32; color: #000; }}
        .group-label-3 {{ background-color: #ffcc00; color: #000; }}
        .group-label-4 {{ background-color: #ff0467; color: #fff; }}
        .group-label-5 {{ background-color: #9063cd; color: #fff; }}
        .group-label-unclassified {{ background-color: #555; color: #fff; }}

        .group-heading {{
            background-color: #2a2a2a;
            padding: 10px 15px;
            margin: 20px 0 10px 0;
            border-left: 5px solid;
            font-weight: bold;
            font-size: 1.1em;
        }}

        .group-heading-1 {{ border-left-color: #06b050; color: #06b050; }}
        .group-heading-2 {{ border-left-color: #ed7d32; color: #ed7d32; }}
        .group-heading-3 {{ border-left-color: #ffcc00; color: #ffcc00; }}
        .group-heading-4 {{ border-left-color: #ff0467; color: #ff0467; }}
        .group-heading-5 {{ border-left-color: #9063cd; color: #9063cd; }}
        .group-heading-unclassified {{ border-left-color: #555; color: #aaa; }}

        .sort-controls {{
            background-color: #1a1a1a;
            padding: 15px;
            border-radius: 5px;
            border-left: 4px solid #51cf66;
            flex: 1;
        }}

        .sort-buttons {{
            display: flex;
            gap: 10px;
            margin-top: 10px;
        }}

        .sort-btn {{
            padding: 8px 16px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            font-weight: bold;
            transition: all 0.2s;
            background-color: #333;
            color: #aaa;
        }}

        .sort-btn.active {{
            background-color: #51cf66;
            color: #000;
        }}

        .sort-btn:hover {{
            background-color: #444;
        }}

        .sort-btn.active:hover {{
            background-color: #6dd77d;
        }}

        .message-block.hidden {{
            display: none;
        }}

        .group-heading.hidden {{
            display: none;
        }}
    </style>
</head>
<body>
""")

        # Add navigation box if prev or next lengths are provided
        if prev_length is not None or next_length is not None:
            f.write('    <div class="nav-box">\n')

            # Previous link
            if prev_length is not None:
                f.write(f'        <a href="structure_heatmap_{prev_length}char.html" class="nav-link">← {prev_length}</a>\n')
            else:
                f.write('        <span class="nav-link disabled">←</span>\n')

            # Center: Home + Jump to
            f.write('        <div class="nav-center">\n')
            f.write('            <a href="index.html">Home</a>\n')
            f.write('            <span>|</span>\n')
            f.write('            <div class="nav-jump">\n')
            f.write('                <label for="length-jump">Go to:</label>\n')

            if all_available_lengths:
                # Generate dropdown with available lengths
                f.write('                <select id="length-jump">\n')
                f.write(f'                    <option value="" selected>--</option>\n')
                for length in sorted(all_available_lengths):
                    if length == target_length:
                        f.write(f'                    <option value="{length}" selected>{length}</option>\n')
                    else:
                        f.write(f'                    <option value="{length}">{length}</option>\n')
                f.write('                </select>\n')
            else:
                # Fallback to text input if no lengths provided
                f.write('                <input type="number" id="length-jump" min="1" max="999" placeholder="##">\n')

            f.write('            </div>\n')
            f.write('        </div>\n')

            # Next link
            if next_length is not None:
                f.write(f'        <a href="structure_heatmap_{next_length}char.html" class="nav-link">{next_length} →</a>\n')
            else:
                f.write('        <span class="nav-link disabled">→</span>\n')

            f.write('    </div>\n')

        f.write(f"""
    <h1>EAM Structure Heatmap - {target_length} Character Messages</h1>
""")

        # Add exclusion notice if Groups 1 and 2 are excluded
        if exclude_groups_12:
            f.write("""
    <div style="background: rgba(255, 193, 7, 0.15); border-left: 3px solid #ffc107; padding: 0.75rem 1rem; margin-bottom: 1.5rem; border-radius: 4px;">
        <strong style="color: #ffc107;">⚠ Group 1 and Group 2 Excluded</strong><br>
        <span style="color: #e6e6eb; font-size: 0.9rem;">
            For Group 1 and 2 30 character messages, of which the dataset contains over 9000 such EAMs, no structural patterns are apparent.
            <br>For this reason, they are excluded from this report. (This exclusion applies only to Group 1 and 2 30 character messages.)
        </span>
    </div>
""")

        f.write(f"""
    <!-- Horizontal layout: Info box + 3 stat cards -->
    <div class="top-section">
        <div class="info-box">
            <strong>Analysis Type:</strong> Hot position pairs + consolidated pattern detection<br>
            <strong>Total Messages:</strong> {len(messages)}<br>
            <strong>Hot Pairs Threshold:</strong> ≥30% of messages<br>
            <strong>Pattern Types:</strong> <span style="color: #ff69b4; font-weight: bold;">Quadruple Repeats</span>, <span style="color: #51cf66; font-weight: bold;">Gapped</span>, <span style="color: #4a9eff; font-weight: bold;">Exact k≥2</span>, <span style="color: #cc5de8; font-weight: bold;">Hot k=1</span>
        </div>
        <div class="stat-card">
            <div class="stat-value">{len(hot_pairs)}</div>
            <div class="stat-label">Hot Position Pairs</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{sum(1 for d in message_data if d['patterns'])}</div>
            <div class="stat-label">Messages with Patterns</div>
        </div>
        <div class="stat-card">
            <div class="stat-value">{sum(len(d['patterns']) for d in message_data)}</div>
            <div class="stat-label">Total Patterns Found</div>
        </div>
    </div>

""")

        # Determine which groups are actually present in this dataset
        groups_present = set()
        for data in message_data:
            if data['group']:
                groups_present.add(data['group'])
            else:
                groups_present.add('unclassified')

        # Only show sort and filter controls if there are multiple groups
        if len(groups_present) > 1:
            f.write("""    <div class="controls-container">
        <div class="sort-controls">
            <strong>Display Mode:</strong>
            <div class="sort-buttons">
                <button class="sort-btn active" id="sort-grouped">Grouped by Classification</button>
                <button class="sort-btn" id="sort-chronological">Ungrouped</button>
            </div>
        </div>

        <div class="filter-controls">
            <strong>Filter by Group:</strong>
            <div class="filter-group">
""")

            # Show checkboxes for groups 1-5 if they exist
            for group_num in [1, 2, 3, 4, 5]:
                if group_num in groups_present:
                    f.write(f"""            <div class="filter-checkbox">
                <input type="checkbox" id="filter-group-{group_num}" checked>
                <label for="filter-group-{group_num}"><span class="group-label group-label-{group_num}">Group {group_num}</span></label>
            </div>
""")

            # Show unclassified if it exists
            if 'unclassified' in groups_present:
                f.write("""            <div class="filter-checkbox">
                <input type="checkbox" id="filter-group-unclassified" checked>
                <label for="filter-group-unclassified"><span class="group-label group-label-unclassified">Unknown</span></label>
            </div>
""")

            f.write("""            </div>
        </div>
    </div>
""")

        f.write("""

    <div class="heatmap-container">
        <div class="heatmap-bar">
""")

        # Write heatmap cells
        for i, color in enumerate(colors):
            f.write(f'            <div class="heatmap-cell" style="background-color: {color};" title="Position {i+1}: {position_counts[i]} messages"></div>\n')

        f.write('        </div>\n')
        f.write('        <div class="position-ruler">\n')

        # Write position labels
        for i in range(target_length):
            f.write(f'            <div class="position-label">{i+1:02d}</div>\n')

        f.write('        </div>\n')
        f.write('    </div>\n\n')

        # Calculate opacity values for each position based on heatmap intensity
        import math
        max_count = max(position_counts) if position_counts else 1
        position_opacity = []
        for count in position_counts:
            if count == 0:
                position_opacity.append(0.3)  # Minimum opacity for non-structural positions
            else:
                log_ratio = math.log(count + 1) / math.log(max_count + 1)
                intensity_ratio = log_ratio ** 3  # Same cubic scaling as heatmap
                # Map to opacity range 0.4 to 1.0
                opacity = 0.4 + (intensity_ratio * 0.6)
                position_opacity.append(opacity)

        # Container for messages (for sorting manipulation)
        f.write('    <div id="messages-container">\n')

        # Write messages in two-line format
        pattern_global_id = 0
        for data in message_data:
            msg = data['message']
            timestamp = data['timestamp']
            callsign = data['callsign']
            prefix = data['prefix']
            group = data['group']
            patterns = data['patterns']

            # Format timestamp
            if timestamp:
                ts_str = timestamp.strftime('%Y%m%d %H:%M')
            else:
                ts_str = 'Unknown'

            # Build dot HTML (with proper HTML escaping)
            import html
            msg_escaped = html.escape(msg, quote=True)
            prefix_escaped = html.escape(prefix, quote=True)
            callsign_escaped = html.escape(callsign, quote=True)

            if group:
                dot = f'<span class="dot group-{group}-dot" data-message="{msg_escaped}" title="{prefix_escaped} (Group {group})">●</span>'
            else:
                dot = f'<span class="dot" style="color: #555;" data-message="{msg_escaped}" title="{prefix_escaped}">●</span>'

            meta_str = f'{ts_str} {callsign_escaped}'

            # Build position-to-pattern mapping
            position_to_patterns = {}  # position -> list of (pattern_id, type)
            position_to_type = {}  # position -> type (for priority-based coloring)

            for p in patterns:
                pattern_global_id += 1
                all_positions = get_pattern_positions(p)

                for pos in all_positions:
                    if pos not in position_to_patterns:
                        position_to_patterns[pos] = []
                    position_to_patterns[pos].append((pattern_global_id, p['type'], p.get('count', 1)))

                    # Track type with priority for coloring: quad_repeat > gapped > exact > hot_k1
                    priority_order = {'quad_repeat': 4, 'gapped': 3, 'exact': 2, 'hot_k1': 1}
                    current_priority = priority_order.get(position_to_type.get(pos), 0)
                    new_priority = priority_order.get(p['type'], 0)

                    if pos not in position_to_type or new_priority > current_priority:
                        position_to_type[pos] = p['type']

            # Write message block with data attributes for filtering and sorting
            group_attr = f'data-group="{group}"' if group else 'data-group="unclassified"'
            timestamp_attr = f'data-timestamp="{timestamp.isoformat()}"' if timestamp else 'data-timestamp="0000-00-00T00:00:00"'

            # Store pattern positions for this message (for heatmap recalculation)
            pattern_positions = []
            for p in patterns:
                all_positions = list(get_pattern_positions(p))
                weight = 1.0  # All patterns have equal weight
                pattern_positions.append({'positions': all_positions, 'weight': weight})

            import json
            import html
            pattern_data = json.dumps(pattern_positions)
            pattern_data_escaped = html.escape(pattern_data, quote=True)

            f.write(f'        <div class="message-block" {group_attr} {timestamp_attr} data-patterns="{pattern_data_escaped}">\n')
            f.write(f'            <div class="message-meta">{dot}<span>{meta_str}</span></div>\n')
            f.write('            <div class="message-display">')

            # Pre-compute highlight signatures for each position
            position_highlight_map = {}  # position -> set of positions that would be highlighted
            for pos in position_to_patterns:
                highlighted_positions = set()
                # Get all pattern IDs for this position
                pattern_ids_for_pos = [pid for pid, _, _ in position_to_patterns[pos]]
                # Find all positions that share any of these pattern IDs
                for other_pos in position_to_patterns:
                    other_pattern_ids = [pid for pid, _, _ in position_to_patterns[other_pos]]
                    if any(pid in pattern_ids_for_pos for pid in other_pattern_ids):
                        highlighted_positions.add(other_pos)
                position_highlight_map[pos] = sorted(list(highlighted_positions))

            for i, char in enumerate(msg):
                if i in position_to_patterns:
                    ptype = position_to_type[i]
                    pattern_ids = ','.join([str(pid) for pid, _, _ in position_to_patterns[i]])
                    # Get max count for this position (for tooltip)
                    max_count = max([count for _, _, count in position_to_patterns[i]])
                    # Quad repeats always get full opacity, others use heatmap-based opacity
                    opacity = 1.0 if ptype == 'quad_repeat' else position_opacity[i]
                    count_display = f' (×{max_count})' if max_count > 2 else ''
                    title_text = f'{ptype}{count_display}'
                    # Add position and highlight signature
                    highlight_sig = ','.join([str(p) for p in position_highlight_map[i]])
                    f.write(f'<span class="char char-{ptype}" data-patterns="{pattern_ids}" data-position="{i}" data-highlight-sig="{highlight_sig}" style="opacity: {opacity:.2f}" title="{title_text}">{char}</span>')
                else:
                    # Non-patterned characters still need position and empty signature for cross-message highlighting
                    f.write(f'<span class="char" data-position="{i}" data-highlight-sig="">{char}</span>')

            f.write('</div>\n')
            f.write('        </div>\n')

        # Close messages container
        f.write('    </div>\n')

        f.write(f"""
    <script>
        // Track currently selected position and signature
        let selectedPosition = null;
        let selectedSignature = null;

        // Add click handler to all characters with position data
        document.querySelectorAll('.char[data-position]').forEach(char => {{
            char.addEventListener('click', function(e) {{
                e.stopPropagation();
                const position = this.getAttribute('data-position');
                const signature = this.getAttribute('data-highlight-sig');

                // Skip if no signature (shouldn't happen, but be safe)
                if (signature === null) {{
                    return;
                }}

                // If clicking the same position+signature, deselect
                if (selectedPosition === position && selectedSignature === signature) {{
                    deselectAll();
                    selectedPosition = null;
                    selectedSignature = null;
                    return;
                }}

                // Select this position+signature combination
                selectedPosition = position;
                selectedSignature = signature;

                // Deselect all first
                deselectAll();

                // If signature is empty (non-patterned character), do nothing
                if (signature === '') {{
                    return;
                }}

                // Get the positions to highlight from the signature
                const positionsToHighlight = signature.split(',').map(p => p.trim()).filter(p => p !== '');

                // Find all message blocks
                document.querySelectorAll('.message-block').forEach(messageBlock => {{
                    // Get all characters in this message
                    const chars = messageBlock.querySelectorAll('.char');

                    // Check if this message has the same pattern at the same position
                    const posInt = parseInt(position);
                    if (posInt < chars.length) {{
                        const charAtPosition = chars[posInt];
                        const charSignature = charAtPosition.getAttribute('data-highlight-sig');

                        // If this character has the same signature (and it's not empty), highlight the pattern
                        if (charSignature === signature && charSignature !== '') {{
                            // Highlight all positions in the signature for this message
                            positionsToHighlight.forEach(pos => {{
                                const posToHighlight = parseInt(pos);
                                if (posToHighlight < chars.length) {{
                                    chars[posToHighlight].classList.add('char-selected');
                                }}
                            }});
                        }}
                    }}
                }});
            }});
        }});

        function deselectAll() {{
            document.querySelectorAll('.char-selected').forEach(char => {{
                char.classList.remove('char-selected');
            }});
        }}

        // Click outside to deselect
        document.addEventListener('click', function(e) {{
            if (!e.target.classList.contains('char') && !e.target.classList.contains('dot')) {{
                deselectAll();
                selectedPosition = null;
                selectedSignature = null;
            }}
        }});

        // Dot copy functionality
        document.querySelectorAll('.dot').forEach(dot => {{
            dot.addEventListener('click', function(e) {{
                e.stopPropagation();
                const message = this.getAttribute('data-message');

                // Copy to clipboard
                navigator.clipboard.writeText(message).catch(err => {{
                    console.error('Failed to copy:', err);
                }});
            }});
        }});

        // Group filtering functionality
        const messageLength = {target_length};
        const heatmapCells = document.querySelectorAll('.heatmap-cell');

        function updateHeatmapAndVisibility() {{
            // Get checked groups
            const checkedGroups = new Set();

            // Check groups 1-5
            for (let i = 1; i <= 5; i++) {{
                const checkbox = document.getElementById('filter-group-' + i);
                if (checkbox && checkbox.checked) {{
                    checkedGroups.add(String(i));
                }}
            }}

            // Check unclassified
            const unclassifiedCheckbox = document.getElementById('filter-group-unclassified');
            if (unclassifiedCheckbox && unclassifiedCheckbox.checked) {{
                checkedGroups.add('unclassified');
            }}

            // Show/hide messages based on filters
            const messageBlocks = document.querySelectorAll('.message-block');
            const visibleMessages = [];

            messageBlocks.forEach(block => {{
                const group = block.getAttribute('data-group');

                if (checkedGroups.has(group)) {{
                    block.classList.remove('hidden');
                    visibleMessages.push(block);
                }} else {{
                    block.classList.add('hidden');
                }}
            }});

            // Show/hide group headings based on checked groups
            document.querySelectorAll('.group-heading').forEach(heading => {{
                // Extract group number/type from heading class
                const classList = Array.from(heading.classList);
                const groupClass = classList.find(c => c.startsWith('group-heading-'));

                if (groupClass) {{
                    const group = groupClass.replace('group-heading-', '');

                    if (checkedGroups.has(group)) {{
                        heading.classList.remove('hidden');
                    }} else {{
                        heading.classList.add('hidden');
                    }}
                }}
            }});

            // Recalculate aggregate heatmap
            const positionCounts = new Array(messageLength).fill(0);

            visibleMessages.forEach(block => {{
                const patternDataStr = block.getAttribute('data-patterns');
                if (!patternDataStr) return;

                try {{
                    const patternData = JSON.parse(patternDataStr);
                    if (Array.isArray(patternData)) {{
                        // Collect all positions covered by ANY pattern for this message
                        // Each position should only be counted once per message
                        const coveredPositions = new Set();
                        patternData.forEach(pattern => {{
                            if (pattern.positions && Array.isArray(pattern.positions)) {{
                                pattern.positions.forEach(pos => {{
                                    if (pos >= 0 && pos < messageLength) {{
                                        coveredPositions.add(pos);
                                    }}
                                }});
                            }}
                        }});

                        // Now increment count once per position
                        coveredPositions.forEach(pos => {{
                            positionCounts[pos] += 1.0;
                        }});
                    }}
                }} catch (e) {{
                    // Silent error handling
                }}
            }});

            // Update heatmap cells with new colors
            const maxCount = Math.max(...positionCounts, 1);

            positionCounts.forEach((count, i) => {{
                if (i >= heatmapCells.length) return;

                let color;
                if (count === 0) {{
                    color = '#1a1a1a';
                }} else {{
                    const logRatio = Math.log(count + 1) / Math.log(maxCount + 1);
                    const intensityRatio = Math.pow(logRatio, 3);
                    const intensity = Math.floor(intensityRatio * 255);
                    color = 'rgb(' + intensity + ', ' + Math.floor(intensity / 2) + ', 0)';
                }}
                heatmapCells[i].style.backgroundColor = color;
                heatmapCells[i].title = 'Position ' + (i + 1) + ': ' + count.toFixed(1) + ' weighted messages';
            }});
        }}

        // Add event listeners to all checkboxes
        const filterCheckboxes = document.querySelectorAll('.filter-checkbox input[type="checkbox"]');
        filterCheckboxes.forEach(checkbox => {{
            checkbox.addEventListener('change', updateHeatmapAndVisibility);
        }});

        // Sorting functionality
        const messagesContainer = document.getElementById('messages-container');
        let currentSortMode = 'grouped';  // Default to grouped

        function sortMessages(mode) {{
            const messageBlocks = Array.from(document.querySelectorAll('.message-block'));

            // Remove all existing group headings
            document.querySelectorAll('.group-heading').forEach(h => h.remove());

            if (mode === 'chronological') {{
                // Sort by timestamp
                messageBlocks.sort((a, b) => {{
                    const tsA = a.getAttribute('data-timestamp');
                    const tsB = b.getAttribute('data-timestamp');
                    return tsA.localeCompare(tsB);
                }});

                // Clear container and re-append in chronological order
                messagesContainer.innerHTML = '';
                messageBlocks.forEach(block => messagesContainer.appendChild(block));

            }} else if (mode === 'grouped') {{
                // Sort by group first, then by timestamp within each group
                messageBlocks.sort((a, b) => {{
                    const groupA = a.getAttribute('data-group');
                    const groupB = b.getAttribute('data-group');

                    // Define group order: 1, 2, 3, 4, 5, unclassified
                    const groupOrder = {{'1': 0, '2': 1, '3': 2, '4': 3, '5': 4, 'unclassified': 5}};
                    const orderA = groupOrder[groupA] !== undefined ? groupOrder[groupA] : 6;
                    const orderB = groupOrder[groupB] !== undefined ? groupOrder[groupB] : 6;

                    if (orderA !== orderB) {{
                        return orderA - orderB;
                    }}

                    // Within same group, sort by timestamp
                    const tsA = a.getAttribute('data-timestamp');
                    const tsB = b.getAttribute('data-timestamp');
                    return tsA.localeCompare(tsB);
                }});

                // Clear container
                messagesContainer.innerHTML = '';

                // Group messages and add headings
                let currentGroup = null;
                messageBlocks.forEach(block => {{
                    const group = block.getAttribute('data-group');

                    if (group !== currentGroup) {{
                        currentGroup = group;
                        const heading = document.createElement('div');
                        heading.className = 'group-heading group-heading-' + group;

                        let groupName = 'Group ' + group;
                        if (group === 'unclassified') {{
                            groupName = 'Unknown Classification';
                        }}

                        heading.textContent = groupName;
                        messagesContainer.appendChild(heading);
                    }}

                    messagesContainer.appendChild(block);
                }});
            }}

            currentSortMode = mode;
            updateHeatmapAndVisibility();  // Update visibility after sorting
        }}

        // Sort button event listeners
        document.getElementById('sort-grouped').addEventListener('click', function() {{
            document.getElementById('sort-grouped').classList.add('active');
            document.getElementById('sort-chronological').classList.remove('active');
            sortMessages('grouped');
        }});

        document.getElementById('sort-chronological').addEventListener('click', function() {{
            document.getElementById('sort-chronological').classList.add('active');
            document.getElementById('sort-grouped').classList.remove('active');
            sortMessages('chronological');
        }});

        // Initialize with grouped view (default)
        sortMessages('grouped');

        // Navigation jump handler
        const lengthJump = document.getElementById('length-jump');
        if (lengthJump) {{
            if (lengthJump.tagName === 'SELECT') {{
                // Dropdown handler
                lengthJump.addEventListener('change', function() {{
                    const targetLength = this.value;
                    if (targetLength) {{
                        const targetUrl = `structure_heatmap_${{targetLength}}char.html`;
                        window.location.href = targetUrl;
                    }}
                }});
            }} else {{
                // Input field handler (fallback)
                lengthJump.addEventListener('keypress', function(e) {{
                    if (e.key === 'Enter') {{
                        const targetLength = parseInt(this.value);
                        if (targetLength > 0) {{
                            const targetUrl = `structure_heatmap_${{targetLength}}char.html`;
                            window.location.href = targetUrl;
                        }}
                    }}
                }});
            }}
        }}
    </script>
</body>
</html>
""")

    return output_path

def generate_single_heatmap(df, target_length, exclude_groups_12=False, prev_length=None, next_length=None, all_available_lengths=None):
    """Generate heatmap for a single message length with optional navigation."""
    # Filter data
    if exclude_groups_12:
        # Load group classifications and find all Group 1 and Group 2 prefixes
        df_groups = load_group_classifications()
        if not df_groups.empty:
            excluded_prefixes = set(df_groups[df_groups['GROUP'].isin([1, 2])]['PREFIX'].unique())
            full_df = df[(df['MSG_LEN'] == target_length) & (~df['PR'].isin(excluded_prefixes))]
            print(f"  Excluded {len(excluded_prefixes)} Group 1 and Group 2 prefixes")
        else:
            print("  Warning: Could not load group classifications, including all messages")
            full_df = df[df['MSG_LEN'] == target_length]
    else:
        full_df = df[df['MSG_LEN'] == target_length]

    messages = full_df['MESSAGE'].unique().tolist()
    messages = sorted(messages)

    if not messages:
        print(f"  No messages found for length {target_length}")
        return None

    print(f"  Analyzing {len(messages)} unique messages...")

    # Generate HTML report
    output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
    output_path = generate_html_report(messages, full_df, target_length, output_dir, prev_length, next_length, all_available_lengths, exclude_groups_12)

    # Print hot pairs summary
    hot_pairs = identify_hot_position_pairs(messages, min_frequency=0.3)
    print(f"  Hot position pairs: {len(hot_pairs)}")

    return output_path

def main():
    """Main execution function."""
    import sys

    print("EAM Structure Heatmap Generator")
    print("="*70)
    print()

    # Check for --all flag to generate all lengths
    if len(sys.argv) > 1 and sys.argv[1] == '--all':
        print("Batch mode: Generating heatmaps for all valid message lengths...")
        print()

        df = load_eam_data()
        if df.empty:
            print("No data available. Exiting.")
            return

        # Find all unique message lengths
        length_counts = df['MSG_LEN'].value_counts().sort_index()

        print(f"Found {len(length_counts)} unique message lengths:")
        for length, count in length_counts.items():
            print(f"  {length:3d} chars: {count:5,} messages")
        print()

        # Get user confirmation
        response = input("Generate heatmaps for all lengths? (y/n): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return

        print()
        print("Generating heatmaps...")
        print("-" * 70)

        output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
        os.makedirs(output_dir, exist_ok=True)

        successful = 0
        failed = 0

        # Get sorted list of all lengths for navigation
        all_lengths = sorted(length_counts.keys())

        for i, target_length in enumerate(all_lengths):
            try:
                print(f"\n{target_length} character messages:")

                # Determine prev/next for navigation
                prev_length = all_lengths[i-1] if i > 0 else None
                next_length = all_lengths[i+1] if i < len(all_lengths)-1 else None

                # Special handling for 30-char: exclude Group 1 and Group 2 by default
                exclude_groups_12 = (target_length == 30)
                if exclude_groups_12:
                    print("  [30-char special case: Excluding Group 1 and Group 2 prefixes]")

                output_path = generate_single_heatmap(df, target_length, exclude_groups_12, prev_length, next_length, all_lengths)

                if output_path:
                    print(f"  ✓ Generated: {output_path}")
                    successful += 1
                else:
                    failed += 1

            except Exception as e:
                print(f"  ✗ Error: {e}")
                failed += 1

        print()
        print("="*70)
        print(f"Batch generation complete!")
        print(f"  Successful: {successful}")
        print(f"  Failed: {failed}")
        print(f"  Output directory: {output_dir}")
        return

    # Check for range argument (e.g., "25-92")
    if len(sys.argv) > 1 and '-' in sys.argv[1] and not sys.argv[1].startswith('--'):
        try:
            range_parts = sys.argv[1].split('-')
            if len(range_parts) == 2:
                start_length = int(range_parts[0])
                end_length = int(range_parts[1])

                if start_length >= end_length:
                    print("Error: Range start must be less than range end")
                    print("Example: python eam_structure_heatmap.py 25-92")
                    return

                print(f"Range mode: Generating heatmaps for {start_length} to {end_length} characters...")
                print()

                df = load_eam_data()
                if df.empty:
                    print("No data available. Exiting.")
                    return

                # Find which lengths in the range have data
                available_lengths = sorted(df['MSG_LEN'].unique())
                target_lengths = [l for l in available_lengths if start_length <= l <= end_length]

                if not target_lengths:
                    print(f"No messages found in range {start_length}-{end_length}")
                    return

                print(f"Found {len(target_lengths)} message lengths in range:")
                for length in target_lengths:
                    count = len(df[df['MSG_LEN'] == length])
                    print(f"  {length:3d} chars: {count:5,} messages")
                print()

                print("Generating heatmaps...")
                print("-" * 70)

                output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'output')
                os.makedirs(output_dir, exist_ok=True)

                successful = 0
                failed = 0

                for i, target_length in enumerate(target_lengths):
                    try:
                        print(f"\n{target_length} character messages:")

                        # Determine prev/next for navigation
                        prev_length = target_lengths[i-1] if i > 0 else None
                        next_length = target_lengths[i+1] if i < len(target_lengths)-1 else None

                        # Special handling for 30-char: exclude Group 1 and Group 2 by default
                        exclude_groups_12 = (target_length == 30)
                        if exclude_groups_12:
                            print("  [30-char special case: Excluding Group 1 and Group 2 prefixes]")

                        output_path = generate_single_heatmap(df, target_length, exclude_groups_12, prev_length, next_length, target_lengths)

                        if output_path:
                            print(f"  ✓ Generated: {output_path}")
                            successful += 1
                        else:
                            failed += 1

                    except Exception as e:
                        print(f"  ✗ Error: {e}")
                        failed += 1

                print()
                print("="*70)
                print(f"Range generation complete!")
                print(f"  Successful: {successful}")
                print(f"  Failed: {failed}")
                print(f"  Output directory: {output_dir}")
                return

            else:
                raise ValueError("Invalid range format")
        except (ValueError, IndexError):
            print("Error: Invalid range format")
            print("Usage: python eam_structure_heatmap.py [start-end]")
            print("Example: python eam_structure_heatmap.py 25-92")
            return

    # Single length mode (existing behavior)
    # Get target length from command line argument or prompt
    if len(sys.argv) > 1:
        try:
            target_length = int(sys.argv[1])
        except ValueError:
            print("Error: Length must be an integer or range (e.g., 25-92)")
            print("Usage: python eam_structure_heatmap.py [length]")
            print("       python eam_structure_heatmap.py [start-end]")
            print("       python eam_structure_heatmap.py --all")
            print("Example: python eam_structure_heatmap.py 30")
            print("Example: python eam_structure_heatmap.py 25-92")
            return
    else:
        # Interactive prompt for IDE users
        while True:
            try:
                target_length_input = input("Enter message length to analyze (number, range like '25-92', or 'all'): ")
                if target_length_input.lower() == 'all':
                    # Restart in batch mode
                    sys.argv.append('--all')
                    main()
                    return
                # Check if it's a range
                if '-' in target_length_input:
                    sys.argv.append(target_length_input)
                    main()
                    return
                # Otherwise try to parse as integer
                target_length = int(target_length_input)
                break
            except ValueError:
                print("Error: Please enter a valid integer, range (e.g., '25-92'), or 'all'")
            except KeyboardInterrupt:
                print("\nExiting.")
                return

    # Check if we should exclude/include Group 1 and Group 2 for 30-char messages
    exclude_groups_12 = False
    if target_length == 30:
        # By default, exclude Group 1 and Group 2 for 30-char messages
        exclude_groups_12 = True
        if len(sys.argv) > 2 and sys.argv[2] == '--include-g1g2':
            exclude_groups_12 = False
            print("Including all groups (Group 1 and Group 2 will be included)...")
        else:
            print("Excluding Group 1 and Group 2 prefixes by default for 30 character messages.")
            print("To include them, use: python eam_structure_heatmap.py 30 --include-g1g2")
        print()

    df = load_eam_data()

    if df.empty:
        print("No data available. Exiting.")
        return

    # Get all available lengths for dropdown
    all_available_lengths = sorted(df['MSG_LEN'].unique())

    print(f"\n{target_length} character messages:")
    output_path = generate_single_heatmap(df, target_length, exclude_groups_12, all_available_lengths=all_available_lengths)

    if output_path:
        print(f"\n✓ Heatmap generated: {output_path}")

        # Load the data for detailed stats
        if exclude_groups_12:
            df_groups = load_group_classifications()
            if not df_groups.empty:
                excluded_prefixes = set(df_groups[df_groups['GROUP'].isin([1, 2])]['PREFIX'].unique())
                full_df = df[(df['MSG_LEN'] == target_length) & (~df['PR'].isin(excluded_prefixes))]
            else:
                full_df = df[df['MSG_LEN'] == target_length]
        else:
            full_df = df[df['MSG_LEN'] == target_length]

        messages = full_df['MESSAGE'].unique().tolist()
        hot_pairs = identify_hot_position_pairs(messages, min_frequency=0.3)

        # Sort hot pairs by frequency
        pair_counts = defaultdict(int)
        for msg in messages:
            for pos1 in range(len(msg)):
                char = msg[pos1]
                for pos2 in range(pos1 + 1, len(msg)):
                    if msg[pos2] == char and (pos1, pos2) in hot_pairs:
                        pair_counts[(pos1, pos2)] += 1

        sorted_pairs = sorted(pair_counts.items(), key=lambda x: x[1], reverse=True)

        if sorted_pairs:
            print("\nTop 10 hot position pairs:")
            for (pos1, pos2), count in sorted_pairs[:10]:
                delta = pos2 - pos1
                pct = (count / len(messages)) * 100
                print(f"  Position {pos1+1}→{pos2+1} (Δ{delta}): {count}/{len(messages)} messages ({pct:.1f}%)")
    else:
        print(f"\n✗ Failed to generate heatmap for {target_length} character messages")

if __name__ == "__main__":
    main()

