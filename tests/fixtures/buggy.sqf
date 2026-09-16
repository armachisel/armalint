// Fixture: intentionally invalid snippet.
// Expected diagnostics:
//   E001  bracket balance: unclosed '('
//   W101  possible undefined variable: _undefinedVar
//   W201  unknown function/command: thisFunctionDoesNotExist
_value = (player;              // E001: unclosed parenthesis
hint str _undefinedVar;        // W101: undefined local variable
call thisFunctionDoesNotExist; // W201: unknown call target
