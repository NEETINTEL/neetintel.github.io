"""
Shared data loader for EAM structure research.
Reads from CSV (fast) or Excel (fallback), with consistent filtering.
"""

import pandas as pd
import os

def load_eam_data(prefer_csv=True):
    """
    Load EAM data from CSV or Excel.

    Parameters:
    -----------
    prefer_csv : bool
        If True, try CSV first then fall back to Excel.
        If False, use Excel directly.

    Returns:
    --------
    pd.DataFrame with columns: DATE, UTC, CALLSIGN, PR, Q, MESSAGE, E6, MSG_LEN
    Filtered to exclude backslash/asterisk entries and NaN messages.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    csv_path = os.path.join(script_dir, 'data', 'set-all.csv')
    excel_path = '/SHORTWAVES.xlsx'

    df = None
    source = None

    # Try CSV first if preferred
    if prefer_csv and os.path.exists(csv_path):
        try:
            print(f"Loading data from CSV: {csv_path}")
            df = pd.read_csv(csv_path, encoding='utf-8-sig')  # utf-8-sig handles BOM
            source = 'CSV'
        except Exception as e:
            print(f"Error reading CSV: {e}")
            print("Falling back to Excel...")

    # Fall back to Excel if CSV failed or not preferred
    if df is None:
        try:
            print(f"Loading data from Excel: {excel_path}")
            df = pd.read_excel(excel_path, sheet_name='SET-ALL')
            source = 'Excel'
        except FileNotFoundError:
            print(f"Error: Excel file not found at {excel_path}")
            return pd.DataFrame()
        except Exception as e:
            print(f"Error reading Excel file: {e}")
            return pd.DataFrame()

    if df is None or df.empty:
        print("No data loaded.")
        return pd.DataFrame()

    print(f"Loaded {len(df):,} rows from {source}")

    # Apply standard filtering
    # Filter out messages with '\' or '*' in column Q
    df_filtered = df[~df['Q'].astype(str).str.contains('[\\\\*]', na=False, regex=True)]

    # Remove rows where MESSAGE is NaN
    df_filtered = df_filtered.dropna(subset=['MESSAGE'])

    # Exclude messages with '?', '_', or '.' in the message transcription (incomplete/uncertain transcriptions)
    df_filtered = df_filtered[~df_filtered['MESSAGE'].astype(str).str.contains('[?_.]', na=False, regex=True)]

    # Add message length column
    df_filtered['MSG_LEN'] = df_filtered['MESSAGE'].str.len()

    print(f"After filtering: {len(df_filtered):,} valid messages")

    # Return only the columns we need for analysis
    return df_filtered[['DATE', 'UTC', 'CALLSIGN', 'PR', 'Q', 'MESSAGE', 'E6', 'MSG_LEN']].copy()

def get_messages_by_length(df, target_length):
    """
    Filter dataframe to specific message length and return unique messages.

    Parameters:
    -----------
    df : pd.DataFrame
        Output from load_eam_data()
    target_length : int
        Message length to filter for

    Returns:
    --------
    list of unique message strings
    """
    length_df = df[df['MSG_LEN'] == target_length]

    if length_df.empty:
        return []

    messages = length_df['MESSAGE'].tolist()
    unique_messages = sorted(list(set(messages)))

    return unique_messages

def get_message_stats(df, target_length):
    """
    Get statistics for a specific message length.

    Returns:
    --------
    dict with keys: total_count, unique_count, date_range, messages, full_df
    """
    length_df = df[df['MSG_LEN'] == target_length]

    if length_df.empty:
        return None

    messages = length_df['MESSAGE'].tolist()
    unique_messages = sorted(list(set(messages)))

    return {
        'total_count': len(messages),
        'unique_count': len(unique_messages),
        'date_range': (length_df['DATE'].min(), length_df['DATE'].max()),
        'messages': unique_messages,
        'full_df': length_df
    }

if __name__ == "__main__":
    # Test the loader
    print("Testing data loader...\n")

    df = load_eam_data()

    if not df.empty:
        print(f"\nMessage length distribution (top 20):")
        length_counts = df['MSG_LEN'].value_counts().sort_index()
        for length, count in length_counts.head(20).items():
            print(f"  {length:3d} chars: {count:5,} messages")

        # Test getting specific length
        print(f"\n51-character messages:")
        stats = get_message_stats(df, 51)
        if stats:
            print(f"  Total: {stats['total_count']}, Unique: {stats['unique_count']}")
            print(f"  Date range: {stats['date_range'][0]} to {stats['date_range'][1]}")

