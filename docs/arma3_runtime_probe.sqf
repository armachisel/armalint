/*
    Arma 3 runtime probe

    Paste this file's contents into the in-game Debug Console and execute it
    in single-player/editor preview (or on the server).  The report is copied
    to the clipboard and also written to the RPT.

    `supportInfo "i:<name>"` is the engine's authoritative command lookup.
    `isFunction` checks the Functions Library; the runtime-variable column
    shows whether that function is currently compiled in missionNamespace.
*/

private _commands = [
    // Names reported as possible vanilla commands.
    "sortBy",
    "getTerrainHeightATL",
    "setSpeed",
    "setWeaponReloaded",
    "setWeather",
    "forceWeather",
    "fadFog",
    "setFogParams",
    "enable",
    "lerp",

    // Closest documented alternatives, included for comparison.
    "getTerrainHeight",
    "getTerrainHeightASL",
    "setSpeedMode",
    "forceSpeed",
    "setWeaponReloadingTime",
    "setOvercast",
    "setRain",
    "setFog",
    "fogParams",
    "forceWeatherChange",
    "ctrlEnable",
    "enableSimulation"
];

private _functions = [
    "BIS_fnc_sortBy",
    "BIS_fnc_lerp",
    "ace_interactions_addAction",
    "ace_interact_menu_fnc_addActionToClass",
    "ace_interact_menu_fnc_addActionToObject",
    "TFAR_fnc_isTransmitting",
    "TFAR_fnc_isSpeaking",
    "tfar_core_fnc_isSpeaking"
];

private _lines = [
    "Arma 3 runtime probe",
    format ["productVersion: %1", productVersion],
    "",
    "kind\tname\tengine-or-library\truntime-variable\tdetails"
];

{
    private _name = _x;
    private _info = supportInfo format ["i:%1", _name];
    _lines pushBack format [
        "command\t%1\t%2\t\t%3",
        _name,
        !(_info isEqualTo []),
        _info
    ];
} forEach _commands;

{
    private _name = _x;
    private _library = isFunction _name;
    private _runtime = !(isNil { missionNamespace getVariable [_name, nil] });
    _lines pushBack format [
        "function\t%1\t%2\t%3\t",
        _name,
        _library,
        _runtime
    ];
} forEach _functions;

private _report = _lines joinString toString [13, 10];
copyToClipboard _report;
diag_log _report;
hint format ["Copied %1 runtime checks to the clipboard.", count _lines - 4];

_report
