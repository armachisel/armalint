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
| `E008` | A code block is followed by a statement that needs a semicolon in a case where the boundary is clear. The check is deliberately conservative because a final semicolon before `}` is optional in SQF. |

## Analysis warnings

Warnings do not make the command fail, but they are often where the useful
mistakes are found.

| Code | Check |
| --- | --- |
| `W101` | A script-local variable is used before Armalint can find a definition, `params`, or `param` declaration. |
| `W104` | Code is unreachable after an unconditional `exitWith`, `throw`, `breakOut`, `continue`, or a pair of terminating branches. |
| `W201` | A name used as a `call` or `spawn` target is not in the built-in, mission, or indexed function registry. |
| `W202` | A direct command name is not in the built-in command registry. |
| `W203` | A known command or indexed function receives an argument whose statically inferred type is incompatible with its signature. |
| `W204` | A statically indexed function receives more arguments than its indexed signature declares. Shorter calls are allowed because extracted signatures may include optional parameters. |

## How cautious is the analysis?

Literal values and simple assignments are useful evidence. A complicated
expression is not. When there is not enough information to say something
sensible, the checker stays quiet. That means it will miss some errors. It
also means it should not fill a build with warnings that turn out to be
unrelated to the problem you are trying to find.

Config files are handled as config files. SQF embedded in code-valued config
properties is linted, while the class hierarchy itself is not treated as SQF.
