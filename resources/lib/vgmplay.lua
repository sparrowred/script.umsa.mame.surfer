-- license:BSD-3-Clause
-- copyright-holders: sparrowred

-- VGMPlay driver script.
-- Measures audio levels, controls playback through the socket,
-- and reports playback statistics.
--
-- Playback terminates on:
--   1. "exit" received on the control socket
--   2. configured playback duration reached
--   3. start-of-VGM silence detected

local LOG_TO_STDOUT = false
-- Maximum text bytes per message, one frame stays well below 1 KiB.
local LOG_MAX_TEXT = 480
-- Total log bytes per session. Bounds a blocking write when Python is gone:
-- without this the kernel buffer would fill and could stall emulation.
local LOG_MAX_TOTAL_BYTES = 65536

--
-- Audio measurement configuration
--
local FINGERPRINT_SECONDS = 0.10  -- ~100ms fingerprint window
--
-- Start-of-VGM silence detection configuration
--
-- Armed at t=0 and permanently disarmed by the first audible sample
-- (rms >= SILENCE_THRESHOLD). Only a VGM that never becomes audible is
-- terminated; mid-track and end-of-track silence are ignored on purpose.
local SILENCE_THRESHOLD = 0.001  -- RMS below this counts as silence
local SILENCE_SECONDS = 2.0      -- sustained silence required to exit
local DIAG_SILENCE_LOG = true    -- SILENCE_START / SILENCE_END diagnostics
--
-- Dynamic loudness leveling configuration
--
local LEVEL_INITIAL_GAIN_DB = -2.0 -- immediate attenuation applied at t=0
local LEVEL_TARGET_DB    = -22.0  -- configurable target loudness (dBFS)
local LEVEL_MAX_GAIN_DB  = 1.0   -- configurable maximum positive gain
local LEVEL_HEADROOM_DB  = -1.0   -- peak/headroom safety limit
local LEVEL_NOISE_FLOOR  = -40.0  -- don't boost below noise floor
local LEVEL_MIN_GAIN_DB  = -24.0 -- runaway floor for negative gain
local LEVEL_RAMP_DB_PER_ADJ = 1.0 -- max change per adjustment
local LEVEL_START_DELAY  = 0.5    -- start adjusting after ~0.5s of valid measurements
local LEVEL_REEVAL_INT   = 0.5    -- re-evaluate every ~0.5s
local LEVEL_ROLL_SEC     = 1.5    -- rolling window ~1-2s for decisions

--
-- Leveling cutoff (freeze the gain once converged, never adapt forever)
--
-- Active leveling is frozen automatically: not before LEVEL_LOCK_MIN_SEC,
-- as soon as the gain has stayed within LEVEL_LOCK_DITHER_DB of a stable
-- anchor for LEVEL_LOCK_STABLE_SEC, and always by LEVEL_LOCK_MAX_SEC. After
-- the lock the gain never changes again; RMS measurement continues.
local LEVEL_LOCK_MIN_SEC    = 10.0 -- no freeze before 10s
local LEVEL_LOCK_MAX_SEC    = 15.0 -- hard ceiling: freeze no later than 15s
local LEVEL_LOCK_STABLE_SEC = 3.0  -- gain must be settled for this long
local LEVEL_LOCK_DITHER_DB  = 2.0  -- +/- dither counts as settled


--
-- seconds_to_run pre-exit configuration
--
-- Emulated seconds before MAME's -seconds_to_run limit at which the final
-- statistics are sent. vgmplay has no screens, so the periodic callback runs
-- once per emulated frame (~60 Hz): 1.0s is ~60 frames of slack and MAME only
-- checks its limit on a non-skipped frame after the same callback has run.
-- For short runs the trigger falls back to half of the run (see init below).
local PREEXIT_MARGIN = 1.0

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
local fingerprint_count = 0     -- Number of fingerprint windows completed

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
-- the gain is frozen for the rest of the run. The dither anchor is the gain
-- at which the stability window started.
local level_locked = false
local level_anchor_gain = nil
local level_anchor_time = 0



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
    level_current_gain_db = new_gain_db
    if level_baseline_vol == nil then
        level_baseline_vol = manager.machine.sound.volume or 0
    end
    -- sound.volume is float dB (luaengine.cpp: set_master_gain(db_to_linear(db)));
    -- no rounding - the loop works with fractional gain and would otherwise
    -- limit-cycle around whole dB steps
    local target_vol = level_baseline_vol + level_current_gain_db
    if target_vol < -96 then target_vol = -96 end
    if target_vol > 96 then target_vol = 96 end
    manager.machine.sound.volume = target_vol
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

