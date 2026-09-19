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
    "W217": ("warning", "Invalid params declaration shape"),
    "W218": ("warning", "Invalid namespace variable operation"),
    "W219": ("warning", "Invalid event-handler lifecycle or declaration"),
    "W220": ("warning", "Invalid remote execution contract"),
    "W221": ("warning", "Invalid public-variable contract"),
    "W222": ("warning", "Value overwritten before use"),
    "W223": ("warning", "Repeated constant assignment"),
    "W224": ("warning", "Ineffective empty expression"),
    "W225": ("warning", "Macro redefined"),
    "W226": ("warning", "Undefined or unresolved macro use"),
    "W227": ("warning", "Malformed conditional preprocessor nesting"),
    "W228": ("warning", "Unsupported or malformed preprocessor directive"),
    "W301": ("warning", "Trailing whitespace"),
    "W302": ("warning", "Tab character in source indentation"),
}


def metadata() -> list[dict[str, str]]:
    return [
        {"id": code, "name": message, "defaultSeverity": severity}
        for code, (severity, message) in sorted(RULES.items())
    ]
