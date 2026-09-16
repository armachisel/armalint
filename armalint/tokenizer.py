"""Tokenizer for Arma 3 SQF source code (lexical layer only)."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Token:
    """A single lexical token: type, decoded value, 1-based line/column, raw slice."""

    type: str
    value: str
    line: int
    column: int
    raw: str


_KEYWORDS = frozenset(
    (
        "true", "false", "nil", "private", "params", "if", "then", "else",
        "for", "while", "do", "switch", "case", "default", "foreach",
        "from", "to", "step", "and", "or", "not", "exitwith", "throw",
        "try", "catch", "call", "spawn", "execvm", "compile", "select",
        "format",
    )
)

_TWO_CHAR_OPERATORS = frozenset(("==", "!=", "<=", ">=", "&&", "||", "++", "--", "=>"))
_ONE_CHAR_OPERATORS = frozenset("+-*/%^<>=!:")
_OPERATOR_CHARS = _ONE_CHAR_OPERATORS | frozenset("&|")

_SIMPLE_TOKENS = {
    "(": "lparen", ")": "rparen", "[": "lbracket", "]": "rbracket",
    "{": "lbrace", "}": "rbrace", ";": "semicolon", ",": "comma",
}

# Token types after which a "-" is binary subtraction, not a negative literal.
_VALUE_TYPES = frozenset(
    ("number", "ident", "local", "string", "keyword", "rparen", "rbracket", "rbrace")
)


def _is_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


def _is_ident_start(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z") or ch == "_"


def _is_ident_char(ch: str) -> bool:
    return _is_ident_start(ch) or _is_digit(ch)


class _Scanner:
    def __init__(self, source: str) -> None:
        self.src = source
        self.pos = 0
        self.line = 1
        self.col = 1
        self.line_has_content = False

    def peek(self, offset: int = 0) -> str:
        index = self.pos + offset
        return self.src[index] if index < len(self.src) else ""

    def advance(self) -> str:
        ch = self.src[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _scan_identifier(self) -> None:
        while _is_ident_char(self.peek()):
            self.advance()

    def _scan_string(self) -> str:
        quote = self.advance()
        chars = []
        while True:
            ch = self.peek()
            if ch == "":
                break  # EOF: unpaired quote, emit what we have and continue
            if ch == quote:
                if self.peek(1) == quote:  # doubled quote is a literal quote
                    chars.append(quote)
                    self.advance()
                    self.advance()
                else:
                    self.advance()  # closing quote
                    break
            else:
                # Newlines are ordinary string characters in SQF: append them
                # and keep scanning. ``advance()`` maintains the line/column
                # bookkeeping for embedded ``\n`` so tokens after the string
                # get correct positions.
                chars.append(ch)
                self.advance()
        return "".join(chars)

    def _scan_number(self) -> None:
        if self.peek() == "-":
            self.advance()
        if self.peek() == "0" and self.peek(1) in ("x", "X"):
            self.advance()
            self.advance()
            while self.peek() and self.peek() in "0123456789abcdefABCDEF":
                self.advance()
            return
        while _is_digit(self.peek()):
            self.advance()
        if self.peek() == ".":
            self.advance()
            while _is_digit(self.peek()):
                self.advance()
        if self.peek() in ("e", "E"):
            look = self.pos + 1
            if look < len(self.src) and self.src[look] in ("+", "-"):
                look += 1
            if look < len(self.src) and _is_digit(self.src[look]):
                self.advance()
                if self.peek() in ("+", "-"):
                    self.advance()
                while _is_digit(self.peek()):
                    self.advance()

    def _scan_line_comment(self) -> None:
        self.advance()
        self.advance()
        while self.peek() and self.peek() not in ("\n", "\r"):
            self.advance()

    def _scan_block_comment(self) -> None:
        self.advance()
        self.advance()
        while self.peek():
            if self.peek() == "*" and self.peek(1) == "/":
                self.advance()
                self.advance()
                return
            self.advance()


def tokenize(source: str) -> list[Token]:
    """Tokenize SQF ``source`` into a flat token list ending with ``eof``."""
    sc = _Scanner(source)
    tokens: list[Token] = []

    def last_is_value() -> bool:
        return bool(tokens) and tokens[-1].type in _VALUE_TYPES

    while sc.pos < len(source):
        ch = sc.peek()

        if ch == "\n":
            sc.advance()
            sc.line_has_content = False
            continue
        if ch in (" ", "\t", "\r"):
            sc.advance()
            continue

        start, start_line, start_col = sc.pos, sc.line, sc.col

        if ch == "#" and not sc.line_has_content:
            sc.advance()
            content_start = sc.pos
            while sc.peek() and sc.peek() not in ("\n", "\r"):
                sc.advance()
            value = source[content_start:sc.pos].strip()
            tokens.append(Token("preprocessor", value, start_line, start_col, source[start:sc.pos]))
            sc.line_has_content = True
            continue

        if ch == "/" and sc.peek(1) in ("/", "*"):
            if sc.peek(1) == "/":
                sc._scan_line_comment()
            else:
                sc._scan_block_comment()
            tokens.append(Token("comment", source[start:sc.pos], start_line, start_col, source[start:sc.pos]))
            sc.line_has_content = True
            continue

        if ch in ('"', "'"):
            value = sc._scan_string()
            tokens.append(Token("string", value, start_line, start_col, source[start:sc.pos]))
            sc.line_has_content = True
            continue

        if (
            _is_digit(ch)
            or (ch == "." and _is_digit(sc.peek(1)))
            or (ch == "-" and _is_digit(sc.peek(1)) and not last_is_value())
        ):
            sc._scan_number()
            tokens.append(Token("number", source[start:sc.pos], start_line, start_col, source[start:sc.pos]))
            sc.line_has_content = True
            continue

        if _is_ident_start(ch):
            sc._scan_identifier()
            text = source[start:sc.pos]
            if text.startswith("_"):
                ttype = "local"
            elif text.lower() in _KEYWORDS:
                ttype = "keyword"
            else:
                ttype = "ident"
            tokens.append(Token(ttype, text, start_line, start_col, source[start:sc.pos]))
            sc.line_has_content = True
            continue

        if ch in _OPERATOR_CHARS:
            two = ch + sc.peek(1)
            if two in _TWO_CHAR_OPERATORS:
                sc.advance()
                sc.advance()
            else:
                sc.advance()
            tokens.append(Token("operator", source[start:sc.pos], start_line, start_col, source[start:sc.pos]))
            sc.line_has_content = True
            continue

        if ch in _SIMPLE_TOKENS:
            sc.advance()
            tokens.append(Token(_SIMPLE_TOKENS[ch], source[start:sc.pos], start_line, start_col, source[start:sc.pos]))
            sc.line_has_content = True
            continue

        # Unrecognized character: emit a single-char operator so scanning
        # always makes forward progress.
        sc.advance()
        tokens.append(Token("operator", source[start:sc.pos], start_line, start_col, source[start:sc.pos]))
        sc.line_has_content = True

    tokens.append(Token("eof", "", sc.line, sc.col, ""))
    return tokens


if __name__ == "__main__":
    toks = tokenize("_x = player;")
    assert [(t.type, t.value) for t in toks] == [
        ("local", "_x"), ("operator", "="), ("ident", "player"),
        ("semicolon", ";"), ("eof", ""),
    ]

    toks = tokenize('hint "hello ""world""";')
    assert toks[0].type == "ident" and toks[0].value == "hint"
    assert toks[1].type == "string" and toks[1].value == 'hello "world"'

    toks = tokenize('#include "foo.hpp"\n_x = 1;')
    assert toks[0].type == "preprocessor" and toks[0].value == 'include "foo.hpp"'
    assert toks[1].type == "local"

    toks = tokenize("-5 0x1F 1.5e-3 2E+10")
    assert [t.type for t in toks] == ["number"] * 4 + ["eof"]
    assert [t.value for t in toks[:-1]] == ["-5", "0x1F", "1.5e-3", "2E+10"]

    toks = tokenize("if (_x >= 1 && _y <= 2) then { _x++; };")
    assert toks[0].type == "keyword" and toks[0].value == "if"
    pairs = [(t.type, t.value) for t in toks]
    assert ("operator", ">=") in pairs and ("operator", "&&") in pairs
    assert ("operator", "++") in pairs

    toks = tokenize("a /* hi\nthere */ b")
    assert toks[1].type == "comment" and "\n" in toks[1].value

    # Multi-line string: a newline is an ordinary character, not a terminator.
    toks = tokenize('_x = "a\nb";')
    assert toks[2].type == "string" and toks[2].value == "a\nb"
    assert toks[3].type == "semicolon" and toks[3].line == 2, toks[3]

    # Doubled-quote escaping still works across embedded newlines.
    toks = tokenize('_x = "a\n""b";')
    assert toks[2].type == "string" and toks[2].value == 'a\n"b', toks[2].value
    assert toks[3].type == "semicolon" and toks[3].line == 2, toks[3]

    # A source that ends in an unclosed quote is still an unterminated string
    # (only EOF terminates it now, not a newline).
    assert tokenize('"abc')[0].value == "abc"
    assert tokenize("'it''s'")[0].value == "it's"
    assert tokenize("").pop().type == "eof"

    print("tokenizer self-test passed")
