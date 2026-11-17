-- license:BSD-3-Clause
-- copyright-holders: sparrowred

-- VGMPlay driver script.
-- Measures audio levels, levels the loudness towards LEVEL_TARGET_DB, fades
-- out a playback that -seconds_to_run cuts (VGMPLAY_FADE_SECONDS), takes
-- commands from the control socket and reports playback statistics.
--
-- Playback terminates on:
--   1. "exit" received on the control socket
--   2. MAME's own -seconds_to_run limit (the final frames are sent
--      PREEXIT_MARGIN seconds before, see the pre-exit plan)
--   3. SILENCE_SECONDS of unbroken silence, at any time of the playback

local LOG_TO_STDOUT = false
-- Maximum text bytes per message, one frame stays well below 1 KiB.
local LOG_MAX_TEXT = 480
-- Total log bytes per session. Bounds a blocking write when Python is gone:
-- without this the kernel buffer would fill and could stall emulation.
local LOG_MAX_TOTAL_BYTES = 65536
-- Part of the budget only the final sequence (RMS_STATS -> VGM_VOLUME ->
-- EXIT_NOW, at most 3 frames of < 512 bytes) may use, so a chatty playback
-- cannot cost the statistics of its end.
local LOG_FINAL_RESERVE = 2048

--
-- Audio measurement configuration
--
local FINGERPRINT_SECONDS = 0.10  -- ~100ms fingerprint window
--
-- Silence detection configuration
--
-- Active for the whole playback: SILENCE_SECONDS of unbroken silence end the
-- VGM, at the start as well as after the music. Silence is a callback RMS
-- below SILENCE_THRESHOLD or a flat buffer: after some tracks the mixer
-- keeps handing out one constant non-zero value, which is inaudible but far
-- above the threshold. Flat means the samples of every channel are equal -
-- a held square tone has a constant RMS too, but not constant samples.
local SILENCE_THRESHOLD = 0.001  -- RMS below this counts as silence
local SILENCE_SECONDS = 3.0      -- sustained silence required to exit
local SILENCE_FLAT_EPS = 1e-6    -- max - min of a channel at or below this: flat
local DIAG_SILENCE_LOG = true    -- SILENCE diagnostics (one frame per long dip)
-- Music with rests dips below the threshold at note rate: only a dip longer
-- than SILENCE_DIAG_MIN_SEC is logged, once at its end, and at most
-- SILENCE_DIAG_MAX_FRAMES times per playback. RMS_STATS counts all of them.
local SILENCE_DIAG_MIN_SEC = 0.2
local SILENCE_DIAG_MAX_FRAMES = 20
--
-- Dynamic loudness leveling configuration
--
local LEVEL_INITIAL_GAIN_DB = -2.0 -- immediate attenuation applied at t=0
local LEVEL_TARGET_DB    = -22.0  -- configurable target loudness (dBFS)
local LEVEL_MAX_GAIN_DB  = 12.0  -- configurable maximum positive gain
local LEVEL_HEADROOM_DB  = -1.0   -- sample peak limit for positive gain
local LEVEL_NOISE_FLOOR  = -48.0  -- windows at or below this are not measured
local LEVEL_MIN_GAIN_DB  = -24.0 -- runaway floor for negative gain
local LEVEL_RAMP_DB_PER_ADJ = 1.0 -- max cut per adjustment
local LEVEL_RAMP_UP_DB_PER_ADJ = 0.5 -- max boost per adjustment (slower: a
                                  -- quiet intro may be followed by a loud part)
local LEVEL_START_DELAY  = 0.5    -- start adjusting after ~0.5s of valid measurements
local LEVEL_REEVAL_INT   = 0.5    -- re-evaluate every ~0.5s
local LEVEL_ROLL_SEC     = 1.5    -- rolling window ~1-2s for decisions

--
-- Leveling cutoff (freeze the gain once converged, never adapt forever)
--
-- Active leveling is frozen automatically: not before LEVEL_LOCK_MIN_SEC,
-- as soon as the gain has stayed within LEVEL_LOCK_DITHER_DB of a stable
-- anchor for LEVEL_LOCK_STABLE_SEC, and always by LEVEL_LOCK_MAX_SEC. After
-- the lock the gain never rises again; RMS measurement continues. It is
-- still cut when the output level exceeds the target by more than
-- LEVEL_LOCK_GUARD_DB or a later sample peak breaks the headroom (quiet
-- intro, loud main part). The three times are seconds of measured audio
-- (windows above LEVEL_NOISE_FLOOR), not run time.
local LEVEL_LOCK_MIN_SEC    = 10.0 -- no freeze before 10s of measured audio
local LEVEL_LOCK_MAX_SEC    = 15.0 -- hard ceiling: freeze after 15s of measured audio
local LEVEL_LOCK_STABLE_SEC = 3.0  -- gain must be settled for this long (measured)
local LEVEL_LOCK_DITHER_DB  = 2.0  -- +/- dither counts as settled
local LEVEL_LOCK_GUARD_DB   = 4.0  -- locked: cut once this far above the target


--
-- seconds_to_run pre-exit configuration
--
-- Emulated seconds before MAME's -seconds_to_run limit at which the final
-- statistics are sent. vgmplay has no screens, so the periodic callback runs
-- once per emulated frame (~60 Hz): 1.0s is ~60 frames of slack and MAME only
-- checks its limit on a non-skipped frame after the same callback has run.
-- For short runs the trigger falls back to half of the run (see init below).
local PREEXIT_MARGIN = 1.0

