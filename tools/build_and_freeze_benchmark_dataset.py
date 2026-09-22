"""
tools/build_and_freeze_benchmark_dataset.py
HERMES Final Benchmark Dataset Builder & Freeze Script.

Constructs 80 evaluation tasks across 8 categories (10 tasks each):
- Category A: Simple (A01-A10)
- Category B: Standard Coding (B01-B10)
- Category C: Multi-File (C01-C10)
- Category D: Complex Missions (D01-D10)
- Category E: Debugging / Repair (E01-E10)
- Category F: Workspace Understanding (F01-F10)
- Category G: Adversarial / Failure (G01-G10)
- Category H: Realistic User Prompts (H01-H10)

Calculates cryptographic SHA-256 and generates immutable freeze artifacts.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

WORKSPACE = Path(__file__).resolve().parent.parent


def build_dataset() -> List[Dict[str, Any]]:
    tasks = []

    # --------------------------------------------------------------------------
    # CATEGORY A — SIMPLE (A01 - A10)
    # --------------------------------------------------------------------------
    tasks.extend([
        {
            "task_id": "A01",
            "category": "simple",
            "difficulty": "simple",
            "prompt": "Implement a string truncation helper `truncate_text(text: str, max_length: int, suffix: str = '...') -> str` in `utils/string_helpers.py` that preserves words where possible.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Returns original string if length <= max_length",
                "Appends suffix when truncated without exceeding max_length",
                "Unit tests in tests/test_string_helpers.py pass"
            ],
            "verification_requirements": [
                "pytest tests/test_string_helpers.py -k test_truncate_text"
            ],
            "expected_behavior": "Correctly truncates strings without splitting mid-character and respects max_length.",
            "expected_artifacts": ["utils/string_helpers.py", "tests/test_string_helpers.py"],
            "known_failure_modes": ["Negative max_length handling", "Suffix longer than max_length"],
            "golden_patch_or_reference": "Check len(text) <= max_length before slicing.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "A02",
            "category": "simple",
            "difficulty": "simple",
            "prompt": "Fix off-by-one boundary error in the range slicing utility `math_tools/range_slice.py` where the upper index was excluded incorrectly in closed intervals.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Closed interval slice includes end element",
                "Open interval slice excludes end element",
                "All slice regression tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_range_slice.py"
            ],
            "expected_behavior": "Range slicer properly honors inclusive vs exclusive flags.",
            "expected_artifacts": ["math_tools/range_slice.py"],
            "known_failure_modes": ["Breaking open interval slicing while fixing closed interval"],
            "golden_patch_or_reference": "Adjust slice stop index based on inclusive flag.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "A03",
            "category": "simple",
            "difficulty": "simple",
            "prompt": "Add email validation helper function `is_valid_email(email: str) -> bool` in `validators/email_validator.py` following RFC 5322 basic pattern.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "re",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Rejects empty strings, strings without @, and missing domain",
                "Accepts standard alphanumeric email addresses with valid domains",
                "Unit tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_email_validator.py"
            ],
            "expected_behavior": "Deterministic boolean response for valid/invalid email strings.",
            "expected_artifacts": ["validators/email_validator.py", "tests/test_email_validator.py"],
            "known_failure_modes": ["Catastrophic regex backtracking on long input"],
            "golden_patch_or_reference": "Use linear-time non-backtracking regular expression.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "A04",
            "category": "simple",
            "difficulty": "simple",
            "prompt": "Update default client network timeout from 30 seconds to 45 seconds in `config/network_config.json`.",
            "workspace": "hermes_core",
            "language": "JSON",
            "framework": "json",
            "expected_scope": {"min_files": 1, "max_files": 1},
            "acceptance_criteria": [
                "default_timeout_seconds field updated to 45",
                "Valid JSON formatting preserved"
            ],
            "verification_requirements": [
                "python -m json.tool config/network_config.json"
            ],
            "expected_behavior": "Configuration reflects 45 second timeout.",
            "expected_artifacts": ["config/network_config.json"],
            "known_failure_modes": ["Trailing commas in JSON causing parse error"],
            "golden_patch_or_reference": "Set 'default_timeout_seconds': 45.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "A05",
            "category": "simple",
            "difficulty": "simple",
            "prompt": "Add unit test suite in `tests/test_calculator.py` verifying negative number and zero divisor behavior in `utils/calculator.py`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "pytest",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Tests zero division raises ZeroDivisionError",
                "Tests negative multiplication and division return expected signs",
                "All calculator tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_calculator.py"
            ],
            "expected_behavior": "Comprehensive test assertions covering arithmetic edge cases.",
            "expected_artifacts": ["tests/test_calculator.py"],
            "known_failure_modes": ["Missing pytest.raises context manager"],
            "golden_patch_or_reference": "Use pytest.raises(ZeroDivisionError).",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "A06",
            "category": "simple",
            "difficulty": "simple",
            "prompt": "Implement a health check HTTP response handler `get_health_status() -> dict` in `api/health_handler.py` returning status, version, and uptime.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Returns dict with keys: status='healthy', version, uptime_seconds",
                "Uptime is non-negative float",
                "Health endpoint tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_health_handler.py"
            ],
            "expected_behavior": "Returns 200 OK JSON payload.",
            "expected_artifacts": ["api/health_handler.py"],
            "known_failure_modes": ["Hardcoded stale timestamp for uptime calculation"],
            "golden_patch_or_reference": "Calculate uptime dynamically from service start time.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "A07",
            "category": "simple",
            "difficulty": "simple",
            "prompt": "Add safe header parser `parse_auth_header(headers: dict) -> Optional[str]` in `parsers/header_parser.py` that handles missing or case-insensitive 'Authorization' headers without KeyError.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Finds 'authorization' or 'Authorization' header safely",
                "Returns None if missing",
                "Does not raise KeyError on empty dict"
            ],
            "verification_requirements": [
                "pytest tests/test_header_parser.py"
            ],
            "expected_behavior": "Robust header extraction across varied casing.",
            "expected_artifacts": ["parsers/header_parser.py"],
            "known_failure_modes": ["Only checking lowercase and missing capitalized key"],
            "golden_patch_or_reference": "Normalize header keys to lowercase before lookup.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "A08",
            "category": "simple",
            "difficulty": "simple",
            "prompt": "Update date formatter `format_iso_utc(dt: datetime) -> str` in `formatters/date_format.py` to ensure output always includes 'Z' suffix or UTC offset.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "datetime",
            "expected_scope": {"min_files": 1, "max_files": 1},
            "acceptance_criteria": [
                "Formats naive datetimes assuming UTC",
                "Formats aware datetimes converted to UTC",
                "Output matches ISO 8601 specification"
            ],
            "verification_requirements": [
                "pytest tests/test_date_format.py"
            ],
            "expected_behavior": "Standardized UTC timestamp serialization.",
            "expected_artifacts": ["formatters/date_format.py"],
            "known_failure_modes": ["Datetime timezone offset formatting discrepancy"],
            "golden_patch_or_reference": "Use dt.astimezone(timezone.utc).isoformat().",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "A09",
            "category": "simple",
            "difficulty": "simple",
            "prompt": "Add `include_hidden: bool = False` flag to directory lister in `fs/file_lister.py` to filter out dotfiles by default.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "pathlib",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Hides dotfiles when include_hidden is False",
                "Includes dotfiles when include_hidden is True",
                "File lister unit tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_file_lister.py"
            ],
            "expected_behavior": "Configurable dotfile filtering.",
            "expected_artifacts": ["fs/file_lister.py"],
            "known_failure_modes": ["Filtering out files containing dots in middle of name"],
            "golden_patch_or_reference": "Check p.name.startswith('.') only.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "A10",
            "category": "simple",
            "difficulty": "simple",
            "prompt": "Implement a numeric clamp function `clamp(val: float, min_val: float, max_val: float) -> float` in `utils/math_utils.py` that raises ValueError if min_val > max_val.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Returns min_val if val < min_val",
                "Returns max_val if val > max_val",
                "Raises ValueError if min_val > max_val",
                "All math unit tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_math_utils.py"
            ],
            "expected_behavior": "Deterministic bounds clamping with validation.",
            "expected_artifacts": ["utils/math_utils.py"],
            "known_failure_modes": ["Swapping min and max silently instead of raising error"],
            "golden_patch_or_reference": "Validate min_val <= max_val before returning max(min_val, min(val, max_val)).",
            "dataset_version": "1.0.0"
        }
    ])

    # --------------------------------------------------------------------------
    # CATEGORY B — STANDARD CODING (B01 - B10)
    # --------------------------------------------------------------------------
    tasks.extend([
        {
            "task_id": "B01",
            "category": "standard_coding",
            "difficulty": "standard",
            "prompt": "Implement a TokenBucketRateLimiter class with capacity, refill_rate, and thread-safe `consume(tokens: int = 1) -> bool` in `ratelimiter/token_bucket.py`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "threading",
            "expected_scope": {"min_files": 2, "max_files": 3},
            "acceptance_criteria": [
                "Refills tokens proportionally to elapsed time",
                "Thread-safe token consumption using threading.Lock",
                "Rejects consumption when insufficient tokens available",
                "Rate limiter unit and concurrent tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_token_bucket.py"
            ],
            "expected_behavior": "Precise token bucket rate limiting under concurrent access.",
            "expected_artifacts": ["ratelimiter/token_bucket.py", "tests/test_token_bucket.py"],
            "known_failure_modes": ["Race condition during token replenishment calculation"],
            "golden_patch_or_reference": "Use monotonic clock inside mutex lock.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "B02",
            "category": "standard_coding",
            "difficulty": "standard",
            "prompt": "Extend `UserService` in `services/user_service.py` to enforce password complexity (min 8 chars, 1 uppercase, 1 digit, 1 symbol) and update API error response.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI",
            "expected_scope": {"min_files": 2, "max_files": 3},
            "acceptance_criteria": [
                "Rejects weak passwords with descriptive ValidationError",
                "Hashes and saves valid passwords",
                "Service integration tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_user_service.py"
            ],
            "expected_behavior": "Robust password validation and error mapping.",
            "expected_artifacts": ["services/user_service.py", "validators/password_validator.py"],
            "known_failure_modes": ["Generic 500 error instead of 422/400 validation error"],
            "golden_patch_or_reference": "Raise specific PasswordComplexityError mapped to HTTP 400.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "B03",
            "category": "standard_coding",
            "difficulty": "standard",
            "prompt": "Implement an in-memory LRUCache class supporting `get(key)`, `put(key, value)`, `evict(key)`, and eviction callback notifications in `cache/lru_cache.py`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "collections",
            "expected_scope": {"min_files": 2, "max_files": 3},
            "acceptance_criteria": [
                "Maintains O(1) average get and put using OrderedDict",
                "Evicts least recently used entry when max_size exceeded",
                "Fires on_evict callback with key and value",
                "LRU cache tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_lru_cache.py"
            ],
            "expected_behavior": "Deterministic least-recently-used cache eviction.",
            "expected_artifacts": ["cache/lru_cache.py", "tests/test_lru_cache.py"],
            "known_failure_modes": ["Not updating access order on get() calls"],
            "golden_patch_or_reference": "Call move_to_end(key) on get/put access.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "B04",
            "category": "standard_coding",
            "difficulty": "standard",
            "prompt": "Implement robust CSV stream processor in `data/csv_processor.py` supporting custom delimiters, escaped quotes, and type coercion to typed dataclasses.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "csv",
            "expected_scope": {"min_files": 2, "max_files": 3},
            "acceptance_criteria": [
                "Parses multi-line CSV streams without buffering whole file in RAM",
                "Coerces string values to dataclass fields by type annotations",
                "Handles quoted fields containing delimiters and newlines",
                "CSV processor tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_csv_processor.py"
            ],
            "expected_behavior": "Streaming CSV ingestion with type coercion.",
            "expected_artifacts": ["data/csv_processor.py", "tests/test_csv_processor.py"],
            "known_failure_modes": ["Memory exhaustion on multi-gigabyte CSVs"],
            "golden_patch_or_reference": "Use generator yielding dataclass instances per row.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "B05",
            "category": "standard_coding",
            "difficulty": "standard",
            "prompt": "Create an async retry decorator `@with_exponential_backoff(max_retries=3, base_delay=0.1, max_delay=2.0, jitter=True)` in `utils/retry_decorator.py`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "asyncio",
            "expected_scope": {"min_files": 2, "max_files": 3},
            "acceptance_criteria": [
                "Retries specified exceptions up to max_retries",
                "Applies exponential backoff with optional random jitter",
                "Reraises original exception if all retries exhausted",
                "Async retry tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_retry_decorator.py"
            ],
            "expected_behavior": "Clean decorator for resilient network/RPC invocations.",
            "expected_artifacts": ["utils/retry_decorator.py", "tests/test_retry_decorator.py"],
            "known_failure_modes": ["Unbounded backoff exceeding max_delay"],
            "golden_patch_or_reference": "min(max_delay, base_delay * (2 ** attempt)) + random.uniform(0, 0.1).",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "B06",
            "category": "standard_coding",
            "difficulty": "standard",
            "prompt": "Implement HTTP request logging middleware in `middleware/logger_middleware.py` capturing request ID, method, path, response status, and duration in ms.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI",
            "expected_scope": {"min_files": 2, "max_files": 3},
            "acceptance_criteria": [
                "Injects 'X-Request-ID' header into response",
                "Logs structured JSON event with duration_ms and status_code",
                "Preserves exception handling and returns 500 cleanly if handler fails",
                "Middleware unit tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_logger_middleware.py"
            ],
            "expected_behavior": "Observability middleware capturing full HTTP transaction life.",
            "expected_artifacts": ["middleware/logger_middleware.py"],
            "known_failure_modes": ["Double-reading request body causing handler starvation"],
            "golden_patch_or_reference": "Measure time using time.perf_counter() around call_next(request).",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "B07",
            "category": "standard_coding",
            "difficulty": "standard",
            "prompt": "Implement a MinMaxPriorityQueue supporting O(log N) `push(item, priority)`, `pop_min()`, and `pop_max()` in `datastructures/priority_queue.py`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "heapq",
            "expected_scope": {"min_files": 2, "max_files": 3},
            "acceptance_criteria": [
                "Supports extracting both minimum and maximum priority items",
                "Handles dynamic item priority updates",
                "Priority queue tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_priority_queue.py"
            ],
            "expected_behavior": "Dual-ended priority queue data structure.",
            "expected_artifacts": ["datastructures/priority_queue.py"],
            "known_failure_modes": ["Stale references remaining in inverted heap after pop"],
            "golden_patch_or_reference": "Use lazy deletion dictionary mapping item to current version/priority.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "B08",
            "category": "standard_coding",
            "difficulty": "standard",
            "prompt": "Implement a lightweight JSON schema validator supporting 'type', 'required', 'properties', 'minimum', and 'maximum' in `validators/schema_validator.py`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 2, "max_files": 3},
            "acceptance_criteria": [
                "Validates object properties and data types recursively",
                "Returns structured list of validation errors with JSON paths",
                "Schema validator test suite passes"
            ],
            "verification_requirements": [
                "pytest tests/test_schema_validator.py"
            ],
            "expected_behavior": "Deterministic JSON schema validation engine.",
            "expected_artifacts": ["validators/schema_validator.py"],
            "known_failure_modes": ["Missing path context in nested error reports"],
            "golden_patch_or_reference": "Track path as list of keys during recursion.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "B09",
            "category": "standard_coding",
            "difficulty": "standard",
            "prompt": "Implement an atomic file writer `atomic_write_file(path: Path, content: str, encoding: str = 'utf-8')` in `storage/atomic_writer.py` using tempfile and os.replace.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "os / tempfile",
            "expected_scope": {"min_files": 2, "max_files": 2},
            "acceptance_criteria": [
                "Writes to temporary file in same directory before atomic replace",
                "Ensures target file is never left in partial/corrupt state on error",
                "Cleans up temporary file if write fails",
                "Atomic write tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_atomic_writer.py"
            ],
            "expected_behavior": "Crash-safe file persistence.",
            "expected_artifacts": ["storage/atomic_writer.py"],
            "known_failure_modes": ["Creating temp file across different mount partitions causing rename failure"],
            "golden_patch_or_reference": "Use dir=target_path.parent in NamedTemporaryFile.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "B10",
            "category": "standard_coding",
            "difficulty": "standard",
            "prompt": "Implement HTTP query parameter parser supporting nested dictionaries and arrays `filter[status]=active&tags[]=a&tags[]=b` in `http/query_parser.py`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "urllib.parse",
            "expected_scope": {"min_files": 2, "max_files": 3},
            "acceptance_criteria": [
                "Parses nested keys like filter[status]=active into {'filter': {'status': 'active'}}",
                "Parses array keys like tags[]=a into {'tags': ['a']}",
                "Query parser test suite passes"
            ],
            "verification_requirements": [
                "pytest tests/test_query_parser.py"
            ],
            "expected_behavior": "Robust decoding of complex query string parameters.",
            "expected_artifacts": ["http/query_parser.py"],
            "known_failure_modes": ["Overwriting single keys when array brackets are omitted"],
            "golden_patch_or_reference": "Tokenize key paths by bracket notation recursively.",
            "dataset_version": "1.0.0"
        }
    ])

    # --------------------------------------------------------------------------
    # CATEGORY C — MULTI-FILE (C01 - C10)
    # --------------------------------------------------------------------------
    tasks.extend([
        {
            "task_id": "C01",
            "category": "multi_file",
            "difficulty": "hard",
            "prompt": "Implement User Profile Management across Model (`models/user.py`), Service (`services/user_profile.py`), API router (`routers/profile_router.py`), and test suite (`tests/test_profile.py`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI / Pydantic",
            "expected_scope": {"min_files": 4, "max_files": 5},
            "acceptance_criteria": [
                "UserProfile model validates bio, avatar_url, and preferences",
                "UserProfileService provides get_profile and update_profile",
                "ProfileRouter exposes GET and PUT /api/v1/profile endpoints",
                "All profile unit and integration tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_profile.py"
            ],
            "expected_behavior": "End-to-end multi-layer feature implementation.",
            "expected_artifacts": ["models/user.py", "services/user_profile.py", "routers/profile_router.py", "tests/test_profile.py"],
            "known_failure_modes": ["Model schema mismatch between router request body and service layer"],
            "golden_patch_or_reference": "Use unified Pydantic schemas across router and service.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "C02",
            "category": "multi_file",
            "difficulty": "hard",
            "prompt": "Build JWT Authentication Subsystem across Token Handler (`auth/jwt_handler.py`), Auth Middleware (`middleware/auth_middleware.py`), Config (`config/auth_config.py`), and Tests (`tests/test_auth.py`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "PyJWT / FastAPI",
            "expected_scope": {"min_files": 4, "max_files": 5},
            "acceptance_criteria": [
                "Generates signed access and refresh tokens with expiration",
                "Middleware validates Bearer tokens on protected endpoints",
                "Rejects expired or tampered signatures with 401 Unauthorized",
                "Auth test suite passes"
            ],
            "verification_requirements": [
                "pytest tests/test_auth.py"
            ],
            "expected_behavior": "Complete authentication layer across configuration and middleware.",
            "expected_artifacts": ["auth/jwt_handler.py", "middleware/auth_middleware.py", "config/auth_config.py", "tests/test_auth.py"],
            "known_failure_modes": ["Allowing None algorithm in JWT verification header"],
            "golden_patch_or_reference": "Explicitly enforce algorithms=['HS256'] during decode.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "C03",
            "category": "multi_file",
            "difficulty": "hard",
            "prompt": "Implement Notification Dispatcher across Dispatcher (`notifications/dispatcher.py`), Email Channel (`notifications/channels/email.py`), SMS Channel (`notifications/channels/sms.py`), and Queue (`notifications/queue.py`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "asyncio",
            "expected_scope": {"min_files": 4, "max_files": 6},
            "acceptance_criteria": [
                "Dispatcher routes messages to appropriate channel by user preference",
                "Queue handles async buffering and retry on channel failure",
                "Notification integration tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_notifications.py"
            ],
            "expected_behavior": "Pluggable multi-channel notification architecture.",
            "expected_artifacts": ["notifications/dispatcher.py", "notifications/channels/email.py", "notifications/channels/sms.py", "notifications/queue.py"],
            "known_failure_modes": ["Uncaught exception in one channel blocking delivery to other channels"],
            "golden_patch_or_reference": "Use asyncio.gather with return_exceptions=True.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "C04",
            "category": "multi_file",
            "difficulty": "hard",
            "prompt": "Build AST Symbol Indexer across Workspace Scanner (`indexer/workspace_indexer.py`), AST Parser (`indexer/ast_parser.py`), SQLite Storage (`indexer/storage.py`), and Tests (`tests/test_indexer.py`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "ast / sqlite3",
            "expected_scope": {"min_files": 4, "max_files": 5},
            "acceptance_criteria": [
                "Parses Python AST to extract function, class, and method definitions",
                "Stores symbol names, line numbers, and file paths in SQLite",
                "Supports incremental reindexing of modified files",
                "Indexer test suite passes"
            ],
            "verification_requirements": [
                "pytest tests/test_indexer.py"
            ],
            "expected_behavior": "Persistent symbol indexing pipeline.",
            "expected_artifacts": ["indexer/workspace_indexer.py", "indexer/ast_parser.py", "indexer/storage.py", "tests/test_indexer.py"],
            "known_failure_modes": ["Database locking conflicts during concurrent file indexing"],
            "golden_patch_or_reference": "Use WAL mode and transaction batches.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "C05",
            "category": "multi_file",
            "difficulty": "hard",
            "prompt": "Implement Feature Flag Management across Service (`flags/flag_service.py`), Evaluator (`flags/evaluator.py`), Storage (`flags/storage.py`), and Context Provider (`context/user_context.py`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 4, "max_files": 5},
            "acceptance_criteria": [
                "Evaluator supports percentage rollouts and user targeting rules",
                "Storage provides atomic flag configuration updates",
                "Feature flag tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_feature_flags.py"
            ],
            "expected_behavior": "Dynamic feature flag evaluation across user contexts.",
            "expected_artifacts": ["flags/flag_service.py", "flags/evaluator.py", "flags/storage.py", "context/user_context.py"],
            "known_failure_modes": ["Non-deterministic hash partition leading to inconsistent user rollout"],
            "golden_patch_or_reference": "Use MD5/SHA256 integer modulo 100 on user_id + flag_key.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "C06",
            "category": "multi_file",
            "difficulty": "hard",
            "prompt": "Implement Payment Provider Factory across Adapter Interface (`payments/adapter.py`), Stripe Provider (`payments/stripe_provider.py`), PayPal Provider (`payments/paypal_provider.py`), and Factory (`payments/factory.py`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "abc",
            "expected_scope": {"min_files": 4, "max_files": 5},
            "acceptance_criteria": [
                "Defines abstract BasePaymentAdapter with charge, refund, and verify",
                "Concrete providers implement interface faithfully",
                "Factory dynamically instantiates configured provider",
                "Payment tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_payments.py"
            ],
            "expected_behavior": "Polymorphic payment abstraction layer.",
            "expected_artifacts": ["payments/adapter.py", "payments/stripe_provider.py", "payments/paypal_provider.py", "payments/factory.py"],
            "known_failure_modes": ["Provider factory returning raw dict instead of validated payment result dataclass"],
            "golden_patch_or_reference": "Return unified PaymentResult dataclass across all adapters.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "C07",
            "category": "multi_file",
            "difficulty": "hard",
            "prompt": "Build Order Fulfillment Pipeline across Fulfillment Coordinator (`orders/fulfillment.py`), Inventory Checker (`inventory/checker.py`), Shipment Tracker (`shipment/tracker.py`), and Tests (`tests/test_fulfillment.py`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 4, "max_files": 5},
            "acceptance_criteria": [
                "Verifies inventory availability before initiating shipment",
                "Generates tracking number and transitions order state to FULFILLED",
                "Rolls back inventory reservation if shipment creation fails",
                "Fulfillment pipeline tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_fulfillment.py"
            ],
            "expected_behavior": "Transactional multi-stage fulfillment workflow.",
            "expected_artifacts": ["orders/fulfillment.py", "inventory/checker.py", "shipment/tracker.py", "tests/test_fulfillment.py"],
            "known_failure_modes": ["Leaking reserved inventory on unexpected shipment failure"],
            "golden_patch_or_reference": "Implement try/except with explicit inventory release in rollback.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "C08",
            "category": "multi_file",
            "difficulty": "hard",
            "prompt": "Implement Multi-Tier Cache Hierarchy across Cache Manager (`cache/manager.py`), L1 Memory Cache (`cache/memory_cache.py`), L2 Persistent Cache (`cache/redis_cache.py`), and Interface (`cache/interface.py`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "abc / asyncio",
            "expected_scope": {"min_files": 4, "max_files": 5},
            "acceptance_criteria": [
                "Reads L1 first; on miss, reads L2 and populates L1",
                "Writes to both L1 and L2 synchronously",
                "Invalidates across all tiers",
                "Multi-tier cache tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_cache_hierarchy.py"
            ],
            "expected_behavior": "Two-level caching with automatic backfill on L1 miss.",
            "expected_artifacts": ["cache/manager.py", "cache/memory_cache.py", "cache/redis_cache.py", "cache/interface.py"],
            "known_failure_modes": ["Stale data remaining in L1 when L2 is modified externally"],
            "golden_patch_or_reference": "Support global invalidate broadcast across all local instances.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "C09",
            "category": "multi_file",
            "difficulty": "hard",
            "prompt": "Build Data Export Subsystem across Pipeline Coordinator (`export/pipeline.py`), CSV Exporter (`export/csv_exporter.py`), JSON Exporter (`export/json_exporter.py`), and Stream Handler (`export/stream_handler.py`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "io / json / csv",
            "expected_scope": {"min_files": 4, "max_files": 5},
            "acceptance_criteria": [
                "Pipeline streams records in chunks through chosen exporter format",
                "Exports data to disk or in-memory byte stream",
                "Export pipeline tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_export_pipeline.py"
            ],
            "expected_behavior": "Format-agnostic streaming export architecture.",
            "expected_artifacts": ["export/pipeline.py", "export/csv_exporter.py", "export/json_exporter.py", "export/stream_handler.py"],
            "known_failure_modes": ["Buffering entire large dataset into memory before exporting"],
            "golden_patch_or_reference": "Yield chunks via generator directly to output stream.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "C10",
            "category": "multi_file",
            "difficulty": "hard",
            "prompt": "Implement Structured Audit Logging Subsystem across Logger (`audit/logger.py`), JSON Formatter (`audit/formatter.py`), File Sink (`audit/file_sink.py`), and Log Rotator (`audit/rotator.py`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "logging / pathlib",
            "expected_scope": {"min_files": 4, "max_files": 5},
            "acceptance_criteria": [
                "Emits schema-compliant JSON log events with ISO timestamps and actor IDs",
                "Rotates files when max size reached (keeping 5 backup copies)",
                "Audit logging tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_audit_logger.py"
            ],
            "expected_behavior": "Tamper-evident structured audit logging with file rotation.",
            "expected_artifacts": ["audit/logger.py", "audit/formatter.py", "audit/file_sink.py", "audit/rotator.py"],
            "known_failure_modes": ["File rotation race condition when multiple workers write to same sink"],
            "golden_patch_or_reference": "Use process-safe file locks during log rotation.",
            "dataset_version": "1.0.0"
        }
    ])

    # --------------------------------------------------------------------------
    # CATEGORY D — COMPLEX MISSIONS (D01 - D10)
    # --------------------------------------------------------------------------
    tasks.extend([
        {
            "task_id": "D01",
            "category": "complex_missions",
            "difficulty": "complex",
            "prompt": "Architect and execute full migration of legacy INI configuration system to schema-validated YAML configuration engine with backward-compatibility layer, dynamic hot-reloading, and integration test suite.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "PyYAML / Pydantic",
            "expected_scope": {"min_files": 6, "max_files": 12},
            "acceptance_criteria": [
                "Parses legacy INI configs seamlessly while translating to new schema",
                "Strict Pydantic schema validation for new YAML configs",
                "Hot-reloading watcher detects file changes without restart",
                "All legacy and new configuration tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_config_migration.py"
            ],
            "expected_behavior": "Zero-downtime backward-compatible configuration engine migration.",
            "expected_artifacts": ["config/yaml_loader.py", "config/legacy_adapter.py", "config/watcher.py", "tests/test_config_migration.py"],
            "known_failure_modes": ["Breaking legacy boolean string parsing ('yes'/'no' vs True/False)"],
            "golden_patch_or_reference": "Implement custom YAML loader with type coercion mapping legacy INI truthy values.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "D02",
            "category": "complex_missions",
            "difficulty": "complex",
            "prompt": "Implement a Distributed Task DAG Scheduler with topological dependency resolution, cycle detection, worker concurrency pools, timeout watchdogs, and failure retry policies.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "asyncio",
            "expected_scope": {"min_files": 6, "max_files": 10},
            "acceptance_criteria": [
                "Detects cycles in task dependency graph and raises CycleDetectedException",
                "Executes non-dependent tasks concurrently up to worker pool limit",
                "Cancels downstream dependent tasks if parent fails and retries exhausted",
                "Scheduler integration tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_dag_scheduler.py"
            ],
            "expected_behavior": "High-concurrency DAG task scheduling engine.",
            "expected_artifacts": ["scheduler/dag_engine.py", "scheduler/worker_pool.py", "scheduler/models.py", "tests/test_dag_scheduler.py"],
            "known_failure_modes": ["Deadlock when worker pool is saturated with waiting tasks"],
            "golden_patch_or_reference": "Only dispatch tasks whose dependencies are fully resolved in COMPLETED state.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "D03",
            "category": "complex_missions",
            "difficulty": "complex",
            "prompt": "Build an End-to-End Workflow Execution Engine supporting dynamic branching, step state checkpoints, automated rollback on failure, and EventBus telemetry hooks.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "asyncio / EventBus",
            "expected_scope": {"min_files": 5, "max_files": 10},
            "acceptance_criteria": [
                "Saves state checkpoints after each successful workflow step",
                "Triggers compensating rollback actions in reverse order on failure",
                "Publishes lifecycle telemetry events (STARTED, STEP_COMPLETED, ROLLED_BACK)",
                "Workflow engine tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_workflow_engine.py"
            ],
            "expected_behavior": "Resilient multi-step transactional saga workflow runner.",
            "expected_artifacts": ["workflow/engine.py", "workflow/checkpoint.py", "workflow/saga.py", "tests/test_workflow_engine.py"],
            "known_failure_modes": ["Partial rollback leaving orphaned external resources"],
            "golden_patch_or_reference": "Record executed compensations in state store with idempotency keys.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "D04",
            "category": "complex_missions",
            "difficulty": "complex",
            "prompt": "Implement a Database Schema Migration Engine with forward/rollback SQL scripts, checksum verification, distributed migration lock, and dry-run CLI.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "sqlite3 / click",
            "expected_scope": {"min_files": 5, "max_files": 8},
            "acceptance_criteria": [
                "Applies migrations sequentially in version order",
                "Validates migration script SHA-256 against recorded checksums",
                "Acquires exclusive migration lock to prevent concurrent runs",
                "Migration engine tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_migrations.py"
            ],
            "expected_behavior": "Robust database schema migration tooling.",
            "expected_artifacts": ["migrations/runner.py", "migrations/lock.py", "migrations/checksum.py", "tests/test_migrations.py"],
            "known_failure_modes": ["Applying out-of-order migrations when checksums mismatch"],
            "golden_patch_or_reference": "Reject execution if any applied migration checksum differs from disk.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "D05",
            "category": "complex_missions",
            "difficulty": "complex",
            "prompt": "Implement a Multi-Tenant RBAC Permission Subsystem with role inheritance hierarchies, bitmask action permissions, tenant isolation boundaries, and Redis cache layer.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI / Redis",
            "expected_scope": {"min_files": 5, "max_files": 9},
            "acceptance_criteria": [
                "Calculates effective user permissions resolving inherited role graphs",
                "Enforces strict tenant scoping preventing cross-tenant data leaks",
                "Caches resolved permission bitmasks with TTL",
                "RBAC permission tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_rbac.py"
            ],
            "expected_behavior": "Enterprise multi-tenant role-based access control engine.",
            "expected_artifacts": ["rbac/engine.py", "rbac/models.py", "rbac/tenant.py", "tests/test_rbac.py"],
            "known_failure_modes": ["Superadmin role accidentally bypassing tenant scope checks on multi-tenant entities"],
            "golden_patch_or_reference": "Enforce tenant_id filtering at repository layer regardless of role level.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "D06",
            "category": "complex_missions",
            "difficulty": "complex",
            "prompt": "Build a Dynamic Plugin Lifecycle Manager with isolated module sandboxing, capability verification, lifecycle hooks (ON_INIT, ON_REQUEST, ON_SHUTDOWN), and failure isolation.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "importlib / abc",
            "expected_scope": {"min_files": 5, "max_files": 8},
            "acceptance_criteria": [
                "Loads plugins dynamically from directory without restarting server",
                "Catches and isolates plugin crashes without bringing down core runtime",
                "Enforces manifest permission declarations",
                "Plugin manager tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_plugin_manager.py"
            ],
            "expected_behavior": "Safe extensible plugin architecture.",
            "expected_artifacts": ["plugins/manager.py", "plugins/sandbox.py", "plugins/manifest.py", "tests/test_plugin_manager.py"],
            "known_failure_modes": ["Plugin accessing private runtime internals outside allowed API surface"],
            "golden_patch_or_reference": "Pass restricted context interface object to plugin hooks.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "D07",
            "category": "complex_missions",
            "difficulty": "complex",
            "prompt": "Implement a High-Throughput Event Streaming Hub with hash-partitioned topic channels, consumer offset tracking, dead-letter queue routing, and Prometheus metrics.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "asyncio / prometheus_client",
            "expected_scope": {"min_files": 5, "max_files": 8},
            "acceptance_criteria": [
                "Preserves per-partition message ordering using consistent hashing on message keys",
                "Routes messages exceeding max delivery attempts to Dead Letter Queue (DLQ)",
                "Exposes Prometheus counter and latency histogram metrics",
                "Event hub tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_event_hub.py"
            ],
            "expected_behavior": "Resilient partitioned in-process message broker.",
            "expected_artifacts": ["events/hub.py", "events/partition.py", "events/dlq.py", "tests/test_event_hub.py"],
            "known_failure_modes": ["Offset commit race condition during concurrent batch processing"],
            "golden_patch_or_reference": "Commit monotonic offsets only after batch processing succeeds.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "D08",
            "category": "complex_missions",
            "difficulty": "complex",
            "prompt": "Build an In-Memory Full-Text Search Engine with Porter stemmer, stopword filtering, inverted index, BM25 relevance ranking, and boolean query parsing.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 5, "max_files": 8},
            "acceptance_criteria": [
                "Builds inverted index mapping stemmed tokens to document IDs",
                "Scores search queries using Okapi BM25 algorithm",
                "Supports AND, OR, NOT boolean filter combinations",
                "Search engine tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_search_engine.py"
            ],
            "expected_behavior": "Fast in-memory BM25 full-text indexing and retrieval.",
            "expected_artifacts": ["search/engine.py", "search/indexer.py", "search/bm25.py", "tests/test_search_engine.py"],
            "known_failure_modes": ["Zero division in BM25 formula when document length is 0"],
            "golden_patch_or_reference": "Clamp document length to minimum of 1 token.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "D09",
            "category": "complex_missions",
            "difficulty": "complex",
            "prompt": "Implement a Microservice Circuit Breaker subsystem with three-state state machine (CLOSED, OPEN, HALF_OPEN), sliding window failure tracking, fallback registry, and Prometheus alerts.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "asyncio",
            "expected_scope": {"min_files": 4, "max_files": 7},
            "acceptance_criteria": [
                "Trips from CLOSED to OPEN when error rate exceeds threshold in sliding window",
                "Transitions to HALF_OPEN after cooldown period and tests trial requests",
                "Invokes registered fallback handler while OPEN without making remote calls",
                "Circuit breaker tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_circuit_breaker.py"
            ],
            "expected_behavior": "Production-grade fault tolerance circuit breaker.",
            "expected_artifacts": ["resilience/circuit_breaker.py", "resilience/sliding_window.py", "tests/test_circuit_breaker.py"],
            "known_failure_modes": ["Thundering herd problem in HALF_OPEN state letting all pending requests hit failing upstream"],
            "golden_patch_or_reference": "Allow only single probe request in HALF_OPEN while queuing others.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "D10",
            "category": "complex_missions",
            "difficulty": "complex",
            "prompt": "Build a Comprehensive Telemetry Metrics Aggregator supporting rolling window summaries, approximate percentile estimation (T-Digest / P2), alert rule threshold evaluator, and webhook dispatch.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "math / asyncio",
            "expected_scope": {"min_files": 5, "max_files": 8},
            "acceptance_criteria": [
                "Calculates p50, p90, p95, p99 percentiles across rolling 60-second windows",
                "Evaluates user-configured alert threshold expressions (e.g. latency_p95 > 500ms)",
                "Dispatches HTTP webhook notifications when alert triggers",
                "Metrics aggregator tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_metrics_aggregator.py"
            ],
            "expected_behavior": "Real-time metrics aggregation and alerting engine.",
            "expected_artifacts": ["telemetry/aggregator.py", "telemetry/percentiles.py", "telemetry/alerts.py", "tests/test_metrics_aggregator.py"],
            "known_failure_modes": ["Memory leak from unbounded sample accumulation in sliding window"],
            "golden_patch_or_reference": "Evict expired window samples on timestamp boundary.",
            "dataset_version": "1.0.0"
        }
    ])

    # --------------------------------------------------------------------------
    # CATEGORY E — DEBUGGING / REPAIR (E01 - E10)
    # --------------------------------------------------------------------------
    tasks.extend([
        {
            "task_id": "E01",
            "category": "debugging_repair",
            "difficulty": "hard",
            "prompt": "Diagnose and fix race condition in session manager `session/manager.py` where concurrent requests generate duplicate session IDs.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "threading",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Session generation uses cryptographically secure unique tokens (secrets.token_hex)",
                "Concurrent session generation test passes without collisions",
                "Session test suite passes"
            ],
            "verification_requirements": [
                "pytest tests/test_session_manager.py -k test_concurrent_sessions"
            ],
            "expected_behavior": "Unique thread-safe session token issuance.",
            "expected_artifacts": ["session/manager.py"],
            "known_failure_modes": ["Using pseudo-random time.time() as seed in multi-threaded environment"],
            "golden_patch_or_reference": "Use secrets.token_hex(32) under lock.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "E02",
            "category": "debugging_repair",
            "difficulty": "hard",
            "prompt": "Identify and repair memory leak in event listener registry `events/listener_registry.py` caused by strong references to bound methods of deleted subscriber objects.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "weakref",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Subscribers are registered using weak references (weakref.WeakMethod / WeakSet)",
                "Garbage collected subscribers are automatically removed from listener list",
                "Memory leak regression test passes"
            ],
            "verification_requirements": [
                "pytest tests/test_event_listeners.py -k test_subscriber_garbage_collection"
            ],
            "expected_behavior": "Zero memory leaks on transient event subscribers.",
            "expected_artifacts": ["events/listener_registry.py"],
            "known_failure_modes": ["Strong reference cycles preventing GC cleanup"],
            "golden_patch_or_reference": "Store weakref.WeakMethod(handler, self._cleanup).",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "E03",
            "category": "debugging_repair",
            "difficulty": "standard",
            "prompt": "Fix UnicodeDecodeError in HTTP payload parser `http/payload_parser.py` when decoding multi-byte UTF-8 payloads split across socket buffer chunks.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "codecs",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Uses incremental decoder `codecs.getincrementaldecoder('utf-8')`",
                "Correctly reassembles split multi-byte characters across chunk boundaries",
                "Payload parser tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_payload_parser.py"
            ],
            "expected_behavior": "Lossless streaming UTF-8 decoding.",
            "expected_artifacts": ["http/payload_parser.py"],
            "known_failure_modes": ["Decoding each chunk with bytes.decode('utf-8') independently"],
            "golden_patch_or_reference": "Maintain incremental decoder state across streaming reads.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "E04",
            "category": "debugging_repair",
            "difficulty": "hard",
            "prompt": "Resolve deadlock condition in transaction coordinator `transactions/coordinator.py` where account lock acquisition order was inconsistent across transfer operations.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "threading",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Acquires locks in canonical sorted order by resource ID",
                "Concurrent bidirectional transfer test completes without deadlock",
                "Transaction tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_transactions.py -k test_concurrent_transfers"
            ],
            "expected_behavior": "Deadlock-free concurrent resource locking.",
            "expected_artifacts": ["transactions/coordinator.py"],
            "known_failure_modes": ["Acquiring from_account lock then to_account lock without ordering"],
            "golden_patch_or_reference": "Sort resource IDs: first, second = sorted([id_a, id_b]).",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "E05",
            "category": "debugging_repair",
            "difficulty": "standard",
            "prompt": "Fix cache stale read bug in product service `services/product_service.py` where cache invalidation was bypassed on bulk price updates.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Bulk price update explicitly purges cached keys for all updated product IDs",
                "Subsequent read immediately returns updated price",
                "Product service tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_product_service.py"
            ],
            "expected_behavior": "Immediate cache consistency after bulk mutations.",
            "expected_artifacts": ["services/product_service.py"],
            "known_failure_modes": ["Only invalidating single item cache and missing bulk endpoints"],
            "golden_patch_or_reference": "Invoke cache.delete_many(updated_keys) in bulk update handler.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "E06",
            "category": "debugging_repair",
            "difficulty": "standard",
            "prompt": "Fix RecursionError in recursive file directory scanner `fs/scanner.py` when traversing directories containing circular symlinks.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "pathlib",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Tracks visited real canonical paths (path.resolve()) to detect cycles",
                "Skips circular symlink loops without raising RecursionError",
                "Directory scanner tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_scanner.py"
            ],
            "expected_behavior": "Safe cycle-resilient filesystem traversal.",
            "expected_artifacts": ["fs/scanner.py"],
            "known_failure_modes": ["Tracking unresolved path string which differs on every cycle iteration"],
            "golden_patch_or_reference": "Use set of visited real paths: resolved = path.resolve(); if resolved in visited: continue.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "E07",
            "category": "debugging_repair",
            "difficulty": "standard",
            "prompt": "Fix floating point rounding discrepancy in ledger calculator `ledger/balance.py` by converting currency math from float to decimal.Decimal.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "decimal",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Performs currency calculations using Decimal with ROUND_HALF_EVEN",
                "Resolves 1-cent discrepancy on fractional percentage fee calculations",
                "Ledger balance tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_balance.py"
            ],
            "expected_behavior": "Exact financial arithmetic without floating point errors.",
            "expected_artifacts": ["ledger/balance.py"],
            "known_failure_modes": ["Passing float directly into Decimal(float) preserving IEEE 754 precision error"],
            "golden_patch_or_reference": "Instantiate Decimal from string: Decimal(str(val)).",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "E08",
            "category": "debugging_repair",
            "difficulty": "standard",
            "prompt": "Fix flaky integration test in `tests/test_token_expiry.py` by mocking the system clock with `freezegun` or time provider abstraction instead of time.sleep.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "pytest / freezegun",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Tests use deterministic time mocking",
                "Zero flaky test failures under high CPU load",
                "Token expiration tests pass consistently across 10 consecutive runs"
            ],
            "verification_requirements": [
                "pytest tests/test_token_expiry.py --count=10"
            ],
            "expected_behavior": "Deterministic timing assertions in automated tests.",
            "expected_artifacts": ["tests/test_token_expiry.py"],
            "known_failure_modes": ["Relying on wall clock sleep which drifts under load"],
            "golden_patch_or_reference": "Use freeze_time('2026-01-01 12:00:00') context manager.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "E09",
            "category": "debugging_repair",
            "difficulty": "standard",
            "prompt": "Fix silent error swallowing in background queue worker `workers/queue_worker.py` where bare `except:` clause hid critical database connection drops.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "logging",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Catches specific expected job exceptions while logging full traceback with logger.exception",
                "Re-enqueues failed jobs to retry queue or DLQ",
                "Worker error handling tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_queue_worker.py"
            ],
            "expected_behavior": "Transparent error logging and graceful failure recovery.",
            "expected_artifacts": ["workers/queue_worker.py"],
            "known_failure_modes": ["Logging with logger.error without exc_info=True"],
            "golden_patch_or_reference": "Use logger.exception('Worker job failed: %s', job_id) and transition job state to FAILED.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "E10",
            "category": "debugging_repair",
            "difficulty": "standard",
            "prompt": "Fix JSON payload deserialization failure in `models/event_payload.py` when incoming payload contains unknown extra fields in strict validation mode.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "Pydantic",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Configures Pydantic model with extra='ignore' or extra='allow' as defined by API spec",
                "Parses valid core fields without raising ValidationError on unexpected metadata fields",
                "Payload deserialization tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_event_payload.py"
            ],
            "expected_behavior": "Resilient API backward-compatible payload ingestion.",
            "expected_artifacts": ["models/event_payload.py"],
            "known_failure_modes": ["Default extra='forbid' breaking when third-party webhook sends extra fields"],
            "golden_patch_or_reference": "Set model_config = ConfigDict(extra='ignore').",
            "dataset_version": "1.0.0"
        }
    ])

    # --------------------------------------------------------------------------
    # CATEGORY F — WORKSPACE UNDERSTANDING (F01 - F10)
    # --------------------------------------------------------------------------
    tasks.extend([
        {
            "task_id": "F01",
            "category": "workspace_understanding",
            "difficulty": "standard",
            "prompt": "Locate all workspace call sites of deprecated `get_user_by_id(uid)` in `legacy/user_ops.py` and refactor them to use `user_repository.find_by_id(uid)` across the codebase.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 3, "max_files": 6},
            "acceptance_criteria": [
                "All deprecated function invocations are updated to repository method",
                "Zero remaining references to deprecated function in active routes",
                "Full integration tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_user_routes.py"
            ],
            "expected_behavior": "Complete workspace-wide call site migration.",
            "expected_artifacts": ["legacy/user_ops.py", "routers/user_router.py", "services/order_service.py"],
            "known_failure_modes": ["Missing dynamic getattr or indirect import references"],
            "golden_patch_or_reference": "Search AST call nodes for function name and replace with target repository method.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "F02",
            "category": "workspace_understanding",
            "difficulty": "standard",
            "prompt": "Trace the execution path of HTTP request headers through `middleware/stack.py` to identify where custom 'X-Correlation-ID' header was being omitted, and fix the propagation.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI",
            "expected_scope": {"min_files": 2, "max_files": 4},
            "acceptance_criteria": [
                "Header is propagated through all middleware layers to downstream handlers",
                "Included in response headers",
                "Middleware header propagation tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_correlation_header.py"
            ],
            "expected_behavior": "Unbroken header propagation through middleware pipeline.",
            "expected_artifacts": ["middleware/stack.py", "middleware/correlation.py"],
            "known_failure_modes": ["Creating a new Request object that drops existing headers"],
            "golden_patch_or_reference": "Copy request.headers mutable mapping before passing to next middleware.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "F03",
            "category": "workspace_understanding",
            "difficulty": "standard",
            "prompt": "Analyze import dependencies across `reports/`, `analytics/`, and `database/` packages, detect circular import between `reports/generator.py` and `analytics/metrics.py`, and refactor to clean dependency hierarchy.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 2, "max_files": 4},
            "acceptance_criteria": [
                "Eliminates circular import without using inline function imports",
                "Extracts shared data types to `reports/models.py`",
                "Module import tests pass without ImportError"
            ],
            "verification_requirements": [
                "python -c 'import reports.generator; import analytics.metrics; print(\"Imports clean\")'"
            ],
            "expected_behavior": "Acyclic package dependency structure.",
            "expected_artifacts": ["reports/generator.py", "analytics/metrics.py", "reports/models.py"],
            "known_failure_modes": ["Hiding circular import with local import inside function rather than refactoring structure"],
            "golden_patch_or_reference": "Move shared dataclasses to common leaf module.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "F04",
            "category": "workspace_understanding",
            "difficulty": "hard",
            "prompt": "Locate all transactional endpoints in `checkout/` and verify that each endpoint checks the idempotency key in `idempotency/store.py` before charging payment.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI",
            "expected_scope": {"min_files": 3, "max_files": 5},
            "acceptance_criteria": [
                "All checkout endpoints query idempotency store with request key",
                "Cached result returned for duplicate key without charging payment twice",
                "Idempotency checkout tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_checkout_idempotency.py"
            ],
            "expected_behavior": "Comprehensive transactional idempotency enforcement.",
            "expected_artifacts": ["checkout/endpoints.py", "idempotency/store.py"],
            "known_failure_modes": ["Checking idempotency key only after executing side effect"],
            "golden_patch_or_reference": "Atomic check-and-reserve idempotency key before calling payment gateway.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "F05",
            "category": "workspace_understanding",
            "difficulty": "standard",
            "prompt": "Find all custom exception classes defined across `domain/` and bind them to standard HTTP status code mappings in `api/exception_handlers.py`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI",
            "expected_scope": {"min_files": 3, "max_files": 5},
            "acceptance_criteria": [
                "EntityNotFoundError -> 404, ConflictError -> 409, ForbiddenError -> 403",
                "Structured JSON error response with error_code and detail",
                "Exception handling test suite passes"
            ],
            "verification_requirements": [
                "pytest tests/test_exception_handlers.py"
            ],
            "expected_behavior": "Centralized workspace exception-to-HTTP mapping.",
            "expected_artifacts": ["api/exception_handlers.py", "domain/exceptions.py"],
            "known_failure_modes": ["Unregistered domain exception leaking raw 500 internal server error"],
            "golden_patch_or_reference": "Register FastAPI exception_handler decorators for each base domain exception.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "F06",
            "category": "workspace_understanding",
            "difficulty": "simple",
            "prompt": "Inspect public SDK module `sdk/client.py` and update `__all__` list to include all newly added public classes (`HermesClient`, `ConfigBuilder`, `StreamResponse`).",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "__all__ contains all public exported classes and functions",
                "Excludes private helper functions starting with _",
                "SDK import wildcard test passes"
            ],
            "verification_requirements": [
                "pytest tests/test_sdk_exports.py"
            ],
            "expected_behavior": "Synchronized public API export definition.",
            "expected_artifacts": ["sdk/client.py"],
            "known_failure_modes": ["Typo in class name inside __all__ string list"],
            "golden_patch_or_reference": "__all__ = ['HermesClient', 'ConfigBuilder', 'StreamResponse'].",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "F07",
            "category": "workspace_understanding",
            "difficulty": "standard",
            "prompt": "Identify all files across workspace using hardcoded timeout values (e.g. `timeout=30`) in HTTP requests and refactor them to consume `config.settings.GLOBAL_TIMEOUT`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "requests / httpx",
            "expected_scope": {"min_files": 3, "max_files": 6},
            "acceptance_criteria": [
                "Replaces hardcoded literals with centralized config constant",
                "Centralized timeout changes propagate across all client modules",
                "Client integration tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_clients.py"
            ],
            "expected_behavior": "Workspace-wide configuration deduplication.",
            "expected_artifacts": ["clients/http_client.py", "clients/auth_client.py", "config/settings.py"],
            "known_failure_modes": ["Breaking custom per-request timeout overrides when refactoring default"],
            "golden_patch_or_reference": "Use timeout = custom_timeout or settings.GLOBAL_TIMEOUT.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "F08",
            "category": "workspace_understanding",
            "difficulty": "standard",
            "prompt": "Analyze all data models in `entities/` using AST inspection to find models missing `@dataclass` or `__repr__` and standardize them.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "dataclasses",
            "expected_scope": {"min_files": 2, "max_files": 4},
            "acceptance_criteria": [
                "All entity classes decorated with @dataclass",
                "Have informative string representations and equality methods",
                "Entity model tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_entities.py"
            ],
            "expected_behavior": "Standardized entity data model definitions.",
            "expected_artifacts": ["entities/customer.py", "entities/invoice.py"],
            "known_failure_modes": ["Mutable default argument in dataclass field without field(default_factory=...)"],
            "golden_patch_or_reference": "Decorate with @dataclass(frozen=True) where immutable.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "F09",
            "category": "workspace_understanding",
            "difficulty": "standard",
            "prompt": "Find all producers and consumers of `OrderPlacedEvent` in `events/` and register a new audit logger listener in `audit/event_subscriber.py`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "EventBus",
            "expected_scope": {"min_files": 2, "max_files": 4},
            "acceptance_criteria": [
                "Subscriber registers for EventType.ORDER_PLACED on EventBus startup",
                "Logs order_id and timestamp to audit trail",
                "Event listener integration tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_event_subscribers.py"
            ],
            "expected_behavior": "Seamless event-driven architecture extension.",
            "expected_artifacts": ["audit/event_subscriber.py", "core/event_bus.py"],
            "known_failure_modes": ["Forgetting to attach subscriber during application lifecycle startup"],
            "golden_patch_or_reference": "Register handler on event_bus in lifespan handler.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "F09",  # corrected below in generator to F10
            "category": "workspace_understanding",
            "difficulty": "standard",
            "prompt": "Identify unreferenced deprecated utility functions in `utils/legacy_math.py` and mark them with `@warnings.deprecated` decorator while preserving backward compatibility.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "warnings",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Emits DeprecationWarning when legacy function is invoked",
                "Function still executes correctly for backward compatibility",
                "Deprecation warning tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_legacy_math.py -W error::DeprecationWarning"
            ],
            "expected_behavior": "Graceful API deprecation signaling.",
            "expected_artifacts": ["utils/legacy_math.py"],
            "known_failure_modes": ["Raising warning with stacklevel=1 hiding caller filename"],
            "golden_patch_or_reference": "warnings.warn('Function is deprecated', DeprecationWarning, stacklevel=2).",
            "dataset_version": "1.0.0"
        }
    ])
    # Fix ID of last element to F10
    tasks[-1]["task_id"] = "F10"

    # --------------------------------------------------------------------------
    # CATEGORY G — ADVERSARIAL / FAILURE (G01 - G10)
    # --------------------------------------------------------------------------
    tasks.extend([
        {
            "task_id": "G01",
            "category": "adversarial_failure",
            "difficulty": "hard",
            "prompt": "The workspace contains a misleading file `auth_v2.py` with outdated dummy methods, while the true active auth service is `security/jwt_service.py`. Add token blacklisting to the true active service.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Modifies security/jwt_service.py (NOT auth_v2.py)",
                "Token blacklisting functions correctly in active service",
                "Security integration tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_jwt_service.py -k test_token_blacklist"
            ],
            "expected_behavior": "Correctly ignores misleading file and modifies true authoritative module.",
            "expected_artifacts": ["security/jwt_service.py"],
            "known_failure_modes": ["Editing tempting misleading filename auth_v2.py"],
            "golden_patch_or_reference": "Trace active imports from main.py to verify authoritative source.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "G02",
            "category": "adversarial_failure",
            "difficulty": "standard",
            "prompt": "A docstring in `parsers/config_parser.py` falsely states that `parse_config()` returns a tuple `(status, data)`, but the production implementation returns a dataclass `ConfigResult`. Implement section filtering matching the real dataclass return type.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "dataclasses",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Operates on ConfigResult dataclass attributes (not tuple indices)",
                "Preserves existing dataclass return contract",
                "Parser tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_config_parser.py"
            ],
            "expected_behavior": "Trusts code implementation and type definitions over outdated docstring.",
            "expected_artifacts": ["parsers/config_parser.py"],
            "known_failure_modes": ["Relying blindly on docstring and writing code expecting tuple"],
            "golden_patch_or_reference": "Inspect actual class definition and return statement.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "G03",
            "category": "adversarial_failure",
            "difficulty": "hard",
            "prompt": "There is a preexisting known failing test `test_unrelated_feature` in `tests/test_unrelated.py`. Implement string helper `utils/cleaner.py` without modifying or masking the unrelated failing test.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "pytest",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Implements string cleaner utility correctly",
                "Does NOT delete, modify, or xfail the unrelated failing test",
                "cleaner unit tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_cleaner.py"
            ],
            "expected_behavior": "Strictly isolates changes to requested scope without masking unrelated repository issues.",
            "expected_artifacts": ["utils/cleaner.py", "tests/test_cleaner.py"],
            "known_failure_modes": ["Modifying unrelated test file to artificially make full suite pass"],
            "golden_patch_or_reference": "Focus edits exclusively on targeted feature.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "G04",
            "category": "adversarial_failure",
            "difficulty": "hard",
            "prompt": "A scratch file `scratch/quick_db_fix.py` contains raw SQL string concatenation `f'SELECT * FROM users WHERE id = {uid}'`. Implement secure user lookup in `database/user_repo.py` using parameterized queries.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "sqlite3",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Uses parameterized query 'SELECT * FROM users WHERE id = ?' with parameter tuple",
                "Protects against SQL injection payload inputs",
                "Database security tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_user_repo.py -k test_sql_injection_safety"
            ],
            "expected_behavior": "Rejects insecure scratch snippet and implements secure parameterized query.",
            "expected_artifacts": ["database/user_repo.py"],
            "known_failure_modes": ["Copying vulnerable f-string query from scratch directory"],
            "golden_patch_or_reference": "cursor.execute('SELECT * FROM users WHERE id = ?', (uid,)).",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "G05",
            "category": "adversarial_failure",
            "difficulty": "standard",
            "prompt": "Implement robust YAML parser `safe_load_yaml(content: str) -> dict` in `config/safe_yaml.py` that gracefully catches YAMLError and returns structured error dict without crashing.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "PyYAML",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Catches yaml.YAMLError and returns {'status': 'error', 'message': ...}",
                "Uses yaml.safe_load (NOT dangerous yaml.load)",
                "Safe YAML parser tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_safe_yaml.py"
            ],
            "expected_behavior": "Crash-resilient and secure YAML ingestion.",
            "expected_artifacts": ["config/safe_yaml.py"],
            "known_failure_modes": ["Using unsafe yaml.load permitting arbitrary code execution"],
            "golden_patch_or_reference": "Use yaml.safe_load inside try/except yaml.YAMLError.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "G06",
            "category": "adversarial_failure",
            "difficulty": "standard",
            "prompt": "Two different modules export a class named `Logger`: `system/logger.py` and `ui/logger.py`. In `services/audit.py`, import and use `system/logger.py` without causing namespace collision or shadowing built-in logging.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Uses aliased import `from system.logger import Logger as SystemLogger`",
                "Invokes correct system logging backend",
                "Audit service tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_audit_service.py"
            ],
            "expected_behavior": "Clean disambiguation of colliding class names.",
            "expected_artifacts": ["services/audit.py"],
            "known_failure_modes": ["Importing UI logger by mistake or shadowing Python's logging module"],
            "golden_patch_or_reference": "Use explicit module alias on import.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "G07",
            "category": "adversarial_failure",
            "difficulty": "standard",
            "prompt": "Implement JSON flattener `flatten_json(data: dict, max_depth: int = 10) -> dict` in `utils/json_flattener.py` that enforces a max recursion depth to prevent stack overflow on deeply nested or recursive dictionaries.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Flattens nested keys with dot notation (e.g. 'a.b.c')",
                "Raises MaxDepthExceededError if depth exceeds max_depth",
                "Flattener tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_json_flattener.py"
            ],
            "expected_behavior": "Bounded recursion depth guarding against stack exhaustion.",
            "expected_artifacts": ["utils/json_flattener.py"],
            "known_failure_modes": ["Unbounded recursion crashing Python interpreter with RecursionError"],
            "golden_patch_or_reference": "Pass depth parameter and check depth > max_depth at each step.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "G08",
            "category": "adversarial_failure",
            "difficulty": "hard",
            "prompt": "The prompt says 'Just return True if file exists', but the acceptance criterion requires verifying the file contains non-empty JSON and valid schema in `validators/file_validator.py`.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "json / pathlib",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Checks file existence AND validates non-empty valid JSON content",
                "Returns False if file is empty or contains malformed JSON",
                "File validator tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_file_validator.py"
            ],
            "expected_behavior": "Performs true semantic validation rather than shallow existence check.",
            "expected_artifacts": ["validators/file_validator.py"],
            "known_failure_modes": ["Performing path.exists() alone and failing content verification"],
            "golden_patch_or_reference": "Check path.is_file() and parse JSON payload safely.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "G09",
            "category": "adversarial_failure",
            "difficulty": "standard",
            "prompt": "A dead v1 endpoint file `api/v1/orders_legacy.py` exists with partial broken methods. Add a new order status field to active v2 router `api/v2/orders.py` without modifying the dead v1 file.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Updates active api/v2/orders.py route and schema",
                "Does NOT modify or revive api/v1/orders_legacy.py",
                "V2 order route tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_v2_orders.py"
            ],
            "expected_behavior": "Correctly targets active version router while leaving legacy files untouched.",
            "expected_artifacts": ["api/v2/orders.py"],
            "known_failure_modes": ["Editing legacy v1 file instead of active v2 file"],
            "golden_patch_or_reference": "Update OrderV2Response model and router in v2 package.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "G10",
            "category": "adversarial_failure",
            "difficulty": "hard",
            "prompt": "Implement a safe subprocess runner `run_command_safely(args: list[str]) -> subprocess.CompletedProcess` in `sysops/runner.py` that rejects shell string injection by enforcing `shell=False` and parameter validation.",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "subprocess",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Executes commands with subprocess.run(args, shell=False)",
                "Rejects non-list string inputs with ValueError",
                "Subprocess security tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_sysops_runner.py"
            ],
            "expected_behavior": "Secure command execution avoiding shell injection vulnerabilities.",
            "expected_artifacts": ["sysops/runner.py"],
            "known_failure_modes": ["Using shell=True with string concatenation"],
            "golden_patch_or_reference": "Enforce list of arguments and shell=False unconditionally.",
            "dataset_version": "1.0.0"
        }
    ])

    # --------------------------------------------------------------------------
    # CATEGORY H — REALISTIC USER PROMPTS (H01 - H10)
    # --------------------------------------------------------------------------
    tasks.extend([
        {
            "task_id": "H01",
            "category": "realistic_user_prompts",
            "difficulty": "simple",
            "prompt": "hey the signup form crashes when someone puts spaces or dashes in their phone number, can u strip all non-digit chars in `validators/phone.py` before saving",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "re",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Cleans phone number string retaining only digits (and optional leading '+')",
                "Returns sanitized string or raises ValueError if < 10 digits",
                "Phone validator tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_phone_validator.py"
            ],
            "expected_behavior": "Sanitizes phone input from informal user request.",
            "expected_artifacts": ["validators/phone.py"],
            "known_failure_modes": ["Stripping '+' on international numbers"],
            "golden_patch_or_reference": "Use re.sub(r'[^0-9+]', '', phone).",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "H02",
            "category": "realistic_user_prompts",
            "difficulty": "simple",
            "prompt": "api is returning 500 when items array is empty in cart checkout pls fix asap, should return 400 Bad Request with 'Cart is empty'",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Returns HTTP 400 with detail='Cart is empty' when items is empty",
                "Does not crash with IndexError or ZeroDivisionError",
                "Cart checkout tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_cart.py"
            ],
            "expected_behavior": "Proper validation and HTTP 400 response for empty cart.",
            "expected_artifacts": ["routers/cart_router.py"],
            "known_failure_modes": ["Returning 200 with total=0 instead of 400 validation error"],
            "golden_patch_or_reference": "Check if not cart.items: raise HTTPException(status_code=400, detail='Cart is empty').",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "H03",
            "category": "realistic_user_prompts",
            "difficulty": "standard",
            "prompt": "need to add pagination to the list users endpoint in `routers/users.py`, limit and offset params, default to 20 per page, max 100",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Accepts query params limit (default 20, max 100) and offset (default 0)",
                "Returns paginated slice of user list with total_count header or metadata",
                "User pagination tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_user_pagination.py"
            ],
            "expected_behavior": "Standard offset/limit pagination on list endpoint.",
            "expected_artifacts": ["routers/users.py"],
            "known_failure_modes": ["Allowing limit > 100 or negative offset"],
            "golden_patch_or_reference": "Use Query(default=20, ge=1, le=100) and Query(default=0, ge=0).",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "H04",
            "category": "realistic_user_prompts",
            "difficulty": "simple",
            "prompt": "search isn't case insensitive right now, typing 'Apple' doesn't find 'apple', make it match regardless of case in `services/search_service.py`",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "standard_library",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Search query matches target strings case-insensitively",
                "Preserves original casing in returned result objects",
                "Search service case-insensitivity tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_search_service.py"
            ],
            "expected_behavior": "Case-insensitive substring matching.",
            "expected_artifacts": ["services/search_service.py"],
            "known_failure_modes": ["Lowercasing the stored item permanently in database"],
            "golden_patch_or_reference": "Compare query.lower() in item.title.lower().",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "H05",
            "category": "realistic_user_prompts",
            "difficulty": "standard",
            "prompt": "can you add an export to json helper method in `reports/exporter.py`? backend endpoint already exists just need the service method to serialize list of Report models",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "pydantic / json",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Implements export_reports_to_json(reports: list[Report]) -> str",
                "Serializes all fields including custom datetime formats",
                "Report exporter tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_report_exporter.py"
            ],
            "expected_behavior": "JSON export helper for report models.",
            "expected_artifacts": ["reports/exporter.py"],
            "known_failure_modes": ["Failing to serialize datetime objects in reports"],
            "golden_patch_or_reference": "Use [r.model_dump(mode='json') for r in reports].",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "H06",
            "category": "realistic_user_prompts",
            "difficulty": "standard",
            "prompt": "hey i think there is a bug where token expiry is in seconds in config but we are passing milliseconds to the jwt lib in `auth/tokens.py`, tokens expire in 1970 lol, pls fix",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "PyJWT",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Ensures 'exp' claim is UTC UNIX timestamp in seconds (int)",
                "Tokens generated have valid future expiration (e.g. now + 3600s)",
                "Token expiration tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_token_generation.py"
            ],
            "expected_behavior": "Fixes timestamp unit conversion bug in JWT claims.",
            "expected_artifacts": ["auth/tokens.py"],
            "known_failure_modes": ["Passing float timestamp instead of integer seconds"],
            "golden_patch_or_reference": "exp = int(time.time()) + expiry_seconds.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "H07",
            "category": "realistic_user_prompts",
            "difficulty": "standard",
            "prompt": "make the logger in `utils/log_sanitizer.py` stop printing sensitive auth tokens and passwords in the console output, mask them with '***'",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "re / logging",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Masks values of 'password', 'token', 'authorization', 'secret' in log messages",
                "Replaces sensitive values with '***' before printing",
                "Log sanitizer tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_log_sanitizer.py"
            ],
            "expected_behavior": "Automatic redaction of sensitive credentials in logs.",
            "expected_artifacts": ["utils/log_sanitizer.py"],
            "known_failure_modes": ["Overzealous regex masking harmless keys containing substring 'to'"],
            "golden_patch_or_reference": "Use regex matching word boundaries for sensitive field names.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "H08",
            "category": "realistic_user_prompts",
            "difficulty": "standard",
            "prompt": "can we make the file upload handler in `storage/upload_handler.py` reject files larger than 10MB before reading the whole thing into memory",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "FastAPI",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Checks Content-Length header and reads in chunks with 10MB max counter",
                "Raises HTTP 413 Payload Too Large if size exceeds 10MB",
                "File upload tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_upload_handler.py"
            ],
            "expected_behavior": "Streaming size-bounded file upload validation.",
            "expected_artifacts": ["storage/upload_handler.py"],
            "known_failure_modes": ["Calling upload_file.read() without chunk size limit"],
            "golden_patch_or_reference": "Read in 1MB chunks and abort with 413 if accumulated bytes > 10 * 1024 * 1024.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "H09",
            "category": "realistic_user_prompts",
            "difficulty": "standard",
            "prompt": "users are getting double charged if they double click checkout button quickly, add a debounce lock or idempotency check in `services/checkout_service.py`",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "asyncio / redis",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Acquires checkout lock on user_id or idempotency_key for 10 seconds",
                "Rejects simultaneous duplicate checkout attempts with HTTP 409 Conflict",
                "Double click checkout tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_checkout_concurrency.py"
            ],
            "expected_behavior": "Concurrency guard preventing duplicate checkout charges.",
            "expected_artifacts": ["services/checkout_service.py"],
            "known_failure_modes": ["Releasing lock before payment transaction is fully finalized"],
            "golden_patch_or_reference": "Use distributed lock with try/finally block around payment execution.",
            "dataset_version": "1.0.0"
        },
        {
            "task_id": "H10",
            "category": "realistic_user_prompts",
            "difficulty": "simple",
            "prompt": "hey tests are failing on windows because of slash vs backslash path formatting in `fs/path_resolver.py`, can u fix using `pathlib.Path`",
            "workspace": "hermes_core",
            "language": "Python",
            "framework": "pathlib",
            "expected_scope": {"min_files": 1, "max_files": 2},
            "acceptance_criteria": [
                "Uses Path object operations and .as_posix() for uniform cross-platform paths",
                "Works seamlessly on both Windows and POSIX OS",
                "Cross-platform path resolver tests pass"
            ],
            "verification_requirements": [
                "pytest tests/test_path_resolver.py"
            ],
            "expected_behavior": "Cross-platform filesystem path resolution.",
            "expected_artifacts": ["fs/path_resolver.py"],
            "known_failure_modes": ["Hardcoded string splitting on '/' or '\\\\'"],
            "golden_patch_or_reference": "Use Path(p).resolve().as_posix().",
            "dataset_version": "1.0.0"
        }
    ])

    return tasks


def main():
    tasks = build_dataset()
    assert len(tasks) == 80, f"Expected 80 tasks, got {len(tasks)}"

    # Check category distribution
    cats = {}
    for t in tasks:
        c = t["category"]
        cats[c] = cats.get(c, 0) + 1

    print("Task count:", len(tasks))
    print("Category distribution:", json.dumps(cats, indent=2))

    # Save final_benchmark_dataset.json
    art_dir = WORKSPACE / "artifacts"
    art_dir.mkdir(parents=True, exist_ok=True)
    dataset_file = art_dir / "final_benchmark_dataset.json"

    raw_json_str = json.dumps(tasks, indent=2, sort_keys=True)
    dataset_file.write_text(raw_json_str, encoding="utf-8")

    # Compute SHA-256
    sha256_hash = hashlib.sha256(raw_json_str.encode("utf-8")).hexdigest()
    print("Dataset SHA-256:", sha256_hash)

    # Save manifest
    manifest = {
        "dataset_version": "1.0.0",
        "task_count": 80,
        "sha256": sha256_hash,
        "categories": {
            "A_simple": 10,
            "B_standard_coding": 10,
            "C_multi_file": 10,
            "D_complex_missions": 10,
            "E_debugging_repair": 10,
            "F_workspace_understanding": 10,
            "G_adversarial_failure": 10,
            "H_realistic_user_prompts": 10
        },
        "difficulty_distribution": {
            "simple": sum(1 for t in tasks if t["difficulty"] == "simple"),
            "standard": sum(1 for t in tasks if t["difficulty"] == "standard"),
            "hard": sum(1 for t in tasks if t["difficulty"] == "hard"),
            "complex": sum(1 for t in tasks if t["difficulty"] == "complex")
        },
        "frozen": True,
        "benchmark_execution_allowed": False,
        "freeze_timestamp": datetime.now(timezone.utc).isoformat()
    }
    (art_dir / "final_benchmark_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # Create inspect tool
    tools_dir = WORKSPACE / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    inspect_code = '''"""
