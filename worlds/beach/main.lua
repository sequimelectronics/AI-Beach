-- SPDX-License-Identifier: AGPL-3.0-only
-- Copyright (C) 2026 Becky Northaven and the AI-Beach contributors
-- Beach: a long beach for people and small AI agents.
-- Kick balls about on the ball field, climb the dune, build sandcastles that fall if built badly.
--
-- The Pickup / Place / Throw handlers follow the pattern of Clawblox's
-- worlds/mesa-island/main.lua (MIT; see NOTICE.md and LICENSE.clawblox).
--
-- Axes: x = east (the sea is east), z = north (goals at the north and south ends), y = up.

--------------------------------------------------------------------------------
-- CASTLE PLOTS: a keeper can move, add or remove plots here, or switch them off.
-- Pieces can be placed anywhere; a castle only "counts" inside a plot.
--------------------------------------------------------------------------------
local PLOTS = {
    enabled = true,
    half_size = 2.5, -- each plot is a 5 x 5 square
    list = {   -- two north-south columns of four at the Sandcastles (south-west)
        { id = 1, x = -40, z = -20 }, { id = 2, x = -40, z = -30 }, { id = 3, x = -40, z = -40 }, { id = 4, x = -40, z = -50 },
        { id = 5, x = -28, z = -20 }, { id = 6, x = -28, z = -30 }, { id = 7, x = -28, z = -40 }, { id = 8, x = -28, z = -50 },
    },
}

--------------------------------------------------------------------------------
-- REGIONS (10-18, the keeper's island): four corners and a plaza in the middle, each its own
-- place. Agents always know where every region is (the map); they see moving things only
-- within the world's observation radius, and speech is heard within the speaker's region (a
-- shout carries everywhere). The bands between regions (the dune, the paths) are between:
-- only shouts carry there. Keep in step with [[speech.regions]] in world.toml.
--------------------------------------------------------------------------------
local REGIONS = {
    { name = "the Plaza", x = { -12, 12 }, z = { -12, 12 } },
    { name = "the Ball Court", x = { -70, -12 }, z = { 12, 70 } },
    { name = "the Sandcastles", x = { -70, -12 }, z = { -70, -12 } },
    { name = "the Lighthouse", x = { 12, 70 }, z = { 12, 70 } },
    { name = "the Pier", x = { 12, 70 }, z = { -70, -12 } },
}

--------------------------------------------------------------------------------
-- THE ISLAND: a rounded square (half = 80, corners rounded with corner_r) and a few rounded
-- bumps (the lighthouse headland in the north-east, a bulge on the castle coast, one by the
-- pier), with shallow sea all around out to the invisible walls. on_land() below is the one
-- test for "is this sand or sea"; the adapter's map card describes the same shapes.
--------------------------------------------------------------------------------
local ISLAND = {
    half = 55, corner_r = 18, top_y = 0,   -- ~110 across: every area one walk from the Plaza
    bumps = {
        { name = "the headland", x = 48, z = 48, r = 16 },
        { name = "the castle beach", x = -55, z = -24, r = 10 },
        { name = "the pier point", x = 55, z = -18, r = 8 },
    },
    wall = 70,   -- invisible walls at x = +/-70 and z = +/-70, in the shallows
}

local function on_land(x, z)
    local I = ISLAND
    local ax, az = math.abs(x), math.abs(z)
    if ax <= I.half and az <= I.half then
        local inner = I.half - I.corner_r
        local dx, dz = math.max(ax - inner, 0), math.max(az - inner, 0)
        if dx * dx + dz * dz <= I.corner_r * I.corner_r then return true end
    end
    for _, b in ipairs(I.bumps) do
        if (x - b.x) ^ 2 + (z - b.z) ^ 2 <= b.r * b.r then return true end
    end
    return false
end

--------------------------------------------------------------------------------
-- WORLD SETTINGS
--------------------------------------------------------------------------------
local CONFIG = {
    gravity = 35,                 -- a little above Earth at this scale (~28 if a 5-stud character is 1.75 m); mesa uses 10
    spawn_points = {               -- at the Plaza, the middle of the island: every area is one walk away
        { -6, -6 }, { 6, -6 }, { -6, 6 }, { 6, 6 }, { 0, -9 }, { 0, 9 },
    },
    -- The ball court (north-west) runs east-west along the north shore, the sea along its long side
    -- (a hard kick ends in the water: a gentle threat). Goals `line` either side of its middle, at
    -- its east and west ends.
    field = { x = -30, z = 42 },
    goal = { line = 16, half_width = 3, height = 3, return_after = 3 },
    center = Vector3.new(-30, 0, 42),   -- where a scored ball goes back to: the court's middle
    -- The dune between the court and the castles: an uneven ridge of three sand ledges 1.4 high
    -- (a walk climbs 1.0 at most; a running jump about 1.7), two with a second ledge on top.
    -- Walk through the gap at x -32..-27, or round its east end by the Plaza.
    dune = {
        step = 1.4,
        ledges = {
            { name = "DuneWest", x = { -55, -42 }, z = { -4, 4 }, top = { x = { -52, -45 }, z = { -2, 2 } } },
            { name = "DuneMiddle", x = { -43, -32 }, z = { -1, 7 }, top = { x = { -40, -35 }, z = { 2, 6 } } },
            { name = "DuneEast", x = { -27, -17 }, z = { -6, 2 } },
        },
        gaps = { { x = { -32, -27 } }, { x = { -17, -12 } } },
    },
    -- The lifeguard: a ball left outside the Ball Court, untouched and still, for `after` seconds is
    -- picked up and hidden somewhere on the island's sand (in a region, never in the sea, on the dune
    -- or in a plot), with a hint of where. Then it's hide and seek.
    lifeguard = { after = 120 },
    kick = { reach = 3.0, impulse = 20, max_speed = 40, lift = 0.18 },  -- body radius 1 + ball radius 0.6 + walking slack
    pickup_range = 6, place_range = 7, match_radius = 1.5,
    hold_offset = Vector3.new(0, 3.5, 0),
    throw = { max_speed = 10, up = 6 },
    sand_roll_drag = 1.2,         -- 1/s: a rolling ball loses ~70% of its speed per second on sand
    water = { drag = 2.5, wash_after = 3, wash_speed = 4 },
    max_pieces = 80,              -- eight plots
    -- Badges for the day (the Beach gives them; the world only reports what happened):
    -- a goal counts for whoever kicked the ball last, within kick_memory seconds;
    -- a sandcastle is castle_pieces or more resting in a plot; it "stood tall" at
    -- tall_height or more, standing still for stand_s seconds.
    badges = { kick_memory = 10, castle_pieces = 3, tall_height = 4, stand_s = 3, again_s = 600 },
    -- Watching (when the world runs with an AI Beach): people and agents who watch have no
    -- character; their names show at this spot, on a patch of sand off the west coast outside
    -- the walls, where nothing can reach; the world announces each one.
    watch = { name = "the lifeguard chair", x = -77, z = -30 },
}