--
-- Fade-out configuration
--
-- Python sets VGMPLAY_FADE_SECONDS for a playback that -seconds_to_run cuts
-- inside the music (looping tracks, capped tracks, intro VGMs); a track that
-- runs to its own end gets none. The master volume then falls linearly in dB
-- by FADE_FLOOR_DB over the last seconds and is muted at the limit. A socket
-- exit (stop, skip) ends at once, without fade.
local FADE_FLOOR_DB = -40.0      -- attenuation reached at the end of the fade
local FADE_MAX_SECONDS = 10.0    -- longer requests are ignored
local FADE_MUTE_DB = -96.0       -- lowest sound.volume

-- Maximum bytes of unparsed socket input to keep before discarding.
local RX_MAX_BYTES = 4096

--
-- Socket / Exit state
--
local exiting = false
local rx = ""
local socket = nil
local log_socket_ok = false  -- socket logging enabled
local log_bytes_sent = 0
local log_dropped = 0
-- defined below (after sanitize); declared here so the leveling can use it
local log
local silence_dips = 0  -- dips longer than SILENCE_DIAG_MIN_SEC (RMS_STATS)

-- seconds_to_run pre-exit trigger, set once during initialisation below.
local preexit_seconds = 0  -- MAME's -seconds_to_run (0 = unlimited/disabled)
local preexit_at = 0       -- emulated time at which the final logs are sent

-- The final statistics sequence must be emitted exactly once per playback.
-- The flag is a global (like VGMPLAY_SOCKET) so it also protects when a
-- second script execution or a second registered callback overlaps the first
-- one: globals survive the autoboot re-execution, locals of an earlier
-- execution do not.
-- VGMPLAY_FINAL_LOGS_SENT = false  -- set by emit_final_logs(), nil until then

-- The open control connection lives in the global VGMPLAY_SOCKET so it survives
-- the autoboot re-execution (see the control socket section). It is
-- deliberately not initialised here: assigning nil on every execution would
-- defeat the reuse. A fresh lua state simply starts with nil.

--
-- Audio statistics
--
local diag_last_rms = 0
local total_energy_sum = 0      -- Sum of (rms^2) across all fingerprint windows
local total_energy_samples = 0  -- Total fingerprint samples (sum of fingerprint_samples per window)
local peak_energy = 0           -- Peak RMS observed in any fingerprint window
local peak_sample = 0           -- Largest absolute sample seen (leveling headroom)
local periodic_calls = 0         -- calls of the periodic callback (RMS_STATS periodic=)
local fingerprint_count = 0     -- Number of fingerprint windows completed
-- The same over music windows only (review M9): neither flat nor at or below
-- LEVEL_NOISE_FLOOR, i.e. the windows the leveling measures. Silence, a frozen
-- mixer and the tail before a silence exit stay out.
local music_energy_sum = 0
local music_energy_samples = 0
local music_windows = 0

--
-- Dynamic leveling state
--
local level_win_energy_list = {}  -- recent window energy (RMS of 100ms window) values
local level_win_time_list = {}    -- timestamps of those windows (emulated seconds)
local level_total_valid_sec = 0   -- total valid measurement seconds accumulated from windows
local level_last_adj_sec = -1e12  -- time of last adjustment
local level_current_gain_db = 0.0
local level_manual_override = false
local level_baseline_vol = nil

-- Leveling cutoff state (see LEVEL_LOCK_* config): once level_locked is set
-- the gain only goes down for the rest of the run. The dither anchor is the
-- gain at which the stability window started.
local level_locked = false
local level_anchor_gain = nil
local level_anchor_time = 0     -- measured seconds (level_total_valid_sec)

-- Diagnostics of the locked phase for the final RMS_STATS (review M2): when
-- the lock fell, the gain it froze, the loudest predicted output level seen
-- by a locked evaluation and the sum of all cuts made while locked.
local level_lock_time = nil
local level_lock_gain = nil
local level_post_lock_max_db = -math.huge
local level_locked_cut_db = 0

-- Fade-out state (see the fade-out configuration): planned once during
-- initialisation, fade_base_vol is the volume the fade started from.
local fade_len = 0          -- seconds, 0 = no fade
local fade_start_at = 0     -- emulated time the fade begins
local fade_base_vol = nil   -- set when the fade has begun



--
-- Logging
--

-- One line, printable, bounded: CR/LF/tab would break the line framing.
local function sanitize(text, limit)
    text = tostring(text)
    text = (text:gsub("[\r\n\t]", " "))
    limit = limit or LOG_MAX_TEXT
    if limit < 1 then
        limit = 1
    end
    if #text > limit then
        text = text:sub(1, limit)
    end
    return text
end

-- MAME builds embed Lua 5.1 to 5.4: math.log10 only exists from 5.2 and the
-- two argument math.log(x, base) form only from 5.2 too, so fall back to the
-- single argument division that every version accepts.
local function log10(x)
    if math.log10 then
        return math.log10(x)
    end
    return math.log(x) / math.log(10)
end

local function linear_to_db(linear)
    if linear <= 0 then
        return -math.huge
    end
    return 20.0 * log10(linear)
end

local function apply_gain(new_gain_db)
    -- level_baseline_vol is set when the script loads, before the first call
    level_current_gain_db = new_gain_db
    -- sound.volume is float dB (luaengine.cpp: set_master_gain(db_to_linear(db)));
    -- no rounding - the loop works with fractional gain and would otherwise
    -- limit-cycle around whole dB steps
    local target_vol = level_baseline_vol + level_current_gain_db
    if target_vol < -96 then target_vol = -96 end
    if target_vol > 96 then target_vol = 96 end
    pcall(function()
        manager.machine.sound.volume = target_vol
    end)
