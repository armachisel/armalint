# Rules and analysis

Armalint emits stable rule codes with a severity and source location.

The current checks include bracket and string balance, trailing commas,
missing array commas, malformed `if`/`else` syntax, reversed `forEach` syntax,
missing statement terminators in conservative cases, unknown call targets,
undefined locals, unreachable code, and built-in or configured function type
mismatches.

Type checking is intentionally conservative: literals and simple assignments
are checked, while expressions whose type cannot be inferred are left alone.
Function names and signatures may come from built-ins, mission functions,
Arma/DLC data, or installed mods discovered by the updater.

Use JSON output when an editor or agent needs machine-readable diagnostics.