local BALLS = {
    -- name, kind, diameter, density, friction, elasticity, home x/z, extra drag on sand
    { name = "SoccerBall", kind = "soccer ball", d = 1.2, density = 0.8, friction = 0.6, elasticity = 0.5,
      color = Color3.fromRGB(245, 245, 245), home = { -30, 42 }, sand_drag = 1.2 },
    { name = "Volleyball", kind = "volleyball", d = 1.1, density = 0.3, friction = 0.5, elasticity = 0.85,
      color = Color3.fromRGB(250, 214, 64), home = { -36, 38 }, sand_drag = 1.6 },
    { name = "BeachBall", kind = "beach ball", d = 1.8, density = 0.05, friction = 0.5, elasticity = 0.7,
      color = Color3.fromRGB(235, 80, 90), home = { -24, 46 }, sand_drag = 2.5,
      -- Air resistance stand-in (the engine has none): lift cancels most of gravity,
      -- quadratic drag slows it in flight, and a light breeze nudges it along the beach.
      air = { lift = 0.8, drag = 0.06, breeze = Vector3.new(0, 0, 0.6) } },
}

local PIECES = {
    -- shape -> size and look. Sand pieces are dense, grippy and do not bounce.
    block = { size = Vector3.new(1, 1, 1), color = Color3.fromRGB(222, 196, 140) },
    tower = { size = Vector3.new(1, 2, 1), color = Color3.fromRGB(214, 186, 128) },
    wall = { size = Vector3.new(2, 1, 0.5), color = Color3.fromRGB(230, 205, 150) },
    flag = { size = Vector3.new(0.25, 1.5, 0.25), color = Color3.fromRGB(220, 60, 60) },
}

local RunService = game:GetService("RunService")
local Players = game:GetService("Players")
local AgentInputService = game:GetService("AgentInputService")
local HttpService = game:GetService("HttpService")
local ReplicatedStorage = game:GetService("ReplicatedStorage")
local ServerStorage = game:GetService("ServerStorage")

Workspace.Gravity = CONFIG.gravity

local sandPhysics = PhysicalProperties.new(2.0, 1.2, 0.0, 1.0, 1.0)
local piecePhysics = PhysicalProperties.new(1.6, 1.0, 0.0, 1.0, 1.0)

--------------------------------------------------------------------------------
-- HELPERS
--------------------------------------------------------------------------------
local function child(parent, name)
    return parent:FindFirstChild(name)
end

local function scenery(name, size, pos, props)
    local p = child(Workspace, name) or Instance.new("Part")
    p.Name = name
    p.Size = size
    p.Position = pos
    p.Anchored = true
    for k, v in pairs(props or {}) do
        if k == "Role" then
            p:SetAttribute("RenderRole", v)
        else
            p[k] = v
        end
    end
    p:AddTag("Static")
    p.Parent = Workspace
    return p
end

local announceEvent = child(ReplicatedStorage, "Announce") or Instance.new("RemoteEvent")
announceEvent.Name = "Announce"
announceEvent.Parent = ReplicatedStorage

-- Clawblox has no way for a world script to post into the HTTP chat, so world
-- messages go out as an "Announce" replicated event; observations carry it in
-- recent_events and the renderer shows it as a banner.
local function announce(text)
    print("[announce] " .. text)
    announceEvent:FireAllClients({ text = text, from = "Beach" })
end

-- Events for the Beach's badges for the day. A world script can't reach the network, so they
-- go into this world's own DataStore (the same store the BeachDoor script uses), where the
-- Beach's bridge picks them up. Each names only the join (UserId and the name joined under):
-- the Beach decides who that is. The rows are a ring of 64 keys, so the store never grows.
local eventStore = game:GetService("DataStoreService"):GetDataStore("BeachDoor")
local eventSeq = 0
local lastEvent = {}   -- "kind:UserId" -> os.clock() of the last report
local function inGame(player)
    for _, q in ipairs(Players:GetPlayers()) do
        if q == player then return true end
    end
    return false
end
local function beachEvent(kind, player)
    if not player or not inGame(player) then return end
    local key = kind .. ":" .. tostring(player.UserId)
    local now = os.clock()
    if lastEvent[key] and now - lastEvent[key] < CONFIG.badges.again_s and kind ~= "goal" then return end
    lastEvent[key] = now
    eventSeq = eventSeq + 1
    local row = { seq = eventSeq, kind = kind, user_id = player.UserId, joined_as = player.Name }
    task.spawn(function()
        pcall(function() eventStore:SetAsync("event:" .. tostring(row.seq % 64), row) end)
    end)
end

local state = child(ServerStorage, "BeachState") or Instance.new("Folder")
state.Name = "BeachState"
state.Parent = ServerStorage

--------------------------------------------------------------------------------
-- SCENERY (all tagged Static: it never appears in agent observations)
--------------------------------------------------------------------------------
local I = ISLAND
local sandLook = { Role = "Sand", Color = Color3.fromRGB(236, 214, 160), CustomPhysicalProperties = sandPhysics,
    Material = Enum.Material.Sand }
local function sandBox(name, sx, sz, cx, cz)
    scenery(name, Vector3.new(sx, 4, sz), Vector3.new(cx, I.top_y - 2, cz), sandLook)
end
local function sandDisc(name, cx, cz, r)
    local look = { Shape = Enum.PartType.Cylinder }
    for k, v in pairs(sandLook) do look[k] = v end
    scenery(name, Vector3.new(r * 2, 4, r * 2), Vector3.new(cx, I.top_y - 2, cz), look)
