"""
Check if there are rows in Supabase with NULL values affecting the mapping
"""

sample_data = [
    {
        'A': '16',
        'B': '13',
        'C': '11',
        'D': None,
        'correct_option': 'C',
    },
    {
        'A': 'output()',
        'B': 'print()',
        'C': 'printf()',
        'D': 'show()',
        'correct_option': 'C',
    },
]

for idx, row in enumerate(sample_data):
    print(f"\n=== Row {idx + 1} ===")
    print(f"DB values: A={row['A']}, B={row['B']}, C={row['C']}, D={row['D']}")
    print(f"correct_option in DB: {row['correct_option']}")
    
    # Build options like the backend does
    options = []
    option_mapping = {}
    
    for option_letter in ['A', 'B', 'C', 'D']:
        if row[option_letter]:
            option_mapping[len(options)] = option_letter
            options.append(row[option_letter])
    
    print(f"Built options: {options}")
    print(f"option_mapping: {option_mapping}")
    
    # What does "C" map to?
    try:
        if "C" in option_mapping.values():
            for idx_val, letter in option_mapping.items():
                if letter == "C":
                    print(f"✓ Correct letter 'C' is at index {idx_val} in options list")
                    print(f"  Option at index {idx_val}: '{options[idx_val]}'")
        else:
            print(f"✗ ERROR: Correct letter 'C' is NOT in option_mapping!")
            print(f"  Available letters: {list(option_mapping.values())}")
    except Exception as e:
        print(f"✗ ERROR: {e}")
