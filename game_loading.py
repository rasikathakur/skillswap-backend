from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from supabase import create_client
import os
from dotenv import load_dotenv

load_dotenv()

router = APIRouter(prefix="/api/games", tags=["games"])

# Initialize Supabase client
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


class ConceptMatchRequest(BaseModel):
    language: str
    level: str


class ConceptMatchQuestion(BaseModel):
    id: str
    question: str
    options: list[str]
    correct: str
    coding_language: str
    level: str


@router.post("/concept-match/load")
async def load_concept_match(request: ConceptMatchRequest):
    """
    Fetch concept match MCQs from Supabase based on language and level.
    Returns a list of questions with options and correct_option letter (A, B, C, D).
    """
    try:
        # Query the concept_match table
        response = supabase.table("concept_match").select(
            "id, question, A, B, C, D, correct_option, coding_language, level"
        ).eq("coding_language", request.language).eq("level", request.level).execute()

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail=f"No questions found for {request.language} at {request.level} level"
            )

        # Transform the response into the format needed by the frontend
        questions = []
        for row in response.data:
            # Build options list from A, B, C, D (only non-null values)
            options = []
            option_mapping = {}  # Maps option index (as NUMBER) to letter (A, B, C, D)
            
            for option_letter in ['A', 'B', 'C', 'D']:
                if row[option_letter]:
                    index = len(options)
                    option_mapping[index] = option_letter  # Use numeric key, not string
                    options.append(row[option_letter])
            
            q = {
                "id": row['id'],
                "question": row['question'],
                "options": options,
                "correct": row['correct_option'],  # Store the option letter (A, B, C, D)
                "option_mapping": option_mapping,  # Index to letter mapping with NUMERIC keys
                "coding_language": row['coding_language'],
                "level": row['level']
            }
            print(f"Question: {row['question']}")
            print(f"  A={row.get('A')}, B={row.get('B')}, C={row.get('C')}, D={row.get('D')}")
            print(f"  correct_option from DB: {row['correct_option']}")
            print(f"  options list: {options}")
            print(f"  option_mapping: {option_mapping}")
            print(f"  final q.correct: {q['correct']}")
            questions.append(q)

        return {
            "status": "success",
            "total": len(questions),
            "language": request.language,
            "level": request.level,
            "questions": questions
        }

    except Exception as e:
        # Preserve explicit HTTPExceptions (like 404) thrown above,
        # re-raise them so FastAPI returns the correct status code.
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


# Level titles for different language categories
PROGRAMMING_LEVELS = [
    "Fibonacci Series",
    "Prime Number",
    "Reverse String",
    "Matrix Multiplication",
    "Removing Duplicates",
    "Palindrome",
    "Factorial",
    "Armstrong",
    "GCD",
    "LCM"
]

DATABASE_LEVELS = [
    "Second Highest Salary",
    "Department Highest Salary",
    "Frequent Customers",
    "Above Class Average",
    "Duplicate Emails",
    "Pivot Marks",
    "Top Rated Products",
    "Low Scoring Students",
    "Bought and Reviewed",
    "Update Electronics Price"
]


class DebuggingRaceRequest(BaseModel):
    language: str
    level: int  # 1-10


@router.post("/debugging-race/load")
async def load_debugging_race(request: DebuggingRaceRequest):
    """
    Fetch debugging race challenges from Supabase based on language and level.
    Level is 1-10, title is determined by language type.
    """
    try:
        # Determine if it's a database language or programming language
        is_database = request.language in ['SQL', 'NoSQL']
        levels = DATABASE_LEVELS if is_database else PROGRAMMING_LEVELS
        
        # Validate level
        if request.level < 1 or request.level > 10:
            raise HTTPException(
                status_code=400,
                detail="Level must be between 1 and 10"
            )
        
        # Get the title for this level
        level_title = levels[request.level - 1]  # Convert 1-based to 0-based index
        
        # Query the debugging_race table
        response = supabase.table("debugging_race").select(
            "id, title, coding_language, code, total_lines, buggy_line, option_a, option_b, option_c, option_d, correct_option, explanation"
        ).eq("coding_language", request.language).eq("title", level_title).execute()

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail=f"No challenge found for {request.language} at level {request.level} ({level_title})"
            )

        # Return the first matching question (there should be only one per level)
        row = response.data[0]
        
        # Build option_mapping: maps letter (A/B/C/D) to text value
        option_mapping = {
            "A": row['option_a'],
            "B": row['option_b'],
            "C": row['option_c'],
            "D": row['option_d']
        }
        
        return {
            "status": "success",
            "language": request.language,
            "level": request.level,
            "level_title": level_title,
            "challenge": {
                "id": row['id'],
                "title": row['title'],
                "coding_language": row['coding_language'],
                "code": row['code'],
                "total_lines": row['total_lines'],
                "buggy_line": row['buggy_line'],
                "option_mapping": option_mapping,
                "correct_option": row['correct_option'],
                "explanation": row['explanation']
            }
        }

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


class CodeCompletionRequest(BaseModel):
    language: str
    level: str  # "EASY", "MEDIUM", or "HARD"


@router.post("/code-completion/load")
async def load_code_completion(request: CodeCompletionRequest):
    """
    Fetch code completion question from Supabase based on language and level.
    Returns incomplete_code (text with 'drop' placeholders), complete_code, missing_tokens array and correct_token_order array.
    """
    try:
        response = supabase.table("code_completion_questions").select(
            "id, title, coding_language, level, incomplete_code, complete_code, missing_tokens, correct_token_order"
        ).eq("coding_language", request.language).eq("level", request.level).execute()

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail=f"No code completion question found for {request.language} at {request.level} level"
            )

        row = response.data[0]

        return {
            "status": "success",
            "language": request.language,
            "level": request.level,
            "question": {
                "id": row['id'],
                "title": row['title'],
                "coding_language": row['coding_language'],
                "level": row['level'],
                "incomplete_code": row['incomplete_code'],
                "complete_code": row['complete_code'],
                "missing_tokens": row['missing_tokens'],
                "correct_token_order": row['correct_token_order']
            }
        }

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))


class CodeRearrangementRequest(BaseModel):
    language: str
    level: str  # "EASY", "MEDIUM", or "HARD"


@router.post("/code-rearrangement/load")
async def load_code_rearrangement(request: CodeRearrangementRequest):
    """
    Fetch code rearrangement questions from Supabase based on language and level.
    Returns code_lines array (original order) and also provides shuffled version for display.
    """
    try:
        # Query the code_rearrangement_questions table
        response = supabase.table("code_rearrangement_questions").select(
            "id, title, coding_language, level, code_lines"
        ).eq("coding_language", request.language).eq("level", request.level).execute()

        if not response.data:
            raise HTTPException(
                status_code=404,
                detail=f"No code rearrangement question found for {request.language} at {request.level} level"
            )

        # Return the first matching question
        row = response.data[0]
        original_lines = row['code_lines']
        
        # Shuffle the lines for display
        import random
        shuffled_lines = original_lines.copy()
        random.shuffle(shuffled_lines)
        
        return {
            "status": "success",
            "language": request.language,
            "level": request.level,
            "question": {
                "id": row['id'],
                "title": row['title'],
                "coding_language": row['coding_language'],
                "level": row['level'],
                "original_lines": original_lines,
                "shuffled_lines": shuffled_lines
            }
        }

    except Exception as e:
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
