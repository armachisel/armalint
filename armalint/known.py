"""Registry of known SQF commands and ``BIS_fnc_*`` functions for Armalint.

Names are stored and matched case-insensitively (SQF identifiers are
case-insensitive). Runtime registration is supported via :func:`register`.

Both registries are seeded from generated data files under ``armalint/data/``
(``commands.txt`` and ``functions.txt``): comprehensive, lowercase, one-per-line
lists sourced from community mirrors. Each data file is UNION-ed with its inline
fallback set below, so a missing data file reduces coverage but never
correctness.
"""

from __future__ import annotations

from pathlib import Path


def _normalize(name: str) -> str:
    """Normalize a name for storage/lookup (SQF names are case-insensitive)."""
    return name.strip().lower()


def _load_commands_from_data() -> set[str]:
    """Load command names from ``armalint/data/commands.txt`` (best-effort).

    Returns a set of lowercased command names, or an empty set if the data file
    is missing or unreadable. The inline ``_INLINE_COMMANDS`` fallback is always
    UNION-ed in afterwards, so a missing data file reduces coverage but never
    correctness.
    """
    path = Path(__file__).resolve().parent / "data" / "commands.txt"
    names: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                name = line.strip()
                if not name or name.startswith("#"):
                    continue
                names.add(_normalize(name))
    except OSError:
        # Data file absent (e.g. checkout without generated data): fall back to
        # the inline set only.
        pass
    return names


def _load_functions_from_data() -> set[str]:
    """Load function names from ``armalint/data/functions.txt`` (best-effort).

    Returns a set of lowercased ``BIS_fnc_*`` function names, or an empty set if
    the data file is missing or unreadable. The inline ``_INLINE_FUNCTIONS``
    fallback is always UNION-ed in afterwards, so a missing data file reduces
    coverage but never correctness.
    """
    path = Path(__file__).resolve().parent / "data" / "functions.txt"
    names: set[str] = set()
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                name = line.strip()
                if not name or name.startswith("#"):
                    continue
                names.add(_normalize(name))
    except OSError:
        # Data file absent (e.g. checkout without generated data): fall back to
        # the inline set only.
        pass
    return names


# Script-path extensions that indicate a string is a file, not a function name.
SCRIPT_EXTENSIONS = (".sqf", ".sqs", ".ext")

# --- Known commands (stored lowercased) -------------------------------------
# This inline set is a fallback that guarantees baseline coverage even when the
# generated data file is unavailable; it is UNION-ed with the data file below
# (``KNOWN_COMMANDS = _INLINE_COMMANDS | <data file>``).

