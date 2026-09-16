# Rules and analysis

The rule codes are deliberately stable. They are intended to be useful in a
terminal, in an editor, and in a script that wants to make sense of JSON
output.

The syntax checks cover the usual small disasters: unbalanced brackets,
unterminated strings, trailing commas, missing commas in arrays, malformed
`if`/`else` forms, and reversed `forEach` syntax. There are also checks for
unknown call targets, locals used before they are defined, unreachable code,
and missing statement terminators in the cases where a boundary can be
identified without guessing.

The type checker is intentionally cautious. Literal values and simple local
assignments are useful evidence. A complicated expression is not. When there
is not enough information to say something sensible, the checker stays quiet.
That means it will miss some errors. It also means it should not fill a build
with warnings that turn out to be unrelated to the problem you are trying to
find.

Function names and signatures can come from the built-in registry, mission
functions, Arma and DLC data, or installed mods discovered by the updater.
The updater only uses data it can actually find on the machine; it does not
pretend that an unknown mod function is valid just because its namespace looks
familiar.
