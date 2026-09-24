"""Phase 7 multi-evidence matching engine and teaching workflow."""
from .config import Phase7Config
from .matcher import Phase7Matcher, MatchResult
from .teaching_session import TeachingSessionManager, TeachingState
from .template_induction import SyntaxTemplate, induce_template