_INLINE_COMMANDS: set[str] = {
    # Output / debugging
    "hint", "hintC", "hintSilent", "hintCADetailed", "systemChat", "diag_log",
    "titleText", "titleCut", "titleRsc", "cutText", "cutRsc", "briefing",
    # Core / misc
    "player", "server", "time", "date", "serverTime", "diag_tickTime",
    "missionNamespace", "profileNamespace", "uiNamespace", "parsingNamespace",
    "localNamespace", "missionStart", "worldName", "worldSize",
    "isServer", "isDedicated", "hasInterface", "isMultiplayer",
    "isNull", "isNil", "isNilEx", "typeName", "typeOf", "isKindOf",
    "isEqualTo", "isEqualType", "isEqualTypeAny", "isEqualTypeArray",
    "isEqualTypeParams", "isClass", "isArray", "isText", "isNumber", "isScalar",
    "str", "format", "parseNumber", "parseText", "parseSimpleArray",
    "toString", "toArray", "toLower", "toUpper", "splitString",
    # Math / conversion
    "abs", "floor", "ceil", "round", "sqrt", "exp", "ln", "log", "min", "max",
    "mod", "random", "sin", "cos", "tan", "asin", "acos", "atan", "atan2",
    "deg", "rad", "pi", "linearConversion",
    # Control flow / code
    "call", "spawn", "execVM", "exec", "compile", "compileFinal",
    "remoteExec", "remoteExecCall", "sleep", "uiSleep", "waitUntil",
    "exitWith", "throw", "try", "catch", "terminate", "scriptDone",
    "scriptNull", "isScriptRunning", "canSuspend",
    "preprocessFile", "preprocessFileLineNumbers", "loadFile",
    "select", "count", "forEach", "forEachMember", "find", "findIf",
    "arrayIntersect", "pushBack", "append", "pushBackUnique", "resize",
    "reverse", "sort", "list", "apply", "selectRandom",
    # Variables / namespaces / public
    "setVariable", "getVariable", "setVariablePublic", "publicVariable",
    "publicVariableServer", "publicVariableClient", "isPublicVariableClient",
    "saveVar", "loadVar", "allVariables", "variableName",
    # Objects / positions
    "createVehicle", "createVehicleLocal", "createVehicleCrew", "createUnit",
    "createGroup", "createAgent", "createMine", "deleteVehicle", "deleteGroup",
    "setPos", "setPosWorld", "setPosASL", "setPosATL", "setPosASLW",
    "getPos", "getPosWorld", "getPosASL", "getPosATL", "getPosASLW",
    "getPosVisual", "visiblePosition", "visiblePositionASL",
    "setDir", "getDir", "setVectorDir", "setVectorUp", "setVectorDirAndUp",
    "vectorDir", "vectorUp", "setVelocity", "setVelocityModelSpace",
    "velocity", "distance", "distance2D", "distanceSqr", "vectorDistance",
    "vectorDistanceSqr", "modelToWorld", "worldToModel", "modelToWorldVisual",
    "screenToWorld", "worldToScreen", "getDirVisual", "setDirVisual",
    "attachedTo", "attachTo", "attachedObjects", "objectParent",
    "boundingBox", "boundingBoxReal", "boundingCenter", "sizeOf",
    "selectionPosition", "selectionNames", "isTouchingGround",
    "nearestObject", "nearestObjects", "nearestTerrainObjects", "nearestBuilding",
    "nearestLocations", "allUnits", "allPlayers", "allGroups", "allDead",
    "allMissionObjects", "allSimpleObjects", "vehicles", "crew", "units",
    "leader", "group", "side", "sideChat", "groupChat", "vehicleChat",
    "commandChat", "globalChat", "customChat",
    # Markers
    "createMarker", "createMarkerLocal", "deleteMarker", "deleteMarkerLocal",
    "setMarkerPos", "setMarkerPosLocal", "setMarkerText", "setMarkerType",
    "setMarkerColor", "setMarkerShape", "setMarkerSize", "setMarkerDir",
    "setMarkerBrush", "setMarkerAlpha", "setMarkerAlphaLocal",
    "markerPos", "getMarkerPos", "markerText", "markerType", "markerColor",
    "markerShape", "markerSize", "markerDir", "markerBrush", "markerAlpha",
    "allMapMarkers",
    # AI / units / groups
    "enableSimulation", "enableSimulationGlobal", "enableAI", "disableAI",
    "enableFatigue", "enableStamina", "enableAIFeature", "disableAIFeature",
    "setDamage", "setDammage", "getDammage", "damage", "alive", "lifeState",
    "setFuel", "setCaptive", "setBehaviour", "setCombatMode", "setSpeedMode",
    "setFormation", "setSkill", "setRank", "setUnitRank", "rank", "skill",
    "setFace", "setIdentity", "setSpeaker", "setName", "name", "profileName",
    "setUnitPos", "unitPos", "allowFleeing", "setSuppression", "suppression",
    "setUnconscious", "unconscious", "setAmmo", "setMagazineTurretAmmo",
    "setMagazineAmmoCargo", "addWeapon", "removeWeapon", "addWeaponGlobal",
    "removeWeaponGlobal", "addMagazine", "removeMagazine", "addMagazineGlobal",
    "removeMagazineGlobal", "addItem", "removeItem", "addItemGlobal",
    "removeItemGlobal", "addBackpack", "removeBackpack", "addBackpackGlobal",
    "removeBackpackGlobal", "assignItem", "unassignItem", "linkItem",
    "unlinkItem", "addHeadgear", "removeHeadgear", "addGoggles", "removeGoggles",
    "uniform", "vest", "backpack", "headgear", "goggles", "hmd",
    "primaryWeapon", "secondaryWeapon", "handgunWeapon", "binocular",
    "magazines", "weapons", "items", "uniformItems", "vestItems",
    "backpackItems", "magazineCargo", "weaponCargo", "itemCargo",
    "backpackCargo", "getMagazineCargo", "getWeaponCargo", "getItemCargo",
    "getBackpackCargo", "clearMagazineCargo", "clearWeaponCargo",
    "clearItemCargo", "clearBackpackCargo", "clearAllItemsFromBackpack",
    "currentMagazine", "currentWeapon", "currentMuzzle", "currentWeaponMode",
    "currentMagazineDetail", "selectWeapon", "selectWeaponTurret",
    "addPrimaryWeaponItem", "addSecondaryWeaponItem", "addHandgunItem",
    "primaryWeaponItems", "secondaryWeaponItems", "handgunItems",
    "removePrimaryWeaponItem", "removeSecondaryWeaponItem", "removeHandgunItem",
    "forceWeaponFire", "fire", "fireAtTarget", "doFire", "commandFire",
    "suppressFor", "commandSuppressiveFire", "reveal", "knowsAbout",
    "doTarget", "doWatch", "commandWatch", "doFollow", "commandFollow",
    "move", "doMove", "commandMove", "setDestination", "moveTo",
    "moveToCompleted", "moveToFailed", "moveInDriver", "moveInGunner",
    "moveInCommander", "moveInCargo", "moveInTurret", "assignAsDriver",
    "assignAsGunner", "assignAsCommander", "assignAsCargo", "assignAsCargoIndex",
    "assignAsTurret", "unassignVehicle", "leaveVehicle", "join", "joinSilent",
    "joinAs", "joinAsSilent", "setGroupId", "groupId", "groupOwner",
    "groupIconParams", "setGroupIconParams", "addWaypoint", "deleteWaypoint",
    "setWaypointType", "setWaypointBehaviour", "setWaypointCombatMode",
    "setWaypointSpeed", "setWaypointFormation", "setWaypointCompletionRadius",
    "setWaypointTimeout", "setWaypointStatements", "setWaypointPosition",
    "waypointPosition", "waypointType", "currentWaypoint", "waypoints",
    "lock", "locked", "lockIdentity", "lockTurret", "isVehicleRadarOn",
    "enableGunLights", "setPilotLight", "flyInHeight", "flyInHeightASL",
    "land", "landAt", "action", "actionIDs", "addAction", "removeAction",
    "removeAllActions", "addEventHandler", "removeEventHandler",
    "removeAllEventHandlers", "addMissionEventHandler", "removeMissionEventHandler",
    "addPublicVariableEventHandler", "onMapSingleClick", "onEachFrame",
    # Rating / score
    "rating", "addRating", "addScore", "score", "addScoreSide", "scoreSide",
    "kill", "getPlayerUID", "getPlayerUIDOld",
    # Tasks / triggers
    "createTask", "setTaskState", "taskState", "taskDescription", "taskHint",
    "taskChildren", "currentTask", "setCurrentTask", "deleteTask", "triggerActivated",
    "createTrigger", "deleteTrigger", "triggerArea", "triggerStatements",
    "triggerTimeout", "triggerType", "triggerText", "setTriggerArea",
    "setTriggerStatements", "setTriggerTimeout", "setTriggerType",
    "setTriggerActivation", "triggerAttachVehicle", "setTriggerText",
    # Sounds / music / speech
    "playSound", "playSound3D", "playMusic", "stopMusic", "fadeMusic",
    "fadeSound", "fadeSpeech", "fadeRadio", "fadeEnvironment",
    "say", "say2D", "say3D", "createSoundSource", "soundVolume", "musicVolume",
    "radioVolume", "environmentVolume", "enableRadio", "enableEnvironment",
    "enableSentences", "setRadioMsg", "enableChannel",
    # Camera / view
    "cameraOn", "camCreate", "camDestroy", "camUseNVG", "camCommit",
    "camPreload", "camPreparePos", "camPrepareTarget", "camPrepareFov",
    "camSetPos", "camSetTarget", "camSetFov", "camSetRelPos", "camSetRelTarget",
    "switchCamera", "cameraEffect", "cameraView",
    # Config / extension
    "getNumber", "getText", "getArray", "getMissionConfigValue", "configFile",
    "missionConfigFile", "campaignConfigFile", "configNull", "configName",
    "configProperties", "configSourceMod", "configHierarchy", "configClasses",
    "inheritsFrom", "callExtension", "extension",
    # Geometry / terrain
    "lineIntersects", "lineIntersectsSurfaces", "lineIntersectsObjs",
    "lineIntersectsWith", "terrainIntersect", "terrainIntersectASL",
    "terrainIntersectAtASL", "getTerrainHeightASL", "surfaceIsWater",
    "surfaceNormal", "surfaceType", "intersect", "sunOrMoon",
    "overcast", "fog", "rain", "wind", "gusts", "humidity", "windStr",
    # UI / dialogs
    "createDialog", "closeDialog", "displayNull", "findDisplay",
    "ctrlCreate", "ctrlDelete", "ctrlSetText", "ctrlText", "ctrlSetPosition",
    "ctrlPosition", "ctrlCommit", "ctrlShow", "ctrlEnable", "ctrlSetFocus",
    "ctrlSetFade", "ctrlFade", "ctrlSetFont", "ctrlSetTextColor",
    "ctrlSetBackgroundColor", "ctrlSetTooltip", "ctrlSetEventHandler",
    "ctrlAddEventHandler", "ctrlRemoveEventHandler",
    "ctrlRemoveAllEventHandlers", "ctrlMapAnimAdd", "ctrlMapAnimClear",
    "ctrlMapAnimCommit", "ctrlMapAnimDone", "ctrlSetScale", "ctrlSetStructuredText",
    "lbAdd", "lbClear", "lbColor", "lbCurSel", "lbData", "lbDelete",
    "lbPicture", "lbSelection", "lbSetColor", "lbSetCurSel", "lbSetData",
    "lbSetPicture", "lbSetSelectColor", "lbSetSelected", "lbSetText",
    "lbSetValue", "lbSize", "lbText", "lbValue", "lbSort",
    "sliderSetPosition", "sliderPosition", "sliderRange", "sliderSetRange",
    "sliderSetSpeed", "progressSetPosition", "progressPosition",
    "getMousePosition", "ctrlMapWorldToScreen", "ctrlMapScreenToWorld",
    # Loadout
    "getUnitLoadout", "setUnitLoadout", "getLoadout", "setLoadout",
    "getUnitLoadoutFaction", "setUnitLoadoutFaction",
    # Vehicle / weapon misc
    "setObjectTexture", "setObjectTextureGlobal", "getObjectTextures",
    "setObjectMaterial", "setObjectMaterialGlobal", "getObjectMaterials",
    "animate", "animationState", "animationPhase", "animationNames",
    "playMove", "playMoveNow", "switchMove", "playAction", "playActionNow",
    "gesture", "setMass", "getMass", "mass", "getCenterOfMass",
    "turretLocal", "setPylonLoadout", "getPylonLoadout", "setAmmoOnPylon",
    "getAmmoOnPylon", "setAmmoContainer",
    # Time / mission flow
    "setDate", "setTimeMultiplier", "accTime", "setAccTime", "timeMultiplier",
    "skipTime", "saveGame", "loadGame", "endMission", "failMission",
    "isGamePaused", "getMissionPath", "missionName", "missionDifficulty",
    # Misc
    "setWind", "setFog", "setOvercast", "setRain", "setGusts", "setHumidity",
    "selectMax", "selectMin", "vectorAdd", "vectorDiff", "vectorMultiply",
    "vectorCrossProduct", "vectorDotProduct", "vectorCos", "vectorMagnitude",
    "vectorMagnitudeSqr", "vectorNormalized", "vectorFromTo", "getTerrainInfo",
    "nearRoads", "getRoadInfo",
}