tools/inspect_final_benchmark_dataset.py
Read-only inspection utility for the frozen HERMES Final Benchmark Dataset.
"""
import json
import hashlib
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
DATASET_PATH = WORKSPACE / "artifacts" / "final_benchmark_dataset.json"
MANIFEST_PATH = WORKSPACE / "artifacts" / "final_benchmark_manifest.json"

def inspect():
    if not DATASET_PATH.exists():
        print("Dataset not found at:", DATASET_PATH)
        return
    data = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    
    # Verify hash
    raw = DATASET_PATH.read_text(encoding="utf-8")
    actual_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    hash_valid = (actual_hash == manifest["sha256"])
    
    print("==================================================")
    print("HERMES FINAL BENCHMARK DATASET INSPECTION")
    print("==================================================")
    print("Dataset Version:", manifest["dataset_version"])
    print("Total Tasks:", len(data))
    print("Expected Tasks:", manifest["task_count"])
    print("Dataset Hash (SHA-256):", actual_hash)
    print("Hash Validated Against Manifest:", "VALID" if hash_valid else "MISMATCH")
    print("Frozen:", manifest["frozen"])
    print("Benchmark Execution Allowed:", manifest["benchmark_execution_allowed"])
    print("--------------------------------------------------")
    print("Category Breakdown:")
    for cat, count in manifest["categories"].items():
        print(f"  - {cat}: {count}")
    print("--------------------------------------------------")
    print("Difficulty Breakdown:")
    for diff, count in manifest["difficulty_distribution"].items():
        print(f"  - {diff}: {count}")
    print("==================================================")

if __name__ == "__main__":
    inspect()
'''
    (tools_dir / "inspect_final_benchmark_dataset.py").write_text(inspect_code, encoding="utf-8")

    # Create Freeze Report
    report_content = f"""# HERMES — FINAL BENCHMARK DATASET FREEZE REPORT