end
-- The island: a cross of two boxes, a disc in each corner (the rounded corners), and the bumps.
local inner = I.half - I.corner_r
sandBox("Sand", I.half * 2, inner * 2, 0, 0)
sandBox("SandNS", inner * 2, I.half * 2, 0, 0)
for _, c in ipairs({ { 1, 1, "NE" }, { -1, 1, "NW" }, { 1, -1, "SE" }, { -1, -1, "SW" } }) do
    sandDisc("SandCorner" .. c[3], c[1] * inner, c[2] * inner, I.corner_r)
end
for i, b in ipairs(I.bumps) do
    sandDisc("SandBump" .. i, b.x, b.z, b.r)
end
-- The shallow sea floor all around sits just under the sand, so a ball rolls in and out freely;
-- out past the walls, open water.
local W = I.wall
scenery("SeaFloor", Vector3.new(W * 2 + 8, 4, W * 2 + 8), Vector3.new(0, I.top_y - 2.05, 0),
    { Role = "SeaFloor", Color = Color3.fromRGB(120, 178, 196), CustomPhysicalProperties = sandPhysics })
for _, o in ipairs({ { "OceanEast", 300, 900, W + 154, 0 }, { "OceanWest", 300, 900, -W - 154, 0 },
                     { "OceanNorth", W * 2 + 8, 300, 0, W + 154 }, { "OceanSouth", W * 2 + 8, 300, 0, -W - 154 } }) do
    scenery(o[1], Vector3.new(o[2], 0.3, o[3]), Vector3.new(o[4], 0.15, o[5]),
        { Role = "Ocean", CanCollide = false, CanQuery = false, CanTouch = false, Transparency = 0.25,
          Color = Color3.fromRGB(52, 140, 190), Material = Enum.Material.Glass })
end

local function wall(name, size, pos)
    scenery(name, size, pos, { Transparency = 1, CanQuery = false, CanTouch = false,
        CustomPhysicalProperties = sandPhysics })
end
local WH = 30
wall("WallEast", Vector3.new(2, WH, W * 2 + 4), Vector3.new(W + 1, WH / 2, 0))
wall("WallWest", Vector3.new(2, WH, W * 2 + 4), Vector3.new(-W - 1, WH / 2, 0))
wall("WallNorth", Vector3.new(W * 2 + 4, WH, 2), Vector3.new(0, WH / 2, W + 1))
wall("WallSouth", Vector3.new(W * 2 + 4, WH, 2), Vector3.new(0, WH / 2, -W - 1))

-- Goals: two poles and a crossbar at each end of the field; the zone behind the line is invisible.
local G = CONFIG.goal
local F = CONFIG.field
local GOALS = {
    { name = "east", sign = 1 },
    { name = "west", sign = -1 },
}
for _, g in ipairs(GOALS) do
    local x = F.x + g.sign * G.line
    local cap = g.name:sub(1, 1):upper() .. g.name:sub(2)
    for _, side in ipairs({ -1, 1 }) do
        scenery(cap .. "GoalPost" .. (side < 0 and "S" or "N"), Vector3.new(0.3, G.height, 0.3),
            Vector3.new(x, G.height / 2, F.z + side * G.half_width),
            { Role = "GoalPost", Color = Color3.fromRGB(250, 250, 250) })
    end
    scenery(cap .. "GoalBar", Vector3.new(0.3, 0.3, G.half_width * 2 + 0.3), Vector3.new(x, G.height, F.z),
        { Role = "GoalPost", Color = Color3.fromRGB(250, 250, 250) })
end

-- The dune: an uneven ridge of sand ledges, some with a second ledge on top. Unlike the scenery
-- above it is NOT tagged Static: agents see it once they're near (it's solid ground to climb, and
-- their adapter needs it to plan a running jump). It isn't a pickup and never moves.
do
    local D = CONFIG.dune
    local function ledge(name, x, z, y0, y1)
        local p = child(Workspace, name) or Instance.new("Part")
        p.Name = name
        p.Size = Vector3.new(x[2] - x[1], y1 - y0, z[2] - z[1])
        p.Position = Vector3.new((x[1] + x[2]) / 2, (y0 + y1) / 2, (z[1] + z[2]) / 2)
        p.Anchored = true
        p.Color = Color3.fromRGB(230, 206, 150)
        p.Material = Enum.Material.Sand
        p.CustomPhysicalProperties = sandPhysics
        p:SetAttribute("RenderRole", "Dune")
        p:SetAttribute("Kind", "dune")
        p.Parent = Workspace
    end
    for _, l in ipairs(D.ledges) do
        ledge(l.name, l.x, l.z, 0, D.step)
        if l.top then ledge(l.name .. "Top", l.top.x, l.top.z, D.step, D.step * 2) end
    end
end

-- Plot markers: thin flat squares you can walk over.
if PLOTS.enabled then
    for _, plot in ipairs(PLOTS.list) do
        scenery("PlotMarker" .. plot.id, Vector3.new(PLOTS.half_size * 2, 0.05, PLOTS.half_size * 2),
            Vector3.new(plot.x, 0.03, plot.z),
            { Role = "PlotMarker", CanCollide = false, CanQuery = false, CanTouch = false,
              Color = Color3.fromRGB(120, 170, 220), Transparency = 0.35 })
    end
end

-- The lifeguard chair: the watch spot. Behind the land wall, off the sand, and nothing in it
-- collides, so a watcher never blocks a ball or a build.
do
    local W = CONFIG.watch
    local white = Color3.fromRGB(250, 248, 240)
    local red = Color3.fromRGB(214, 58, 52)
    local function chairPart(name, size, pos, color)
        scenery(name, size, Vector3.new(W.x + pos[1], pos[2], W.z + pos[3]),
            { Role = "LifeguardChair", Color = color, CanCollide = false, CanQuery = false, CanTouch = false })
    end
    chairPart("WatchDune", Vector3.new(7, 0.6, 9), { 0, -0.1, 0 }, Color3.fromRGB(228, 204, 150))
    for i, leg in ipairs({ { -0.9, -0.8 }, { 0.9, -0.8 }, { -0.9, 0.8 }, { 0.9, 0.8 } }) do
        chairPart("WatchChairLeg" .. i, Vector3.new(0.25, 3.2, 0.25), { leg[1], 1.8, leg[2] }, white)
    end
    for i, y in ipairs({ 1.0, 2.0 }) do
        chairPart("WatchChairRung" .. i, Vector3.new(0.2, 0.15, 1.85), { 0.9, y, 0 }, white)
    end
    chairPart("WatchChairSeat", Vector3.new(2.1, 0.25, 1.9), { 0, 3.4, 0 }, white)
    chairPart("WatchChairBack", Vector3.new(0.25, 1.6, 1.9), { -1.0, 4.3, 0 }, red)
    scenery("WatchSign", Vector3.new(0.15, 1.0, 2.2), Vector3.new(W.x - 1.3, 5.7, W.z),
        { Role = "WatchSign", Color = white, CanCollide = false, CanQuery = false, CanTouch = false })
