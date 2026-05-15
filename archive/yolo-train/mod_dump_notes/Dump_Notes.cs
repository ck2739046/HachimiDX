using HarmonyLib;
using MelonLoader;
using UnityEngine;
using System;
using System.Collections;
using System.Reflection;
using System.Collections.Generic;
using System.IO;
using System.Text;
using Monitor;
using Monitor.Game;
using Manager;
using Main;
using Process;
using DB;
using Util;
using MAI2.Util;
using DiagnosticsProcess = System.Diagnostics.Process;
using DiagnosticsProcessStartInfo = System.Diagnostics.ProcessStartInfo;

[assembly: MelonInfo(typeof(default_namespace.Dump_notes), "Dump_Notes", "1.0.0", "Simon273")]
[assembly: MelonGame("sega-interactive", "Sinmai")]

namespace default_namespace {
    public class Dump_notes : MelonMod
    {
        private enum NoteCategory
        {
            Unknown,
            Touch,
            TouchHold,
            Hold,
            Star,
            TapOrBreak,
            SlideRootStar
        }

        private static FieldInfo? _activeNoteListField;
        private static FieldInfo? _activeSlideListField;
        private static bool _fieldsInitialized = false;
        private static readonly Dictionary<System.Type, Dictionary<string, FieldInfo?>> _hierarchyFieldCache = new Dictionary<System.Type, Dictionary<string, FieldInfo?>>();
        private static readonly Dictionary<System.Type, NoteReflectionAccessors> _noteAccessorCache = new Dictionary<System.Type, NoteReflectionAccessors>();
        private static readonly Dictionary<System.Type, SlideRootReflectionAccessors> _slideAccessorCache = new Dictionary<System.Type, SlideRootReflectionAccessors>();
        private static readonly Dictionary<string, DateTime> _warningLogTimeMap = new Dictionary<string, DateTime>();
        private static readonly List<NoteInfo> _frameNotesBuffer = new List<NoteInfo>(256);
        private static readonly List<string> _lineBuffer = new List<string>(512);
        private static readonly StringBuilder _lineBuilder = new StringBuilder(192);
        private const int DumpMonitorIndex = 0;
        private const int MainScreenCaptureX = 0;
        private const int MainScreenCaptureY = 0;
        private const int MainScreenCaptureWidth = 1080;
        private const int MainScreenCaptureHeight = 1080;
        private const int VideoFramerate = 60;
        private const int VideoCloseTimeoutMs = 3000;
        private static readonly Rect _mainScreenCaptureRect = new Rect(MainScreenCaptureX, MainScreenCaptureY, MainScreenCaptureWidth, MainScreenCaptureHeight);
        private static readonly WaitForEndOfFrame _waitForEndOfFrame = new WaitForEndOfFrame();

        private static string _sessionBaseName = "";
        private static string _outputFilePath = "";
        private static string _outputVideoPath = "";
        private static StreamWriter? _outputWriter;
        private static DiagnosticsProcess? _videoProcess;
        private static Stream? _videoInputStream;
        private static Texture2D? _captureTexture;
        private static byte[]? _captureFrameBuffer;
        private static bool _isFileCreated = false;
        private static bool _isDumpEnabled = false;
        private static bool _isExportSessionActive = false;
        private static bool _isVideoCaptureReady = false;
        private static bool _videoCaptureLoopStarted = false;
        private static int _pendingVideoFrameCaptureRequests = 0;
        private static int _capturedVideoFrameCount = 0;
        private const int FlushIntervalFrames = 15;
        private static int _framesSinceLastFlush = 0;
    // 注: 使用 GetKeyDown 进行边沿触发，不再需要上一帧状态
        private static List<string> _currentMusicInfo = new List<string> { "Unknown" };
        private static bool _gameStartDetected = false; // 乐曲开始标志
        private static bool _isSlideOnlyDumpEnabled = false;
        private static int _nextUniqueId = 0;
        private static readonly Dictionary<(int, bool), int> _noteIdMap = new Dictionary<(int, bool), int>();

        private class NoteReflectionAccessors
        {
            public FieldInfo? NoteObjField;
            public FieldInfo? ColorsObjectField;
            public FieldInfo? SpriteRenderField;
            public FieldInfo? AppearMsecField;
            public FieldInfo? TailMsecField;
        }

        private class SlideRootReflectionAccessors
        {
            public FieldInfo? AppearMsecField;
            public FieldInfo? StarLaunchMsecField;
            public FieldInfo? StarArriveMsecField;
            public FieldInfo? NoteIndexField;
            public FieldInfo? EndFlagField;
            public FieldInfo? BreakFlagField;
            public FieldInfo? FanStarObjsField;
            public FieldInfo? FanSpriteStarsField;
            public FieldInfo? BaseStarNoteField;
            public FieldInfo? BaseSpriteRenderField;
        }

        private class NoteInfo
        {
            public string NoteType { get; set; } = string.Empty;
            public int NoteIndex { get; set; }
            public NoteCategory Category { get; set; }
            public Vector3 Position { get; set; }
            public Vector3 LocalPosition { get; set; }
            public string Status { get; set; } = string.Empty;
            public float AppearMsec { get; set; }
            public bool IsExNote { get; set; }  // EX音符标志 (适用于Tap、Hold、Break)

