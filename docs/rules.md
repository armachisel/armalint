# Rules and analysis

The rule codes are stable. They are useful in a terminal, in an editor, and
in JSON consumed by another tool.

## Syntax errors

These are errors and make the command exit with status 1.

| Code | Check |
| --- | --- |
| `E001` | Unmatched or unclosed `(`, `[`, or `{`. |
| `E002` | Unterminated string literal. |
| `E003` | Trailing comma in an array, such as `[1, 2,]`. |
| `E004` | An `if` condition is not followed by `then`. This also understands the valid `if (...) exitWith {...}` form. |
| `E005` | `else` is not followed by a code block or another `if`. |
| `E006` | Adjacent literal values in an array are missing a comma. |
| `E007` | Reversed `forEach` syntax; the code block must come before `forEach`. |
| `E008` | A code block or command expression is followed by a statement that needs a semicolon in a case where the boundary is clear. The check is deliberately conservative because a final semicolon before `}` is optional in SQF. |
| `E009` | A statement uses a known command in postfix form, such as `_items reverse;`, which is not a complete SQF command expression. |

## Analysis warnings

Warnings do not make the command fail, but they are often where the useful
mistakes are found.

| Code | Check |
| --- | --- |
| `W101` | A script-local variable is used before Armalint can find a definition, `params`, or `param` declaration. |
| `W104` | Code is unreachable after an unconditional `exitWith`, `throw`, `breakOut`, `continue`, or a pair of terminating branches. |
| `W206` | An `if` condition is a literal value and therefore always has the same truth value. |
| `W201` | A name used as a `call` or `spawn` target is not in the built-in, mission, or indexed function registry. |
| `W202` | A direct command name is not in the built-in command registry. |
| `W203` | A known command or indexed function receives an argument whose statically inferred type is incompatible with its signature. |
| `W204` | A statically indexed function receives more arguments than its indexed signature declares. Shorter calls are allowed because extracted signatures may include optional parameters. |
| `W205` | `call` or `spawn` is targeting a literal value known not to contain code. |
| `W207` | A global function name is defined more than once in the same file. |
| `W208` | A global function definition is later overwritten by a non-code value. |
| `W209` | A `private` or `params` local has no later reference in its lexical scope. Files proven to be included fragments and files containing includes are skipped. |

## How cautious is the analysis?

Literal values and simple assignments are useful evidence. A complicated
expression is not. When there is not enough information to say something
sensible, the checker stays quiet. That means it will miss some errors. It
also means it should not fill a build with warnings that turn out to be
unrelated to the problem you are trying to find.

Config files are handled as config files. SQF embedded in code-valued config
properties is linted, while the class hierarchy itself is not treated as SQF.

The parser builds source-spanned nodes for `if`/`else`, `for`, `while`,
`waitUntil`, `try`/`catch`, `switch`, `exitWith`, `forEach`, and direct `call`/`spawn` code
blocks. Scope and type analysis use those nodes where the syntax is
unambiguous; dynamic expressions remain unchecked.

The duplicate-definition checks use the conventional Arma function marker
`_fnc_` or evidence that an arbitrary global code value is later used as a
`call` or `spawn` target. They report repeated definitions and overwrites for
names such as `ALT_fnc_buildRoute`, while leaving unrelated global state alone.

## Suppressing rules

Use `--ignore-rule W206` to suppress a rule for one command invocation. A
mission's `armalint.json` can apply suppression to the whole mission with
`{"ignoreRules": ["W206"]}`. In source, use
`// armalint: disable-next-line W206` or
`// armalint: disable-line W206`; use paired `disable` and `enable` comments
for a file or section-wide exception. Omitting rule codes disables or enables
all rules. Command-line and mission-configured suppressions also cover
diagnostics remapped from `#include`d files.