end

--------------------------------------------------------------------------------
-- MAP INFO for agents: scenery is Static (hidden from observations), so the
-- layout is published once as attributes on a folder that observations include.
--------------------------------------------------------------------------------
local mapInfo = child(Workspace, "BeachMap") or Instance.new("Folder")
mapInfo.Name = "BeachMap"
mapInfo:SetAttribute("Layout", HttpService:JSONEncode({
    world = "beach",
    axes = "x east, z north, y up",
    -- The island's shape (on_land above): sand inside it, shallow sea outside, out to the walls.
    island = { half = I.half, corner_r = I.corner_r, bumps = I.bumps },
    sand = { x = { -I.half, I.half }, z = { -I.half, I.half }, top_y = I.top_y },   -- its bounding box
    walls = { x = { -I.wall, I.wall }, z = { -I.wall, I.wall } },
    goals = {
        { name = "east", line_x = F.x + G.line, z = { F.z - G.half_width, F.z + G.half_width }, height = G.height },
        { name = "west", line_x = F.x - G.line, z = { F.z - G.half_width, F.z + G.half_width }, height = G.height },
    },
    regions = REGIONS,
    dune = { ledge = CONFIG.dune.step, ledges = CONFIG.dune.ledges, gaps = CONFIG.dune.gaps },
    center = { CONFIG.center.X, CONFIG.center.Z },
    centre = { CONFIG.center.X, CONFIG.center.Z }, -- the name before job 12, for older adapters  -- spelling: kept
    plots = PLOTS.enabled and (function()
        local out = {}
        for _, p in ipairs(PLOTS.list) do
            table.insert(out, { id = p.id, x = p.x, z = p.z, half = PLOTS.half_size })
        end
        return out
    end)() or {},
    spawns = CONFIG.spawn_points,
}))
mapInfo.Parent = Workspace

-- Who's watching, for agents (observations include this folder): a JSON list of names.
local watchersInfo = child(Workspace, "Watchers") or Instance.new("Folder")
watchersInfo.Name = "Watchers"
watchersInfo:SetAttribute("Spot", CONFIG.watch.name)
watchersInfo:SetAttribute("Names", "[]")
watchersInfo.Parent = Workspace

local score = child(Workspace, "Score") or Instance.new("Folder")
score.Name = "Score"
if score:GetAttribute("East") == nil then
    score:SetAttribute("East", 0)
    score:SetAttribute("West", 0)
end
score.Parent = Workspace

--------------------------------------------------------------------------------
-- BALLS
--------------------------------------------------------------------------------
local ballInfo = {}   -- part -> config row
local balls = {}

local function setPickup(part, kind, role)
    part:SetAttribute("RenderRole", role)
    part:SetAttribute("Kind", kind)
    part:SetAttribute("IsPickupObject", true)
    part:SetAttribute("IsCarryable", true)
end

local function homeOf(cfg)
    return Vector3.new(cfg.home[1], cfg.d / 2 + 0.05, cfg.home[2])
end

for _, cfg in ipairs(BALLS) do
    local b = child(Workspace, cfg.name)
    if not b then
        b = Instance.new("Part")
        b.Name = cfg.name
        b.Shape = Enum.PartType.Ball
        b.Size = Vector3.new(cfg.d, cfg.d, cfg.d)
        b.Position = homeOf(cfg)
        b.Parent = Workspace
    end
    b.Anchored = false
    b.Color = cfg.color
    b.Material = Enum.Material.SmoothPlastic
    b.CustomPhysicalProperties = PhysicalProperties.new(cfg.density, cfg.friction, cfg.elasticity, 1.0, 1.0)
    setPickup(b, cfg.kind, "Ball")
    b:SetAttribute("IsBall", true)
    ballInfo[b] = cfg
    table.insert(balls, b)
end

--------------------------------------------------------------------------------
-- SAND PIECES
--------------------------------------------------------------------------------
local function pieceCount()
    local n = 0
    for _, inst in ipairs(Workspace:GetChildren()) do
        if inst:GetAttribute("PieceKind") then
            n = n + 1
        end
    end
    return n
end

local function makePiece(shape, position)
    local spec = PIECES[shape]
    local counter = (state:GetAttribute("PieceCounter") or 0) + 1
    state:SetAttribute("PieceCounter", counter)
    local p = Instance.new("Part")
    p.Name = shape:sub(1, 1):upper() .. shape:sub(2) .. "_" .. counter
    p.Size = spec.size
    p.Position = position
    p.Anchored = false
    p.Color = spec.color
    p.Material = Enum.Material.Sand
    p.CustomPhysicalProperties = piecePhysics
    setPickup(p, shape .. " piece", "SandPiece")
    p:SetAttribute("PieceKind", shape)
    p.Parent = Workspace
    return p
end

local function topOf(part)
    local cf = part.CFrame
    local s = part.Size
    local ok, ext = pcall(function()
        return math.abs(cf.RightVector.Y) * s.X / 2 + math.abs(cf.UpVector.Y) * s.Y / 2
            + math.abs(cf.LookVector.Y) * s.Z / 2
    end)
    return part.Position.Y + (ok and ext or s.Y / 2)
end

local pieceRest = {}   -- part -> bottom height when last at rest
local function bottomOf(part)
    return part.Position.Y - (topOf(part) - part.Position.Y)
end

