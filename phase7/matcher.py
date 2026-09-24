"""Core Phase 7 matcher: deterministic five-signal fusion with BGE fallback."""
from __future__ import annotations
from dataclasses import asdict
from typing import Any
from .config import Phase7Config
from .schemas import MatchResult, CLIExample
from .tokenizer import tokenize_cli
from .template_induction import SyntaxTemplate, syntax_score
from .context_scorer import context_score
from .value_semantics import infer_value, value_semantics_score, negation_matches
from .framework_fit import framework_fit
from .fusion import fuse
from .precedent import PrecedentStore
from .bge_matcher import BGEMatcher

class Phase7Matcher:
    def __init__(self, controls: dict[str, dict], config: Phase7Config | None=None,
                 precedent: PrecedentStore | None=None, bge: BGEMatcher | None=None):
        self.controls=controls
        self.config=config or Phase7Config()
        self.precedent=precedent or PrecedentStore()
        self.bge=bge

    def _evaluate_candidate(self, line, vendor, canonical_field, template, examples, context_path=None):
        control=self.controls[canonical_field]
        ex_inferred=[infer_value(tokenize_cli(e.raw_line)) for e in examples]
        candidate=infer_value(tokenize_cli(line))
        scores={
            "syntax": syntax_score(line, template),
            "context": context_score(context_path, [e.context_path for e in examples]),
            "value_semantics": value_semantics_score(candidate, control["expected_value"]),
            "framework_fit": framework_fit(candidate, control["operator"], control["expected_value"]),
            "precedent": self.precedent.score(vendor, canonical_field, template.signature),
        }
        neg_gate=not negation_matches(candidate, ex_inferred)
        fusion_score,bucket,effective,available=fuse(scores,self.config,negation_mismatch=neg_gate)
        decision="ADMIN_REVIEW"
        status="unresolved"
        bge_score=None
        matched_example=examples[0].raw_line if examples else None
        if bucket=="HIGH":
            decision="AUTO_APPLY"; status="auto_applied"
        elif bucket=="MEDIUM":
            if self.bge is not None:
                try:
                    result=self.bge.match(line,vendor)
                    if result is not None:
                        bge_score=result["score"]
                        if result["accepted"]:
                            decision="BGE_RESOLVED"; status="bge_resolved"
                            matched_example=result["record"].raw_line
                        else:
                            decision="ADMIN_REVIEW"
                    else:
                        decision="ADMIN_REVIEW"
                except Exception as exc:
                    decision="ADMIN_REVIEW"
            else:
                decision="ADMIN_REVIEW"
        return MatchResult(
            original_line=line, normalized_line=" ".join(tokenize_cli(line)),
            vendor=vendor, candidate_canonical_field=canonical_field,
            syntax_score=scores["syntax"], context_score=scores["context"],
            value_semantics_score=scores["value_semantics"],
            framework_fit_score=scores["framework_fit"], precedent_score=scores["precedent"],
            available_signals=available, effective_weights=effective, fusion_score=fusion_score,
            confidence_bucket=bucket, decision=decision, matched_example=matched_example,
            matched_template=template.text, bge_score=bge_score, final_mapping_status=status,
            unavailable_signals=[k for k in ("syntax","context","value_semantics","framework_fit","precedent") if k not in available],
            explanation={"negation_gate_triggered":neg_gate, "canonical_field":canonical_field}
        )

    def match(self, line: str, vendor: str, template: SyntaxTemplate, examples: list[CLIExample],
              context_path: str | None = None) -> MatchResult:
        if not examples:
            raise ValueError("At least one confirmed example is required")
        field=examples[0].canonical_field
        if any(e.canonical_field != field for e in examples):
            raise ValueError("All confirmed examples must use the same canonical_field")
        return self._evaluate_candidate(line,vendor,field,template,examples,context_path)
