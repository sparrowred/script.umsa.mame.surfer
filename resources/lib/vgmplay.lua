-- license:BSD-3-Clause
-- copyright-holders: sparrowred

-- VGMPlay driver script: silence + loop detection with socket control.
--
-- Termination conditions:
--   1. 2 seconds of silence
--   2. Repeating audio pattern (approximately 3-7 seconds)
--   3. "x" received on the control socket
--
-- Keep using:
--   -seconds_to_run 90
-- as the ultimate safety timeout.

print(
    string.format(
        "SCRIPT START: time=%.6f phase=%s gamename=%s",
        emu.time(),
        manager.machine.phase,
        emu.gamename()
    )
)

--
-- Enhanced diagnostics
--
local DIAG_SILENCE_LOG = true
local DIAG_ENERGY_LOG = false  -- verbose
local diag_last_rms = 0
local diag_last_energy = 0
local diag_loop_check_count = 0
local diag_rms_min = 1e9
local diag_rms_max = 0

--
-- Tunables (silence + loop detection)
--

local SILENCE_THRESHOLD = 0.001
local SILENCE_SECONDS = 2.0

-- Loop detection
local LOOP_MIN_SECONDS = 3.0
local LOOP_MAX_SECONDS = 7.0

-- Audio fingerprint resolution.
-- One fingerprint represents approximately 100 ms.
local FINGERPRINT_SECONDS = 0.10

-- How similar two fingerprints must be.
-- 1.0 = identical
-- 0.0 = unrelated
local LOOP_CORRELATION = 0.92

-- Number of repeated matches required before exiting.
local LOOP_CONFIRMATIONS = 3

-- How much audio must be available before testing.
local LOOP_MIN_HISTORY_SECONDS = 10.0

-- Maximum bytes of unparsed socket input to keep before discarding.
local RX_MAX_BYTES = 4096

--
-- Mixer setup
--
-- The autoboot script is re-executed on every machine reset, and
-- register_function() appends rather than replaces, so an unguarded second
-- run would register every callback twice and run the detector twice per
-- audio update. mixer.hook is readable from Lua and is reset to false in the
-- device_sound_interface constructor, so it doubles as a reliable "this
-- machine is already wired up" sentinel. It also re-arms correctly if a
-- second machine is started within the same MAME process.
--

local mixer = manager.machine.sounds[":mixer"]

if not mixer then
    print("ERROR: :mixer sound device not found")
    return
end

if mixer.hook then
    print("SKIP: already initialised for this machine")
    return
end

mixer.hook = true

--
-- Shared state
--

local exiting = false
local rx = ""
local silence_start = nil
local socket = nil

--
-- Single exit path for every termination condition.
--
local function exit_now(reason)
    if exiting then
        return
    end
    exiting = true

    mixer.hook = false

    if socket ~= nil then
        socket:close()
    end

    print(string.format(
        "EXIT_NOW: %s (t=%.3f, rms=%.6f, min=%.6f, max=%.6f)",
        reason, emu.time(), diag_last_rms, diag_rms_min, diag_rms_max))
    manager.machine:exit()
end

--
-- Control socket
--
-- Flags must be 3 = OPEN_FLAG_READ|OPEN_FLAG_WRITE. Adding
-- OPEN_FLAG_CREATE makes create_socket() take the bind()+listen() branch
-- instead of connect(), so MAME would try to listen on a port the Python
-- peer already owns and open() would fail with "Address already in use".
--

local socket_obj = emu.file("", 3)

-- open() returns nil on success, or the error message as a string
local err = socket_obj:open("socket.127.0.0.1:1234")

if err then
    print("SOCKET FAILED:", err)
    socket = nil
else
    socket = socket_obj
    print("Socket connected to", socket:filename())
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
        print("VGM VOLUME UP (stub)")
    elseif line == "volume_down" then
        print("VGM VOLUME DOWN (stub)")
    else
        print("Unknown command:", line)
    end
end

--
-- Socket poll
--
-- Socket I/O runs here rather than in the sound update: read() is already
-- non-blocking (zero timeout select()), so this cannot stall emulation.
--

emu.register_periodic(function()

    if exiting or socket == nil then
        return
    end

    local data = socket:read(4096)

    if #data == 0 then
        return
    end

    rx = rx .. data

    -- Discard oversized input that never produced a newline
    if #rx > RX_MAX_BYTES then
        print("Socket input overflow, discarding buffer")
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
end)

--
-- Audio fingerprint history
--
-- Each entry:
--   {
--       time = emulation time,
--       energy = average RMS-like energy
--   }
--

local history = {}

local fingerprint_start = nil
local fingerprint_sum = 0
local fingerprint_samples = 0

local loop_matches = 0
local last_loop_check = 0
local loop_reason = ""

--
-- Calculate correlation between two sections of the
-- energy fingerprint history.
--
local function correlation(start_a, start_b, length)

    local sum_a = 0
    local sum_b = 0
    local count = 0

    for i = 0, length - 1 do

        local a = history[start_a + i].energy
        local b = history[start_b + i].energy

        sum_a = sum_a + a
        sum_b = sum_b + b

        count = count + 1
    end

    if count == 0 then
        return 0
    end

    local mean_a = sum_a / count
    local mean_b = sum_b / count

    local numerator = 0
    local denom_a = 0
    local denom_b = 0

    for i = 0, length - 1 do

        local a = history[start_a + i].energy - mean_a
        local b = history[start_b + i].energy - mean_b

        numerator = numerator + a * b
        denom_a = denom_a + a * a
        denom_b = denom_b + b * b
    end

    if denom_a == 0 or denom_b == 0 then
        return 0
    end

    return numerator / math.sqrt(denom_a * denom_b)