end


local function compute_recent_rms_db()
    -- compute recent RMS from rolling window over last LEVEL_ROLL_SEC
    -- average energies linearly: rms_recent = sqrt(mean(rms_win_i^2))
    local now = emu.time()
    local cutoff = now - LEVEL_ROLL_SEC
    -- Remove expired entries; oldest timestamps are first.
    while #level_win_time_list > 0 and level_win_time_list[1] < cutoff - 1e-9 do
        table.remove(level_win_time_list, 1)
        table.remove(level_win_energy_list, 1)
    end
    if #level_win_energy_list == 0 then
        return -math.huge, 0
    end
    local sum_sq = 0
    for i = 1, #level_win_energy_list do
        local e = level_win_energy_list[i]
        sum_sq = sum_sq + e * e
    end
    local rms_recent = math.sqrt(sum_sq / #level_win_energy_list)
    local rms_db = linear_to_db(rms_recent)
    return rms_db, #level_win_energy_list
end

-- " out_db=<dB>": predicted output level of the recent music at the volume
-- MAME uses now (sound.volume + measured source level). Empty when there is
-- no measurement (empty rolling window, no sound hook) or no sound.volume.
-- Read by Python for the music info (review M5).
local function out_db_field()
    local rms_db = compute_recent_rms_db()
    if rms_db == -math.huge then
        return ""
    end
    local ok, volume = pcall(function()
        return manager.machine.sound.volume
    end)
    if not ok or type(volume) ~= "number" then
        return ""
    end
    return string.format(" out_db=%.2f", volume + rms_db)
end

-- " gain_db=<dB> state=<auto|locked|manual>": the gain UMSA puts on the
-- track and who sets it (leveling, frozen leveling, user). Python shows both
-- at the end of the music info.
local function gain_state_fields(gain_db, state)
    return string.format(" gain_db=%.2f state=%s", gain_db, state)
end

local function lock_leveling(now, text)
    level_locked = true
    level_lock_time = now
    level_lock_gain = level_current_gain_db
    log("INFO", text .. out_db_field() .. gain_state_fields(level_current_gain_db, "locked"))
end

local function update_leveling()
    -- No gain change may follow the final statistics sequence or work
    -- against the fade-out
    if VGMPLAY_FINAL_LOGS_SENT or level_manual_override or fade_base_vol then
        return
    end
    local now = emu.time()
    -- Freeze the leveled gain once converged: hard ceiling LEVEL_LOCK_MAX_SEC,
    -- otherwise when the gain has stayed within LEVEL_LOCK_DITHER_DB of its
    -- anchor for LEVEL_LOCK_STABLE_SEC after LEVEL_LOCK_MIN_SEC. Once locked
    -- the gain is never raised again (see the cut-only branch below); RMS
    -- measurement continues. The lock times count seconds of measured audio
    -- (windows above the noise floor), not run time: a silent or faint
    -- lead-in must not use up the time the loop needs to reach the target.
    local measured = level_total_valid_sec
    if level_locked then
        -- nothing to decide here
    elseif measured >= LEVEL_LOCK_MAX_SEC - 1e-9 then
        lock_leveling(now, string.format(
            "LEVEL_LOCKED: t=%.3f measured=%.1f reason=max gain=%.2f",
            now, measured, level_current_gain_db))
        return
    elseif measured >= LEVEL_LOCK_MIN_SEC - 1e-9 then
        if level_anchor_gain == nil then
            level_anchor_gain = level_current_gain_db
            level_anchor_time = measured
        elseif math.abs(level_current_gain_db - level_anchor_gain) <= LEVEL_LOCK_DITHER_DB then
            if measured - level_anchor_time >= LEVEL_LOCK_STABLE_SEC - 1e-9 then
                lock_leveling(now, string.format(
                    "LEVEL_LOCKED: t=%.3f measured=%.1f reason=stable gain=%.2f anchor=%.2f",
                    now, measured, level_current_gain_db, level_anchor_gain))
                return
            end
        else
            level_anchor_gain = level_current_gain_db
            level_anchor_time = measured
        end
    end
    if level_last_adj_sec < 0 then
        level_last_adj_sec = 0
    end
    if level_total_valid_sec < LEVEL_START_DELAY then
        return
    end
    if now - level_last_adj_sec < LEVEL_REEVAL_INT - 1e-9 then
        return
    end
    local rms_db = compute_recent_rms_db()
    if rms_db == -math.huge then
        return
    end
    -- never boost silence or the digital noise floor: hold instead
    if rms_db <= LEVEL_NOISE_FLOOR + 1e-9 then
        level_last_adj_sec = now
        return
    end
    -- The samples seen by the lua hook are taken before m_master_gain is
    -- applied (sound.cpp hands the speaker buffers to the hook, master_gain
    -- is only multiplied in at the output stage), so the measurement never
    -- reflects our own volume changes. The loop therefore predicts the
    -- *output* level as baseline + applied gain + measured source level.
    -- Using the raw measurement instead would leave the loop open and walk
    -- the gain in one direction until it hit a limit.
    local effective_db = level_baseline_vol + level_current_gain_db + rms_db

    -- Highest gain allowed: the configured maximum and the sample peak
    -- (baseline + gain + peak <= headroom). The peak only limits a boost: a
    -- source that clips without any gain is not cut for it, so the limit
    -- never falls below 0 dB.
    local ceiling = LEVEL_MAX_GAIN_DB
    if peak_sample > 0 then
        local by_peak = LEVEL_HEADROOM_DB - linear_to_db(peak_sample)
            - level_baseline_vol
        if by_peak < 0 then
            by_peak = 0
        end
        if by_peak < ceiling then
            ceiling = by_peak
        end
    end

    local wanted
    if level_locked then
        if effective_db > level_post_lock_max_db then
            level_post_lock_max_db = effective_db
        end
        -- cut only: the frozen gain stays unless the output is clearly too loud
        local excess = effective_db - (LEVEL_TARGET_DB + LEVEL_LOCK_GUARD_DB)
        wanted = level_current_gain_db
        if excess > 0 then
            wanted = wanted - excess
        end
    else
        wanted = level_current_gain_db + (LEVEL_TARGET_DB - effective_db)
    end
    -- a gain above the ceiling comes down too (later peak, also when locked)
    if wanted > ceiling then
        wanted = ceiling
    end
    -- runaway floor
    if wanted < LEVEL_MIN_GAIN_DB then
        wanted = LEVEL_MIN_GAIN_DB
    end

    local step = wanted - level_current_gain_db
    if step > LEVEL_RAMP_UP_DB_PER_ADJ then
        step = LEVEL_RAMP_UP_DB_PER_ADJ
    elseif step < -LEVEL_RAMP_DB_PER_ADJ then
        step = -LEVEL_RAMP_DB_PER_ADJ
    end
    if level_locked and step > 0 then
        step = 0
    end

    if math.abs(step) > 1e-6 then
        local old_gain = level_current_gain_db
        apply_gain(old_gain + step)
        if level_locked then
            level_locked_cut_db = level_locked_cut_db + (old_gain - level_current_gain_db)
        end
        -- eff_db is the predicted output before the step, out_db after it
        -- (the music info shows out_db)
        log("INFO", string.format(
            "LEVEL_ADJ: t=%.3f rms_db=%.2f eff_db=%.2f out_db=%.2f%s gain %.2f->%.2f",
            now, rms_db, effective_db,
            effective_db + (level_current_gain_db - old_gain),
            gain_state_fields(level_current_gain_db, level_locked and "locked" or "auto"),
            old_gain, level_current_gain_db))
    end
    level_last_adj_sec = now
end

-- Best-effort log output; socket failures disable further socket writes.
-- Only the final sequence passes `final` and may use LOG_FINAL_RESERVE.
function log(level, text, final)
    -- keep room for the drop counter so it survives truncation
    local suffix = ""
    if log_dropped > 0 then
        suffix = string.format(" dropped_messages=%d", log_dropped)
    end
    local msg = sanitize(text, LOG_MAX_TEXT - #suffix) .. suffix

    -- stdout is the fallback when the control socket is unreachable, and an
    -- optional mirror when LOG_TO_STDOUT is set
    if LOG_TO_STDOUT or not log_socket_ok or socket == nil then
        print(level .. ": " .. msg)
    end

    if not log_socket_ok or socket == nil then
        return
    end

    local frame = "LOG|" .. level .. "|" .. msg .. "\n"
    local limit = LOG_MAX_TOTAL_BYTES
    if not final then
        limit = limit - LOG_FINAL_RESERVE
    end
    if log_bytes_sent + #frame > limit then
        log_dropped = log_dropped + 1
        return
    end

    -- write() returns the byte count when it reports one, or nothing at all;
    -- a short count means the stream would be corrupted, so treat it as broken
    local ok, written = pcall(socket.write, socket, frame)

    if not ok or (type(written) == "number" and written < #frame) then
        -- fail fast, no retries: a broken socket must not cost playback time
        log_socket_ok = false
        log_dropped = log_dropped + 1
        return
    end

    log_dropped = 0
    log_bytes_sent = log_bytes_sent + #frame
end

--
-- seconds_to_run lookup
--
-- MAME owns the authoritative limit (Python passes -seconds_to_run), so it is
-- read back through the Lua API instead of being sent over the socket:
--   manager.machine.options      -> emu_options (userdata)
--   .entries                     -> { name -> core_options::entry }
--   .entries["seconds_to_run"]:value() -> integer (option type is INTEGER)
-- Accessing it as manager.machine.options.seconds_to_run returns nil.
-- Any failure just disables the pre-exit trigger: playback must not change.
local function read_seconds_to_run()
    local ok, value = pcall(function()
        return manager.machine.options.entries["seconds_to_run"]:value()
    end)

    if ok and type(value) == "number" then
        -- sanitize before it reaches string.format("%d"): reject NaN, +-inf
        -- and anything without a 32-bit integer representation
        local floored = math.floor(value)
        if floored == floored and floored > -2147483648 and floored < 2147483648 then
            return floored
        end
    end

    log("WARN", "PRE_EXIT: seconds_to_run unavailable, pre-exit logging disabled")
    return 0
end

--
-- Control socket
--
-- Flags must be 3 = OPEN_FLAG_READ|OPEN_FLAG_WRITE. Adding OPEN_FLAG_CREATE
-- makes create_socket() take the bind()+listen() branch instead of connect(),
-- so MAME would try to listen on a port the Python peer already owns.
--
-- Opened before the first log call so no startup diagnostic is lost.
--
-- The autoboot script runs again after the initial machine reset. The mixer
-- device object cannot carry the connection: on MAME 0.289 any new field on it
-- is refused with "sol: cannot set (new_index) into this object", so the open
-- connection is kept in a global instead. The lua state survives the
-- re-execution, so the second run reuses the same socket (verified: globals
-- set by the first execution are still there in the second one).
--
local socket_reused = false

if VGMPLAY_SOCKET then
    socket = VGMPLAY_SOCKET
    socket_reused = true
    log_socket_ok = true
else
    local socket_obj = emu.file("", 3)
    local configured_port = os.getenv("VGMPLAY_PORT")
    -- fallback for a start by hand: Python always passes the port its
    -- listener is bound to (setting vgm_port) as VGMPLAY_PORT
    local socket_port = "22713"
    local err

    if configured_port ~= nil then
        local port_number
        if configured_port:match("^%d+$") then
            local significant_port = configured_port:gsub("^0+", "")
            if #significant_port <= 5 then
                port_number = tonumber(significant_port)
            end
        end
        if not port_number or port_number < 1 or port_number > 65535 then
            err = "Invalid VGMPLAY_PORT: " .. configured_port
        else
            socket_port = tostring(port_number)
        end
    end

    -- open() returns nil on success, or the error message as a string
    if not err then
        err = socket_obj:open("socket.127.0.0.1:" .. socket_port)
    end

    if err then
        log("WARN", "SOCKET FAILED: " .. tostring(err))
        socket = nil
        log_socket_ok = false
    else
        socket = socket_obj
        VGMPLAY_SOCKET = socket_obj
        log_socket_ok = true
    end
end

-- diagnostics only: a missing field must not end the script
local machine_phase = "?"
pcall(function()
    machine_phase = manager.machine.phase
end)

log("INFO", string.format(
    "SCRIPT START: time=%.6f phase=%s gamename=%s",
    emu.time(),
    tostring(machine_phase),
    emu.gamename()
))

if log_socket_ok then
    log("INFO", (socket_reused and "Reusing socket " or "Socket connected to ")
        .. tostring(socket:filename()))
end

--
-- Mixer setup
--
-- An uncaught error in an autoboot script is fatal for MAME ("Fatal error:
-- Error running autoboot script", exit code 3), so every API that only newer
-- MAME versions have is probed, never assumed.
--
-- The sound hook API (manager.machine.sounds, <device>.hook,
-- emu.register_sound_update) came with the sound system of MAME 0.278. Without
-- it the script runs in legacy mode: the VGM plays and the control socket
-- works (exit, final frames), only the level measurement and the leveling
-- are off. sound.volume does not exist there either; every access to it is
-- wrapped in pcall.
--
-- The autoboot script is re-executed on every machine reset, so the mixer
-- device doubles as the per-machine state store (mixer.hook is reset to
-- false by the device_sound_interface constructor). Legacy mode has no such
-- device and keeps the marker in a global.
--
local mixer = nil
pcall(function()
    mixer = manager.machine.sounds[":mixer"]
end)

local has_sound_hook = mixer ~= nil and emu.register_sound_update ~= nil

if has_sound_hook then
    if mixer.hook then
        log("INFO", "SKIP: already initialised for this machine")
        return
    end
    mixer.hook = true
else
    if VGMPLAY_LEGACY_INIT then
        log("INFO", "SKIP: already initialised for this machine")
        return
    end
    VGMPLAY_LEGACY_INIT = true
    log("WARN", "LEGACY: no sound hook API (MAME < 0.278), playing without "
        .. "level measurement and leveling")
end

--
-- Dynamic leveling baseline: the start volume this session levels around.
-- manager.machine.sound.volume is dB (luaengine.cpp: linear_to_db/db_to_linear).
-- MAME persists the final volume into cfg/vgmplay.cfg as master_volume, so a
-- run without an explicit -volume inherits whatever the previous run left
-- behind. An explicit "-volume N" on the command line overrides the cfg and
-- keeps the start deterministic - the log line below shows what was used.
--
pcall(function()
    level_baseline_vol = manager.machine.sound.volume or 0
end)
if level_baseline_vol == nil then
    -- no sound.volume (old MAME): the read raised, level around 0 dB
    level_baseline_vol = 0
end
log("INFO", string.format(
    "LEVEL_BASELINE: start_volume_db=%.2f target_db=%.1f max_gain_db=%.1f ramp_db=%.1f ramp_up_db=%.1f",
    level_baseline_vol, LEVEL_TARGET_DB, LEVEL_MAX_GAIN_DB, LEVEL_RAMP_DB_PER_ADJ,
    LEVEL_RAMP_UP_DB_PER_ADJ
))

--
-- Initial gain-down: apply a fixed attenuation right at playback start so
-- loud content never starts hot while leveling gathers its first RMS windows.
-- Purely additive on the baseline volume; the sound hook samples before
-- master gain, so the RMS data is unaffected.
--
if has_sound_hook then
    apply_gain(LEVEL_INITIAL_GAIN_DB)
    log("INFO", string.format(
        "LEVEL_INITIAL: t=%.3f gain_db=%.2f baseline_db=%.2f start_delay=%.1f state=auto",
        emu.time(), level_current_gain_db, level_baseline_vol, LEVEL_START_DELAY
    ))
end

--
-- seconds_to_run pre-exit plan (initialised once per machine)
--
-- The limit is a whole number of emulated seconds (Python passes
-- vgm_header.mame_seconds_to_run: rounded up, at least 1).
--   0              -> MAME has no run limit, trigger disabled
--   N - MARGIN     -> normal case (N >= 3, e.g. 10 -> 9.0, 90 -> 89.0)
--   N * 0.5        -> fallback when N <= MARGIN (N = 1 -> 0.5, N = 2 -> 1.0)
-- Nothing here shortens or extends playback: it only schedules the final log
-- frames, MAME still terminates on its own -seconds_to_run limit.
--
preexit_seconds = read_seconds_to_run()

if preexit_seconds > 0 then
    preexit_at = math.max(preexit_seconds - PREEXIT_MARGIN, preexit_seconds * 0.5)
else
    preexit_at = 0
end

log("DEBUG", string.format(
    "PRE_EXIT_PLAN: seconds_to_run=%d now=%.3f trigger=%.3f margin=%.2f",
    preexit_seconds, emu.time(), preexit_at, PREEXIT_MARGIN
))

--
-- Fade-out plan (see the fade-out configuration)
--
-- Needs MAME's run limit and sound.volume (MAME >= 0.278). The fade never
-- takes more than half of the run.
--
local function plan_fade_out()
    local configured = os.getenv("VGMPLAY_FADE_SECONDS")
    if configured == nil or configured == "" then
        return
    end
    local seconds = tonumber(configured)
    if seconds == nil or seconds <= 0 or seconds > FADE_MAX_SECONDS then
        log("WARN", "FADE_OUT: invalid VGMPLAY_FADE_SECONDS: " .. configured)
        return
    end
    if preexit_seconds <= 0 then
        log("DEBUG", "FADE_OUT: no seconds_to_run limit, fade-out disabled")
        return
    end
    local readable = pcall(function()
        return manager.machine.sound.volume + 0
    end)
    if not readable then
        log("DEBUG", "FADE_OUT: no sound.volume, fade-out disabled")
        return
    end
    fade_len = math.min(seconds, preexit_seconds * 0.5)
    fade_start_at = preexit_seconds - fade_len
    log("DEBUG", string.format(
        "FADE_OUT_PLAN: start=%.3f len=%.2f floor_db=%.1f",
        fade_start_at, fade_len, FADE_FLOOR_DB))
end

plan_fade_out()

-- One step of the fade, called from the periodic callback (once per frame).
local fade_end_logged = false  -- FADE_OUT_END is logged once
local function update_fade_out(now)
    if fade_len <= 0 or now < fade_start_at then
        return
    end
    if fade_base_vol == nil then
        local ok = pcall(function()
            fade_base_vol = manager.machine.sound.volume + 0
        end)
        if not ok or fade_base_vol == nil then
            fade_len = 0
            return
        end
        log("DEBUG", string.format(
            "FADE_OUT_START: t=%.3f volume_db=%.2f", now, fade_base_vol))
    end
    local progress = (now - fade_start_at) / fade_len
    local volume = FADE_MUTE_DB
    if progress < 1 then
        volume = fade_base_vol + FADE_FLOOR_DB * progress
        if volume < FADE_MUTE_DB then
            volume = FADE_MUTE_DB
        end
    elseif not fade_end_logged then
        fade_end_logged = true
        log("DEBUG", string.format(
            "FADE_OUT_END: t=%.3f volume_db=%.2f", now, volume))
    end
    pcall(function()
        manager.machine.sound.volume = volume
    end)
end

--
-- Final statistics, exactly once per playback.
--
-- Emitted either by the seconds_to_run pre-exit trigger (periodic callback)
-- or by exit_now() on a socket/user exit, whoever gets there first. It only
-- writes log frames: no socket close, no exiting flag, no mixer hook change
-- and no manager.machine:exit() - the pre-exit path must leave MAME running
-- so its own -seconds_to_run handling performs the termination.
--
local function emit_final_logs(reason)
    if VGMPLAY_FINAL_LOGS_SENT then
        return
    end
    VGMPLAY_FINAL_LOGS_SENT = true

    local now = emu.time()

    local avg_rms = 0
    if total_energy_samples > 0 then
        avg_rms = math.sqrt(total_energy_sum / total_energy_samples)
    end

    -- dBFS, -inf for silence
    local avg_dbfs = linear_to_db(avg_rms)
    local peak_dbfs = linear_to_db(peak_energy)

    local avg_dbfs_str = (avg_dbfs == -math.huge) and "-inf" or string.format("%.2f", avg_dbfs)
    local peak_dbfs_str = (peak_dbfs == -math.huge) and "-inf" or string.format("%.2f", peak_dbfs)

    -- Music-only average (review M9): avg_* above keeps every window so it
    -- stays comparable with the earlier analyses.
    local music_rms = 0
    if music_energy_samples > 0 then
        music_rms = math.sqrt(music_energy_sum / music_energy_samples)
    end
    local music_dbfs = linear_to_db(music_rms)
    local music_dbfs_str = (music_dbfs == -math.huge) and "-inf" or string.format("%.2f", music_dbfs)

    -- Locked-phase diagnostics (review M2); empty / -inf without a lock.
    local lock_t_str = level_lock_time and string.format("%.3f", level_lock_time) or ""
    local lock_gain_str = level_lock_gain and string.format("%.2f", level_lock_gain) or ""
    local post_lock_max_str = (level_post_lock_max_db == -math.huge) and "-inf"
        or string.format("%.2f", level_post_lock_max_db)
    local peak_db = linear_to_db(peak_sample)
    local peak_db_str = (peak_db == -math.huge) and "-inf" or string.format("%.2f", peak_db)

    -- Final RMS_STATS closes the statistics sequence. INFO (not DEBUG) so the
    -- final sequence survives with debug logging switched off.
    log("INFO", string.format(
        "RMS_STATS: t=%.3f fingerprint=%.3f avg_rms_so_far=%.6f peak_rms=%.6f windows=%d silence_dips=%d"
            .. " lock_t=%s lock_gain=%s post_lock_max_db=%s locked_cut_db=%.2f periodic=%d peak_db=%s",
        now, diag_last_rms,
        total_energy_samples > 0 and math.sqrt(total_energy_sum / total_energy_samples) or 0,
        peak_energy,
        fingerprint_count,
        silence_dips,
        lock_t_str, lock_gain_str, post_lock_max_str, level_locked_cut_db, periodic_calls,
        peak_db_str
    ), true)

    log("INFO", string.format(
        "VGM_VOLUME file=\"%s\" avg_rms=%.6f avg_dbfs=%s peak_rms=%.6f peak_dbfs=%s samples=%d fingerprint_windows=%d"
            .. " music_rms=%.6f music_dbfs=%s music_windows=%d",
        emu.gamename(),
        avg_rms,
        avg_dbfs_str,
        peak_energy,
        peak_dbfs_str,
        total_energy_samples,
        fingerprint_count,
        music_rms,
        music_dbfs_str,
        music_windows
    ), true)

    log("INFO", string.format(
        "EXIT_NOW: %s (t=%.3f, rms=%.6f, avg_rms=%.6f, peak_rms=%.6f)",
        reason, now, diag_last_rms, avg_rms, peak_energy
    ), true)

    -- Do not restore the baseline here: this runs before MAME's own termination
    -- and would snap the volume up during playback, fighting any fade-out.
    -- MAME persists volume in cfg; Python's non-zero -volume pins the next run
    -- instead of relying on that saved value.
end

--
-- Single exit path for every termination condition.
--
local function exit_now(reason)
    if exiting then
        return
    end
    exiting = true

    if has_sound_hook then
        mixer.hook = false
    end

    -- Final stats/logs first - a no-op when the seconds_to_run pre-exit
    -- trigger already emitted them - then close, then quit MAME.
    emit_final_logs(reason)

    -- Log first, close second: a closed socket cannot deliver the final frames.
    -- Python reads what is already buffered before it shuts the connection down.
    if socket ~= nil then
        local closing = socket
        socket = nil  -- nothing may write after this point, even on error
        log_socket_ok = false
        VGMPLAY_SOCKET = nil
        pcall(closing.close, closing)  -- a failed close must not block the exit
    end

    manager.machine:exit()
end

--
-- Command handling
--
-- Manual volume change by the user. It switches the leveling off for the rest
-- of the track; without sound.volume (MAME before 0.278) nothing changes and
-- the leveling stays on. The frame carries out_db for the music info.
local function change_volume(step_db, name)
    local ok, volume = pcall(function()
        manager.machine.sound.volume = manager.machine.sound.volume + step_db
        return manager.machine.sound.volume
    end)
    if not ok or type(volume) ~= "number" then
        log("WARN", "VGM VOLUME " .. name .. " failed")
        return
    end
    level_manual_override = true
    local gain_fields = ""
    if level_baseline_vol then
        gain_fields = gain_state_fields(volume - level_baseline_vol, "manual")
    end
    log("INFO", string.format("VGM VOLUME %s: volume=%.2f", name, volume)
        .. out_db_field() .. gain_fields)
end

local function handle_command(line)
    line = line:gsub("\r$", "")
    line = line:gsub("^%s+", "")
    line = line:gsub("%s+$", "")

    if line == "" then
        return
    end

    if line == "exit" then
        exit_now("EXIT on socket command")
    elseif line == "volume_up" then
        change_volume(1, "UP")
    elseif line == "volume_down" then
        change_volume(-1, "DOWN")
    else
        log("WARN", "Unknown command: " .. line)
    end
end

local function process_socket_input(data)
    rx = rx .. data

    if #rx > RX_MAX_BYTES then
        log("WARN", "Socket input overflow, discarding buffer")
        rx = ""
        return
    end

    while true do
        local nl = rx:find("\n", 1, true)
        if not nl then
            break
        end
        local line = rx:sub(1, nl - 1)
        rx = rx:sub(nl + 1)
        handle_command(line)
    end
end

local function poll_socket()
    if exiting or socket == nil then
        return
    end

    local data = socket:read(4096)

    if #data == 0 then
        return
    end

    process_socket_input(data)
end

--
-- Socket poll
--
-- Commands only: the log direction is written by log() and never read here.
--
emu.register_periodic(function()
    periodic_calls = periodic_calls + 1
    -- seconds_to_run pre-exit trigger: emit the final statistics slightly
    -- before MAME reaches its own -seconds_to_run limit (MAME checks the
    -- limit only after the periodic callbacks of this same frame). It never
    -- closes the socket or touches `exiting`/the machine - it only writes
    -- the final log frames, and VGMPLAY_FINAL_LOGS_SENT keeps it to one run.
    if not exiting then
        update_fade_out(emu.time())
    end

    if not VGMPLAY_FINAL_LOGS_SENT and preexit_at > 0 then
        local now = emu.time()
        if now >= preexit_at then
            log("DEBUG", string.format(
                "PRE_EXIT_TRIGGER: planned=%.3f actual=%.3f str=%d",
                preexit_at, now, preexit_seconds
            ))
            emit_final_logs(string.format("PRE_EXIT seconds_to_run=%d", preexit_seconds))
        end
    end

    poll_socket()
end)

--
-- Sound callback - measures audio level
--
-- Sound callback / fingerprint state
local fingerprint_start = nil
local fingerprint_sum = 0
local fingerprint_samples = 0

local silence_start = nil
local silence_flat = false      -- the dip began with a frozen (flat, non-zero) buffer
local fingerprint_flat = true   -- every callback of the current window was flat

-- Returns the RMS over all channels and whether the buffer is flat (every
-- channel holds one constant value).
local function calculate_callback_rms(channels)
    local sum = 0
    local count = 0
    local flat = true

    for _, buffer in pairs(channels) do
        local lo = math.huge
        local hi = -math.huge
        for i = 1, #buffer do
            local v = buffer[i]
            sum = sum + v * v
            count = count + 1
            if v < lo then
                lo = v
            end
            if v > hi then
                hi = v
            end
        end
        if #buffer > 0 then
            if hi - lo > SILENCE_FLAT_EPS then
                flat = false
            end
            local peak = math.max(math.abs(lo), math.abs(hi))
            if peak > peak_sample then
                peak_sample = peak
            end
        end
    end

    if count == 0 then
        return nil
    end

    return math.sqrt(sum / count), flat
end

local function update_silence_detection(rms, flat, now)
    --
    -- SILENCE_SECONDS of unbroken silence (see the configuration above) end
    -- the VGM; any audible callback in between starts the count again.
    --
    if rms >= SILENCE_THRESHOLD and not flat then
        if silence_start and now - silence_start > SILENCE_DIAG_MIN_SEC then
            silence_dips = silence_dips + 1
            if DIAG_SILENCE_LOG and silence_dips <= SILENCE_DIAG_MAX_FRAMES then
                log("DEBUG", string.format(
                    "SILENCE: t=%.3f len=%.2f flat=%s",
                    silence_start, now - silence_start, tostring(silence_flat)))
            elseif DIAG_SILENCE_LOG and silence_dips == SILENCE_DIAG_MAX_FRAMES + 1 then
                log("DEBUG", "SILENCE: further dips not logged")
            end
        end
        silence_start = nil
    elseif not silence_start then
        silence_start = now
        -- frozen mixer: inaudible although the RMS is above the threshold
        silence_flat = flat and rms >= SILENCE_THRESHOLD
    elseif now - silence_start >= SILENCE_SECONDS then
        return now - silence_start
    end

    return nil
end

local function accumulate_fingerprint(rms, now)
    if not fingerprint_start then
        fingerprint_start = now
    end

    fingerprint_sum = fingerprint_sum + rms * rms
    fingerprint_samples = fingerprint_samples + 1

    return now - fingerprint_start >= FINGERPRINT_SECONDS
end

local function calculate_fingerprint_energy(sum, samples)
    if samples > 0 then
        return math.sqrt(sum / samples)
    else
        return 0
    end
end

local function update_audio_statistics(energy)
    total_energy_sum = total_energy_sum + fingerprint_sum
    total_energy_samples = total_energy_samples + fingerprint_samples

    if energy > peak_energy then
        peak_energy = energy
    end

    fingerprint_count = fingerprint_count + 1
end

local function update_level_window(energy, now, duration)
    -- Silence and the noise floor are not measured: a pause or a faint intro
    -- must not pull the rolling level down and trigger a boost.
    if linear_to_db(energy) <= LEVEL_NOISE_FLOOR then
        return false
    end
    table.insert(level_win_energy_list, energy)
    table.insert(level_win_time_list, now)
    -- the real length of the window (it closes on the first callback at or
    -- after FINGERPRINT_SECONDS), so measured seconds keep pace with run time
    level_total_valid_sec = level_total_valid_sec + duration

    local cutoff_roll = now - LEVEL_ROLL_SEC
    while #level_win_time_list > 0 and level_win_time_list[1] < cutoff_roll - 1e-9 do
        table.remove(level_win_time_list, 1)
        table.remove(level_win_energy_list, 1)
    end
    return true
end

if not has_sound_hook then
    log("INFO", "VGMPlay started without volume measurement")
    return
end

emu.register_sound_update(function(samples)
    if exiting then
        return
    end

    local channels = samples[":mixer"]
    if not channels or not channels[1] then
        return
    end

    local rms, flat = calculate_callback_rms(channels)
    if rms == nil then
        return
    end

    diag_last_rms = rms

    local now = emu.time()

    local silence_duration = update_silence_detection(rms, flat, now)
    if silence_duration then
        exit_now(string.format(
            "VGM SILENCE DETECTED: %.2f seconds (flat=%s)",
            silence_duration, tostring(silence_flat)))
        return
    end

    if not flat then
        fingerprint_flat = false
    end

    local fingerprint_complete = accumulate_fingerprint(rms, now)

    if fingerprint_complete then
        local energy = calculate_fingerprint_energy(fingerprint_sum, fingerprint_samples)

        update_audio_statistics(energy)

        -- a frozen buffer is no music: keep it out of the leveling
        if not fingerprint_flat
                and update_level_window(energy, now, now - fingerprint_start) then
            music_energy_sum = music_energy_sum + fingerprint_sum
            music_energy_samples = music_energy_samples + fingerprint_samples
            music_windows = music_windows + 1
        end

        update_leveling()

        fingerprint_start = now
        fingerprint_sum = 0
        fingerprint_samples = 0
        fingerprint_flat = true
    end
end)

log("INFO", "VGMPlay volume measurement started")
log("INFO", string.format("Fingerprint window: %.2fs", FINGERPRINT_SECONDS))
