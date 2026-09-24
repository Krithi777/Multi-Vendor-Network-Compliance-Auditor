"""Induce reusable syntax templates from administrator-confirmed examples."""
from __future__ import annotations
from dataclasses import dataclass
from difflib import SequenceMatcher
from collections import Counter
from .tokenizer import tokenize_cli, normalize_tokens

@dataclass(frozen=True)
class SyntaxTemplate:
    tokens: tuple[str, ...]
    signature: str

    @property
    def text(self) -> str:
        return " ".join(self.tokens)

def _common_length(seqs):
    return min(len(s) for s in seqs)

def induce_template(lines: list[str]) -> SyntaxTemplate:
    if len(lines) < 3:
        raise ValueError("At least 3 confirmed examples are required")
    seqs = [normalize_tokens(tokenize_cli(x)) for x in lines]
    # Align all examples against the first sequence. This intentionally uses
    # SequenceMatcher rather than raw-string equality.
    base = seqs[0]
    aligned = [base]
    for seq in seqs[1:]:
        sm = SequenceMatcher(a=base, b=seq, autojunk=False)
        out = [None] * len(base)
        for a, b, size in sm.get_matching_blocks():
            for i in range(size):
                if a + i < len(base):
                    out[a+i] = seq[b+i]
        aligned.append(out)
    # Fixed positions are tokens occurring identically in every aligned row.
    template = []
    for i, tok in enumerate(base):
        vals = [row[i] if i < len(row) else None for row in aligned]
        if vals[0] is not None and all(v == vals[0] for v in vals):
            template.append(vals[0])
        else:
            template.append("{VALUE}")
    # Compress adjacent placeholders; signatures are stable and reusable.
    compressed=[]
    for tok in template:
        if tok == "{VALUE}" and compressed and compressed[-1] == "{VALUE}":
            continue
        compressed.append(tok)
    sig = " ".join(compressed)
    return SyntaxTemplate(tuple(compressed), sig)

def syntax_score(candidate_line: str, template: SyntaxTemplate) -> float:
    cand = normalize_tokens(tokenize_cli(candidate_line))
    if not cand or not template.tokens:
        return 0.0
    # Compare fixed structure while treating {VALUE} as a wildcard.
    ti = 0
    matched = 0
    fixed = 0
    for ct in cand:
        if ti >= len(template.tokens):
            break
        tt = template.tokens[ti]
        if tt == "{VALUE}":
            matched += 1
            ti += 1
        elif ct == tt:
            matched += 1
            fixed += 1
            ti += 1
        else:
            # permit a small edit mismatch by SequenceMatcher later
            ti += 1
    structure = matched / max(len(template.tokens), len(cand), 1)
    fixed_ratio = fixed / max(sum(t != "{VALUE}" for t in template.tokens), 1)
    edit = SequenceMatcher(
        a=[t for t in cand],
        b=[t for t in template.tokens if t != "{VALUE}"],
        autojunk=False,
    ).ratio()
    # Fixed-token coverage dominates; edit similarity supplies partial credit.
    return max(0.0, min(1.0, 0.65 * structure + 0.35 * min(fixed_ratio, edit)))