local function update_leveling()
    -- No gain change may follow the final statistics sequence
    if VGMPLAY_FINAL_LOGS_SENT or level_manual_override then
        return
    end
    local now = emu.time()
    -- Freeze the leveled gain once converged: hard ceiling LEVEL_LOCK_MAX_SEC,
    -- otherwise when the gain has stayed within LEVEL_LOCK_DITHER_DB of its
    -- anchor for LEVEL_LOCK_STABLE_SEC after LEVEL_LOCK_MIN_SEC. Once locked
    -- no further adjustment is ever made; RMS measurement continues.
    if level_locked then
        return
    end
    if now >= LEVEL_LOCK_MAX_SEC then
        level_locked = true
        _dbg_log_level(string.format(
            "LEVEL_LOCKED: t=%.3f reason=max gain=%.2f", now, level_current_gain_db))
        return
    end
    if now >= LEVEL_LOCK_MIN_SEC then
        if level_anchor_gain == nil then
            level_anchor_gain = level_current_gain_db
            level_anchor_time = now
        elseif math.abs(level_current_gain_db - level_anchor_gain) <= LEVEL_LOCK_DITHER_DB then
            if now - level_anchor_time >= LEVEL_LOCK_STABLE_SEC then
                level_locked = true
                _dbg_log_level(string.format(
                    "LEVEL_LOCKED: t=%.3f reason=stable gain=%.2f anchor=%.2f",
                    now, level_current_gain_db, level_anchor_gain))
                return
            end
        else
            level_anchor_gain = level_current_gain_db
            level_anchor_time = now
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
    if level_baseline_vol == nil then
        level_baseline_vol = manager.machine.sound.volume or 0
    end

    -- The samples seen by the lua hook are taken before m_master_gain is
    -- applied (sound.cpp hands the speaker buffers to the hook, master_gain
    -- is only multiplied in at the output stage), so the measurement never
    -- reflects our own volume changes. The loop therefore predicts the
    -- *output* level as baseline + applied gain + measured source level.
    -- Using the raw measurement instead would leave the loop open and walk
    -- the gain in one direction until it hit a limit.
    local effective_db = level_baseline_vol + level_current_gain_db + rms_db
    local delta_db = LEVEL_TARGET_DB - effective_db

    local step = 0
    if delta_db > LEVEL_RAMP_DB_PER_ADJ then
        step = LEVEL_RAMP_DB_PER_ADJ
    elseif delta_db < -LEVEL_RAMP_DB_PER_ADJ then
        step = -LEVEL_RAMP_DB_PER_ADJ
    else
        step = delta_db
    end
    if math.abs(step) < 1e-6 then
        level_last_adj_sec = now
        return
    end

    local proposed = level_current_gain_db + step
    if proposed > LEVEL_MAX_GAIN_DB then
        proposed = LEVEL_MAX_GAIN_DB
    end
    -- peak/headroom safety: baseline + gain + observed peak <= headroom
    if peak_energy > 0 then
        local gain_max_by_peak = LEVEL_HEADROOM_DB - linear_to_db(peak_energy)
            - level_baseline_vol
        if proposed > gain_max_by_peak then
            proposed = gain_max_by_peak
        end
    end
    -- runaway floor
    if proposed < LEVEL_MIN_GAIN_DB then
        proposed = LEVEL_MIN_GAIN_DB
    end

    local old_gain = level_current_gain_db
    if math.abs(proposed - old_gain) > 1e-9 then
        level_current_gain_db = proposed
        apply_gain(level_current_gain_db)
        _dbg_log_level(string.format(
            "LEVEL_ADJ: t=%.3f rms_db=%.2f eff_db=%.2f gain %.2f->%.2f",
            now, rms_db, effective_db, old_gain, level_current_gain_db))
    end
    level_last_adj_sec = now
end

-- Best-effort log output; socket failures disable further socket writes.
local function log(level, text)
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

    if log_bytes_sent >= LOG_MAX_TOTAL_BYTES then
        log_dropped = log_dropped + 1
        return
    end

    local frame = "LOG|" .. level .. "|" .. msg .. "\n"
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

