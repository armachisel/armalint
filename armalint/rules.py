"""Stable rule metadata for machine-readable integrations."""

RULES = {
    "E001": ("error", "Unmatched or unclosed bracket"),
    "E002": ("error", "Unterminated string literal"),
    "E003": ("error", "Trailing comma in an array"),
    "E004": ("error", "Missing then after an if condition"),
    "E005": ("error", "Invalid else syntax"),
    "E006": ("error", "Missing comma between array elements"),
    "E007": ("error", "Reversed forEach syntax"),
    "E008": ("error", "Missing semicolon after a code block"),
    "E009": ("error", "Invalid postfix command expression"),
    "E010": ("error", "Malformed config structure"),
    "E011": ("error", "Malformed mission.sqm structure"),
    "W101": ("warning", "Possible undefined local variable"),
    "W104": ("warning", "Unreachable code"),
    "W201": ("warning", "Unknown function or command name"),
    "W202": ("warning", "Unknown direct command name"),
    "W203": ("warning", "Incompatible argument type"),
    "W204": ("warning", "Incorrect function argument count"),
    "W205": ("warning", "Call or spawn target is not code"),
    "W206": ("warning", "Constant if condition"),
    "W207": ("warning", "Duplicate function definition"),
    "W208": ("warning", "Function overwritten by a non-code value"),
    "W209": ("warning", "Unused local variable"),
    "W210": ("warning", "Include cycle detected"),
    "W211": ("warning", "Repeated include without an include guard"),
    "W212": ("warning", "Duplicate mission addon entry"),
    "W213": ("warning", "Invalid mission addon name"),
    "W214": ("warning", "Config property defined more than once"),
    "W215": ("warning", "Local declaration shadows or duplicates another local"),
    "W216": ("warning", "Comparison uses incompatible statically known types"),
    "W301": ("warning", "Trailing whitespace"),
    "W302": ("warning", "Tab character in source indentation"),
}


def metadata() -> list[dict[str, str]]:
    return [
        {"id": code, "name": message, "defaultSeverity": severity}
        for code, (severity, message) in sorted(RULES.items())
    ]