            // 尺寸相关属性
            public Vector3 TouchDecorPosition { get; set; }  // Touch装饰位置
            public float TouchAlpha { get; set; }            // Touch音符透明度 (Init->Scale阶段 0->1)
            public float TouchHoldProgress { get; set; }     // TouchHold视觉进度 (0~1)
            public Vector2 HoldBodySize { get; set; }           // Hold尺寸
            public Vector3 HoldLocalScale { get; set; }         // Hold音符的localScale
            public Vector3 TapLocalScale { get; set; }          // Tap音符的localScale (Scale阶段)
            
            // StarNote相关属性
            public Vector3 StarLocalScale { get; set; }         // StarNote的localScale
            public float UserNoteSize { get; set; }             // 用户设置的音符大小
            public float StarAlpha { get; set; }                // 星星透明度（第二段）
            public float StarLaunchMsec { get; set; }           // 星星发射时间（第二段）
            public float StarArriveMsec { get; set; }           // 星星到达时间（第二段）
            public int UniqueNoteId { get; set; } = -1;         // 全局唯一ID（从0递增）
        }

        public override void OnInitializeMelon()
        {
            HarmonyInstance.PatchAll(typeof(Dump_notes));
            EnsureVideoCaptureLoopStarted();
            MelonLogger.Msg($"Load success.");
            MelonLogger.Msg($"  I键: 切换全量导出 (默认关闭)");
            MelonLogger.Msg($"  O键: 切换仅Slide导出 (默认关闭, 仅txt)");
        }