# --- Known functions (stored lowercased) ------------------------------------
# This inline set is a fallback that guarantees baseline coverage even when the
# generated data file is unavailable; it is UNION-ed with the data file below
# (``KNOWN_FUNCTIONS = _INLINE_FUNCTIONS | <data file>``).

_INLINE_FUNCTIONS: set[str] = {
    "BIS_fnc_param", "BIS_fnc_paramDaytime", "BIS_fnc_addStackedEventHandler",
    "BIS_fnc_removeStackedEventHandler", "BIS_fnc_MP", "BIS_fnc_remoteExec",
    "BIS_fnc_spawn", "BIS_fnc_call", "BIS_fnc_initMultiplayer",
    "BIS_fnc_taskCreate", "BIS_fnc_taskSetState", "BIS_fnc_taskCompleted",
    "BIS_fnc_taskState", "BIS_fnc_taskExists", "BIS_fnc_taskDescription",
    "BIS_fnc_setTask", "BIS_fnc_showNotification", "BIS_fnc_dynamicText",
    "BIS_fnc_inGameUILoaded", "BIS_fnc_displayName", "BIS_fnc_objectVar",
    "BIS_fnc_exportCfgGroups", "BIS_fnc_importCfgGroups", "BIS_fnc_markerCreate",
    "BIS_fnc_arrayShuffle", "BIS_fnc_arrayPushStack", "BIS_fnc_relPos",
    "BIS_fnc_findSafePos", "BIS_fnc_nearestRoad", "BIS_fnc_randomPos",
    "BIS_fnc_dirTo", "BIS_fnc_relativeDirTo", "BIS_fnc_inAngleSector",
    "BIS_fnc_distance2D", "BIS_fnc_objectsGrabber", "BIS_fnc_objectsMapper",
    "BIS_fnc_timeToString", "BIS_fnc_getCfgData", "BIS_fnc_getCfgDataBool",
    "BIS_fnc_configPath", "BIS_fnc_loadInventory", "BIS_fnc_saveInventory",
    "BIS_fnc_arsenal", "BIS_fnc_addWeapon", "BIS_fnc_itemType",
    "BIS_fnc_selectRandom", "BIS_fnc_findInPairs", "BIS_fnc_sortBy",
    "BIS_fnc_areEqual", "BIS_fnc_bitflagsCheck", "BIS_fnc_error",
    "BIS_fnc_errorMsg", "BIS_fnc_log", "BIS_fnc_logFormat", "BIS_fnc_diagKey",
    "BIS_fnc_helicopterDustEfx", "BIS_fnc_ambientAnim", "BIS_fnc_ambientFlyby",
    "BIS_fnc_camp_artillery", "BIS_fnc_weaponHoldActionAdd",
    "BIS_fnc_holdActionAdd", "BIS_fnc_holdActionRemove", "BIS_fnc_advHint",
    "BIS_fnc_3DENExportOldSQM", "BIS_fnc_wp", "BIS_fnc_help",
    "BIS_fnc_typeText", "BIS_fnc_typeText2", "BIS_fnc_infoText",
    "BIS_fnc_moduleExecute", "BIS_fnc_missionName", "BIS_fnc_locationDescription",
    "BIS_fnc_initParams", "BIS_fnc_endMission", "BIS_fnc_diary",
    "BIS_fnc_showRespawnMenu", "BIS_fnc_respawnTickets",
    "BIS_fnc_addRespawnPosition", "BIS_fnc_removeRespawnPosition",
    "BIS_fnc_getRespawnPositions", "BIS_fnc_setRespawnInventory",
    "BIS_fnc_addVirtualItemCargo", "BIS_fnc_addVirtualWeaponCargo",
    "BIS_fnc_addVirtualMagazineCargo", "BIS_fnc_addVirtualBackpackCargo",
    "BIS_fnc_getVirtualItemCargo", "BIS_fnc_createRuin", "BIS_fnc_removeRuin",
    "BIS_fnc_boundingBoxCorner", "BIS_fnc_getFactions",
    "BIS_fnc_findNestedElement", "BIS_fnc_isInsideArea", "BIS_fnc_insideArea",
    "BIS_fnc_getServerVariable", "BIS_fnc_setServerVariable",
    "BIS_fnc_missionTasks", "BIS_fnc_feedbackMain",
}