-- LEVEL_ADJ diagnostics go through the same log path (socket first, stdout
-- fallback). It is global and assigned here because `log` is a local defined
-- above; a local defined earlier could not see it.
function _dbg_log_level(text)
    log("INFO", text)
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
-- Mixer setup
--
-- The autoboot script is re-executed on every machine reset, so the mixer
-- device doubles as the per-machine state store (mixer.hook is reset to
-- false by the device_sound_interface constructor).
--

local mixer = manager.machine.sounds[":mixer"]

if not mixer then
    log("ERROR", ":mixer sound device not found")
    return
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
    local socket_port = "1234"
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

log("INFO", string.format(
    "SCRIPT START: time=%.6f phase=%s gamename=%s",
    emu.time(),
    manager.machine.phase,
    emu.gamename()
))

if log_socket_ok then
    log("INFO", (socket_reused and "Reusing socket " or "Socket connected to ")
        .. tostring(socket:filename()))
end

if mixer.hook then
    log("INFO", "SKIP: already initialised for this machine")
    return
end

mixer.hook = true

--
-- Dynamic leveling baseline: the start volume this session levels around.
-- manager.machine.sound.volume is dB (luaengine.cpp: linear_to_db/db_to_linear).
-- MAME persists the final volume into cfg/vgmplay.cfg as master_volume, so a
-- run without an explicit -volume inherits whatever the previous run left
-- behind. An explicit "-volume N" on the command line overrides the cfg and
-- keeps the start deterministic - the log line below shows what was used.
--
level_baseline_vol = manager.machine.sound.volume or 0
log("INFO", string.format(
    "LEVEL_BASELINE: start_volume_db=%.2f target_db=%.1f max_gain_db=%.1f ramp_db=%.1f",
    level_baseline_vol, LEVEL_TARGET_DB, LEVEL_MAX_GAIN_DB, LEVEL_RAMP_DB_PER_ADJ
))
if level_baseline_vol > 20 then
    log("WARN", string.format(
        "LEVEL_BASELINE: start volume %.2f dB looks inherited from the previous run's cfg, pin the run with -volume",
        level_baseline_vol
    ))
end

--
-- Initial gain-down: apply a fixed attenuation right at playback start so
-- loud content never starts hot while leveling gathers its first RMS windows.
-- Purely additive on the baseline volume; the sound hook samples before
-- master gain, so the RMS data is unaffected.
--
apply_gain(LEVEL_INITIAL_GAIN_DB)
log("INFO", string.format(
    "LEVEL_INITIAL: t=%.3f gain_db=%.2f volume_db=%.2f baseline_db=%.2f start_delay=%.1f",
    emu.time(), level_current_gain_db, manager.machine.sound.volume,
    level_baseline_vol, LEVEL_START_DELAY
))

--
-- seconds_to_run pre-exit plan (initialised once per machine)
--
-- The limit is an integer number of emulated seconds (Python passes int()).
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

    -- Convert to dBFS (20 * log10(rms)), handle zero safely.
    -- MAME builds embed Lua 5.1 to 5.4: math.log10 only exists from 5.2 and
    -- the two argument math.log(x, base) form only from 5.2 too, so fall back
    -- to the single argument division that every version accepts.
    local function log10(x)
        if math.log10 then
            return math.log10(x)
        end
        return math.log(x) / math.log(10)
    end

    local avg_dbfs
    if avg_rms > 0 then
        avg_dbfs = 20 * log10(avg_rms)
    else
        avg_dbfs = -math.huge  -- -inf
    end

    local peak_dbfs
    if peak_energy > 0 then
        peak_dbfs = 20 * log10(peak_energy)
    else
        peak_dbfs = -math.huge
    end

    local avg_dbfs_str = (avg_dbfs == -math.huge) and "-inf" or string.format("%.2f", avg_dbfs)
    local peak_dbfs_str = (peak_dbfs == -math.huge) and "-inf" or string.format("%.2f", peak_dbfs)

    -- Python logs header metadata separately; Lua uses placeholders here.
    local header_modifier = 0  -- Not directly available in Lua without args
    local header_gain = 1.0
    local has_extra_header = false

    -- Final RMS_STATS closes the statistics sequence. INFO (not DEBUG) so the
    -- final sequence survives with debug logging switched off.
    log("INFO", string.format(
        "RMS_STATS: t=%.3f fingerprint=%.3f avg_rms_so_far=%.6f peak_rms=%.6f windows=%d",
        now, diag_last_rms,
        total_energy_samples > 0 and math.sqrt(total_energy_sum / total_energy_samples) or 0,
        peak_energy,
        fingerprint_count
    ))

    log("INFO", string.format(
        "VGM_VOLUME file=\"%s\" header_modifier=%d header_gain=%.6f avg_rms=%.6f avg_dbfs=%s peak_rms=%.6f peak_dbfs=%s samples=%d fingerprint_windows=%d has_extra_header=%s",
        emu.gamename(),
        header_modifier,
        header_gain,
        avg_rms,
        avg_dbfs_str,
        peak_energy,
        peak_dbfs_str,
        total_energy_samples,
        fingerprint_count,
        has_extra_header and "true" or "false"
    ))

    log("INFO", string.format(
        "EXIT_NOW: %s (t=%.3f, rms=%.6f, avg_rms=%.6f, peak_rms=%.6f)",
        reason, now, diag_last_rms, avg_rms, peak_energy
    ))

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

    mixer.hook = false

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
        level_manual_override = true
        manager.machine.sound.volume = manager.machine.sound.volume+1
        log("INFO", "VGM VOLUME UP")
    elseif line == "volume_down" then
        level_manual_override = true
        manager.machine.sound.volume = manager.machine.sound.volume-1
        log("INFO", "VGM VOLUME DOWN")
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
    -- seconds_to_run pre-exit trigger: emit the final statistics slightly
    -- before MAME reaches its own -seconds_to_run limit (MAME checks the
    -- limit only after the periodic callbacks of this same frame). It never
    -- closes the socket or touches `exiting`/the machine - it only writes
    -- the final log frames, and VGMPLAY_FINAL_LOGS_SENT keeps it to one run.
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