end

--
-- Look for a repeating section.
--
local function check_for_loop(now)

    -- Don't bother checking too frequently.
    if now - last_loop_check < 1.0 then
        return false
    end

    last_loop_check = now
    diag_loop_check_count = diag_loop_check_count + 1
    if diag_loop_check_count % 10 == 0 then
        print(string.format(
            "LOOP_CHECK: t=%.3f hist=%d rms=%.6f min=%.6f max=%.6f",
            now, #history, diag_last_rms, diag_rms_min, diag_rms_max))
        diag_rms_min = 1e9
        diag_rms_max = 0
    end

    if #history < LOOP_MIN_HISTORY_SECONDS / FINGERPRINT_SECONDS then
        return false
    end

    --
    -- Test loop periods from 3.0 to 7.0 seconds.
    --
    local best_correlation = 0
    local best_period = 0

    local step = FINGERPRINT_SECONDS

    for period = LOOP_MIN_SECONDS, LOOP_MAX_SECONDS, step do

        local frames = math.floor(period / FINGERPRINT_SECONDS)

        if #history >= frames * 2 then

            local start_old = #history - frames * 2 + 1
            local start_new = #history - frames + 1

            local corr = correlation(
                start_old,
                start_new,
                frames
            )

            if corr > best_correlation then
                best_correlation = corr
                best_period = period
            end
        end
    end

    if best_correlation >= LOOP_CORRELATION then

        loop_matches = loop_matches + 1

        print(string.format(
            "LOOP_CAND: t=%.3f period=%.2fs corr=%.3f matches=%d/%d hist=%d",
            now,
            best_period,
            best_correlation,
            loop_matches,
            LOOP_CONFIRMATIONS,
            #history
        ))


        if loop_matches >= LOOP_CONFIRMATIONS then

            loop_reason = string.format(
                "VGM AUDIO LOOP DETECTED: %.2f seconds, correlation %.3f",
                best_period,
                best_correlation
            )

            return true
        end

    else

        -- A failed check breaks the confirmation sequence.
        if loop_matches > 0 then
            print(string.format(
                "LOOP_RESET: t=%.3f corr=%.3f after %d matches",
                now,
                best_correlation,
                loop_matches
            ))
        end
        loop_matches = 0
    end

    return false
end

--
-- Sound callback
--
emu.register_sound_update(function(samples)

    if exiting then
        return
    end

    local channels = samples[":mixer"]

    if not channels or not channels[1] then
        return
    end


    --
    -- Calculate RMS of this sound callback.
    --
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
        return
    end

    local rms = math.sqrt(sum / count)
    diag_last_rms = rms
    if rms < diag_rms_min then
        diag_rms_min = rms
    end
    if rms > diag_rms_max then
        diag_rms_max = rms
    end

    local now = emu.time()


    --
    -- SILENCE DETECTION
    --
    if rms < SILENCE_THRESHOLD then

        if not silence_start then
            silence_start = now
            if DIAG_SILENCE_LOG then
                print(string.format("SILENCE_START: t=%.3f rms=%.6f", now, rms))
            end
        elseif now - silence_start >= SILENCE_SECONDS then

            exit_now(string.format(
                "VGM SILENCE DETECTED: %.2f seconds",
                now - silence_start
            ))

            return
        end

    else

        if silence_start and DIAG_SILENCE_LOG and now - silence_start > 0.2 then
            print(string.format(
                "SILENCE_END: t=%.3f after %.2fs (not silent long enough)",
                now,
                now - silence_start
            ))
        end
        silence_start = nil
    end


    --
    -- Build 100 ms audio fingerprint.
    --
    if not fingerprint_start then
        fingerprint_start = now
    end

    fingerprint_sum =
        fingerprint_sum + rms * rms

    fingerprint_samples =
        fingerprint_samples + 1


    --
    -- Finish fingerprint approximately every 100 ms.
    --
    if now - fingerprint_start >= FINGERPRINT_SECONDS then

        local energy

        if fingerprint_samples > 0 then
            energy = math.sqrt(
                fingerprint_sum / fingerprint_samples
            )
        else
            energy = 0
        end

        diag_last_energy = energy
        if DIAG_ENERGY_LOG then
            print(string.format("FP: t=%.3f rms=%.6f energy=%.6f hist=%d", now, diag_last_rms, energy, #history))
        end


        table.insert(history, {
            time = now,
            energy = energy
        })


        --
        -- Keep approximately 12 seconds of history.
        --
        while #history > 120 do
            table.remove(history, 1)
        end


        fingerprint_start = now
        fingerprint_sum = 0
        fingerprint_samples = 0


        --
        -- Don't try loop detection while silent.
        --
        if rms >= SILENCE_THRESHOLD then

            if check_for_loop(now) then
                exit_now(loop_reason)
                return
            end
        end
    end

end)


print("VGMPlay silence + loop detector started")
print(string.format(
    "Silence: %.1fs, loop range: %.1f-%.1fs, correlation: %.2f",
    SILENCE_SECONDS,
    LOOP_MIN_SECONDS,
    LOOP_MAX_SECONDS,
    LOOP_CORRELATION
))