# Normalize both registries to lowercase for case-insensitive lookup, then
# union the inline fallbacks with the comprehensive generated data files.
_INLINE_COMMANDS = {_normalize(name) for name in _INLINE_COMMANDS}
_INLINE_FUNCTIONS = {_normalize(name) for name in _INLINE_FUNCTIONS}
KNOWN_COMMANDS = _INLINE_COMMANDS | _load_commands_from_data()
KNOWN_FUNCTIONS = _INLINE_FUNCTIONS | _load_functions_from_data()


def is_known_command(name: str) -> bool:
    """True if ``name`` is a registered SQF command (case-insensitive)."""
    return _normalize(name) in KNOWN_COMMANDS


def is_known_function(name: str) -> bool:
    """True if ``name`` is a registered ``BIS_fnc_*``-style function (case-insensitive)."""
    return _normalize(name) in KNOWN_FUNCTIONS


def is_known(name: str) -> bool:
    """True if ``name`` is a known command or function (case-insensitive)."""
    n = _normalize(name)
    return n in KNOWN_COMMANDS or n in KNOWN_FUNCTIONS


def register(name: str, kind: str) -> None:
    """Register ``name`` at runtime.

    ``kind`` is one of ``"command"``, ``"function"``, or ``"both"``.
    """
    n = _normalize(name)
    k = kind.strip().lower()
    if k == "command":
        KNOWN_COMMANDS.add(n)
    elif k == "function":
        KNOWN_FUNCTIONS.add(n)
    elif k == "both":
        KNOWN_COMMANDS.add(n)
        KNOWN_FUNCTIONS.add(n)
    else:
        raise ValueError(f"unknown kind: {kind!r}")


if __name__ == "__main__":
    assert len(KNOWN_COMMANDS) >= 150, len(KNOWN_COMMANDS)
    assert len(KNOWN_FUNCTIONS) >= 60, len(KNOWN_FUNCTIONS)
    assert is_known_command("hint")
    assert is_known_command("HINT")
    assert is_known_function("BIS_fnc_param")
    assert is_known_function("bis_fnc_param")
    assert is_known("setPos") and is_known("BIS_fnc_spawn")
    assert not is_known("definitelyNotReal")
    register("myCustomCommand", "command")
    register("MY_Custom_Function", "function")
    assert is_known_command("mycustomcommand")
    assert is_known_function("my_custom_function")
    print("known self-test passed")