--------------------------------------------------------------------------------
-- PLAYERS
--------------------------------------------------------------------------------
local held = {}        -- player -> part
local placing = {}     -- { part, from, to, t, dur, by }
local placedBy = {}    -- piece -> the player who last put it down
local lastKick = {}    -- ball -> { player, at }
local thrown = {}      -- part -> grace end time

local function hrpOf(player)
    local c = player.Character
    return c and c:FindFirstChild("HumanoidRootPart")
end

local function spawnPoint()
    local i = (state:GetAttribute("NextSpawn") or 0) % #CONFIG.spawn_points + 1
    state:SetAttribute("NextSpawn", i)
    local sp = CONFIG.spawn_points[i]
    return Vector3.new(sp[1], 3, sp[2])
end

local function setupPlayer(player, fresh)
    local c = player.Character
    if not c then
        return
    end
    local hum = c:FindFirstChild("Humanoid")
    if hum then
        hum.WalkSpeed = 16
        hum.JumpPower = 50
    end
    local hrp = c:FindFirstChild("HumanoidRootPart")
    if hrp then
        -- No GLB model ships with this world; the renderer draws a named capsule.
        hrp:SetAttribute("ModelUrl", nil)
        c:SetAttribute("ModelUrl", nil)
        -- Name the character so everyone nearby can be named, even from behind. The name is the
        -- player's Beach name, set by the BeachDoor script once the Beach vouches for the join
        -- (and updated live after a rename); until then, "..." .
        hrp:SetAttribute("PlayerName", player:GetAttribute("BeachName") or "...")
        -- Whose character this is, so a chat line (which names its sender's join) can be matched
        -- to the label even when the speaker is out of view.
        hrp:SetAttribute("PlayerUserId", player.UserId)
        if fresh then
            hrp.Position = spawnPoint()
        end
    end
    player:SetAttribute("LastActionResult", "Ready")
end

local function dropHeld(player)
    local part = held[player]
    if not part then
        return
    end
    held[player] = nil
    part.CanCollide = true
    local hrp = hrpOf(player)
    if hrp then
        part.Position = hrp.Position + Vector3.new(1.5, -1, 0)
    end
end

--------------------------------------------------------------------------------
-- ACTIONS
--------------------------------------------------------------------------------
local function vec(v)
    if type(v) ~= "table" then return nil end
    local x, y, z = tonumber(v[1]), tonumber(v[2]), tonumber(v[3])
    if not x or not y or not z or x ~= x or y ~= y or z ~= z then return nil end
    return Vector3.new(x, y, z)
end

local function result(player, text)
    player:SetAttribute("LastActionResult", text)
end

local function nearestPickup(target, maxDist, exclude)
    local best, bestD = nil, maxDist
    for _, inst in ipairs(Workspace:GetChildren()) do
        if inst:IsA("Part") and inst:GetAttribute("IsPickupObject") and inst ~= exclude then
            local d = (inst.Position - target).Magnitude
            if d <= bestD then
                best, bestD = inst, d
            end
        end
    end
    return best
end

local function isHeld(part)
    for _, p in pairs(held) do
        if p == part then return true end
    end
    return false
end

local function doPickup(player, data)
    if held[player] then return result(player, "PickupFailed:AlreadyHolding") end
    local target = vec(data and data.position)
    if not target then return result(player, "PickupFailed:InvalidPosition") end
    local hrp = hrpOf(player)
    if not hrp or (hrp.Position - target).Magnitude > CONFIG.pickup_range then
        return result(player, "PickupFailed:OutOfRange")
    end
    local part = nearestPickup(target, CONFIG.match_radius)
    if not part or isHeld(part) then return result(player, "PickupFailed:NoObject") end
    held[player] = part
    part.Anchored = false
    part.CanCollide = false
    part.AssemblyLinearVelocity = Vector3.new(0, 0, 0)
    part.AssemblyAngularVelocity = Vector3.new(0, 0, 0)
    part:SetAttribute("InWaterSince", nil)
    result(player, "PickupSuccess")
end

local function rotationFrom(data, part)
    local r = data and data.rotation
    if type(r) == "table" then
        local pitch = tonumber(r.pitch or r[1] or 0) or 0
        local yaw = tonumber(r.yaw or r[2] or 0) or 0
        local roll = tonumber(r.roll or r[3] or 0) or 0
        return CFrame.fromOrientation(math.rad(pitch), math.rad(yaw), math.rad(roll))
    end
    return CFrame.fromOrientation(0, 0, 0) -- upright by default
end

local function occupied(player, part, cf)
    -- Probe slightly smaller than the piece so resting exactly on a surface
    -- (stacking) is not counted as overlapping it.
    local probe = Instance.new("Part")
    probe.Size = part.Size * 0.9
    probe.Shape = part.Shape
    probe.CFrame = cf
    local params = OverlapParams.new()
    params.FilterType = Enum.RaycastFilterType.Exclude
    params.FilterDescendantsInstances = { part, player.Character }
    local hits = Workspace:GetPartsInPart(probe, params)
    probe:Destroy()
    for _, h in ipairs(hits) do
        if h:IsA("Part") and h.CanCollide then return true end
    end
    return false
end

local function doPlace(player, data)
    local part = held[player]
    if not part then return result(player, "PlaceFailed:EmptyHands") end
    local target = vec(data and data.position)
    if not target then return result(player, "PlaceFailed:InvalidPosition") end
    local hrp = hrpOf(player)
    if not hrp or (hrp.Position - target).Magnitude > CONFIG.place_range then
        return result(player, "PlaceFailed:OutOfRange")
    end
    local cf = CFrame.new(target) * rotationFrom(data, part)
    if occupied(player, part, cf) then return result(player, "PlaceFailed:Occupied") end
    held[player] = nil
    part.Anchored = true
    part.CanCollide = false
    table.insert(placing, { part = part, from = part.CFrame, to = cf, t = 0, dur = 0.3, by = player })
    result(player, "PlaceSuccess")
end

local function doThrow(player, data)
    local part = held[player]
    local hrp = hrpOf(player)
    if not part or not hrp then return result(player, "ThrowFailed:EmptyHands") end
    local dir = vec(data and data.direction)
    if not dir or dir.Magnitude < 1e-3 then return result(player, "ThrowFailed:InvalidDirection") end
    dir = dir.Unit
    local speed = math.clamp(tonumber(data.speed) or CONFIG.throw.max_speed, 0, CONFIG.throw.max_speed)
    held[player] = nil
    part.Anchored = false
    part.CanCollide = false
    part.Position = hrp.Position + Vector3.new(0, 2.5, 0) + dir * 1.75
    part.AssemblyLinearVelocity = dir * speed + Vector3.new(0, CONFIG.throw.up, 0)
    thrown[part] = os.clock() + 0.18
    result(player, "ThrowSuccess")
end

local function doKick(player, data)
    local hrp = hrpOf(player)
    if not hrp then return result(player, "KickFailed:NoCharacter") end
    local dir = vec(data and data.direction)
    if not dir then return result(player, "KickFailed:InvalidDirection") end
    local flat = Vector3.new(dir.X, 0, dir.Z)
    if flat.Magnitude < 1e-3 then return result(player, "KickFailed:InvalidDirection") end
    local power = math.clamp(tonumber(data.power) or 0.5, 0, 1)
    -- Nearest ball within reach of your feet (horizontal distance; any height up to your head).
    local best, bestD = nil, CONFIG.kick.reach
    for _, b in ipairs(balls) do
        if b.Parent and not isHeld(b) then
            local d = Vector3.new(b.Position.X - hrp.Position.X, 0, b.Position.Z - hrp.Position.Z).Magnitude
            local dy = b.Position.Y - (hrp.Position.Y - 2.5)
            if d <= bestD and dy > -1 and dy < 4 then
                best, bestD = b, d
            end
        end
    end
    if not best then return result(player, "KickFailed:NoBallInReach") end
    local cfg = ballInfo[best]
    -- Each ball's top kick speed comes from its mass (impulse / mass, capped);
    -- power scales it linearly, so a light kick is light for every ball.
    local topSpeed = math.min(CONFIG.kick.impulse / best:GetMass(), CONFIG.kick.max_speed)
    local speed = power * topSpeed
    local up = math.max(dir.Unit.Y, CONFIG.kick.lift)
    local v = flat.Unit * speed + Vector3.new(0, up * speed, 0)
    best.AssemblyLinearVelocity = v
    best:SetAttribute("InWaterSince", nil)
    player:SetAttribute("LastKicked", best.Name)
    lastKick[best] = { player = player, at = os.clock() }
    result(player, "KickSuccess")
end

local function doMold(player, data)
    if held[player] then return result(player, "MoldFailed:HandsFull") end
    local shape = data and tostring(data.shape or ""):lower()
    if not PIECES[shape] then return result(player, "MoldFailed:UnknownShape") end
    if pieceCount() >= CONFIG.max_pieces then return result(player, "MoldFailed:TooManyPieces") end
    local hrp = hrpOf(player)
    if not hrp then return result(player, "MoldFailed:NoCharacter") end
    local part = makePiece(shape, hrp.Position + CONFIG.hold_offset)
    part.CanCollide = false
    held[player] = part
    player:SetAttribute("LastMolded", part.Name)
    result(player, "MoldSuccess")
end

if AgentInputService then
    AgentInputService.InputReceived:Connect(function(player, kind, data)
        -- Only players the Beach has let in may act (see scripts/ServerScriptService/BeachDoor.lua).
        local door = player:GetAttribute("BeachDoor")
        if door ~= "ok" and door ~= "guest" then
            return result(player, "WaitingForTheBeach")
        end
        local c = player.Character
        local hum = c and c:FindFirstChild("Humanoid")
        if not hum then return end
        if kind == "MoveTo" then
            local p = vec(data and data.position)
            if not p then return result(player, "MoveToFailed:InvalidPosition") end
            hum:MoveTo(p)
        elseif kind == "Stop" then
            hum:CancelMoveTo()
        elseif kind == "Jump" then
            hum.Jump = true
        elseif kind == "Pickup" then
            doPickup(player, data)
        elseif kind == "Place" then
            doPlace(player, data)
        elseif kind == "Throw" then
            doThrow(player, data)
        elseif kind == "Kick" then
            doKick(player, data)
        elseif kind == "Mold" then
            doMold(player, data)
        else
            result(player, "InvalidAction")
        end
    end)
end

--------------------------------------------------------------------------------
-- CASTLES: what is in each plot, how high, and whether something fell
--------------------------------------------------------------------------------
local plotFolders = {}
local plotState = {}
local castles = child(Workspace, "Castles") or Instance.new("Folder")
castles.Name = "Castles"
castles.Parent = Workspace
if PLOTS.enabled then
    for _, plot in ipairs(PLOTS.list) do
        local f = child(castles, "Plot" .. plot.id) or Instance.new("Folder")
        f.Name = "Plot" .. plot.id
        f:SetAttribute("Plot", plot.id)
        f:SetAttribute("Pieces", f:GetAttribute("Pieces") or 0)
        f:SetAttribute("Height", f:GetAttribute("Height") or 0)
        f:SetAttribute("HasFlag", f:GetAttribute("HasFlag") or false)
        f:SetAttribute("Falls", f:GetAttribute("Falls") or 0)
        f.Parent = castles
        plotFolders[plot.id] = f
        plotState[plot.id] = { lastFallAt = -math.huge }
    end
end

local function plotAt(pos)
    if not PLOTS.enabled then return nil end
    for _, plot in ipairs(PLOTS.list) do
        if math.abs(pos.X - plot.x) <= PLOTS.half_size and math.abs(pos.Z - plot.z) <= PLOTS.half_size then
            return plot.id
        end
    end
    return nil
end



local evalTimer = 0
local function evaluatePlots(dt)
    evalTimer = evalTimer + dt
    if evalTimer < 0.25 then return end
    evalTimer = 0
    local per = {}
    for id in pairs(plotFolders) do per[id] = { n = 0, top = 0, flag = false, moving = false, builders = {} } end
    local now = os.clock()
    for _, inst in ipairs(Workspace:GetChildren()) do
        local kind = inst:GetAttribute("PieceKind")
        if kind and not isHeld(inst) and not inst.Anchored then
            local id = plotAt(inst.Position)
            inst:SetAttribute("InPlot", id)
            local speed = inst.AssemblyLinearVelocity.Magnitude
            -- A piece that was resting up high and now rests at least 0.5 lower fell.
            if speed < 0.15 then
                local b = bottomOf(inst)
                local before = pieceRest[inst]
                if before and b < before - 0.5 then
                    local pid = id or plotAt(inst.Position)
                    if pid and now - plotState[pid].lastFallAt > 2 then
                        plotState[pid].lastFallAt = now
                        plotFolders[pid]:SetAttribute("Falls", (plotFolders[pid]:GetAttribute("Falls") or 0) + 1)
                        announce("The sandcastle in plot " .. pid .. " fell down!")
                    end
                end
                pieceRest[inst] = b
            end
            if id then
                local p = per[id]
                p.n = p.n + 1
                if placedBy[inst] then p.builders[placedBy[inst]] = true end
                if kind == "flag" then
                    p.flag = true -- decoration: a flag does not add to the castle's height
                else
                    p.top = math.max(p.top, topOf(inst))
                end
                if speed > 0.3 then p.moving = true end
            end
        elseif kind then
            pieceRest[inst] = nil -- held or being placed: forget its old resting height
        end
    end
    local B = CONFIG.badges
    for id, f in pairs(plotFolders) do
        local p = per[id]
        local height = math.floor(p.top + 0.3)
        f:SetAttribute("Pieces", p.n)
        f:SetAttribute("Height", height)
        f:SetAttribute("HasFlag", p.flag)
        f:SetAttribute("Settled", not p.moving)
        -- Badges: everyone who put a piece of a standing castle down built it.
        local st = plotState[id]
        if p.n >= B.castle_pieces and not p.moving then
            for player in pairs(p.builders) do beachEvent("castle", player) end
        end
        if height >= B.tall_height and not p.moving then
            st.tallSince = st.tallSince or now
            if now - st.tallSince >= B.stand_s then
                for player in pairs(p.builders) do beachEvent("tall_castle", player) end
            end
        else
            st.tallSince = nil
        end
    end
end

--------------------------------------------------------------------------------
-- MAIN LOOP
--------------------------------------------------------------------------------
local goalReturns = {}   -- ball -> time to return to center
local lastZ = {}         -- ball -> its position along the court on the previous tick

--------------------------------------------------------------------------------
-- THE LIFEGUARD (Becky, 10-18): a ball left outside the Ball Court, untouched and still for a while,
-- is picked up and hidden somewhere on the island's sand, with a hint of where. Hide and seek.
--------------------------------------------------------------------------------
local function regionAt(x, z)
    for _, r in ipairs(REGIONS) do
        if x >= r.x[1] and x <= r.x[2] and z >= r.z[1] and z <= r.z[2] then return r.name end
    end
    return nil
end

local function clearSpot(x, z)
    if not on_land(x, z) or plotAt(Vector3.new(x, 0, z)) then return false end
    for _, l in ipairs(CONFIG.dune.ledges) do
        if x >= l.x[1] - 2 and x <= l.x[2] + 2 and z >= l.z[1] - 2 and z <= l.z[2] + 2 then return false end
    end
    return true
end

local ballActive = {}    -- ball -> os.clock() when someone last had it, kicked it, or it last rolled
local ballHidden = {}    -- ball -> true while the lifeguard's hiding place is unfound
local function lifeguard(now)
    local L = CONFIG.lifeguard
    for _, b in ipairs(balls) do
        local pos, cfg = b.Position, ballInfo[b]
        local kicked = lastKick[b] and lastKick[b].at or 0
        if isHeld(b) or kicked > (ballActive[b] or 0) then
            ballHidden[b] = nil   -- found (or touched): it's in play again
        end
        if isHeld(b) or b.AssemblyLinearVelocity.Magnitude > 0.3 or goalReturns[b]
            or regionAt(pos.X, pos.Z) == "the Ball Court" then
            ballActive[b] = now
        end
        local idle = now - math.max(ballActive[b] or now, kicked)
        if idle >= L.after and not ballHidden[b] then
            for _ = 1, 60 do
                local x = math.random() * ISLAND.half * 2 - ISLAND.half
                local z = math.random() * ISLAND.half * 2 - ISLAND.half
                local where = regionAt(x, z)
                if where and where ~= "the Ball Court" and clearSpot(x, z) then
                    local r = cfg.d / 2
                    b.Position = Vector3.new(x, r + 0.05, z)
                    b.AssemblyLinearVelocity = Vector3.new(0, 0, 0)
                    b.AssemblyAngularVelocity = Vector3.new(0, 0, 0)
                    b:SetAttribute("InWaterSince", nil)
                    lastZ[b] = nil
                    announce(string.format("The lifeguard found the %s and left it somewhere around %s.", cfg.kind, where))
                    ballHidden[b] = true   -- it stays there until someone finds it
                    break
                end
            end
            ballActive[b] = now
        end
    end
end

local lifeguardTimer = 0
RunService.Heartbeat:Connect(function(dt)
    local now = os.clock()
    lifeguardTimer = lifeguardTimer + dt
    if lifeguardTimer >= 1 then
        lifeguardTimer = 0
        lifeguard(now)
    end

    for _, player in ipairs(Players:GetPlayers()) do
        local hrp = hrpOf(player)
        if hrp and hrp.Position.Y < -30 then
            hrp.Position = spawnPoint()
            hrp.AssemblyLinearVelocity = Vector3.new(0, 0, 0)
        end
        local part = held[player]
        if part and hrp then
            part.Position = hrp.Position + CONFIG.hold_offset
            part.AssemblyLinearVelocity = Vector3.new(0, 0, 0)
            part.AssemblyAngularVelocity = Vector3.new(0, 0, 0)
        end
    end

    local i = 1
    while i <= #placing do
        local p = placing[i]
        p.t = p.t + dt
        local a = math.min(p.t / p.dur, 1)
        local e = 1 - (1 - a) * (1 - a)
        p.part.CFrame = p.from:Lerp(p.to, e)
        if a >= 1 then
            p.part.Anchored = false
            p.part.CanCollide = true
            p.part.AssemblyLinearVelocity = Vector3.new(0, 0, 0)
            if p.part:GetAttribute("PieceKind") then
                -- Where it was put down counts as its resting height: if it then
                -- topples straight away, that is a fall too.
                pieceRest[p.part] = bottomOf(p.part)
                placedBy[p.part] = p.by
            end
            table.remove(placing, i)
        else
            i = i + 1
        end
    end

    for part, untilT in pairs(thrown) do
        if now >= untilT then
            if part.Parent then part.CanCollide = true end
            thrown[part] = nil
        end
    end

    for _, b in ipairs(balls) do
        local cfg = ballInfo[b]
        if b.Parent and not isHeld(b) then
            local pos = b.Position
            local v = b.AssemblyLinearVelocity
            local r = cfg.d / 2
            local onGround = pos.Y - r < 0.2 and math.abs(v.Y) < 1.0

            -- Goals: the ball crosses the goal line between the posts, under the bar.
            -- (Rolling in from the side, behind the line, does not count.)
            -- (x measured from the court's middle: the goals are at its east and west ends)
            local rel = pos.X - F.x
            local prev = lastZ[b] or rel
            lastZ[b] = rel
            if not goalReturns[b] and math.abs(pos.Z - F.z) < G.half_width and pos.Y < G.height then
                for _, g in ipairs(GOALS) do
                    if rel * g.sign > G.line and prev * g.sign <= G.line then
                        local key = g.name == "east" and "East" or "West"
                        score:SetAttribute(key, (score:GetAttribute(key) or 0) + 1)
                        announce(string.format("Goal at the %s end! (%s)", g.name, cfg.kind))
                        goalReturns[b] = now + G.return_after
                        local k = lastKick[b]
                        if k and now - k.at <= CONFIG.badges.kick_memory then beachEvent("goal", k.player) end
                    end
                end
            end
            if goalReturns[b] and now >= goalReturns[b] then
                goalReturns[b] = nil
                b.Position = Vector3.new(CONFIG.center.X, r + 0.05, CONFIG.center.Z)
                b.AssemblyLinearVelocity = Vector3.new(0, 0, 0)
                b.AssemblyAngularVelocity = Vector3.new(0, 0, 0)
            end

            -- Sea: water slows the ball, and after a few seconds it drifts back to the island.
            -- (Off the island and down at the sea floor; a ball up on the pier isn't in the water.)
            if not on_land(pos.X, pos.Z) and pos.Y - r < 0.5 then
                local since = b:GetAttribute("InWaterSince")
                if not since then
                    b:SetAttribute("InWaterSince", now)
                    since = now
                end
                local k = math.exp(-CONFIG.water.drag * dt)
                v = Vector3.new(v.X * k, v.Y, v.Z * k)
                if now - since > CONFIG.water.wash_after then
                    local home = Vector3.new(-pos.X, 0, -pos.Z)   -- toward the island's middle
                    home = home.Magnitude > 0.01 and home.Unit or Vector3.new(-1, 0, 0)
                    v = Vector3.new(home.X * CONFIG.water.wash_speed, math.max(v.Y, 0), home.Z * CONFIG.water.wash_speed)
                end
                b.AssemblyLinearVelocity = v
            elseif b:GetAttribute("InWaterSince") then
                b:SetAttribute("InWaterSince", nil)
            elseif onGround then
                -- Sand: rolling resistance (the engine has none; see the report).
                local k = math.exp(-(cfg.sand_drag or CONFIG.sand_roll_drag) * dt)
                if v.Magnitude > 0.05 then
                    b.AssemblyLinearVelocity = Vector3.new(v.X * k, v.Y, v.Z * k)
                    b.AssemblyAngularVelocity = b.AssemblyAngularVelocity * k
                end
            end

            -- Beach ball air resistance stand-in.
            if cfg.air then
                local vv = b.AssemblyLinearVelocity
                local lift = Vector3.new(0, cfg.air.lift * CONFIG.gravity * dt, 0)
                local drag = vv * (-cfg.air.drag * vv.Magnitude * dt)
                if drag.Magnitude > vv.Magnitude then drag = -vv end
                local breeze = onGround and Vector3.new(0, 0, 0) or cfg.air.breeze * dt
                if not onGround or vv.Magnitude > 0.2 then
                    b.AssemblyLinearVelocity = vv + lift + drag + breeze
                end
            end

            if pos.Y < -30 then
                b.Position = homeOf(cfg)
                b.AssemblyLinearVelocity = Vector3.new(0, 0, 0)
            end
        end
    end

    -- Sand pieces that fall into the sea dissolve.
    for _, inst in ipairs(Workspace:GetChildren()) do
        if inst:GetAttribute("PieceKind") and inst.Position.Y < 1.5 and not on_land(inst.Position.X, inst.Position.Z)
            and not isHeld(inst) then
            inst:Destroy()
        end
    end

    evaluatePlots(dt)
end)

--------------------------------------------------------------------------------
-- WATCHERS: the Beach's bridge writes who's watching into this world's DataStore (key
-- "watchers"); their names go on the board above the lifeguard chair and in the Watchers
-- folder, and each new one is announced. Nobody watches unseen.
--------------------------------------------------------------------------------
task.spawn(function()
    local watching = {}
    local sign = child(Workspace, "WatchSign")
    while true do
        task.wait(1)
        local ok, w = pcall(function() return eventStore:GetAsync("watchers") end)
        if ok then
            local names = (type(w) == "table" and type(w.names) == "table") and w.names or {}
            local now, list = {}, {}
            for _, n in ipairs(names) do
                if type(n) == "string" and n ~= "" and not now[n] then
                    now[n] = true
                    table.insert(list, n)
                    if not watching[n] then
                        announce(n .. " is watching from " .. CONFIG.watch.name)
                    end
                end
            end
            watching = now
            watchersInfo:SetAttribute("Names", HttpService:JSONEncode(list))
            if sign then sign:SetAttribute("WatchNames", table.concat(list, ", ")) end
        end
    end
end)

--------------------------------------------------------------------------------
-- JOIN / LEAVE
--------------------------------------------------------------------------------
Players.PlayerAdded:Connect(function(player)
    setupPlayer(player, true)
    player.CharacterAdded:Connect(function()
        setupPlayer(player, true)
    end)
end)
Players.PlayerRemoving:Connect(dropHeld)
for _, player in ipairs(Players:GetPlayers()) do
    setupPlayer(player, false)
end

print("=== Beach ===")
