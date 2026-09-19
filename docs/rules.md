# Rules and analysis

The rule codes are stable. They are useful in a terminal, in an editor, and
in JSON consumed by another tool.

The complete registry-backed catalog, including severity and categories, is
generated in [`rule-catalog.md`](rule-catalog.md). Run
`python -m armalint.rule_docs --check` in CI to detect documentation drift.

## Syntax errors

These are errors by default. The process exit threshold can be changed with
`--fail-on` when a project needs a different CI policy.

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
| `E010` | A class-based config has unmatched or unclosed braces. |
| `E011` | A text `mission.sqm` is missing its required `version` field. |
| `E012` | The project configuration or a configured plugin is invalid. |

## Analysis warnings

Warnings do not make the command fail by default, but they are often where the useful
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
| `W210` | A local include cycle is detected. Ordinary repeated includes are not warned about. |
| `W211` | A file is included repeatedly without `#pragma once` or a conventional `#ifndef`/`#define` guard. |
| `W212` | A mission addon is listed more than once. |
| `W213` | A mission addon name is malformed or no addon list is present. |
| `W214` | A config property is assigned more than once in the same class. |
| `W215` | A local declaration shadows or duplicates another local. |
| `W216` | A comparison uses incompatible statically known primitive types. |
| `W217` | A `params` declaration has an invalid shape. |
| `W218` | A namespace variable operation has an invalid argument shape. |
| `W219` | An event-handler declaration or removal has an invalid lifecycle shape. |
| `W220` | A `remoteExec` or `remoteExecCall` contract is malformed. |
| `W221` | A public-variable command does not receive a variable name string. |
| `W222` | A local value is overwritten before it is read. |
| `W223` | A local is assigned the same constant value repeatedly. |
| `W224` | An empty code block or empty-array expression has no useful effect. |
| `W225` | A preprocessor macro is redefined. |
| `W226` | A preprocessor macro is undefined or an expression cannot be resolved. |
| `W227` | Preprocessor conditional directives are unbalanced. |
| `W228` | A preprocessor directive is unsupported or malformed. |
| `W229` | An inline suppression is missing a justification. |
| `W230` | An inline suppression does not match any diagnostic. |
| `W231` | A suppression directive is malformed or names an unknown rule. |

The SQF contract checks are intentionally conservative. `params` declarations
are checked for the supported string and `[name, default, validators]` shapes;
dynamic declarations are left alone. Namespace checks cover malformed
`getVariable`/`setVariable` calls on explicit namespace objects. Event-handler
checks pair static registrations with removals in the same file, while dynamic
handler IDs remain unchecked. Remote execution checks the required argument
array and Boolean JIP position. Public-variable commands require a literal
variable-name string so typos and accidental value publication are visible.
| `W301` | Trailing whitespace when optional style checks are enabled with `--style`. |
| `W302` | Tab character when optional style checks are enabled with `--style`. |

## How cautious is the analysis?

Literal values and simple assignments are useful evidence. A complicated
expression is not. When there is not enough information to say something
sensible, the checker stays quiet. That means it will miss some errors. It
also means it should not fill a build with warnings that turn out to be
unrelated to the problem you are trying to find.

Config files are handled as config files. SQF embedded in code-valued config
properties is linted, while the class hierarchy itself is not treated as SQF.
Local includes, object-like macros, and simple literal/defined conditional
directives are supported; arbitrary preprocessor expressions are not executed.

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

An `armalint.json` file may set `severity` (or `ruleSeverity`) for rules to
`error`, `warning`, `info`, or `off`, and `ignore` (or `ignorePatterns`) to
filename globs for generated or vendor files. These settings are
project-specific and complement command-line and source-comment controls.

Use `--check-suppressions` in CI to require a reason after each inline rule
code, for example `// armalint: disable-next-line W206 -- intentional fallback`,
and to report suppressions that no longer match a diagnostic. Use
`--baseline PATH` to carry known findings between CI runs; baseline entries use
the same stable fingerprints emitted in SARIF.

Use `--style` to enable optional whitespace rules `W301` (trailing whitespace)
and `W302` (tab characters). Use `--sarif` for SARIF 2.1.0 output with stable
rule metadata, severity, messages, and source locations for CI and code
scanning systems.