-- Silence detection stays disabled after the first audible sample.
local silence_start = nil
local silence_audio_seen = false

local function calculate_callback_rms(channels)
    local sum = 0
    local count = 0

    for _, buffer in pairs(channels) do
        for i = 1, #buffer do
            local v = buffer[i]
            sum = sum + v * v
            count = count + 1
        end
    end

    if count == 0 then
        return nil
    end

    return math.sqrt(sum / count)
end

local function update_silence_detection(rms, now)
    --
    -- Start-of-VGM silence detection: armed at t=0, permanently
    -- disarmed by the first audible sample. Only a VGM that never
    -- becomes audible reaches the exit below; once music has been
    -- heard, silence at any later point is ignored on purpose.
    --
    if rms >= SILENCE_THRESHOLD then
        if silence_start and DIAG_SILENCE_LOG and now - silence_start > 0.2 then
            log("DEBUG", string.format(
                "SILENCE_END: t=%.3f after %.2fs (not silent long enough)",
                now, now - silence_start))
        end
        silence_start = nil
        silence_audio_seen = true
    elseif not silence_audio_seen then
        if not silence_start then
            silence_start = now
            if DIAG_SILENCE_LOG then
                log("DEBUG", string.format(
                    "SILENCE_START: t=%.3f rms=%.6f", now, rms))
            end
        elseif now - silence_start >= SILENCE_SECONDS then
            return now - silence_start
        end
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

local function update_level_window(energy, now)
    table.insert(level_win_energy_list, energy)
    table.insert(level_win_time_list, now)
    level_total_valid_sec = level_total_valid_sec + FINGERPRINT_SECONDS

    local cutoff_roll = now - LEVEL_ROLL_SEC
    while #level_win_time_list > 0 and level_win_time_list[1] < cutoff_roll - 1e-9 do
        table.remove(level_win_time_list, 1)
        table.remove(level_win_energy_list, 1)
    end
end

emu.register_sound_update(function(samples)
    if exiting then
        return
    end

    local channels = samples[":mixer"]
    if not channels or not channels[1] then
        return
    end

    local rms = calculate_callback_rms(channels)
    if rms == nil then
        return
    end

    diag_last_rms = rms

    local now = emu.time()

    local silence_duration = update_silence_detection(rms, now)
    if silence_duration then
        exit_now(string.format(
            "VGM SILENCE DETECTED: %.2f seconds",
            silence_duration))
        return
    end

    local fingerprint_complete = accumulate_fingerprint(rms, now)

    if fingerprint_complete then
        local energy = calculate_fingerprint_energy(fingerprint_sum, fingerprint_samples)

        update_audio_statistics(energy)

        update_level_window(energy, now)

        update_leveling()

        fingerprint_start = now
        fingerprint_sum = 0
        fingerprint_samples = 0
    end
end)

log("INFO", "VGMPlay volume measurement started")
log("INFO", string.format("Fingerprint window: %.2fs", FINGERPRINT_SECONDS))