        static void InitializeFields()
        {
            if (_fieldsInitialized) return;

            var gameCtrlType = typeof(GameCtrl);
            _activeNoteListField = gameCtrlType.GetField("_activeNoteList", BindingFlags.NonPublic | BindingFlags.Instance);
            _activeSlideListField = gameCtrlType.GetField("_activeSlideList", BindingFlags.NonPublic | BindingFlags.Instance);

            _fieldsInitialized = true;
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(GameProcess), "OnStart")]
        public static void GameProcess_OnStart_Postfix(GameProcess __instance)
        {
            try
            {
                StopExportSession("track-start-reset");

                // 获取乐曲信息
                _currentMusicInfo = GetCurrentMusicInfo();
                _gameStartDetected = true;
                _nextUniqueId = 0;
                _noteIdMap.Clear();
                MelonLogger.Msg($"track start: {string.Join(" - ", _currentMusicInfo)}");

                if (_isDumpEnabled || _isSlideOnlyDumpEnabled)
                {
                    StartExportSession("track-start");
                }
                
            }
            catch (Exception e)
            {
                MelonLogger.Error($"Error getting music info on track start: {e}");
            }
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(GameProcess), "OnRelease")]
        public static void GameProcess_OnRelease_Postfix(GameProcess __instance)
        {
            try
            {
                if (_gameStartDetected)
                {
                    // 乐曲结束，重置状态
                    StopExportSession("track-end");
                    _gameStartDetected = false;
                    MelonLogger.Msg($"track end, ready for next track.");
                }
            }
            catch (Exception e)
            {
                MelonLogger.Error($"Error on track end: {e}");
            }
        }

        private static List<string> GetCurrentMusicInfo()
        {
            try
            {
                // 获取当前选择的音乐ID (第一个玩家)
                int musicId = GameManager.SelectMusicID[0];

                // 获取音乐数据
                var musicData = DataManager.Instance.GetMusic(musicId);
                if (musicData == null) return new List<string> { "Unknown" };

                // 获取难度信息
                int difficulty = GameManager.SelectDifficultyID[0];
                string[] difficultyNames = { "Basic", "Advanced", "Expert", "Master", "Re:Master" };
                string difficultyName = difficulty < difficultyNames.Length ? difficultyNames[difficulty] : $"Unknown({difficulty})";

                // 构建信息
                string musicName = musicData.name?.str ?? "Unknown";
                return new List<string> { musicId.ToString(), musicName, difficultyName };
            }
            catch (Exception e)
            {
                MelonLogger.Warning($"Failed to get music info: {e.Message}");
                return new List<string> { "Unknown" };
            }
        }

        [HarmonyPostfix]
        [HarmonyPatch(typeof(GameCtrl), "UpdateNotes")]
        public static void GameCtrl_UpdateNotes_Postfix(GameCtrl __instance)
        {
            try
            {
                if ((!_isDumpEnabled && !_isSlideOnlyDumpEnabled) || !_gameStartDetected) return;
                if (__instance == null || __instance.MonitorIndex != DumpMonitorIndex) return;

                if (!_isExportSessionActive)
                {
                    StartExportSession("update-fallback");
                    if (!_isExportSessionActive)
                        return;
                }

                InitializeFields();
                DumpAllNotePositions(__instance);
            }
            catch (Exception e)
            {
                MelonLogger.Error($"Error in note dumping: {e}");
            }
        }

        private static void DumpAllNotePositions(GameCtrl gameCtrl)
        {
            var allNotes = _frameNotesBuffer;
            allNotes.Clear();

            // 获取当前游戏时间
            var currentTime = NotesManager.GetCurrentMsec();
            float userNoteSize = GetCurrentUserNoteSize();

            // 获取活跃音符列表（第一段星星等）
            var activeNoteList = _activeNoteListField?.GetValue(gameCtrl) as List<NoteBase>;
            if (activeNoteList != null)
            {
                foreach (var note in activeNoteList)
                {
                    if (note != null && note.gameObject.activeSelf)
                    {
                        var noteInfo = GetNoteInfo(note, currentTime, userNoteSize);
                        if (noteInfo != null)
                        {
                            if (_isSlideOnlyDumpEnabled && noteInfo.Category != NoteCategory.Star)
                                continue;
                            allNotes.Add(noteInfo);
                        }
                    }
                }
            }

            // 获取活跃Slide列表（第二段星星）
            var activeSlideList = _activeSlideListField?.GetValue(gameCtrl) as List<SlideRoot>;
            if (activeSlideList != null)
            {
                for (int i = 0; i < activeSlideList.Count; i++)
                {
                    var slideRoot = activeSlideList[i];
                    if (slideRoot != null)
                    {
                        AppendSlideRootStarInfos(slideRoot, currentTime, allNotes);
                    }
                }
            }

            // 每帧都写入；无音符时由 PrintNoteFrame 写入 NA 标记
            PrintNoteFrame(currentTime, allNotes);
        }

        private static NoteInfo? GetNoteInfo(NoteBase noteBase, float currentTime, float userNoteSize)
        {
            try
            {
                var noteTypeObj = noteBase.GetType();
                string noteType = noteTypeObj.Name;
                bool isTouchHold = noteBase is TouchHoldC;
                bool isTouch = noteBase is TouchNoteB;
                bool isHold = noteBase is HoldNote || noteBase is BreakHoldNote;
                bool isStar = noteBase is StarNote || noteBase is BreakStarNote;
                bool isTapOrBreak = noteBase is TapNote || noteBase is BreakNote;
                NoteCategory noteCategory = NoteCategory.Unknown;
                var accessors = GetNoteReflectionAccessors(noteTypeObj);

                // 获取实际的音符位置
                Vector3 actualPosition = Vector3.zero;
                Vector3 actualLocalPosition = Vector3.zero;

                // 通过反射获取 NoteObj
                var noteObj = accessors.NoteObjField?.GetValue(noteBase) as GameObject;
                if (noteObj == null)
                    return null;

                actualPosition = noteObj.transform.position;
                actualLocalPosition = noteObj.transform.localPosition;

                float appearMsec = GetFieldFloat(accessors.AppearMsecField, noteBase, -1f);

                // 初始化尺寸数据
                Vector3 touchDecorPosition = Vector3.zero;
                float touchAlpha = 0f;
                float touchHoldProgress = 0f;
                Vector2 holdBodySize = Vector2.zero;
                Vector3 holdLocalScale = Vector3.zero;
                Vector3 starLocalScale = Vector3.zero;
                Vector3 tapLocalScale = Vector3.zero;

                // 处理Touch/Touch-Hold音符尺寸
                if (isTouch)
                {
                    noteCategory = isTouchHold ? NoteCategory.TouchHold : NoteCategory.Touch;

                    // 获取ColorsObject数组
                    var colors = accessors.ColorsObjectField?.GetValue(noteBase) as SpriteRenderer[];
                    if (colors != null && colors.Length > 0 && colors[0] != null)
                    {
                        touchDecorPosition = colors[0].transform.localPosition;
                        touchAlpha = colors[0].color.a;
                    }

                    if (isTouchHold)
                    {
                        touchHoldProgress = GetTouchHoldProgress(noteBase, currentTime, appearMsec);
                    }
                }
                // 处理Hold音符尺寸
                else if (isHold)
                {
                    noteCategory = NoteCategory.Hold;
                    var spriteRender = accessors.SpriteRenderField?.GetValue(noteBase) as SpriteRenderer;
                    if (spriteRender != null)
                        holdBodySize = spriteRender.size;

                    holdLocalScale = noteObj.transform.localScale;
                }
                // 处理Star音符尺寸
                else if (isStar)
                {
                    noteCategory = NoteCategory.Star;
                    // 获取NoteObj的localScale
                    starLocalScale = noteObj.transform.localScale;
                }
                // 处理Tap音符尺寸
                else if (isTapOrBreak)
                {
                    noteCategory = NoteCategory.TapOrBreak;
                    // 获取NoteObj的localScale
                    tapLocalScale = noteObj.transform.localScale;
                }

                // 获取基本信息
                var noteInfo = new NoteInfo
                {
                    NoteType = noteType,
                    NoteIndex = noteBase.GetNoteIndex(),
                    Category = noteCategory,
                    Position = actualPosition,
                    LocalPosition = actualLocalPosition,
                    Status = noteBase.GetNoteStatus().ToString(),
                    AppearMsec = appearMsec,
                    IsExNote = noteBase.ExNote,  // 获取EX音符标志

                    // touch/hold/tap/star尺寸数据
                    TouchDecorPosition = touchDecorPosition,
                    TouchAlpha = touchAlpha,
                    TouchHoldProgress = touchHoldProgress,
                    HoldBodySize = holdBodySize,
                    HoldLocalScale = holdLocalScale,
                    TapLocalScale = tapLocalScale,
                    StarLocalScale = starLocalScale,
                    UserNoteSize = userNoteSize
                };

                // 为Star音符（第一段Slide）分配Unique ID
                if (noteCategory == NoteCategory.Star)
                {
                    noteInfo.UniqueNoteId = GetOrAssignUniqueNoteId(noteInfo.NoteIndex, isSecondStage: false);
                }

                return noteInfo;
            }
            catch (Exception e)
            {
                LogWarningThrottled("note-info-" + noteBase.GetType().Name, $"Failed to get note info for {noteBase.GetType().Name}: {e.Message}");
                return null;
            }
        }

        private static float GetTouchHoldProgress(NoteBase noteBase, float currentTime, float appearMsec)
        {
            var accessors = GetNoteReflectionAccessors(noteBase.GetType());
            float tailMsec = GetFieldFloat(accessors.TailMsecField, noteBase, appearMsec);
            if (tailMsec <= appearMsec)
                return 0f;

            float progress = (currentTime - appearMsec) / (tailMsec - appearMsec);
            return ClampProgress(progress);
        }

        private static float ClampProgress(float value)
        {
            if (float.IsNaN(value) || float.IsInfinity(value))
                return 0f;
            return Mathf.Clamp01(value);
        }

        private static void AppendSlideRootStarInfos(object slideRoot, float currentTime, List<NoteInfo> target)
        {
            try
            {
                var slideRootType = slideRoot.GetType();
                var accessors = GetSlideRootReflectionAccessors(slideRootType);

                float appearMsec = GetFieldFloat(accessors.AppearMsecField, slideRoot, 0f);
                float starLaunchMsec = GetFieldFloat(accessors.StarLaunchMsecField, slideRoot, 0f);
                float starArriveMsec = GetFieldFloat(accessors.StarArriveMsecField, slideRoot, 0f);
                int noteIndex = GetFieldInt(accessors.NoteIndexField, slideRoot, -1);
                bool breakFlag = GetFieldBool(accessors.BreakFlagField, slideRoot, false);

                // 判断是否在第二段的可见范围内（从AppearMsec开始，包括缩放淡入阶段）
                if (currentTime < appearMsec)
                    return;

                // 确定状态（根据时间判断所处阶段）
                string status;
                if (currentTime < appearMsec)
                    status = "Init";  // AppearMsec之前（实际上已被过滤，不会到达这里）
                else if (currentTime < starLaunchMsec)
                    status = "Scale"; // AppearMsec → StarLaunchMsec：缩放+淡入阶段
                else if (currentTime < starArriveMsec)
                    status = "Move";  // StarLaunchMsec → StarArriveMsec：沿轨迹移动阶段
                else
                    status = "End";   // StarArriveMsec之后：已到达终点

                // 确定类型名称（添加-Move后缀）
                string typeName = breakFlag ? "BreakStarNote-Move" : "StarNote-Move";

                // SlideFan(wifi) 是 3 个星星对象：_baseStarObjs + _baseSpriteStars
                var fanStarObjs = accessors.FanStarObjsField?.GetValue(slideRoot) as GameObject[];
                var fanSpriteStars = accessors.FanSpriteStarsField?.GetValue(slideRoot) as SpriteRenderer[];

                if (fanStarObjs != null && fanStarObjs.Length > 0)
                {
                    for (int lane = 0; lane < fanStarObjs.Length; lane++)
                    {
                        var starObj = fanStarObjs[lane];
                        if (starObj == null || !starObj.activeSelf)
                            continue;

                        var sprite = (fanSpriteStars != null && lane < fanSpriteStars.Length) ? fanSpriteStars[lane] : null;
                        float alpha = sprite?.color.a ?? 0f;

                        target.Add(CreateSlideStarNoteInfo(
                            typeName,
                            noteIndex,
                            starObj,
                            status,
                            appearMsec,
                            breakFlag,
                            alpha,
                            starLaunchMsec,
                            starArriveMsec));
                    }

                    return;
                }

                // 普通 SlideRoot：单个 _baseStarNote + BaseSpriteRender
                var baseStarNote = accessors.BaseStarNoteField?.GetValue(slideRoot) as GameObject;
                if (baseStarNote == null || !baseStarNote.activeSelf)
                    return;

                var baseSpriteRender = accessors.BaseSpriteRenderField?.GetValue(slideRoot) as SpriteRenderer;
                float baseAlpha = baseSpriteRender?.color.a ?? 0f;

                target.Add(CreateSlideStarNoteInfo(
                    typeName,
                    noteIndex,
                    baseStarNote,
                    status,
                    appearMsec,
                    breakFlag,
                    baseAlpha,
                    starLaunchMsec,
                    starArriveMsec));
            }
            catch (Exception e)
            {
                LogWarningThrottled("slide-root-info", $"Failed to get slide root star info: {e.Message}");
            }
        }

        private static NoteInfo CreateSlideStarNoteInfo(
            string typeName,
            int noteIndex,
            GameObject starObj,
            string status,
            float appearMsec,
            bool breakFlag,
            float alpha,
            float starLaunchMsec,
            float starArriveMsec)
        {
            var info = new NoteInfo
            {
                NoteType = typeName,
                NoteIndex = noteIndex,
                Category = NoteCategory.SlideRootStar,
                Position = starObj.transform.position,
                LocalPosition = starObj.transform.localPosition,
                Status = status,
                AppearMsec = appearMsec,
                IsExNote = breakFlag, // Break就是EX

                // 第二段星星特有数据
                StarLocalScale = starObj.transform.localScale,
                StarAlpha = alpha,
                StarLaunchMsec = starLaunchMsec,
                StarArriveMsec = starArriveMsec,
                UserNoteSize = 1f // SlideRoot的星星尺寸已经包含在localScale中
            };
            info.UniqueNoteId = GetOrAssignUniqueNoteId(noteIndex, isSecondStage: true);
            return info;
        }

        private static NoteReflectionAccessors GetNoteReflectionAccessors(System.Type type)
        {
            if (_noteAccessorCache.TryGetValue(type, out var cached))
            {
                return cached;
            }

            var accessors = new NoteReflectionAccessors
            {
                NoteObjField = GetFieldFromHierarchy(type, "NoteObj"),
                ColorsObjectField = GetFieldFromHierarchy(type, "ColorsObject"),
                SpriteRenderField = GetFieldFromHierarchy(type, "SpriteRender"),
                AppearMsecField = GetFieldFromHierarchy(type, "AppearMsec"),
                TailMsecField = GetFieldFromHierarchy(type, "TailMsec")
            };

            _noteAccessorCache[type] = accessors;
            return accessors;
        }

        private static SlideRootReflectionAccessors GetSlideRootReflectionAccessors(System.Type type)
        {
            if (_slideAccessorCache.TryGetValue(type, out var cached))
            {
                return cached;
            }

            var accessors = new SlideRootReflectionAccessors
            {
                AppearMsecField = GetFieldFromHierarchy(type, "AppearMsec"),
                StarLaunchMsecField = GetFieldFromHierarchy(type, "StarLaunchMsec"),
                StarArriveMsecField = GetFieldFromHierarchy(type, "StarArriveMsec"),
                NoteIndexField = GetFieldFromHierarchy(type, "NoteIndex"),
                EndFlagField = GetFieldFromHierarchy(type, "EndFlag"),
                BreakFlagField = GetFieldFromHierarchy(type, "BreakFlag"),
                FanStarObjsField = GetFieldFromHierarchy(type, "_baseStarObjs"),
                FanSpriteStarsField = GetFieldFromHierarchy(type, "_baseSpriteStars"),
                BaseStarNoteField = GetFieldFromHierarchy(type, "_baseStarNote"),
                BaseSpriteRenderField = GetFieldFromHierarchy(type, "BaseSpriteRender")
            };

            _slideAccessorCache[type] = accessors;
            return accessors;
        }

        private static FieldInfo? GetFieldFromHierarchy(System.Type type, string fieldName)
        {
            if (!_hierarchyFieldCache.TryGetValue(type, out var fieldsByName))
            {
                fieldsByName = new Dictionary<string, FieldInfo?>();
                _hierarchyFieldCache[type] = fieldsByName;
            }

            if (fieldsByName.TryGetValue(fieldName, out var cachedField))
            {
                return cachedField;
            }

            var current = type;
            while (current != null)
            {
                var field = current.GetField(fieldName, BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.Instance);
                if (field != null)
                {
                    fieldsByName[fieldName] = field;
                    return field;
                }

                current = current.BaseType;
            }

            fieldsByName[fieldName] = null;
            return null;
        }

        private static float GetCurrentUserNoteSize()
        {
            try
            {
                if (GamePlayManager.Instance != null)
                {
                    return GamePlayManager.Instance.GetGameScore(0).UserOption.NoteSize.GetValue();
                }
            }
            catch
            {
            }

            return 1f;
        }

        private static float GetFieldFloat(FieldInfo? field, object instance, float defaultValue)
        {
            if (field == null)
                return defaultValue;

            var value = field.GetValue(instance);
            if (value is float f)
                return f;
            if (value is double d)
                return (float)d;
            if (value is int i)
                return i;
            return defaultValue;
        }

        private static int GetFieldInt(FieldInfo? field, object instance, int defaultValue)
        {
            if (field == null)
                return defaultValue;

            var value = field.GetValue(instance);
            if (value is int i)
                return i;
            if (value is float f)
                return (int)f;
            if (value is double d)
                return (int)d;
            return defaultValue;
        }

        private static bool GetFieldBool(FieldInfo? field, object instance, bool defaultValue)
        {
            if (field == null)
                return defaultValue;

            var value = field.GetValue(instance);
            if (value is bool b)
                return b;
            return defaultValue;
        }

        private static int GetOrAssignUniqueNoteId(int noteIndex, bool isSecondStage)
        {
            var key = (noteIndex, isSecondStage);
            if (!_noteIdMap.TryGetValue(key, out int id))
            {
                id = _nextUniqueId++;
                _noteIdMap[key] = id;
            }
            return id;
        }

        private static void PrintNoteFrame(float currentTime, List<NoteInfo> notes)
        {
            try
            {
                if (!EnsureOutputWriter())
                    return;

                // 构建数据行
                var lines = _lineBuffer;
                lines.Clear();
                lines.Add($"Time:{currentTime:F4}|Count:{notes.Count}");

                if (notes.Count == 0)
                {
                    lines.Add("NA");
                }

                for (int i = 0; i < notes.Count; i++)
                {
                    var note = notes[i];

                    // 基础信息
                    _lineBuilder.Clear();
                    _lineBuilder.Append(note.NoteType).Append('-').Append(note.NoteIndex).Append(" | ");
                    _lineBuilder.AppendFormat("{0:F4}, {1:F4}", note.Position.x, note.Position.y).Append(" | ");
                    _lineBuilder.AppendFormat("{0:F4}, {1:F4}", note.LocalPosition.x, note.LocalPosition.y).Append(" | ");
                    _lineBuilder.Append(note.Status).Append(" | ");
                    _lineBuilder.AppendFormat("{0:F4}", note.AppearMsec).Append(" | ");
                    _lineBuilder.Append("EX:").Append(note.IsExNote ? "Y" : "N").Append(" | UniqueId:").Append(note.UniqueNoteId);
                    
                    // Touch/Touch-Hold音符
                    if (note.Category == NoteCategory.Touch || note.Category == NoteCategory.TouchHold)
                    {
                        var decorPosition = note.TouchDecorPosition;
                        _lineBuilder.AppendFormat(" | TouchDecorPosition: {0:F4} | Alpha: {1:F4}", decorPosition.y, note.TouchAlpha);
                        if (note.Category == NoteCategory.TouchHold)
                        {
                            _lineBuilder.AppendFormat(" | TouchHoldProgress: {0:F4}", note.TouchHoldProgress);
                        }
                    }
                    // Hold音符
                    else if (note.Category == NoteCategory.Hold)
                    {
                        _lineBuilder.AppendFormat(" | HoldScale: {0:F4},{1:F4} | HoldBodySize: {2:F4}", note.HoldLocalScale.x, note.HoldLocalScale.y, note.HoldBodySize.y);
                    }
                    // Star音符-Move（第二段）
                    else if (note.Category == NoteCategory.SlideRootStar)
                    {
                        _lineBuilder.AppendFormat(" | StarScale: {0:F4},{1:F4}", note.StarLocalScale.x, note.StarLocalScale.y);
                        _lineBuilder.AppendFormat(" | Alpha: {0:F4}", note.StarAlpha);
                        _lineBuilder.AppendFormat(" | LaunchMsec: {0:F4} | ArriveMsec: {1:F4}", note.StarLaunchMsec, note.StarArriveMsec);
                    }
                    // Star音符（第一段）
                    else if (note.Category == NoteCategory.Star)
                    {
                        _lineBuilder.AppendFormat(" | StarScale: {0:F4},{1:F4} | UserNoteSize: {2:F4}", note.StarLocalScale.x, note.StarLocalScale.y, note.UserNoteSize);
                    }
                    // Tap音符
                    else if (note.Category == NoteCategory.TapOrBreak)
                    {
                        _lineBuilder.AppendFormat(" | TapScale: {0:F4},{1:F4}", note.TapLocalScale.x, note.TapLocalScale.y);
                    }

                    lines.Add(_lineBuilder.ToString());
                }

                if (_outputWriter == null)
                    return;

                for (int i = 0; i < lines.Count; i++)
                {
                    _outputWriter.WriteLine(lines[i]);
                }

                _framesSinceLastFlush++;
                if (_framesSinceLastFlush >= FlushIntervalFrames)
                {
                    _outputWriter.Flush();
                    _framesSinceLastFlush = 0;
                }

                if (!_isSlideOnlyDumpEnabled)
                {
                    RequestVideoFrameCapture();
                }
            }
            catch (Exception e)
            {
                LogWarningThrottled("write-note-frame", $"Failed to write note frame to file: {e.Message}");
            }
        }

        private static void StartExportSession(string reason)
        {
            if (_isExportSessionActive)
                return;

            if ((!_isDumpEnabled && !_isSlideOnlyDumpEnabled) || !_gameStartDetected)
                return;

            BuildSessionOutputPaths();

            bool textReady = EnsureOutputWriter();
            bool videoReady = _isSlideOnlyDumpEnabled ? false : EnsureVideoWriter();
            _isExportSessionActive = textReady;
            _pendingVideoFrameCaptureRequests = 0;
            _capturedVideoFrameCount = 0;

            if (!textReady)
            {
                LogWarningThrottled("start-export-session", "Failed to start export session because txt writer is unavailable.");
                CloseVideoWriter();
                return;
            }

            if (!videoReady)
            {
                LogWarningThrottled("start-export-session-video", "Video export disabled for this session. txt export will continue.");
            }

            MelonLogger.Msg($"export session started ({reason}).");
        }

        private static void StopExportSession(string reason)
        {
            bool hadSessionData = _isExportSessionActive || _isFileCreated || _videoProcess != null || !string.IsNullOrEmpty(_outputFilePath) || !string.IsNullOrEmpty(_outputVideoPath);

            _isExportSessionActive = false;
            _pendingVideoFrameCaptureRequests = 0;

            CloseOutputWriter();
            CloseVideoWriter();

            _sessionBaseName = "";
            _outputFilePath = "";
            _outputVideoPath = "";

            if (hadSessionData)
            {
                MelonLogger.Msg($"export session stopped ({reason}).");
            }
        }

        private static void BuildSessionOutputPaths()
        {
            if (!string.IsNullOrEmpty(_outputFilePath) && !string.IsNullOrEmpty(_outputVideoPath))
                return;

            var desktopPath = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
            var timestamp = DateTime.Now.ToString("yyyy-MM-dd_HH-mm-ss");
            var musicIdRaw = _currentMusicInfo.Count > 0 ? _currentMusicInfo[0] : "Unknown";
            var safeMusicId = SanitizeFileNameToken(musicIdRaw);

            _sessionBaseName = $"{safeMusicId}_{timestamp}";
            _outputFilePath = Path.Combine(desktopPath, _sessionBaseName + ".txt");
            _outputVideoPath = Path.Combine(desktopPath, _sessionBaseName + ".mp4");
        }

        private static string SanitizeFileNameToken(string value)
        {
            if (string.IsNullOrWhiteSpace(value))
                return "Unknown";

            var invalidChars = Path.GetInvalidFileNameChars();
            var builder = new StringBuilder(value.Length);
            for (int i = 0; i < value.Length; i++)
            {
                char c = value[i];
                bool isInvalid = false;
                for (int j = 0; j < invalidChars.Length; j++)
                {
                    if (c == invalidChars[j])
                    {
                        isInvalid = true;
                        break;
                    }
                }

                builder.Append(isInvalid ? '_' : c);
            }

            return builder.Length > 0 ? builder.ToString() : "Unknown";
        }

        private static bool EnsureOutputWriter()
        {
            if (_outputWriter != null && _isFileCreated)
                return true;

            try
            {
                if (string.IsNullOrEmpty(_outputFilePath))
                {
                    BuildSessionOutputPaths();
                }

                if (string.IsNullOrEmpty(_outputFilePath))
                    return false;

                var startedAt = DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss");

                _outputWriter = new StreamWriter(_outputFilePath, false, Encoding.UTF8);
                _outputWriter.WriteLine($"Note Dump Started at {startedAt}");
                _outputWriter.WriteLine($"Music Info: {string.Join(" - ", _currentMusicInfo)}");
                _outputWriter.WriteLine($"Video File: {_outputVideoPath}");
                _outputWriter.WriteLine("Format: Type-Index | PosX, PosY | LocalX, LocalY | Status | AppearMsec | IsEX | UniqueId | (Details...)");
                _outputWriter.WriteLine("  Touch: TouchDecor+Alpha(+TouchHoldProgress) | Hold: HoldScale+HoldSize | Tap/Break: TapScale");
                _outputWriter.WriteLine("  Star(1st): StarScale+UserNoteSize | Star-Move(2nd): StarScale+Alpha+LaunchMsec+ArriveMsec");
                _outputWriter.WriteLine("=".PadRight(30, '='));

                _framesSinceLastFlush = 0;
                _isFileCreated = true;
                MelonLogger.Msg($"Note dump output file: {_outputFilePath}");
                return true;
            }
            catch (Exception e)
            {
                LogWarningThrottled("create-output-writer", $"Failed to create output file: {e.Message}");
                CloseOutputWriter();
                return false;
            }
        }

        private static bool EnsureVideoWriter()
        {
            if (_videoProcess != null && !_videoProcess.HasExited && _videoInputStream != null)
            {
                _isVideoCaptureReady = true;
                return true;
            }

            if (string.IsNullOrEmpty(_outputVideoPath))
            {
                BuildSessionOutputPaths();
            }

            if (string.IsNullOrEmpty(_outputVideoPath))
                return false;

            if (Screen.width < MainScreenCaptureX + MainScreenCaptureWidth || Screen.height < MainScreenCaptureY + MainScreenCaptureHeight)
            {
                LogWarningThrottled("video-capture-rect", $"Screen size is too small for capture rect. screen={Screen.width}x{Screen.height}");
                return false;
            }

            try
            {
                string ffmpegArgs =
                    $"-hide_banner -loglevel error -nostats -y -f rawvideo -pixel_format rgb24 -video_size {MainScreenCaptureWidth}x{MainScreenCaptureHeight} -framerate {VideoFramerate} -i - -vf vflip -an -c:v libx264 -preset ultrafast -crf 18 -pix_fmt yuv420p \"{_outputVideoPath}\"";

                var startInfo = new DiagnosticsProcessStartInfo
                {
                    FileName = "ffmpeg",
                    Arguments = ffmpegArgs,
                    UseShellExecute = false,
                    RedirectStandardInput = true,
                    RedirectStandardOutput = false,
                    RedirectStandardError = false,
                    CreateNoWindow = true
                };

                var process = new DiagnosticsProcess();
                process.StartInfo = startInfo;

                if (!process.Start())
                {
                    LogWarningThrottled("video-start", "ffmpeg process did not start.");
                    _isVideoCaptureReady = false;
                    return false;
                }

                _videoProcess = process;
                _videoInputStream = process.StandardInput.BaseStream;
                _isVideoCaptureReady = true;

                MelonLogger.Msg($"Note dump video file: {_outputVideoPath}");
                return true;
            }
            catch (Exception e)
            {
                LogWarningThrottled("video-start", $"Failed to start ffmpeg: {e.Message}");
                CloseVideoWriter();
                return false;
            }
        }

        private static void CloseOutputWriter()
        {
            try
            {
                if (_outputWriter != null)
                {
                    _outputWriter.Flush();
                    _outputWriter.Dispose();
                }
            }
            catch (Exception e)
            {
                LogWarningThrottled("close-output-writer", $"Failed to close output file: {e.Message}");
            }
            finally
            {
                _outputWriter = null;
                _framesSinceLastFlush = 0;
                _isFileCreated = false;
            }
        }

        private static void CloseVideoWriter()
        {
            _isVideoCaptureReady = false;

            try
            {
                if (_videoInputStream != null)
                {
                    _videoInputStream.Flush();
                    _videoInputStream.Dispose();
                }
            }
            catch (Exception e)
            {
                LogWarningThrottled("video-close-stream", $"Failed to close ffmpeg input stream: {e.Message}");
            }
            finally
            {
                _videoInputStream = null;
            }

            try
            {
                if (_videoProcess != null)
                {
                    if (!_videoProcess.HasExited)
                    {
                        if (!_videoProcess.WaitForExit(VideoCloseTimeoutMs))
                        {
                            LogWarningThrottled("video-close-timeout", "ffmpeg did not exit in time, killing process.");
                            _videoProcess.Kill();
                            _videoProcess.WaitForExit();
                        }
                    }
                }
            }
            catch (Exception e)
            {
                LogWarningThrottled("video-close-process", $"Failed to close ffmpeg process: {e.Message}");
            }
            finally
            {
                if (_videoProcess != null)
                {
                    _videoProcess.Dispose();
                    _videoProcess = null;
                }
            }

            ReleaseCaptureTexture();
        }

        private static void EnsureVideoCaptureLoopStarted()
        {
            if (_videoCaptureLoopStarted)
                return;

            MelonCoroutines.Start(VideoCaptureLoop());
            _videoCaptureLoopStarted = true;
        }

        private static IEnumerator VideoCaptureLoop()
        {
            while (true)
            {
                if (!_isExportSessionActive || !_isVideoCaptureReady || _pendingVideoFrameCaptureRequests <= 0)
                {
                    yield return null;
                    continue;
                }

                yield return _waitForEndOfFrame;

                if (!_isExportSessionActive || !_isVideoCaptureReady || _pendingVideoFrameCaptureRequests <= 0)
                    continue;

                _pendingVideoFrameCaptureRequests--;
                TryCaptureMainScreenFrame();
            }
        }

        private static void RequestVideoFrameCapture()
        {
            if (!_isExportSessionActive || !_isVideoCaptureReady)
                return;

            if (_pendingVideoFrameCaptureRequests < 2)
            {
                _pendingVideoFrameCaptureRequests++;
            }
        }

        private static void EnsureCaptureTexture()
        {
            if (_captureTexture != null)
                return;

            _captureTexture = new Texture2D(MainScreenCaptureWidth, MainScreenCaptureHeight, TextureFormat.RGB24, mipChain: false);
        }

        private static void ReleaseCaptureTexture()
        {
            if (_captureTexture != null)
            {
                UnityEngine.Object.Destroy(_captureTexture);
                _captureTexture = null;
            }

            _captureFrameBuffer = null;
        }

        private static void TryCaptureMainScreenFrame()
        {
            if (!_isVideoCaptureReady || _videoInputStream == null)
                return;

            try
            {
                EnsureCaptureTexture();
                if (_captureTexture == null)
                    return;

                _captureTexture.ReadPixels(_mainScreenCaptureRect, 0, 0);
                _captureTexture.Apply(updateMipmaps: false);

                var rawData = _captureTexture.GetRawTextureData();
                if (_captureFrameBuffer == null || _captureFrameBuffer.Length != rawData.Length)
                {
                    _captureFrameBuffer = new byte[rawData.Length];
                }

                Buffer.BlockCopy(rawData, 0, _captureFrameBuffer, 0, rawData.Length);
                _videoInputStream.Write(_captureFrameBuffer, 0, _captureFrameBuffer.Length);
                _capturedVideoFrameCount++;
            }
            catch (Exception e)
            {
                LogWarningThrottled("video-write", $"Failed to write video frame: {e.Message}");
                CloseVideoWriter();
            }
        }

        private static void LogWarningThrottled(string key, string message)
        {
            var now = DateTime.UtcNow;
            if (_warningLogTimeMap.TryGetValue(key, out var lastLogTime))
            {
                var diff = now - lastLogTime;
                if (diff.TotalSeconds < 1.0)
                    return;
            }

            _warningLogTimeMap[key] = now;
            MelonLogger.Warning(message);
        }
        
        // 热键监听
        [HarmonyPostfix]
        [HarmonyPatch(typeof(GameMainObject), "Update")]
        public static void OnGameMainObjectUpdate()
        {
            // 边沿触发：按下一次 I 键，切换全量导出
            if (Input.GetKeyDown(KeyCode.I))
            {
                if (_isDumpEnabled)
                {
                    // 关闭全量
                    _isDumpEnabled = false;
                    StopExportSession("hotkey-off");
                    MelonLogger.Msg("stop dump notes.");
                }
                else
                {
                    // 开启全量，关闭Slide-Only
                    if (_isSlideOnlyDumpEnabled)
                    {
                        _isSlideOnlyDumpEnabled = false;
                        StopExportSession("hotkey-off-slide-only");
                        MelonLogger.Msg("slide-only dump disabled (switched to full dump).");
                    }
                    _isDumpEnabled = true;
                    if (_gameStartDetected)
                    {
                        StartExportSession("hotkey-on");
                        MelonLogger.Msg("start dump notes.");
                    }
                    else
                    {
                        MelonLogger.Msg("dump notes armed. wait track start.");
                    }
                }
            }

            // 边沿触发：按下一次 O 键，切换Slide-Only导出
            if (Input.GetKeyDown(KeyCode.O))
            {
                if (_isSlideOnlyDumpEnabled)
                {
                    // 关闭Slide-Only
                    _isSlideOnlyDumpEnabled = false;
                    StopExportSession("hotkey-off-slide-only");
                    MelonLogger.Msg("stop slide-only dump.");
                }
                else
                {
                    // 开启Slide-Only，关闭全量
                    if (_isDumpEnabled)
                    {
                        _isDumpEnabled = false;
                        StopExportSession("hotkey-off");
                        MelonLogger.Msg("full dump disabled (switched to slide-only).");
                    }
                    _isSlideOnlyDumpEnabled = true;
                    if (_gameStartDetected)
                    {
                        StartExportSession("hotkey-on-slide-only");
                        MelonLogger.Msg("start slide-only dump.");
                    }
                    else
                    {
                        MelonLogger.Msg("slide-only dump armed. wait track start.");
                    }
                }
            }
        }
    }
}
