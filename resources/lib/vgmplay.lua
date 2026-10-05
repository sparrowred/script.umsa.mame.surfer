-- license:BSD-3-Clause
-- copyright-holders: sparrowred

-- VGMPlay driver script: audio volume measurement with socket control.
-- Silence/loop/stuck-buffer detectors removed - playback duration is header-driven.
-- Lua measures actual audio level and logs at exit.
--
-- Termination conditions:
--   1. "exit" received on the control socket
--   2. -seconds_to_run N timeout (N set by Python based on VGM header)
--
-- Logs at exit: VGM_VOLUME with header metadata and actual RMS measurements.

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
local DIAG_RMS_LOG = true
local diag_last_rms = 0

--
-- Audio measurement configuration
--
local FINGERPRINT_SECONDS = 0.10  -- ~100ms fingerprint window

-- Maximum bytes of unparsed socket input to keep before discarding.
local RX_MAX_BYTES = 4096

--
-- Mixer setup
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
local socket = nil

-- Volume measurement accumulators
local total_energy_sum = 0      -- Sum of (rms^2) across all fingerprint windows
local total_energy_samples = 0  -- Total fingerprint samples (sum of fingerprint_samples per window)
local peak_energy = 0           -- Peak RMS observed in any fingerprint window
local fingerprint_count = 0     -- Number of fingerprint windows completed

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

    -- Calculate final average RMS from accumulated energy
    local avg_rms = 0
    if total_energy_samples > 0 then
        avg_rms = math.sqrt(total_energy_sum / total_energy_samples)
    end

    -- Convert to dBFS (20 * log10(rms)), handle zero safely
    -- Use math.log(x, 10) for Lua 5.1 compatibility (math.log10 added in 5.2)
    local function log10(x)
        return math.log(x, 10)
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

    -- Format -inf nicely for logging
    local avg_dbfs_str = (avg_dbfs == -math.huge) and "-inf" or string.format("%.2f", avg_dbfs)
    local peak_dbfs_str = (peak_dbfs == -math.huge) and "-inf" or string.format("%.2f", peak_dbfs)

    -- Header volume metadata (set by Python via initial log, but we include what we can)
    -- Note: Python logs header metadata separately in "UMSA VGM PLAN" line
    -- We include placeholder values here; Python post-processing can correlate
    local header_modifier = 0  -- Not directly available in Lua without args
    local header_gain = 1.0
    local has_extra_header = false

    print(string.format(
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

    print(string.format(
        "EXIT_NOW: %s (t=%.3f, rms=%.6f, avg_rms=%.6f, peak_rms=%.6f)",
        reason, emu.time(), diag_last_rms, avg_rms, peak_energy
    ))

    manager.machine:exit()
end

--
-- Control socket
--
local socket_obj = emu.file("", 3)

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
emu.register_periodic(function()
    if exiting or socket == nil then
        return
    end

    local data = socket:read(4096)

    if #data == 0 then
        return
    end

    rx = rx .. data

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
-- Sound callback - measures audio level
--
local fingerprint_start = nil
local fingerprint_sum = 0
local fingerprint_samples = 0

emu.register_sound_update(function(samples)
    if exiting then
        return
    end

    local channels = samples[":mixer"]
    if not channels or not channels[1] then
        return
    end

    -- Calculate RMS of this sound callback
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

    local now = emu.time()

    -- Build ~100ms audio fingerprint
    if not fingerprint_start then
        fingerprint_start = now
    end

    fingerprint_sum = fingerprint_sum + rms * rms
    fingerprint_samples = fingerprint_samples + 1

    -- Finish fingerprint approximately every 100ms
    if now - fingerprint_start >= FINGERPRINT_SECONDS then
        local energy
        if fingerprint_samples > 0 then
            energy = math.sqrt(fingerprint_sum / fingerprint_samples)
        else
            energy = 0
        end

        -- Accumulate energy for overall average RMS
        -- We accumulate sum of squares (fingerprint_sum) and count
        total_energy_sum = total_energy_sum + fingerprint_sum
        total_energy_samples = total_energy_samples + fingerprint_samples

        -- Track peak energy
        if energy > peak_energy then
            peak_energy = energy
        end

        fingerprint_count = fingerprint_count + 1

        if DIAG_RMS_LOG and fingerprint_count % 50 == 0 then
            print(string.format(
                "RMS_STATS: t=%.3f fingerprint=%.3f avg_rms_so_far=%.6f peak_rms=%.6f windows=%d",
                now, energy,
                total_energy_samples > 0 and math.sqrt(total_energy_sum / total_energy_samples) or 0,
                peak_energy,
                fingerprint_count
            ))
        end

        fingerprint_start = now
        fingerprint_sum = 0
        fingerprint_samples = 0
    end
end)

print("VGMPlay volume measurement started")
print(string.format("Fingerprint window: %.2fs", FINGERPRINT_SECONDS))