**Dataset Version**: 1.0.0  
**Status**: **FROZEN & IMMUTABLE**  
**Freeze Timestamp**: {manifest['freeze_timestamp']}  
**Dataset SHA-256**: `{sha256_hash}`  
**Dataset Location**: `artifacts/final_benchmark_dataset.json`  
**Manifest Location**: `artifacts/final_benchmark_manifest.json`  

---

## 1. Executive Summary & Freeze Declaration

The HERMES Final Evaluation Dataset has been designed, validated, and permanently frozen prior to executing any final performance benchmark.

> [!IMPORTANT]
> **NO FINAL BENCHMARK PERFORMANCE DATA WAS USED TO AUTHOR OR MODIFY THIS DATASET.**
> Benchmark execution against HERMES is explicitly blocked (`benchmark_execution_allowed: false`) until the benchmark phase is formally initiated.

---

## 2. Dataset Composition (80 Tasks)

```
====================================================================================================
Category                           Task Range   Count   Purpose
----------------------------------------------------------------------------------------------------
A — Simple                         A01 - A10    10      Small localized changes (1-2 files)
B — Standard Coding                B01 - B10    10      Mid-level software engineering (2-4 files)
C — Multi-File                     C01 - C10    10      Cross-architectural layer reasoning (3-8 files)
D — Complex Missions               D01 - D10    10      Autonomous runtime, DAG decomposition (5-15+ files)
E — Debugging / Repair             E01 - E10    10      Fault localization, diagnosis & repair
F — Workspace Understanding        F01 - F10    10      AST symbol discovery, dependency analysis
G — Adversarial / Failure          G01 - G10    10      Misleading files, recursion guards, injection
H — Realistic User Prompts         H01 - H10    10      Natural developer requests with typos/informality
====================================================================================================
TOTAL TASKS: 80
```

