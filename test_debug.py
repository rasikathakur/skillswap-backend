"""Debug script to test the option_mapping logic"""

# Simulate your data
row = {
    'id': '123',
    'question': 'What is 5 + 3 * 2?',
    'A': '16',
    'B': '13',
    'C': '11',
    'D': None,  # D is NULL
    'correct_option': 'C',
    'coding_language': 'Python',
    'level': 'EASY'
}

# Simulate backend logic
options = []
option_mapping = {}

for option_letter in ['A', 'B', 'C', 'D']:
    if row[option_letter]:
        option_mapping[len(options)] = option_letter
        options.append(row[option_letter])

print("=== BACKEND SIMULATION ===")
print(f"Question: {row['question']}")
print(f"Options from DB: A={row['A']}, B={row['B']}, C={row['C']}, D={row['D']}")
print(f"Options list built: {options}")
print(f"Option mapping: {option_mapping}")
print(f"Correct answer in DB: {row['correct_option']}")
print()

# User selects "11" (third option in the list, index 2)
user_chosen_text = "11"
user_chosen_index = options.index(user_chosen_text)

print("=== FRONTEND SELECTION ===")
print(f"User selected: '{user_chosen_text}'")
print(f"Index in options list: {user_chosen_index}")
print()

# Frontend validation
chosen_letter = option_mapping[user_chosen_index]
correct_letter = row['correct_option']

print("=== VALIDATION ===")
print(f"Chosen index {user_chosen_index} maps to letter: {chosen_letter}")
print(f"Correct letter from DB: {correct_letter}")
print(f"Match? {chosen_letter == correct_letter}")
print()

# Check for any type mismatches
print("=== TYPE CHECK ===")
print(f"chosen_letter type: {type(chosen_letter).__name__} = {repr(chosen_letter)}")
print(f"correct_letter type: {type(correct_letter).__name__} = {repr(correct_letter)}")
print(f"Are they equal? {chosen_letter == correct_letter}")
print(f"String comparison: '{chosen_letter}' === '{correct_letter}': {str(chosen_letter) == str(correct_letter)}")