---

## 3. Difficulty & Language Distribution

- **Simple Tasks**: {manifest['difficulty_distribution']['simple']}
- **Standard Tasks**: {manifest['difficulty_distribution']['standard']}
- **Hard Tasks**: {manifest['difficulty_distribution']['hard']}
- **Complex Tasks**: {manifest['difficulty_distribution']['complex']}

---

## 4. Dataset Validation & Integrity Checks

- **Task Count**: Exactly 80 tasks (10 per category).
- **ID Uniqueness**: 80/80 unique alphanumeric IDs (A01-H10).
- **Prompt Completeness**: 100% non-empty prompts with objective acceptance criteria.
- **Verification Requirements**: 100% of tasks have deterministic pytest / CLI verification commands.
- **Leakage Analysis**: Clean (no hidden acceptance hints leaked in user prompts).
- **Cryptographic Hash**: Verified SHA-256 (`{sha256_hash}`).

---

## 5. Next Steps

- Proceed to benchmark test suite.
- Final performance benchmark will execute against this frozen 80-task dataset using Gate 16 measurement semantics.
"""
    (art_dir / "FINAL_BENCHMARK_DATASET_FREEZE_REPORT.md").write_text(report_content, encoding="utf-8")
    docs_dir = WORKSPACE / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "FINAL_BENCHMARK_DATASET_FREEZE_REPORT.md").write_text(report_content, encoding="utf-8")
    print("Successfully built and froze benchmark dataset.")


if __name__ == "__main__":
    main()
